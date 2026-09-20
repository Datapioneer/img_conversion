#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二：组装 28 份病历的 32 字段结果 → results_619304.json。

确定性字段用正则从 `_脱敏.md` 抽取；判定类字段（超声类型/时间/LVEF、心衰、出院日期、
心功能与来源）来自 docs 证据包的人工定稿（见 OVERRIDE），并逐条写明依据。

用法: python build_results_619304.py <病历名清单txt> <输出根目录> <labs.json> <字段excel> <输出json>
"""
import json
import os
import re
import subprocess
import sys

# 判定类字段人工定稿：超声(类型/时间/LVEF)、心衰、出院日期、心功能、来源
OVERRIDE = {
    "619304 无胱抑素 黎开祥": dict(echo_type="床旁心脏", echo_time="2025-08-05 07:57:06", lvef="68",
                                hf="是", dis_date="2025-08-11", nyha="IV级(NYHA分级)", nyha_src="出院诊断"),
    "574862 无胱抑素 张祥生": dict(echo_type="心脏彩超_心脏", echo_time="2025-08-15 16:42:53", lvef="64",
                                hf="否", dis_date="2025-08-24", nyha="无", nyha_src="无"),
    "575128 无胱抑素 杨桂联": dict(echo_type="床旁心脏", echo_time="2025-09-05", lvef="46",
                                hf="是", dis_date="2025-09-10", nyha="无", nyha_src="无"),
    "575783 无胱抑素 郑钦生": dict(echo_type="床旁心脏", echo_time="2025-07-09 16:54:59", lvef="40",
                                hf="否", dis_date="2025-07-17", nyha="无", nyha_src="无"),
    "576635 无胱抑素 侨桂凤": dict(echo_type="心脏彩超_心脏", echo_time="2025-09-25 09:44:47", lvef="41",
                                hf="否", dis_date="2025-09-29", nyha="Ⅱ级(NYHA分级)", nyha_src="入院诊断"),
    "580571 无胱抑素 陈振国": dict(echo_type="心脏彩超_心脏", echo_time="2025-09-10 17:00:56", lvef="无",
                                hf="否", dis_date="2025-09-15", nyha="无", nyha_src="无"),
    "582003 无胱抑素 尹春梅": dict(echo_type="床旁心脏", echo_time="2025-09-21 20:57:28", lvef="56",
                                hf="否", dis_date="无", nyha="无", nyha_src="无"),
    "582648 无胱抑素 陈秀花": dict(echo_type="心脏彩超_心脏", echo_time="2025-07-14", lvef="无",
                                hf="否", dis_date="2025-07-26", nyha="无", nyha_src="无"),
    "584025 无胱抑素 徐月新": dict(echo_type="床旁心脏", echo_time="2025-07-06 21:50:18", lvef="48",
                                hf="否", dis_date="2025-07-11", nyha="Ⅱ级(NYHA分级)", nyha_src="入院诊断"),
    "584261 无心电图记录": dict(echo_type="无", echo_time="无", lvef="无", hf="无", dis_date="无",
                          nyha="无", nyha_src="无"),
    "592710 无胱抑素 廖国华": dict(echo_type="心脏彩超_心脏", echo_time="2025-08-01", lvef="74",
                                hf="否", dis_date="2025-08-04", nyha="I级(NYHA分级)", nyha_src="入院诊断"),
    "597852 无胱抑素 黄贻江": dict(echo_type="心脏彩超_心脏", echo_time="2025-08-14", lvef="无",
                                hf="否", dis_date="无", nyha="无", nyha_src="无"),
    "599534 无胱抑素 林举伟": dict(echo_type="心脏彩超_心脏", echo_time="2025-07-14 14:14:09", lvef="55",
                                hf="否", dis_date="2025-07-28", nyha="II级(NYHA分级)", nyha_src="入院诊断"),
    "602961 无胱抑素 郭斯光 第二次入院": dict(echo_type="床旁心脏", echo_time="2025-08-31 19:55:28", lvef="64",
                                      hf="否", dis_date="2025-09-17", nyha="无", nyha_src="无"),
    "602961 无胱抑素 郭斯光 第一次入院": dict(echo_type="床旁心脏", echo_time="2025-08-05 15:56:42", lvef="63",
                                      hf="否", dis_date="2025-08-22", nyha="无", nyha_src="无"),
    "602970 无胱抑素 王陆": dict(echo_type="心脏彩超_心脏", echo_time="2025-09-03 16:01:47", lvef="69",
                              hf="否", dis_date="2025-09-10", nyha="无", nyha_src="无"),
    "603131 无胱抑素 赵朝光": dict(echo_type="床旁心脏", echo_time="2025-09-05 18:16:53", lvef="57",
                                hf="否", dis_date="2025-09-13", nyha="无", nyha_src="无"),
    "603460 无胱抑素 严开坊": dict(echo_type="心脏彩超_心脏", echo_time="2025-07-18 17:16:48", lvef="56",
                                hf="是", dis_date="无", nyha="Ⅱ级(NYHA分级)", nyha_src="入院诊断"),
    "606175 无胱抑素 陈钻伯": dict(echo_type="心脏彩超_心脏", echo_time="2025-08-26 15:28:10", lvef="66",
                                hf="否", dis_date="2025-08-30", nyha="无", nyha_src="无"),
    "607305 无胱抑素 程建瑛": dict(echo_type="心脏彩超_心脏", echo_time="2025-07-01 15:20:46", lvef="66",
                                hf="否", dis_date="2025-07-29", nyha="无", nyha_src="无"),
    "608158 无胱抑素 符永利": dict(echo_type="床旁心脏", echo_time="2025-08-19", lvef="73",
                                hf="否", dis_date="2025-08-28", nyha="无", nyha_src="无"),
    "608207 无胱抑素 黄玉香": dict(echo_type="心脏彩超_心脏", echo_time="2025-08-07 09:51:00", lvef="60",
                                hf="是", dis_date="2025-08-14", nyha="Ⅱ级(NYHA分级)", nyha_src="出院诊断"),
    "609432 无心电图记录": dict(echo_type="无", echo_time="无", lvef="无", hf="无", dis_date="无",
                          nyha="无", nyha_src="无"),
    "610716 无胱抑素 吴月灵": dict(echo_type="心脏彩超_心脏", echo_time="2025-09-16 15:15:10", lvef="66",
                                hf="否", dis_date="2025-09-25", nyha="无", nyha_src="无"),
    "612288 无胱抑素 陈福": dict(echo_type="心脏彩超_心脏", echo_time="2025-09-10", lvef="56",
                              hf="否", dis_date="2025-09-11", nyha="无", nyha_src="无"),
    "613718 无胱抑素 伏秀芳": dict(echo_type="床旁心脏", echo_time="2025-07-16 15:47:51", lvef="55",
                                hf="否", dis_date="2025-07-26", nyha="无", nyha_src="无"),
    "615559 无胱抑素 杜光兴": dict(echo_type="心脏彩超_心脏", echo_time="2025-08-19 09:35:49", lvef="59",
                                hf="否", dis_date="2025-08-27", nyha="I级(NYHA分级)", nyha_src="入院诊断"),
    "615583 无胱抑素 马业丁": dict(echo_type="床旁心脏", echo_time="2025-07-10 08:21:38", lvef="53",
                                hf="是", dis_date="2025-07-14", nyha="Ⅲ级", nyha_src="入院诊断"),
}

DEF = re.compile(r"(否认|无|未|不)[^。；;，,]{0,12}(高血压|糖尿病)")
# 护理文书单名（`糖尿病毛细血管全` 等）会污染现病史窗口，误判为「有糖尿病」
FORM_NOISE = ("糖尿病毛细血管全", "糖尿病手细血管全", "糖尿病二项", "糖尿病足",
              "毛细血管全", "手细血管全")
HF_WORDS = ("急性心功能不全", "急性心力衰竭", "慢性心功能不全急性加重", "急性心衰",
            "急性左心衰竭", "慢性心力衰竭急性加重", "心力衰竭", "心功能不全", "心衰")
SUSPECT = ("呼吸困难", "胸闷", "气短", "气喘", "气促")
# 单据表表头被 OCR 打散导致申请时间取不到的少数几份：按 单据行/叙述日期人工定稿
BNP_T_FIX = {"608207 无胱抑素 黄玉香": "2025-08-11"}


KILLIP_FIX = (("Ki11ip", "Killip"), ("Ki1lip", "Killip"), ("Kiip", "Killip"),
              ("Ki1ip", "Killip"), ("Yillip", "Killip"), ("Ki11p", "Killip"))


def killip_of(txt):
    """EHR 里 Killip 常被 OCR 成 Ki11ip/Ki1lip/Kiip，先归一化再判级。"""
    t = txt
    for a, b in KILLIP_FIX:
        t = t.replace(a, b)
    m = re.search(r"Killip\s*([IⅠ1]{1,3}|[Ⅱ2]|[Ⅲ3]|[Ⅳ4])\s*级?", t, re.I)
    if not m:
        return "无"
    g = m.group(1).replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    g = g.replace("1", "I").replace("2", "II").replace("3", "III").replace("4", "IV")
    return g + "级"


def flat(path):
    return re.sub(r"\s+", " ", open(path, encoding="utf-8").read())


def g(pat, s, n=1, grp=1):
    m = re.search(pat, s)
    return m.group(grp) if m else ""


def judge_dx(s0, kw):
    s = s0
    for noise in FORM_NOISE:
        s = s.replace(noise, " " * len(noise))
    dis = g(r"出院诊断[:：](.{4,400}?)(?=治疗结果|入院情况|出院情况)", s)
    adm = g(r"入院诊断[:：](.{4,300}?)(?=出院诊断|治疗结果|入院情况|入院记录)", s)
    hx = g(r"现病史[:：](.{4,1500})", s)
    hx = re.split(r"既往史|家族史|个人史|婚育史|流行病学史", hx)[0]      # 截断到下一节，避免家族史误判
    past = g(r"既往史[:：](.{4,400})", s)
    past = re.split(r"家族史|个人史|婚育史|流行病学史|打印", past)[0]
    for src, txt in (("出院诊断", dis), ("现病史", hx), ("既往史", past)):
        if kw in txt:
            i = txt.find(kw)
            if DEF.search(txt[max(0, i - 20):i + len(kw)]):
                continue
            return "有", src
    if kw in adm:
        return "有", "入院诊断"
    return "无", ""


def main() -> int:
    names_txt, outroot, labs_json, fields_xlsx, out_json = sys.argv[1:6]
    names = [l.strip() for l in open(names_txt, encoding="utf-8") if l.strip()]
    labs = json.load(open(labs_json, encoding="utf-8"))
    fields = json.loads(subprocess.run(
        [sys.executable, "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts/read_fields.py",
         fields_xlsx], capture_output=True, text=True, check=True).stdout)["fields"]
    F = [f["name"] for f in fields]
    key = {
        "sex": F[0], "age": F[1], "echo_type": F[2], "echo_time": F[3], "lvef": F[4], "ee": F[5],
        "rec_type": F[6], "dept": F[7], "adm_time": F[8], "chief": F[9], "suspect_hf": F[10],
        "past": F[11], "past_detail": F[12], "htn": F[13], "htn_desc": F[14], "dm": F[15],
        "dm_desc": F[16], "adm_dx": F[17], "dis_dx": F[18], "dis_date": F[19], "hf": F[20],
        "af": F[21], "renal": F[22], "nyha": F[23], "killip": F[24], "src": F[25],
        "bnp_v": F[26], "bnp_t": F[27], "cr_v": F[28], "cr_t": F[29], "cys_v": F[30], "cys_t": F[31],
    }
    out = []
    for n in names:
        s = flat(os.path.join(outroot, n, n + "_脱敏.md"))
        o = OVERRIDE[n]
        lab = labs.get(n, {})
        adm_time = g(r"入院时间[:：]\s*(\d{4}[-年]\d{1,2}[-月]\d{1,2}日?\s*[\d:：]{0,8})", s)
        adm_time = re.sub(r"年|月", "-", adm_time).replace("日", "").strip()
        adm_dx = g(r"入院诊断[:：]\s*(.{4,300}?)(?=出院诊断|治疗结果|入院情况|入院记录)", s)
        dis_dx = g(r"出院诊断[:：]\s*(.{4,400}?)(?=治疗结果|入院情况|出院情况|出院医嘱)", s)
        chief = g(r"主诉[:：]?\s*([^。\n]{2,60}。)", s)
        past = g(r"既往史[:：]\s*([^\n]{2,260})", s)
        dept = g(r"性别[:：]\s*[男女].{0,12}?科\s*室[:：]?\s*([^\s<（(]{2,12}?)(?=床号|病床|住院|\s|<)", s)
        sex_age = g(r"姓名[:：]?\s*\S{0,4}?性别[:：]?\s*(男|女)\s*年龄[:：]?\s*(\d{1,3})\s*岁", s)
        sex = sex_age[0] if sex_age else "无"
        age = re.search(r"年龄[:：]?\s*(\d{1,3})\s*岁", s)
        htn, htn_src = judge_dx(s, "高血压")
        dm, dm_src = judge_dx(s, "糖尿病")
        rec = "再次入院记录" if re.search(r"再次入院记录[^。]{0,80}(姓名|入院时间)", s) else "入院记录"
        hf_neg = (s.count("姓名") == 0)      # 空病历
        row = {
            "文档标题": n,
            key["sex"]: sex, key["age"]: age.group(1) if age else "无",
            key["echo_type"]: o["echo_type"], key["echo_time"]: o["echo_time"], key["lvef"]: o["lvef"],
            key["ee"]: "5.27" if "平均E/e'=5.27" in s else "无",
            key["rec_type"]: "无" if hf_neg else rec,
            key["dept"]: dept or "无", key["adm_time"]: adm_time or "无",
            key["chief"]: chief or "无",
            key["suspect_hf"]: "是" if any(w in chief for w in SUSPECT) else "否",
            key["past"]: "有" if past else "详见前次病历记载",
            key["past_detail"]: past or "无",
            key["htn"]: htn, key["htn_desc"]: ("来源：%s。%s" % (htn_src, "有高血压病史记载" if htn == "有" else "否认/未提及高血压")) if not hf_neg else "无",
            key["dm"]: dm, key["dm_desc"]: ("来源：%s。%s" % (dm_src, "有糖尿病史记载" if dm == "有" else "否认/未提及糖尿病")) if not hf_neg else "无",
            key["adm_dx"]: adm_dx or "无", key["dis_dx"]: dis_dx or "无",
            key["dis_date"]: o["dis_date"], key["hf"]: o["hf"],
            key["af"]: "是" if re.search(r"房颤|房扑|心房颤动|心房扑动", dis_dx) else "否",
            key["renal"]: "有" if "肾功能不全" in dis_dx else "无",
            key["nyha"]: o["nyha"], key["killip"]: killip_of(dis_dx + " " + adm_dx),
            key["src"]: o["nyha_src"],
            key["bnp_v"]: lab.get("bnp_value") or "无",
            key["bnp_t"]: BNP_T_FIX.get(n) or (lab.get("bnp") or {}).get("apply", "")[:10] or "无",
            key["cr_v"]: lab.get("cr_value") or "无",
            key["cr_t"]: (lab.get("cr") or {}).get("apply", "")[:10] or "无",
            key["cys_v"]: lab.get("cys_value") or "无",
            key["cys_t"]: "无",
        }
        out.append(row)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("build_results: %d 份 × %d 字段 -> %s" % (len(out), len(F) + 1, out_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
