#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批次交付清单：为每份病历列出产物、字节数与验收结论，输出 Markdown 索引。

用法: python delivery_index.py <病历名清单txt> <输出根目录> <索引md>
"""
import os
import re
import sys

FILES = ("_图转文.md", "_补全.md", "_补全报告.txt", "敏感词.txt", "敏感词清单.txt",
         "_脱敏.md", "_脱敏.docx", "字段线索.txt", "检验单列表.txt", "检验结果指标.txt",
         "图片层医院名.txt")


def main() -> int:
    names_txt, outroot, out_md = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    rows = []
    tot_md = tot_px = 0
    for n in names:
        d = os.path.join(outroot, n)
        cells = []
        for suf in ("_图转文.md", "_补全.md", "敏感词清单.txt", "_脱敏.md", "_脱敏.docx"):
            p = os.path.join(d, n + suf)
            if suf == "敏感词清单.txt":
                p = os.path.join(d, "敏感词清单.txt")
            cells.append(os.path.getsize(p) if os.path.isfile(p) else 0)
        mdp = os.path.join(d, n + "_脱敏.md")
        pxe = os.path.join(d, n + "_脱敏.docx")
        m = open(mdp, encoding="utf-8").read() if os.path.isfile(mdp) else ""
        tot_md += len(m)
        tot_px += m.count("\u2588")
        words = 0
        wp = os.path.join(d, "敏感词.txt")
        if os.path.isfile(wp):
            words = sum(1 for l in open(wp, encoding="utf-8") if l.strip())
        rows.append((n, cells, len(m), m.count("\u2588"), words))

    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 批次交付清单（353889-619304，28 份）\n\n")
        f.write("输出根目录：`output/<病历名>/`（病历名 = 源 docx 文件名去扩展名）\n\n")
        f.write("| # | 病历名 | 图转文 | 补全 | 词表 | 脱敏md | 脱敏docx | 脱敏字符 | 掩码字符 | 词表词数 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for i, (n, c, ln, px, w) in enumerate(rows, 1):
            f.write("| %d | %s | %s | %s | %s | %s | %s | %d | %d | %d |\n"
                    % (i, n, *["%.1fK" % (x / 1024) if x else "—" for x in c], ln, px, w))
        f.write("\n**合计**：脱敏文本 %s 字符，掩码 %s 个。\n" % (format(tot_md, ","), format(tot_px, ",")))
        f.write("\n每份目录内另有中间产物：`手动词.txt`、`名部词.txt`、`敏感词_基础.txt`、"
                "`图片层医院名.txt`、`字段线索.txt`、`检验单列表.txt`、`检验结果指标.txt`、`<病历名>_可读.md`。\n")
    print("delivery_index: %d 份 -> %s" % (len(rows), out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
