#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取提取字段模板，输出 JSON。

支持两种格式：
1. 单行表头（新版）：第一行的每个单元格是一个字段名，如「性别,年龄,诊断」，mode 默认 exact。
2. 多列模板（旧版）：含「字段名」列，每行一个字段（字段名/提取模式/判定条件/是否必填）。

用法: python read_fields.py <模板.xlsx|csv>
"""
import sys
import json
import pandas as pd


def main():
    if len(sys.argv) < 2:
        print("用法: python read_fields.py <模板文件>", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    df = pd.read_csv(path) if path.lower().endswith('.csv') else pd.read_excel(path)
    df = df.fillna('').astype(str)
    fields = []

    if '字段名' in df.columns:
        # 旧版多列模板：每行一个字段
        for _, r in df.iterrows():
            name = r.get('字段名', '').strip()
            if not name:
                continue
            fields.append({
                "name": name,
                "mode": r.get('提取模式', 'exact').strip() or 'exact',
                "judge": r.get('判定条件', '').strip(),
                "required": r.get('是否必填', '').strip() in ('是', 'yes', 'true', '1', 'Y', 'y'),
            })
    else:
        # 新版单行表头：每个单元格是一个字段名
        for col in df.columns:
            name = str(col).strip()
            if name:
                fields.append({"name": name, "mode": "exact", "judge": "", "required": False})

    print(json.dumps({"fields": fields}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
