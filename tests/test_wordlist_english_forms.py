# -*- coding: utf-8 -*-
"""批 16（待裁-16 落地）：判据的**英文对等形**回归测试。

要防的病灶只有一句话：**正文换成英文之后，守卫没跟着换，于是它"看不见"了**。
看不见有两种坏法，都各配一组断言：
· **假阴**（守卫消失）——英文病灶句写出来不响 ⇒ 正向用例：同一句话中文响、英文也响；
· **假阳**（守卫过宽）——英文形比中文形宽，把已验收稿判成缺陷 ⇒ 反向用例：
  易混词（highlight／notice／staffed／never touches the ground）不许命中，
  且 20 份现役真源上 H3R20 的 error 必须归零（改前实测 7 条全是假报）。

匹配语义（词边界＋复数容忍）本身在 `prompt_format` 的自检里已经钉住；
这里钉的是**两张闸接上了这把尺**，以及**每条英文词形都对得上一个中文词形**。
"""
import io
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # engine/
for _p in (os.path.join(os.path.dirname(ROOT), "tools"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

WZY = r"D:\AIWorkflow\tmp\wzy"
if WZY not in sys.path:
    sys.path.insert(0, WZY)
import prompt_format as PF          # noqa: E402
import h3_rule_gate as HG           # noqa: E402
import prompt_lint as PL            # noqa: E402

MF = os.path.join(WZY, "h3_rewrite_manifest.json")
BK = r"E:\本地工作流规范手册\99_维护\_改前备份_20261003_正文英译"


def _live_texts():
    mf = json.load(io.open(MF, encoding="utf-8"))
    out = []
    for f in mf["files"]:
        if os.path.isfile(f["path"]):
            out.append((os.path.basename(f["path"]), io.open(f["path"], encoding="utf-8").read()))
    return out


LIVE = _live_texts()
pytestmark = pytest.mark.skipif(not LIVE, reason="改写清单或现役真源不在场")


def _shot_rows(text):
    import contextlib
    s = HG.synth_shot(text)
    with contextlib.redirect_stdout(io.StringIO()):
        return dict(HG.check_format(text) + HG.check_shot(None, s, text)
                    + HG.check_space(text) + HG.check_style(text) + HG.check_decisive(text))


# ─────────────────────────────── 1. 匹配器语义（英文形要能命中）─────────────────
@pytest.mark.parametrize("entry,text", [
    ("light", "cold light leaking between towers"),
    ("light", "the street lamps give off a soft light"),
    ("strike", "the fist strikes her cheek"),
    ("never bends", "the shaft never bends and never doubles"),
    ("fully bound", "fully bound in white hemp cloth"),
])
def test_english_entry_fires(entry, text):
    assert entry in PF.match_terms(text, [entry]), "英文词形在英文正文上打不中＝守卫仍瞎"


@pytest.mark.parametrize("entry,text", [
    ("light", "a highlighted edge"),
    ("no", "there is nothing here"),
    ("not", "note the position"),
    ("staff", "the staffed desk"),
    ("strike", "a striking distance"),          # striking ≠ strike 的 -s/-es 档，不该命中
    ("leak", "a leaky pipe"),
])
def test_english_entry_does_not_overfire(entry, text):
    assert PF.match_terms(text, [entry]) == [], "%r 从 %r 里吃下了不该算的词" % (entry, text)


# ─────────────────────────────── 2. 每张补过的表：中英两侧都得有牙 ───────────────
@pytest.mark.parametrize("name", [
    "CAM_RESULT_ONLY", "LIGHT_NOUN", "LIGHT_BAD_V", "FX_BAD", "FX_POS",
    "ABSTRACT", "BODY", "底线_MARK", "UNWRAP", "VIOLENCE", "FACE", "R7_TAIL_RISK",
    "MUSIC_WORDS",
])
def test_table_has_both_language_forms(name):
    words = getattr(HG, name)
    cn = [w for w in words if not w.isascii()]
    en = [w for w in words if w.isascii()]
    assert cn and en, "%s 缺一侧（中文 %d／英文 %d）⇒ 换语言就失明" % (name, len(cn), len(en))


def test_lock_lists_have_both_language_forms():
    """`LOCK_*` 是 check_shot 里的函数级表，探针按 AST 也取得到——这里直接查它俩合并后的形。"""
    src = io.open(os.path.join(WZY, "h3_rule_gate.py"), encoding="utf-8").read()
    for marker in (u"'形态、数量'", u"'不拆开'", "'fully bound'", "'stay identical'"):
        assert marker in src, "锁句表少了 %s 这一族的形" % marker


# ─────────────────────────────── 3. 同一句话：中文响、英文也得响（假阴回归）───────
def test_h3r8_light_verb_fires_in_both_languages():
    zh = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          u"[Shot 1] 全息冷光射出，扫过她的脸。 0.0-2.0 秒：她侧身。\n"
          u"overall_soundscape:\n环境音只有风声。\nnon_diegetic_music:\nN/A\n")
    en = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          "[Shot 1] Holographic cold light shoots out and sweeps past her face. "
          "0.0-2.0s: She turns aside.\n"
          "overall_soundscape:\nwind only.\nnon_diegetic_music:\nN/A\n")
    for tag, t in (u"中文", zh), (u"英文", en):
        rows = _shot_rows(t)
        got = [c for c in rows.get("H3R8", []) if c["lvl"] == "warn"]
        assert got, "%s 稿的「光＋会射出去的动词」没报 warn（%s）" % (tag, rows.get("H3R8"))


