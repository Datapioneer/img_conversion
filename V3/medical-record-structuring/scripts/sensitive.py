#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敏感词识别（自包含，不依赖其他技能）。

用法：
    python sensitive.py <输入的图转文md> <输出敏感词txt> [--manual <手动词文件>]
                        [--engine code|llm] [--service URL] [--model qwen3:14b]
                        [--num-ctx 8192] [--chunk 8000] [--timeout 1800]
    python sensitive.py --verify <脱敏后md>          # 漏网复扫（输出匿名化）

引擎（2026-09-16 起默认 code）：
- **code（默认）**：本地正则识别，0 网络、秒级、无 GPU 争抢。
    ① 医院名：后缀锚点（医院/卫生院/保健院/门诊部/诊所/卫生服务中心/卫生室/医务室/卫生所/保健所）
       向前回溯取全名，通用词（上级/当地/本院等）过滤；
    ② 患者姓名：`姓名[:：]` 锚点 + 文件名自动提取（病历名去掉产物后缀后的最后一个中文段，
       如 `703386 无胱抑素 李军_补全.md` → 取「李军」），mask.py 全局掩码；
    ③ 医护姓名：`医师/医生/护士/签名` 角色锚点（要求带冒号，保守防误报）；
    ④ 号码类：床号/住院号/手机号/ID/地址 + 无标签床号（`数字+床`）、括号流水号（`(数字)`）；
    ⑤ 并入 --manual 手工补齐词。
- **llm（备份）**：原有三段合并流程（正则 + 分块调 Ollama + 手动词）。远程 Ollama（默认
  qwen3:14b）恢复可用/资源空闲后，加 `--engine llm` 即可切回，其余参数不变。
- 两个引擎输出文件格式一致，下游 mask.py 无需改动。
- `--no-llm` 保留为兼容别名，等价于 `--engine code`。

验证模式（code/llm 引擎通用，质量兜底）：
    python sensitive.py --verify <脱敏后md>
    校验：① `姓名：` 后未掩汉字 ② 角色/签名锚点后未掩汉字 ③ 医院后缀前紧邻非掩码汉字
    ④ 残留手机号。退出码非 0 = 有漏网（输出匿名化明细，补词重跑 mask.py 后再验）。

数据流向：code 引擎 0 网络；llm 引擎敏感文本发送到内网 GPU 机器（默认 10.20.79.38），
不出公司内网。控制台只打印计数与匿名化样本，禁止把敏感词打印到 stdout。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.20.79.38:11434").rstrip("/")
DEFAULT_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "1800"))
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:14b")
DEFAULT_NUM_CTX = 8192  # 14b 在 16384 下可能静默返回 0 词（实测坑），8192 实测正常

PROMPT_TEMPLATE = """现有病人的病历数据，请结合上下文提取以下文本中的一切医院名和所有人名(姓名可能重复出现在任何地方，且字符"姓名"之后一定为患者的名字)，并严格按照以下格式返回（不要返回任何额外的信息！！）:
提取的医院名和人名，如果有多个用换行符"\\n"间隔，如无，返回null
例如：坪山人民医院\\n肇庆市第一人民医院\\n张三\\n李四\\n王五"""


# ---------------------------------------------------------------- Ollama ----
def ollama_chat(prompt, model=None, service=None, timeout=None, num_ctx=None):
    """调用 Ollama /api/chat，返回去噪后的文本（剥离 qwen3 的 thinking）。"""
    base = (service or DEFAULT_OLLAMA_URL).rstrip("/")
    model = model or DEFAULT_MODEL
    timeout = timeout or DEFAULT_TIMEOUT
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if num_ctx:
        payload["options"]["num_ctx"] = num_ctx
    req = urllib.request.Request(
        f"{base}/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Ollama HTTP {e.code}: {detail}") from e
    content = ((data.get("message") or {}).get("content") or "").strip()
    if "<think>" in content:
        content = content.split("</think>", 1)[-1].strip() if "</think>" in content \
            else content.split("<think>", 1)[-1].strip()
    return content


# ------------------------------------------------------------- 分块 / 提取 ----
def split_by_image(md_text):
    """按「# 图片 N」标题分块；标题前的导言文本也作为独立块返回。"""
    parts = re.split(r"(# 图片 \d+)", md_text)
    result = []
    preamble = parts[0].strip() if parts else ""
    if preamble:
        result.append(("# 文档文本", preamble))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            result.append((title, content))
    return result


