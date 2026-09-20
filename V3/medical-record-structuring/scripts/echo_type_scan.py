# -*- coding: utf-8 -*-
"""超声检查类型：按「检查所见出现床旁 → 床旁心脏，否则取检查项目内容」重扫。

为什么需要这个脚本：
    该列在首轮（v1）是一次性人工定稿后写进 OVERRIDE 字典的，之后各版全部**复用**；
    定稿时只看「检查项目」字段、没有真正扫描「检查所见」，于是
    `608207 黄玉香`（检查项目=心脏彩超_心脏，但检查所见写「床旁超声检查…」）被错判为心脏彩超，
    且该错误在 v2~v5 被一路继承。

判定规则（确定性）：
    1. 切出文书中所有「超声报告块」：`检查项目：X … 检查所见：<文本>`；
    2. 只保留心脏类项目（心脏彩超 / 床旁心脏 / 超声心动图 / 心脏）；
    3. 该报告块的「检查所见」文本里出现 `床旁` → 该报告为床旁；
    4. 患者存在任一份床旁报告 → 输出 `床旁心脏`；否则输出该报告「检查项目」的内容。

用法: python echo_type_scan.py <names.txt> <outroot> <out.json>
"""
import json
import os
import re
import sys

# 报告块起点
ITEM = re.compile(r"检查项目[:：]\s*([^\s<（(]{2,24})")
FIND = re.compile(r"检查所见[:：]")
HEART = re.compile(r"心脏|超声心动图")
BED = "床旁"


def blocks(t):
    """返回 [(检查项目, 检查所见文本, 是否床旁)]，按出现顺序。"""
    out = []
    items = list(ITEM.finditer(t))
    for i, m in enumerate(items):
        name = m.group(1).strip().replace("\\_", "_")   # 原文下划线常被 Markdown 转义
        end = items[i + 1].start() if i + 1 < len(items) else min(len(t), m.start() + 4000)
        seg = t[m.start():end]
        fm = FIND.search(seg)
        # 检查所见正文：从「检查所见：」到下一个报告边界/表格结束，限 1200 字
        body = seg[fm.end():fm.end() + 1200] if fm else ""
        if not HEART.search(name) and not HEART.search(body[:200]):
            continue
        out.append((name, body, BED in body[:60]))
    return out


def check(xlsx_path, res, col_want="诊断|入选|超声|检查类型|入院|主诉|E/e"):
    """交付前自检：把结果表里「可确定性重算」的列与重扫结论逐值比对，报出不一致项。"""
    import pandas as pd
    df = pd.read_excel(xlsx_path).fillna("").astype(str)
    cols = list(df.columns)
    hit = [c for c in cols if c != "文档标题" and re.search(col_want, c)]
    if not hit:
        print("  （结果表里没有检查类型列，跳过自检）")
        return 0
    col = hit[0]
    bad = 0
    for _, r in df.iterrows():
        n, v = r[cols[0]], r[col]
        if n in res and res[n]["derived"] != v:
            print("  ✗ %-30s 结果表=%s  重扫=%s  （%s）" % (n, v, res[n]["derived"], res[n]["why"]))
            bad += 1
    print("  自检：%d 项不一致 %s" % (bad, "→ 需修正" if bad else "✅"))
    return bad


def main() -> int:
    names = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    outroot, out_json = sys.argv[2], sys.argv[3]
    res = {}
    for n in names:
        p = os.path.join(outroot, n, n + "_脱敏.md")
        if not os.path.isfile(p):
            res[n] = {"scan": [], "derived": "无", "why": "缺产物"}
            continue
        t = re.sub(r"[ \t]+", " ", open(p, encoding="utf-8").read())
        if t.count("姓名") == 0:
            res[n] = {"scan": [], "derived": "无", "why": "空病历"}
            continue
        bs = blocks(t)
        if not bs:
            res[n] = {"scan": [], "derived": "无", "why": "未捕获超声报告块"}
            continue
        beds = [b for b in bs if b[2]]
        if beds:
            derived, why = "床旁心脏", "有 %d 份报告 检查所见 含「床旁」" % len(beds)
        else:
            derived, why = bs[0][0], "无床旁报告 → 取检查项目内容（首份）"
        res[n] = {"scan": [{"item": b[0], "bed": b[2]} for b in bs], "derived": derived, "why": why}
    json.dump(res, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("echo_type_scan: %d 份 -> %s" % (len(names), out_json))
    if len(sys.argv) > 5 and sys.argv[4] == "--check":
        print("交付前自检（超声检查类型 vs 结果表）:")
        return 1 if check(sys.argv[5], res) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
