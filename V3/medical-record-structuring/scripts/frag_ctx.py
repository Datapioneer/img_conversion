import re, sys
md, kw = sys.argv[1], sys.argv[2]
text = open(md, encoding="utf-8").read()
words = [w.strip() for w in open(kw, encoding="utf-8") if w.strip()]
names = [w for w in words if 2 <= len(w) <= 6 and re.fullmatch(r"[\u4e00-\u9fa5]+", w)]
seen = set()
for w in names:
    for L in range(len(w)-1, 1, -1):
        for i in range(0, len(w)-L+1):
            s = w[i:i+L]
            if len(s) >= 2 and s in text and s not in seen:
                seen.add(s)
                for m in list(re.finditer(re.escape(s), text))[:2]:
                    a, b = max(0, m.start()-12), min(len(text), m.end()+12)
                    print("[%s] %s" % (s, text[a:b].replace("\n", " ")))
