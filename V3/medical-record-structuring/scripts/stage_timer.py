#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段计时器：把确定性环节的墙钟耗时逐条落到 timing/<日期>_stages.json。

用法: python stage_timer.py <阶段名> -- <命令...>
例:   python stage_timer.py "S2 敏感词识别" -- python sensitive.py in.md out.txt --manual m.txt

输出：stdout 原样透传命令输出；stderr 打印 `[计时] <阶段名> <耗时> s`；
     并在 timing/<日期>_stages.json 追加一条 {"stage","seconds","exit","at"}。
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMING = os.path.join(ROOT, "timing")


def main() -> int:
    try:
        sep = sys.argv.index("--")
    except ValueError:
        print("用法: stage_timer.py <阶段名> -- <命令...>", file=sys.stderr)
        return 2
    stage = sys.argv[1]
    cmd = sys.argv[sep + 1:]

    os.makedirs(TIMING, exist_ok=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd)
    secs = round(time.perf_counter() - t0, 3)

    rec = {
        "stage": stage,
        "seconds": secs,
        "exit": proc.returncode,
        "at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    path = os.path.join(TIMING, dt.date.today().isoformat() + "_stages.json")
    data = []
    if os.path.exists(path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = []
    data.append(rec)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("[计时] %s %.3f s (exit=%d)" % (stage, secs, proc.returncode), file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
