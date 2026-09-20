#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 UTF-8 文件名清单（每行一个）物化为可读的 TSV：序号、存在、字节数、完整路径。

用法: python list_docs.py <清单txt> <输出tsv>
"""
import os
import sys


def main() -> int:
    lst, out = sys.argv[1], sys.argv[2]
    names = [l.rstrip("\n") for l in open(lst, encoding="utf-8") if l.strip()]
    n_ok = 0
    total = 0
    with open(out, "w", encoding="utf-8") as f:
        f.write("idx\texists\tbytes\tpath\n")
        for i, p in enumerate(names, 1):
            ex = os.path.isfile(p)
            sz = os.path.getsize(p) if ex else 0
            total += sz
            n_ok += ex
            f.write("%d\t%s\t%d\t%s\n" % (i, "1" if ex else "0", sz, p))
    print("list_docs: %d/%d 存在, 合计 %.1f MB -> %s" % (n_ok, len(names), total / 1048576, out))
    return 0 if n_ok == len(names) else 1


if __name__ == "__main__":
    raise SystemExit(main())