def split_by_chars(text, limit):
    """按字符数切块；尽量在换行边界切开，返回 [(标题, 内容), ...]。"""
    if len(text) <= limit:
        return [("全文", text)]
    parts, start, idx = [], 0, 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            cut = text.rfind("\n", end - 500, end)
            if cut > start:
                end = cut
        idx += 1
        parts.append((f"片段 {idx}", text[start:end]))
        start = end
    return parts


def auto_extract(md_text):
    """正则自动提取候选敏感词，返回 (words_set, stats)。"""
    words, stats = set(), {}

    def add(cat, w):
        if w and len(str(w)) >= 4:
            words.add(str(w))
            stats[cat] = stats.get(cat, 0) + 1

    # 床号：允许 '+'/'＋' 连接（EHR 实测「床号：50+02」「床号：20+05」），2026-09-18 修。
    # 原 `(\d{3,6})` 对 "50+02" 完全失配 → 床号整条漏掩。放宽位数后由 add() 的 len>=4 兜底，
    # 不会把 1~3 位短号放进词表（短号在长数字内易误伤）。
    for m in re.finditer(r"床\s*号[:：\s]*(\d{1,6}(?:\s*[+＋]\s*\d{1,4})?)", md_text):
        add("bed", m.group(1))
    # 「数字+床」无标签格式（如 350949床），EHR 截图常见，原版正则抓不到
    for m in re.finditer(r"(?<![\d\-—－])(\d{3,6})\s*床", md_text):
        add("bed", m.group(1))
    for m in re.finditer(r"(?:住院号|住院流水号|门诊号|流水号|登记号|就诊号)[:：\s]*(\d{5,12})", md_text):
        add("num", m.group(1))
    # 「(流水号」无标签格式（如 (1225441)）
    for m in re.finditer(r"[（(](\d{5,9})[)）]?", md_text):
        add("num", m.group(1))
    # 带字母前缀的编号：病案号 B380335 / 患者ID D000389543（2026-09-18 新增）。
    # 原 `(\d{4,12})` 只认纯数字，实测本批 5 份病历的病案号全为 B/D+6~9 位，整类漏掩。
    for m in re.finditer(r"(?:患者\s*ID|病历号|病案号)[:：\s]*([A-Za-z]{0,2}\d{4,12})", md_text):
        add("id", m.group(1))
    # 检验条码号/样本号：患者可追溯的记录号（2026-09-18 新增）。
    # 实测形态 126042234785（12 位条码）、20260423-519（日期-序号）、4496（4 位样本号）。
    # 依赖 mask.py 的长词优先：条码先掩，短样本号此后不再命中，避免短号切入长号内部。
    for m in re.finditer(r"(?:条码号|样本号|标本号|标本条码)[:：\s]*([A-Za-z]{0,2}\d{3,14}(?:\s*-\s*\d{1,6})?)",
                         md_text):
        add("barcode", m.group(1))
    for m in re.finditer(r"1[3-9]\d{9}", md_text):
        add("phone", m.group(0))
    for m in re.finditer(r"(?:常住地址|家庭住址|住址|地址)[:：\s]*([一-龥]{4,30}(?:[村组路街巷号栋室楼单元\d]+)?)", md_text):
        addr = m.group(1).strip()
        if len(addr) >= 6:
            add("addr", addr)
            if "省" in addr:
                add("addr", addr.split("省", 1)[1])
    return words, stats


# --------------------------------------------------------- 代码引擎（默认） ----
# 机构后缀（如需扩充在此追加，注意按长度参与回溯即可，无需排序）
HOSPITAL_SUFFIXES = [
    "社区卫生服务中心", "卫生服务中心", "妇幼保健院", "保健院", "卫生院",
    "保健所", "门诊部", "诊所", "卫生室", "医务室", "卫生所", "医院",
]
_SUFFIX_RE = re.compile("|".join(HOSPITAL_SUFFIXES))

# 后缀前允许出现的全名字符（向前回溯的字符类）
_NAME_CHAR = r"[一-龥A-Za-z0-9（）()·．.\-—－_/／]"

