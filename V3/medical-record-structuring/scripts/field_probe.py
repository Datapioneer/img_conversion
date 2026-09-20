#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二提取辅助：按字段线索把脱敏文本里的相关区域紧凑打印出来。

用法: python field_probe.py <_脱敏.md> <输出txt>
输出到文件（不落 stdout），便于 Read 一次读全；命中区域各自带 20~120 字上下文。
"""
import re
import sys

# 字段线索 → 正则（命中即打印该行/该窗口）
PATTERNS = [
    ("性别年龄", r"姓名[:：].{0,40}"),
    ("入院记录类型", r"(再次)?入院记录"),
    ("入院时间", r"(入院时间|入院日期)[:：]?.{0,30}"),
    ("出院日期", r"(出院日期|出院时间)[:：]?.{0,30}"),
    ("入院科室", r"(入院科室|就诊科室|科室[:：]|科别[:：]).{0,30}"),
    ("主诉", r"主诉[:：]?.{0,120}"),
    ("现病史", r"现病史[:：]?.{0,260}"),
    ("既往史", r"既往史[:：]?.{0,260}"),
    ("入院诊断", r"入院诊断[:：]?.{0,300}"),
    ("出院诊断", r"出院诊断[:：]?.{0,400}"),
    ("补充诊断", r"补充诊断[:：]?.{0,200}"),
    ("Killip", r"Killip.{0,60}"),
    ("心功能分级", r"心功能[^\u4e00-\u9fa5]?[IVX]{1,4}级?.{0,40}"),
    ("肾功能不全", r"肾功能不全.{0,60}"),
    ("房颤房扑", r"(房颤|房扑|心房颤动|心房扑动).{0,60}"),
    ("超声项目时间", r"(检查项目|申请时间)[:：]?.{0,60}"),
    ("超声所见结果", r"(检查所见|报告结果|检查日期|检查时间|检查诊室)[:：]?.{0,200}"),
    ("EF测值", r"(LVEF|EF|左室射血分数|泵功能)[^<]{0,80}"),
    ("Ee测值", r"(E/e|E／e|平均E)[^\u4e00-\u9fa5]{0,60}"),
    ("BNP", r"(脑自然肽|N端前体|NT-?proBNP|pro-?BNP|BNP)[^\u4e00-\u9fa5]{0,80}"),
    ("肌酐", r"肌酐[^\u4e00-\u9fa5]{0,40}"),
    ("胱抑素", r"胱抑素[^\u4e00-\u9fa5]{0,40}"),
    ("单据行", r"<td>[^<]{0,24}</td><td[^>]*>[^<]{0,60}</td>"),
    ("急诊转诊", r"(急诊科|急诊).{0,60}"),
]


def main() -> int:
    src, out = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8").read()
    flat = re.sub(r"\s+", " ", text)
    seen = set()
    with open(out, "w", encoding="utf-8") as f:
        for name, pat in PATTERNS:
            hits = []
            for m in re.finditer(pat, flat):
                s = m.group(0).strip()
                if s in seen:
                    continue
                seen.add(s)
                hits.append(s)
                if len(hits) >= 12:
                    break
            f.write("### %s\n" % name)
            for h in hits:
                f.write("  %s\n" % h)
            if not hits:
                f.write("  (无命中)\n")
    print("field_probe: %s -> %s (%d 字符)" % (src.split("/")[-1], out, len(open(out, encoding="utf-8").read())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
