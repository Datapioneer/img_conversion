#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敏感词识别（自包含，不依赖其他技能）。

用法：
    python sensitive.py <输入的图转文md> <输出敏感词txt> [--manual <手动词文件>]
                        [--service http://10.20.79.38:11434] [--model qwen3:32b]
                        [--chunk 8000] [--timeout 1800]

说明：
- 输入：supplement.py 产出的 `_补全.md`（或 `_图转文.md`）。
- 内部三段合并：
    ① 正则自动提取（床号 / 住院号 / 手机号 / ID / 地址）
    ② 分块调远程 Ollama（默认 http://10.20.79.38:11434，qwen3:32b）识别医院名 / 人名
    ③ 并入 --manual 手工补齐词（每行一个）
- 分块策略：优先按「# 图片 N」分块，否则按字符数切块（默认 8000 字/块）。
  单块调用失败重试 1 次，仍失败则抛错中止（防止漏识别导致脱敏不完整）。
- 本脚本只做「识别」，掩码由 mask.py 完成（便于补齐后重跑掩码而无需再调 LLM）。
- 数据流向：敏感文本会发送到内网 GPU 机器（默认 10.20.79.38）上的 qwen3:32b，不出公司内网。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.20.79.38:11434").rstrip("/")
DEFAULT_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "1800"))

PROMPT_TEMPLATE = """现有病人的病历数据，请结合上下文提取以下文本中的一切医院名和所有人名(姓名可能重复出现在任何地方，且字符"姓名"之后一定为患者的名字)，并严格按照以下格式返回（不要返回任何额外的信息！！）:
提取的医院名和人名，如果有多个用换行符"\\n"间隔，如无，返回null
例如：坪山人民医院\\n肇庆市第一人民医院\\n张三\\n李四\\n王五"""


# ---------------------------------------------------------------- Ollama ----
def ollama_chat(prompt, model="qwen3:32b", service=None, timeout=None, num_ctx=None):
    """调用 Ollama /api/chat，返回去噪后的文本（剥离 qwen3 的 thinking）。"""
    base = (service or DEFAULT_OLLAMA_URL).rstrip("/")
    timeout = timeout or DEFAULT_TIMEOUT
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if num_ctx:
        payload["options"]["num_ctx"] = num_ctx
    req = urllib.request.Request(
        f"{base}/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Ollama HTTP {e.code}: {detail}") from e
    content = ((data.get("message") or {}).get("content") or "").strip()
    if "<think>" in content:
        content = content.split("</think>", 1)[-1].strip() if "</think>" in content \
            else content.split("<think>", 1)[-1].strip()
    return content


# ------------------------------------------------------------- 分块 / 提取 ----
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
    """按字符数切块；尽量在换行边界切开，返回 [(标题, 内容), ...]。"""
    if len(text) <= limit:
        return [("全文", text)]
    parts, start, idx = [], 0, 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            cut = text.rfind("\n", end - 500, end)
            if cut > start:
                end = cut
        idx += 1
        parts.append((f"片段 {idx}", text[start:end]))
        start = end
    return parts


def auto_extract(md_text):
    """正则自动提取候选敏感词，返回 (words_set, stats)。"""
    words, stats = set(), {}

    def add(cat, w):
        if w and len(str(w)) >= 4:
            words.add(str(w))
            stats[cat] = stats.get(cat, 0) + 1

    for m in re.finditer(r"床\s*号[:：\s]*(\d{3,6})", md_text):
        add("bed", m.group(1))
    # 「数字+床」无标签格式（如 350949床），EHR 截图常见，原版正则抓不到
    for m in re.finditer(r"(\d{3,6})\s*床", md_text):
        add("bed", m.group(1))
    for m in re.finditer(r"(?:住院号|住院流水号|门诊号|流水号|登记号|就诊号)[:：\s]*(\d{5,12})", md_text):
        add("num", m.group(1))
    # 「(流水号」无标签格式（如 (1225441)）
    for m in re.finditer(r"[（(](\d{5,9})[)）]?", md_text):
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
    """把 (标题, 内容) 聚合为 LLM 批次：单块超长先自切，再按字符预算合并。"""
    refined = []
    for title, content in parts:
        if len(content) > max_chars:
            refined.extend(split_by_chars(content, max_chars))
        else:
            refined.append((title, content))
    batches, cur, cur_len = [], [], 0
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
    """对一个批次调用 Ollama 识别；失败重试，仍失败抛异常。"""
    text = "\n\n".join(f"{t}\n{c}" for t, c in batch)
    prompt = PROMPT_TEMPLATE + "\n\n文本：\n" + text
    last_err = None
    for attempt in range(retries + 1):
        try:
            return ollama_chat(prompt, model=model, service=service,
                               timeout=timeout, num_ctx=16384)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[sensitive] 调用失败（第 {attempt + 1} 次）: {e}", file=sys.stderr)
            time.sleep(3)
    raise RuntimeError(f"Ollama 识别失败（已重试 {retries} 次）: {last_err}")


def main():
    ap = argparse.ArgumentParser(description="识别病历文本中的医院名/人名等敏感词")
    ap.add_argument("md_file", help="输入 Markdown（建议用 _补全.md）")
    ap.add_argument("out_txt", help="输出敏感词文件")
    ap.add_argument("--manual", default=None, help="手工补齐敏感词文件（每行一个，可选）")
    ap.add_argument("--service", default=DEFAULT_OLLAMA_URL)
    ap.add_argument("--model", default="qwen3:32b")
    ap.add_argument("--chunk", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--no-llm", action="store_true",
                    help="跳过 LLM 识别，只用正则+手动词（Ollama 不可用/显存不足时用）")
    args = ap.parse_args()

    with open(args.md_file, encoding="utf-8") as f:
        md_text = f.read()

    parts = split_by_image(md_text) or split_by_chars(md_text.strip(), args.chunk)
    print(f"分块: {len(parts)} 块", file=sys.stderr)

    auto_words, stats = auto_extract(md_text)
    print(f"自动提取: {json.dumps(stats, ensure_ascii=False)}", file=sys.stderr)

    llm_words = []
    if args.no_llm:
        print("已启用 --no-llm：跳过 LLM 识别（仅正则 + 手动词）", file=sys.stderr)
    else:
        batches = group_parts(parts, args.chunk)
        print(f"LLM 调用: {len(batches)} 批（每批 ≤{args.chunk} 字, model={args.model} @ {args.service}）",
              file=sys.stderr)
        for i, batch in enumerate(batches, 1):
            t0 = time.time()
            raw = (call_llm_batch(batch, args.model, args.service, args.timeout) or "")
            raw = raw.strip().replace("\\n", "\n")
            for line in raw.splitlines():
                w = line.strip().strip("\"'，,。 ")
                if w and w.lower() != "null":
                    llm_words.append(w)
            print(f"批次 {i}/{len(batches)} 完成（{time.time() - t0:.0f}s，累计 {len(llm_words)} 词）",
                  file=sys.stderr)

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
