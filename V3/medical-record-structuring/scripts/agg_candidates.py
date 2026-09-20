#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨份候选聚合：对一批病历跑「角色相邻 / 表格裸单元格 / 相似变体」三类扫描并按份数聚合。

用法: python agg_candidates.py <病历名清单txt> <输出根目录> <输出tsv>

输出 TSV：候选词 | 出现份数 | 类别(A角色/B表格/C变体) | 首见病历
按「份数降序、类别优先 A」排序，便于优先处理跨份复用性高的漏名。
"""
import os
import re
import sys

ROLE = r"(?:主任医师|副主任医师|主治医师|住院医师|规培医师|医师|医生|护士|护师|技师|签名|审签|审核人|检验人|术者|记录者|创建者|创建人|创健人|申请人)"
STOP = set("""单据 样本 血清 检验人 审核人 项目 葡萄糖 名称 结果 单位 参考值 提示
性别 年龄 姓名 床号 科别 住院号 日期 时间 类型 状态 序号 指标 数值 参考范围 项目名称
患者 病区 病室 医嘱 药品 剂量 用法 频次 途径 执行 签名 医师 护士 合计 金额 数量 单价
主任医师 副主任医师 主治医师 住院医师 规培医师 医生 检验师 技师 科别 病区 床号 性别 年龄
姓名 备注 说明 结果 单位 状态 类型 序号 项目 名称 数值 日期 时间 签名 记录者 创建者 创建人
操作者 以上 无 如下 同上 资料 护理 检查 检验 医院 医科 大学 附属 第二 出院 入院 住院 者 患""".split())
NOISE = re.compile(r"(资料|护理|检查|检验|报告|记录|医嘱|评估|告知|同意|证明|申请|打印|查看|查询|"
                   r"信息|基本|住院|入院|出院|病程|谈话|手术|会诊|体温|检验单|第|页|科|室|区|"
                   r"上午|下午|全天|周[一二三四五六日]|主任|医师|护士|签名|以上|无|之|其)")


def scan(text, known):
    out = {}
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,4})\s*" + ROLE, text):
        w = m.group(1)
        if w not in STOP and w not in known:
            out.setdefault(w, set()).add("A")
    for m in re.finditer(r"<td>\s*([\u4e00-\u9fa5]{2,4})(\d?)\s*</td>", text):
        w = m.group(1)
        if w not in STOP and w not in known:
            out.setdefault(w, set()).add("B")
    known_names = {w for w in known if 2 <= len(w) <= 4 and re.fullmatch(r"[\u4e00-\u9fa5]+", w)}
    for m in re.finditer(r"[\u4e00-\u9fa5]{2,4}", text):
        w = m.group()
        if w in known:
            continue
        for k in known_names:
            if len(set(w) & set(k)) >= 2 and abs(len(w) - len(k)) <= 1:
                out.setdefault(w, set()).add("C")
                break
    return out


def main() -> int:
    names_txt, outroot, out_tsv = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    agg = {}
    for n in names:
        d = os.path.join(outroot, n)
        comp = os.path.join(d, n + "_补全.md")
        kw = os.path.join(d, "敏感词.txt")
        if not (os.path.isfile(comp) and os.path.isfile(kw)):
            continue
        text = open(comp, encoding="utf-8").read()
        known = {w.strip() for w in open(kw, encoding="utf-8") if w.strip()}
        for w, cats in scan(text, known).items():
            rec = agg.setdefault(w, {"docs": set(), "cats": set()})
            rec["docs"].add(n)
            rec["cats"] |= cats

    rows = []
    for w, r in agg.items():
        if NOISE.search(w):
            continue
        rows.append((w, len(r["docs"]), "".join(sorted(r["cats"])), sorted(r["docs"])[0]))
    rows.sort(key=lambda x: (-x[1], "A" not in x[2], -len(x[0]), x[0]))

    with open(out_tsv, "w", encoding="utf-8") as f:
        f.write("候选词\t份数\t类别\t首见病历\n")
        for w, c, cat, first in rows:
            f.write("%s\t%d\t%s\t%s\n" % (w, c, cat, first))
    print("agg_candidates: %d 个候选（已滤噪）-> %s" % (len(rows), out_tsv))
    multi = [r for r in rows if r[1] >= 3]
    print("出现在 >=3 份的候选 %d 个（优先看）" % len(multi))
    for w, c, cat, first in multi[:40]:
        print("  %-8s %2d 份  [%s]" % (w, c, cat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