# 前缀为这些通用词的不算医院名（描述性用法）
_GENERIC_PREFIX = {
    "", "上级", "下级", "当地", "本院", "贵院", "外院", "就近", "附近",
    "其他", "其它", "某", "大型", "三甲", "二甲", "三乙", "一甲", "公立", "私立",
}

# 回溯出的候选里含这些片段 → 不是医院名（描述性语句被整段吞掉，如「患者遂至当地医院」）
# 2026-09-18 扩充：EHR 报告页脚的公众号引导语/标语。
# 实测「长按识别二维码 关注 yjsy168 绿色医院人文关爱」→ 被回溯成「绿色医院」；
# 「请扫码关注医院公众号…」→ 「请扫码关注医院」。二者均非机构名，掩码后只损失引导语可读性，
# 且会在 --verify ③ 反复报「医院名漏网」。按「公众号」既有先例并入通用词。
_GENERIC_CONTAINS = (
    "当地", "本院", "贵院", "外院", "我院", "你院", "该院", "上级", "下级",
    "就近", "附近", "其他", "其它", "大型", "三甲", "二甲", "公立", "私立",
    "公众号", "疾病", "症状", "没有", "未曾", "已经", "一直", "长期",
    "扫码", "关注", "绿色",
)

# 回溯候选的前导动词/主语（逐层剥掉后再判定，避免「患者在XX医院」被整段吞掉）
_LEAD_STRIP = (
    "患者", "病人", "家属", "其", "遂往", "遂至", "随即到", "随即", "转至", "转入",
    "发病以来", "发病后", "起病后", "起病以来", "曾于", "既往于", "曾在", "就诊于",
    "未曾前往", "前往", "送至", "送往", "收住", "入", "于", "在", "至", "到", "往", "去",
)

# 姓名/表头常用词黑名单（不得作为姓名）
_NAME_BLACKLIST = {
    "性别", "年龄", "男", "女", "未知", "患者", "病历", "资料", "本人",
    "签字", "审核", "家属", "委托", "图转文", "补全", "脱敏", "文档",
    "全文", "文本", "报告", "清单", "敏感词", "手动词",
    # 表头/标签词（角色锚点跨行捕获时会误吞，如「签名：\n日期：」）
    "日期", "时间", "无", "以上", "如下", "同上", "医师", "医生", "护士",
    "医师签名", "医生签名", "护士签名", "签名", "记录", "记录者", "创建者",
    "操作者", "检查", "检验", "备注", "打印", "第页", "科别", "病区",
}

# 患者姓名锚点：`姓名：**李军**` / `患者姓名:李军` / `姓名 李军`
_PATIENT_NAME_RE = re.compile(r"(?:患者|病人)?姓名\s*[:：]?\s*\*{0,2}([一-龥·]{2,4})\*{0,2}")

# 医护角色锚点：要求冒号，保守防误报（如「主治医师查房」不带名）
_ROLE_TITLE = r"(?:主治|住院|主任|副主任|主管|值班|接诊|手术|麻醉|检查|检验|审核|报告|超声|影像|心电|管床|经治|首诊|会诊|操作|穿刺|换药|送检|标本|申请)?"
_ROLE_RE = re.compile(
    _ROLE_TITLE + r"(?:医师|医生|护士|护师|技师|技士)\s*[:：]\s*([一-龥·]{2,4})"
    r"|(?:医生|医师|护士|患者|委托人|家属|检验者?)?签名\s*[:：]\s*([一-龥·]{2,4})"
)

# 角色/标签词本身绝不能当作人名（2026-09-18 修）。
# 根因：`签名： 住院医师签名：` 经 _ROLE_RE 匹配到「住院医师」，_clean_name 剥掉尾部
# 标签「医师」后只剩「住院」，而「住院」恰是 2 字且不在黑名单 → 被当成医护名。
# 一旦进词表，mask.py 会全局抹掉「住院」，把「住院号」「住院医师签名」「住院天数」
# 「住院志」破坏成「██号」「██医师签名」「██天数」「██志」，严重损伤交付物可读性
# 且会误导阶段二提取。故把「角色标题 + 尾部标签」全集并入黑名单。
# 注：_TAIL_LABELS 在下方定义，其成员的并入见紧邻 _TAIL_LABELS 的那行。
_NAME_BLACKLIST |= {
    "主治", "住院", "主任", "副主任", "主管", "值班", "接诊", "手术", "麻醉",
    "检查", "检验", "审核", "报告", "超声", "影像", "心电", "管床", "经治",
    "首诊", "会诊", "操作", "穿刺", "换药", "送检", "标本", "申请", "检验者",
}

