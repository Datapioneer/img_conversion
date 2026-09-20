#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""姓名尾部（名）安全网生成器。

动机：EHR/OCR 会稳定地把 3 字姓名掐成 2 字（`郭义龙`→`部义龙`、`吕有凯`→`邑有凯`、
`葛广全`→`葛广`），或被更长的「串字变体」掩码截断后留下名部。逐条枚举变体不可靠，
改用确定性规则：**把词表中每个 3/4 字中文姓名的名部（末 2 字）也加入词表**。
长词优先保证：全名仍按全名掩码，名部只兜底截断/残片。

用法: python name_tail.py <_补全.md> <敏感词.txt> <输出补充词.txt> [--report]
    --report 额外打印「名部出现次数 > 所属全名出现次数」的名部（可能撞到普通词，需人工复核）
"""
import re
import sys

# 名部撞词黑名单（明显不是人名的常用词，人工复核后维护）
TAIL_BLACKLIST = {"朝阳", "和平", "长江", "光明", "建国", "医科", "大学", "附属", "医院"}
# 机构/系统词（不出名部）
ORG_TOKENS = ("医院", "医科", "大学", "附属", "卫生", "保健", "农场", "镇", "村", "省", "市", "县")


def main() -> int:
    md, kw, out = sys.argv[1], sys.argv[2], sys.argv[3]
    report = "--report" in sys.argv
    text = open(md, encoding="utf-8").read()
    words = [w.strip() for w in open(kw, encoding="utf-8") if w.strip()]

    # 只用 3 字全名取名部（末 2 字）：4 字多为「姓名连排」OCR 变体，其名部是噪声。
    names = [w for w in words
             if re.fullmatch(r"[\u4e00-\u9fa5]{3}", w)
             and not any(t in w for t in ORG_TOKENS)]
    tails = {}
    for n in names:
        t = n[-2:]
        tails.setdefault(t, []).append(n)

    collides = []
    for t, owners in tails.items():
        if t in TAIL_BLACKLIST:
            continue
        total = text.count(t)
        owned = sum(text.count(n) for n in owners)
        if total > owned:
            collides.append((t, total, owned, owners))

    with open(out, "w", encoding="utf-8") as f:
        for t in sorted(tails):
            if t in TAIL_BLACKLIST:
                continue
            f.write(t + "\n")

    print("%s: 全名 %d 个 -> 名部 %d 个 -> %s" % (md.split("/")[-1], len(names), len(tails), out))
    if report and collides:
        print("  名部可能撞普通词（出现次数 > 全名次数），需人工复核：")
        for t, total, owned, owners in collides:
            print("    %s 出现 %d 次，全名合计 %d 次（%s）" % (t, total, owned, "/".join(owners)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
