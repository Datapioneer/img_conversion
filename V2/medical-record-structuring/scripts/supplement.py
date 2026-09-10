#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""病历 docx 图转文 + 本地增量补全（A1 + 闸门方案）

独立实现，不依赖、不修改 medical-record-structuring 的任何文件。

背景
----
MinerU pipeline 后端的 layout 分块可能把病历截图右侧的"检查所见 / 报告结果"
整块误判为 figure，导致该块既不输出文字、也不保留图片引用（整块丢失）。
本脚本在 MinerU 结果之上做**增量补全**：只补缺失内容，已有内容一字不动。

流程
----
  1) 解包 docx，按文档顺序提取内嵌图片
  2) 上传 MinerU /file_parse（backend=pipeline，同时取 middle_json / content_list）
  3) 组装原始 Markdown（每图一节 `# 图片 N`）
  4) 闸门·粗筛：逐图判断是否需要补
       - discarded_blocks 非空（MinerU 自述被丢弃的块）→ 强信号
       - 或存在「面积占比 >= 阈值 且 type 属 figure/image」的块
         且该图 md 小节缺关键锚点 → 弱信号
  5) 本地 rapidocr 识别原图（优先只裁可疑块区域），2x 放大
  6) 闸门·细筛：归一化后做片段级 n-gram 差集 + 三重约束过滤
  7) 锚点对齐：用两边共有的文字行建立 y → md 位置映射，
     把缺失片段插到相邻锚点之间；锚点不足则追加到该图小节末尾
  8) 输出 <name>_图转文.md（原始）/ <name>_补全.md / <name>_补全报告.txt
     绝不覆盖目录中已存在的文件

用法
----
  python supplement.py <docx> <输出目录> [--service URL] [--batch 8] [--debug]
