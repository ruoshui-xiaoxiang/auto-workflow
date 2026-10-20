# -*- coding: utf-8 -*-
"""G7 四模式（I2VA/FL2VA/L2VA/T2VA）回归 —— 2026-10-21 官方对齐修复。

背景：G7 此前只认 I2VA 首行并禁止 <Picture 2>，导致官方 FL2VA 稿被误拦、
真首尾帧链只能写 I2VA 口径（方案 §十三第 47/48 条，待裁-12）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from check_preflight import Report, g7_prompt_format  # noqa: E402

I2VA_HEAD = ("For the target video, at 0.00 seconds into the target video, "
             "<Picture 1> (from [Shot 1]) is fully referenced.")
FL2VA_HEAD = ("How the reference pictures align with the target video — "
              "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
              "Picture 2 (from Shot 1) aligns with the 5.17-second mark of the target video.")
L2VA_HEAD = ("How the reference pictures align with the target video — "
             "<Picture 1> (from [Shot 1]) aligns with the 5.17-second mark of the target video.")

BODY = (
    "\n\nintegrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot of a "
    "woman in a dark coat in a rain-soaked alley. She turns her head as the light shifts, then "
    "steps back into shadow. The camera pushes in with small amplitude at slow speed.\n\n"
    "overall_soundscape: Rain taps on metal awnings while distant traffic hums.\n\n"
    "non_diegetic_music: N/A"
)


def run(prompt, kind="h3_i2va"):
    rep = Report()
    g7_prompt_format(rep, prompt, None, "local", kind=kind)
    return rep


def test_fl2va_official_head_is_accepted():
    rep = run(FL2VA_HEAD + "\n" + BODY + "\n\nThe last pose settles into Picture 2.", "h3_fl2va")
    assert not rep.errors, rep.render()


def test_fl2va_accepted_with_generic_kind():
    """泛称 kind 时按内容识别；具体 kind 必须与首行一致（见下一条）。"""
    rep = run(FL2VA_HEAD + "\n" + BODY + "\n\nThe last pose settles into Picture 2.", "h3")
    assert not rep.errors, rep.render()


def test_fl2va_with_i2va_kind_is_rejected():
    rep = run(FL2VA_HEAD + "\n" + BODY + "\n\nThe last pose settles into Picture 2.", "h3_i2va")
    assert rep.errors, rep.render()


def test_fl2va_without_picture2_warns():
    rep = run(FL2VA_HEAD + "\n" + BODY, "h3_fl2va")
    assert not rep.errors, rep.render()
    assert any("Picture 2" in w[2] or "末帧" in w[2] for w in rep.warns), rep.render()


def test_fl2va_rejects_picture3():
    rep = run(FL2VA_HEAD + "\n" + BODY + "\n<Picture 3> is not a frame.", "h3_fl2va")
    assert rep.errors, rep.render()


def test_i2va_still_rejects_picture2():
    rep = run(I2VA_HEAD + "\n" + BODY + "\nThe last pose settles into <Picture 2>.", "h3_i2va")
    assert rep.errors, rep.render()


def test_l2va_head_is_accepted():
    rep = run(L2VA_HEAD + "\n" + BODY, "h3_l2va")
    assert not rep.errors, rep.render()


def test_t2va_has_no_first_line():
    body = BODY.lstrip("\n")
    rep = run(body, "h3_t2va")
    assert not rep.errors, rep.render()
    rep2 = run("<Picture 1> is here.\n\n" + body, "h3_t2va")
    assert rep2.errors, rep2.render()


def test_chinese_body_still_errors():
    zh = I2VA_HEAD + "\n\nintegrated_multimodal_description: [Shot 1] 电影感，中景，雨夜巷子。" \
         "\n\noverall_soundscape: 雨声。\n\nnon_diegetic_music: N/A"
    rep = run(zh, "h3_i2va")
    assert rep.errors, rep.render()


def test_missing_first_line_errors():
    rep = run("Some prose without a first line.\n\n" + BODY.lstrip("\n"), "h3_i2va")
    assert rep.errors, rep.render()
