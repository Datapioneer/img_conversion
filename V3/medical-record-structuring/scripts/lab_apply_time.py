# -*- coding: utf-8 -*-
"""抽「检验单报告申请时间」到时分秒（v3 表头要求）。

规则（沿用已验证口径）：
- 数据源仅限 `检验单列表.txt`（由 lab_tables.py 生成，位于 <table> 内）；
- 单据表按时间**倒序**排列 → **末行 = 首次**；
- 申请时间取该行「申请时间」列（表头 10 列中的第 9 列，索引 8）；
- 该院 OCR 常见破损：日期丢失首位 `2`（`025-08-11`）、日期与时间粘连
  （`2025-08-1007:46:56`）、时间用句点分隔（`14.55:45`）→ 统一归一化。

用法: python lab_apply_time.py <names.txt> <outroot> <out.json>
"""
import json
import os
import re
import sys

BNP_KEY = "脑"
CR_KEY = "肾"
CYS_KEY = "胱抑素"

TS = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s*(\d{2})[:.](\d{2})[:.](\d{2})")
TS_SHORT = re.compile(r"(\d{2})-(\d{2})-(\d{2})\s*(\d{2})[:.](\d{2})[:.](\d{2})")
DATE_ONLY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def norm_ts(cell):
    """把一个单元格归一化成 `YYYY-MM-DD HH:MM:SS`；取不到时分秒返回 ''。"""
    s = cell.replace(" ", "")
    m = TS.search(s)
    if m:
        return "%s-%s-%s %s:%s:%s" % m.groups()
    m = TS_SHORT.search(s)
    if m:                       # OCR 掉了首位 2
        return "20%s-%s-%s %s:%s:%s" % m.groups()
    return ""


def tables(path):
    """解析 检验单列表.txt → [(表头线索, [数据行])]。"""
    txt = open(path, encoding="utf-8").read()
    out = []
    pat = re.compile(r"=+ 表 \d+  表头线索: ([^\n]*)=+\n(.*?)(?=\n=+ 表 \d+ |\Z)", re.S)
    for m in pat.finditer(txt):
        rows = [l.strip() for l in m.group(2).split("\n") if "|" in l]
        out.append((m.group(1), rows))
    return out


def pick_first(tbls, key):
    """取「首次」申请时间（完整时分秒）。

    首次 = 单据表按时间倒序 → 含该单据的**最后一行**。
    列位置不能写死：个别病历（如 608207）表头被打散、行首多出若干空列，
    必须以**表头行**里「申请时间」所在的列号定位，否则会误取「检验时间」。
    """
    rows_k = []
    for head, rows in tbls:
        j = None
        for r in rows:
            cells = [c.strip() for c in r.split("|")]
            if "申请时间" in cells:
                j = cells.index("申请时间")
                break
        for r in rows:
            cells = [c.strip() for c in r.split("|")]
            if "申请时间" in cells:
                continue                      # 表头行
            if key not in r:
                continue
            rows_k.append((j, r))
    if not rows_k:
        return ""
    j, last = rows_k[-1]
    cells = [c.strip() for c in last.split("|")]
    if j is not None and len(cells) > j:
        ts = norm_ts(cells[j])
        if ts:
            return ts
    # 列位置法失败 → 全行时间戳取最后一个（申请时间列位于核收时间之后）
    allts = [t for t in (norm_ts(c) for c in cells) if t]
    if allts:
        return allts[-1]
    d = DATE_ONLY.search(last.replace(" ", ""))
    if d:
        return "-".join(d.groups()) + " 00:00:00"
    return ""


def main() -> int:
    names = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    outroot, out_json = sys.argv[2], sys.argv[3]
    res = {}
    for n in names:
        p = os.path.join(outroot, n, "检验单列表.txt")
        if not os.path.isfile(p):
            res[n] = {"bnp_apply": "", "cr_apply": "", "cys_apply": "", "note": "缺 检验单列表.txt"}
            continue
        tbls = tables(p)
        heads = [h for h, _ in tbls]
        rec = {
            "bnp_apply": pick_first(tbls, BNP_KEY),
            "cr_apply": pick_first(tbls, CR_KEY),
            "cys_apply": pick_first(tbls, CYS_KEY),
            "tables": heads,
        }
        if not rec["bnp_apply"]:
            rec["note"] = "单据表未捕获脑自然肽申请时间"
        res[n] = rec
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    full = sum(1 for r in res.values() if r.get("bnp_apply"))
    fullc = sum(1 for r in res.values() if r.get("cr_apply"))
    print("lab_apply_time: %d 份 | BNP 申请时间命中 %d | 肾功能二项命中 %d | 胱抑素命中 %d"
          % (len(names), full, fullc, sum(1 for r in res.values() if r.get("cys_apply"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
