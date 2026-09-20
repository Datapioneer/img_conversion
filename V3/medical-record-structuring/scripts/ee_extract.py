# -*- coding: utf-8 -*-
"""取「平均E/e'」测值（含图转文实体/断行/跨格修复）。

为什么需要单独的脚本：
    本题此前的取值是**一次性硬编码字面量匹配**（`"5.27" if "平均E/e'=5.27" in s else "无"`），
    既没覆盖「值落在后面某个单元格」的断裂，也没处理实体转义，所以 28 份里只取到 1 份。

三层修复（只读原文，不改任何产物）：
    ① 实体解码：`&#x27;` → `'`（连同 &quot; &amp; &lt; &gt; &nbsp; 一并 html.unescape）；
    ② 表格压平：`</td>`→制表符、`</tr>`→换行、其余标签→空格；
    ③ 跨格缝合：指标名后先看同一格，找不到就向后看 1~3 个单元格找 `=数值`，
       再退化为「合理区间内的裸数值」（1~60，且排除日期/时间/负值），
       于是 `平均E/e&#x27;</td></tr><tr><td>_██ 2022-05-24…心脏彩超_心脏</td><td>=7.57。`
       也能正确取到 7.57。

用法: python ee_extract.py <names.txt> <outroot> <out.json>
"""
import html
import json
import os
import re
import sys

LABEL = re.compile(r"平均\s*E\s*[/／]\s*e\s*(?:['’′‘`]|&#x27;?)?")
EQ = re.compile(r"[=＝]\s*(-?\d+(?:\.\d+)?)")
BARE = re.compile(r"(?<![\d\-:.：])(\d{1,2}(?:\.\d+)?)(?![\d\-:.])")
RAW_LABEL = re.compile(r"平均\s*E\s*[/／]\s*e\s*(?:&#x27;|['’])?")


def normalize(t):
    t = html.unescape(t)
    t = re.sub(r"</t[dh]>", "\t", t)
    t = re.sub(r"</tr\s*>", "\n", t)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return t.replace("\u3000", " ")


def pick(flat, m):
    """在标签后 1~3 个单元格内找 =数值；退化取合理区间裸数值。"""
    tail = flat[m.end():m.end() + 260]
    cells = tail.split("\t")
    for scope, how in (("".join(c for c in cells[:3]), "同格/邻格 =值"),
                       ("".join(cells[:6]), "3~6 格内 =值")):
        e = EQ.search(scope)
        if e:
            return e.group(1), how
    for scope, how in (("".join(cells[:3]), "邻格裸数值"), ("".join(cells[:8]), "远格裸数值")):
        for b in BARE.finditer(scope):
            x = float(b.group(1))
            if 1 <= x <= 60:
                return b.group(1), how
    return "", ""


def main() -> int:
    names = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    outroot, out_json = sys.argv[2], sys.argv[3]
    res, fixed = {}, []
    for n in names:
        p = os.path.join(outroot, n, n + "_脱敏.md")
        if not os.path.isfile(p):
            res[n] = {"ee": "无", "how": "缺产物"}
            continue
        raw = open(p, encoding="utf-8").read()
        if raw.count("姓名") == 0:
            res[n] = {"ee": "无", "how": "空病历"}
            continue
        flat = normalize(raw)
        ms = list(LABEL.finditer(flat))
        if not ms:
            res[n] = {"ee": "无", "how": "原文无「平均E/e'」（或 OCR 未识别）"}
            continue
        val, how = pick(flat, ms[0])
        if not val:
            res[n] = {"ee": "无", "how": "有指标名但未取到数值"}
            continue
        ctx = re.sub(r"\s+", " ", flat[max(0, ms[0].start() - 40):ms[0].end() + 90])
        # 判定是否「必须解码/跨格缝合」才能取到：原文该处带实体，或名字与值之间夹了标签
        rm = RAW_LABEL.search(raw)
        need = bool(rm) and ("&#x27" in rm.group(0) or "</td>" in raw[rm.end():rm.end() + 60])
        res[n] = {"ee": val, "how": how, "ctx": ctx, "needs_fix": need}
        if need:
            fixed.append((n, val, how, ctx))
    json.dump(res, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    got = [(n, r) for n, r in res.items() if r["ee"] != "无"]
    print("ee_extract: %d 份 ｜ 取到值 %d 份" % (len(names), len(got)))
    for n, r in got:
        print("   %-30s = %-8s (%s)" % (n, r["ee"], r["how"]))
    print("\n依赖「实体解码 / 跨格缝合」才有值的：%d 份" % len(fixed))
    for n, v, how, c in fixed:
        print("   %-30s = %-8s (%s)\n        …%s…" % (n, v, how, c[-110:]))
    print("\n未取到值的：", [n for n, r in res.items() if r["ee"] == "无"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
