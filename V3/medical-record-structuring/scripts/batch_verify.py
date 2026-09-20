#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批次验收汇总：患者名归零 / 词表无死词 / 残留 / 掩码数 / 残片种类（跨份聚合）。

用法: python batch_verify.py <病历名清单txt> <输出根目录> <汇总tsv>
"""
import os
import re
import sys


def framents(masked, words):
    names = [w for w in words if 2 <= len(w) <= 6 and re.fullmatch(r"[\u4e00-\u9fa5]+", w)]
    hits = set()
    for w in names:
        for L in range(len(w) - 1, 1, -1):
            for i in range(0, len(w) - L + 1):
                s = w[i:i + L]
                if len(s) >= 2 and s in masked:
                    hits.add(s)
    return hits


def main() -> int:
    names_txt, outroot, out_tsv = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    sys.path.insert(0, "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts")
    from sensitive import patient_name_from_filepath

    all_frag = {}
    rows = []
    for n in names:
        d = os.path.join(outroot, n)
        comp_p = os.path.join(d, n + "_补全.md")
        mask_p = os.path.join(d, n + "_脱敏.md")
        kw_p = os.path.join(d, "敏感词.txt")
        if not os.path.isfile(mask_p):
            rows.append((n, "-", 0, 0, 0, 0, 0, "缺产物"))
            continue
        comp = open(comp_p, encoding="utf-8").read()
        masked = open(mask_p, encoding="utf-8").read()
        words = [w.strip() for w in open(kw_p, encoding="utf-8") if w.strip()] if os.path.isfile(kw_p) else []
        pn = patient_name_from_filepath(comp_p)
        if pn is None:  # 无图片空病历 → 无姓名可验
            pn_cnt_before = pn_cnt_after = 0
            pn = "(无)"
        else:
            pn_cnt_before = comp.count(pn)
            pn_cnt_after = masked.count(pn)
        dead = sum(1 for w in words if w not in comp)
        resid = sum(1 for w in words if w in masked)
        fr = framents(masked, words)
        for s in fr:
            all_frag.setdefault(s, []).append(n)
        rows.append((n, pn, pn_cnt_before, pn_cnt_after, len(words), dead, resid, "残片%s" % ("".join(sorted(fr)) if fr else "0")))

    with open(out_tsv, "w", encoding="utf-8") as f:
        f.write("病历名\t患者名\t原文次数\t脱敏后\t词表\t死词\t残留\t备注\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")

    print("份数 %d" % len(rows))
    bad = [r for r in rows if str(r[3]) not in ("0",) or r[5] != 0 or r[6] != 0]
    print("患者名未归零 / 有死词 / 有残留 的份数：%d" % len(bad))
    for r in bad:
        print("  %s | 患者名=%s %s->%s | 词表=%s 死词=%s 残留=%s | %s"
              % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]))
    print("\n残片种类（跨份聚合，仅列非「海南」类）：")
    for s, docs in sorted(all_frag.items(), key=lambda kv: -len(kv[1])):
        if s in ("海南",):
            continue
        print("  %s  出现在 %d 份: %s" % (s, len(docs), ", ".join(docs[:3]) + ("..." if len(docs) > 3 else "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
