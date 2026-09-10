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


def mask(text, words):
    """长词优先，字符间可夹任意空格的容错掩码，替换为等长 █。"""
    result = text
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
