#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把脱敏 md 做成「可读副本」：在不改动任何可见内容的前提下拆掉超长行。

背景
----
Read 工具对**单行超过 2000 字符**的内容会静默截断。病历 md 的表格行（`<table>...</table>`
整块被序列化在一个物理行里）长达 4644~7831 字符，导致 17%~30% 的内容读不到，
提取方只能再用 Grep/Bash 分段回捞，实测占逐份提取耗时的 53%。
本脚本把超长行在**结构边界或句末标点**处拆开，使每段 ≤ limit，从而一次读全。

红线（硬约束）
--------------
R1 去掉换行后与原文**逐字符相同**          违反 → 退出码 1
R2 只产出副本，原文件不动                   ——
R3 每段长度 ≤ limit                       违反 → 退出码 2
R4 换行不得落在 HTML 标签内部              违反 → 退出码 3
R5 表格行切点必须落在 </td>|</tr>|</table>|</p> 之后
R6 文本行切点必须在 。！？ 之后（尽力而为）  退化硬切 → WARNING
R7 markdown 管道表格行（| 开头）整体不切    → WARNING
R8 R3 与 R5/R6 冲突时 **R3 优先**，退化硬切并记 WARNING
（另：R2 要求副本仅作阅读视图，**不要**用它做 md2docx 转换）

用法
----
    python unwrap_md.py <输入md> <输出md> [--limit 1800] [--lookback-max 400]
                        [--ratio 0.6] [--guard 100] [--no-punct] [--quiet]
