# -*- coding: utf-8 -*-
"""阈值注册表与第五件校验器的回归（2026-10-03 批 7-2）。

这件东西存在的理由：10-02 硬检查查出**阈值散在 5 处**、代码与注释/记忆已经不一致过
（crf16 vs crf18、−16 目标 vs −17 实测）。散着的数没有"谁说了算"。
所以测试要钉的不是"有个文件"，而是三件能证伪的事：
  ① 注册表里每一处读法都**真取到值**（取不到＝指针死了，必须红，不许当成"没有阈值"）；
  ② authority 与 mirror 相等（不等必须报出来，这是我植入门槛验证过的分支）；
  ③ 表里**不许出现值**（写了值就是第二份抄本，本项目的老病）。
"""
import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # engine/
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent / "tools"))

import check_thresholds as CT                          # noqa: E402

REG_PATH = ROOT / "thresholds_registry.json"


def _reg():
    return json.loads(io.open(REG_PATH, encoding="utf-8").read())


def test_registry_exists_and_is_not_empty():
    d = _reg()
    assert d.get("thresholds"), "注册表空的 ⇒ 这条测试就什么都没查"
    assert d.get("_readme"), "没有说明的注册表，下一个人不知道该填什么"


def test_every_declared_file_exists():
    """注册表指的文件必须在盘上——它自己就是一份"指针清单"，死指针等于假覆盖。"""
    missing = []
    for th in _reg()["thresholds"]:
        for pl in th.get("places") or []:
            f = str(pl.get("file") or "").replace("/", os.sep)
            if not os.path.isfile(f):
                missing.append("%s → %s" % (th["id"], f))
    assert not missing, "注册表指着不存在的文件：\n" + "\n".join(missing)


def test_every_place_actually_reads_a_value():
    """每一处都真读得到数。读不到＝读法过期或文件搬走，不能默默算过。"""
    cache = {}
    bad = []
    for th in _reg()["thresholds"]:
        for pl in th.get("places") or []:
            v, why = CT.read_value(pl, cache)
            if v is None:
                bad.append("%s/%s：%s" % (th["id"], pl.get("role"), why))
    assert not bad, "这些读法取不到值：\n" + "\n".join(bad)


def test_no_conflicts_among_authority_and_mirrors():
    errs, warns, _i, data = CT.check(_reg())
    assert not [e for e in errs if "[不一致]" in e], "\n".join(errs)
    assert data["counts"]["unreadable"] == 0, "\n".join(errs)
    # 顺手钉住"确实有东西在被查"——空表会让上面两条都假绿
    assert data["counts"]["thresholds"] >= 10


def test_conflict_is_detected_when_mirrors_diverge(tmp_path):
    """反向验证：把 mirror 改成另一个数，校验器必须红——不然这件工具是摆设。"""
    reg = {"thresholds": [{
        "id": "planted", "含义": "测试", "scope": "通用", "unit": "x", "enforced": True,
        "places": [
            {"role": "authority", "kind": "py_const",
             "file": str(ROOT.parent / "tools" / "check_preflight.py"), "name": "H3_FPS"},
            {"role": "mirror", "kind": "regex", "file": str(ROOT / "tasks.py"),
             "pattern": "expected_fps\\)\\) > ([0-9.]+)", "group": 1}]}]}
    errs, _w, _i, data = CT.check(reg)
    assert any("[不一致]" in e for e in errs), errs
    assert data["counts"]["conflicts"] == 1


def test_unreadable_place_is_an_error_not_a_pass():
    """反向验证 2：读法写错（文件在、名字不存在）必须报 error，不许"读不到就跳过"。"""
    reg = {"thresholds": [{
        "id": "planted2", "含义": "测试", "scope": "通用", "unit": "x", "enforced": True,
        "places": [{"role": "authority", "kind": "py_const",
                    "file": str(ROOT.parent / "tools" / "check_preflight.py"),
                    "name": "NO_SUCH_CONSTANT_XYZ"}]}]}
    errs, _w, _i, data = CT.check(reg)
    assert any("[阈值读不到]" in e for e in errs), errs
    assert data["counts"]["unreadable"] == 1


