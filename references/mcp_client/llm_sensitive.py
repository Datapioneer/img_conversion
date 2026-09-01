#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敏感词识别 CLI（参数化，复用 mcp_client 库）。只负责「识别」这一步。

用法：
    python llm_sensitive.py <图转文md> <输出敏感词txt> [--manual <手动词文件>] [--service URL] [--model qwen3:32b]

说明：
- 输入：docx-ocr 产生的图转文 Markdown（`# 图片 N` 分块）。
- 内部：① 正则自动提取候选（床号/住院号/手机号/ID/地址）；② 调 llm-mcp
  `identify_sensitive_words_batch` 识别医院名/人名；③ 与手工补齐词合并。
- 手工补齐词可放在 `<手工词每行一个>.txt`，供人工补充医院名变体/患者名/住院号等
  检测覆盖不到的项（如 `00697227`、`病床号：603741` 这类 OCR 变体）。
- 本脚本不调用 mask.py；掩码由 desensitize/scripts/mask.py 单独执行，
  以便在补齐后重跑掩码时无需重新调用 LLM。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import McpSession, LLM_URL, extract_text, DEFAULT_TIMEOUT  # noqa: E402

PROMPT_TEMPLATE = """现有病人的病历数据，请结合上下文提取以下文本中的一切医院名和所有人名(姓名可能重复出现在任何地方，且字符"姓名"之后一定为患者的名字)，并严格按照以下格式返回（不要返回任何额外的信息！！）:
提取的医院名和人名，如果有多个用换行符"\\n"间隔，如无，返回null
例如：坪山人民医院\\n肇庆市第一人民医院\\n张三\\n李四\\n王五"""


def split_by_image(md_text):
    parts = re.split(r"(# 图片 \d+)", md_text)
    result = []
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        result.append((title, content))
    return result


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


def main():
    ap = argparse.ArgumentParser(description="识别病历文本中的医院名/人名等敏感词")
    ap.add_argument("md_file", help="图转文 Markdown 路径")
    ap.add_argument("out_txt", help="输出敏感词文件（合并后，原始格式）")
    ap.add_argument("--manual", default=None, help="手工补齐敏感词文件（每行一个，可选）")
    ap.add_argument("--service", default=LLM_URL, help=f"LLM MCP URL (默认 {LLM_URL})")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--model", default="qwen3:32b")
    ap.add_argument("--chunk", type=int, default=15, help="identify_sensitive_words_batch 的 chunk_size")
    args = ap.parse_args()

    with open(args.md_file, encoding="utf-8") as f:
        md_text = f.read()

    parts = split_by_image(md_text)
    part_texts = [content for _, content in parts if content]
    print(f"分块: {len(parts)} 图, 有效块 {len(part_texts)}", file=sys.stderr)

    auto_words, stats = auto_extract(md_text)
    print(f"自动提取: {json.dumps(stats, ensure_ascii=False)}", file=sys.stderr)

    session = McpSession(args.service, timeout=args.timeout)
    session.initialize()
    print(f"调用 identify_sensitive_words_batch (chunk={args.chunk}, model={args.model})...", file=sys.stderr)
    result = session.call_tool("identify_sensitive_words_batch", {
        "parts": part_texts,
        "chunk_size": args.chunk,
        "prompt_template": PROMPT_TEMPLATE,
        "model": args.model,
        "model_type": "local",
    })
    llm_words_raw = extract_text(result)
    print(f"LLM 返回 {len(llm_words_raw)} 字符原始词", file=sys.stderr)

    manual = ""
    if args.manual:
        if os.path.isfile(args.manual):
            with open(args.manual, encoding="utf-8") as f:
                manual = f.read().strip()
            print(f"已并入手工词文件: {args.manual}", file=sys.stderr)
        else:
            print(f"警告：手工词文件不存在，跳过: {args.manual}", file=sys.stderr)

    merged = "\n".join(x for x in [llm_words_raw.strip(), manual, "\n".join(sorted(auto_words))] if x)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_txt)) or ".", exist_ok=True)
    with open(args.out_txt, "w", encoding="utf-8") as f:
        f.write(merged + "\n")
    print(f"敏感词(原始)已写入: {args.out_txt}", file=sys.stderr)


if __name__ == "__main__":
    main()
