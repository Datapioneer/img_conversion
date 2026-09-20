#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无图片 docx 兜底：把 document.xml 的可见文本导出为 `<病历名>_补全.md`。

用于 `X 无心电图记录.docx` 这类「导出时无任何截图」的空病历——`supplement.py`
因「无内嵌图片」终止，但产物链需要一份 `_补全.md` 才能继续脱敏。

用法: python noimage_fallback.py <docx路径> <输出目录>
输出：<输出目录>/<病历名>_补全.md 与 <病历名>_图转文.md（内容相同）、<病历名>_补全报告.txt
"""
import os
import re
import sys
import zipfile

NS_TXT = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)


def visible_text(docx):
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.split(r"</w:p>", xml)
    out = []
    for p in paras:
        t = "".join(NS_TXT.findall(p))
        t = re.sub(r"&amp;", "&", t).strip()
        if t:
            out.append(t)
    return out


def main() -> int:
    docx, outdir = sys.argv[1], sys.argv[2]
    name = os.path.splitext(os.path.basename(docx))[0]
    os.makedirs(outdir, exist_ok=True)
    lines = visible_text(docx)
    body = "# 文档文本（无图片，直取 docx 文本层）\n\n" + "\n\n".join(lines) + "\n"
    for suffix in ("_图转文.md", "_补全.md"):
        with open(os.path.join(outdir, name + suffix), "w", encoding="utf-8") as f:
            f.write(body)
    with open(os.path.join(outdir, name + "_补全报告.txt"), "w", encoding="utf-8") as f:
        f.write("无内嵌图片，未做图转文；本产物由 docx 文本层直取。\n")
        f.write("可见段落数：%d\n" % len(lines))
        for i, l in enumerate(lines, 1):
            f.write("  %d: %s\n" % (i, l))
    print("noimage_fallback: %s -> %s（%d 段，%d 字符）" % (name, outdir, len(lines), len(body)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