# 病历名中的产物后缀段（从文件名提取患者名时剔除）
_FILE_STEM_SUFFIXES = {"图转文", "补全", "脱敏", "报告", "清单"}


# 锚点正则的 `{2,4}` 是贪心的：紧跟姓名的字段标签会被吞进来，形成
# 「李雪飞性」（原文 `姓名：李雪飞性别：男`）、「葛广全主」（`葛广全主任医师`）这类
# 4 字候选。若直接掩码，会把「性别」的「性」、「主任」的「主」一起抹掉，破坏字段标签。
# 处置：先剥掉尾部的整词标签，再剥掉尾部的单字标签（仅当总长 4、剥后仍 ≥3 字）。
_TAIL_LABELS = (
    "性别", "年龄", "医师", "医生", "护士", "护师", "技师", "主任", "主治",
    "住院", "签名", "日期", "时间", "床号", "病区", "科室", "记录", "备注", "当班",
)
_TAIL_CHARS = set("性主当师士期号别")  # 贪心多吞的 1 字（仅 4 字候选时剥离）
_NAME_BLACKLIST |= set(_TAIL_LABELS)   # 尾部标签词本身不得作为人名（2026-09-18 修）


def _clean_name(raw):
    w = (raw or "").strip().strip("*_ ")
    changed = True
    while changed and len(w) > 2:
        changed = False
        for lab in _TAIL_LABELS:
            if w.endswith(lab) and len(w) - len(lab) >= 2:
                w = w[: -len(lab)]
                changed = True
                break
    if len(w) == 4 and w[-1] in _TAIL_CHARS:
        w = w[:-1]
    w = w.strip("·")
    # 出诊时间/门诊安排不是姓名（2026-09-18 修）。
    # 实测 `…主任医师:周一上午知名专家门诊，周二及周五上午专家门诊…` —— 角色锚点的
    # `([一-龥·]{2,4})` 贪心吞进「周一上午」，进词表后会全局抹掉「周一上午」，
    # 并在 frag_check 里把「上午」报成姓名残片（残余的「周二…上午」本就不敏感）。
    if re.search(r"上午|下午|门诊|时间|日期", w):
        return None
    if w and w not in _NAME_BLACKLIST and re.fullmatch(r"[一-龥·]{2,4}", w):
        return w
    return None


def _normalize_hospital(name):
    """剥掉回溯吞进来的前导动词/主语；无法剥净 → 返回 None（描述性用法，不予掩码）。"""
    n = name.strip("（）()·．.-—－_/／ \t")
    changed = True
    while changed:
        changed = False
        for w in _LEAD_STRIP:
            if n.startswith(w) and len(n) - len(w) >= 3:
                n = n[len(w):]
                changed = True
    if any(bad in n for bad in _GENERIC_CONTAINS):
        return None
    if len(n) < 3 or _SUFFIX_RE.fullmatch(n):  # 只剩后缀（如「医院」）
        return None
    return n if re.search(r"[一-龥]", n) else None


def extract_hospitals(flat_text):
    """从压平文本中提取医院全名（后缀回溯法），返回按长度降序去重列表。"""
    found = set()
    for m in _SUFFIX_RE.finditer(flat_text):
        suffix = m.group(0)
        start = m.start()
        cand_start = start
        while cand_start > 0:
            prev = flat_text[cand_start - 1]
            if re.match(_NAME_CHAR, prev):
                cand_start -= 1
                if start - cand_start >= 20:  # 全名长度上限
                    break
            else:
                break
        prefix = flat_text[cand_start:start]
        if prefix.strip("（）()·．.-—－_/／ ") in _GENERIC_PREFIX:
            continue
        name = _normalize_hospital(prefix + suffix)
        if name:
            found.add(name)
    return sorted(found, key=len, reverse=True)


