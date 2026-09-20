#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽取「检验单列表」表格（表头含 `单据` 的 <table>），用于阶段二核对 BNP/肌酐/胱抑素。

用法: python lab_tables.py <_脱敏.md> <输出txt>

每行渲染成 `单据 | 样本 | 检验人 | 检验时间 | 审核人 | 核收时间 | 申请人 | 申请时间`
（表头列序以表格实际为准），按表内原始顺序输出，便于判断「首次」是哪一行。
"""
import html
import re
import sys

TAG = re.compile(r"<[^>]+>")


def cells(row_html):
    return [html.unescape(TAG.sub("", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8").read()
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for m in re.finditer(r"<table>.*?</table>", text, re.S):
            tbl = m.group(0)
            if ">单据<" not in tbl:
                continue
            n += 1
            rows = re.findall(r"<tr>(.*?)</tr>", tbl, re.S)
            # 表格前置说明（单据名称：X）
            lead = text[max(0, m.start() - 200):m.start()]
            hm = re.search(r"单据名称[:：]\s*\S{0,6}", lead)
            f.write("\n========== 表 %d  表头线索: %s ==========\n" % (n, hm.group(0) if hm else "?"))
            for r in rows:
                c = cells(r)
                if not c or all(not x for x in c):
                    continue
                f.write(" | ".join(c) + "\n")
    print("lab_tables: %d 张检验单表 -> %s" % (n, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