def test_h3r13_abstract_without_body_part_fires_in_both_languages():
    zh = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          u"[Shot 1] 她站定从容。 0.0-2.0 秒：她抬手格开。\n"
          u"overall_soundscape:\n环境音。\nnon_diegetic_music:\nN/A\n")
    en = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          "[Shot 1] She stands settled and unhurried. 0.0-2.0s: She raises her forearm to block.\n"
          "overall_soundscape:\nroom tone.\nnon_diegetic_music:\nN/A\n")
    for tag, t in (u"中文", zh), (u"英文", en):
        rows = _shot_rows(t)
        assert [c for c in rows.get("H3R13", []) if c["lvl"] == "warn"], \
            "%s 稿的抽象词单独成句没报 warn" % tag


def test_music_leak_fires_in_both_languages():
    zh = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          u"[Shot 1] 背景音乐响起，她转身。 0.0-2.0 秒：她走。\n"
          u"overall_soundscape:\n脚步。\nnon_diegetic_music:\nN/A\n")
    en = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          "[Shot 1] A music bed rises as she turns. 0.0-2.0s: She walks.\n"
          "overall_soundscape:\nfootsteps.\nnon_diegetic_music:\nN/A\n")
    for tag, t in (u"中文", zh), (u"英文", en):
        rows = _shot_rows(t)
        assert [c for c in rows.get("H3R9/§七", []) if c["name"] == u"泄漏"], \
            "%s 稿正文里的音乐没报泄漏" % tag


def test_h3r14_bottom_line_ok_in_english():
    """底线句的英文形（`the fist never touching her face or skin`）要被认成"已写底线"。"""
    en = (PF.SKELETON_INSTRUCTION + "\nintegrated_multimodal_description:\n"
          "[Shot 1] 0.0-2.0s: His fist swings at her face, the fist never touching her face or skin. "
          "2.0-4.0s: She steps back.\n"
          "overall_soundscape:\nroom tone.\nnon_diegetic_music:\nN/A\n")
    rows = _shot_rows(en)
    got = rows.get("H3R14", [])
    assert got and got[0]["lvl"] == "ok", got