def extract_names(text):
    """提取患者名（姓名锚点）与医护名（角色锚点），返回 (患者名集合, 医护名集合)。"""
    patients, staff = set(), set()
    for m in _PATIENT_NAME_RE.finditer(text):
        w = _clean_name(m.group(1))
        if w:
            patients.add(w)
    for m in _ROLE_RE.finditer(text):
        raw = next((g for g in m.groups() if g), None)
        w = _clean_name(raw)
        if w:
            staff.add(w)
    return patients, staff


# 病历名里出现、但不是姓名的段（2026-09-17 扩充：本批 28 份含「第N次入院」「无心电图记录」）
_FILE_STEM_NONNAME = {
    "第一次入院", "第二次入院", "第三次入院", "第四次入院", "初次入院", "再次入院",
    "入院", "出院", "无心电图记录", "心电图记录", "无胱抑素", "无肌酐", "无检查",
}


def patient_name_from_filepath(md_path):
    """从病历名提取患者名：去掉产物后缀段与非姓名段后，取最后一个中文段。

    兼容几种命名：
    - `703386 无胱抑素 李军_补全.md`            → 段 [无胱抑素, 李军] → 取「李军」
    - `703386_李军_图转文.md`                  → 段 [李军] → 取「李军」
    - `602961 无胱抑素 郭斯光 第二次入院.md`    → 段 [无胱抑素, 郭斯光, 第二次入院]
                                                → 剔除「第二次入院」→ 取「郭斯光」
    - `584261 无心电图记录.md`                 → 段被整体剔除 → 返回 None
                                                （调用方须回退到正文 `姓名：` 锚点）
    提取不到返回 None。
    """
    stem = os.path.splitext(os.path.basename(md_path))[0]
    segs = [s for s in re.split(r"[_\-\s]+", stem) if s]
    segs = [s for s in segs
            if s not in _FILE_STEM_SUFFIXES
            and s not in _FILE_STEM_NONNAME
            and not re.fullmatch(r"\d+", s)
            and not re.search(r"入院|出院|记录|无胱抑素|无肌酐", s)
            and 2 <= len(s) <= 4]
    if not segs:
        return None
    return _clean_name(segs[-1])


def run_code_engine(md_text, md_path):
    """代码引擎：本地正则识别，返回 (words_sorted, stats_line)。"""
    flat = re.sub(r"[\r\n]+", "", md_text)  # 压平换行；mask.py 的 \s* 容错仍能命中跨行词

    hospitals = extract_hospitals(flat)
    patients, staff = extract_names(md_text)
    from_file = patient_name_from_filepath(md_path)
    if from_file:
        patients.add(from_file)
    elif patients:
        # 病历名不含姓名（如「584261 无心电图记录」）→ 回退到正文 `姓名：` 锚点中出现最多者
        cnt = {}
        for m in _PATIENT_NAME_RE.finditer(md_text):
            w = _clean_name(m.group(1))
            if w:
                cnt[w] = cnt.get(w, 0) + 1
        if cnt:
            from_file = max(cnt, key=lambda k: (cnt[k], len(k)))
            patients.add(from_file)
            from_file = from_file + "(正文回退)"
    auto_words, stats = auto_extract(md_text)

    line = ("代码引擎识别: 医院 %d 个 | 患者名 %d 个（含文件名来源 %s）| 医护名 %d 个 | 号码/地址 %s"
            % (len(hospitals), len(patients), "是" if from_file else "否", len(staff),
               "{%s}" % ", ".join("%s:%d" % kv for kv in sorted(stats.items()))))
    all_words = sorted(set(hospitals) | patients | staff | auto_words, key=len, reverse=True)
    return all_words, line


# ------------------------------------------------------------- 验证模式 ----
def _anon(s):
    """匿名化：把疑似敏感片段替换为占位符，仅保留结构供人工排查。"""
    s = re.sub(r"1[3-9]\d{9}", "<手机号>", s)
    s = re.sub(r"[一-龥A-Za-z0-9]{2,20}(?:医院|卫生院|保健院|门诊部|诊所|卫生服务中心|卫生室|医务室)", "<医院名>", s)
    s = re.sub(r"([一-龥·]{2,4})", "<名>", s)
    return s


