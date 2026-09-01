#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx 图转文 CLI（参数化，复用 mcp_client 库）。

用法：
    python mineru_call.py <宿主机docx绝对路径> <输出Markdown绝对路径> [--service http://localhost:8010/mcp] [--timeout 1800]

示例：
    python mineru_call.py "E:\\shiny_wd\\agent\\.workbuddy\\output\\697227\\697227.docx" "E:\\shiny_wd\\agent\\.workbuddy\\output\\697227\\697227_图转文.md"

说明：
- 只传宿主机路径即可：`to_container_path()` 自动把 `E:\\shiny_wd\\...` 转成容器内 `/ws/...`。
- 长超时（默认 1800s）直连本机 mineru-mcp streamableHttp，规避会话内 2 分钟超时。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import McpSession, to_container_path, extract_text, MINERU_URL, DEFAULT_TIMEOUT  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="MinerU docx 图转文")
    ap.add_argument("docx", help="宿主机 docx 绝对路径")
    ap.add_argument("out_md", help="输出 Markdown 绝对路径")
    ap.add_argument("--service", default=MINERU_URL, help=f"MinerU MCP URL (默认 {MINERU_URL})")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"超时秒数 (默认 {DEFAULT_TIMEOUT})")
    args = ap.parse_args()

    if not os.path.isfile(args.docx):
        print(f"错误：docx 不存在: {args.docx}", file=sys.stderr)
        sys.exit(1)
    if not args.docx.lower().endswith(".docx"):
        print(f"警告：文件不是 .docx 后缀: {args.docx}", file=sys.stderr)

    docx_container = to_container_path(args.docx)
    print(f"docx(宿主机) = {args.docx}", file=sys.stderr)
    print(f"docx(容器)   = {docx_container}", file=sys.stderr)

    session = McpSession(args.service, timeout=args.timeout)
    session.initialize()
    print("已连接，调用 parse_document ...", file=sys.stderr)
    result = session.call_tool("parse_document", {"docx_path": docx_container})
    md_text = extract_text(result)

    os.makedirs(os.path.dirname(os.path.abspath(args.out_md)) or ".", exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md_text)
    print(f"Markdown 已写入: {args.out_md} ({len(md_text)} chars)", file=sys.stderr)


if __name__ == "__main__":
    main()