def test_prop_state_lock_not_ground_touch():
    """道具状态句 `never touches the ground` **不算**接触底线——否则闸开口说"合规"（假阳的 ok 最坏）。"""
    assert PF.match_terms("it is never shaken loose and never touches the ground",
                          HG.底线_MARK) == [], "把道具不落地当成了『拳没打中脸』的底线句"
    assert PF.match_terms("the fist never once touches her face or skin", HG.底线_MARK), \
        "真底线句的英文形没被认出来"


# ─────────────────────────────── 4. 假阳回归（已验收稿不许被报）───────────────────
@pytest.mark.parametrize("sentence", [
    "Both figures hold the standoff and the framing settles for a moment.",
    "She stands in a standoff with a tall heavy-armoured mech.",
    "The heavy-armed man struggles to get up.",
    "The grappling standoff of the previous shot is not replayed.",
])
def test_r20_does_not_call_standing_around_a_tug_of_war(sentence):
    assert PF.match_terms(sentence, HG.TUG) == [], "对峙/挣扎起身被算成双向拉扯＝error 假报"


@pytest.mark.parametrize("sentence", [
    "He drags her toward him with the chain.",
    "She hauls back on the rope with both arms.",
    "He leans his weight back until the coils stop him.",
])
def test_r20_still_calls_the_real_tug(sentence):
    assert PF.match_terms(sentence, HG.TUG), "真反例被撤词撤掉了——R20 从此看不见拔河"


def test_r13_momentum_is_physics_not_posture():
    """`tracking the sideways momentum of the staff-block` 是运镜跟随动量，不是「气势」标签。"""
    assert PF.match_terms("tracking the sideways momentum of the staff-block and the jab",
                          HG.ABSTRACT) == []


def test_live_corpus_has_no_invented_errors():
    """**错误级**判据的两条硬性质（改前实测 7 条 error 全是假报，故必须钉住）：
    ① 不许由被撤掉的宽词（standoff／裸 struggle）触发——那正是假报的来源；
    ② 英文侧报 error 的每一份稿子，它的**改前中文对照稿**在同一套判据下也报 error。
       口径：判据的松紧以**人审标定过的那一侧**（中文）为准，英文侧只许"同样看见"，
       不许凭空多报，也不许一撤了之反而少报（少报记在方案里，不在测试里钉死条数）。"""
    inv = re.compile(r"standoff|struggles to get up|hold the standoff", re.I)
    bad = []
    for name, text in LIVE:
        for rid, chks in _shot_rows(text).items():
            for c in chks:
                if c["lvl"] == "error" and inv.search(c["msg"]):
                    bad.append("%s %s:%s" % (name[:18], rid, c["msg"][:60]))
    assert not bad, bad
    # 改前中文对照稿（批 15 备份）里同一份是否也报 error——备份不在场就跳过这一腿
    missing = []
    for name, text in LIVE:
        old = _backup_text(name)
        if old is None:
            missing.append(name[:18])
            continue
        if not _live_corpus_has(old, "error"):
            # 只有当英文侧这条不是真反例词（drag/haul/lean weight back/test of strength）时才追
            if _only_loose_errors(text):
                missing.append("英文侧凭空多报：%s" % name[:18])
    assert not [m for m in missing if m.startswith(u"英文侧")], missing


def _backup_text(name):
    for f in json.load(io.open(MF, encoding="utf-8"))["files"]:
        if os.path.basename(f["path"]) == name:
            b = os.path.join(BK, os.path.basename(os.path.dirname(f["path"])) + u"__" + name)
            return io.open(b, encoding="utf-8").read() if os.path.isfile(b) else None
    return None


def _live_corpus_has(text, lvl):
    return any(c["lvl"] == lvl for chks in _shot_rows(text).values() for c in chks)


def _only_loose_errors(text):
    """英文侧的 error 是否**只**由真较力词触发（是⇒返回 False，不算凭空多报）。"""
    real = re.compile(r"drag|haul|lean\w*\s+(?:his|her)\s+weight|test of strength|"
                      u"拉扯|僵持|角力|拉锯|拔河|往回拉", re.I)
    errs = [c["msg"] for chks in _shot_rows(text).values() for c in chks if c["lvl"] == "error"]
    return bool(errs) and not all(real.search(m) for m in errs)