def verify_masked(masked_path):
    """漏网复扫：检查脱敏产物，返回 (问题数, [(类别, 匿名化片段), ...])。"""
    with open(masked_path, encoding="utf-8") as f:
        text = f.read()
    problems = []

    # ① 姓名：后面仍有未掩汉字（患者名/医护名漏网）
    for m in re.finditer(r"姓名\s*[:：]?\s*([一-龥·]{2,4})", text):
        if _clean_name(m.group(1)) is None:   # 表头词（性别/日期/医师签名…）不算漏网
            continue
        problems.append(("姓名漏网", _anon(m.group(0))))
    # ② 角色/签名锚点后仍有未掩汉字（表头词已由黑名单过滤，如「签名：\n\n日期：」）
    for m in re.finditer(r"(?:医师|医生|护士|护师|技师)\s*[:：]\s*([一-龥·]{2,4})|签名\s*[:：]\s*([一-龥·]{2,4})", text):
        raw = next((g for g in m.groups() if g), None)
        if _clean_name(raw) is None:
            continue
        problems.append(("角色名漏网", _anon(m.group(0))))
    # ③ 医院后缀前紧邻非掩码汉字（排除通用词引用）
    for m in _SUFFIX_RE.finditer(text):
        start = m.start()
        if start == 0:
            continue
        prev = text[start - 1]
        if prev == "█" or re.match(_NAME_CHAR, prev) is None:
            continue
        cand_start = start
        while cand_start > 0 and re.match(_NAME_CHAR, text[cand_start - 1]) and start - cand_start < 20:
            cand_start -= 1
        prefix = text[cand_start:start]
        if prefix.strip("（）()·．.-—－_/／ ") in _GENERIC_PREFIX:
            continue
        # 与 extract_hospitals 同口径：描述性用法（当地/本院/上级…）不算漏网
        if any(bad in prefix for bad in _GENERIC_CONTAINS):
            continue
        stripped = _normalize_hospital(prefix + m.group(0))
        if stripped is None:
            continue
        problems.append(("医院名漏网", _anon(text[max(0, cand_start - 6):m.end()])))
    # ④ 残留手机号
    for m in re.finditer(r"1[3-9]\d{9}", text):
        problems.append(("手机号漏网", "<手机号>"))

    return len(problems), problems


# ------------------------------------------------------------- 主流程 ----
def group_parts(parts, max_chars):
    """把 (标题, 内容) 聚合为 LLM 批次：单块超长先自切，再按字符预算合并。"""
    refined = []
    for title, content in parts:
        if len(content) > max_chars:
            refined.extend(split_by_chars(content, max_chars))
        else:
            refined.append((title, content))
    batches, cur, cur_len = [], [], 0
    for title, content in refined:
        add_len = len(title) + len(content) + 2
        if cur and cur_len + add_len > max_chars:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append((title, content))
        cur_len += add_len
    if cur:
        batches.append(cur)
    return batches


def call_llm_batch(batch, model, service, timeout, retries=1, num_ctx=DEFAULT_NUM_CTX):
    """对一个批次调用 Ollama 识别；失败重试，仍失败抛异常。"""
    text = "\n\n".join(f"{t}\n{c}" for t, c in batch)
    prompt = PROMPT_TEMPLATE + "\n\n文本：\n" + text
    last_err = None
    for attempt in range(retries + 1):
        try:
            return ollama_chat(prompt, model=model, service=service,
                               timeout=timeout, num_ctx=num_ctx)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[sensitive] 调用失败（第 {attempt + 1} 次）: {e}", file=sys.stderr)
            time.sleep(3)
    raise RuntimeError(f"Ollama 识别失败（已重试 {retries} 次）: {last_err}")


