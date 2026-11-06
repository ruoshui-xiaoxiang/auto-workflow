#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""h3_official_spec.py · MiniMax H3 官方写稿规则的**固化件**＋强制对齐器

来源（一手，逐行读过；本文件是它的机器可执行副本，不是新规则）：
  D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\SKILL.md      (40 行)
  D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\base-en.txt   (222 行) T2VA/I2VA/FL2VA/L2VA
  D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\ref-en.txt    (341 行) Ref2VA 全参考六段
上游＝权重仓 MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing/。

两种用法：
  1) 校验（执法）：py h3_official_spec.py check <稿.txt>... [--mode fl2va] [--seconds 8] [--house]
       逐条核官方契约，输出 error/warn/info＋**官方出处**（文件:节）。error≠0 时退出码 1。
  2) 填充（强制对齐）：fill(spec) 按官方骨架拼稿——首行逐字、字段名与顺序固定、
       运镜只用 12 行受控词、切镜只用 5 个白名单短语，写不出不合规的结构。

与其它闸的关系：`check_h3_all.py`/`h3_rule_gate.py` 是本机房内闸（含自创的 D7 三标签、D9 禁词表），
本文件只管**官方契约**那一层；两层都过才算干净。房内规与官方的差异见
`E:\创作\_待审文档\H3官方对齐审计_20261012.md`。
"""
from __future__ import print_function

import argparse
import io
import json
import os
import re
import sys

OFFICIAL_DIR = r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3"
CITE_BASE = "base-en.txt"
CITE_REF = "ref-en.txt"
CITE_SKILL = "SKILL.md"

# ---------------------------------------------------------------- 官方常量（逐字）
I2VA_FIRST_LINE = ("For the target video, at 0.00 seconds into the target video, "
                   "<Picture 1> (from [Shot 1]) is fully referenced.")
FL2VA_FIRST_LINE = ("How the reference pictures align with the target video — "
                    "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                    "Picture 2 (from Shot {N}) aligns with the {S}-second mark of the target video.")
L2VA_FIRST_LINE = ("How the reference pictures align with the target video — "
                   "<Picture 1> (from [Shot {N}]) aligns with the {S}-second mark of the target video.")

BASE_FIELDS = ("integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:")
REF_FIELDS = ("subject_definitions:", "summary:", "retention_analysis:",
              "detailed_description:", "overall_soundscape:", "non_diegetic_music:")

# base-en §4.3：12 行运动类型（全称，逐字）＋幅度 2 档＋速度 2 档
CAMERA_TYPES = [
    ("Zoom In", "焦距变化、机身不动"), ("Zoom Out", "焦距变化、机身不动"),
    ("Push In", "机身向前"), ("Pull Out", "机身向后"),
    ("Pan Left", "机位不动、镜头水平摇"), ("Pan Right", "机位不动、镜头水平摇"),
    ("Truck Left", "机身水平横移"), ("Truck Right", "机身水平横移"),
    ("Tilt Up", "机位不动、镜头垂直俯仰"), ("Tilt Down", "机位不动、镜头垂直俯仰"),
    ("Pedestal Up", "整机升降"), ("Pedestal Down", "整机升降"),
    ("Arc Shot", "绕主体弧线运动"), ("Tracking Shot", "跟随运动主体"),
    ("Static Shot", "机位与镜头都不动"),
    ("Shake Slightly", "轻微晃动"), ("Shake Strongly", "强烈晃动"),
    ("POV", "主体视点"),
    ("Roll Clockwise", "绕镜头轴顺时针滚转"), ("Roll Counterclockwise", "绕镜头轴逆时针滚转"),
]
CAMERA_NAMES = [n for n, _ in CAMERA_TYPES]
CAMERA_ALIAS = {"Roll CW": "Roll Clockwise", "Roll CCW": "Roll Counterclockwise"}
# 官方例句用的是屈折形式（"pulls out"／"pans right"／"holds a static shot"），
# 所以判定要按词形模式，不能拿类型名做子串匹配（否则官方 Case 3 自己都会被误判）。
CAMERA_PATTERNS = [
    r"zoom[sed]*\s+in", r"zoom[sed]*\s+out", r"push(?:es|ed)?\s+in", r"pull[sed]*\s+out",
    r"pan[sned]*\s+(?:left|right)", r"truck[sed]*\s+(?:left|right)",
    r"tilt[sed]*\s+(?:up|down)", r"pedestal[sed]*\s+(?:up|down)",
    r"arc[sed]*\s+(?:around|shot)", r"track[sed]*", r"static\s+shot", r"hold[s]?\s+a\s+static\s+shot",
    r"shake[s]?\s+(?:slightly|strongly)", r"point\s+of\s+view", r"\bPOV\b",
    r"roll[sed]*\s+(?:clockwise|counterclockwise)",
]
CAMERA_RE = re.compile("|".join(CAMERA_PATTERNS), re.I)
AMPLITUDE = ("with small amplitude", "with large amplitude")
SPEED = ("at slow speed", "at fast speed")
# 官方：medium amplitude 与 normal speed 通常省略 ⇒ 这些写法要挑出来
SUPERFLUOUS = re.compile(r"\b(medium|moderate|normal|steady)\s+(amplitude|speed)\b", re.I)
# 官方 §4.3：运镜要写成镜内自然英文动作句，不是句尾堆标签；G7 另禁器材名词
GEAR = re.compile(r"\b(dolly|steadicam|tripod|gimbal|crane\s+mount|handheld\s+rig)\b", re.I)

# base-en §4.2：切镜白名单（5 个）＋非硬切（仅用户明确要求）
CUT_PHRASES = ("the camera cuts to", "the shot cuts to", "the shot transitions to",
               "the shot changes to", "the shot switches to")
NON_HARD_CUT = re.compile(r"\b(cross[- ]dissolve|dissolve|fade(?:s|d)?\s+(?:in|out|to)|wipe)\b", re.I)

# base-en §4.4：说话人与台词
VOICEOVER_PHRASE = "says in an off-screen voiceover"
CONTINUITY_PHRASES = ("continues seamlessly across the cut",
                      "continues uninterrupted into the next shot",
                      "carries over from the previous shot",
                      "remains audible across the transition")
SPEAKER_ID = re.compile(r"\((S\d+(?:,S\d+)*)\)")
D_TAG = re.compile(r"<d>\s*\[([A-Za-z\u4e00-\u9fff]+)\]\s*([\s\S]*?)\s*</d>")
# 引导词只判"有没有"，所以宁宽勿窄：官方 §4.4 要求说话人身份/动作/语气写在 <d> 外，
# 但没给固定动词表。窄表会把 `saying coldly:`／`speaks:`／`growls:` 判成缺引导
# （10-13 拿房内 15 份现役稿实测：5 份假 warn，全是词形没收录）。
SPEECH_LEAD = re.compile(r"\b(say|says|said|saying|exclaim\w*|repl\w+|answer\w*|whisper\w*|"
                         r"shout\w*|ask\w*|mutter\w*|call\w*|cry|cries|crying|sing|sings|singing|"
                         r"speak|speaks|speaking|spoken|growl\w*|rasp\w*|add|adds|adding|yell\w*|"
                         r"murmur\w*|utter\w*|demand\w*|retort\w*|announce\w*|voice|voiced|voicing|"
                         r"mock\w*|taunt\w*|sneer\w*|quip\w*|joke\w*|snap\w*|bark\w*|hiss\w*|"
                         r"intone\w*|chant\w*|recit\w*|repeat\w*|stat|states|stating|stated|"
                         r"tell|tells|telling|told|respond\w*|continu\w*|admit\w*|confess\w*|"
                         r"insist\w*|plead\w*|beg|begs|begging|warn\w*|order\w*|command\w*|"
                         r"words?|lyrics?|vocalization\w*)\b",
                         re.I)
# 声景段专用：SPEECH_LEAD 里的 `rasp`／`growl`／`cry`／`call` 在 overall_soundscape 里首先
# 是**声音名词**（the rasp of fabric／a low growl of the engine），拿宽表扫那段会造假 warn
# （10-13 实测：dance_woman_v1 的 'rasp' 被误报）。所以这段只收明确的"说话/人声"词。
SPEECH_IN_SND = re.compile(r"\b(say|says|said|saying|speak|speaks|speaking|spoken|voice|voices|"
                           r"voiced|voicing|vocal|vocals|dialogue|narrat\w+|narration|"
                           r"whisper\w*|mutter\w*|shout\w*|yell\w*|exclaim\w*|answer\w*|repl\w+|"
                           r"ask\w*|sing|sings|singing|words?|lyrics?)\b", re.I)
LIPS_CLOSED = re.compile(r"(lips?\s+(remain|stay|close)|closes?\s+(her|his|their)\s+lips?|"
                         r"mouth\s+(closed|shut)|closes?\s+his\s+mouth)", re.I)

# base-en §4.7 / ref-en §6：非叙事音乐不许写抽象情绪词
MOOD_WORDS = re.compile(r"\b(emotional|emotion|tense|tension|sad|sadness|happy|"
                        r"melanchol(?:y|ic|ious)|melancholia|dramatic|mood|moody|feeling|"
                        r"sentimental|heroic|epic|haunting(?:ly)?|eerie|ominous|nostalgic|"
                        r"suspense(?:ful)?|uplifting|heart[- ]?warming|dreamy|gloomy|"
                        r"somber|sombre|tragic|joyful|peaceful|romantic|mysterious|lonely|loneliness)\b",
                        re.I)

# ref-en §3：summary 任务类型前缀（6 值，多类型用 " + " 连）
TASK_TYPES = ("keyframe completion", "reference generation", "video editing",
              "video continuation", "audio reuse", "audio reference")
# ref-en §4.1 / §4.2：保留档位
RETENTION_VISIBLE = ("fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference")
RETENTION_AUDIO = ("fully_copy", "partially_copy", "reference", "weak_reference")
LABEL_DEF = re.compile(r"<(Subject|Picture|Video|Audio)\s+(\d+)>")
VIDEO_EDIT_OPENER = "The target video is an edited version of <Video 1>."

# SKILL.md Tips：时长 4–15 秒
DURATION_RANGE = (4.0, 15.0)
FPS = 24
# 官方名义 4–15s＝96–360 帧；引擎放行区间按 B1 裁定（10-23）＝**107–345**（G6），
# 其中 107–123 属"官方允许、本机训练下限外"⇒ G6 放行但打风险 warn；旧 362 停止用于新批次。
# 这里保留官方口径供写稿契约判，不要把它当引擎放行区间。
FRAMES_RANGE = (int(DURATION_RANGE[0] * FPS), int(DURATION_RANGE[1] * FPS))   # 96–360

# ref-en §5.2：生成类任务 detailed_description 350–500 词
REF_WORD_RANGE = (350, 500)

MODES = {
    "t2va":   {"first_line": None, "fields": BASE_FIELDS, "body_field": "integrated_multimodal_description:",
               "structure": "整体视听时间轴（无图对齐行）"},
    "i2va":   {"first_line": I2VA_FIRST_LINE, "fields": BASE_FIELDS,
               "body_field": "integrated_multimodal_description:",
               "structure": "首帧锚定 → 动作起势 → 连续发展 → 结果或反应"},
    "fl2va":  {"first_line": FL2VA_FIRST_LINE, "fields": BASE_FIELDS,
               "body_field": "integrated_multimodal_description:",
               "structure": "首帧态 → 可见的中间变化 → 差异逐步收窄 → 末帧态"},
    "l2va":   {"first_line": L2VA_FIRST_LINE, "fields": BASE_FIELDS,
               "body_field": "integrated_multimodal_description:",
               "structure": "合理前置态 → 显式动作与过渡路径 → 末镜逐步收敛 → 落末帧"},
    "ref2va": {"first_line": None, "fields": REF_FIELDS, "body_field": "detailed_description:",
               "structure": "六段顺序锁死；风格句写在 [Shot 1] **之前**"},
}

# 格式核心（W2）：所有闸的"这是哪套格式 / 哪个模式"只从这里取答案。
# 这里只认**官方首行与字段指纹**；中文十块/无格式的判断属 prompt_format.detect 的活，
# 本文件不复制那张表（避免第三份）。
ALIGN_FIRST_PREFIX = "How the reference pictures align with the target video"
SKELETON_MODES = ("i2va", "fl2va", "l2va", "t2va")
# 六段里独有且够特殊的三个：判"六段"只能看这一组。用全量 REF_FIELDS 会把骨架自带的
# overall_soundscape / non_diegetic_music 误判成六段（老 G7 踩过）。
REF2VA_ONLY_FIELDS = ("subject_definitions:", "retention_analysis:", "detailed_description:")
# 镜像方向：判"六段里混进骨架"只能看骨架**独有**的那一个字段。BASE_FIELDS 里的
# overall_soundscape / non_diegetic_music 同时也是官方六段的最后两段，拿全量 BASE_FIELDS
# 去撞会把每一份合法 Ref2VA 稿误报成混用（2026-10-23 W2 复核时抓到）。
SKELETON_ONLY_FIELDS = ("integrated_multimodal_description:",)

# 房内自创标签（官方无此要求；`--house` 时才按 error 判）
HOUSE_LABELS = ("SPATIAL ANCHOR:", "ENVIRONMENT:", "UNIQUENESS LOCK:")

CJK = re.compile(u"[\u3400-\u9fff\uf900-\ufaff]")


# ---------------------------------------------------------------- 格式核心（W2，单一真源）
# 2026-10-23 W2：`check_preflight._detect_skeleton_mode/_g7_skeleton`、`h3_rule_gate.check_format`、
# `check_h3_dialogue` D10 一律调用本节。此前三处各自写首行/字段判断，同一份 FL2VA 稿在
# G7 里是 fl2va、在房内闸里按 I2VA 判（只许 Picture 1）、在对白闸里按 I2VA 首行判 ⇒ 必分叉。
def detect_skeleton_mode(text):
    """只按官方首行/起始字段判骨架模式：i2va / fl2va / l2va / t2va / None。

    · I2VA：逐字首行；
    · FL2VA / L2VA：以 `How the reference pictures align ...` 开头，首行出现 `Picture 2`
      的是 FL2VA（首尾帧），否则 L2VA（只有尾帧）；
    · T2VA：官方无首行，正文必须**直接以** integrated_multimodal_description: 开头。
    注意：本函数**不**看字段是否齐全——缺字段由调用方按 analyze() 报，别把"缺字段"误判成
    "模式认不出"（反过来也不行）。
    """
    t = (text or "").lstrip(u"\ufeff").lstrip()
    if not t:
        return None
    head = t.split("\n", 1)[0]
    if head.startswith(I2VA_FIRST_LINE):
        return "i2va"
    if head.startswith(ALIGN_FIRST_PREFIX):
        return "fl2va" if "Picture 2" in head else "l2va"
    if t.startswith(BASE_FIELDS[0]):
        return "t2va"
    return None


def detect_format(text):
    """H3 的格式类：`h3_ref2va` / `h3_skeleton` / None（不负责十块/图片）。

    判据从严到宽：六段独有字段 ≥2 > 骨架首行或三字段齐全。与 `prompt_format.detect`
    的 H3 分支**同口径**（那边仍管 sd_tenblock/plain），不另立第三套。
    """
    t = (text or "").lstrip(u"\ufeff")
    if not t.strip():
        return None
    if sum(1 for f in REF2VA_ONLY_FIELDS if f in t) >= 2:
        return "h3_ref2va"
    if detect_skeleton_mode(t) or all(f in t for f in BASE_FIELDS):
        return "h3_skeleton"
    return None


def detect_mode(text):
    """完整模式：i2va/fl2va/l2va/t2va/ref2va，认不出返回 None。

    优先级与 `prompt_format.detect` 对齐：六段指纹 ≥2 先判 ref2va（骨架里混进六段字段时，
    先按六段审再由各自的"混用"条目报出来），再按首行判四种基础模式。
    """
    fmt = detect_format(text)
    if fmt == "h3_ref2va":
        return "ref2va"
    if fmt == "h3_skeleton":
        return detect_skeleton_mode(text)
    return None


def shot_blocks(text):
    """按**行首** `[Shot N]` 切镜：[(shot_no|None, block)]。无切点则整篇当一镜（None）。

    ⚠️ 必须锚行首：官方 I2VA 首行里 `(from [Shot 1])` 也含 `[Shot 1]`，不锚会多切一段假镜。
    R18 与 D5（按 Shot 计人）共用这一份实现。
    """
    hits = list(re.finditer(r"(?m)^[ \t]*\[Shot\s*(\d+)\]", text or ""))
    if not hits:
        return [(None, text or "")]
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((int(m.group(1)), text[m.start():end]))
    return out


def analyze(text):
    """把"格式/模式/字段/正文起点/图片槽/分镜"一次算清，供各闸共用。

    返回 dict（全部只读）：
      format  h3_ref2va / h3_skeleton / None
      mode    i2va/fl2va/l2va/t2va/ref2va/None
      fields  本格式应有的字段元组
      counts  {字段: 次数}
      missing / duplicated  字段缺失/重复清单
      order_ok  True/False/None（字段不齐时 None＝判不了，不假装通过）
      body_field / body / body_start_ok
      pictures  {int} 被引用的 <Picture N>
      shots     [(no|None, block)]
    """
    t = (text or "").lstrip(u"\ufeff")
    fmt = detect_format(t)
    mode = detect_mode(t)
    if fmt == "h3_ref2va":
        fields = REF_FIELDS
        body_field = "detailed_description:"
    elif fmt == "h3_skeleton":
        fields = BASE_FIELDS
        body_field = BASE_FIELDS[0]
    else:
        fields, body_field = (), ""
    counts = {f: t.count(f) for f in fields}
    missing = [f for f in fields if counts[f] == 0]
    duplicated = [f for f in fields if counts[f] > 1]
    order_ok = None
    if fields and not missing:
        idx = [t.find(f) for f in fields]
        order_ok = idx == sorted(idx)
    body = section(t, body_field, [f for f in fields if f != body_field]) if body_field else ""
    return {
        "format": fmt, "mode": mode, "fields": fields, "counts": counts,
        "missing": missing, "duplicated": duplicated, "order_ok": order_ok,
        "body_field": body_field, "body": body,
        "body_start_ok": body.lstrip().startswith("[Shot 1]") if fmt == "h3_skeleton" else None,
        "pictures": {int(n) for n in re.findall(r"<Picture\s*(\d+)>", t)},
        "shots": shot_blocks(t),
    }


def section(text, field, stops):
    """取出某字段正文（到下一个字段名为止）。"""
    i = text.find(field)
    if i < 0:
        return ""
    j = len(text)
    for s in stops:
        k = text.find(s, i + len(field))
        if k > 0:
            j = min(j, k)
    return text[i + len(field):j].strip()


def sentences(s):
    return [x for x in re.split(r"(?<=[.!?])\s+", (s or "").strip()) if x.strip()]


def shots_of(body):
    """返回 [(shot_no, timestamp_or_None, text)]。"""
    out = []
    for m in re.finditer(r"\[Shot\s+(\d+)\]\s*(At\s+(\d{2}:\d{2}\.\d{3}))?", body):
        out.append((int(m.group(1)), m.group(3), m.start()))
    res = []
    for i, (no, ts, pos) in enumerate(out):
        end = out[i + 1][2] if i + 1 < len(out) else len(body)
        res.append((no, ts, body[pos:end]))
    return res


class Report(object):
    def __init__(self):
        self.rows = []

    def add(self, rid, sev, msg, cite):
        self.rows.append({"id": rid, "sev": sev, "msg": msg, "cite": cite})

    def count(self, sev):
        return sum(1 for r in self.rows if r["sev"] == sev)

    def render(self):
        lines = []
        for r in sorted(self.rows, key=lambda x: ({"error": 0, "warn": 1, "info": 2}[x["sev"]], x["id"])):
            lines.append("%-5s %-6s %s  [%s]" % (r["sev"].upper(), r["id"], r["msg"], r["cite"]))
        return lines


# ---------------------------------------------------------------- 校验
def validate(text, mode=None, seconds=None, frames=None, house=False, is_edit_task=False):
    """逐条核官方契约。返回 Report。所有 msg 都带官方出处。"""
    rp = Report()
    text = text or ""
    if text.startswith(u"\ufeff"):
        rp.add("F0", "error", "带 UTF-8 BOM（官方样例无 BOM，房内闸也判 error）", CITE_BASE + " §2.1")
        text = text.lstrip(u"\ufeff")
    mode = mode or detect_mode(text)
    if mode not in MODES:
        if detect_format(text) == "h3_skeleton":
            rp.add("F0", "error", "H3 骨架首行不是官方四形之一（I2VA/FL2VA/L2VA 用逐字句式；"
                   "T2VA 无首行、必须直接以 integrated_multimodal_description: 开头）",
                   CITE_BASE + " §2.1")
        else:
            rp.add("F0", "error", "认不出模式（既不是四种基础模式也不是 Ref2VA 六段）",
                   CITE_SKILL + " Workflow:1")
        return rp
    spec = MODES[mode]

    # ---- 时长（SKILL Tips：4–15 秒）
    secs = seconds
    if secs is None and frames:
        secs = frames / float(FPS)
    if secs is not None and not (DURATION_RANGE[0] - 1e-6 <= secs <= DURATION_RANGE[1] + 1e-6):
        rp.add("F6", "error", "时长 %.2fs 不在官方 4–15 秒（对应 %d–%d 帧 @24fps）"
               % (secs, FRAMES_RANGE[0], FRAMES_RANGE[1]), CITE_SKILL + " Tips:1")

    # S5：先把行尾统一成 LF 再判。以前 CRLF 稿的「首行后的空行」是 "\r\n"，
    # 这里 `rest[:1] != "\n"` 看到的是 "\r" ⇒ 合法稿被误判 F0 error（10-24 P2 实跑抓到）。
    # 只影响判读用的副本，不改原稿字节（原稿哈希另有快照校验）。
    head = text.lstrip().replace("\r\n", "\n").replace("\r", "\n")
    # ---- F0 首行
    if spec["first_line"]:
        want_prefix = spec["first_line"].split("{")[0].strip()
        if not head.startswith(want_prefix):
            rp.add("F0", "error", "%s 首行不是官方指令行（应以 %r 开头）" % (mode.upper(), want_prefix[:60]),
                   CITE_BASE + " §2.1")
        else:
            first, rest = head.split("\n", 1)
            if rest[:1] != "\n":
                # 官方 base-en §2.1 是 must（"followed by a blank line"）；G7 早就按 error 判，
                # 写稿契约端不能只 warn——同一件事两把尺就会"写作时绿、提交时红"。
                rp.add("F0", "error", "官方 §2.1：首行之后必须空一行再进核心字段", CITE_BASE + " §2.1")
            if mode in ("fl2va", "l2va"):
                if not re.search(r"\d+\.\d{2}-second mark", first):
                    rp.add("F0", "error", "对齐行的秒数必须写成两位小数 S.SS", CITE_BASE + " §2.1")
                if secs is not None:
                    marks = [float(x) for x in re.findall(r"(\d+\.\d+)-second mark", first)]
                    if marks and secs and abs(max(marks) - secs) > 0.05:
                        rp.add("F0", "warn", "对齐行末点 %.2fs 与实际时长 %.2fs 不符"
                               % (max(marks), secs), CITE_BASE + " §2.1")
                    if marks and 0.0 not in marks and mode == "fl2va":
                        rp.add("F0", "warn", "FL2VA 对齐行应含 0.00-second mark", CITE_BASE + " §2.1")
    elif mode == "t2va" and head.startswith("For the target video"):
        rp.add("F0", "error", "T2VA 不该有图对齐首行", CITE_BASE + " §2.1")

    # ---- F1 字段齐全、各一次、顺序对
    pos = -1
    for f in spec["fields"]:
        n = text.count(f)
        if n != 1:
            rp.add("F1", "error", "字段 %s 出现 %d 次（官方要求各一次）" % (f, n),
                   (CITE_REF if mode == "ref2va" else CITE_BASE) + " §1/§2.2")
        k = text.find(f)
        if k >= 0:
            if k < pos:
                rp.add("F1", "error", "字段顺序错了：%s 应在前一个字段之后" % f,
                       (CITE_REF if mode == "ref2va" else CITE_BASE) + " §1")
            pos = k
    body = section(text, spec["body_field"], [f for f in spec["fields"] if f != spec["body_field"]])

    # ---- F2 正文英文（<d> 内台词与引号内可见文字豁免）
    probe = D_TAG.sub(" ", body)
    probe = re.sub(r"\"[^\"]*\"", " ", probe)
    zh = [(i + 1, l.strip()[:50]) for i, l in enumerate(probe.splitlines()) if CJK.search(l)]
    if zh:
        rp.add("F2", "error", "重写段落有 %d 处非英文（第 %d 行：%s）——豁免仅 <d> 内台词与引号内可见文字"
               % (len(zh), zh[0][0], zh[0][1]), CITE_SKILL + " Output Rules:1 / " + CITE_REF + " 开头")

    # ---- F3 分镜与切点
    sh = shots_of(body)
    if not sh:
        rp.add("F3", "error", "正文里没有 [Shot N] 分镜标记", CITE_BASE + " §4.2")
    else:
        if sh[0][0] != 1:
            rp.add("F3", "warn", "首个分镜应是 [Shot 1]", CITE_BASE + " §4.2")
        if sh[0][1]:
            rp.add("F3", "error", "[Shot 1] 不带时间码", CITE_BASE + " §4.2")
        prev = 0.0
        for no, ts, _ in sh[1:]:
            if not ts:
                rp.add("F3", "error", "[Shot %d] 缺切点时间码 At MM:SS.mmm" % no, CITE_BASE + " §4.2")
                continue
            mm, ss = ts.split(":")
            t = int(mm) * 60 + float(ss)
            if t <= prev:
                rp.add("F3", "error", "[Shot %d] 切点 %.3f 未严格递增（上一个 %.3f）" % (no, t, prev),
                       CITE_BASE + " §4.2")
            if secs is not None and t > secs + 1e-6:
                rp.add("F3", "error", "[Shot %d] 切点 %.3fs 超出时长 %.2fs" % (no, t, secs),
                       CITE_BASE + " §4.2")
            prev = t
        # 切镜短语白名单
        for m in re.finditer(r"\[Shot\s+\d+\]\s*At\s+\d{2}:\d{2}\.\d{3},\s*([^.]{0,40})", body):
            frag = m.group(1).lower()
            if not any(p in frag for p in CUT_PHRASES):
                rp.add("F4", "warn", "切镜措辞不在官方 5 个白名单里：%r" % m.group(1).strip()[:40],
                       CITE_BASE + " §4.2")
        for m in NON_HARD_CUT.finditer(body):
            rp.add("F4", "warn", "出现非硬切 %r——官方规定仅用户明确要求时才用" % m.group(0),
                   CITE_BASE + " §4.2")

    # ---- F5 运镜
    # 两种写法都要按 §4.3 的词表判：官方自然句 `The camera pushes in ...`
    # 与房内标签式 `Push In at slow speed: the camera opens on ...`／`Camera: Push In ...`。
    # 只判 "the camera" 后面那一截会漏两类：① 标签式稿里的器材名词（Dolly Zoom）与中档词
    # （at normal speed）——10-13 用坏稿实测确实漏；② 反过来把房内稿误判——类型词写在
    # "the camera" **前面**当标签（P1A：`Push In at slow speed: the camera opens on ...`），
    # 只看后半截就报"没用官方类型词"，12 份假 warn 全是这么来的。
    # 所以每句都带 80 字前置上下文一起判。
    wins = []
    for m in re.finditer(r"[Tt]he camera ([^.]{0,120})", body):
        wins.append((body[max(0, m.start() - 80):m.start()], m.group(1)))
    wins += [("", h) for h in re.findall(r"\bcamera\s*:\s*([^.]{0,120})", body, re.I)]
    for pre, frag in wins:
        # "the camera cuts to ..." 是**切镜**句（官方 §4.2 白名单），不是运镜句，别按 §4.3 判
        if re.match(r"\s*(cuts?|transitions?|changes?|switches?)\s+to\b", frag, re.I):
            continue
        g = GEAR.search(pre + frag)
        if g:
            rp.add("F5", "error", "运镜写了器材名词 %r（官方只给 12 行运动类型）" % g.group(0),
                   CITE_BASE + " §4.3")
        s = SUPERFLUOUS.search(frag)
        if s:
            rp.add("F5", "warn", "%r 属中档幅度/常速，官方口径是省略不写" % s.group(0),
                   CITE_BASE + " §4.3")
        if not CAMERA_RE.search(frag) and not any(n.lower() in (pre + frag).lower()
                                                 for n in CAMERA_NAMES):
            rp.add("F5", "warn", "这句运镜没用官方 12 行类型词：%r" % frag.strip()[:60],
                   CITE_BASE + " §4.3")
    for a in CAMERA_ALIAS:
        if re.search(re.escape(a), body, re.I):
            rp.add("F5", "warn", "%s 是简写，官方全称是 %s" % (a, CAMERA_ALIAS[a]), CITE_BASE + " §4.3")
    if re.search(r"Camera\s*:\s*\S", body):
        rp.add("F5", "info", "用了 `Camera:` 标签式写法；官方要求写成镜内自然英文动作句"
               "（房内 80 份现役稿都这么写，属房内风格）", CITE_BASE + " §4.3")

    # ---- F7 说话人与台词
    for m in D_TAG.finditer(body):
        pre = body[max(0, m.start() - 160):m.start()]
        if not SPEAKER_ID.search(pre):
            rp.add("F7", "error", "<d> 前 160 字内没有 (Sx) 说话人 ID：%r" % m.group(2)[:24],
                   CITE_BASE + " §4.4")
        if not SPEECH_LEAD.search(pre):
            rp.add("F7", "warn", "<d> 前缺说话动词/voice 引导", CITE_BASE + " §4.4")
        if VOICEOVER_PHRASE in pre:
            after = body[m.end():m.end() + 140]
            if not LIPS_CLOSED.search(after):
                rp.add("F7", "error", "voiceover 的 <d> 之后必须写明嘴唇闭合", CITE_BASE + " §4.4")
        if "[" in m.group(2) or "]" in m.group(2):
            rp.add("F7", "warn", "<d> 内只放语言标记与原文，别再有方括号", CITE_BASE + " §4.4")
    for m in SPEAKER_ID.finditer(body):
        pass
    if re.search(r"\(S\d+\s*,\s*S\d+\)", body):
        rp.add("F7", "warn", "齐声写作 (S1,S2)，逗号后不留空格", CITE_BASE + " §4.4")

    # ---- F8 / F9 两段声音
    snd_field = "overall_soundscape:"
    snd = section(text, snd_field, ["non_diegetic_music:"] + [f for f in spec["fields"] if f.endswith(":") and f != snd_field])
    if snd.strip() and snd.strip() != "N/A":
        n = len(sentences(snd))
        if not 1 <= n <= 4:
            rp.add("F8", "warn", "overall_soundscape 应 1–4 句一段，现在 %d 句" % n, CITE_BASE + " §4.6")
        if "<d>" in snd or "</d>" in snd:
            rp.add("F8", "error", "台词跑进了 overall_soundscape（官方：台词只在正文 <d> 内）",
                   CITE_BASE + " §4.6 / " + CITE_REF + " §6")
        _sv = SPEECH_IN_SND.search(snd)
        if _sv:
            rp.add("F8", "warn", "overall_soundscape 里出现说话/人声词 %r——官方那段只写环境声、"
                   "动作声与**非语言**人声（台词留在正文 <d> 内）。若本意是声明"
                   "\"这里没人说话\"：房内 D9 判负面声明无效，直写听到的声就行，别写 no voice"
                   % _sv.group(0), CITE_BASE + " §4.6")
        q = re.findall(r"[\"“][^\"”]{2,}[\"”]", snd)
        if any(CJK.search(x) for x in q):
            rp.add("F8", "error", "overall_soundscape 里出现引号中文＝台词泄漏", CITE_REF + " §6")
    elif snd.strip() == "N/A":
        rp.add("F8", "info", "overall_soundscape 写成 N/A —— 官方规定仅在用户明确要求全片静音时才用",
               CITE_BASE + " §4.6")
    mus = section(text, "non_diegetic_music:", [])
    if mus.strip() and mus.strip() != "N/A":
        n = len(sentences(mus))
        if not 1 <= n <= 3:
            rp.add("F9", "warn", "non_diegetic_music 应 1–3 句，现在 %d 句" % n, CITE_BASE + " §4.7")
        mw = MOOD_WORDS.search(mus)
        if mw:
            rp.add("F9", "warn", "非叙事音乐里出现抽象情绪词 %r（官方要求只写乐器/速度/节奏/强弱）"
                   % mw.group(0), CITE_BASE + " §4.7")

    # ---- F10 Ref2VA 专项
    if mode == "ref2va":
        summ = section(text, "summary:", ["retention_analysis:"])
        m = re.match(r"\s*\[([^\]]+)\]", summ)
        if not m:
            rp.add("F10", "error", "summary 必须以方括号任务类型前缀开头", CITE_REF + " §3")
        else:
            for t in [x.strip() for x in m.group(1).split("+")]:
                if t not in TASK_TYPES:
                    rp.add("F10", "error", "summary 任务类型 %r 不在官方 6 值里" % t, CITE_REF + " §3")
            if "video editing" in m.group(1) and VIDEO_EDIT_OPENER not in summ:
                rp.add("F10", "warn", "video editing 任务的 summary 前缀后应紧跟 %r" % VIDEO_EDIT_OPENER,
                       CITE_REF + " §3")
        ret = section(text, "retention_analysis:", ["detailed_description:"])
        # ref-en §4.1/§4.2 的档位是 **fixed English values**（硬规），不是建议措辞：
        #  可见 <Picture>/<Video>/<Subject> → fully_preserved|partially_preserved|attribute_transfer|weak_reference
        #  音频 <Audio> → fully_copy|partially_copy|reference|weak_reference
        # 此前只 warn"没标记"，等于把硬规判软了；现在：缺标记仍 warn（官方没要求每行都写），
        # 但**写了非法值/写错家族**按 error。
        _TIER_VIS, _TIER_AUD = set(RETENTION_VISIBLE), set(RETENTION_AUDIO)
        _tier_re = re.compile(r"\b([a-z][a-z_]{3,}(?:_preserved|_copy|preserved|reference|transfer)\b)")
        for line in [l for l in ret.splitlines() if l.strip()]:
            mk = re.findall(r"\b(fully_preserved|partially_preserved|attribute_transfer|"
                            r"weak_reference|fully_copy|partially_copy|reference)\b", line)
            if not mk:
                rp.add("F10", "warn", "retention_analysis 这一行没有档位标记：%r" % line.strip()[:50],
                       CITE_REF + " §4")
            looks = [t for t in _tier_re.findall(line) if t not in mk]
            for t in looks:
                rp.add("F10", "error", "retention_analysis 用了**非官方档位词** %r"
                                       "（官方是 fixed English values，见 §4.1/§4.2）" % t,
                       CITE_REF + " §4.1")
            aud_ctx = "<Audio" in line or re.search(r"\baudio\b", line, re.I)
            vis_ctx = re.search(r"<(Picture|Video|Subject)", line)
            for t in mk:
                if aud_ctx and vis_ctx:
                    continue          # 同一行两边都提到：不判家族，只判合法性
                if aud_ctx and t not in _TIER_AUD:
                    rp.add("F10", "error", "这一行是 <Audio> 语境，档位 %r 属于可见家族；"
                                           "音频档只能用 %s" % (t, sorted(_TIER_AUD)),
                           CITE_REF + " §4.2")
                if vis_ctx and not aud_ctx and t not in _TIER_VIS:
                    rp.add("F10", "error", "这一行是 <Picture>/<Video> 语境，档位 %r 属于音频家族；"
                                           "可见档只能用 %s" % (t, sorted(_TIER_VIS)),
                           CITE_REF + " §4.1")
            if SPEAKER_ID.search(line):
                rp.add("F10", "error", "retention_analysis 里不写 (Sx)", CITE_REF + " §5.4")
        sd = section(text, "subject_definitions:", ["summary:"])
        # 官方 §2：只作为**来源引用**的 <Picture N>/<Video N> 写在某个 <Subject N> 定义里、不单列一行，
        # 这类标签本来就不会在正文再出现 ⇒ 只有"单独成行定义"的才算必须在正文用到。
        standalone, cited = set(), set()
        for line in sd.splitlines():
            line = line.strip()
            if not line:
                continue
            m0 = re.match(r"^<(Subject|Picture|Video|Audio)\s+(\d+)>", line)
            if m0:
                standalone.add("%s %s" % (m0.group(1), m0.group(2)))
            for mm in LABEL_DEF.finditer(line):
                cited.add("%s %s" % (mm.group(1), mm.group(2)))
        defined = standalone
        used = set()
        for m in LABEL_DEF.finditer(body):
            used.add("%s %s" % (m.group(1), m.group(2)))
        for u in sorted(used - defined - cited):
            rp.add("F10", "error", "正文用了未定义的标签 <%s>" % u, CITE_REF + " §2 / Output Rules:2")
        for d in sorted(defined - used):
            rp.add("F10", "warn" if d.startswith("Subject") else "info",
                   "定义了却没在正文使用的标签 <%s>%s"
                   % (d, "" if d.startswith("Subject") else "（若只作来源引用，官方允许不单列一行）"),
                   CITE_REF + " §2")
        if not is_edit_task:
            w = len(re.findall(r"[A-Za-z']+", body))
            if not (REF_WORD_RANGE[0] <= w <= REF_WORD_RANGE[1]):
                # 官方 §5.2：对话密集内容优先装下完整台词时间线，不机械凑字数 ⇒ 有台词就降级为 info
                rp.add("F10", "info" if "<d>" in body else "warn",
                       "detailed_description %d 词，官方生成类任务口径 350–500 词"
                       "（对话密集可优先保台词时间线；编辑类不受此限）" % w, CITE_REF + " §5.2")
        i_style = body.find("[Shot 1]")
        if i_style > 0:
            pre = body[:i_style].strip()
            if not pre:
                rp.add("F10", "warn", "Ref2VA 的风格句要写在 [Shot 1] **之前**（一到两句英文）",
                       CITE_REF + " §5.2")

    # ---- F11 屏幕文字
    # 官方 §4.5：画面里可见的横幅/招牌/标签/字幕要**逐字保原文并放进英文双引号**；
    # §4.4：<d> 里的台词保留原语言。所以判之前要先挖掉这两种豁免，否则**每一句中文台词都会
    # 被误报成"可见文字漏了引号"**（10-13 拿房内 15 份现役稿实测：6 份假 warn）。
    # 正文里的裸中文已由 F2 判 error，本条只补 F2 够不着的地方（声景/Ref2VA 三段等）。
    probe = D_TAG.sub(" ", text)
    probe = re.sub(r"\"[^\"]*\"", " ", probe)
    m = re.search(u"[\u3400-\u9fff]{2,}", probe)
    if m and not zh:                     # zh＝F2 已经在正文里抓到的裸中文，别同一条病再报两遍
        rp.add("F11", "warn", "有没进双引号也没进 <d> 的中文 %r——"
               "画面可见文字要逐字保原文并进英文双引号，其余段落要英文"
               % m.group(0)[:20], CITE_BASE + " §4.5 / §4.6")

    # ---- F12 占位符/剧情梗概
    for pat, msg in ((r"__(?:PROMPT|REF1|W|H|LEN|SEED|PREFIX)__", "留着模板占位符没替换"),
                     (r"<Subject N>|<Picture N>|<Video N>|<Audio N>", "留着 <Xxx N> 占位没换成编号"),
                     (r"\bTBD\b|\bTODO\b|\bXXX\b", "留着 TBD/TODO")):
        m = re.search(pat, text)
        if m:
            rp.add("F12", "error", "%s（%r）" % (msg, m.group(0)), CITE_SKILL + " Output Rules:3")

    # ---- H 房内标签（非官方）
    if house:
        for lab in HOUSE_LABELS:
            if lab not in text:
                rp.add("H7", "error", "缺房内标签 %s（⚠ 官方无此要求，是本机 check_h3_dialogue D7 的加严）"
                       % lab, "房内规 D7")
    else:
        if any(lab in text for lab in HOUSE_LABELS):
            rp.add("H7", "info", "稿里用了房内自创标签（SPATIAL ANCHOR/ENVIRONMENT/UNIQUENESS LOCK）；"
                   "官方无此要求，内容本身官方都要写，只是不打标签", CITE_BASE + " §4.1")
    return rp


# ---------------------------------------------------------------- 强制填充
def first_line(mode, shots=1, seconds=None):
    if mode == "i2va":
        return I2VA_FIRST_LINE
    n = max(1, int(shots))
    s = "%.2f" % (seconds if seconds else n * 124 / float(FPS))
    if mode == "fl2va":
        return FL2VA_FIRST_LINE.format(N=n, S=s)
    if mode == "l2va":
        return L2VA_FIRST_LINE.format(N=n, S=s)
    return ""


def camera_sentence(cam_type, amplitude=None, speed=None, purpose=None, style="official"):
    """按官方 §4.3 拼一句合法运镜：类型（12 行全称）＋幅度（仅 small/large）＋速度（仅 slow/fast）。

    style="official"（默认，强制对齐官方）：写成镜内自然英文动作句——
        `The camera pulls out with small amplitude at slow speed, ...`
    style="house"：房内 80 份现役稿与 10-09 人审金样用的标签式——
        `Camera: Pull Out with small amplitude at slow speed, ...`
    官方 §4.3 明确"不要堆成句尾标签"，所以 house 只是兼容既有已审稿件，不是推荐写法。
    """
    t = CAMERA_ALIAS.get(cam_type, cam_type)
    if t not in CAMERA_NAMES:
        raise ValueError("运镜类型 %r 不在官方 12 行里：%s" % (cam_type, " / ".join(CAMERA_NAMES)))
    if amplitude and amplitude not in AMPLITUDE:
        raise ValueError("幅度只有 %s（中档按官方省略，收到 %r）" % (" / ".join(AMPLITUDE), amplitude))
    if speed and speed not in SPEED:
        raise ValueError("速度只有 %s（常速按官方省略，收到 %r）" % (" / ".join(SPEED), speed))
    if style == "house":
        bits = [t]
        if amplitude:
            bits.append(amplitude)
        if speed:
            bits.append(speed)
        s = "Camera: " + " ".join(bits)
        if purpose:
            s += ", " + purpose.strip().rstrip(".")
        return re.sub(r"\s+", " ", s).strip() + "."
    verb = {"Static Shot": "holds a static shot", "Shake Slightly": "shakes slightly",
            "Shake Strongly": "shakes strongly",
            "POV": "takes the subject's point of view"}.get(t)
    if verb:
        core = verb
    else:
        core = {
            "Zoom In": "zooms in", "Zoom Out": "zooms out",
            "Push In": "pushes in", "Pull Out": "pulls out",
            "Pan Left": "pans left", "Pan Right": "pans right",
            "Truck Left": "trucks left", "Truck Right": "trucks right",
            "Tilt Up": "tilts up", "Tilt Down": "tilts down",
            "Pedestal Up": "pedestals up", "Pedestal Down": "pedestals down",
            "Arc Shot": "arcs around the subject",
            "Tracking Shot": "tracks the moving subject",
            "Roll Clockwise": "rolls clockwise", "Roll Counterclockwise": "rolls counterclockwise",
        }[t]
    parts = ["The camera", core]
    if amplitude:
        parts.append(amplitude)
    if speed:
        parts.append(speed)
    s = " ".join(parts)
    if purpose:
        s += ", " + purpose.strip().rstrip(".")
    return re.sub(r"\s+", " ", s).strip() + "."


def parse_camera(s):
    """把自由写法的一句运镜拆成官方四元组 (类型, 幅度, 速度, 目的)，供 fill() 强制对齐用。
    拆不出合法类型就抛错——宁可失败，不要静默产出不合规的运镜句。"""
    s = (s or "").strip().rstrip(".")
    for a, b in CAMERA_ALIAS.items():
        s = re.sub(re.escape(a), b, s, flags=re.I)
    hit = None
    for n in sorted(CAMERA_NAMES, key=len, reverse=True):
        if re.search(re.escape(n), s, re.I):
            hit = n
            break
    if not hit:
        raise ValueError("运镜类型认不出来：%r（官方 12 行：%s）" % (s[:60], " / ".join(CAMERA_NAMES)))
    amp = next((a for a in AMPLITUDE if a.lower() in s.lower()), None)
    spd = next((v for v in SPEED if v.lower() in s.lower()), None)
    rest = re.sub(re.escape(hit), " ", s, flags=re.I)
    for x in [amp, spd]:
        if x:
            rest = re.sub(re.escape(x), " ", rest, flags=re.I)
    # 官方口径：medium/moderate 幅度与 normal/steady 速度**省略不写** ⇒ 从剩余里也剔掉
    rest = SUPERFLUOUS.sub(" ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" ,;")
    rest = re.sub(r"^(with|at|and|,)\s+", "", rest, flags=re.I).strip(" ,;")
    return hit, amp, spd, (rest or None)


def fill(spec, camera_style="official"):
    """按官方骨架强制拼稿。不合规的输入直接抛错，不会静默产出坏稿。

    spec 例：
      {"mode":"i2va", "seconds":5.17, "style":"Live-action, cinematic",
       "house": {"axis":"...", "env":"...", "lock":"..."},          # 可选，房内标签（非官方）
       "shots":[{"no":1, "text":"...", "camera":("Tracking Shot","with large amplitude",
                                                 "at fast speed","following the shove")}],
       "soundscape":"...", "music":"N/A",
       # ref2va 另需：subject_definitions / summary / retention_analysis（字符串）
      }
    """
    mode = spec.get("mode", "i2va")
    if mode not in MODES:
        raise ValueError("mode 只能是 %s" % "/".join(MODES))
    secs = spec.get("seconds")
    if secs is not None and not (DURATION_RANGE[0] <= secs <= DURATION_RANGE[1]):
        raise ValueError("时长 %.2fs 不在官方 4–15 秒" % secs)
    shots = spec.get("shots") or []
    if not shots:
        raise ValueError("至少要一个 shot")

    house = spec.get("house") or {}
    head = []
    if house.get("axis"):
        head.append("SPATIAL ANCHOR: %s" % house["axis"].strip().rstrip(".") + ".")
    if house.get("env"):
        head.append("ENVIRONMENT: %s" % house["env"].strip().rstrip(".") + ".")
    if house.get("lock"):
        head.append("UNIQUENESS LOCK: %s" % house["lock"].strip().rstrip(".") + ".")

    segs = []
    for i, sh in enumerate(shots):
        no = int(sh.get("no", i + 1))
        seg = "[Shot %d]" % no
        if no > 1:
            at = sh.get("at")
            if not at or not re.match(r"^\d{2}:\d{2}\.\d{3}$", str(at)):
                raise ValueError("[Shot %d] 切点必须是 At MM:SS.mmm（现在 %r）" % (no, at))
            phrase = sh.get("cut_phrase", "the camera cuts to")
            if phrase not in CUT_PHRASES:
                raise ValueError("切镜措辞 %r 不在官方 5 个白名单里" % phrase)
            seg += " At %s, %s" % (at, phrase)
        bits = []
        if no == 1:
            if spec.get("style") and mode != "ref2va":
                bits.append(spec["style"].strip().rstrip(".") + ".")
            bits += head
        if sh.get("text"):
            bits.append(str(sh["text"]).strip())
        if sh.get("camera"):
            c = sh["camera"]
            args = list(c) if isinstance(c, (list, tuple)) else [c]
            bits.append(camera_sentence(*args, style=camera_style))
        segs.append(re.sub(r"\s+", " ", seg + " " + " ".join(b for b in bits if b)).strip())

    chunks = []
    fl = first_line(mode, len(shots), secs)
    if fl:
        chunks.append(fl)
    if mode == "ref2va":
        for f in ("subject_definitions", "summary", "retention_analysis"):
            v = (spec.get(f) or "").strip()
            if not v:
                raise ValueError("Ref2VA 缺 %s（六段顺序锁死，一段都不能少）" % f)
            chunks.append("%s:\n%s" % (f, v))
        dd = []
        if spec.get("style"):                      # 官方：风格句写在 [Shot 1] 之前
            dd.append(spec["style"].strip().rstrip(".") + ".")
        dd += segs
        chunks.append("detailed_description:\n" + "\n".join(dd))
    else:
        chunks.append("%s\n%s" % (MODES[mode]["body_field"], "\n".join(segs) if len(segs) > 1
                                 else segs[0]))
    chunks.append("overall_soundscape:\n%s" % (spec.get("soundscape") or "N/A").strip())
    chunks.append("non_diegetic_music:\n%s" % (spec.get("music") or "N/A").strip())
    return "\n\n".join(chunks) + "\n"


# ---------------------------------------------------------------- 自测：拿官方自己的例子当标准答案
def _fenced_blocks(path):
    txt = io.open(path, encoding="utf-8").read()
    return re.findall(r"```text\n([\s\S]*?)```", txt)


def selftest():
    """用官方 Case 1–4 与 Ref2VA 完整示例回测本校验器：官方稿必须 0 error。"""
    base = os.path.join(OFFICIAL_DIR, CITE_BASE)
    ref = os.path.join(OFFICIAL_DIR, CITE_REF)
    cases = []
    txt = io.open(base, encoding="utf-8").read()
    for m in re.finditer(r"### Case (\d+): (\w+)\n([\s\S]*?)```text\n([\s\S]*?)```", txt):
        cases.append(("Case %s %s" % (m.group(1), m.group(2)), m.group(2).lower(), m.group(4)))
    for blk in _fenced_blocks(ref):
        if blk.strip().startswith("subject_definitions:"):
            cases.append(("Ref2VA 完整示例", "ref2va", blk))
    rows = []
    for name, mode, body in cases:
        rp = validate(body, mode=mode, seconds=None, house=False)
        rows.append((name, mode, rp.count("error"), rp.count("warn"), rp.count("info"),
                     [r for r in rp.rows if r["sev"] == "error"]))
    print("%-22s %-8s %5s %5s %5s" % ("官方样例", "模式", "err", "warn", "info"))
    bad = 0
    for name, mode, e, w, i, errs in rows:
        print("%-22s %-8s %5d %5d %5d" % (name, mode, e, w, i))
        for r in errs:
            print("      ERROR %s %s [%s]" % (r["id"], r["msg"], r["cite"]))
        if e:
            bad += 1
    print("\n自测：%d 份官方样例，%s" % (len(rows), "全部 0 error ✅" if not bad
                                          else "🔴 %d 份被误判——校验器要修" % bad))
    return 1 if bad else 0


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="H3 官方写稿契约：校验与强制填充")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="校验稿件是否合规官方契约")
    c.add_argument("files", nargs="*")
    c.add_argument("--dir", default=None, help="扫这个目录下所有 .txt（与其它闸同用法）")
    c.add_argument("--mode", choices=list(MODES), default=None, help="缺省自动判")
    c.add_argument("--seconds", type=float, default=None)
    c.add_argument("--frames", type=int, default=None)
    c.add_argument("--house", action="store_true", help="把房内 D7 三标签也当 error 判")
    c.add_argument("--json", action="store_true")
    c.add_argument("--selftest", action="store_true", help="改用官方 Case 1–4 与 Ref2VA 完整示例自测")
    s = sub.add_parser("spec", help="打印固化的官方常量（JSON）")
    s.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.cmd == "spec":
        data = {"modes": {k: {"first_line": v["first_line"], "fields": list(v["fields"]),
                              "structure": v["structure"]} for k, v in MODES.items()},
                "camera_types": CAMERA_NAMES, "amplitude": list(AMPLITUDE), "speed": list(SPEED),
                "cut_phrases": list(CUT_PHRASES), "task_types": list(TASK_TYPES),
                "retention_visible": list(RETENTION_VISIBLE), "retention_audio": list(RETENTION_AUDIO),
                "voiceover_phrase": VOICEOVER_PHRASE, "continuity_phrases": list(CONTINUITY_PHRASES),
                "duration_seconds": list(DURATION_RANGE), "frames_at_24fps": list(FRAMES_RANGE),
                "ref_word_range": list(REF_WORD_RANGE), "house_labels_only": list(HOUSE_LABELS),
                "official_source": OFFICIAL_DIR}
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if a.cmd == "check":
        if a.selftest:
            return selftest()
        files = list(a.files)
        if a.dir:
            if not os.path.isdir(a.dir):
                print("🔴 --dir 不存在：%s" % a.dir)
                return 4
            files += [os.path.join(a.dir, f) for f in sorted(os.listdir(a.dir)) if f.endswith(".txt")]
        if not files:
            print("要么给稿件路径／--dir，要么加 --selftest")
            return 4
        bad = 0
        for f in files:                       # ← 必须遍历 files（含 --dir 扫到的），
            txt = io.open(f, encoding="utf-8", errors="replace").read()   #   只遍历 a.files 会静默全过
            rp = validate(txt, mode=a.mode, seconds=a.seconds, frames=a.frames, house=a.house)
            e, w, i = rp.count("error"), rp.count("warn"), rp.count("info")
            if a.json:
                print(json.dumps({"file": f, "mode": a.mode or detect_mode(txt),
                                  "error": e, "warn": w, "info": i, "rows": rp.rows},
                                 ensure_ascii=False, indent=2))
            else:
                print("===== %s ｜ 模式 %s ｜ error=%d warn=%d info=%d"
                      % (os.path.basename(f), a.mode or detect_mode(txt), e, w, i))
                for line in rp.render():
                    print("  " + line)
            if e:
                bad += 1
        print("官方契约：%s（实检 %d 份%s）"
              % ("全过" if not bad else "%d 份有 error" % bad, len(files),
                 "，房内 D7 三标签也当硬要求" if a.house else ""))
        return 1 if bad else 0
    ap.print_help()
    return 4


if __name__ == "__main__":
    sys.exit(main())
