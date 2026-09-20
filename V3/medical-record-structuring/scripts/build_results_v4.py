# -*- coding: utf-8 -*-
"""按 v4 表头（6 字段）组装结果。

v4 相对 v3 的变化：
- 字段 15 → 6（仅保留 性别 / 年龄 / 超声检查类型 / 平均E/e' / 入院记录类型 / 主诉）；
- 第 3 列补注「值一般为床旁心脏或者心脏彩超」，判定规则不变（否则输出「检查项目」的内容）；
- 第 5 列补注「若为『有多次入院记录』其类型归类为『再次入院记录』」→ **需要重判**。

因此：除「入院记录类型」外全部复用 v3；入院记录类型按新规重判
（文书标题为 `多次入院记录` 或 `再次入院记录` → 再次入院记录；标题为 `入院记录` → 入院记录）。

用法: python build_results_v4.py <names.txt> <outroot> <v3_results.json> <fields_v4.xlsx> <out.json>
"""
import json
import os
import re
import subprocess
import sys

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"

# 标题后紧跟 姓名/入院时间/主诉 才算是「文书标题」，避免把侧栏导航项当成标题
TITLE = re.compile(r"(多次入院记录|再次入院记录|入院记录)[^。]{0,80}?(姓名|入院时间|主诉)[:：]")


def rec_type(text):
    hits = set()
    for m in TITLE.finditer(text):
        hits.add(m.group(1))
    if "多次入院记录" in hits or "再次入院记录" in hits:
        return "再次入院记录"
    if "入院记录" in hits:
        return "入院记录"
    return "无"          # 空病历


def main() -> int:
    names_txt, outroot, v3_json, fields_xlsx, out_json = sys.argv[1:6]
    chief_json = sys.argv[6] if len(sys.argv) > 6 else ""
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    v3 = {r["文档标题"]: r for r in json.load(open(v3_json, encoding="utf-8"))}
    chief = json.load(open(chief_json, encoding="utf-8")) if chief_json else {}
    k3 = list(next(iter(v3.values())).keys())     # v3: [文档标题] + 15 字段
    fields = json.loads(subprocess.run(
        [sys.executable, SKILL + "/read_fields.py", fields_xlsx],
        capture_output=True, text=True, check=True).stdout)["fields"]
    F = [f["name"] for f in fields]
    assert len(F) == 6, "v4 模板应为 6 字段，实际 %d" % len(F)

    out, changed = [], []
    for n in names:
        r3 = v3[n]
        p = os.path.join(outroot, n, n + "_脱敏.md")
        txt = re.sub(r"[ \t]+", " ", open(p, encoding="utf-8").read()) if os.path.isfile(p) else ""
        new_type = rec_type(txt)
        if new_type != r3[k3[6]]:
            changed.append((n, r3[k3[6]], new_type))
        out.append({
            "文档标题": n,
            F[0]: r3[k3[1]],          # 性别
            F[1]: r3[k3[2]],          # 年龄
            F[2]: r3[k3[3]],          # 超声检查类型
            F[3]: r3[k3[5]],          # 平均E/e'
            F[4]: new_type,           # 入院记录类型（重判）
            F[5]: (chief.get(n, {}).get("chief") or r3[k3[7]]),   # 主诉（回源重抽）
        })
    json.dump(out, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("build_results_v4: %d 份 × %d 字段 -> %s" % (len(out), len(F) + 1, out_json))
    print("  入院记录类型按 v4 新规重判，变更 %d 份：" % len(changed))
    for n, a, b in changed:
        print("    %-30s %s -> %s" % (n, a, b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
