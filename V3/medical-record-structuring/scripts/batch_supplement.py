#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量跑「图转文 + 增量补全」（阶段一 S1），逐份计时、失败不中断、可续跑。

用法: python batch_supplement.py <docx清单txt> <输出根目录> [--log <日志txt>]

- 每份 docx 输出到 `<输出根目录>/<病历名>/`（病历名 = docx 文件名去扩展名，符合技能命名规范）
- 已有 `<病历名>_补全.md` 且非空 → 跳过（续跑安全）
- 单份失败 → 记 FAILED 继续下一份（技能铁律 4）
- 逐份耗时写入 <日志>，格式 `OK/FAILED<TAB>秒<TAB>病历名`
"""
import os
import subprocess
import sys
import time

SKILL = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"
PY = sys.executable


def main() -> int:
    lst, outroot = sys.argv[1], sys.argv[2]
    log = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--log" else None
    docs = [l.strip() for l in open(lst, encoding="utf-8") if l.strip()]
    os.makedirs(outroot, exist_ok=True)
    rows, t_all = [], time.perf_counter()

    for i, docx in enumerate(docs, 1):
        name = os.path.splitext(os.path.basename(docx))[0]
        outdir = os.path.join(outroot, name)
        done = os.path.join(outdir, name + "_补全.md")
        if os.path.isfile(done) and os.path.getsize(done) > 0:
            print("[%2d/%d] 跳过（已有产物） %s" % (i, len(docs), name), flush=True)
            rows.append(("SKIP", 0.0, name))
            continue
        os.makedirs(outdir, exist_ok=True)
        t0 = time.perf_counter()
        print("[%2d/%d] 开始 %s" % (i, len(docs), name), flush=True)
        p = subprocess.run([PY, SKILL + "/supplement.py", docx, outdir],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        secs = round(time.perf_counter() - t0, 1)
        ok = p.returncode == 0 and os.path.isfile(done) and os.path.getsize(done) > 0
        status = "OK" if ok else "FAILED"
        print("[%2d/%d] %s %.1fs %s" % (i, len(docs), status, secs, name), flush=True)
        if not ok:
            tail = (p.stderr or p.stdout or "")[-600:]
            print("      失败输出尾部: %s" % tail.replace("\n", " | "), flush=True)
        rows.append((status, secs, name))

    total = round(time.perf_counter() - t_all, 1)
    if log:
        with open(log, "w", encoding="utf-8") as f:
            f.write("status\tseconds\t病历名\n")
            for s, sec, nm in rows:
                f.write("%s\t%.1f\t%s\n" % (s, sec, nm))
            f.write("TOTAL\t%.1f\t%d 份\n" % (total, len(docs)))
    n_ok = sum(1 for s, _, _ in rows if s == "OK")
    n_fail = sum(1 for s, _, _ in rows if s == "FAILED")
    n_skip = sum(1 for s, _, _ in rows if s == "SKIP")
    print("批次完成：成功 %d | 失败 %d | 跳过 %d | 总耗时 %.1fs (%.1f min)"
          % (n_ok, n_fail, n_skip, total, total / 60), flush=True)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
