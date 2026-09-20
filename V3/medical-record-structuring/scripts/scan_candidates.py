#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手工补词候选扫描（辅助 sensitive.py 代码引擎）。

用法: python scan_candidates.py <_补全.md> <敏感词.txt> <候选输出.txt>

扫描三类盲区（不打印明文到 stdout，只打印计数）：
  A. 角色相邻：X(2-4汉字) 紧跟 主任医师/主治医师/副主任医师/住院医师/规培医师/医师/护士/签名
     —— 代码引擎锚点要求冒号，无冒号即漏。
  B. 表格裸单元格：<td>汉字{2,4}数字?</td>，剔除表头/指标词。
  C. 相似变体：与已识别姓名共享 >=2 字且编辑距离 <=2 的候选，抓 OCR 错字。
"""
import re
import sys

ROLE = r"(?:主任医师|副主任医师|主治医师|住院医师|规培医师|医师|医生|护士|检验师|技师|签名|审签|审核人|检验人)"
STOP_CELL = set("""单据 样本 血清 检验人 审核人 项目 葡萄糖 名称 结果 单位 参考值 提示
性别 年龄 姓名 床号 科别 住院号 日期 时间 类型 状态 序号 指标 数值 参考范围 项目名称
患者 病区 病室 医嘱 药品 剂量 用法 频次 途径 执行 签名 医师 护士 合计 金额 数量 单价""".split())
BLACK = set("""日期 时间 医师签名 医生签名 护士签名 签名 记录者 创建者 操作者 以上 无
主任医师 副主任医师 主治医师 住院医师 规培医师 医师 医生 护士 检验师 技师 审核人 检验人
科别 病区 床号 性别 年龄 姓名 备注 说明 结果 单位 状态 类型 序号 项目 名称 数值""".split())


def main() -> int:
    md_path, kw_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    text = open(md_path, encoding="utf-8", errors="replace").read()
    known = {w.strip() for w in open(kw_path, encoding="utf-8", errors="replace") if w.strip()}

    cands = {}

    # A. 角色相邻
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,4})\s*" + ROLE, text):
        w = m.group(1)
        if w in BLACK:
            continue
        cands.setdefault(w, set()).add("A")

    # B. 表格裸单元格
    for m in re.finditer(r"<td>\s*([\u4e00-\u9fa5]{2,4})(\d?)\s*</td>", text):
        w = m.group(1)
        if w in STOP_CELL or w in BLACK:
            continue
        cands.setdefault(w, set()).add("B")

    # C. 相似变体：与已识别姓名共享 >=2 字
    known_names = {w for w in known
                   if 2 <= len(w) <= 4 and re.fullmatch(r"[\u4e00-\u9fa5]+", w)}
    for m in re.finditer(r"[\u4e00-\u9fa5]{2,4}", text):
        w = m.group()
        for k in known_names:
            if w == k:
                break
            if len(set(w) & set(k)) >= 2 and abs(len(w) - len(k)) <= 1:
                cands.setdefault(w, set()).add("C")
                break

    new = {w: t for w, t in cands.items() if w not in known}
    with open(out_path, "w", encoding="utf-8") as f:
        for w in sorted(new, key=lambda x: (sorted(new[x]), len(x), x)):
            f.write(w + "\n")
    print(f"{md_path}: 已知 {len(known)} | 新候选 {len(new)} "
          f"(A角色 {sum('A' in t for t in new.values())} "
          f"B表格 {sum('B' in t for t in new.values())} "
          f"C变体 {sum('C' in t for t in new.values())}) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
