#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量阶段二：对每个病历目录跑「敏感词识别 → 名部安全网 → 掩码 → 验收」并逐份计时。

用法:
  python batch_stage2.py <病历名清单txt> <输出根目录> <共用词表txt> <日志tsv>

每份流程（全部确定性、0 网络）：
  1) sensitive.py  <_补全.md> 敏感词_基础.txt --manual <共用词表>      → 代码词 + 共用词
  2) name_tail.py  <_补全.md> 敏感词_基础.txt 名部词.txt --report      → 名部安全网
  3) cat 专有词_人工.txt(若有) 共用词表 名部词.txt > 手动词.txt
  4) sensitive.py  <_补全.md> 敏感词.txt --manual 手动词.txt          → 最终词表
  5) mask.py       <_补全.md> 敏感词.txt <_脱敏.md> 敏感词清单.txt
  6) sensitive.py --verify <_脱敏.md>            （漏网复扫）
  7) frag_check.py <_脱敏.md> 敏感词.txt         （姓名残片回扫）
  8) md2docx.py    <_脱敏.md> <_脱敏.docx>
  9) unwrap_md.py  <_脱敏.md> <_可读.md>         （阅读副本）
每步耗时与退出码写入 <日志tsv>；单份失败不中断。
"""
import os
import subprocess
import sys
import time

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"
PY = sys.executable


def run(cmd, cwd=None):
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=cwd)
    return round(time.perf_counter() - t0, 3), p.returncode, (p.stderr or "") + (p.stdout or "")


def main() -> int:
    names_txt, outroot, shared, log = sys.argv[1:5]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    rows = []

    def rec(name, stage, sec, code):
        rows.append((name, stage, sec, code))

    for i, name in enumerate(names, 1):
        d = os.path.join(outroot, name)
        comp = os.path.join(d, name + "_补全.md")
        if not (os.path.isfile(comp) and os.path.getsize(comp) > 0):
            print("[%2d/%d] 跳过（无 _补全.md） %s" % (i, len(names), name), flush=True)
            continue
        own = os.path.join(d, "专有词_人工.txt")
        base = os.path.join(d, "敏感词_基础.txt")
        tail = os.path.join(d, "名部词.txt")
        manual = os.path.join(d, "手动词.txt")
        final = os.path.join(d, "敏感词.txt")
        masked = os.path.join(d, name + "_脱敏.md")
        readable = os.path.join(d, name + "_可读.md")
        dx = os.path.join(d, name + "_脱敏.docx")

        stages = [
            ("S2a 识别", [PY, SKILL + "/sensitive.py", comp, base, "--manual", shared]),
            ("S2b 名部", [PY, SKILL + "/name_tail.py", comp, base, tail]),
            ("S2c 合并", None),
            ("S2d 终词表", [PY, SKILL + "/sensitive.py", comp, final, "--manual", manual]),
            ("S3 掩码", [PY, SKILL + "/mask.py", comp, final, masked, os.path.join(d, "敏感词清单.txt")]),
            ("S4a 复扫", [PY, SKILL + "/sensitive.py", "--verify", masked]),
            ("S4b 残片", [PY, SKILL + "/frag_check.py", masked, final]),
            ("S5 转docx", [PY, SKILL + "/md2docx.py", masked, dx]),
            ("S2e 可读", [PY, SKILL + "/unwrap_md.py", masked, readable, "--quiet"]),
        ]
        print("[%2d/%d] %s" % (i, len(names), name), flush=True)
        for stage, cmd in stages:
            if cmd is None:  # 合并手动词
                t0 = time.perf_counter()
                parts = []
                for p in (own, shared, tail):
                    if os.path.isfile(p):
                        parts.append(open(p, encoding="utf-8").read().rstrip("\n"))
                with open(manual, "w", encoding="utf-8") as f:
                    f.write("\n".join(x for x in parts if x) + "\n")
                rec(name, stage, round(time.perf_counter() - t0, 3), 0)
                continue
            sec, code, out = run(cmd)
            rec(name, stage, sec, code)
            if code not in (0, 1):
                print("      %s 退出码 %s: %s" % (stage, code, out[-300:].replace("\n", " | ")), flush=True)

    with open(log, "w", encoding="utf-8") as f:
        f.write("病历名\t阶段\t秒\t退出码\n")
        for r in rows:
            f.write("%s\t%s\t%.3f\t%d\n" % r)
    agg = {}
    for _, st, sec, _ in rows:
        agg.setdefault(st, []).append(sec)
    print("\n阶段汇总（份数 / 合计秒 / 中位秒）:")
    for st in sorted(agg):
        v = sorted(agg[st])
        print("  %-12s %2d  %.3f  %.3f" % (st, len(v), sum(v), v[len(v) // 2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
