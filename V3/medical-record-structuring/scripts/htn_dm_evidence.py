# -*- coding: utf-8 -*-
"""抽取「高血压 / 糖尿病」三级证据来源的原文片段。

按 v2 表头要求，描述取值优先级：出院诊断 ＞ 现病史 ＞ 既往史。
三种来源的窗口都必须截断到下一节标题，否则家族史/护理单名会串入。
输出：每份病历 × 每种病 → 三条候选片段（带来源标签），供人工定稿。
"""
import os
import re
import sys

BASE = "D:/wd2/output"

SEC_END = r"既往史|家族史|个人史|婚育史|流行病学史|治疗结果|入院情况|出院情况|出院医嘱|出院带药|补充诊断|打印"
DX_END = r"治疗结果|入院情况|出院情况|出院医嘱|出院诊断|补充诊断|出院带药|病理诊断|打印"

# 护理/检验单据名会被误当成描述，需先抹掉
FORM_NOISE = ("糖尿病毛细血管全", "糖尿病手细血管全", "糖尿病二项", "糖尿病足",
              "毛细血管全", "手细血管全", "高血压二项", "高血压三项")


def flat(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"[ \t]+", " ", t)
    for noise in FORM_NOISE:
        t = t.replace(noise, " " * len(noise))
    return t


def window(t, start_pat, end_pat, maxlen):
    m = re.search(start_pat + r"[:：]?(.{4,%d})" % maxlen, t)
    if not m:
        return None
    s = m.group(1)
    cut = re.split(end_pat, s)
    return cut[0] if cut else s


def raw_ctx(seg, kw, pad=42, limit=3):
    """关键词前后各 pad 字的原始上下文，保留「否认/无」等否定词，便于人工定稿。"""
    if not seg or kw not in seg:
        return []
    out = []
    for m in re.finditer(re.escape(kw), seg):
        a, b = max(0, m.start() - pad), min(len(seg), m.end() + pad)
        frag = seg[a:b].replace("\n", " ").strip()
        if frag and frag not in out:
            out.append(frag)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    names = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    out_path = sys.argv[2]
    DIS = ("高血压", "糖尿病")
    lines = []
    for n in names:
        p = os.path.join(BASE, n, n + "_脱敏.md")
        if not os.path.isfile(p):
            lines.append("#### %s  (缺产物)" % n)
            continue
        t = flat(p)
        dis_dx = window(t, "出院诊断", DX_END, 400)
        adm_hx = window(t, "现病史", SEC_END, 1500)
        past = window(t, "既往史", SEC_END, 400)
        adm_dx = window(t, "入院诊断", DX_END, 400)
        lines.append("=" * 70)
        lines.append("#### %s" % n)
        for kw in DIS:
            lines.append("  --%s" % kw)
            hit = False
            for tag, seg in (("出院诊断", dis_dx), ("现病史", adm_hx), ("既往史", past), ("入院诊断", adm_dx)):
                for c in raw_ctx(seg, kw):
                    lines.append("     [%s] %s" % (tag, c))
                    hit = True
            if not hit:
                lines.append("     (四种来源均无命中 -> 描述填 /)")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("htn_dm_evidence: %d 份 -> %s (%d 字符)" % (len(names), out_path, os.path.getsize(out_path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
