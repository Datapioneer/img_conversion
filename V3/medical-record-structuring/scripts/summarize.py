#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总多个病人的结构化提取结果（dict 列表）为 xlsx（自包含）。

用法:
    python summarize.py <input.json> <output.xlsx> [--columns 列1,列2,...]

- input.json 为 dict 列表，每个 dict 是一个病人的提取结果（每行一个病人）。
- --columns 指定固定列顺序（第一列建议为「文档标题」），严格按此输出，缺失填空，
  不合并 / 不增删 / 不转置。
- 不传 --columns 时，回退为按各 dict key 首次出现顺序。

依赖 pandas + openpyxl。
"""
import sys
import json
import argparse
import pandas as pd


def main():
    ap = argparse.ArgumentParser(description="汇总结构化提取结果为 xlsx")
    ap.add_argument("input", help="输入 JSON（dict 列表）")
    ap.add_argument("output", help="输出 xlsx 路径")
    ap.add_argument("--columns", default=None,
                    help="逗号分隔的固定列顺序，如 '文档标题,性别,年龄'")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print("input.json 需为 dict 或 dict 列表", file=sys.stderr)
        sys.exit(2)

    if args.columns:
        cols = [c.strip() for c in args.columns.split(",") if c.strip()]
    else:
        cols = []
        for d in data:
            if isinstance(d, dict):
                for k in d:
                    if k not in cols:
                        cols.append(k)

    rows = [{c: d.get(c, "") if isinstance(d, dict) else "" for c in cols} for d in data]
    df = pd.DataFrame(rows, columns=cols)
    df.to_excel(args.output, index=False)
    print(f"已导出 {len(data)} 行 × {len(cols)} 列 → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
