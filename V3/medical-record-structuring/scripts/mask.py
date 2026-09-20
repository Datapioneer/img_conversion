#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脱敏掩码脚本（自包含）：清洗敏感词 + 容错正则掩码。

用法:
    python mask.py <markdown文件> <敏感词原始输出文件> <脱敏输出文件> [敏感词清单输出文件]

说明:
- 掩码统一用等长 █ 替换；长词优先（避免短词先替导致长词残缺）。
- 容错：词内字符之间允许夹任意空白（应对 OCR 把「张 三」拆开的情况）。
- 只做确定性替换，不调用任何模型。
"""
import re
import sys


def clean_words(raw_lines):
    """去列表前缀/冗余键名/内部空白，去重，按长度降序。"""
    valid = []
    for line in raw_lines:
        line = str(line).strip()
        if not line:
            continue
        line = line.replace('\\n', '\n')
        parts = re.split(r'[\n\r\,\，\；\;\、\s]+', line)
        for w in parts:
            w = w.strip()
            if not w:
                continue
            w = re.sub(r'^(\d+[\.\、]|\-|\*|\•)\s*', '', w)
            w = re.sub(r'^(医院名|人名|姓名|医院|患者|提取的医院名和人名)[:：]\s*', '', w)
            w = re.sub(r'\s+', '', w)
            if w and w.lower() not in ["null", "none", "无"]:
                valid.append(w)
    return sorted(list(set(valid)), key=len, reverse=True)


# ------------------------------------------------ 锚点整段掩码（2026-09-17 新增）----
# 动机：EHR 截图里签名区常把同一次操作的两个姓名连排（`医师签名：姚富会姚宫会`），
# OCR 还会串字（`上级医师签名：张秋张秋林`）。词表法只能枚举有限变体，一旦 4 字变体
# 先匹配，就会把 3 字真名的尾字留下（`███` + `宫会`），造成单字/双字残片泄漏。
# 处置：在词表掩码**之前**，对「角色/签署锚点 + 冒号」后紧跟的 2~6 字汉字整段掩码；
# 掩码前先剥掉尾部的字段标签（性别/年龄/主任/医师…），避免把标签一起抹掉。
_ANCHOR_RUN_RE = re.compile(
    r"(?:签名|医师|医生|护士|护师|技师|姓名|记录者|创建者|创建人|创健人|创建|操作者|"
    r"检查人|检验人|审核人|申请人|申请者|术者|报告人|核对人|录入人|送检|"
    r"送检医师|检验医生|审核医生|手术医师|麻醉医师|"
    # 2026-09-18 新增：本批（弋矶山）检验报告单/超声报告高频署名锚点，
    # 原先缺失导致「检验者：张三」整段未被锚点掩码，只能靠词表兜底。
    r"检验者|审核者|审校者|申核者|申核医生|报告医生|报告者|诊断医生|记录人|操作人|"
    r"送检者|复核者|核对者|录入者|书写者)"
    r"\s*[:：]\s*([\u4e00-\u9fa5]{2,6})")

# 锚点后仅 1~2 字、且其后不再是汉字（OCR 掐字残留，如「检验者：张 审核时间」）。
# 动机：EHR 把姓名掐成单字时，`{2,6}` 的主规则失配，而单字又绝不能进词表全局掩码
# —— 实测量「张」在该病历另出现 3 次于「舒张期」，全局掩码会毁掉医学术语。
# 故只在此类锚点紧邻位置收口。`(?![一-龥])` 保证不会截断更长的姓名（长名走主规则）。
_ANCHOR_SHORT_RE = re.compile(
    r"((?:检验者|审核者|审校者|申核者|申核医生|审核医生|报告医生|送检医生|诊断医生|"
    r"检验医生|报告者|医师签名|医生签名|护士签名|签名|姓名))"
    r"\s*[:：]\s*([\u4e00-\u9fa5]{1,2})(?![一-龥])")

# 签名锚点**之前**紧邻的 1~2 字姓名（OCR 把姓名与「医师签名」拆成两格/两段，
# 如 `<td>权 医师签名：`）。要求中间有空白，避免误伤「主治医师签名」这类连排职称。
_ANCHOR_PRE_RE = re.compile(
    r"([\u4e00-\u9fa5]{1,2})(\s+)((?:医师签名|医生签名|护士签名|签名))")

# 短候选/前置候选的兜底停用字：这些单字是字段标签或结构字符，不是姓名。
# 典型：`签名： 日 期：2026…` 的「日」——若不加防护会被掩成 `█ 期`。
_SHORT_STOP = set("日 期 时 间 性 别 年 龄 男 女 无 略 人 本 上 下 者 科 室 病 区 床 号 "
                  "记 录 备 注 意 见 签 名 医 师 生 护 士 主 治 院 住 入 出 第 共 页".split())

_LABEL_TAILS = (
    "性别", "年龄", "医师", "医生", "护士", "护师", "技师", "主任", "主治",
    "住院", "签名", "日期", "时间", "床号", "病区", "科室", "记录", "备注", "当班",
)
_LABEL_CHARS = set("性主当师士期号别")
_RUN_BLACKLIST = {
    "无", "以上", "如下", "同上", "日期", "时间", "性别", "年龄", "男", "女",
    "医师", "医生", "护士", "护师", "技师", "签名", "系统", "本人", "家属",
    "患者", "委托人", "记录者", "创建者", "创建人", "操作者", "未知", "略",
}


def _strip_label_tail(run):
    """剥掉整段候选尾部的字段标签，返回真正的姓名字符串。"""
    w = run
    changed = True
    while changed and len(w) > 2:
        changed = False
        for lab in _LABEL_TAILS:
            if w.endswith(lab) and len(w) - len(lab) >= 2:
                w = w[: -len(lab)]
                changed = True
                break
    if len(w) == 4 and w[-1] in _LABEL_CHARS:
        w = w[:-1]
    return w


def mask_anchor_runs(text):
    """锚点整段掩码：`锚点：张三李四` → 姓名整段替换为等长 █。幂等（█ 不在字符类内）。

    三条规则，均以「锚点」定位，不做全局替换：
    ① 主规则 `_ANCHOR_RUN_RE`：锚点后 2~6 字整段掩码（连排姓名收口）；
    ② 短规则 `_ANCHOR_SHORT_RE`：锚点后仅 1~2 字（OCR 掐字残留，如「检验者：张」）；
    ③ 前置规则 `_ANCHOR_PRE_RE`：签名锚点前紧邻的 1~2 字（如「权 医师签名」）。
    ②③ 命中单字时用 `_SHORT_STOP` 排除字段标签（「日 期」的「日」等）。
    """
    def repl(m):
        run = m.group(1)
        name = _strip_label_tail(run)
        if name in _RUN_BLACKLIST or run in _RUN_BLACKLIST:
            return m.group(0)
        # 只掩姓名本身，剥掉的字段标签原样保留（否则会抹掉「性别」等标签）
        masked = "█" * len(name) + run[len(name):]
        return m.group(0)[: m.start(1) - m.start(0)] + masked

    text = _ANCHOR_RUN_RE.sub(repl, text)

    def repl_short(m):
        w = m.group(2)
        if w in _SHORT_STOP or w in _RUN_BLACKLIST:
            return m.group(0)
        return m.group(1) + m.group(0)[len(m.group(1)): m.start(2) - m.start(0)] + "█" * len(w)

    text = _ANCHOR_SHORT_RE.sub(repl_short, text)

    def repl_pre(m):
        w = m.group(1)
        if w in _SHORT_STOP or w in _RUN_BLACKLIST:
            return m.group(0)
        return "█" * len(w) + m.group(2) + m.group(3)

    return _ANCHOR_PRE_RE.sub(repl_pre, text)


def mask(text, words):
    """长词优先，字符间可夹任意空格的容错掩码，替换为等长 █。

    先做锚点整段掩码（收口签名区连排姓名），再按词表逐词掩码（覆盖正文叙述）。
    """
    result = mask_anchor_runs(text)
    for word in words:
        pattern = r'\s*'.join(re.escape(c) for c in word)
        result = re.sub(pattern, lambda m: '█' * len(m.group(0)), result, flags=re.IGNORECASE)
    return result


def main():
    if len(sys.argv) < 4:
        print("用法: python mask.py <markdown文件> <敏感词原始输出文件> <脱敏输出文件> [敏感词清单输出文件]",
              file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding='utf-8') as f:
        text = f.read()
    with open(sys.argv[2], encoding='utf-8') as f:
        raw = f.read().splitlines()
    words = clean_words(raw)
    with open(sys.argv[3], 'w', encoding='utf-8') as f:
        f.write(mask(text, words))
    if len(sys.argv) >= 5:
        with open(sys.argv[4], 'w', encoding='utf-8') as f:
            f.write("\n".join(words))
    print("识别到敏感词 %d 个" % len(words), file=sys.stderr)


if __name__ == "__main__":
    main()
