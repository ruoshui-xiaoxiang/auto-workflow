# -*- coding: utf-8 -*-
"""提示词格式识别与分区（质检链路的共用底座）。

为什么要有这个文件
------------------
2026-09-28 起，提示词**按通道刻意切分成两套**，目的是避免混用：

  · 本地 H3 视频层     ＝ 官方 I2VA 骨架（首行逐字指令 + 恰三个字段 + `[Shot 1]` 正文）
  · 云端 SD 通道       ＝ 中文十块模板（【生成目标】…【风格与光影】）
  · 本地 H3 Ref2VA     ＝ 官方全参考六段（subject_definitions … non_diegetic_music）
  · 图片（首帧/定妆）  ＝ 无强制格式

而原先的质检判定普遍靠**中文块名**把提示词切成「视觉描述区 / 台词区 / 镜头区」，
再在各区上跑词表。骨架格式里**没有任何【】** ⇒ 这些判定会静默退化成
"整篇当一个区"或"查不到 ⇒ 判通过"——**假阴比假阳更危险**，因为它报的是 ok。

本模块只做一件事：**先认格式，再把六类职责区切出来**，让所有质检脚本共用同一套分区口径。
判据本身（哪算违规）仍留在各脚本里。

用法
----
    from prompt_format import detect, regions, beats, mixing
    k = detect(text)                 # 'h3_skeleton' / 'h3_ref2va' / 'sd_tenblock' / 'plain'
    r = regions(text)                # {'body':…, 'dialog':[…], 'sound':…, 'camera':…, 'invariant':…, 'style':…, 'kind':k}
    bs = beats(text)                 # [(起秒, 止秒, 该拍文本), …]，骨架与十块都能取到
    bad = mixing(text, want='h3')    # 混用清单（空＝没混）

只读工具：不写文件、不改提示词。
"""
import re

# ---------------------------------------------------------------- 常量与指纹

SKELETON_INSTRUCTION = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced.")

BASE_FIELDS = ("integrated_multimodal_description:",
               "overall_soundscape:",
               "non_diegetic_music:")

REF2VA_FIELDS = ("subject_definitions:", "summary:", "retention_analysis:",
                 "detailed_description:", "overall_soundscape:",
                 "non_diegetic_music:")

# 六段里**独有**的严格标记：基础骨架（三字段）绝不会含这些。
# 判"骨架里混进六段"只能看这一组——用全量 REF2VA_FIELDS 会把骨架自带的
# overall_soundscape / non_diegetic_music 误判成混用（A 线 23 镜全会假报，实测踩过）。
# `summary:` 也太通用（正文可能出现该英文词），故不入判据。
REF2VA_ONLY = ("subject_definitions:", "retention_analysis:", "detailed_description:")

TEN_BLOCKS = ("生成目标", "参考素材职责", "未采用素材", "主体与关系", "场景与环境",
              "事件脚本", "保持一致", "镜头", "声音", "风格与光影")

# 必填核心五块（只属云端 SD 通道）
CORE_BLOCKS = ("主体与关系", "事件脚本", "保持一致", "镜头", "声音")

BLOCK_RE = re.compile(u"【([^】]{1,12})】")

# 目标通道
H3_CHANNELS = ("h3", "h3_skeleton", "h3_ref2va")

# ---------------------------------------------------------------- 格式识别


def _has_block(text):
    return bool(BLOCK_RE.search(text))


def detect(text):
    """返回 'h3_skeleton' / 'h3_ref2va' / 'sd_tenblock' / 'plain'。

    判据从严到宽：六段 > 基础三字段骨架 > 中文十块 > 无格式（图片/其它）。
    同时含两套指纹时**优先报混用**（调用方应先跑 mixing()），这里仍按"更具体的那套"归类。
    """
    if not text:
        return "plain"
    t = text.strip()
    n_ref = sum(1 for f in REF2VA_ONLY if f in t)
    n_base = sum(1 for f in BASE_FIELDS if f in t)
    if n_ref >= 2:                       # subject_definitions / retention_analysis / detailed_description 任两个
        return "h3_ref2va"
    if n_base == 3 and (SKELETON_INSTRUCTION in t or "[Shot" in t):
        return "h3_skeleton"
    if n_base == 3:
        return "h3_skeleton"          # 缺首行指令的骨架：格式仍是骨架，指令缺失由 G7 报
    if _has_block(t):
        return "sd_tenblock"
    return "plain"


