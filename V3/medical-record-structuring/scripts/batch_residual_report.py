#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""残片归因报告：对每个残片给出「哪个词表条目包含它」+ 该残片在脱敏文本里的上下文。

用途：判断残片是「真名泄漏」还是「标签/时间词噪音」，并据此写 `<病历名>/专有词_人工.txt`。

用法: python batch_residual_report.py <病历名清单txt> <输出根目录> <报告txt>
"""
import os
import re
import sys

# 明显不是姓名的残片（科室/文书/时间/职称类）——只在报告里降噪，不参与判定
NOISE = re.compile(
    r"^(资料|护理|检查|检验|医院|医科|第二|出院|入院|患者|住院|院资|院资料|上午|下午|全天|"
    r"周三|周五|平素|提示|海南|大学|附属|中心|病房|科|室|记录|报告|单|页|日|月|年|时|分)$"
)


def main() -> int:
    names_txt, outroot, out_txt = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    with open(out_txt, "w", encoding="utf-8") as f:
        for n in names:
            d = os.path.join(outroot, n)
            mask_p = os.path.join(d, n + "_脱敏.md")
            kw_p = os.path.join(d, "敏感词.txt")
            if not (os.path.isfile(mask_p) and os.path.isfile(kw_p)):
                continue
            masked = open(mask_p, encoding="utf-8").read()
            flat = re.sub(r"\s+", " ", masked)
            words = [w.strip() for w in open(kw_p, encoding="utf-8") if w.strip()]
            names_w = [w for w in words if 2 <= len(w) <= 6 and re.fullmatch(r"[\u4e00-\u9fa5]+", w)]
            frags = set()
            for w in names_w:
                for L in range(len(w) - 1, 1, -1):
                    for i in range(0, len(w) - L + 1):
                        s = w[i:i + L]
                        if len(s) >= 2 and s in masked:
                            frags.add(s)
            frags = sorted(x for x in frags if not NOISE.match(x) and x != "海南")
            f.write("\n========== %s ==========\n" % n)
            if not frags:
                f.write("  ✅ 无残片\n")
                continue
            for s in frags:
                owners = [w for w in names_w if s in w and w != s]
                m = re.search(re.escape(s), flat)
                ctx = flat[max(0, m.start() - 26):m.end() + 16] if m else ""
                f.write("  【%s】被这些词表条目包含: %s\n" % (s, "/".join(owners[:4]) or "(无)"))
                f.write("      上下文: %s\n" % ctx)
    print("batch_residual_report -> %s" % out_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