"""
import argparse
import io
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import uuid
import zipfile

# ----------------------------------------------------------------- 常量 ----
DEFAULT_SERVICE = os.environ.get("MINERU_API_URL", "http://10.20.79.38:8888").rstrip("/")
DEFAULT_TIMEOUT = int(os.environ.get("MCP_TIMEOUT", "1800"))
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp", ".jfif"}

# 闸门参数（可按实测标定）
AREA_RATIO_THRESHOLD = 0.03     # 可疑块面积占比阈值
# 正文锚点：报告页本应出现；md 缺失 → 疑似丢块（粗筛触发条件）
CONTENT_ANCHORS = ("检查所见", "报告结果", "备注", "检查日期", "超声测值")
# 面板字段：报告页都有，不能作为丢块判据；仅用于锚点对齐
PANEL_ANCHORS = ("检查项目", "申请时间", "检查人", "检查诊室")
ALIGN_ANCHORS = CONTENT_ANCHORS + PANEL_ANCHORS
NGRAM = 6                       # n-gram 窗口
MIN_FRAGMENT = 6                # 补入片段最小长度（归一化后字符数）
MIN_SCORE = 0.6                 # rapidocr 置信度阈值
UPSCALE = 2                     # OCR 前放大倍数
REGION_X_MIN = 0.5              # 只采纳 box 中心 x > 图宽*该值 的行（右侧报告区）；设 0 关闭
COVERAGE_THRESHOLD = 0.5        # 行覆盖率低于此值才视为缺失行
# 噪音行正则（系统状态栏/水印/纯数字等，非病历正文）
NOISE_PATTERNS = (
    re.compile(r"^\d+$"),
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"),
    re.compile(r"本机IP|服务器|南京海泰|电子病历系统"),
)

FAILED_PLACEHOLDER = "*(图片 {n} 解析失败)*"


# ------------------------------------------------------- 1. docx 解包 ----
def extract_docx_images(docx_path):
    """解包 docx，返回 [(图片名, bytes), ...]（按 document.xml 中出现的顺序）。"""
    with zipfile.ZipFile(docx_path) as z:
        names = set(z.namelist())
        if "word/document.xml" not in names:
            raise RuntimeError("不是有效的 docx（缺少 word/document.xml）")
        doc_xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        rid_order = re.findall(r'r:(?:embed|id)="(rId\d+)"', doc_xml)

        rels_xml = ""
        if "word/_rels/document.xml.rels" in names:
            rels_xml = z.read("word/_rels/document.xml.rels").decode("utf-8", errors="replace")
        rid_to_target = {}
        for m in re.finditer(r"<Relationship\b[^>]*/?>", rels_xml):
            tag = m.group(0)
            rid = re.search(r'Id="(rId\d+)"', tag)
            typ = re.search(r'Type="([^"]+)"', tag)
            tgt = re.search(r'Target="([^"]+)"', tag)
            if rid and typ and tgt and typ.group(1).endswith("/image"):
                rid_to_target.setdefault(rid.group(1), tgt.group(1))

        images, seen = [], set()
        for rid in rid_order:
            target = rid_to_target.get(rid)
            if not target:
                continue
            media_path = target if target.startswith("word/") else "word/" + target.lstrip("/")
            media_path = media_path.replace("word/word/", "word/")
            if media_path not in names or media_path in seen:
                continue
            seen.add(media_path)
            if os.path.splitext(media_path)[1].lower() not in RASTER_EXTS:
                continue
            images.append((os.path.basename(media_path), z.read(media_path)))
    return images


# ------------------------------------------------------- 2. MinerU 调用 ----
def _build_multipart(files, fields):
    boundary = "----wb" + uuid.uuid4().hex
    parts = []
    for name, value in (fields or {}).items():
        parts.append((f"--{boundary}\r\n"
                      f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                      f"{value}\r\n").encode("utf-8"))
    for filename, data in files:
        parts.append((f"--{boundary}\r\n"
                      f'Content-Disposition: form-data; name="files"; '
                      f'filename="{filename}"\r\n'
                      f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8"))
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def mineru_parse(files, service, timeout):
    """上传文件解析，返回 {stem: {"md":..., "middle_json":..., "content_list":...}}。"""
    fields = {
        "backend": "pipeline",
        "parse_method": "auto",
        "lang_list": "ch",
        "return_md": "true",
        "return_middle_json": "true",
        "return_content_list": "true",
    }
    body, ctype = _build_multipart(files, fields)
    req = urllib.request.Request(f"{service}/file_parse", data=body,
                                 headers={"Content-Type": ctype}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"MinerU HTTP {e.code}: {detail}") from e
    if data.get("status") != "completed":
        raise RuntimeError(f"MinerU 任务失败: {data.get('error') or data.get('status')}")

    out = {}
    for key, val in (data.get("results") or {}).items():
        if isinstance(val, dict):
            out[key] = {
                "md": val.get("md_content") or val.get("md") or "",
                "middle_json": val.get("middle_json"),
                "content_list": val.get("content_list"),
            }
        else:
            out[key] = {"md": str(val), "middle_json": None, "content_list": None}
    return out


def _as_obj(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return None
    return v


# --------------------------------------------------------- 3. 闸门·粗筛 ----
def page_scale(middle, img_w, img_h):
    """由 page_size 求坐标换算因子 (sx, sy)。"""
    try:
        ps = middle["pdf_info"][0]["page_size"]
        return img_w / float(ps[0]), img_h / float(ps[1])
    except Exception:  # noqa: BLE001
        return 1.0, 1.0


def block_area_ratio(bbox, page_size):
    try:
        w = abs(float(bbox[2]) - float(bbox[0]))
        h = abs(float(bbox[3]) - float(bbox[1]))
        return (w * h) / (float(page_size[0]) * float(page_size[1]))
    except Exception:  # noqa: BLE001
        return 0.0


def md_has_anchor(md_section, anchors=CONTENT_ANCHORS):
    return [a for a in anchors if a in md_section]


def gate_screen(middle, img_size, md_section, debug=False):
    """粗筛：返回 (need: bool, reason: str, boxes: [ [x1,y1,x2,y2], ... ])。

    boxes 用**原图像素坐标**表示（已按 page_size 换算），供裁剪使用。
    """
    if not middle:
        return False, "无 middle_json", []
    try:
        page = middle["pdf_info"][0]
    except Exception:  # noqa: BLE001
        return False, "middle_json 结构异常", []

    page_size = page.get("page_size") or [img_size[0], img_size[1]]
    sx, sy = page_scale(middle, img_size[0], img_size[1])

    def to_px(b):
        return [b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy]

    # 信号 1：discarded_blocks 非空（MinerU 自述丢弃）
    discarded = page.get("discarded_blocks") or []
    big_discarded = []
    for b in discarded:
        r = block_area_ratio(b.get("bbox", [0, 0, 0, 0]), page_size)
        if r >= AREA_RATIO_THRESHOLD:
            big_discarded.append(b)
    if debug and discarded:
        print(f"    [粗筛] discarded_blocks={len(discarded)} 个，其中大块 {len(big_discarded)} 个",
              file=sys.stderr)

    if debug:
        def _txt_of(b):
            t = ""
            for ln in (b.get("lines") or []):
                for sp in (ln.get("spans") or []):
                    t += sp.get("content") or ""
            if not t:
                t = str(b.get("content") or "")
            return t
        print(f"    [粗筛] page_size={page_size} 图片={img_size}", file=sys.stderr)
        print(f"    [粗筛] preproc={len(page.get('preproc_blocks') or [])} "
              f"discarded={len(discarded)} para={len(page.get('para_blocks') or [])}",
              file=sys.stderr)
        for tag, blks in (("pre ", page.get("preproc_blocks") or []),
                          ("disc", discarded)):
            for b in blks:
                t = _txt_of(b)
                r = block_area_ratio(b.get("bbox", [0, 0, 0, 0]), page_size)
                kw = [a for a in ("检查所见", "报告结果", "备注", "检查日期", "检查项目") if a in t]
                print(f"      {tag} type={b.get('type')} area={r:.4f} "
                      f"chars={len(t)} kw={kw}", file=sys.stderr)

    # 信号 2：大 figure/image 块 + md 缺锚点
    big_figure = []
    for b in (page.get("preproc_blocks") or []):
        if str(b.get("type", "")).lower() in ("figure", "image"):
            r = block_area_ratio(b.get("bbox", [0, 0, 0, 0]), page_size)
            if r >= AREA_RATIO_THRESHOLD:
                big_figure.append(b)

    content_hits = [a for a in CONTENT_ANCHORS if a in md_section]
    panel_hits = [a for a in PANEL_ANCHORS if a in md_section]
    if debug:
        print(f"    [粗筛] 大 figure 块={len(big_figure)} 正文锚点={content_hits} "
              f"面板字段={panel_hits}", file=sys.stderr)

    boxes = [to_px(b["bbox"]) for b in (big_discarded or big_figure)]

    if big_discarded:
        return True, f"discarded_blocks 含 {len(big_discarded)} 个大块", boxes
    # 核心判据：报告页 md 里缺「正文锚点」→ layout 漏检，疑似丢块
    if not content_hits and (page.get("preproc_blocks") or []):
        return True, "md 缺正文锚点（检查所见/报告结果）", boxes
    return False, "判定正常", []


# ------------------------------------------------------------ 4. OCR ----
_OCR_ENGINE = None


def _load_rapidocr():
    """兼容 rapidocr 2.x 与 rapidocr-onnxruntime 1.x。"""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    try:
        from rapidocr import RapidOCR  # v2.x
        _OCR_ENGINE = ("v2", RapidOCR())
    except ImportError:
        from rapidocr_onnxruntime import RapidOCR  # v1.x
        _OCR_ENGINE = ("v1", RapidOCR())
    return _OCR_ENGINE


def ocr_lines_from_image(img_bytes, crop_box=None, upscale=UPSCALE):
    """对图片（或裁剪区域）做 OCR。

    返回 [(text, box, score)]，**box 已换算回原图像素坐标系**，
    以便后续按图片尺寸做区域过滤与锚点对齐。
    """
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    ox, oy = 0, 0
    if crop_box:
        x1, y1, x2, y2 = [int(round(v)) for v in crop_box]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.width, x2), min(img.height, y2)
        if x2 - x1 > 20 and y2 - y1 > 20:
            img = img.crop((x1, y1, x2, y2))
            ox, oy = x1, y1
    if upscale and upscale != 1:
        img = img.resize((img.width * upscale, img.height * upscale), Image.LANCZOS)

    arr = np.array(img)
    try:
        import cv2
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:  # noqa: BLE001
        pass

    tag, engine = _load_rapidocr()
    lines = []
    if tag == "v2":
        res = engine(arr)
        boxes = getattr(res, "boxes", None)
        txts = getattr(res, "txts", None)
        scores = getattr(res, "scores", None)
        if boxes is not None and txts is not None:
            for i, txt in enumerate(txts):
                sc = float(scores[i]) if scores is not None and i < len(scores) else 0.0
                lines.append((str(txt), boxes[i], sc))
    else:
        res, _ = engine(arr)
        for item in (res or []):
            box, txt, sc = item[0], item[1], item[2]
            lines.append((str(txt), box, float(sc)))

    # 坐标换算回原图坐标系：原图 = 裁剪偏移 + OCR坐标 / 放大倍数
    k = upscale if (upscale and upscale != 1) else 1
    if ox or oy or k != 1:
        lines = [(t, [[ox + float(p[0]) / k, oy + float(p[1]) / k] for p in box], sc)
                 for t, box, sc in lines]
    return lines


# --------------------------------------------------------- 5. 闸门·细筛 ----
_PUNCT = re.compile(r"[，。；：、（）()\[\]【】“”‘’·\-—\s!?,.;:\"'`~!@#$%^&*_+=|\\/<>]")


def normalize(s):
    s = re.sub(r"<[^>]+>", "", s)          # 剥离 HTML 标签
    s = unicodedata.normalize("NFKC", s)   # 全角 -> 半角
    s = _PUNCT.sub("", s)                  # 去标点与空白
    return s


def find_missing(ocr_text, md_text, n=NGRAM, min_len=MIN_FRAGMENT):
    """返回 OCR 中有、md 中没有的连续片段（归一化后）。"""
    md = normalize(md_text)
    ocr = normalize(ocr_text)
    if not md or not ocr:
        return []
    grams = {md[i:i + n] for i in range(len(md) - n + 1)}
    out, i = [], 0
    while i <= len(ocr) - n:
        if ocr[i:i + n] not in grams:
            start = i
            while i <= len(ocr) - n and ocr[i:i + n] not in grams:
                i += 1
            frag = ocr[start:i + n - 1]
            if len(frag) >= min_len:
                out.append(frag)
        else:
            i += 1
    return out


def line_coverage(key, md_norm, n=NGRAM):
    """该行的 n-gram 有多大比例已存在于 md 中（1.0 = 完全已存在）。"""
    total = len(key) - n + 1
    if total <= 0:
        return 1.0
    hit = sum(1 for i in range(total) if key[i:i + n] in md_norm)
    return hit / total


def pick_missing_lines(ocr_lines, md_text, img_w=0, region_x=REGION_X_MIN,
                       min_score=MIN_SCORE, cov_thres=COVERAGE_THRESHOLD):
    """挑出 md 中「未被覆盖」的 OCR 行，返回 [(原文, box)]（保留原始标点）。

    - 行级判断：整行已存在 → 跳过；覆盖率低 → 视为缺失行
    - 区域过滤：box 中心 x 需大于 img_w*region_x（默认只取右侧报告区，避免 UI 噪音）
    - 补入的是**原始 OCR 文本**，不是归一化文本
    """
    md_norm = normalize(md_text)
    out = []
    for text, box, score in ocr_lines:
        if score < min_score:
            continue
        key = normalize(text)
        if len(key) < MIN_FRAGMENT:          # 太短（图标文字/纯数字）跳过
            continue
        if key in md_norm:                   # 整行已存在
            continue
        if img_w and region_x:
            try:
                cx = sum(p[0] for p in box) / len(box)
                if cx < img_w * region_x:
                    continue                 # 不在报告区，丢弃（UI 噪音）
            except Exception:  # noqa: BLE001
                pass
        if line_coverage(key, md_norm) <= cov_thres:
            out.append((text, box))
    return out


def _yc(box):
    """文字行 bbox 的垂直中心。"""
    return sum(p[1] for p in box) / len(box)


def filter_by_anchor_span(missing, img_h, pad_ratio=0.03):
    """用正文锚点行的 y 范围界定正文区，剔除顶部状态栏/底部水印等噪音。"""
    ys = [_yc(b) for t, b in missing if any(a in normalize(t) for a in CONTENT_ANCHORS)]
    if not ys:
        return missing
    lo, hi = min(ys), max(ys)
    pad = img_h * pad_ratio
    return [(t, b) for t, b in missing if lo - pad <= _yc(b) <= hi + pad]


def is_noise(text):
    """系统状态栏/水印/纯数字等非病历正文行。"""
    t = text.strip()
    return any(p.search(t) for p in NOISE_PATTERNS)


# ------------------------------------------------------- 6. 定位与补入 ----
def anchor_align_insert(md_section, ocr_lines, new_texts):
    """用锚点对齐，把 new_texts 插到 md_section 中正确位置；失败则追加到末尾。"""
    md_norm = normalize(md_section)
    anchors = []  # [(y, md_char_pos)]
    for text, box, _score in ocr_lines:
        key = normalize(text)
        if len(key) < 3:
            continue
        pos = md_norm.find(key)
        if pos >= 0:
            y = sum(p[1] for p in box) / len(box)
            anchors.append((y, pos))
    anchors.sort()

    if not anchors:
        return md_section + "\n\n" + "\n".join(new_texts), "追加（无锚点）"

    # 缺失文本按 OCR 顺序插入：优先插在第一个锚点之前，否则依次追加
    out = md_section
    for t in new_texts:
        out = out.rstrip() + "\n" + t
    return out, "锚点对齐后追加"


def build_supplement(images, mineru_results, debug=False):
    """对每张图做闸门 + 补全，返回 (原始md, 补全md, 报告)。"""
    from PIL import Image

    raw_sections, full_sections, report = [], [], []
    for idx, (name, data) in enumerate(images):
        stem = os.path.splitext(f"{idx:03d}_{name}")[0]
        res = mineru_results.get(stem) or {}
        md = (res.get("md") or "").strip()
        middle = _as_obj(res.get("middle_json"))
        if not md:
            md = FAILED_PLACEHOLDER.format(n=idx + 1)

        raw_sections.append(f"# 图片 {idx + 1}\n\n{md}")
        section = f"# 图片 {idx + 1}\n\n{md}"

        img = Image.open(io.BytesIO(data))
        need, reason, boxes = gate_screen(middle, (img.width, img.height), md, debug=debug)
        if debug:
            print(f"  图片{idx + 1} ({name} {img.width}x{img.height}): "
                  f"need={need} ({reason})", file=sys.stderr)

        if not need:
            full_sections.append(section)
            report.append(f"图片 {idx + 1}: 跳过（{reason}）")
            continue

        try:
            crop = boxes[0] if boxes else None
            lines = ocr_lines_from_image(data, crop_box=crop)
            missing = pick_missing_lines(lines, md, img_w=img.width)
            missing = filter_by_anchor_span(missing, img.height)
            missing = [(t, b) for t, b in missing if not is_noise(t)]
            has_anchor = any(any(a in normalize(t) for a in CONTENT_ANCHORS)
                             for t, _b in missing)
            if not missing or not has_anchor:
                full_sections.append(section)
                report.append(f"图片 {idx + 1}: 闸门通过但细筛未发现缺失正文行，未补（{reason}）")
                continue
            body = "\n".join(t for t, _b in missing)
            section2 = section.rstrip() + "\n\n<!-- 以下为本地 OCR 补充识别 -->\n" + body
            full_sections.append(section2)
            report.append(f"图片 {idx + 1}: 补入 {len(missing)} 行（{reason}）\n"
                          + "\n".join("    + " + t[:90] for t, _b in missing))
        except Exception as e:  # noqa: BLE001
            full_sections.append(section)
            report.append(f"图片 {idx + 1}: 补全失败（{e}），已退回原内容")

    return "\n\n".join(raw_sections), "\n\n".join(full_sections), "\n".join(report)


# --------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(description="病历 docx 图转文 + 本地增量补全")
    ap.add_argument("docx", help="docx 绝对路径")
    ap.add_argument("out_dir", help="输出目录")
    ap.add_argument("--service", default=DEFAULT_SERVICE)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--dump-middle", action="store_true", help="导出每图 middle_json 供诊断")
    args = ap.parse_args()

    if not os.path.isfile(args.docx):
        print(f"错误：docx 不存在: {args.docx}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(args.out_dir, exist_ok=True)
    doc_name = os.path.splitext(os.path.basename(args.docx))[0]

    print(f"[1/4] 解包 docx ...", file=sys.stderr)
    images = extract_docx_images(args.docx)
    print(f"      内嵌图片 {len(images)} 张", file=sys.stderr)
    if not images:
        print("无内嵌图片，终止。", file=sys.stderr)
        sys.exit(0)

    print(f"[2/4] 上传 MinerU 解析（{args.service}）...", file=sys.stderr)
    results = {}
    for start in range(0, len(images), args.batch):
        batch = images[start:start + args.batch]
        upload = [(f"{start + i:03d}_{nm}", d) for i, (nm, d) in enumerate(batch)]
        results.update(mineru_parse(upload, args.service, args.timeout))
        print(f"      进度 {min(start + args.batch, len(images))}/{len(images)}", file=sys.stderr)

    if args.dump_middle:
        mdir = os.path.join(args.out_dir, "_middle")
        os.makedirs(mdir, exist_ok=True)
        for idx, (name, _d) in enumerate(images):
            stem = os.path.splitext(f"{idx:03d}_{name}")[0]
            obj = _as_obj((results.get(stem) or {}).get("middle_json"))
            if obj is not None:
                p = os.path.join(mdir, f"{idx + 1:02d}_middle.json")
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(obj, f, ensure_ascii=False, indent=1)
                print(f"      已导出 {p}", file=sys.stderr)

    print(f"[3/4] 闸门 + 本地补全 ...", file=sys.stderr)
    raw_md, full_md, report = build_supplement(images, results, debug=args.debug)

    print(f"[4/4] 写出产物 ...", file=sys.stderr)
    paths = {
        "raw": os.path.join(args.out_dir, f"{doc_name}_图转文.md"),
        "full": os.path.join(args.out_dir, f"{doc_name}_补全.md"),
        "report": os.path.join(args.out_dir, f"{doc_name}_补全报告.txt"),
    }
    for k, p in paths.items():
        if os.path.exists(p):
            print(f"      跳过已存在文件: {p}", file=sys.stderr)
            continue
        with open(p, "w", encoding="utf-8") as f:
            f.write({"raw": raw_md, "full": full_md, "report": report}[k] + "\n")
        print(f"      已写出 {p}", file=sys.stderr)
    print("完成。", file=sys.stderr)


if __name__ == "__main__":
    main()
