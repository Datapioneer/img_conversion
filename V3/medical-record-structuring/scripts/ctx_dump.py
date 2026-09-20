#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""候选词上下文导出（辅助人工判定真实姓名）。

用法: python ctx_dump.py <_补全.md> <候选词.txt> <输出txt>
对每个候选词输出最多 2 条 30 字上下文（window），供人工确认是否为真实姓名。
仅为本地人工核对用途，不打印到 stdout。
"""
import re
import sys


def main() -> int:
    md_path, cand_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    text = open(md_path, encoding="utf-8", errors="replace").read()
    flat = re.sub(r"[ \t]+", " ", text)
    cands = [w.strip() for w in open(cand_path, encoding="utf-8", errors="replace") if w.strip()]

    with open(out_path, "w", encoding="utf-8") as f:
        for w in cands:
            hits, last = [], -10 ** 9
            for m in re.finditer(re.escape(w), flat):
                if m.start() - last < 12:      # 去重叠命中
                    continue
                last = m.start()
                a, b = max(0, m.start() - 14), min(len(flat), m.end() + 14)
                hits.append(flat[a:b].replace("\n", "⏎"))
                if len(hits) >= 2:
                    break
            f.write("### %s\n" % w)
            for h in hits:
                f.write("    %s\n" % h)
            if not hits:
                f.write("    (无命中)\n")
    print("%s: 导出 %d 个候选上下文 -> %s" % (md_path, len(cands), out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
