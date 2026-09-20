#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整图复核（图片层医院名扫描）。

背景：EHR 截图的**窗口标题栏**（如 `XX医院-医技工作站`）既不被 MinerU 转为文本，
也不落在补全采纳区（补全只取右侧正文区），因此文本层永远不含该串。
本脚本对 docx 内嵌图片做整图 rapidocr，用「医院|医科|附属|卫生|保健」扫一遍，
把命中词并入 --manual 词表（掩码空操作，但会记入敏感词清单，便于向用户说明）。

用法: python image_scan.py <docx路径> <输出命中txt>
仅本地推理（0 网络）。stdout 只打印计数。
"""
import io
import re
import sys
import zipfile

import numpy as np
from PIL import Image

HOSP_PAT = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9（）()·\-—]{2,25}?(?:医院|医科|附属|卫生院|卫生服务中心|保健院|门诊部|诊所|卫生室)")


def main() -> int:
    docx_path, out_path = sys.argv[1], sys.argv[2]
    from rapidocr import RapidOCR
    engine = RapidOCR()

    hits = {}
    with zipfile.ZipFile(docx_path) as z:
        names = [n for n in z.namelist()
                 if n.startswith("word/media/") and n.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
        for i, n in enumerate(sorted(names), 1):
            try:
                img = Image.open(io.BytesIO(z.read(n))).convert("RGB")
            except Exception:  # noqa: BLE001
                continue
            if max(img.size) < 200:
                continue
            big = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
            res = engine(np.array(big))
            txts = list(getattr(res, "txts", None) or [])
            for t in txts:
                for m in HOSP_PAT.finditer(str(t)):
                    w = m.group(0)
                    if len(w) >= 4:
                        hits.setdefault(w, set()).add(n)

    with open(out_path, "w", encoding="utf-8") as f:
        for w in sorted(hits, key=lambda x: (-len(x), x)):
            f.write(w + "\n")
    print("%s: 图片 %d 张 | 命中医院类词 %d 个 -> %s"
          % (docx_path, len(names), len(hits), out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