def test_live_corpus_props_lock_no_longer_warns():
    """道具锁：12 份英译真源曾被假报 warn（锁句都在，只是闸只认中文形）。"""
    bad = []
    for name, text in LIVE:
        for c in _shot_rows(text).get("H3R1", []):
            if c["lvl"] == "warn":
                bad.append(name[:20])
    assert not bad, bad


def test_beats_visible_on_english_bodies():
    """底座时间戳单位认 `s`：**正文里写了区间**的稿子，节拍数不许是 0
       （0＝步数/收势/容量/时长四条规则一起判不了）。
       没写区间的稿子（K 系列单拍稿）本来就没拍可数，不算失明——别把"没有"读成"看不见"。"""
    rng = re.compile(r"\d+\.\d+\s*[–-]\s*\d+\.\d+\s*(?:秒|s(?![A-Za-z]))")
    blind = []
    for name, text in LIVE:
        body = PF.regions(text)["body"]
        if rng.search(body) and not PF.beats(text):
            blind.append(name[:22])
    assert not blind, "这些稿子正文里有时间戳区间却读不到节拍：%s" % blind


# ─────────────────────────────── 5. 词表闸：英文否定句不再算"高危点名" ────────────
# 说明：图片链那十张**毒词表**（SKIN/ARMOR/WEAPON/MAKEUP/DOLL/COLOR/STRUCT/DELEGATE/
# DECOR/RENDER）按通道分治保持中文原样——它们是四份人审标定文件（dz0b2 那批）标出来的，
# 换语言用同一条判据没有实证。所以这里测的是**句位判定这台机器**，
# 词表用调用方自备（真实表里本就是英文的条目，如 guoman 档的 cinematic）。
_VOC = ['cinematic', 'photorealistic']


def test_lint_english_ban_line_is_low_risk():
    txt = "Soft 35mm film look. Do not use any cinematic grading or photorealistic skin."
    hits = PL.find_terms(txt, _VOC)
    assert hits, "词形没命中，用例本身失效"
    assert all(neg for _w, neg in hits), hits          # 全落在禁令句 ⇒ 低危，不算点名


def test_lint_english_positive_callout_still_high_risk():
    """否定认全了，肯定句点名必须照样响——否则就是反向失明。"""
    txt = "A cinematic grade with photorealistic skin and a graded colour palette."
    hits = PL.find_terms(txt, _VOC)
    assert hits and all(not neg for _w, neg in hits), hits


def test_lint_neg_english_leads_are_in_the_single_source():
    """`check_preflight` 与 `prompt_lint` 共用一份 NEG：英文引导词缺一条＝两张表又分家了。"""
    from check_preflight import BAN_LEADS_EN
    for lead in ('do not', 'does not', 'never ', 'no ', 'not ', 'without'):
        assert lead in PL.NEG, "NEG 缺英文引导词 %r" % lead
        assert lead in BAN_LEADS_EN, "G7 侧缺 %r" % lead


def test_lint_sentence_boundary_covers_ascii():
    """上一句的"Do not"管不到下一句的毒词（英文句末 `. ` 必须算边界）。"""
    txt = "Do not use any cinematic grade. The frame carries a cinematic look over the wet ground."
    kinds = [neg for _w, neg in PL.find_terms(txt, ['cinematic'])]
    assert False in kinds, "第二句里的 cinematic 被上一句的 Do not 洗白了：%s" % kinds


def test_lint_still_uses_the_shared_matcher():
    """词表闸没绕过底座自己匹配：`highlight` 里的 light、`noting` 里的 not 都不算命中。"""
    assert PL.find_terms("a highlighted edge", ['light']) == []
    assert PL.find_terms("the crew is well staffed", ['staff']) == []
