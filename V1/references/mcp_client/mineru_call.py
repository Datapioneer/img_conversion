#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx 图转文 CLI（参数化，复用 mcp_client 库，远程 MinerU API 上传模式）。

用法：
    python mineru_call.py <docx绝对路径> <输出Markdown绝对路径> [--service http://10.20.79.38:8888] [--timeout 1800] [--batch 8]

流程（复刻旧 mineru-mcp 行为）：
1. 本地解包 docx（zip），按文档顺序提取内嵌图片（word/media/*，
   通过 document.xml 中的 r:embed / v:imagedata r:id 顺序确定先后）。
2. 图片分批上传远程 MinerU /file_parse（backend=pipeline，无幻觉 OCR），
   每张图片得到一段 Markdown。
3. 按「# 图片 N」（N 从 1 起）逐图组装最终 Markdown；docx 里若有数字文本
   （非扫描件），以「# 文档文本」小节前置。
4. 无图片的纯文本 docx：整份 docx 直接上传解析。

说明：
- 长超时（默认 1800s）直连远程服务，规避会话内 2 分钟超时。
- 病历 docx 多为扫描图片容器，走图片 OCR 路线；图片中的文字会被完整识别。
"""
import argparse
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_client import (  # noqa: E402
    MINERU_API_URL, DEFAULT_TIMEOUT, RASTER_EXTS, mineru_file_parse,
)

# 单张图片解析失败时的占位符（与旧 mineru-mcp 行为一致）
FAILED_PLACEHOLDER = "*(图片 {n} 解析失败)*"


def extract_docx_parts(docx_path):
    """解包 docx，返回 (数字文本, [(图片名, bytes), ...] 按文档顺序)。"""
    with zipfile.ZipFile(docx_path) as z:
        names = set(z.namelist())
        if "word/document.xml" not in names:
            raise RuntimeError("不是有效的 docx（缺少 word/document.xml）")
        doc_xml = z.read("word/document.xml").decode("utf-8", errors="replace")

        # 数字文本：拼接所有 <w:t> 内容（保留段落分隔）
        paragraphs = re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", doc_xml, flags=re.S)
        text_lines = []
        for p in paragraphs:
            ts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.S)
            line = "".join(ts)
            if line.strip():
                text_lines.append(line)
        digital_text = "\n".join(text_lines)

        # 图片顺序：document.xml 中出现的 r:embed / r:id（含 VML v:imagedata）按先后
        rid_order = re.findall(r'r:(?:embed|id)="(rId\d+)"', doc_xml)

        # 关系映射 rId -> media 路径
        if "word/_rels/document.xml.rels" in names:
            rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8", errors="replace")
        else:
            rels_xml = ""
        rid_to_target = {}
        for m in re.finditer(
                r'<Relationship[^>]*Id="(rId\d+)"[^>]*Type="[^"]*/image"[^>]*Target="([^"]+)"',
                rels_xml):
            rid_to_target[m.group(1)] = m.group(2)
        # 兼容属性顺序不同的情况
        for m in re.finditer(r"<Relationship\b[^>]*/?>", rels_xml):
            tag = m.group(0)
            rid = re.search(r'Id="(rId\d+)"', tag)
            typ = re.search(r'Type="([^"]+)"', tag)
            tgt = re.search(r'Target="([^"]+)"', tag)
            if rid and typ and tgt and typ.group(1).endswith("/image"):
                rid_to_target.setdefault(rid.group(1), tgt.group(1))

        images = []
        seen = set()
        for rid in rid_order:
            target = rid_to_target.get(rid)
            if not target:
                continue  # 非 rId 或非图片关系（超链接等）
            media_path = "word/" + target.lstrip("/") if not target.startswith("word/") else target
            media_path = media_path.replace("word/word/", "word/")
            if media_path not in names or media_path in seen:
                continue
            seen.add(media_path)
            ext = os.path.splitext(media_path)[1].lower()
            if ext not in RASTER_EXTS:
                print(f"[mineru_call] 跳过不支持的图片格式 {media_path}（{ext}）",
                      file=sys.stderr)
                continue
            images.append((os.path.basename(media_path), z.read(media_path)))

    return digital_text, images


def ocr_images(images, batch_size, service, timeout):
    """分批上传图片 OCR，返回与 images 等长的 Markdown 列表（失败为占位符）。"""
    results = [None] * len(images)
    for start in range(0, len(images), batch_size):
        batch = images[start:start + batch_size]
        # 上传名加序号前缀，避免同名不同扩展名互相覆盖结果键
        upload = [(f"{start + i:03d}_{name}", data) for i, (name, data) in enumerate(batch)]
        try:
            md_map = mineru_file_parse(upload, backend="pipeline",
                                       timeout=timeout, service=service)
            for i, (name, _) in enumerate(batch):
                stem = os.path.splitext(f"{start + i:03d}_{name}")[0]
                results[start + i] = (md_map.get(stem) or "").strip()
        except Exception as e:  # noqa: BLE001
            print(f"[mineru_call] 批次 {start // batch_size + 1} 整批失败（{e}），逐张重试...",
                  file=sys.stderr)
            for i, (name, data) in enumerate(batch):
                idx = start + i
                try:
                    md_map = mineru_file_parse(
                        [(f"{idx:03d}_{name}", data)], backend="pipeline",
                        timeout=timeout, service=service)
                    stem = os.path.splitext(f"{idx:03d}_{name}")[0]
                    results[idx] = (md_map.get(stem) or "").strip()
                except Exception as e1:  # noqa: BLE001
                    print(f"[mineru_call] 图片 {idx + 1}（{name}）解析失败: {e1}",
                          file=sys.stderr)
                    results[idx] = FAILED_PLACEHOLDER.format(n=idx + 1)
        print(f"[mineru_call] OCR 进度: {min(start + batch_size, len(images))}/{len(images)}",
              file=sys.stderr)
    return results


def parse_docx(docx_path, service, timeout, batch_size):
    """主流程：docx -> Markdown 文本。"""
    digital_text, images = extract_docx_parts(docx_path)
    print(f"[mineru_call] docx 解包: 数字文本 {len(digital_text)} 字, "
          f"内嵌图片 {len(images)} 张", file=sys.stderr)

    sections = []
    if images:
        mds = ocr_images(images, batch_size, service, timeout)
        for i, md in enumerate(mds):
            if md:
                sections.append(f"# 图片 {i + 1}\n\n{md}")
    else:
        # 无图片：整份 docx 直接上传（数字文档解析，默认 hybrid 后端）
        with open(docx_path, "rb") as f:
            data = f.read()
        try:
            md_map = mineru_file_parse(
                [(os.path.basename(docx_path), data)],
                backend="hybrid-auto-engine", timeout=timeout, service=service)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"整份 docx 解析失败: {e}") from e
        stem = os.path.splitext(os.path.basename(docx_path))[0]
        md = (md_map.get(stem) or next(iter(md_map.values()), "")).strip()
        if md:
            sections.append(md)

    # 数字文本前置（仅当 docx 有图片且仍含非平凡文本时）
    if images and digital_text and len(digital_text.strip()) >= 20:
        sections.insert(0, f"# 文档文本\n\n{digital_text.strip()}")

    return "\n\n".join(sections)


def main():
    ap = argparse.ArgumentParser(description="MinerU docx 图转文（远程 API 上传模式）")
    ap.add_argument("docx", help="docx 绝对路径")
    ap.add_argument("out_md", help="输出 Markdown 绝对路径")
    ap.add_argument("--service", default=MINERU_API_URL,
                    help=f"MinerU API 根地址 (默认 {MINERU_API_URL})")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                    help=f"超时秒数 (默认 {DEFAULT_TIMEOUT})")
    ap.add_argument("--batch", type=int, default=8, help="图片每批上传张数 (默认 8)")
    args = ap.parse_args()

    if not os.path.isfile(args.docx):
        print(f"错误：docx 不存在: {args.docx}", file=sys.stderr)
        sys.exit(1)
    if not args.docx.lower().endswith(".docx"):
        print(f"警告：文件不是 .docx 后缀: {args.docx}", file=sys.stderr)

    print(f"docx         = {args.docx}", file=sys.stderr)
    print(f"MinerU API   = {args.service}", file=sys.stderr)

    md_text = parse_docx(args.docx, args.service, args.timeout, args.batch)

    os.makedirs(os.path.dirname(os.path.abspath(args.out_md)) or ".", exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md_text + "\n")
    print(f"Markdown 已写入: {args.out_md} ({len(md_text)} chars)", file=sys.stderr)


if __name__ == "__main__":
    main()
