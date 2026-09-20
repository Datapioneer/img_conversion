import re, sys
md, kw = sys.argv[1], sys.argv[2]
text = open(md, encoding="utf-8").read()
words = set(w.strip() for w in open(kw, encoding="utf-8") if w.strip())
ROLE = r"(?:检查人|申请人|申请者|术者|报告人|审核者|核对人|录入人|操作者|记录者|创建者|创建人|创健人|检验人|审核人|送检医师|检验医生|审核医生|手术医师|麻醉医师|治疗师|护士长)"
for m in re.finditer(ROLE + r"\s*[:：]\s*([\u4e00-\u9fa5]{2,6})", text):
    w = m.group(1)
    flag = "" if w in words else "  <== 不在词表"
    print("%s -> %s%s" % (m.group(0).replace("\n"," "), w, flag))