def main():
    ap = argparse.ArgumentParser(description="识别病历文本中的医院名/人名等敏感词（代码引擎默认 / LLM 备份）")
    ap.add_argument("md_file", nargs="?", help="输入 Markdown（建议用 _补全.md）；--verify 模式下为脱敏后文件")
    ap.add_argument("out_txt", nargs="?", help="输出敏感词文件")
    ap.add_argument("--manual", default=None, help="手工补齐敏感词文件（每行一个，可选）")
    ap.add_argument("--engine", choices=["code", "llm"], default="code",
                    help="识别引擎：code=本地正则（默认，0 网络）；llm=远程 Ollama（备份）")
    ap.add_argument("--service", default=DEFAULT_OLLAMA_URL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX,
                    help="[llm] Ollama 上下文窗口（14b 建议 8192，16384 下可能静默返回 0 词）")
    ap.add_argument("--chunk", type=int, default=8000, help="[llm] 每批最大字符数")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="[llm] 超时秒数")
    ap.add_argument("--no-llm", action="store_true",
                    help="兼容别名，等价于 --engine code")
    ap.add_argument("--verify", default=None, help="验证模式：对指定脱敏后 md 做漏网复扫")
    args = ap.parse_args()

    # ---- 验证模式 ----
    if args.verify:
        n, problems = verify_masked(args.verify)
        if n == 0:
            print("漏网复扫: 0 处问题，脱敏产物通过校验", file=sys.stderr)
            return 0
        print("漏网复扫: 发现 %d 处疑似漏网（匿名化）:" % n, file=sys.stderr)
        for kind, ctx in problems[:20]:
            print("  [%s] %s" % (kind, ctx), file=sys.stderr)
        if n > 20:
            print("  ...（其余 %d 处省略）" % (n - 20), file=sys.stderr)
        print("请补词后重跑 mask.py，再重新 --verify。", file=sys.stderr)
        return 1

    if not args.md_file or not args.out_txt:
        ap.error("需要 <md文件> <输出txt> 两个位置参数（或使用 --verify）")

    with open(args.md_file, encoding="utf-8") as f:
        md_text = f.read()

    # ---- 代码引擎（默认；--no-llm 为兼容别名）----
    engine = "llm" if (args.engine == "llm" and not args.no_llm) else "code"
    if engine == "code":
        all_words, line = run_code_engine(md_text, args.md_file)
        print(line, file=sys.stderr)

        manual = ""
        if args.manual:
            if os.path.isfile(args.manual):
                with open(args.manual, encoding="utf-8") as f:
                    manual = f.read().strip()
                print(f"已并入手工词文件: {args.manual}", file=sys.stderr)
            else:
                print(f"警告：手工词文件不存在，跳过: {args.manual}", file=sys.stderr)

        merged = "\n".join(x for x in ["\n".join(all_words), manual] if x)
        os.makedirs(os.path.dirname(os.path.abspath(args.out_txt)) or ".", exist_ok=True)
        with open(args.out_txt, "w", encoding="utf-8") as f:
            f.write(merged + "\n")
        print(f"敏感词已写入: {args.out_txt}（代码 {len(all_words)} + 手工 "
              f"{len([l for l in manual.splitlines() if l.strip()])} 行）", file=sys.stderr)
        return 0

    # ---- LLM 引擎（备份）----
    parts = split_by_image(md_text) or split_by_chars(md_text.strip(), args.chunk)
    print(f"分块: {len(parts)} 块", file=sys.stderr)

    auto_words, stats = auto_extract(md_text)
    print(f"自动提取: {json.dumps(stats, ensure_ascii=False)}", file=sys.stderr)

    llm_words = []
    batches = group_parts(parts, args.chunk)
    print(f"LLM 调用: {len(batches)} 批（每批 ≤{args.chunk} 字, model={args.model} @ {args.service}）",
          file=sys.stderr)
    for i, batch in enumerate(batches, 1):
        t0 = time.time()
        raw = (call_llm_batch(batch, args.model, args.service, args.timeout,
                              num_ctx=args.num_ctx) or "")
        raw = raw.strip().replace("\\n", "\n")
        for line in raw.splitlines():
            w = line.strip().strip("\"'，,。 ")
            if w and w.lower() != "null":
                llm_words.append(w)
        print(f"批次 {i}/{len(batches)} 完成（{time.time() - t0:.0f}s，累计 {len(llm_words)} 词）",
              file=sys.stderr)

    manual = ""
    if args.manual:
        if os.path.isfile(args.manual):
            with open(args.manual, encoding="utf-8") as f:
                manual = f.read().strip()
            print(f"已并入手工词文件: {args.manual}", file=sys.stderr)
        else:
            print(f"警告：手工词文件不存在，跳过: {args.manual}", file=sys.stderr)

    merged = "\n".join(x for x in ["\n".join(llm_words), manual,
                                   "\n".join(sorted(auto_words))] if x)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_txt)) or ".", exist_ok=True)
    with open(args.out_txt, "w", encoding="utf-8") as f:
        f.write(merged + "\n")
    print(f"敏感词(原始)已写入: {args.out_txt}（LLM {len(llm_words)} + 自动 {len(auto_words)}）",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
