# -*- coding: utf-8 -*-
"""通道未裁的守门用例（批1 项5／GAP-C2·C3）。

钉两件事，缺一不可：
  A. 「非空且不认识的通道词」绝不能再被悄悄判成 h3 —— 那是原无条件兜底的病，
     实测中招的是千问三个 kind 词、即梦的 jimeng／dreamina 两个。
  B. 合法泛称 `video`／空 的行为**一字不许变** —— 它不是假装，是文档明写的
     "只定通道不定格式"，而且 C57 回归与"图片流忘声明要 fail loud"两条现役用例都依赖它。
"""
import sys

import pytest

sys.path.insert(0, r"D:\AIWorkflow\tools")

from check_preflight import (CHANNEL_UNADJUDICATED, Report, channel_of,  # noqa: E402
                             g7_prompt_format)

TEN = ("【生成目标】一段视频\n【主体与关系】甲与乙\n【场景与环境】夜，荒原\n"
       "【事件脚本】甲向前走了三步，停下。\n【保持一致】同一身甲胄\n【镜头】固定机位\n"
       "【声音】风声\n【风格与光影】冷色\n【武君仪外貌锁定】无\n【Motion】慢")


# ── A. 未裁：绝不再被当成 h3 ────────────────────────────────────────────
@pytest.mark.parametrize("kind, want", [
    ("h3", "h3"), ("h3_i2va", "h3"), ("h3_ref2va", "h3"), ("h3_skeleton", "h3"),
    ("ref2va", "h3"), ("i2va", "h3"), ("fl2va", "h3"),
    ("image", "image"), ("img", "image"), ("picture", "image"),
    ("first_frame", "image"), ("t2i", "image"), ("i2i", "image"),
    ("cloud", "cloud"), ("sd", "cloud"), ("seedance", "cloud"),
    ("ark", "cloud"), ("kling", "cloud"), ("vidu", "cloud"), ("hailuo", "cloud"),
])
def test_named_channel_words_still_resolve(kind, want):
    """已登记的 20 个具名 kind 逐个给真通道，不许顺手也判成未裁。
    （这张表是从 channel_of 的三个元组抄的 —— 它只列 kind，不含 qianwen／jimeng
      那些"注册表声明了但 channel_of 不认识"的词，那类见下面 A 段。）"""
    assert channel_of(kind, "local") == want, kind


@pytest.mark.parametrize("kind", [
    "qianwen", "qwen", "bailian", "jimeng", "dreamina",
    "h3_i2v", "h3_i2va_", "H3-I2VA", "sdxl", "flux", "", "  ",
])
def test_unlisted_words_are_not_silently_h3(kind):
    """没登记过的词 ⇒ 未裁。

    ⚠ 故意把打错字的形态也列进来（`h3_i2v`、`h3_i2va_`）：原兜底会把它们当成 h3，
    于是"yaml 里 prompt_kind 少打一个 a"这种失误的表现是**审错了还显示 ✓**，
    比直接报错更难查。
    大小写／空白由 channel_of 自己归一（它先 strip().lower()），所以 `H3-I2VA` 属未裁而不是未登记。
    """
    if kind.strip() == "":
        assert channel_of(kind, "local") == "h3", "空串属合法泛称，见 test_generic_video_*"
        return
    assert channel_of(kind, "local") == CHANNEL_UNADJUDICATED, kind
    assert channel_of(kind, "ark") == CHANNEL_UNADJUDICATED, (kind, "provider 也不该替它定")


# ── B. 合法泛称：行为一字不许变 ──────────────────────────────────────────
@pytest.mark.parametrize("kind", ["video", "", None])
def test_generic_video_still_resolves_by_provider(kind):
    """`video`／空 是文档明写的泛称：由 provider 定 h3/cloud，**保留**原行为。"""
    assert channel_of(kind, "local") == "h3"
    assert channel_of(kind, "ark") == "cloud"
    assert channel_of(kind, "cloud") == "cloud"


def test_c57_six_segment_still_not_blocked():
    """C57 本体：六段稿无论声不声明 kind 都不该被骨架判据假拦。
    泛称那条路必须仍然通，否则这次改动就把 ref2va 通道又拦死一遍。"""
    for kind in ("video", "h3_ref2va"):
        rep = Report()
        g7_prompt_format(rep, TEN.replace("【生成目标】一段视频",
                         "【生成目标】一段视频\n[Shot 1]\nduration: 5.2\n"
                         "reference_to_video: enabled\naudio: native"),
                         None, "local", kind=kind)
        errs = [t for _, _, t in rep.items if _ == "error"]
        assert not any("首帧" in e or "指令" in e for e in errs), (kind, errs)


# ── C. 未裁时的行为：不跑判据、不打 ✓、也不 error（不替 D7 做主）──────────
def test_unadjudicated_emits_warn_not_ok_and_not_error():
    rep = Report()
    g7_prompt_format(rep, TEN, None, "local", kind="qianwen")
    levels = [lv for lv, _, _ in rep.items]
    assert "ok" not in levels, f"未裁绝不能打 ✓（那等于替它背书）：{levels}"
    assert not rep.errors, f"未裁不该 error 拦停（那等于把『未裁』悄悄裁成『不许走』，越 D7 的权）：" \
                           f"{[t for _, _, t in rep.errors]}"
    assert rep.warns, "必须至少留一条 warn 作为人工放行的痕迹"
    text = " ".join(t for _, _, t in rep.warns)
    for must in ("通道未裁", "未执行", "人工关口"):
        assert must in text, (must, text[:200])


def test_unadjudicated_does_not_run_any_format_judgement():
    """未裁时连"混用"这种跨通道判据也不跑 —— 因为不知道跟谁比。
    拿一份铁定会触发混用的稿（中文十块）验证：只应有那一条未裁 warn，不该冒出混用 error。"""
    rep = Report()
    g7_prompt_format(rep, TEN, None, "local", kind="jimeng")
    assert not rep.errors, [t for _, _, t in rep.errors]
    assert len(rep.warns) == 1, rep.warns


def test_explicit_channel_still_overrides():
    """CLI 的 --channel 显式指定时，绕过未裁逻辑（它本来就是"人工替机器定"的口子）。"""
    rep = Report()
    g7_prompt_format(rep, TEN, None, "local", kind="qianwen", channel="cloud")
    assert any("通道＝cloud" in t for _, _, t in rep.items), rep.items
