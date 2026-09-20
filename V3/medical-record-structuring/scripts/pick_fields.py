# -*- coding: utf-8 -*-
"""通用「换版取列」工具：把上一版结果按列号投影到新表头。

表头每迭代一版就写一个专用组装脚本会迅速堆积。凡是**新表头是旧表头子集**的情况，
一律用本工具取列即可（本批次 v5 相对 v4 就只是 6 列取 4 列）。

用法:
  python pick_fields.py <新字段xlsx> <源results.json> <out.json> <源列号> <源列号> ...
源列号 = 源结果键列表的下标（0 = 文档标题，1 = 第 1 个字段 …），顺序与新表头一一对应。

例：
  # v5 = 性别/年龄/超声类型/平均E-e' ← v4 的第 1/2/3/4 列
  python pick_fields.py 病历信息提取v5.xlsx results_v4.json results_v5.json 1 2 3 4
"""
import json
import re
import subprocess
import sys

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"


def main() -> int:
    fields_xlsx, src_json, out_json = sys.argv[1:4]
    specs = [int(x) for x in sys.argv[4:]]
    fields = json.loads(subprocess.run(
        [sys.executable, SKILL + "/read_fields.py", fields_xlsx],
        capture_output=True, text=True, check=True).stdout)["fields"]
    F = [f["name"] for f in fields]
    if len(specs) != len(F):
        print("取列数(%d) 与表头字段数(%d) 不一致，请检查" % (len(specs), len(F)))
        return 2
    src = json.load(open(src_json, encoding="utf-8"))
    keys = list(src[0].keys())
    for s in specs:
        if s >= len(keys):
            print("源列号 %d 超出范围（源共 %d 列）" % (s, len(keys)))
            return 2
    out = []
    for row in src:
        rec = {"文档标题": row[keys[0]]}
        if row[keys[0]] != row["文档标题"]:
            rec["文档标题"] = row["文档标题"]
        for i, s in enumerate(specs):
            rec[F[i]] = row[keys[s]]
        out.append(rec)
    json.dump(out, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("pick_fields: %d 份 × %d 字段 -> %s" % (len(out), len(F) + 1, out_json))
    print("  列映射: " + " | ".join("新%d ← 旧%d(%s)" % (i + 1, s, keys[s][:14]) for i, s in enumerate(specs)))
    # 一致性自检：新表头里若含「不重复值少」的判定列，抽样提示
    for i, s in enumerate(specs):
        if re.search(r"性别|类型|入院记录", F[i]):
            vals = sorted({r[F[i]] for r in out})
            print("  %-14s 取值集合: %s" % (F[i][:14], vals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
