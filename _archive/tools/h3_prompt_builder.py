#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""h3_prompt_builder.py — H3 提示词的通用渲染器（项目无关）

设计原则
--------
1. **单一真源**：角色外观只写在 characters.yaml，场景只写在 scenes.yaml，
   镜头稿只写"这一镜发生什么"。外观文字禁止在镜头里手写。
2. **格式由代码保证**：字段名从 h3_official_spec.MODES 取，台词只走 <d>，
   说话人编号、闭唇句、summary 任务类型、retention 的 appears-in 全部自动生成。
3. **渲染完立刻过官方闸**：error > 0 不落盘，坏稿只进 _rejected/。

任何项目都按同一套目录结构挂载：

    <project>/h3/
      characters.yaml   # 角色卡（人定一次）
      scenes.yaml       # 场景卡（含合法变化的时间线）
      lexicon.yaml      # 易错同音词（可选）
      shots.yaml        # 镜头表
      out/              # 渲染产物

用法：
  py h3_prompt_builder.py template
  py h3_prompt_builder.py build --project <project>/h3 --out-dir <project>/h3/out
  py h3_prompt_builder.py build --project ... --only U04
  py h3_prompt_builder.py build --project ... --out-dir ... --trace [trace.json]
  py h3_prompt_builder.py check --file out/U04.txt --mode ref2va --seconds 12.0
  py h3_prompt_builder.py lint --project <project>/h3      # 只查卡，不渲染
