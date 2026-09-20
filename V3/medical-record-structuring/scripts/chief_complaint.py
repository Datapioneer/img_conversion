# -*- coding: utf-8 -*-
"""从入院记录提取「主诉」。

老口径 `主诉[:：]\\s*([^。\\n]{2,60}。)` 要求结尾必须是句号，导致
「主诉：反复胸闷痛2年余，再发3天 现病史：…」（原文主诉后无句号）整条漏取。
本脚本改为：主诉起始锚点 → 截断到下一节/句号/换行，并统一去掉结尾标点，
使 28 份口径一致。

用法: python chief_complaint.py <names.txt> <outroot> <out.json>
"""
import json
import os
import re
import sys

START = re.compile(r"主诉[:：]\s*")
STOP = re.compile(r"\s*(?:现病史|既往史|个人史|病史陈述者|就诊时间|入院时间|病例特点)")
TAIL = "。；;，,、 \t"


def extract(text):
    """返回 (主诉, 命中方式)。优先取「主诉：…」正文段，其次取病例特点里的「主诉…」。"""
    m = START.search(text)
    if m:
        seg = text[m.end():m.end() + 200]
        seg = STOP.split(seg)[0]
        seg = re.sub(r"\s+", " ", seg).strip().strip(TAIL)
        if 2 <= len(seg) <= 80:
            return seg, "主诉段"
    m = re.search(r"主诉[：:]?\s*([^。\n]{2,60})", text)
    if m:
        seg = re.sub(r"\s+", " ", m.group(1)).strip().strip(TAIL)
        if len(seg) >= 2:
            return seg, "回退匹配"
    return "无", ""


def main() -> int:
    names = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    outroot, out_json = sys.argv[2], sys.argv[3]
    res, fixed = {}, []
    for n in names:
        p = os.path.join(outroot, n, n + "_脱敏.md")
        if not os.path.isfile(p):
            res[n] = {"chief": "无", "how": "缺产物"}
            continue
        t = re.sub(r"[ \t]+", " ", open(p, encoding="utf-8").read())
        if t.count("姓名") == 0:                    # 空病历
            res[n] = {"chief": "无", "how": "空病历"}
            continue
        val, how = extract(t)
        res[n] = {"chief": val, "how": how}
        if how != "主诉段":
            fixed.append((n, val, how))
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    none_cnt = sum(1 for r in res.values() if r["chief"] == "无")
    print("chief_complaint: %d 份 | 取不到 %d 份 | 非「主诉段」来源 %d 份"
          % (len(names), none_cnt, len(fixed)))
    for n, v, h in fixed:
        print("    %-30s %s (%s)" % (n, v, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
