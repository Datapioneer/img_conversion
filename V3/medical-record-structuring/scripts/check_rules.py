#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二 规则检查（确定性判定，不依赖 LLM）。

实现 medical-record-structuring 的三条规则：
  REQ001 (warning) 字段值为 无/空/信息不足 时提示
  FMT001 (warning) 字段名含「日期/时间」且值非空时须匹配 \\d{4}-\\d{2}-\\d{2}
  PRV001 (error)   结果表中不得残留该病人已识别的姓名/医院名明文

用法: python check_rules.py <结果.xlsx> <输出目录> [--manifest 标题=敏感词清单路径 ...]
"""
import argparse
import os
import re
import sys

import pandas as pd

DATE_KEYS = ("日期", "时间")
MISSING = {"无", "", "信息不足", "nan", "None"}


def field_has(key, *kw):
    return any(k in key for k in kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("outdir")
    ap.add_argument("--manifest", nargs="*", default=[],
                    help="格式 标题=敏感词清单文件路径")
    a = ap.parse_args()

    df = pd.read_excel(a.xlsx)
    df = df.fillna("").astype(str)
    title_col = df.columns[0]
    value_cols = [c for c in df.columns if c != title_col]

    req, fmt, prv = [], [], []

    # ---- REQ001 空值 ----
    for _, row in df.iterrows():
        t = row[title_col]
        for c in value_cols:
            if row[c].strip() in MISSING:
                req.append((t, c))

    # ---- FMT001 日期格式 ----
    for _, row in df.iterrows():
        t = row[title_col]
        for c in value_cols:
            if not field_has(c, *DATE_KEYS):
                continue
            v = row[c].strip()
            if v in MISSING:
                continue
            if not re.search(r"\d{4}-\d{2}-\d{2}", v):
                fmt.append((t, c, v))

    # ---- PRV001 脱敏完整性 ----
    man = {}
    for item in a.manifest:
        if "=" not in item:
            continue
        k, p = item.split("=", 1)
        man[k.strip()] = p.strip()
    for _, row in df.iterrows():
        t = row[title_col]
        p = man.get(t)
        if not p or not os.path.isfile(p):
            prv.append((t, "<清单缺失>", "未提供敏感词清单，无法校验"))
            continue
        words = [w.strip() for w in open(p, encoding="utf-8") if w.strip()]
        blob = "\n".join(row[c] for c in value_cols)
        for w in words:
            if len(w) < 2 or re.fullmatch(r"[\d.]+", w):
                continue
            if "█" in w:
                continue
            if w in blob:
                prv.append((t, w, "结果表中残留明文"))

    # ---- 报告 ----
    lines = []
    lines.append("# 阶段二 规则检查报告\n")
    lines.append(f"- 结果表：`{os.path.basename(a.xlsx)}`　行数 {len(df)}　列数 {len(df.columns)}"
                 f"（首列「{title_col}」+ {len(value_cols)} 个字段）\n")

    def block(rid, level, items, detail_fn, total=True):
        ok = len(items) == 0
        lines.append(f"\n## {rid} | {level} | {'✅ 通过' if ok else '⚠️ 未通过'}\n")
        if ok:
            lines.append("无异常项。\n")
            return
        lines.append(f"共 {len(items)} 项异常：\n")
        lines.append("| 文档标题 | 字段 | 详情 |")
        lines.append("|---|---|---|")
        for it in items:
            lines.append("| " + " | ".join(str(x).replace("|", "\\|") for x in detail_fn(it)) + " |")
        lines.append("")

    block("REQ001", "warning", req, lambda x: (x[0], x[1], "值为「无」/空"))
    block("FMT001", "warning", fmt, lambda x: (x[0], x[1], f"值 `{x[2]}` 不含 yyyy-MM-dd"))
    block("PRV001", "error", prv, lambda x: (x[0], x[1], x[2]))

    out = os.path.join(a.outdir, "规则检查报告.md")
    os.makedirs(a.outdir, exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"REQ001 {len(req)} 项 | FMT001 {len(fmt)} 项 | PRV001 {len(prv)} 项 → {out}")
    return 1 if prv else 0


if __name__ == "__main__":
    sys.exit(main())
