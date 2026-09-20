import re, sys
src, out = sys.argv[1], sys.argv[2]
kws = sys.argv[3:]
R = int(sys.argv[3].split("=")[0]) if False else None
text = re.sub(r"[ \t]+", " ", open(src, encoding="utf-8").read())
with open(out, "w", encoding="utf-8") as f:
    for kw in kws:
        f.write("########## %s ##########\n" % kw)
        n = 0
        for m in re.finditer(re.escape(kw), text):
            a, b = m.start(), min(len(text), m.end() + 2200)
            f.write("----\n%s\n" % text[a:b].replace("\n", " ⏎ "))
            n += 1
            if n >= 2: break
        if n == 0: f.write("(无命中)\n")
print("ok ->", out)
