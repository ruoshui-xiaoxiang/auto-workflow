# -*- coding: utf-8 -*-
"""正文语言闸（10-03 批 14 建，用户裁「要建闸」）。

判据来自官方三处硬性（`ref-en.txt:5`、`ref-en.txt:217`、`SKILL.md:33`）：
**重写段落用英文**，保留原语言的只有 `<d>` 内台词／歌词、画面可见文字、官方点名的引用原文。
这组测试锁三件事：① 真拦得住（不是永远绿的摆设）；② 三处豁免不误伤；
③ **只管 H3 通道**——云端十块／图片链的中文正文不在这条射程内（通道分治）。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent            # engine/
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent / "tools"))
sys.path.insert(2, str(ROOT.parent / "tmp" / "wzy"))

from check_preflight import run_checks                    # noqa: E402
import prompt_format as PF                                # noqa: E402


def g7(spec):
    s = dict(spec)
    s.setdefault("only", ["G7"])
    s.setdefault("refs", ["a.png"])
    s.setdefault("characters", "none")
    rep = run_checks(s)
    return ([t for lv, g, t in rep.items if g == "G7" and lv == "error"],
            [t for lv, g, t in rep.items if g == "G7" and lv == "warn"])


SKEL_EN = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
    "integrated_multimodal_description: [Shot 1] Live-action, cinematic, a woman in a rain-soaked "
    'coat stands by a neon sign reading "\u8425\u4e1a\u4e2d" and says '
    "<d>[\u4e2d\u6587] \u7ad9\u4f4f\u3002</d> The camera pushes in with small amplitude at slow speed.\n\n"
    "overall_soundscape: Rain hits the pavement and traffic hums in the distance.\n\n"
    "non_diegetic_music: N/A")


def test_english_body_with_chinese_dialogue_passes():
    """正样本：正文全英文，台词进 `<d>`、画面可见文字进双引号 ⇒ 一条都不该报。"""
    err, warn = g7({"prompt": SKEL_EN, "prompt_kind": "h3_i2va", "provider": "local"})
    assert not [t for t in err if "\u975e\u82f1\u6587" in t], err
    assert PF.non_english_spans(SKEL_EN) == [], PF.non_english_spans(SKEL_EN)


def test_chinese_body_is_blocked():
    """反向验证：把正文一个短语换成中文，必须当场被 error 拦下。"""
    bad = SKEL_EN.replace("a woman in a rain-soaked coat stands", u"一个穿湿外套的女人站在")
    err, _ = g7({"prompt": bad, "prompt_kind": "h3_i2va", "provider": "local"})
    assert any(u"非英文字符" in t for t in err), err


def test_chinese_in_soundscape_is_also_blocked():
    """`overall_soundscape` 也是重写段落（官方 §4 三条共用），中文一样拦。"""
    bad = SKEL_EN.replace("Rain hits the pavement", u"雨打在路面上")
    err, _ = g7({"prompt": bad, "prompt_kind": "h3_i2va", "provider": "local"})
    assert any(u"非英文字符" in t for t in err), err


def test_ref2va_branch_is_covered_too():
    """六段分支同样接了这条：只在骨架接＝换个模式就漏。"""
    six = SKEL_EN.split("\n\n", 1)[1]
    six = ("subject_definitions:\n<Subject 1> is the rain-soaked street in <Picture 1>.\n\n"
           "summary:\n[reference generation] The target video shows <Subject 1> with a woman.\n\n"
           "retention_analysis:\n<Subject 1>: fully_preserved - the wet pavement is retained.\n\n"
           "detailed_description:\n" + six.replace(
               "For the target video", "") + "\n\n"
           "overall_soundscape:\nRain hits the pavement.\n\nnon_diegetic_music:\nN/A\n")
    err, _ = g7({"prompt": six, "prompt_kind": "h3_ref2va", "provider": "local"})
    assert not [t for t in err if u"非英文" in t], err
    zh = six.replace("a woman", u"一个女人")
    err2, _ = g7({"prompt": zh, "prompt_kind": "h3_ref2va", "provider": "local"})
    assert any(u"非英文字符" in t for t in err2), err2


def test_cloud_and_image_channels_are_not_touched():
    """通道分治：云端中文十块／图片链中文提示词**不吃这条**（官方规定只属 H3 骨架与六段）。"""
    ten = (u"\u3010\u751f\u6210\u76ee\u6807\u3011\u4e00\u6761 5 \u79d2\u955c"
           u"\u3010\u4e3b\u4f53\u4e0e\u5173\u7cfb\u3011\u5973\u4eba\u7ad9\u5728\u8857\u4e0a"
           u"\u3010\u4e8b\u4ef6\u811a\u672c\u30110.0-5.0 \u79d2\uff1a\u5979\u56de\u5934"
           u"\u3010\u4fdd\u6301\u4e00\u81f4\u3011\u670d\u88c5\u4e0d\u53d8"
           u"\u3010\u955c\u5934\u3011\u4e2d\u666f\uff0c\u7f13\u7f13\u524d\u63a8"
           u"\u3010\u58f0\u97f3\u3011\u96e8\u58f0")
    err, _ = g7({"prompt": ten, "prompt_kind": "seedance", "provider": "ark"})
    assert not [t for t in err if u"非英文" in t], err
    img = u"21\u5c81\u5973\u5b50\uff0c\u6e05\u51b7\u9aa8\u76f8\uff0c\u5199\u5b9e3D CG"
    err2, _ = g7({"prompt": img, "prompt_kind": "image", "provider": "local"})
    assert not [t for t in err2 if u"非英文" in t], err2


def test_the_official_requirement_is_still_on_disk():
    """闸判的是官方原文；官方哪天改口，这条测试要当场红，而不是让闸继续拦。"""
    import io as _io
    off = Path(r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3")
    ref = _io.open(off / "ref-en.txt", encoding="utf-8", errors="replace").read()
    sk = _io.open(off / "SKILL.md", encoding="utf-8", errors="replace").read()
    assert "Write all six rewrite sections in English" in ref, "官方 §1 那句不在了⇒ 判据要重读"
    assert "Write the body in English" in ref, "官方 §5.1 那句不在了⇒ 判据要重读"
    assert "Write rewrite sections in English" in sk, "官方 SKILL 那句不在了⇒ 判据要重读"


def test_live_selftest_fixture_is_official_form():
    """自测夹具本身必须过闸——夹具过不了，说明现役路径一跑就红。"""
    p = Path(r"D:\AIWorkflow\tmp\selftest_prompt.txt")
    assert p.is_file(), p
    assert PF.non_english_spans(p.read_text(encoding="utf-8")) == [], \
        PF.non_english_spans(p.read_text(encoding="utf-8"))[:3]


@pytest.mark.parametrize("frag", [u"\u9ad8\u7cbe\u5ea6", u"\u5973\u4eba", u"\u96e8"])
def test_detector_catches_each_shape(frag):
    """尺子本身的三类形态：正文／带空格的短语／单词块都算一处。"""
    body = "integrated_multimodal_description: [Shot 1] %s stands there.\n" % frag
    got = PF.non_english_spans(body)
    assert got and frag in got[0][1], (frag, got)

def test_default_subset_covers_it_even_when_yaml_lists_only_a_few():
    """一键成片流的 `gate` 步骤只列 G11/G13，但每镜走 t_video ⇒ preflight 默认子集里就有 G7。

    这条锁的是**可达性**：判据写在文件里、流却调不到＝等于没有（09-14 那 10 个裁判件的教训）。
    """
    bad = SKEL_EN.replace("a woman in a rain-soaked coat stands", u"一个穿湿外套的女人站在")
    rep = run_checks({"prompt": bad, "refs": ["a.png"], "prompt_kind": "h3_i2va",
                      "provider": "local", "characters": "none"})   # **不传 only**＝引擎默认子集
    assert any(g == "G7" and lv == "error" and u"非英文字符" in t
               for lv, g, t in rep.items), rep.items[:6]

