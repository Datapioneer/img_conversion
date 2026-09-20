# -*- coding: utf-8 -*-
"""按「32 字段全集 + 前几轮细化」的表头组装结果（第 6 版口径）。

该表头是 v1 的 32 字段全集（字段顺序与 v2 完全一致），但措辞吸收了 v2~v5 的细化：
- 第 3 列：扫描「检查所见」，含「床旁」→ 床旁心脏，否则取「检查项目」内容（已修 2 处错判）
- 第 4 列：超声心动图的检查时间（未要求时分秒，仍给完整时间戳）
- 第 7 列：含「有多次入院记录 → 归类为再次入院记录」（需重判）
- 第 10 列：主诉（从入院记录中提取）（已回源补齐 3 份）
- 第 15/17 列：含 (5) 只输出最高优先级来源（单来源口径）
- 第 28/30/32 列：要求精确到时分秒

⚠️ 关键：新表头的**列名文案已变**（如第 3 列由「超声心动图…」改为「心脏超声的检查类型…」）。
所以组装时必须**按位置映射到新列名**输出，否则 `summarize.py` 取不到列、会写出空列
（本次就是靠 `echo_type_scan.py --check` 抓到 8 列写空）。

用法: python build_results_v6.py <names.txt> <outroot> <v2_results.json> <fields.xlsx>
        <echo_time.json> <lab_apply.json> <desc.json> <chief.json> <out.json>
"""
import json
import os
import re
import subprocess
import sys

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"
TITLE = re.compile(r"(多次入院记录|再次入院记录|入院记录)[^。]{0,80}?(姓名|入院时间|主诉)[:：]")
# 需要定点替换的字段（1 基序号）：4 检查时间、7 入院记录类型、10 主诉、15/17 描述、28/30/32 申请时间
PATCH = {4, 7, 10, 15, 17, 28, 30, 32}


def rec_type(text):
    hits = {m.group(1) for m in TITLE.finditer(text)}
    if "多次入院记录" in hits or "再次入院记录" in hits:
        return "再次入院记录"
    return "入院记录" if "入院记录" in hits else "无"


def main() -> int:
    (names_txt, outroot, v2_json, fields_xlsx, echo_json, lab_json,
     desc_json, chief_json, out_json) = sys.argv[1:10]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    v2 = {r["文档标题"]: r for r in json.load(open(v2_json, encoding="utf-8"))}
    k2 = list(next(iter(v2.values())).keys())      # [文档标题] + 32 字段（旧列名）
    echo = json.load(open(echo_json, encoding="utf-8"))
    labs = json.load(open(lab_json, encoding="utf-8"))
    desc = json.load(open(desc_json, encoding="utf-8"))
    chief = json.load(open(chief_json, encoding="utf-8"))
    F = [f["name"] for f in json.loads(subprocess.run(
        [sys.executable, SKILL + "/read_fields.py", fields_xlsx],
        capture_output=True, text=True, check=True).stdout)["fields"]]
    assert len(F) == 32 == len(k2) - 1, "字段数不匹配：模板 %d / 旧结果 %d" % (len(F), len(k2) - 1)

    out, chg = [], {"rec_type": [], "chief": []}
    for n in names:
        r = v2[n]
        assert r["文档标题"] == n
        vals = [r[k2[i + 1]] for i in range(32)]      # 按位置取值（→ 输出时套新列名）
        # ④ 检查时间
        vals[3] = echo.get(n) or vals[3]
        # ⑦ 入院记录类型
        p = os.path.join(outroot, n, n + "_脱敏.md")
        txt = re.sub(r"[ \t]+", " ", open(p, encoding="utf-8").read()) if os.path.isfile(p) else ""
        nt = rec_type(txt) if txt.count("姓名") else "无"
        if nt != vals[6]:
            chg["rec_type"].append((n, vals[6], nt))
        vals[6] = nt
        empty = (nt == "无")
        # ⑩ 主诉
        cv = (chief.get(n, {}) or {}).get("chief", "")
        if cv and cv != vals[9]:
            chg["chief"].append((n, vals[9], cv))
        if cv:
            vals[9] = cv
        # ⑮⑰ 描述（单来源）
        d = desc.get(n, {})
        for po, fo, key in ((14, 15, "htn"), (16, 17, "dm")):
            if empty:
                vals[fo - 1] = "无"
                continue
            jd = vals[po - 1]
            vals[fo - 1] = "%s，%s" % (jd, d.get(key, "/"))
            if jd == "有" and d.get(key, "/") == "/":
                print("  !! %s 判「有」但无描述：%s" % (key, n))
        # ㉘㉚㉜ 申请时间（时分秒）
        lb = labs.get(n, {})
        vals[27] = lb.get("bnp_apply") or "无"
        vals[29] = lb.get("cr_apply") or "无"
        vals[31] = lb.get("cys_apply") or "无"
        rec = {"文档标题": n}
        for i in range(32):
            rec[F[i]] = vals[i]
        out.append(rec)
    json.dump(out, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("build_results_v6: %d 份 × %d 字段 -> %s" % (len(out), len(F) + 1, out_json))
    print("  列名已换成新表头文案；入院记录类型重判 %d 份；主诉更新 %d 份"
          % (len(chg["rec_type"]), len(chg["chief"])))
    for n, a, b in chg["rec_type"]:
        print("    %-30s %s -> %s" % (n, a, b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