"""
from __future__ import print_function

import argparse
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import h3_official_spec as SPEC  # noqa: E402
import h3_trace as T  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# ---------------------------------------------------------------- 常量
DIGITS = "零一二三四五六七八九"
PUNCT_RE = re.compile(u"[，,。.！!？?；;：:、…—]")
CJK_RE = re.compile(u"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
STATE_WORDS = ("shattered", "intact", "fragments", "fissures", "debris",
               "broken", "crumbling", "decayed")
SEC_PER_CHAR = 0.19          # 中文实测：字×0.19 + 标点×0.6（两次验实）
SEC_PER_PUNCT = 0.6
TIMING_ABS_TOL = 0.8
TIMING_REL_TOL = 0.2
MIN_WORDS = 200              # detailed_description 软下限（官方 350–500，存量稿普遍偏短）
MAX_WORDS = 650
PRONOUN = {
    "female": ("She", "her"),
    "male": ("He", "his"),
    "object": ("It", "its"),
    "group": ("They", "their"),
}
LIP_RE = re.compile(
    r"\b(closes?\s+(her|his|its|their)\s+lips"
    r"|lips\s+(remain|stay|are)\s+(completely\s+|fully\s+|kept\s+)?closed)\b", re.I)
TASK_TYPES = set(SPEC.TASK_TYPES) if hasattr(SPEC, "TASK_TYPES") else {
    "keyframe completion", "reference generation", "video editing",
    "video continuation", "audio reuse", "audio reference",
}
SUMMARY_PREFIX_RE = re.compile(r"^\[([^\]]+)\]\s*")


class Issue(object):
    def __init__(self, code, level, msg):
        self.code, self.level, self.msg = code, level, msg

    def __repr__(self):
        return "%-5s %-18s %s" % (self.level.upper(), self.code, self.msg)


# ---------------------------------------------------------------- 文本小工具
def cn_num(n):
    if n < 0 or n > 9999:
        return str(n)
    if n == 0:
        return "零"
    if n < 10:
        return DIGITS[n]
    if n < 20:
        return "十" + (DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        return DIGITS[n // 10] + "十" + (DIGITS[n % 10] if n % 10 else "")
    if n < 1000:
        head = DIGITS[n // 100] + "百"
        r = n % 100
        if r == 0:
            return head
        if r < 10:
            return head + "零" + DIGITS[r]
        return head + DIGITS[r // 10] + "十" + (DIGITS[r % 10] if r % 10 else "")
    head = DIGITS[n // 1000] + "千"
    r = n % 1000
    if r == 0:
        return head
    return head + ("零" + cn_num(r) if r < 100 else cn_num(r))


def spell_numbers(text):
    return re.sub(r"\d+", lambda m: cn_num(int(m.group(0))), text or "")


def normalize_punct(text):
    """官方 §5.4：<d> 内只保留 , . ? ! 这类基本标点，去掉装饰符与重复标点。"""
    s = (text or "").strip()
    s = re.sub(r"[~～•·]+", "", s)
    s = re.sub(r"[。｡]", ".", s)
    s = re.sub(r"[，､]", ",", s)
    s = re.sub(r"[？]", "?", s)
    s = re.sub(r"[！]", "!", s)
    s = re.sub(r"[；;：:]", ",", s)
    s = re.sub(r"[、]+", ",", s)
    s = re.sub(r"…+", "...", s)
    s = re.sub(r",\s*,+", ",", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    if s and s[-1] not in ".?!":
        s += "."
    return s


def speech_timing(text):
    puncts = len(PUNCT_RE.findall(text or ""))
    chars = len(PUNCT_RE.sub("", text or "").strip())
    return chars * SEC_PER_CHAR + puncts * SEC_PER_PUNCT, chars, puncts


def one_line(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def ensure_period(s):
    s = (s or "").strip()
    if not s:
        return s
    return s if s[-1] in ".!?\"')" else s + "."


def _trace_aliases(s):
    """给 h3_trace 用：卡值在渲染前后可能经过的等价形态。"""
    base = one_line(s)
    vals = [s, base, ensure_period(base),
            normalize_punct(spell_numbers(s)),
            ensure_period(normalize_punct(spell_numbers(s)))]
    out, seen = [], set()
    for v in vals:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def word_count(s):
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", s or ""))


def strip_cjk_probe(body):
    probe = SPEC.D_TAG.sub(" ", body or "")
    probe = re.sub(r'"[^"]*"', " ", probe)
    return [(i + 1, l.strip()) for i, l in enumerate(probe.splitlines()) if CJK_RE.search(l)]


# ---------------------------------------------------------------- 项目加载
def _load_yaml(path, default=None):
    if not os.path.isfile(path):
        return default
    with io.open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_project(project_dir):
    """读 characters / scenes / lexicon / shots。任何项目都是同一套文件名。"""
    if yaml is None:
        raise SystemExit("需要 PyYAML：py -3.12 -m pip install pyyaml")
    proj = os.path.abspath(project_dir)
    cards = {
        "dir": proj,
        "characters": _load_yaml(os.path.join(proj, "characters.yaml"), {}) or {},
        "scenes": _load_yaml(os.path.join(proj, "scenes.yaml"), {}) or {},
        "lexicon": _load_yaml(os.path.join(proj, "lexicon.yaml"), {}) or {},
        "shots": _load_yaml(os.path.join(proj, "shots.yaml"), {}) or {},
    }
    for key in ("characters", "scenes", "shots"):
        if not cards[key]:
            raise ValueError("%s 缺少 %s.yaml 或文件为空" % (proj, "characters" if key == "characters" else key[:-1]))
    return cards


# ---------------------------------------------------------------- 卡校验
def lint_cards(cards):
    issues = []
    chars = cards["characters"].get("roles") or {}
    scenes = cards["scenes"].get("scenes") or {}

    for name, c in chars.items():
        where = "characters.%s" % name
        for k in ("role", "gender", "appearance"):
            if not c.get(k):
                issues.append(Issue("card_missing", "error", "%s 缺 %s" % (where, k)))
        if c.get("gender") not in PRONOUN:
            issues.append(Issue("card_gender", "error", "%s gender 必须是 %s"
                                % (where, "/".join(sorted(PRONOUN)))))
        app = c.get("appearance") or ""
        if CJK_RE.search(app):
            issues.append(Issue("card_cjk", "error", "%s appearance 必须是英文（正文语言）" % where))
        ref = c.get("reference") or {}
        if ref and not os.path.isfile(ref.get("file", "")):
            issues.append(Issue("card_ref_missing", "error",
                                "%s 参考图不存在：%s" % (where, ref.get("file"))))
        if c.get("speaker"):
            issues.append(Issue("card_speaker_deprecated", "warn",
                                "%s 的 speaker 字段已不参与渲染：编号按本镜发声顺序自动分配"
                                % where))
        crop = ref.get("crop")
        if crop and (len(crop) != 4 or not all(0 <= float(x) <= 1 for x in crop)):
            issues.append(Issue("card_crop", "error",
                                "%s crop 必须是 0–1 的 [x0,y0,x1,y1]" % where))

    speakers = {}
    for name, c in chars.items():
        sp = c.get("speaker")
        if sp:
            if sp in speakers:
                issues.append(Issue("card_speaker_dup", "error",
                                    "%s 与 %s 都占用了 %s" % (speakers[sp], name, sp)))
            speakers[sp] = name

    for name, s in scenes.items():
        where = "scenes.%s" % name
        for k in ("geometry", "lighting", "outside"):
            if not s.get(k):
                issues.append(Issue("card_missing", "error", "%s 缺 %s" % (where, k)))
        for k in ("geometry", "lighting", "outside"):
            v = s.get(k) or ""
            if CJK_RE.search(v):
                issues.append(Issue("card_cjk", "error", "%s.%s 必须是英文" % (where, k)))
        state_words = [w for w in STATE_WORDS if w in (s.get("outside") or "").lower()]
        if state_words:
            issues.append(Issue("card_scene_state", "warn",
                                "%s.outside 含状态词 %s：基础描述应状态中性，"
                                "变化写进 state_timeline" % (where, "/".join(state_words))))
        ref = s.get("reference") or {}
        if ref and not os.path.isfile(ref.get("file", "")):
            issues.append(Issue("card_ref_missing", "error",
                                "%s 参考图不存在：%s" % (where, ref.get("file"))))
        for st in s.get("state_timeline") or []:
            if "at" not in st:
                issues.append(Issue("card_timeline", "error",
                                    "%s state_timeline 每项必须有 at（镜号）" % where))
    return issues


# ---------------------------------------------------------------- 镜头正规化
def _need(obj, key, where):
    v = obj.get(key)
    if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
        raise ValueError("%s 缺少必填字段 %r" % (where, key))
    return v


def resolve_cast(shot, cards):
    """cast: {S1: cmdr} → 带 appearance/pronoun 的 subjects 列表。

    外观只能来自 characters.yaml。镜级写 appearance/subjects 一律报错——
    此前这段是"静默忽略"，等于把"单一真源"变成注释。
    """
    chars = cards["characters"].get("roles") or {}
    sid = shot.get("id", "?")
    if "appearance" in shot or "subjects" in shot:
        raise ValueError("[%s] 不允许镜级写 appearance/subjects：外观只写在 characters.yaml，"
                         "镜头里用 cast: {S1: 角色名}" % sid)
    cast = shot.get("cast") or {}
    if not cast:
        raise ValueError("[%s] 缺少 cast：外观与说话人必须引用角色卡" % sid)
    subjects = []
    for sp in sorted(cast):
        cname = cast[sp]
        c = chars.get(cname)
        if not c:
            raise ValueError("[%s] cast %s=%r 不在 characters.yaml（现有 %s）"
                             % (shot["id"], sp, cname, ", ".join(sorted(chars))))
        g = c.get("gender", "female")
        subjects.append({
            "speaker": sp,
            "role": c["role"],
            "gender": g,
            "appearance": c["appearance"],
            "pronoun": PRONOUN[g],
            "tag": "<Subject %d>" % (len(subjects) + 1),
            "picture": c.get("reference", {}).get("picture_tag") or ("<Picture %d>" % (len(subjects) + 1)),
            "card": cname,
        })
    return subjects


def scene_for_shot(shot, cards):
    """按镜号取场景状态：就近沿用最近一个 state_timeline 锚点。

    旧实现只认精确命中，没登记的镜直接落回基础描述：
    行星在 U01 还完整、U02 就变已碎透。现在按镜头顺序找 <= 当前镜的最后一个锚点；
    没登记的差异才可能被认成漂移。返回值带 _state_source 供 manifest 取证。
    """
    sid = shot.get("scene")
    scenes = cards["scenes"].get("scenes") or {}
    if not sid:
        return None
    sc = scenes.get(sid)
    if not sc:
        raise ValueError("[%s] scene=%r 不在 scenes.yaml" % (shot["id"], sid))
    order = {}
    for i, s in enumerate(cards["shots"].get("shots") or []):
        order[s.get("id")] = i
    idx = order.get(shot["id"], -1)
    state, source, source_idx = None, None, -1
    for st in sc.get("state_timeline") or []:
        j = order.get(st.get("at"))
        if j is None or j > idx:
            continue
        if j > source_idx:
            state, source, source_idx = st, st.get("at"), j
    sc = dict(sc)
    sc["_state"] = state or {}
    sc["_state_source"] = source
    return sc


def normalize_shot(raw, defaults, cards):
    shot = dict(defaults or {})
    shot.update(raw or {})
    sid = _need(shot, "id", "shot")
    mode = _need(shot, "mode", sid)
    canvas = shot.get("canvas") or mode
    if mode == "multiref":
        canvas, mode = "multiref", "ref2va"
    shot["canvas"], shot["mode"] = canvas, mode
    if mode not in SPEC.MODES:
        raise ValueError("[%s] mode=%r 不认识，可选：%s"
                         % (sid, mode, ", ".join(sorted(SPEC.MODES))))
    shot["duration"] = float(_need(shot, "duration", sid))
    shot["subjects"] = resolve_cast(shot, cards)
    if not shot["subjects"]:
        raise ValueError("[%s] 没有 cast" % sid)
    shot["_speakers"] = {s["speaker"]: s for s in shot["subjects"]}
    shot["_scene"] = scene_for_shot(shot, cards)

    content = _need(shot, "content", sid)
    _need(content, "shot_line", "%s.content" % sid)
    if not re.search(r"\[Shot", content["shot_line"]):
        content["shot_line"] = "[Shot 1] " + content["shot_line"].strip()

    dialogues = shot.get("dialogue") or []
    for i, d in enumerate(dialogues):
        if not (d.get("text") or "").strip():
            raise ValueError("[%s] dialogue[%d] 缺 text" % (sid, i))
        sp = d.get("speaker") or "S1"
        if sp not in shot["_speakers"]:
            raise ValueError("[%s] dialogue[%d] speaker=%r 不在 cast（现有 %s）"
                             % (sid, i, sp, ", ".join(sorted(shot["_speakers"]))))
        d["speaker"] = sp
        d["text"] = normalize_punct(spell_numbers(d["text"].strip()))
        if not CJK_RE.search(d["text"]):
            raise ValueError("[%s] dialogue[%d] 台词里没有中文" % (sid, i))
    # 官方 §5.4：按本镜实际发声顺序分配 (S1)(S2)…，不按角色卡固定号。
    # cast 的键只是内部引用名；渲染时一律用 speaker_id。
    speaker_order = {}
    for d in dialogues:
        sp = d["speaker"]
        if sp not in speaker_order:
            speaker_order[sp] = "S%d" % (len(speaker_order) + 1)
        d["speaker_id"] = speaker_order[sp]
    _need(shot, "soundscape", sid)
    shot.setdefault("music", "N/A")
    return shot


# ---------------------------------------------------------------- 渲染
def _dialogue_line(d, shot):
    sub = shot["_speakers"][d["speaker"]]
    name = sub["role"]
    name = name[0].upper() + name[1:] if name else name
    sid_tag = "(%s)" % (d.get("speaker_id") or d["speaker"])
    who = "%s %s" % (sub["tag"], sid_tag)   # 官方 §5.4：<Subject N> (Sx)
    voice = (d.get("voice") or "").strip()
    vo = bool(d.get("voiceover"))
    lang = d.get("language") or shot.get("language") or "Chinese"

    if vo:
        lead = "%s says in an off-screen voiceover: " % who
    elif voice:
        lead = "%s says, voice %s: " % (who, voice)
    else:
        lead = "%s says: " % who
    line = lead + "<d>[%s] %s</d>" % (lang, d["text"])

    after = (d.get("after") or "").strip()
    if vo:
        # 官方：voiceover 之后必须写画内人物嘴唇闭合
        if not after:
            after = "The on-screen figure's lips remain completely closed."
        elif not LIP_RE.search(after):
            after = "The on-screen figure's lips remain completely closed. " + after
    elif not after:
        after = "%s %s" % (sub["pronoun"][0], "closes " + sub["pronoun"][1] + " lips.")
    elif not LIP_RE.search(after):
        after = "%s closes %s lips. %s" % (sub["pronoun"][0], sub["pronoun"][1], after)
    d["_after"] = after
    return line


def _scene_paragraph(sc):
    if not sc:
        return ""
    parts = [one_line(sc["geometry"]), one_line(sc["lighting"]), one_line(sc["outside"])]
    state = sc.get("_state") or {}
    for k in ("planet", "fleet", "light", "note"):
        if state.get(k):
            parts.append(one_line(state[k]))
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(ensure_period(p))
    return " ".join(out)


def _insert_scene(shot_line, scene_text):
    """环境段插在景别句之后、动作之前：先景别机位，再环境，再人物动作。"""
    s = (shot_line or "").strip()
    if not scene_text:
        return s
    m = re.match(r"(\[Shot 1\][^.]*\.)\s*", s)
    if m:
        return m.group(1) + " " + scene_text + " " + s[m.end():]
    return s + " " + scene_text


def _cite_subjects(paragraph, shot):
    out = paragraph
    for sub in shot["subjects"]:
        tag = sub.get("tag")
        if not tag or tag in out:
            continue
        pat = re.compile(r"\b%s\b" % re.escape(sub["role"]), re.I)
        if pat.search(out):
            out = pat.sub(lambda m: "%s (from %s)" % (m.group(0), tag), out, count=1)
    return out


def _has_scene_anchor(shot):
    """只有真挂了三张图的 multiref 镜才引用 <Picture 3>，否则指向不存在的槽位。"""
    return bool((shot.get("_scene") or {}).get("reference", {}).get("picture_tag")) \
        and len(shot.get("images") or []) >= 3


def _retention_lines(shot):
    lines = []
    for sub in shot["subjects"]:
        lines.append("%s (appears in [Shot 1]): fully_preserved — %s identity, clothing and colour "
                     "carry over from %s." % (sub["tag"], sub["role"], sub["picture"]))
    sc = shot["_scene"]
    if sc and _has_scene_anchor(shot):
        lines.append("%s (appears in [Shot 1], composition anchor): weak_reference — only the window "
                     "position and the spacing of the figures are reused; no faces or surface detail "
                     "come from it." % sc["reference"]["picture_tag"])
    for sub in shot["subjects"]:
        c = (shot.get("audio_refs") or {}).get(sub["speaker"])
        if c:
            lines.append("%s: reference — its vocal timbre guides the delivery of %s (%s) "
                         "without copying the original signal." % (c, sub["tag"], sub["speaker"]))
    return lines


def render_ref2va(shot):
    fields = SPEC.MODES["ref2va"]["fields"]
    out = []

    defs = []
    for sub in shot["subjects"]:
        defs.append("%s is %s referenced from %s: %s"
                    % (sub["tag"], sub["role"], sub["picture"], ensure_period(sub["appearance"])))
    sc = shot["_scene"]
    if sc and _has_scene_anchor(shot):
        anchor_tag = sc.get("reference", {}).get("picture_tag")
        defs.append("%s is the environment and composition anchor for [Shot 1]." % anchor_tag)
    for p in shot.get("pictures") or []:
        defs.append("%s %s" % (p["tag"], ensure_period(p.get("desc") or "is a reference picture")))
    for sp, a in (shot.get("audio_refs") or {}).items():
        sub = shot["_speakers"][sp]
        defs.append("%s is the voice-timbre reference for %s (%s)." % (a, sub["tag"], sp))
    out.append(fields[0])
    out.append("\n".join(defs))

    # summary：任务类型前缀必须合法
    summary = ensure_period(shot.get("summary") or "[reference generation] %s" % shot["id"])
    m = SUMMARY_PREFIX_RE.match(summary)
    if not m:
        summary = "[reference generation] " + summary
    out.append("")
    out.append("%s %s" % (fields[1], summary))

    out.append("")
    out.append(fields[2])
    out.append("\n".join(_retention_lines(shot)))

    out.append("")
    out.append(fields[3])
    style = (shot.get("style") or "").strip()
    if style:
        out.append(ensure_period(style))
    scene_text = _scene_paragraph(sc)
    para = [ensure_period(_insert_scene(shot["content"]["shot_line"], scene_text))]
    for b in (shot["content"].get("blocking") or []):
        para.append(ensure_period(one_line(b)))
    for d in shot.get("dialogue") or []:
        line = _dialogue_line(d, shot)
        if d.get("_after"):
            line += " " + ensure_period(d["_after"])
        para.append(line)
    tail = (shot["content"].get("after_all") or "").strip()
    if tail:
        para.append(ensure_period(one_line(tail)))
    out.append(_cite_subjects(" ".join(para), shot))

    out.append("")
    out.append("%s %s" % (fields[4], ensure_period(one_line(shot["soundscape"]))))
    out.append("")
    out.append("%s %s" % (fields[5], shot.get("music") or "N/A"))
    return "\n".join(out).strip() + "\n"


def render_base(shot, mode):
    spec = SPEC.MODES[mode]
    out = []
    first = spec.get("first_line")
    if first:
        if mode == "i2va" or (mode == "fl2va" and not shot.get("last_image")):
            out.append(SPEC.MODES["i2va"]["first_line"])
        else:
            out.append(first.replace("{N}", str(shot.get("last_shot") or 1))
                       .replace("{S}", "%.2f" % shot["duration"]))
        out.append("")
    out.append(spec["fields"][0])
    style = (shot.get("style") or "").strip()
    if style:
        out.append(ensure_period(style))
    scene_text = _scene_paragraph(shot["_scene"])
    para = [ensure_period(_insert_scene(shot["content"]["shot_line"], scene_text))]
    for d in shot.get("dialogue") or []:
        line = _dialogue_line(d, shot)
        if d.get("_after"):
            line += " " + ensure_period(d["_after"])
        para.append(line)
    tail = (shot["content"].get("after_all") or "").strip()
    if tail:
        para.append(ensure_period(one_line(tail)))
    out.append(" ".join(para))
    out.append("")
    out.append("%s %s" % (spec["fields"][1], ensure_period(one_line(shot["soundscape"]))))
    out.append("")
    out.append("%s %s" % (spec["fields"][2], shot.get("music") or "N/A"))
    return "\n".join(out).strip() + "\n"


def render(shot):
    return render_ref2va(shot) if shot["mode"] == "ref2va" else render_base(shot, shot["mode"])


# ---------------------------------------------------------------- 自检
def check_render(shot, text, cards):
    issues = []
    sid, mode, dur = shot["id"], shot["mode"], shot["duration"]

    rp = SPEC.validate(text, mode=mode, seconds=dur)
    for r in rp.rows:
        issues.append(Issue("official_%s" % r["id"], r["sev"], r["msg"]))

    fields = SPEC.MODES[mode]["fields"]
    pos = -1
    for f in fields:
        k = text.find(f)
        if k < 0:
            issues.append(Issue("field_missing", "error", "缺字段 %s" % f))
        elif k < pos:
            issues.append(Issue("field_order", "error", "字段顺序错：%s" % f))
        pos = max(pos, k)

    want = [d["text"] for d in shot.get("dialogue") or []]
    got = [m.group(2).strip() for m in SPEC.D_TAG.finditer(text)]
    if len(got) != len(want):
        issues.append(Issue("dialogue_count", "error",
                            "台词 %d 句，渲染出 %d 句" % (len(want), len(got))))
    else:
        for i, (a, b) in enumerate(zip(want, got)):
            if a != b:
                issues.append(Issue("dialogue_changed", "error",
                                    "第 %d 句台词被动过" % (i + 1)))

    for i, d in enumerate(shot.get("dialogue") or []):
        if not LIP_RE.search(d.get("_after") or ""):
            issues.append(Issue("no_lip_close", "error", "第 %d 句后没有嘴唇闭合句" % (i + 1)))

    for ln, frag in strip_cjk_probe(text):
        issues.append(Issue("cjk_in_body", "error", "正文第 %d 行残留中文：%s" % (ln, frag[:40])))

    # 词数（软下限，官方 350–500）
    body = SPEC.section(text, SPEC.MODES[mode].get("body_field", fields[0]), fields[1:]) \
        if hasattr(SPEC, "section") else text
    wc = word_count(body)
    if wc < MIN_WORDS:
        issues.append(Issue("word_count", "warn",
                            "detailed_description 只有 %d 词（官方 350–500，单镜也别写太短）" % wc))
    elif wc > MAX_WORDS:
        issues.append(Issue("word_count", "warn", "正文 %d 词，超过 %d" % (wc, MAX_WORDS)))

    # 时长预算
    total_est = sum(speech_timing(d["text"])[0] for d in shot.get("dialogue") or [])
    if want:
        tol = max(TIMING_ABS_TOL, total_est * TIMING_REL_TOL)
        forced_min = dur >= 4.0 and total_est < 3.0
        if dur < total_est - tol:
            issues.append(Issue("timing_short", "error",
                                "台词估计 %.2fs，给 %.2fs ⇒ 会吞字" % (total_est, dur)))
        elif dur > total_est + tol and not forced_min:
            issues.append(Issue("timing_long", "error",
                                "台词估计 %.2fs，给 %.2fs ⇒ 多 %.2fs，会被静默填满"
                                % (total_est, dur, dur - total_est)))

    lo, hi = SPEC.DURATION_RANGE
    if not (lo <= dur <= hi):
        issues.append(Issue("duration_range", "error",
                            "时长 %.2fs 不在官方 %.0f–%.0f 秒" % (dur, lo, hi)))

    # 词表告警
    lex = cards.get("lexicon") or {}
    for bad in lex.get("avoid") or []:
        for d in shot.get("dialogue") or []:
            if bad in d["text"]:
                issues.append(Issue("lexicon", "warn",
                                    "台词含易错词 %r（建议换措辞）" % bad))
    return issues


# ---------------------------------------------------------------- CLI
TEMPLATE_PROJECT = u"""\
# 把一个项目挂到通用工具上，只需要这四个文件（全部放 <project>/h3/）

