#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨份「掩码块后残字」聚合：找出 `████` 紧跟的 1~2 个未掩汉字，过滤结构标签后按份数聚合。

这是 `--verify` 与 `frag_check` 之外的第三道泄漏闸门：专抓「更长变体先匹配 → 真名尾字残留」
以及「掩码块后紧跟第二个姓名」。

用法: python agg_tails.py <病历名清单txt> <输出根目录> <输出tsv>
"""
import os
import re
import sys

BLOCK = r"\u2588{2,}"
# 结构标签类残字（不是姓名）：职称、字段名、科室、时间、文书名
LABEL = re.compile(
    r"^(床心|床血|床号|性别|年龄|住院|姓名|医师|医生|护士|护师|技师|主任|主治|副主|规培|"
    r"日[期间]|时间|第|页|科|室|区|号|品|单|项|结|标|备|床|心|血|资|料|护|理|检|查|验|"
    r"医院|医科|大学|附属|第二|出院|入院|患者|患|院|者|以上|无|否|是|详见|见|科别|病区|"
    r"海泰|南京|系统|软件|电子|病历)$"
)


def main() -> int:
    names_txt, outroot, out_tsv = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    agg = {}
    for n in names:
        p = os.path.join(outroot, n, n + "_脱敏.md")
        if not os.path.isfile(p):
            continue
        text = re.sub(r"\s+", " ", open(p, encoding="utf-8").read())
        for m in re.finditer(BLOCK + r"([\u4e00-\u9fa5]{1,2})", text):
            tail = m.group(1)
            if LABEL.match(tail):
                continue
            agg.setdefault(tail, set()).add(n)
    rows = sorted(agg.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    with open(out_tsv, "w", encoding="utf-8") as f:
        f.write("残字\t份数\t病历\n")
        for t, ds in rows:
            f.write("%s\t%d\t%s\n" % (t, len(ds), ",".join(sorted(ds)[:3])))
    print("agg_tails: %d 种残字 -> %s" % (len(rows), out_tsv))
    for t, ds in rows:
        print("  %-5s %2d 份  %s" % (t, len(ds), sorted(ds)[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