def looks_like_h3(text):
    return detect(text) in ("h3_skeleton", "h3_ref2va")


# ---------------------------------------------------------------- 值抽取


def field_value(text, field):
    """取 `field:` 的值。骨架里字段名与值**分行**，十块/一行式里同行 ⇒ 两种都吃。"""
    if field not in text:
        return ""
    after = text.split(field, 1)[1]
    line_end = after.find("\n")
    first = after if line_end < 0 else after[:line_end]
    if first.strip():
        return first.strip()
    # 值在下一行（甚至空一行后）
    rest = after[line_end + 1:] if line_end >= 0 else ""
    for ln in rest.split("\n"):
        if ln.strip():
            return ln.strip()
        if ln.strip() == "" and rest.count("\n") > 4:
            continue
    return ""


def _block_span(text, name):
    """返回【name】块的内容（到下一个任意【】为止）。没有该块返回 ''。"""
    m = re.search(u"【" + re.escape(name) + u"】", text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = BLOCK_RE.search(rest)
    return rest[:nxt.start()] if nxt else rest


def _shot_body(text):
    """骨架正文：`integrated_multimodal_description:` 之后、`overall_soundscape:` 之前。"""
    if "integrated_multimodal_description:" in text:
        seg = text.split("integrated_multimodal_description:", 1)[1]
        for stop in ("overall_soundscape:", "non_diegetic_music:"):
            if stop in seg:
                seg = seg.split(stop, 1)[0]
        return seg.strip()
    if "detailed_description:" in text:
        seg = text.split("detailed_description:", 1)[1]
        for stop in ("overall_soundscape:", "non_diegetic_music:"):
            if stop in seg:
                seg = seg.split(stop, 1)[0]
        return seg.strip()
    return ""


# 骨架正文里承担"非事件"职责的两段
# ⚠️ `Throughout:` 是**标签**：冒号必须在（漏冒号即不算标签）。
#    旧写法把冒号做成可选，在正文还是中文时无害（散文里不会出现 Throughout 这个词）；
#    10-03 正文英译后，现役 P1A 的散文里就有小写 `single shot throughout —`，
#    旧式从那个词起把后面**整段吞成不变量段** ⇒ 运镜/事件/风格三区全空、5 条规则一起降级
#    （判定漂移实测 12/20 份 §五 由 ok 掉 info）。
#    大小写仍不敏感：现役 4 份（K10v3／K11a／K11bv3／两头夹）写的就是小写 `throughout:`，
#    改成只认大写会把这 4 份的不变量段判空——回归对账实测抓到，别"顺手收紧"。
_THROUGHOUT_RE = re.compile(u"Throughout\\s*[：:]\\s*", re.I)
_CAMERA_HINT = (u"Push In", u"Pull Out", u"Truck", u"Pan", u"Tilt", u"Pedestal",
                u"Arc", u"Tracking", u"Static", u"Shake", u"Roll", u"POV", u"Zoom")


def _split_skeleton_body(body):
    """把骨架正文切成 风格段 / 事件段 / 运镜段 / 不变量段。

    骨架是"一条连续散文 + 固定位置挂固定职责"，所以只能按**位置与关键词**切：
      · 风格与光影 ＝ 正文开头到第一个时间戳（或 `[Shot 1]` 后的场景定位段）之前
      · 不变量     ＝ `Throughout:` 之后那一段（官方落点）
      · 运镜       ＝ 含受控运镜词、且出现在时间戳之后的那一句
      · 事件       ＝ 剩下的、带时间戳的部分
    切不准时的兜底原则：**宁可把整段算进视觉描述区**（词表闸照跑），
    不可把区域切成空 ⇒ 那会让所有判定静默通过。
    """
    t = body
    inv = ""
    m = _THROUGHOUT_RE.search(t)
    if m:
        inv = t[m.start():].strip()
        t = t[:m.start()].strip()

    # 按句切（中文句号/句号+空格），再按关键词归类
    parts = re.split(u"(?<=[。.!])\\s+", t)
    parts = [p.strip() for p in parts if p.strip()]
    cam, evt, style = [], [], []
    ts_re = re.compile(r"\d+\.\d+\s*[–-]\s*\d+\.\d+|At\s+\d\d:\d\d")
    for p in parts:
        if any(w in p for w in _CAMERA_HINT) and not ts_re.search(p):
            cam.append(p)
        elif ts_re.search(p):
            evt.append(p)
        elif not evt and not cam:
            style.append(p)          # 时间戳之前的都算质感/场景定位
        else:
            (evt if ts_re.search(p) or evt else style).append(p)
    body_only = u" ".join(evt) if evt else u" ".join(parts)
    return {"style": u" ".join(style), "camera": u" ".join(cam),
            "invariant": inv, "body": body_only, "all": t}


DLG_RE = re.compile(r"<d>(.*?)</d>|<d\s*/>", re.S)
DLG_CN_RE = re.compile(u"[“\"]([^”\"]{1,200})[”\"]")


def dialogues(text):
    """台词逐字清单。

    **口径按格式分治，不能一律退回引号**（实测踩到）：
      · 官方骨架 / 六段：台词的唯一载体是 `<d>[语言] …</d>`。中文正文里那些引号是
        **拟声词与强调**（"铮"的一声、"轰"的一声），拿它们当台词会把 0 台词的镜算成
        3 句 ⇒ 单元数虚高 ⇒ 假报超载（C 线 P3C 实测：`<d>` 0 个、引号 6 个，
        旧口径报 3 句台词、9.25 单元，据此判它"超载要返工"是错的）。
      · 中文十块 / 无格式稿：模板本身不要求 `<d>`，台词就写在引号里 ⇒ 才用引号兜。
    """
    out = [d.strip() for d in DLG_RE.findall(text) if d.strip()]
    if out or detect(text) in ("h3_skeleton", "h3_ref2va"):
        return out
    ev = _block_span(text, u"事件脚本") or text
    return [d.strip() for d in DLG_CN_RE.findall(ev) if d.strip()]


# 时间戳拍：`0.0–1.2 秒：…`（中文区间）／`0.0-1.2s:`（同一区间的英文形）
#           ／`[Shot 1] At 00:00.000: …`（官方毫秒切点，走 _BEAT_EN）
# ⚠️ 单位必须**同时认「秒」和 `s`**：10-03 正文英译后，现役 20 份的时间戳单位全是 `s`
#    （实测 65 处，无一例外），旧式硬写「秒」⇒ beats() 返回空表 ⇒
#    步数／收势／容量／时长四条规则一起掉成"判不了"（判定漂移实测 16/20 份）。
#    区间写法本身＝〔本层自写·官方未规定〕，与官方 §4.2 毫秒切点的取舍另待裁，不在这里定。
_UNIT = u"(?:秒|s(?![A-Za-z]))"        # `s` 后面不接字母，免得 `1.5sustain` 之类误撞
_BEAT_CN = re.compile(r"(\d+\.\d+)\s*[–-]\s*(\d+\.\d+)\s*" + _UNIT +
                      r"\s*[：:]?\s*(.*?)(?=\d+\.\d+\s*[–-]\s*\d+\.\d+\s*" + _UNIT + r"|$)", re.S)
_BEAT_EN = re.compile(r"\[Shot\s*\d+\]\s*At\s*(\d\d):(\d\d)\.(\d\d\d)\s*[::]?\s*(.*?)(?=\[Shot\s*\d+\]\s*At|$)", re.S)


def beats(text):
    """按时间戳切拍，返回 [(起秒, 止秒, 文本)]。骨架与十块都能取到。"""
    r = regions(text)
    body = r["body"] or text
    out = []
    for a, b, c in _BEAT_CN.findall(body):
        try:
            out.append((float(a), float(b), re.sub(r"\s+", " ", c).strip()))
        except ValueError:
            continue
    if out:
        return out
    for h, m, ms, c in _BEAT_EN.findall(body):
        try:
            s0 = int(h) * 60 + int(m) + int(ms) / 1000.0
        except ValueError:
            continue
        out.append((round(s0, 3), None, re.sub(r"\s+", " ", c).strip()))
    return out


# ---------------------------------------------------------------- 统一分区


def regions(text):
    """返回六类职责区。key 缺失/取不到时给空串或空表，但**永远给得出 body**。"""
    kind = detect(text)
    d = {"kind": kind, "style": "", "body": "", "camera": "", "invariant": "",
         "sound": "", "music": "", "dialog": dialogues(text), "blocks": []}
    blocks = [b.strip() for b in BLOCK_RE.findall(text)]
    d["blocks"] = blocks

    if kind in ("h3_skeleton", "h3_ref2va"):
        sp = _split_skeleton_body(_shot_body(text))
        d.update(style=sp["style"], body=sp["body"], camera=sp["camera"],
                 invariant=sp["invariant"])
        d["raw_body"] = sp["all"]
        d["sound"] = field_value(text, "overall_soundscape:")
        d["music"] = field_value(text, "non_diegetic_music:")
        return d

    if kind == "sd_tenblock":
        d["style"] = _block_span(text, u"风格与光影")
        d["camera"] = _block_span(text, u"镜头")
        d["invariant"] = _block_span(text, u"保持一致")
        d["sound"] = _block_span(text, u"声音")
        d["music"] = _block_span(text, u"声音")
        d["body"] = _block_span(text, u"事件脚本")
        if not d["body"]:
            d["body"] = text          # 兜底：绝不留空
        return d

    d["body"] = text                   # 图片/其它：整篇就是视觉描述区
    return d


def visual_zone(text):
    """词表闸该扫的那一区：**去掉台词与声音**，其余全算（宁滥勿漏）。"""
    r = regions(text)
    t = text
    for d in r["dialog"]:
        t = t.replace(d, u" ")
    if r["sound"]:
        t = t.replace(r["sound"], u" ")
    for f in BASE_FIELDS + REF2VA_FIELDS:
        t = t.replace(f, u" ")
    return t


# ---------------------------------------------------------------- 正文语言（10-03 批 14 建闸）
# 官方三处硬性规定重写段落用英文：`ref-en.txt:5`（"Write all six rewrite sections in English.
# Preserve the original language only for dialogue and lyrics inside `<d>` and for text visibly
# present in the scene"）、`ref-en.txt:217`、`SKILL.md:33`。⇒ 豁免只有三处：
#   ① `<d>…</d>` 内的台词／歌词；② 英文双引号内的**画面可见文字**（官方 `base-en.txt:146`）；
#   ③ 逐字首行指令与字段名行（那本就是英文，剔掉纯粹为了不把指纹算进违规）。
# 判据是**二值**的（有没有非英文字符），不带阈值 ⇒ 不吃「绝对带升 error」那条红线。

CJK_RE = re.compile(u"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uac00-\ud7af]+")
_VISUAL_QUOTE_RE = re.compile(r'"([^"\n]{1,400})"')


def _mask_out(text, spans):
    """把豁免片段的内容挖空（保留长度与行号，方便回填上下文）。"""
    chars = list(text)
    for a, b in spans:
        for i in range(max(a, 0), min(b, len(chars))):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


def non_english_spans(text):
    """返回 [(行号, 片段)]——重写段落里出现在豁免区之外的非英文字符。空表＝合格。

    只判**语言**，不判标点（全角标点另按官方 §标点条另说，别混进这条把两件事算成一件事）。
    """
    spans = []
    for m in DLG_RE.finditer(text):                      # ① 台词／歌词
        if m.start(1) != m.end(1):
            spans.append((m.start(1), m.end(1)))
        spans.append((m.start(), m.end()))               # `<d>` 标记本身也剔掉
    for m in _VISUAL_QUOTE_RE.finditer(text):             # ② 画面可见文字
        if m.start(1) != m.end(1):
            spans.append((m.start(1), m.end(1)))
    if text.startswith(SKELETON_INSTRUCTION):             # ③ 逐字首行
        spans.append((0, len(SKELETON_INSTRUCTION)))
    for f in BASE_FIELDS + REF2VA_FIELDS:                 # 字段名行
        for m in re.finditer(re.escape(f), text):
            spans.append((m.start(), m.end()))
    masked = _mask_out(text, spans)
    out = []
    for m in CJK_RE.finditer(masked):
        a = max(masked.rfind("\n", 0, m.start()) + 1, m.start() - 24)
        b = min(masked.find("\n", m.end()) if masked.find("\n", m.end()) >= 0 else len(masked),
                m.end() + 24)
        frag = text[a:b].replace("\n", " ").strip()
        out.append((masked[:m.start()].count("\n") + 1, frag))
    return out


# ---------------------------------------------------------------- 词表匹配器（唯一实现，10-03 批 16 立）
# 为什么要单独立这一把尺：两张闸（`h3_rule_gate`／`prompt_lint`）历来看的都是**中文词表**，
# 写法是 `w in text` 子串匹配。正文英译之后同一条判据必须能看英文，而英文直接套子串匹配会误伤：
#   `no` 撞进 `nothing`／`not` 撞进 `note`、`staff` 撞进 `staffed`、`light` 撞进 `highlight`。
# 语义按条目形态分三种，**一处实现、两处共用**（R2-07：同义判据不许两张表各写一遍）：
#   · 含正则元字符的条目（英文侧惯用 `\bface\b` 这种）⇒ 原样编译，加 re.I；
#   · 纯 ASCII 词 ⇒ 词边界 ＋ 容忍 -s/-es（`eye` 要能看见 `eyes`，`strike` 要能看见 `strikes`）；
#     带空格的条目（`no `／`not `）说明作者要的就是"后面紧跟词"的引导词形 ⇒ 退成大小写不敏感子串；
#   · 含中文的条目 ⇒ 子串匹配（中文无词边界，历来如此）。
_META_RE = re.compile(r"[\[\]{}()|*+?\\^$]")
_TERM_CACHE = {}


def term_pattern(word):
    """单个条目 → 编译好的 pattern；条目为空串返回 None。"""
    if not word:
        return None
    if word in _TERM_CACHE:
        return _TERM_CACHE[word]
    if _META_RE.search(word):
        pat = re.compile(word, re.I)
    elif word.isascii():
        if word != word.strip():                    # 引导词形（带尾空格）：子串语义
            pat = re.compile(re.escape(word), re.I)
        else:
            # 复数／三人称只允许 `-s`／`-es` 这一档：写成 `(?:e?s)?` 会让 `not` 从
            # "note" 里吃掉那个 e 再撞词尾＝自己造误伤（批 16 实测纠正）。
            pat = re.compile(r"(?<![A-Za-z0-9])%s(?:es|s)?(?![A-Za-z0-9])" % re.escape(word), re.I)
    else:
        pat = re.compile(re.escape(word))
    _TERM_CACHE[word] = pat
    return pat


def iter_terms(text, entries):
    """逐个产出 (条目, 命中起点)。要做句位判定的调用方（prompt_lint）用起点。"""
    for w in entries:
        pat = term_pattern(w)
        if pat is None:
            continue
        for m in pat.finditer(text or ""):
            yield w, m.start()


def match_terms(text, entries):
    """→ 命中的条目列表（按条目表原顺序、去重）。"""
    out = []
    for w, _p in iter_terms(text, entries):
        if w not in out:
            out.append(w)
    return out


# 子句／句末边界：**中英标点都算**。
# 旧写法只切 `，。；、` ⇒ 英文正文一整段没有中文标点，"子句"退化成整篇 ⇒
# 任何"同子句要有身体部位"式的豁免句都会在白板上成立（H3R13 实测 3 份 warn 静默消失）。
# ASCII 句点故意不进 CLAUSE_SPLIT（会把 `0.0-1.2s`、`9:16` 切碎），句末扫描用多字符标记。
CLAUSE_SPLIT_RE = re.compile(u"[，。；、,;!?\n]")
SENT_END_MARKS = (u"。", u"！", u"？", u"；", u"\n", u". ", u"! ", u"? ", u"; ")
# 句级切分：中文标点（含全角；）后面直接切，ASCII 分号也切（旧 H3R8 就按 `。；;` 切，
# 少一条会把整段英文基调句当成"一句"，光与 fight 动词跨分号也算同句＝误报）；
# ASCII 句点**必须跟空白**才切（否则 `5.17-second`／`0.0-1.2s` 被切碎，句子数虚高）。
SENT_SPLIT_RE = re.compile(u"(?<=[。！？；;])|(?<=[.!?])\\s+")


def clauses(text):
    """按中英标点切子句（H3R13／词表闸的"同句"判定都用它）。"""
    return [c.strip() for c in CLAUSE_SPLIT_RE.split(text or "") if c.strip()]


def sentences(text):
    """按**句**切（H3R8 光影"同句有光＋会射出去的动词"用这一级，比子句宽、比整篇准）。"""
    return [s.strip() for s in SENT_SPLIT_RE.split(text or "") if s.strip()]


def sent_start(text, pos):
    """从 pos 往前找**最近句末**，返回该句起点（否定引导词的句位判定用）。没有句末则 0。"""
    best = 0
    for e in SENT_END_MARKS:
        i = (text or "").rfind(e, 0, pos)
        if i >= 0:
            best = max(best, i + len(e))
    return best


# ---------------------------------------------------------------- 混用检测


def mixing(text, want="h3"):
    """返回"这份稿子出现了不该属于本通道的格式指纹"的清单。

    want='h3'    ：本地 H3（骨架或六段）——十块块名、云端职责句式算混用
    want='cloud' ：云端 SD 通道——十块齐全即可；出现骨架字段名算混用
    want='image' ：图片口径——两种视频格式都不该整份套上，只查共性坑
    """
    kind = detect(text)
    out = []
    blocks = [b.strip() for b in BLOCK_RE.findall(text)]
    has_skel = any(f in text for f in BASE_FIELDS)
    has_ref = sum(1 for f in REF2VA_ONLY if f in text) >= 2

    if want == "h3":
        if kind == "sd_tenblock":
            out.append(u"十块块名进了 H3 视频提示词：%s" % u"、".join(
                u"【%s】" % b for b in blocks[:6]))
        elif blocks:
            out.append(u"H3 提示词里残留中文块名：%s" % u"、".join(u"【%s】" % b for b in blocks[:6]))
        if kind == "h3_skeleton" and has_ref:
            out.append(u"骨架与全参考六段同时出现（两种 H3 模式混挂）")
    elif want == "cloud":
        if has_skel or has_ref:
            out.append(u"云端 SD 稿里出现本地 H3 的字段名（骨架/六段）")
        missing = [b for b in CORE_BLOCKS if u"【%s】" % b not in text]
        if missing and blocks:
            out.append(u"缺核心分块：%s" % u"、".join(missing))
    elif want == "image":
        if kind in ("h3_skeleton", "h3_ref2va"):
            out.append(u"图片稿套用了 H3 视频骨架字段")
        elif kind == "sd_tenblock" and len(blocks) >= 5:
            out.append(u"图片稿整份套用了视频分块模板（图片无格式要求，只查共性坑）")
    return out


# ---------------------------------------------------------------- 自检


def _selftest():
    skel = (SKELETON_INSTRUCTION + "\n\n"
            + "integrated_multimodal_description:\n"
            + "[Shot 1] 高精度CG半写实，深蓝长袍。 0.0-1.2 秒：他吼道 <d>[中文] 站住。</d> 右拳砸来。"
              " 1.2-2.4 秒：她侧身，拳头绝对没有碰到她的脸。 小幅度慢速 Truck：镜头横移。 "
              "Throughout: 她全程深蓝长袍、长枪始终背在背上。\n"
            + "overall_soundscape:\n其余时间全场安静。环境音只有破风声。\n"
            + "non_diegetic_music:\nN/A\n")
    ten = (u"【生成目标】一条 5 秒镜\n【主体与关系】她与他\n"
           + u"【事件脚本】0.0-1.2 秒：他挥拳。\n【保持一致】她不出声。\n"
           + u"【镜头】中幅度慢速 Push In\n【声音】无音乐\n【风格与光影】冷光\n")
    assert detect(skel) == "h3_skeleton", detect(skel)
    assert detect(ten) == "sd_tenblock"
    assert detect(u"站在一排红灯笼下，镜头缓推。") == "plain"
    r = regions(skel)
    assert r["music"] == "N/A", r["music"]
    assert u"长枪始终背在背上" in r["invariant"]
    assert u"Truck" in r["camera"]
    assert len(beats(skel)) == 2, beats(skel)
    assert mixing(ten, want="h3"), mixing(ten, want="h3")
    assert mixing(skel, want="cloud"), mixing(skel, want="cloud")
    assert mixing(skel, want="h3") == []
    v = visual_zone(skel)
    assert u"站住" not in v and u"破风声" not in v
    # 拟声词引号**不算台词**（C 线 P3C 实测：`<d>` 0 个、引号 6 个，旧口径虚报 3 句台词⇒假超载）
    onoma = (SKELETON_INSTRUCTION + "\n\n"
             + "integrated_multimodal_description:\n[Shot 1] 0.0-1.2 秒：他撞在墙上，"
               + u"“轰”的一声，墙灰落下。 1.2-2.4 秒：她收势站定。\n"
             + "overall_soundscape:\n环境音只有落灰声。\nnon_diegetic_music:\nN/A\n")
    assert detect(onoma) == "h3_skeleton", detect(onoma)
    assert dialogues(onoma) == [], dialogues(onoma)
    ten_dlg = u"【事件脚本】0.0-1.2 秒：他吼道：“站住。”"
    assert dialogues(ten_dlg) == [u"站住。"], dialogues(ten_dlg)   # 十块稿的引号台词仍要收到
    # ── 英文正文形（10-03 批 16：正文英译后底座不能瞎）────────────────────────
    en_skel = (SKELETON_INSTRUCTION + "\n\n"
               + "integrated_multimodal_description:\n[Shot 1] Semi-realistic 3D CG, cold light leaking "
                 "between towers. Landscape 16:9, one continuous 5.17-second take, single shot throughout "
                 "— a neon alley. 0.0-1.2s: The man steps in front of her. 1.2-2.4s: She turns her "
                 "shoulder, the fist never touching her face. Push In at slow speed: the camera opens on "
                 "a medium shot of the two. throughout: the long staff stays fully bound in white hemp "
                 "cloth, its shaft never exposed.\n"
               + "overall_soundscape:\nRoom tone only.\nnon_diegetic_music:\nN/A\n")
    assert detect(en_skel) == "h3_skeleton", detect(en_skel)
    assert len(beats(en_skel)) == 2, beats(en_skel)          # `X.Y-Z.Ws:` 必须认得（旧式只认「秒」）
    assert "Push In" in regions(en_skel)["camera"], regions(en_skel)["camera"][:120]
    assert "never exposed" in regions(en_skel)["invariant"], "小写 throughout: 标签没认出来"
    assert "single shot throughout" in regions(en_skel)["body"] or \
        "single shot throughout" in regions(en_skel)["style"], \
        "散文里的小写 throughout（无冒号）被当成标签吞段＝运镜/事件区全空（批 16 抓到的原病灶）"
    # 词表匹配器：英文词条要能命中，且不能把易混词咬进来
    assert match_terms("her eyes and hand", ["eye", "hand"]) == ["eye", "hand"], \
        match_terms("her eyes and hand", ["eye", "hand"])
    assert match_terms("a highlighted wall", ["light"]) == [], "highlight 里的 light 不算光影名词"
    assert match_terms("note the staff", ["not"]) == [], "not 不该从 note 里吃掉一个 e"
    assert match_terms("note the staff", ["note", "staff"]) == ["note", "staff"]
    assert match_terms("There is nothing here", ["no"]) == [], "裸 no 不该撞进 nothing"
    assert match_terms("there is no lettering", ["no "]) == ["no "], \
        "带空格的引导词形（`no `）要按子串语义命中 `no lettering`"
    assert len(clauses("She stands, unhurried and settled, her hands loose.")) == 3, clauses(
        "She stands, unhurried and settled, her hands loose.")
    _two = "The fist never touches her face. She stands with a loose grip."
    assert sent_start(_two, _two.index("loose")) > 0, \
        "ASCII 句末没被当边界⇒否定词会管到上一句去"
    assert sent_start(_two, _two.index("never")) == 0, "第一句的句起点应是 0"
    # 正文语言（10-03 批 14 建闸）：三处豁免都不该报，正文混中文必须报
    en_ok = (SKELETON_INSTRUCTION + "\n\n"
             + "integrated_multimodal_description: [Shot 1] A woman says "
             + u'<d>[中文] 站住。</d> as a neon sign reading "营业中" glows.\n'
             + "overall_soundscape: rain on the window.\nnon_diegetic_music: N/A")
    assert non_english_spans(en_ok) == [], non_english_spans(en_ok)   # 误伤＝拦掉合规稿
    zh_body = en_ok.replace("A woman says", u"一个女的说话")
    assert len(non_english_spans(zh_body)) == 1, non_english_spans(zh_body)
    zh_sound = en_ok.replace("rain on the window", u"雨打窗户")
    assert any(u"雨打窗户" in f for _, f in non_english_spans(zh_sound)), \
        "soundscape 段的中文没抓到＝假阴"
    print("prompt_format 自检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