# ---------------- characters.yaml ----------------
roles:
  cmdr:
    role: the commander
    gender: female
    appearance: >
      a tall woman in a black floor-length robe with subtle woven patterns,
      a narrow crimson lining, a high-collared black underlayer and black boots,
      her straight black hair drawn into a high ponytail with a gold hair ornament
    reference:
      file: ../assets/cmdr_robe.png
      crop: [0.10, 0.10, 0.55, 0.95]
  adjutant:
    role: the adjutant
    gender: male
    appearance: >
      a man of about twenty-six in a black military coat with dense gold
      embroidery, a crimson inner lining, a long black cape and black leather gloves
    reference:
      file: ../assets/adjutant.png
      crop: [0.00, 0.05, 0.45, 1.00]

# ---------------- scenes.yaml ----------------
scenes:
  bridge:
    geometry: >
      one continuous floor-to-ceiling pane across the back wall with no mullions,
      a narrow hand rail at hip height, polished deck plates that mirror the window
    lighting: >
      cold white overhead light from above and slightly behind the lens,
      a blue rim along the window edge from the planet outside
    outside: >
      a planet hangs beyond the window; its fragmentation state is defined per shot
      in state_timeline; several capital ships hold position at mid distance
    invariants:
      - "one continuous pane, never divided into panes"
      - "the rail stays at hip height"
    reference:
      file: ../assets/bridge.png
      crop: [0.0, 0.0, 1.0, 1.0]
      picture_tag: "<Picture 3>"
    state_timeline:
      - {at: S01, planet: "the planet is still largely intact, fragments just beginning to drift"}
      - {at: S12, planet: "the planet is reduced to a debris ring, its core gone"}

