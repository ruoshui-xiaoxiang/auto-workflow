import zipfile, re, os, glob, sys
SRC = r"E:\创作\武昭君仪"
OUT = r"D:\AIWorkflow\tmp\wzy\txt"
os.makedirs(OUT, exist_ok=True)
def dtext(p):
    with zipfile.ZipFile(p) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.split(r"</w:p>", xml)
    lines = []
    for pa in paras:
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", pa, re.S))
        t = re.sub(r"<[^>]+>", "", t)
        t = t.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">").replace("&quot;",'"').replace("&apos;","'")
        if t.strip():
            lines.append(t.strip())
    return "\n\n".join(lines)
for f in sorted(glob.glob(os.path.join(SRC, "*.docx"))):
    s = dtext(f)
    base = os.path.splitext(os.path.basename(f))[0]
    dst = os.path.join(OUT, base + ".txt")
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(s)
    print(base, len(s))
