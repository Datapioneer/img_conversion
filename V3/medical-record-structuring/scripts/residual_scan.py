#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""残片扫描：掩码块紧邻的未掩汉字（sensitive.py --verify 的盲区补充）。

--verify 用 `[一-龥·]{2,4}` 抓锚点后的汉字，掩码字符 █ 不在字符类内，
因此形如 `上级医师签名：████林` 的「掩码块 + 1~2 残字」抓不到。
本脚本专门扫这类形态，供人工判断是否需要补词。

用法: python residual_scan.py <_脱敏.md> [--anon]
"""
import re
import sys

ANCHOR = r"(?:签名|医师|医生|护士|姓名|患者|记录者|创建者|创建人|申请[人者]|送检医师|检验医生|审核医生|主任医师|主治医师)"
BLOCK = r"\u2588{2,}"


def main() -> int:
    path = sys.argv[1]
    text = open(path, encoding="utf-8").read()
    hits = []
    # 掩码块后紧跟 1~2 个汉字
    for m in re.finditer(BLOCK + r"([\u4e00-\u9fa5]{1,2})", text):
        tail = m.group(1)
        a = max(0, m.start() - 16)
        ctx = text[a:m.end()].replace("\n", " ")
        hits.append(("块后残字", re.sub(r"[\u4e00-\u9fa5]{2,4}", "<名>", ctx), tail))
    # 锚点后紧跟 1~2 个汉字（未被掩码的短名/残片）
    for m in re.finditer(ANCHOR + r"\s*[:：]\s*([\u4e00-\u9fa5]{1,3})(?![\u4e00-\u9fa5])", text):
        hits.append(("锚点后短名", "<锚点>", m.group(1)))
    print("%s: 疑似残片 %d 处" % (path.split("/")[-1], len(hits)))
    for kind, ctx, tail in hits[:40]:
        print("  [%s] %s | 残字=%s" % (kind, ctx, tail))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
