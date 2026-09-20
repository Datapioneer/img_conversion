#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二：读字段模板 + 汇总 results.json → xlsx + 列顺序文件。

用法: python stage2_build.py <字段xlsx> <results.json> <结果xlsx> <列顺序txt>
"""
import json
import subprocess
import sys

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"


def main() -> int:
    fields_xlsx, results_json, out_xlsx, cols_txt = sys.argv[1:5]
    r = subprocess.run([sys.executable, SKILL + "/read_fields.py", fields_xlsx],
                       capture_output=True, text=True, check=True)
    fields = json.loads(r.stdout)["fields"]
    cols = ["文档标题"] + [f["name"] for f in fields]
    with open(cols_txt, "w", encoding="utf-8") as f:
        f.write(",".join(cols))
    subprocess.run([sys.executable, SKILL + "/summarize.py", results_json, out_xlsx,
                    "--columns", ",".join(cols)], check=True)
    print("stage2_build: %d 字段 -> %s" % (len(cols), out_xlsx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