"""
import argparse
import hashlib
import os
import re
import sys

BREAK_HTML = ("</td>", "</tr>", "</table>", "</p>")
BREAK_PUNCT = ("。", "！", "？")
TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")
PIPE_RE = re.compile(r"^\s*\|")

EXIT_OK = 0
EXIT_NOT_CONSERVED = 1
EXIT_OVER_LIMIT = 2
EXIT_TAG_BROKEN = 3
EXIT_BAD_ARG = 4


def last_match(s, kinds, lo, hi):
    """窗口 [lo, hi) 内最后一个断点，返回切点（断点末尾）。找不到返回 -1。"""
    lo = max(0, lo)
    best = -1
    for k in kinds:
        i = s.rfind(k, lo, hi)
        if i >= 0 and i + len(k) > best:
            best = i + len(k)
    return best


def reflow_line(line, limit, lookback, ratio, use_punct=True, guard=100):
    """返回 (段列表, 统计)。统计键：hard 硬切次数 / r6_deg 文本行退化次数。"""
    stats = {"hard": 0, "r6_deg": 0}
    if len(line) <= limit:
        return [line], stats
    is_table = "<table>" in line
    kinds = BREAK_HTML if (is_table or not use_punct) else BREAK_PUNCT
    out, pos = [], 0
    while pos < len(line):
        end = min(pos + limit, len(line))
        if end >= len(line):
            out.append(line[pos:])
            break
        lo = pos + int(limit * ratio)
        cut = last_match(line, kinds, lo, end)                    # L1 窗口内
        if cut < 0:
            cut = last_match(line, kinds, max(pos, lo - lookback), end)   # L2 向左扩展
        if cut < 0:                                               # L3 硬切（R8 兜底）
            stats["hard"] += 1
            if not is_table:
                stats["r6_deg"] += 1
            cut = end
            m = re.search(r"</?[A-Za-z][^<>]*$", line[pos:cut])    # R4 守卫
            if m and m.start() > 0:
                cut = pos + m.start()
        out.append(line[pos:cut])
        pos = cut
    return out, stats


def segment_bounds(segs):
    """段边界在整行中的偏移（不含行首 0 与行尾）。"""
    acc, bounds = 0, []
    for s in segs[:-1]:
        acc += len(s)
        bounds.append(acc)
    return bounds


def sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def build(src, limit, lookback, ratio, use_punct, guard):
    """返回 (副本文本, 报告字典)。不写文件。"""
    lines = src.split("\n")
    out, stats = [], {"hard": 0, "r6_deg": 0, "split_lines": 0, "pipe_skipped": 0,
                      "seg_total": 0, "seg_mid": [], "seg_tail": [], "tag_total": 0,
                      "tag_spanning": 0}
    for line in lines:
        if len(line) > limit and PIPE_RE.match(line):
            stats["pipe_skipped"] += 1
            out.append(line)
            continue
        if len(line) > limit:
            stats["split_lines"] += 1
            segs, st = reflow_line(line, limit, lookback, ratio, use_punct, guard)
            stats["hard"] += st["hard"]
            stats["r6_deg"] += st["r6_deg"]
            stats["seg_total"] += len(segs)
            stats["seg_mid"].extend(len(x) for x in segs[:-1])
            stats["seg_tail"].append(len(segs[-1]))
            bounds = segment_bounds(segs)
            for m in TAG_RE.finditer(line):
                stats["tag_total"] += 1
                if any(m.start() < b < m.end() for b in bounds):
                    stats["tag_spanning"] += 1
            out.extend(segs)
        else:
            out.append(line)
    return "\n".join(out), stats


def main():
    ap = argparse.ArgumentParser(description="超长行重排（阅读副本），内容逐字符守恒")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--limit", type=int, default=1800)
    ap.add_argument("--lookback-max", type=int, default=400)
    ap.add_argument("--ratio", type=float, default=0.6)
    ap.add_argument("--guard", type=int, default=100)
    ap.add_argument("--no-punct", action="store_true", help="文本行也只允许结构断点")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if not (400 <= a.limit < 2000):
        print(f"[错误] --limit 必须在 (400, 2000) 内，收到 {a.limit}", file=sys.stderr)
        return EXIT_BAD_ARG
    if not (0.1 <= a.ratio <= 0.95):
        print(f"[错误] --ratio 必须在 [0.1, 0.95] 内，收到 {a.ratio}", file=sys.stderr)
        return EXIT_BAD_ARG
    if a.lookback_max < 0:
        print(f"[错误] --lookback-max 不能为负", file=sys.stderr)
        return EXIT_BAD_ARG

    src_text = open(a.src, encoding="utf-8").read()
    dst_text, st = build(src_text, a.limit, a.lookback_max, a.ratio,
                         not a.no_punct, a.guard)

    # ---- 硬红线校验（先校验，通过才写文件）----
    r1 = src_text.replace("\n", "") == dst_text.replace("\n", "")
    maxlen = max((len(x) for x in dst_text.split("\n")), default=0)
    r3 = maxlen <= a.limit
    r4 = st["tag_spanning"] == 0
    # 幂等
    dst2, _ = build(dst_text, a.limit, a.lookback_max, a.ratio, not a.no_punct, a.guard)
    r_idem = dst2 == dst_text

    if not r1:
        print(f"[失败 R1] 内容不守恒：{a.src}", file=sys.stderr)
        return EXIT_NOT_CONSERVED
    if not r3:
        print(f"[失败 R3] 仍存在超长段（最长 {maxlen} > {a.limit}）：{a.src}", file=sys.stderr)
        return EXIT_OVER_LIMIT
    if not r4:
        print(f"[失败 R4] 有 {st['tag_spanning']} 个标签被切断：{a.src}", file=sys.stderr)
        return EXIT_TAG_BROKEN

    with open(a.dst, "w", encoding="utf-8", newline="") as f:
        f.write(dst_text)

    if not a.quiet:
        segs = sorted(st["seg_mid"] + st["seg_tail"])
        mid = sorted(st["seg_mid"])
        frag = sum(1 for x in mid if x < 0.4 * a.limit)
        med = mid[len(mid) // 2] if mid else 0
        print(f"{os.path.basename(a.src)}")
        print(f"  源: {len(src_text)} 字符 / {len(src_text.split(chr(10)))} 行 / 最长行 "
              f"{max((len(x) for x in src_text.split(chr(10))), default=0)}"
              f"    sha256[:8]={sha8(src_text)}")
        print(f"  副本->{os.path.basename(a.dst)}: {len(dst_text)} 字符 / "
              f"{len(dst_text.split(chr(10)))} 行 / 最长行 {maxlen}"
              f"    sha256[:8]={sha8(dst_text)}")
        print(f"  拆分: 超长行 {st['split_lines']} 条 → {st['seg_total']} 段"
              f"｜中间段 {len(mid)} 个（中位 {med}，最短 {min(mid) if mid else 0}，"
              f"碎片<{int(0.4 * a.limit)} 共 {frag} 个）")
        print(f"  硬切: {st['hard']} 次" + (f"（其中文本行 R6 退化 {st['r6_deg']} 次）"
                                          if st["r6_deg"] else ""))
        if st["pipe_skipped"]:
            print(f"  [WARNING R7] 跳过 {st['pipe_skipped']} 条管道表格行（未切分）")
        print(f"  校验: R1 守恒 {'✅' if r1 else '❌'}｜R3 行长 {'✅' if r3 else '❌'}"
              f"｜R4 标签完整 {st['tag_total']} 个 跨段 {st['tag_spanning']} {'✅' if r4 else '❌'}"
              f"｜幂等 {'✅' if r_idem else '❌'}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
