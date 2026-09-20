#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨病历共用词表：把上一批已脱敏病历的「医护/医院」词表沉淀下来，供同院新批次直接复用。

用法: python build_shared_manual.py <清单txt...> <输出txt> [--drop 词1,词2,...]

规则（同院病历医护高度重叠，复用的收益远大于风险，但必须剔除下列词类）：
- 纯数字（住院号/床号/流水号）——每份病历不同，复用了没意义且可能误伤
- 上一批的**患者姓名及其名部**（跨病人复用无意义；万一撞词会误掩）
- 单字词（如 OCR 截断留下的「玲」）——单字掩码误伤面太大
- 本批已知的**新患者姓名**（用 --drop 传入，避免把「张三」误掩成「李四」的片段）
"""
import re
import sys


def main() -> int:
    args = sys.argv[1:]
    drop = set()
    if "--drop" in args:
        i = args.index("--drop")
        drop = {w.strip() for w in args[i + 1].split(",") if w.strip()}
        args = args[:i]
    out = args[-1]
    srcs = args[:-1]

    pool = {}
    for p in srcs:
        for line in open(p, encoding="utf-8"):
            w = line.strip()
            if not w or re.fullmatch(r"[\d.\s]+", w) or w in drop:
                continue
            if len(w) < 2:          # 单字词弃用
                continue
            pool[w] = pool.get(w, 0) + 1

    with open(out, "w", encoding="utf-8") as f:
        for w in sorted(pool):
            f.write(w + "\n")
    print("build_shared_manual: %d 个文件 -> %d 个共用词（剔除 drop %d 个）-> %s"
          % (len(srcs), len(pool), len(drop), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