def test_registry_holds_no_values_of_its_own():
    """表里不许抄值：值只准从 places 的读法现取。

    这条防的是我自己——最省事的写法就是顺手在表里写个 `value: 24`，
    那样代码改了表不会改，第五件校验器立刻变成第二份漂移真源。
    """
    banned = ("value", "expected", "actual", "number", "值", "现值", "阈值")
    bad = []
    for th in _reg()["thresholds"]:
        for k in th:
            if k == "含义":
                continue
            if any(b in str(k).lower() for b in banned):
                bad.append("%s.%s" % (th.get("id"), k))
        for pl in th.get("places") or []:
            for k in pl:
                if k in ("value", "expect", "expected"):
                    bad.append("%s.%s" % (th.get("id"), k))
    assert not bad, "注册表里出现取值类字段（等于又造一份抄本）：%s" % "、".join(bad)


def test_unenforced_entries_are_declared_as_such():
    """"挂着没生效"的东西必须显式标 enforced=false，不许靠人记得。

    10-03 批 7-4 之后剩两件：音频上限从未校验、绝对带按裁定不接。
    ⚠ `qc_batch_dino_floor` **原来在这张单上**（"还没接线"），接线后必须**同时**：
      · 从"未生效"里出去（否则这条测试会红着提醒人去修一件已经修好的事＝假阳），
      · 并且被下面那条正向断言钉住（否则有人把它悄悄改回 enforced=false 也没人知道＝假阴）。
    """
    un = {t["id"] for t in _reg()["thresholds"] if t.get("enforced") is False}
    assert {"ark_limit_audios", "qc_absolute_bands_faceWhite"} <= un, un
    assert "qc_batch_dino_floor" not in un, "相对尺已接进引擎，enforced 不该再是 false"


def test_the_wired_ruler_is_enforced_and_lives_outside_tmp():
    """接了线的那把尺：enforced=true ＋ 权威文件在 `tools/` 不在 `tmp/` ＋ 有对账用的原稿镜像。

    为什么单独一条：10-02 之前"标定过的主尺"权威指针写在 `tmp/wzy/qc.py`——**tmp 不是落点**，
    清一次盘阈值就查不到（读不到＝这条注册表项静默失效，比写错更坏）。
    """
    th = {t["id"]: t for t in _reg()["thresholds"]}
    for tid in ("qc_batch_dino_floor", "qc_batch_dino_mean_warn"):
        assert tid in th, "缺阈值登记项 %s（接线之后必须登记，不然是「有数没账」）" % tid
        e = th[tid]
        assert e.get("enforced") is True, "%s 没标 enforced=true" % tid
        auth = [p for p in e["places"] if p.get("role") == "authority"]
        assert len(auth) == 1, "%s 的 authority 应唯一，现 %d 个" % (tid, len(auth))
        f = str(auth[0].get("file") or "").replace("/", os.sep)
        assert "qc_batch_consistency.py" == os.path.basename(f), f
        assert os.sep + "tmp" + os.sep not in f.lower(), "权威指针又指回 tmp 了：%s" % f
        assert os.path.isfile(f), "权威文件不在盘上：%s" % f
        # 标定原稿留着当对账镜像（不是第二权威）；两边数值不等 check_thresholds 会报 error
        assert any(p.get("role") == "reference_only" for p in e["places"]), \
            "%s 丢了与标定原稿的对账镜像" % tid


def test_the_known_doc_code_mismatch_is_recorded():
    """crf16/44100（记忆）vs crf18/48000（代码）这条不一致是**查出来的事实**，
       不许被忘：它要么进 known_mismatches 登记，要么被真修掉。"""
    km = _reg().get("known_mismatches") or []
    assert any("crf" in json.dumps(k, ensure_ascii=False) for k in km), \
        "这条不一致被删掉了却没解决——最坏的处理方式"
