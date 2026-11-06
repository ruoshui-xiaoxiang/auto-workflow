# -*- coding: utf-8 -*-
r"""批 15 落盘台：把 20 份 H3 稿按**句 id** 替换成英文形，写盘前跑六道验收，不过就不写。

为什么按句 id 而不是「读一遍重写一遍」：
  · 跨文件重复的公共段（基调句、站位句、不变量句…）必须**同一串英文**——靠句文本当键去重；
  · 台词逐字不动——`<d>…</d>` 在切句时被单独保护，翻译表里带出的台词必须与原文逐字相等；
  · 数字保真——时间轴／帧数／尺寸的数字串逐一对上（这道检当场抓到过我自己的笔误）。

用法：
    python h3_rewrite_apply.py --check     # 只验收，不写盘（默认）
    python h3_rewrite_apply.py --write     # 验收全过后备份＋写盘
"""
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BS = chr(92)
MANIFEST = os.path.join(HERE, "h3_rewrite_manifest.json")
TABLES = ["h3_shared_en.json", "h3_en_group_p.json", "h3_en_group_k.json", "h3_en_group_d.json"]
BACKUP = r"E:\本地工作流规范手册\99_维护\_改前备份_20261003_正文英译"

CJK = re.compile(u"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
DLG = re.compile(r"<d>.*?</d>", re.S)
SENT = re.compile(u"(?<=[。\u3002\uFF1B])|\\n")
NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?")
# 官方风格 token 里自带的数字不算「稿内量出来的数」：`2D-animated`／`3D CG`
DIM = re.compile(r"\b[23]D\b")
BAD_WORDS = [r"\bdolly\b", r"\bcrane\b", r"\bsteadicam\b", r"\bstabilizer\b", r"\bslider\b",
             r"\bgimbal\b", r"\bdrone\b", r"\btripod\b", r"\bhandheld camera\b",
             r"\bguns?\b", r"\brifles?\b", r"\bpistols?\b", r"\bfirearms?\b", r"\bbullets?\b",
             r"\bshotguns?\b", r"\bspears?\b", r"\blance[sd]?\b"]
CUT_MARKER = r"\[Shot\s*\d+\]\s*At\s+\d\d:\d\d\.\d\d\d"

# 官方 §4.3 的幅度只有 `with small amplitude`／`with large amplitude` 两档、速度只有
# `at slow speed`／`at fast speed` 两档，且明写「**中档幅度与常速通常省略**」。
# 译文里冒出来的 `medium amplitude`／`medium-speed` 是**我们替厂商造的第三档**
# ⇒ 按 R2-16 第①态（照官方值，不改严也不改松）归一化掉，而不是让它进真源。
MEDIUM = [
    (re.compile(r",?\s*with (?:medium|moderate) amplitude", re.I), ""),
    (re.compile(r"\b(?:Medium|medium|moderate)-amplitude,\s*(?:medium|normal)-speed,\s*", re.I), ""),
    (re.compile(r"\b(?:Medium|medium|moderate) amplitude,\s*(?:medium|normal) speed,\s*", re.I), ""),
    (re.compile(r",?\s*at (?:medium|normal) speed", re.I), ""),
]


def normalize_official_values(text):
    """把自造的第三档幅度／速度去掉（官方明示中档与常速省略），并收拾标点。"""
    out = text
    for pat, rep in MEDIUM:
        out = pat.sub(rep, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    return out.strip()



def sid(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def line_pieces(line):
    """把一行切成句段，返回 [(段文本(带台词保护后的键原文), 原样片段)]，顺序与 prep 一致。"""
    out = []
    for raw in SENT.split(line):
        if raw is None:
            continue
        s = raw.strip()
        if not s:
            continue
        out.append(s)
    return out


def key_of(piece):
    body = DLG.sub(lambda m: " " + m.group(0) + " ", piece)
    return sid(body), body


def load_tables():
    en = {}
    dup = []
    for name in TABLES:
        p = os.path.join(HERE, name)
        if not os.path.isfile(p):
            print(u"!! 缺译法表：%s" % p)
            continue
        d = json.load(io.open(p, encoding="utf-8"))
        for k, v in d.items():
            if k.startswith("_"):
                continue
            if k in en and en[k] != v:
                dup.append(k)
            en[k] = normalize_official_values(v)      # 自造的第三档幅度／速度在这里就抹掉
    return en, dup


def zh_of(doc, k):
    return doc["segments"][k]["zh"]


def strip_dialogue(text):
    """抠掉台词区。**含半截 tag**：prep 的切句会把 `<d>…</d>` 切成两段，
    只剥成对 `<d>…</d>` 会留下台词正文，被误判成「英文里仍有中文」（假阳）。
    但只有**标签不平衡**时才敢整段裁到行尾／行首——否则会把台词后面真正的中文一起藏掉（假阴）。
    """
    out = DLG.sub(" ", text)
    if out.count("<d>") != out.count("</d>"):
        out = re.sub(r"<d>.*\Z", " ", out, flags=re.S)        # 前半段：标签开了没闭
        out = re.sub(r"\A.*?</d>", " ", out, flags=re.S)     # 后半段：标签闭了没开
    return out


def check(doc, en, dup):
    """六道验收，返回问题清单（非空＝不写盘）。"""
    bad = []
    if dup:
        bad.append(u"两张表对同一个句 id 给了不同译文（%d 个）：%s" % (len(dup), dup[:4]))
    need = set()
    for f in doc["files"]:
        for _ln, k in f["segments"]:
            need.add(k)
    miss = sorted(need - set(en))
    if miss:
        bad.append(u"缺译文 %d 条：%s" % (len(miss), [zh_of(doc, k)[:26] for k in miss[:5]]))
    for k in sorted(need & set(en)):
        z, e = zh_of(doc, k), en[k]
        if CJK.search(strip_dialogue(e)):
            bad.append(u"%s 英文里仍有中日韩字符（台词区之外）：%s" % (k, CJK.findall(strip_dialogue(e))[:6]))
        if NUM.findall(strip_dialogue(z)) != NUM.findall(DIM.sub("", strip_dialogue(e))):
            bad.append(u"%s 数字不保真：%s → %s" % (k, NUM.findall(z)[:6], NUM.findall(e)[:6]))
        for m in DLG.findall(z):
            if m not in e:
                bad.append(u"%s 台词被改动或缺失：%s" % (k, m[:40]))
        low = e.lower()
        for pat in BAD_WORDS:
            if re.search(pat, low):
                bad.append(u"%s 出现禁用词 %s：%s" % (k, pat, e[:60]))
        if re.search(CUT_MARKER, e):
            bad.append(u"%s 擅自加了官方切点：%s" % (k, e[:60]))
        if not e.strip():
            bad.append(u"%s 译文为空" % k)
    return bad


def rebuild(doc, en):
    """按**原文精确子串**逐段替换（不是把译文拼起来重排）。

    为什么：prep 的切句会把 `<d>…</d>` 从中间切断（`……说：<d>[中文] 站住。` / `背上裹的什么？</d>——`）。
    如果把 pieces 用空格 join 回去，台词里就会凭空多一个空格 ⇒ 「台词逐字不动」这条验收直接破。
    按原文定位替换则半截 tag 原样落回原位，台词字节级不变。
    """
    out = {}
    for f in doc["files"]:
        src = io.open(f["path"], encoding="utf-8").read()
        lines = src.split("\n")
        per_line = {}
        for ln, k in f["segments"]:
            per_line.setdefault(ln, []).append(k)
        new_lines = []
        for i, line in enumerate(lines, 1):
            ks = per_line.get(i)
            if not ks:
                new_lines.append(line)
                continue
            pieces = line_pieces(line)
            # 游标定位每片原文的位置（原文顺序＝切句顺序，天然单调递增）
            spans, cur = [], 0
            for piece in pieces:
                at = line.find(piece, cur)
                if at < 0:
                    spans = None
                    break
                spans.append((at, at + len(piece)))
                cur = at + len(piece)
            if spans is None or len(spans) != len(pieces):
                # 定位失败＝结构对不上，这份稿子整行不动，交给验收喊出来
                problems_holder.append(u"%s 第 %d 行无法按原文定位，整行未改"
                                       % (os.path.basename(f["path"]), i))
                new_lines.append(line)
                continue
            new_line = line
            for (a, b), piece, k in sorted(zip(spans, pieces, ks), key=lambda x: -x[0][0]):
                new_line = new_line[:a] + en.get(k, piece) + new_line[b:]
            new_lines.append(respace(new_line))
        out[f["path"]] = "\n".join(new_lines)
    return out


def respace(line):
    """中文句号后本来不带空格，换成英文后就粘在一起了（`grain.Rendering`）。

    只补**句界空格**，不改内容；而且**只要这一段沾到台词就一个字节都不动**——
    prep 的切句会把 `<d>…</d>` 切成两半，半截里那个 `。` 是台词正文，
    动它就等于改台词，会被文件级的字节比对当场拦下。
    """
    parts = re.split(r"(<d>.*?</d>)", line, flags=re.S)
    out = []
    for seg in parts:
        if u"<d>" in seg or u"</d>" in seg:
            out.append(seg)
            continue
        seg = seg.replace(u"；", u"; ").replace(u"。", u". ")
        seg = re.sub(r"([a-z\)\].,;\"])([A-Z])", u"\\1 \\2", seg)
        seg = re.sub(r"\s+([,.;:])", u"\\1", seg)
        seg = re.sub(r"([.;:])\s*(?=[.;:])", u"", seg)
        seg = re.sub(r"[ \t]{2,}", u" ", seg)
        out.append(seg)
    return u"".join(out).strip()



problems_holder = []


def main():
    doc = json.load(io.open(MANIFEST, encoding="utf-8"))
    en, dup = load_tables()
    bad = check(doc, en, dup)
    print(u"译法表合计 %d 条｜待覆盖句 id %d 条" % (len(en), len({k for f in doc['files'] for _, k in f['segments']})))
    if bad:
        print(u"!! 验收不过 %d 处，**不写盘**：" % len(bad))
        for m in bad[:25]:
            print(u"   - " + m)
        if len(bad) > 25:
            print(u"   …另有 %d 处" % (len(bad) - 25))
        return 1
    new = rebuild(doc, en)
    if problems_holder:
        print(u"!! 定位失败 %d 处，**不写盘**：" % len(problems_holder))
        for m in problems_holder[:12]:
            print(u"   - " + m)
        return 1
    # 整篇级复核：语言闸、台词条数、字段结构
    sys.path.insert(0, HERE)
    import prompt_format as PF
    problems = []
    for p, t in new.items():
        hits = PF.non_english_spans(t)
        if hits:
            problems.append(u"%s 仍有非英文 %d 处（例：第 %d 行 %s）"
                            % (os.path.basename(p), len(hits), hits[0][0], hits[0][1][:50]))
        src = io.open(p, encoding="utf-8").read()
        if DLG.findall(src) != DLG.findall(t):
            problems.append(u"%s **台词不再逐字相等**（改前 %r ／ 改后 %r）"
                            % (os.path.basename(p), DLG.findall(src)[:1], DLG.findall(t)[:1]))
        if PF.detect(t) != PF.detect(src):
            problems.append(u"%s 格式形态变了（%s → %s）"
                            % (os.path.basename(p), PF.detect(src), PF.detect(t)))
        for fld in PF.BASE_FIELDS + PF.REF2VA_ONLY:
            if src.count(fld) != t.count(fld):
                problems.append(u"%s 字段 %s 出现次数变了" % (os.path.basename(p), fld))
    # 最后一道：拿现役 G7 逐份跑一遍，确认这次改写没新增拦截点
    try:
        sys.path.insert(1, r"D:\AIWorkflow" + BS + "tools")
        from check_preflight import run_checks
        for p, t in sorted(new.items()):
            src = io.open(p, encoding="utf-8").read()
            base = {"refs": ["a.png"], "characters": "none", "only": ["G7"],
                    "prompt_kind": ("h3_ref2va" if PF.detect(t) == "h3_ref2va" else "h3_i2va"),
                    "provider": "local"}
            e_old = {t for lv, g, t_ in run_checks(dict(base, prompt=src)).items
                     if g == "G7" and lv == "error"}
            r_new = run_checks(dict(base, prompt=t))
            e_new = {t_ for lv, g, t_ in r_new.items if g == "G7" and lv == "error"}
            extra = e_new - e_old
            if extra:
                problems.append(u"%s G7 新增 error %d 条：%s"
                                % (os.path.basename(p), len(extra), list(extra)[0][:90]))
    except Exception as e:
        problems.append(u"G7 复核没跑成（%s）⇒ 取不到不等于通过" % e)
    if problems:
        print(u"!! 整篇复核不过 %d 处，**不写盘**：" % len(problems))
        for m in problems[:20]:
            print(u"   - " + m)
        return 1
    print(u"✓ 六道验收全过（句级：译文齐全／数字保真／台词逐字／禁词零／无切点／无残留汉字；"
          u"整篇级：语言闸 0 命中／字段与格式不变）｜%d 份待写" % len(new))
    if "--write" not in sys.argv:
        print(u"（这是 --check 模式，未写盘。要落盘加 --write）")
        return 0
    os.makedirs(BACKUP, exist_ok=True)
    rows = []
    for p, t in sorted(new.items()):
        name = os.path.basename(os.path.dirname(p)) + "__" + os.path.basename(p)
        dst = os.path.join(BACKUP, name)
        shutil_copy2(p, dst)
        h1 = hashlib.sha256(io.open(p, "rb").read()).hexdigest()
        h2 = hashlib.sha256(io.open(dst, "rb").read()).hexdigest()
        assert h1 == h2, (p, h1, h2)
        rows.append((name, h1, os.path.getsize(p)))
        io.open(p, "w", encoding="utf-8", newline="\n").write(t)
    lines = [u"# 改前备份 · 批 15 · H3 正文英译（待裁-14 落地）", "",
             u"用户裁定：「全改（21 份）但不重跑」——实际改面 **20 份手改真源**＋1 份派生合订本（重生成）。",
             u"**不重跑**：改完只算合官方形，英文正文在本机的效果没有实跑证据。", "",
             u"| 副本 | 改前 sha256 | 字节 |", u"|---|---|---|"]
    for n, h, sz in rows:
        lines.append(u"| `%s` | `%s` | %d |" % (n, h, sz))
    io.open(os.path.join(BACKUP, u"MANIFEST.md"), "w", encoding="utf-8",
            newline="\n").write("\n".join(lines) + "\n")
    print(u"✓ 已写 %d 份，改前哈希逐份实比，备份在 %s" % (len(rows), BACKUP))
    return 0


def shutil_copy2(a, b):
    import shutil
    shutil.copy2(a, b)


if __name__ == "__main__":
    sys.exit(main())