# ---------------- lexicon.yaml ----------------
avoid: ["星区", "禁卫", "原件"]

# ---------------- shots.yaml ----------------
defaults:
  scene: bridge
  language: Chinese
  style: "Live-action, cinematic, cold grey-blue palette, shallow depth of field, fine film grain."
shots:
  - id: S01
    mode: ref2va
    canvas: ref2va
    duration: 6.0
    cast: {S1: cmdr}
    summary: "[reference generation] The commander gives a short order at the window."
    content:
      shot_line: >
        [Shot 1] Medium shot, static. The commander keeps her weight on both feet
        and lifts one hand slightly before letting it drop.
      after_all: "Her chin stays level."
    dialogue:
      - speaker: S1
        voice: low and even
        text: "通知第六编队就地驻扎。"
    soundscape: >
      A low ventilation hum under the room and the soft shift of fabric as her arm falls.
    music: N/A
"""


def cmd_template(_a):
    print(TEMPLATE_PROJECT)
    return 0


def cmd_lint(args):
    cards = load_project(args.project)
    issues = lint_cards(cards)
    errs = [i for i in issues if i.level == "error"]
    for i in issues:
        print("  %s" % i)
    print("\n卡检查：%d error / %d warn" % (len(errs), len(issues) - len(errs)))
    return 0 if not errs else 1


def cmd_build(args):
    cards = load_project(args.project)
    card_issues = lint_cards(cards)
    errs = [i for i in card_issues if i.level == "error"]
    for i in card_issues:
        print("  %s" % i)
    if errs:
        print("\n角色卡/场景卡有 %d 个 error，先修卡再渲染。" % len(errs))
        return 1

    doc = cards["shots"]
    defaults = doc.get("defaults") or {}
    shots = doc.get("shots") or []
    only = set(args.only or [])
    out_dir = os.path.abspath(args.out_dir)
    rej_dir = os.path.join(out_dir, "_rejected")
    os.makedirs(out_dir, exist_ok=True)

    report, failed = [], 0
    want_trace = args.trace is not None
    trace_path = (os.path.abspath(args.trace or os.path.join(out_dir, "trace.json"))
                  if want_trace else None)
    trace_doc = {"schema": T.SCHEMA, "project": cards["dir"], "shots": {}}
    for raw in shots:
        if only and raw.get("id") not in only:
            continue
        try:
            shot = normalize_shot(raw, defaults, cards)
            text = render(shot)
        except ValueError as e:
            print("[FAIL] %s" % e)
            report.append({"id": raw.get("id"), "ok": False, "errors": [str(e)]})
            failed += 1
            continue

        issues = check_render(shot, text, cards)
        errors = [i for i in issues if i.level == "error"]
        warns = [i for i in issues if i.level == "warn"]
        if want_trace:
            try:
                tr = T.build_shot_trace(
                    shot, text, cards,
                    aliases_fn=_trace_aliases,
                    normalizers={"one_line": one_line,
                                 "spell_numbers": spell_numbers,
                                 "normalize_punct": normalize_punct,
                                 "ensure_period": ensure_period},
                    field_labels=SPEC.MODES[shot["mode"]]["fields"])
                tr["ok"] = not errors
                trace_doc["shots"][shot["id"]] = tr
            except Exception as e:
                trace_doc["shots"][shot["id"]] = {"ok": False, "error": str(e)}
                errors.append(Issue("trace_failed", "error",
                                    "trace 生成失败：%s" % e))
        report.append({"id": shot["id"], "mode": shot["mode"], "canvas": shot["canvas"],
                       "duration": shot["duration"], "ok": not errors,
                       "errors": [repr(i) for i in errors], "warns": [repr(i) for i in warns]})
        if errors:
            failed += 1
            os.makedirs(rej_dir, exist_ok=True)
            with io.open(os.path.join(rej_dir, shot["id"] + ".txt"), "w",
                         encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("[FAIL] %-6s %d error（草稿在 _rejected/）" % (shot["id"], len(errors)))
            for e in errors:
                print("        %s" % e)
            continue
        with io.open(os.path.join(out_dir, shot["id"] + ".txt"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("[ OK ] %-6s %-8s %-7s %.1fs  %d 句  %d warn"
              % (shot["id"], shot["canvas"], shot["mode"], shot["duration"],
                 len(shot.get("dialogue") or []), len(warns)))
        for w in warns:
            print("        %s" % w)

    if want_trace:
        trace_doc["shot_count"] = len(trace_doc["shots"])
        trace_doc["trace_sha1"] = T.sha1_text(
            json.dumps(trace_doc, ensure_ascii=False, sort_keys=True))
        trace_doc["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(trace_path), exist_ok=True)
        with io.open(trace_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(trace_doc, ensure_ascii=False, indent=1))
        print("trace: %s" % trace_path)

    with io.open(os.path.join(out_dir, "build_report.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n共 %d 镜：通过 %d，失败 %d" % (len(report), len(report) - failed, failed))
    return 0 if failed == 0 else 1


def cmd_check(args):
    with io.open(args.file, encoding="utf-8") as f:
        text = f.read()
    mode = args.mode or SPEC.detect_mode(text)
    rp = SPEC.validate(text, mode=mode, seconds=args.seconds)
    errs = [r for r in rp.rows if r["sev"] == "error"]
    warns = [r for r in rp.rows if r["sev"] == "warn"]
    print("%s  mode=%s  error=%d warn=%d" % (args.file, mode, len(errs), len(warns)))
    for r in rp.rows:
        if r["sev"] in ("error", "warn"):
            print("%-5s %-6s %s" % (r["sev"].upper(), r["id"], r["msg"]))
    return 0 if not errs else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="H3 通用提示词渲染器（项目无关）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("template", help="打印一个完整的最小项目样例")
    p.set_defaults(func=cmd_template)

    p = sub.add_parser("lint", help="只检查角色卡/场景卡")
    p.add_argument("--project", required=True)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("build", help="从项目卡渲染官方稿")
    p.add_argument("--project", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--only", nargs="*", default=None)
    p.add_argument("--trace", nargs="?", const="", default=None,
                   help="写来源 trace；不给路径则写 <out-dir>/trace.json")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("check", help="用官方闸验一份成品")
    p.add_argument("--file", required=True)
    p.add_argument("--mode", default=None, choices=list(SPEC.MODES))
    p.add_argument("--seconds", type=float, default=None)
    p.set_defaults(func=cmd_check)

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
