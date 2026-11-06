# -*- coding: utf-8 -*-
"""W5c／B1 裁定的新版 G6 帧数判据（10-23）：官方 4–15s 为准 ⇒ 放行 107–345。

107–123 官方允许但低于本机节点声明的训练下限 ⇒ **放行＋warn**（不以未实测禁选，
也不假装它在训练区间内）；106／346／旧 362 一律拒。
"""
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE.parent / "tools"))

from check_preflight import run_checks, H3_MIN_FRAMES, H3_MAX_FRAMES, H3_LOCAL_TRAINED_MIN  # noqa: E402


def _rep(length):
    return run_checks({"prompt": "x", "refs": [], "length": length, "duration": None,
                       "provider": "local", "only": ["G6"],
                       "output_root": str(Path(pytest.__file__).parent),
                       "project": "无音", "project_aliases": {"无音": ["无音"]}})


def test_bounds_are_b1_official_first():
    assert (H3_MIN_FRAMES, H3_MAX_FRAMES, H3_LOCAL_TRAINED_MIN) == (107, 345, 124)


@pytest.mark.parametrize("length", [107, 124, 192, 243, 345])
def test_approved_grid_points_pass(length):
    rep = _rep(length)
    assert not any(g == "G6" for _lv, g, _m in rep.errors), rep.render()


@pytest.mark.parametrize("length", [106, 346, 362, 0])
def test_out_of_range_rejected(length):
    rep = _rep(length)
    assert any(g == "G6" for _lv, g, _m in rep.errors), rep.render()


def test_362_is_rejected_with_named_reason():
    rep = _rep(362)
    msg = " ".join(m for _lv, g, m in rep.errors if g == "G6")
    assert "362" in msg and ("15.08" in msg or "超官方 15s" in msg), msg
    assert "96–360" in msg, "362 的拒批理由要挂在官方硬界上，不是挂在本网格上"


def test_low_range_warns_but_does_not_block():
    rep = _rep(107)
    warns = [m for lv, g, m in rep.items if lv == "warn" and g == "G6"]
    assert warns and "训练下限" in warns[0], rep.render()
    rep2 = _rep(124)
    assert not [m for lv, g, m in rep2.items if lv == "warn" and g == "G6"
                and "训练下限" in m], rep2.render()
