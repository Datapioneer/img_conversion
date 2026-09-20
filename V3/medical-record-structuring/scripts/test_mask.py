#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mask.py 自测（确定性回归用例）。

用法: python test_mask.py          # 全部通过退出码 0，任一失败退出码 1

覆盖 2026-09-17 修复的两个坑：
1. `mask_anchor_runs` 只掩姓名、不吞字段标签（`姓名：李雪飞性别：女` → `姓名：███性别：女`）；
2. 锚点后姓名连排/串字整段掩码（`医师签名：姚富会姚宫会` → 全部掩掉，不留残片）。
"""
import sys

import mask as M

# (原文, 期望输出)
CASES = [
    ("姓名：李雪飞性别：女年龄：68岁", "姓名：███性别：女年龄：68岁"),
    ("上级医师签名：张秋张秋林", "上级医师签名：█████"),
    ("医师签名：姚富会姚宫会", "医师签名：██████"),
    ("创建者：何书帅", "创建者：███"),
    ("检查人：吴多杏", "检查人：███"),
    ("术者：张远生 记录者：张远生", "术者：███ 记录者：███"),
    # 非姓名（黑名单）不动
    ("医师签名：无", "医师签名：无"),
    ("创建者：日期", "创建者：日期"),
    ("审核人</td><td rowspan=1", "审核人</td><td rowspan=1"),
    # 幂等：已掩码文本再跑一次不变
    ("医师签名：███", "医师签名：███"),
]


def main() -> int:
    fails = []
    for src, want in CASES:
        got = M.mask_anchor_runs(src)
        if got != want:
            fails.append((src, want, got))
    # 词表掩码不应破坏锚点整段掩码结果（长词优先 + 锚点先跑）
    got = M.mask("医师签名：姚富会姚宫会", ["姚富会", "姚宫会"])
    if got != "医师签名：██████":
        fails.append(("mask() 组合", "医师签名：██████", got))

    for src, want, got in fails:
        print("FAIL  %s\n  want: %s\n  got : %s" % (src, want, got))
    print("test_mask: %d/%d 通过" % (len(CASES) + 1 - len(fails), len(CASES) + 1))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
