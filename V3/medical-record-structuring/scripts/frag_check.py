#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""姓名残片检测：脱敏后文本中是否仍含「已识别姓名」的子串（>=2 字）。

思路：若某姓名 W 的某个 2~len(W)-1 长子串 S 仍出现在脱敏文本中，说明掩码被
更长的「串字变体」截断，留下了残片（如 `王天光天光` 先匹配 4 字变体 → 残留 `天光`）。
输出匿名化统计，供补词或加长变体。

用法: python frag_check.py <_脱敏.md> <敏感词.txt>
"""
import re
import sys


def main() -> int:
    md, kw = sys.argv[1], sys.argv[2]
    text = open(md, encoding="utf-8").read()
    words = [w.strip() for w in open(kw, encoding="utf-8") if w.strip()]
    names = [w for w in words if 2 <= len(w) <= 6 and re.fullmatch(r"[\u4e00-\u9fa5]+", w)]
    hits = []
    for w in names:
        for L in range(len(w) - 1, 1, -1):
            for i in range(0, len(w) - L + 1):
                s = w[i:i + L]
                if len(s) >= 2 and s in text:
                    hits.append((s, w))
    uniq = sorted({s for s, _ in hits})
    print("%s: 姓名残片 %d 种 %s" % (md.split("/")[-1], len(uniq), uniq[:20]))
    return 1 if uniq else 0


if __name__ == "__main__":
    raise SystemExit(main())
