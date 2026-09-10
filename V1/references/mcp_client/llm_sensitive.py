#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敏感词识别 CLI（参数化，复用 mcp_client 库，直连远程 Ollama）。只负责「识别」这一步。

用法：
    python llm_sensitive.py <图转文md> <输出敏感词txt> [--manual <手动词文件>] [--service URL] [--model qwen3:32b]

说明：
- 输入：docx-ocr 产生的图转文 Markdown（旧格式「# 图片 N」分块，或新格式整篇/含「# 文档文本」小节）。
- 内部：① 正则自动提取候选（床号/住院号/手机号/ID/地址）；
  ② 分块调用远程 Ollama（默认 http://10.20.79.38:11434，qwen3:32b）按固定提示词
    识别医院名/人名；③ 与手工补齐词合并。
- 分块策略：优先按「# 图片 N」分块（沿用旧格式），否则按字符数切块（默认 8000 字/块，
  避免超出模型上下文）；每块独立调用，单块失败重试一次后中止任务（防止漏识别导致脱敏不完整）。
- 手工补齐词可放在 `<手工词每行一个>.txt`，供人工补充医院名变体/患者名/住院号等
  检测覆盖不到的项（如 `00697227`、`病床号：603741` 这类 OCR 变体）。
- 本脚本不调用 mask.py；掩码由 desensitize/scripts/mask.py 单独执行，
  以便在补齐后重跑掩码时无需重新调用 LLM。
- 注意：敏感文本会发送到内网 GPU 机器（OLLAMA_URL，默认 10.20.79.38）上的 qwen3:32b，
  不出公司内网。
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import OLLAMA_URL, DEFAULT_TIMEOUT, ollama_chat  # noqa: E402

PROMPT_TEMPLATE = """现有病人的病历数据，请结合上下文提取以下文本中的一切医院名和所有人名(姓名可能重复出现在任何地方，且字符"姓名"之后一定为患者的名字)，并严格按照以下格式返回（不要返回任何额外的信息！！）:
提取的医院名和人名，如果有多个用换行符"\\n"间隔，如无，返回null
例如：坪山人民医院\\n肇庆市第一人民医院\\n张三\\n李四\\n王五"""


def split_by_image(md_text):
    """按「# 图片 N」标题分块；标题前的导言文本也作为独立块返回。"""
    parts = re.split(r"(# 图片 \d+)", md_text)
    result = []
    preamble = parts[0].strip() if parts else ""
    if preamble:
        result.append(("# 文档文本", preamble))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            result.append((title, content))
    return result


def split_by_chars(text, limit):
    """按字符数切块；尽量在段落/换行边界切开，返回 [(标题, 内容), ...]。"""
    if len(text) <= limit:
        return [("全文", text)]
    parts = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            # 在 [end-500, end] 范围内找最后一个换行，避免切碎行
            cut = text.rfind("\n", end - 500, end)
            if cut > start:
                end = cut
        idx += 1
        parts.append((f"片段 {idx}", text[start:end]))
        start = end
    return parts


def auto_extract(md_text):
    """自动提取候选敏感词，返回 (words_set, stats)。"""
    words = set()
    stats = {}

    def add(cat, w):
        if w and len(str(w)) >= 4:
            words.add(str(w))
            stats[cat] = stats.get(cat, 0) + 1

    for m in re.finditer(r"床\s*号[:：\s]*(\d{3,6})", md_text):
        add("bed", m.group(1))
    for m in re.finditer(r"(?:住院号|住院流水号|门诊号|流水号|登记号|就诊号)[:：\s]*(\d{5,12})", md_text):
        add("num", m.group(1))
    for m in re.finditer(r"(?:患者\s*ID|病历号|病案号)[:：\s]*(\d{4,12})", md_text):
        add("id", m.group(1))
    for m in re.finditer(r"1[3-9]\d{9}", md_text):
        add("phone", m.group(0))
    for m in re.finditer(r"(?:常住地址|家庭住址|住址|地址)[:：\s]*([一-龥]{4,30}(?:[村组路街巷号栋室楼单元\d]+)?)", md_text):
        addr = m.group(1).strip()
        if len(addr) >= 6:
            add("addr", addr)
            if "省" in addr:
                add("addr", addr.split("省", 1)[1])
    return words, stats


