"""验收：患者名归零 + 词表无死词 + 脱敏残留 0 + 掩码字符数。

用法:
  python chk_mask.py                       # 沿用旧默认批次（兼容历史调用）
  python chk_mask.py <输出根目录> <病历名清单txt>
  # 病历名清单txt 每行一个「病历名」（= docx 文件名去扩展名，= 输出目录名）
"""
import os
import sys

P = "C:/Users/dongyi.qiu/.workbuddy/skills/medical-record-structuring/scripts"
sys.path.insert(0, P)
from sensitive import patient_name_from_filepath  # noqa: E402

if len(sys.argv) >= 3:
    base = sys.argv[1]
    docs = [l.strip() for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
else:
    base = "D:/wd2/output"
    docs = ["703530 无胱抑素 李雪飞", "703543 无胱抑素 邢云", "703641 无胱抑素 陈川新",
            "钟广章", "703386 无胱抑素 李军"]

for n in docs:
    d = os.path.join(base, n)
    src = open(os.path.join(d, n + "_补全.md"), encoding="utf-8").read()
    msk = open(os.path.join(d, n + "_脱敏.md"), encoding="utf-8").read()
    pn = patient_name_from_filepath(os.path.join(d, n + "_补全.md"))
    words = [l.strip() for l in open(os.path.join(d, "敏感词.txt"), encoding="utf-8") if l.strip()]
    hit_src = sum(1 for w in words if w in src)
    hit_msk = sum(1 for w in words if w in msk)
    print("%-22s 患者名=%s 原文=%d 脱敏后=%d | 词表=%d 原文命中=%d 脱敏残留=%d | 掩码字符=%d"
          % (n, pn, src.count(pn or "\0"), msk.count(pn or "\0"), len(words), hit_src, hit_msk,
             msk.count("\u2588")))
