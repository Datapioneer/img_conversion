#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二：6 个检验字段的确定性抽取与配对（BNP/肌酐 值 + 各自的申请时间）。

用法: python lab_extract.py <病历名清单txt> <输出根目录> <输出json>

配对口径（与 SKILL.md 一致）：
- 「申请时间」取自 `检验单列表.txt` 中对应表（脑 / 肾）的**最早一条**（该表按检验时间倒序，末行即首次）；
  行内**最后一个日期时间**即申请时间（列序：检验时间…核收时间…申请时间）。
- 「测值」取自 `检验结果指标.txt` 的首个含目标指标的结果表；若某块线索里有 `检验时间`，
  优先取与单据行检验时间相同的那一块（块级对齐）。
"""
import json
import os
import re
import sys

DT = re.compile(r"\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}(?::\d{2})?|\d{2}-\d{2}-\d{2}\s*\d{2}:\d{2}(?::\d{2})?")
DATE_LIKE = re.compile(r"\d{4}-\d{2}-\d{2}[\d\s:.]*")
RANGE = re.compile(r"\d+\s*[-~]\s*\d+")
UNIT = re.compile(r"(pg/ml|pg/mL|ng/ml|ng/mL|μmol|umol|mmol|U/L|μmol/L)")
VAL = re.compile(r"([<>]?\s*\d[\d.]*)")


def norm_dt(s):
    s = re.sub(r"^(\d{2})-", r"20\1-", s.strip())
    return re.sub(r"\s+", " ", s)


def last_dt(row):
    ds = DT.findall(row)
    return norm_dt(ds[-1]) if ds else ""


def tables(labs):
    """返回 [(表头行, [数据行...])]，每表按文件中出现的顺序。"""
    out = []
    pat = re.compile(r"=+ 表 \d+  表头线索: ([^\n]*)=+\n(.*?)(?=\n=+ 表 \d+ |\Z)", re.S)
    for m in pat.finditer(labs):
        rows = [l.strip() for l in m.group(2).split("\n") if "|" in l]
        out.append((m.group(1), rows))
    return out


def blocks(res):
    """返回 [(线索文本, [命中行...])]。"""
    out = []
    for blk in re.split(r"\n=+ 结果表 \d+ =+\n", res)[1:]:
        lead = ""
        for l in blk.split("\n"):
            if l.startswith("表前线索:"):
                lead = l
        rows = [l.strip() for l in blk.split("\n") if "|" in l]
        out.append((lead, rows))
    return out


def cells_of(row):
    return [c.strip() for c in row.split("|")]


def pick_value(blocks_, kw, target_dt):
    """按「结果值单元格」取值：优先 结果值 同格的数字，其次纯数字单元格。

    先剥掉日期/时间与参考值区间，避免把 `2025-08-03`、`0-125`、`肌钙蛋白1` 当成测值。
    """
    cands = []
    for lead, rows in blocks_:
        for r in rows:
            if kw not in r:
                continue
            for c in cells_of(r):
                c2 = DATE_LIKE.sub(" ", c)
                c2 = RANGE.sub(" ", c2)
                m = re.match(r"^结果值\s*([<>]?\s*\d[\d.]*)$", c2)
                if m:
                    cands.append(([norm_dt(d) for d in DT.findall(lead)], m.group(1).strip(), r[:110]))
                    break
                if re.match(r"^[<>]?\s*\d[\d.]*$", c2):
                    cands.append(([norm_dt(d) for d in DT.findall(lead)], c2.strip(), r[:110]))
                    break
    if not cands:
        return "", ""
    if target_dt:
        for dts, v, r in cands:
            if any(d[:16] == target_dt[:16] for d in dts):
                return v, r
    return cands[0][1], cands[0][2]


BNP_NARR = re.compile(r"脑自然肽N端前体蛋白[^0-9]{0,14}([><]?\s*\d[\d.]*)\s*pg\s*/\s*m[lL1]", re.I)
CR_NARR = re.compile(r"肌酐\s*([<>]?\s*\d{2,4})\s*[μu]?mol", re.I)


def narr_value(md, pat, want_date):
    """兜底：结果表数值单元格被 OCR 吞掉时，从文书叙述（仍位于 <table> 内）按日期取首次值。"""
    flat = re.sub(r"\s+", " ", md)
    hits = []
    for m in pat.finditer(flat):
        pre = flat[max(0, m.start() - 120):m.start()]
        ds = re.findall(r"20\d{2}-\d{2}-\d{2}", pre)
        hits.append((ds[-1] if ds else "", m.group(1).replace(" ", ""), flat[max(0, m.start() - 60):m.end()]))
    if not hits:
        return "", ""
    if want_date:
        d = want_date[:10]
        for dt, v, ctx in hits:
            if dt == d:
                return v, ctx
    dated = [h for h in hits if h[0]]          # 兜底改取「叙述中日期最早」者 = 首次
    if dated:
        return min(dated, key=lambda h: h[0])[1], min(dated, key=lambda h: h[0])[2]
    return hits[0][1], hits[0][2]


def main() -> int:
    names_txt, outroot, out_json = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    out = {}
    for n in names:
        d = os.path.join(outroot, n)
        lp = os.path.join(d, "检验单列表.txt")
        rp = os.path.join(d, "检验结果指标.txt")
        if not (os.path.isfile(lp) and os.path.isfile(rp)):
            out[n] = {"note": "无检验单表（该份无图片内容）"}
            continue
        labs = open(lp, encoding="utf-8").read()
        res = open(rp, encoding="utf-8").read()
        rec = {}
        for head, rows in tables(labs):
            if not rows:
                continue
            first = rows[-1]                      # 倒序表 → 末行 = 首次
            dt = last_dt(first)
            if "脑" in head and "bnp" not in rec:
                rec["bnp"] = {"first_row": first[:150], "apply": dt}
            elif ("肾" in head or "常规生化" in first) and "cr" not in rec:
                rec["cr"] = {"first_row": first[:150], "apply": dt}
        bl = blocks(res)
        bnp_v, bnp_ev = pick_value(bl, "脑自然肽", (rec.get("bnp") or {}).get("apply", ""))
        cr_v, cr_ev = pick_value(bl, "肌酐", (rec.get("cr") or {}).get("apply", ""))
        if not bnp_v or not cr_v:
            mdp = os.path.join(d, n + "_脱敏.md")
            md = open(mdp, encoding="utf-8").read() if os.path.isfile(mdp) else ""
            if not bnp_v:
                bnp_v, bnp_ev = narr_value(md, BNP_NARR, (rec.get("bnp") or {}).get("apply", ""))
                rec["bnp_source"] = "文书叙述兜底"
            if not cr_v:
                cr_v, cr_ev = narr_value(md, CR_NARR, (rec.get("cr") or {}).get("apply", ""))
                rec["cr_source"] = "文书叙述兜底"
        rec["bnp_value"], rec["bnp_evidence"] = bnp_v, bnp_ev
        rec["cr_value"], rec["cr_evidence"] = cr_v, cr_ev
        cys_v, cys_ev = pick_value(bl, "胱抑素", "")
        rec["cys_value"], rec["cys_evidence"] = cys_v, cys_ev
        out[n] = rec
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    miss = [n for n, r in out.items() if not isinstance(r, dict) or not r.get("bnp_value") or not r.get("cr_value")]
    print("lab_extract: %d 份 -> %s" % (len(out), out_json))
    print("BNP 或肌酐未取到的份数：%d %s" % (len(miss), miss[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