def group_parts(parts, max_chars):
    """把 (标题, 内容) 块聚合为 LLM 调用批次：单块超长先自切，再按字符预算合并。"""
    refined = []
    for title, content in parts:
        if len(content) > max_chars:
            refined.extend(split_by_chars(content, max_chars))
        else:
            refined.append((title, content))
    batches = []
    cur, cur_len = [], 0
    for title, content in refined:
        add_len = len(title) + len(content) + 2
        if cur and cur_len + add_len > max_chars:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append((title, content))
        cur_len += add_len
    if cur:
        batches.append(cur)
    return batches


def call_llm_batch(batch, model, service, timeout, retries=1):
    """对一个批次调用 Ollama 识别，返回原始返回文本（失败重试一次，仍失败抛异常）。"""
    text = "\n\n".join(f"{t}\n{c}" for t, c in batch)
    prompt = PROMPT_TEMPLATE + "\n\n文本：\n" + text
    last_err = None
    for attempt in range(retries + 1):
        try:
            return ollama_chat(prompt, model=model, timeout=timeout,
                               service=service, num_ctx=16384)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[llm_sensitive] 调用失败（第 {attempt + 1} 次）: {e}", file=sys.stderr)
            time.sleep(3)
    raise RuntimeError(f"Ollama 识别失败（已重试 {retries} 次）: {last_err}")


def main():
    ap = argparse.ArgumentParser(description="识别病历文本中的医院名/人名等敏感词")
    ap.add_argument("md_file", help="图转文 Markdown 路径")
    ap.add_argument("out_txt", help="输出敏感词文件（合并后，原始格式）")
    ap.add_argument("--manual", default=None, help="手工补齐敏感词文件（每行一个，可选）")
    ap.add_argument("--service", default=OLLAMA_URL, help=f"Ollama API 根地址 (默认 {OLLAMA_URL})")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--model", default="qwen3:32b")
    ap.add_argument("--chunk", type=int, default=8000,
                    help="每次 LLM 调用的最大字符数 (默认 8000)")
    args = ap.parse_args()

    with open(args.md_file, encoding="utf-8") as f:
        md_text = f.read()

    parts = split_by_image(md_text)
    if not parts:
        parts = split_by_chars(md_text.strip(), args.chunk)
    print(f"分块: {len(parts)} 块", file=sys.stderr)

    auto_words, stats = auto_extract(md_text)
    print(f"自动提取: {json.dumps(stats, ensure_ascii=False)}", file=sys.stderr)

    batches = group_parts(parts, args.chunk)
    print(f"LLM 调用: {len(batches)} 批（每批 ≤{args.chunk} 字, model={args.model} @ {args.service}）",
          file=sys.stderr)

    llm_words = []
    for i, batch in enumerate(batches, 1):
        t0 = time.time()
        raw = call_llm_batch(batch, args.model, args.service, args.timeout)
        raw = (raw or "").strip().replace("\\n", "\n")
        # 清洗：过滤 null / 空行 / 提示词残留
        for line in raw.splitlines():
            w = line.strip().strip("\"'，,。 ")
            if w and w.lower() != "null":
                llm_words.append(w)
        print(f"批次 {i}/{len(batches)} 完成（{time.time() - t0:.0f}s，"
              f"新增 {len(llm_words)} 词累计）", file=sys.stderr)

    manual = ""
    if args.manual:
        if os.path.isfile(args.manual):
            with open(args.manual, encoding="utf-8") as f:
                manual = f.read().strip()
            print(f"已并入手工词文件: {args.manual}", file=sys.stderr)
        else:
            print(f"警告：手工词文件不存在，跳过: {args.manual}", file=sys.stderr)

    merged = "\n".join(x for x in ["\n".join(llm_words), manual,
                                   "\n".join(sorted(auto_words))] if x)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_txt)) or ".", exist_ok=True)
    with open(args.out_txt, "w", encoding="utf-8") as f:
        f.write(merged + "\n")
    print(f"敏感词(原始)已写入: {args.out_txt}（LLM {len(llm_words)} + 自动 {len(auto_words)}）",
          file=sys.stderr)


if __name__ == "__main__":
    main()
