#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二证据包：为每份病历抽取「候选值 + 证据片段」，输出一份紧凑的人工复核清单。

用法: python evidence_pack.py <病历名清单txt> <输出根目录> <输出txt>

每个字段给出全部候选值（去重后最多 n 个），便于人工一次性定稿；不依赖 LLM，全部正则。
"""
import os
import re
import sys

ECHO_ITEM = re.compile(r"检查项目[:：]\s*([^\s<（(]{2,14})")
CHECK_DATE = re.compile(r"检查日期[:：]\s*(\d{4}-\d{2}-\d{2})[\s]*(\d{2}:\d{2}(?::\d{2})?)?")
EF = re.compile(r"EF\s*(\d{1,3})\s*%")
EE = re.compile(r"(平均\s*E\s*/?\s*e'?|E\s*/\s*e'|间隔侧\s*e'?)\s*[=:：]?\s*([\d.]+)")
NAME_SEX_AGE = re.compile(r"姓名[:：]?\s*\S{0,4}?性别[:：]?\s*(男|女)\s*年龄[:：]?\s*(\d{1,3})\s*岁")
NAME_DEPT = re.compile(r"性别[:：]\s*[男女].{0,12}?科\s*室[:：]?\s*([^\s<（(]{2,12}?)(?=床号|病床|住院|$|\s|<)")
ADM_TIME = re.compile(r"入院时间[:：]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}日?)\s*([\d:：]{0,8})")
DIS_TIME = re.compile(r"出院时间[:：]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}日?)\s*([\d:：]{0,8})")
CHIEF = re.compile(r"主诉[:：]?\s*([^。\n]{4,70}。)")
ADM_DX = re.compile(r"入院诊断[:：]\s*(.{4,300}?)(?=\s*出院诊断|治疗结果|入院情况|入院记录|$)")
DIS_DX = re.compile(r"出院诊断[:：]\s*(.{4,400}?)(?=\s*治疗结果|入院情况|出院情况|出院医嘱|$)")
NYHA = re.compile(r"心功能\s*([ⅠⅡⅢⅣIVX1-4]{1,3})\s*级")
KILLIP = re.compile(r"Killip\s*([ⅠⅡⅢⅣIVX1-4]{0,3})\s*级?")
RENAL = re.compile(r"肾功能不全")
AF = re.compile(r"(房颤|房扑|心房颤动|心房扑动)")
HYP = re.compile(r"高血压")
DM = re.compile(r"糖尿病")
PAST = re.compile(r"既往史[:：]\s*([^\n]{2,200})")


def uniq(seq, n=4):
    seen, out = set(), []
    for x in seq:
        if isinstance(x, (tuple, list)):
            x = " ".join(str(i) for i in x if i)
        x = re.sub(r"\s+", " ", str(x)).strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
        if len(out) >= n:
            break
    return out


def main() -> int:
    names_txt, outroot, out_txt = sys.argv[1:4]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    sys.path.insert(0, "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts")
    from sensitive import patient_name_from_filepath

    with open(out_txt, "w", encoding="utf-8") as f:
        for n in names:
            d = os.path.join(outroot, n)
            mdp = os.path.join(d, n + "_脱敏.md")
            if not os.path.isfile(mdp):
                continue
            t = re.sub(r"[ \t]+", " ", open(mdp, encoding="utf-8").read())
            flat = re.sub(r"\s+", " ", t)
            lab_sum = os.path.join(d, "检验单列表.txt")
            lab_res = os.path.join(d, "检验结果指标.txt")
            labs = open(lab_sum, encoding="utf-8").read() if os.path.isfile(lab_sum) else ""
            res = open(lab_res, encoding="utf-8").read() if os.path.isfile(lab_res) else ""

            f.write("\n" + "=" * 72 + "\n### %s\n" % n)
            f.write("患者名(取名): %s\n" % (patient_name_from_filepath(mdp) or "(无)"))
            f.write("性别年龄: %s\n" % uniq([m.groups() for m in NAME_SEX_AGE.finditer(flat)]))
            f.write("入院科室: %s\n" % uniq([m.group(1) for m in NAME_DEPT.finditer(flat)]))
            f.write("入院时间: %s | 出院时间: %s\n" % (
                uniq([m.groups() for m in ADM_TIME.finditer(flat)]),
                uniq([m.groups() for m in DIS_TIME.finditer(flat)])))
            f.write("入院记录类型: %s\n" % uniq(re.findall(r"(再次入院记录|入院记录)", flat), 2))
            f.write("主诉: %s\n" % uniq([m.group(1) for m in CHIEF.finditer(flat)], 3))
            f.write("超声检查项目: %s\n" % uniq([m.group(1) for m in ECHO_ITEM.finditer(flat)]))
            f.write("超声检查日期: %s\n" % uniq([m.groups() for m in CHECK_DATE.finditer(flat)]))
            f.write("EF候选: %s | '床旁'出现 %d 次\n" % (
                uniq([m.group(1) for m in EF.finditer(flat)]), len(re.findall(r"床旁", flat))))
            f.write("E/e候选: %s\n" % uniq(["%s=%s" % m.groups() for m in EE.finditer(flat)]))
            f.write("入院诊断: %s\n" % uniq([m.group(1) for m in ADM_DX.finditer(flat)], 2))
            f.write("出院诊断: %s\n" % uniq([m.group(1) for m in DIS_DX.finditer(flat)], 2))
            f.write("补充诊断: %s\n" % uniq(re.findall(r"补充诊断[:：]\s*([^\n<]{2,120})", flat), 2))
            f.write("心功能: %s | Killip: %s | 肾功能不全命中 %d | 房颤房扑命中 %d\n" % (
                uniq(["".join(m.groups()) for m in NYHA.finditer(flat)]),
                uniq(["".join(m.groups()) for m in KILLIP.finditer(flat)]),
                len(RENAL.findall(flat)), len(AF.findall(flat))))
            f.write("高血压提及 %d 次 | 糖尿病提及 %d 次\n" % (
                len(HYP.findall(flat)), len(DM.findall(flat))))
            for m in list(HYP.finditer(flat))[:2]:
                f.write("   [高血压] ...%s...\n" % flat[max(0, m.start() - 24):m.end() + 24])
            for m in list(DM.finditer(flat))[:2]:
                f.write("   [糖尿病] ...%s...\n" % flat[max(0, m.start() - 24):m.end() + 24])
            f.write("既往史: %s\n" % uniq([m.group(1)[:150] for m in PAST.finditer(flat)], 2))
            # 检验单列表：按「========== 表 N 表头线索: X ==========」切块，取每块最后一条数据行（= 首次）
            for blk in re.split(r"\n=+ 表 \d+[^\n]*=+\n", labs)[1:]:
                lines = [l for l in blk.split("\n") if "|" in l]
                if not lines:
                    continue
                f.write("检验单首次行[%s]: %s\n" % (blk.split("\n")[0][:24], lines[-1].strip()[:170]))
            # 结果表：每块打印「表前线索尾部 + 命中行」，靠申请时间对齐
            for blk in re.split(r"\n=+ 结果表 \d+ =+\n", res)[1:]:
                rows = [l.strip() for l in blk.split("\n")
                        if "|" in l and re.search(r"脑自然肽|肌酐|胱抑素", l)]
                if not rows:
                    continue
                lead = ""
                for l in blk.split("\n"):
                    if l.startswith("表前线索:"):
                        lead = l[-110:]
                f.write("结果表[线索 %s] -> %s\n" % (lead, " ； ".join(r[:90] for r in rows[:2])))
    print("evidence_pack: %d 份 -> %s (%d 字符)" % (len(names), out_txt, os.path.getsize(out_txt)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
