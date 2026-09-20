#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从「检验结果表」（含 `结果值` 表头）里抽取目标指标行，并附该表的归属信息。

用法: python lab_results.py <_脱敏.md> <输出txt> [关键词...]
默认关键词: 脑自然肽N端前体蛋白 / N端前体 / 肌酐 / 胱抑素 / eGFR

每张结果表输出一个块：块头给出该表附近的「单据/申请时间/检验时间/科室」线索，
再列出命中行 `项目 | 英文缩写 | 结果值 | 标志 | 单位`。
"""
import html
import re
import sys

DEFAULT_KW = ["脑自然肽", "N端前体", "肌酐", "胱抑素", "eGFR", "肾小球滤过"]
TAG = re.compile(r"<[^>]+>")


def cells(row_html):
    return [html.unescape(TAG.sub("", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    kws = sys.argv[3:] or DEFAULT_KW
    text = open(src, encoding="utf-8").read()
    blocks = 0
    with open(out, "w", encoding="utf-8") as f:
        for m in re.finditer(r"<table>.*?</table>", text, re.S):
            tbl = m.group(0)
            if "结果值" not in tbl and "英文缩写" not in tbl:
                continue
            rows = re.findall(r"<tr>(.*?)</tr>", tbl, re.S)
            parsed = [cells(r) for r in rows]
            flat = [" ".join(c) for c in parsed]
            if not any(k in " ".join(flat) for k in kws):
                continue
            blocks += 1
            head = text[max(0, m.start() - 400):m.start()]
            head = re.sub(r"\s+", " ", head)[-260:]
            f.write("\n========== 结果表 %d ==========\n" % blocks)
            f.write("表前线索: ...%s\n" % head)
            # 表头行（含「项目/结果值」）+ 命中行
            for c in parsed:
                if not c or all(not x for x in c):
                    continue
                line = " | ".join(c)
                if ("结果值" in line) or any(k in line for k in kws):
                    f.write("  %s\n" % line)
    print("lab_results: %d 张结果表 -> %s" % (blocks, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
