#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按关键词导出上下文窗口（阶段二核对用）。

用法: python win.py <输入md> <输出txt> <关键词1> [关键词2 ...]
每个关键词最多导出 4 个窗口（前后各 260/300 字）。
"""
import re
import sys


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    kws = sys.argv[3:]
    text = re.sub(r"[ \t]+", " ", open(src, encoding="utf-8").read())
    with open(out, "w", encoding="utf-8") as f:
        for kw in kws:
            f.write("########## %s ##########\n" % kw)
            n = 0
            for m in re.finditer(re.escape(kw), text):
                a, b = max(0, m.start() - 260), min(len(text), m.end() + 300)
                f.write("----\n%s\n" % text[a:b].replace("\n", " ⏎ "))
                n += 1
                if n >= 4:
                    break
            if n == 0:
                f.write("(无命中)\n")
    print("ok -> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
