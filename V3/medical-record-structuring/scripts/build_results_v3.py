# -*- coding: utf-8 -*-
"""按 v3 表头（15 字段）组装结果。

v3 相对 v2 的变化：
- 字段由 32 个精简为 15 个；
- 两个时间列要求「精确到时分秒」（超声检查时间、三个检验申请时间）；
- 高血压/糖尿病描述新增规则 (5)：**只输出最高优先级来源的内容**，不得并列多个来源。

因此本脚本不重跑判读逻辑，只做「复用 + 定点替换」：
- 性别/年龄/超声类型/入院记录类型/主诉/出院日期/E/e'/高血压判定/糖尿病判定 → 直接复用 v2 结果；
- 超声检查时间 → 复用 v2，但 6 份补全/规范为时分秒（<echo_fix.json>）；
- 三个检验申请时间 → 重新从单据表取首次申请的完整时间戳（<lab_apply.json>）；
- 两个描述列 → 用单来源定稿表（<desc.json>）重建为「有/无，<来源>：<内容>」。

用法: python build_results_v3.py <names.txt> <v2_results.json> <fields_v3.xlsx>
                               <echo_fix.json> <lab_apply.json> <desc.json> <out.json>
"""
import json
import re
import subprocess
import sys

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"

# v2 结果里的 0 基索引（含表头「文档标题」在 0 位）：v2 键列表 = [文档标题] + F[0..31]
V2 = {
    "sex": 1, "age": 2, "echo_type": 3, "echo_time": 4, "ee": 6, "rec_type": 7,
    "chief": 10, "htn": 14, "dm": 16, "dis_date": 20,
}


def main() -> int:
    names_txt, v2_json, fields_xlsx, echo_fix_json, lab_json, desc_json, out_json = sys.argv[1:8]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    v2rows = {r["文档标题"]: r for r in json.load(open(v2_json, encoding="utf-8"))}
    v2keys = list(next(iter(v2rows.values())).keys())
    echo_fix = json.load(open(echo_fix_json, encoding="utf-8"))
    labs = json.load(open(lab_json, encoding="utf-8"))
    desc = json.load(open(desc_json, encoding="utf-8"))
    fields = json.loads(subprocess.run(
        [sys.executable, SKILL + "/read_fields.py", fields_xlsx],
        capture_output=True, text=True, check=True).stdout)["fields"]
    F = [f["name"] for f in fields]
    assert len(F) == 15, "v3 模板应为 15 字段，实际 %d" % len(F)

    out = []
    for n in names:
        v2row = v2rows[n]
        dsc = desc.get(n, {})
        htn = v2row[v2keys[V2["htn"]]]
        dm = v2row[v2keys[V2["dm"]]]
        empty = (v2row[v2keys[V2["rec_type"]]] == "无")      # 空病历（无内容）
        htn_cell = "无" if empty else "%s，%s" % (htn, dsc.get("htn", "/"))
        dm_cell = "无" if empty else "%s，%s" % (dm, dsc.get("dm", "/"))
        for tag, jd, dv in (("高血压", htn, dsc.get("htn", "/")), ("糖尿病", dm, dsc.get("dm", "/"))):
            if empty:
                continue
            if jd == "有" and dv == "/":
                print("  !! %s 判「有」但无描述：%s" % (tag, n))
            if jd == "无" and dv != "/" and not re.search(r"否认|无|未见|不考虑", dv):
                print("  !! %s 判「无」但描述非否定：%s -> %s" % (tag, n, dv))
        echo_time = echo_fix.get(n) or v2row[v2keys[V2["echo_time"]]]
        lab = labs.get(n, {})
        row = {
            "文档标题": n,
            F[0]: v2row[v2keys[V2["sex"]]],
            F[1]: v2row[v2keys[V2["age"]]],
            F[2]: v2row[v2keys[V2["echo_type"]]],
            F[3]: echo_time or "无",
            F[4]: v2row[v2keys[V2["ee"]]],
            F[5]: v2row[v2keys[V2["rec_type"]]],
            F[6]: v2row[v2keys[V2["chief"]]],
            F[7]: htn, F[8]: htn_cell,
            F[9]: dm, F[10]: dm_cell,
            F[11]: v2row[v2keys[V2["dis_date"]]],
            F[12]: lab.get("bnp_apply") or "无",
            F[13]: lab.get("cr_apply") or "无",
            F[14]: lab.get("cys_apply") or "无",
        }
        out.append(row)
    json.dump(out, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    filled = sum(1 for r in out if re.search(r"\d{2}:\d{2}:\d{2}", r[F[3]]))
    print("build_results_v3: %d 份 × %d 字段 -> %s" % (len(out), len(F) + 1, out_json))
    print("  超声检查时间带时分秒 %d/%d ｜ 检验申请时间带时分秒 BNP %d / 肾二项 %d"
          % (filled, len(out),
             sum(1 for r in out if re.search(r"\d{2}:\d{2}:\d{2}", r[F[12]])),
             sum(1 for r in out if re.search(r"\d{2}:\d{2}:\d{2}", r[F[13]]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
