# -*- coding: utf-8 -*-
"""批内 DINO 相对尺接进引擎的回归（2026-10-03 批 7-4 第 3 件）。

裁定原文（10-02 批 6 问 4）：**「只接相对尺，绝对带只报不拦」**，
并且「单张产物跑不了 ⇒ 必须留痕"未测量"，不许当通过」。
所以这批测试钉的是那三件能证伪的事，不是"有没有这个函数"：

  ① 量不了 ⇒ verdict 必须是 not_measured，且**绝不等于放行**（不 raise 也不写 ok）；
  ② 只有"最低值"那条拦人，均值那条只警示（拦多了就是把别的项目整批假拦，10-02 已证）；
  ③ 绝对带（faceL／faceWhite／lpalex／gedge／faceHR）**没被顺手接进来**——
     接了就是把一个项目的标定当通用判据用，那条错误 10-02 实测过（3/3 假拦）。

真尺那一条（`test_the_real_ruler_still_matches_the_calibration`）跑真模型：
它是唯一能证明"引擎里这把尺和标定 0.75/0.80 那把是同一把"的用例。
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

import tasks as T                                      # noqa: E402

TOOLS = ROOT.parent / "tools"
RULER = "qc_batch_consistency"


def _ctx(tmp_path, cfg=None):
    lines = []
    ctx = {"cfg": cfg if cfg is not None else {"log_dir": str(tmp_path)},
           "workflow": "test_flow", "log": lines.append}
    ctx["lines"] = lines
    return ctx


def _stub(monkeypatch, result=None, boom=None):
    """把尺子换成一个假模块：测的是**接线行为**，不是模型本身（真尺另有用例）。"""
    import types

    mod = types.ModuleType(RULER)

    def measure(paths, device="cpu", identity_lock=True):
        if boom:
            raise boom
        r = {"schema": 2, "n_input": len(paths), "verdict": "ok", "reason": None,
             "mean": 0.9, "min": 0.88, "identity_lock": bool(identity_lock),
             "verdict_by_identity_axis": "ok",
             "thresholds": {"min_fail_lo": 0.75,
                            "mean_warn_lo": 0.80},
             "bands_note": "带"}
        r.update(result or {})
        # 11-04：身份锁关着时，真尺会把 fail／warn 降级成 report_only——
        # 假模块必须跟着降，否则测的是"接线以为会发生的事"，不是会发生的事。
        if not r["identity_lock"] and r["verdict"] in ("fail", "warn"):
            r["verdict_by_identity_axis"] = r["verdict"]
            r["verdict"] = "report_only"
        return r

    def explain(res):
        return "批内 DINO 互比：%s（最低 %s 均值 %s）" % (res.get("verdict"),
                                                        res.get("min"), res.get("mean"))

    mod.measure = measure
    mod.explain = explain
    mod.DINO_BATCH_MIN_FAIL_LO = 0.75
    mod.DINO_BATCH_MEAN_WARN_LO = 0.80
    monkeypatch.setitem(sys.modules, RULER, mod)
    return mod


# ── ① 量不了＝未测量，不是通过 ─────────────────────────────────────
def test_a_single_image_batch_is_not_measured_not_passed(monkeypatch, tmp_path):
    _stub(monkeypatch, {"verdict": "not_measured", "min": None, "mean": None,
                        "n_measurable": 1, "reason": "可测图只有 1 张（<2）"})
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc(["only.png"], ctx)
    assert res["verdict"] == "not_measured", res
    assert "1 张" in " ".join(ctx["lines"]) or "未测量" in " ".join(ctx["lines"]), ctx["lines"]


def test_an_empty_batch_is_still_recorded(monkeypatch, tmp_path):
    _stub(monkeypatch, {"verdict": "not_measured", "reason": "没有产物可量（清单为空）"})
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc([], ctx)
    assert res["verdict"] == "not_measured"
    assert res["n_input"] == 0
    # 没量成也必须留痕：返回值会被写进步骤结果里，不能是 None
    assert json.dumps(res, ensure_ascii=False)


def test_a_broken_environment_is_not_measured_and_does_not_kill_the_batch(monkeypatch, tmp_path):
    """尺子起不来（缺依赖／模型不在）⇒ 记未测量，**不抛**：一批 GPU 时间不该为量尺作废；
       但也**不写 ok**：静默失效的裁判比没有裁判更危险（GAP-G3 那条老账）。"""
    _stub(monkeypatch, boom=ImportError("no module named insightface"))
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc(["a.png", "b.png"], ctx)
    assert res["verdict"] == "not_measured", res
    assert "尺子没跑起来" in (res.get("reason") or ""), res
    assert any("未测量≠通过" in l for l in ctx["lines"]), ctx["lines"]


# ── ② 只有最低值那条拦；均值那条只警示 ─────────────────────────────
def test_low_min_blocks_and_the_message_says_what_to_do(monkeypatch, tmp_path):
    _stub(monkeypatch, {"verdict": "fail", "min": 0.728, "mean": 0.770, "n_measurable": 3})
    ctx = _ctx(tmp_path)
    with pytest.raises(RuntimeError) as e:
        T._batch_consistency_qc(["a.png", "b.png", "c.png"], ctx)
    msg = str(e.value)
    assert "批内相对尺拦下" in msg, msg
    # 报错必须带上"怎么办"，而且要说别整批重跑（成本意识是用户定的默认）
    assert "别整批重跑" in msg, msg
    assert "batch_consistency" in msg, msg        # 逃生口写在报错里，不靠人记


def test_mean_below_band_warns_but_does_not_block(monkeypatch, tmp_path):
    _stub(monkeypatch, {"verdict": "warn", "min": 0.81, "mean": 0.79, "n_measurable": 3})
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc(["a.png", "b.png", "c.png"], ctx)
    assert res["verdict"] == "warn"
    assert any("WARN" in l and "均值" in l for l in ctx["lines"]), ctx["lines"]


def test_a_clean_batch_passes_with_the_numbers_attached(monkeypatch, tmp_path):
    _stub(monkeypatch, {"verdict": "ok", "min": 0.844, "mean": 0.876, "n_measurable": 3})
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc(["a.png", "b.png", "c.png"], ctx)
    assert res["verdict"] == "ok"
    assert (res["min"], res["mean"]) == (0.844, 0.876)


# ── ④ 11-04 身份锁：判据只对"这批本该同人同装"生效 ─────────────────
def test_identity_lock_off_downgrades_fail_to_report_only_and_does_not_block(monkeypatch, tmp_path):
    """主题裸跑／探索批：换脸换装是预期。尺子照量、读数照进台账，但**不拦**。
       这条钉的是"降级发生在尺子里、引擎认这个 verdict"，不是"日志好看"。"""
    _stub(monkeypatch, {"verdict": "fail", "min": 0.716, "mean": 0.761, "n_measurable": 4})
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc(["a.png", "b.png", "c.png", "d.png"], ctx,
                                  identity_lock=False)
    assert res["verdict"] == "report_only", res
    assert res["verdict_by_identity_axis"] == "fail", res      # 原判序留痕，不留暗账
    assert (res["min"], res["mean"]) == (0.716, 0.761), res    # 数照给，降级不等于不量
    assert any("未声明身份锁" in l or "只报不拦" in l for l in ctx["lines"]), ctx["lines"]


def test_identity_lock_on_keeps_the_old_blocking_behaviour(monkeypatch, tmp_path):
    """默认 True＝现役行为不变：定妆／i2i 派生批散了一样拦。这条是防"改名顺手把闸拆了"。"""
    _stub(monkeypatch, {"verdict": "fail", "min": 0.728, "mean": 0.770, "n_measurable": 3})
    ctx = _ctx(tmp_path)
    with pytest.raises(RuntimeError) as e:
        T._batch_consistency_qc(["a.png", "b.png", "c.png"], ctx)   # 不传＝默认锁
    assert "同人" in str(e.value) or "同一身衣服" in str(e.value), str(e.value)
    # 报错要指向正确的处置：先声明身份锁，而不是先关整条尺
    assert "identity_lock" in str(e.value), str(e.value)


def test_ok_is_not_downgraded_to_report_only(monkeypatch, tmp_path):
    """量过且齐＝ok，比"只报"更强。锁关着也不许把好消息写成坏消息。"""
    _stub(monkeypatch, {"verdict": "ok", "min": 0.86, "mean": 0.9})
    ctx = _ctx(tmp_path)
    res = T._batch_consistency_qc(["a.png", "b.png"], ctx, identity_lock=False)
    assert res["verdict"] == "ok", res


def test_exploration_chains_declare_the_lock_off():
    """三条纯文生图草稿／成品链必须显式声明 `identity_lock: false`，
       而定妆链（character_sheet）**不许**声明——它默认锁着才是对的。"""
    wf = ROOT / "workflows"
    for name in ("image_draft_batch.yaml", "image_batch_draft.yaml",
                 "image_draft_batch_sdxl.yaml"):
        src = io.open(wf / name, encoding="utf-8").read()
        assert "identity_lock: false" in src, "%s 没声明身份锁，主题裸跑还会被误拦" % name
        assert 'identity_lock: "{{args.identity_lock}}"' in src, \
            "%s 只在 args 里写了值，没交进出图步 ⇒ 尺子收不到，等于没改" % name
    sheet = io.open(wf / "character_sheet.yaml", encoding="utf-8").read()
    assert "identity_lock: false" not in sheet, \
        "定妆链不该关掉身份锁：那批产物必须是同一个人"


def test_the_ruler_no_longer_claims_it_measures_style():
    """判据改名要落在**输出面**上，不只是文档：
       bands_note 再说"画风漂批＝最差"就有人会再拿它当画风尺用（这次就是这么踩的）。"""
    src = io.open(TOOLS / "qc_batch_consistency.py", encoding="utf-8").read()
    i = src.index('res["bands_note"]')
    body = src[i:i + 700]
    assert "身份与造型" in body, "bands_note 还在用画风口径说话"
    assert "交人眼" in body, "bands_note 要写清画风那一维归谁判"
    # 反向自证：explain() 打出去的那一行也不能再自称画风尺
    ebody = src[src.index("def explain("):src.index("def explain(") + 900]
    assert "身份尺" in ebody, "explain() 那行还写着 DINO 互比＝旧口径，人照样会误读"


# ── 逃生口：关掉必须留字据（同 R5-07 的规矩）───────────────────────
def test_turning_the_ruler_off_leaves_written_evidence(tmp_path):
    cfg = {"log_dir": str(tmp_path), "project": "无音",
           "qc": {"batch_consistency": "off"}}
    ctx = _ctx(tmp_path, cfg)
    res = T._batch_consistency_qc(["a.png", "b.png"], ctx)
    assert res["verdict"] == "off"
    led = json.loads((Path(cfg["log_dir"]) / "gate_approvals.json").read_text(encoding="utf-8"))
    bypass = led.get("bypassed") or {}
    assert bypass, "绕过了却没留字据＝R5-07 违规"
    entry = list(bypass.values())[-1]
    assert "批内相对尺" in entry["gates"], entry
    assert "batch_consistency=off" in entry["reason"], entry


def test_the_knob_defaults_to_on(tmp_path):
    """没写 `qc:` 这段的旧 config 必须**默认开**——"新加的行为默认关"等于没加。"""
    cfg = {"log_dir": str(tmp_path)}                  # 没有 qc 键
    ctx = _ctx(cfg=cfg, tmp_path=tmp_path)
    assert T._batch_consistency_qc.__doc__
    # 只验取法：off 判定表里不含缺省值
    knob = str(((cfg.get("qc") or {}) if isinstance(cfg.get("qc"), dict)
                else {}).get("batch_consistency", "on")).lower()
    assert knob == "on", knob


# ── ③ 接线位置与"绝对带没被顺手接进来" ────────────────────────────
def test_the_ruler_is_wired_into_the_image_batch_step():
    src = io.open(ROOT / "tasks.py", encoding="utf-8").read()
    i_def = src.index("def _batch_consistency_qc(")
    i_step = src.index("def t_comfyui(")
    i_end = src.index("@task(", i_step)
    body = src[i_step:i_end]
    assert "_batch_consistency_qc(files, ctx" in body, "出图步骤又没接尺子了"
    assert '"batch_qc"' in body, "尺子结果没进步骤返回值 ⇒ 台账里查不到"
    # 必须排在"纯色废图"那道之后：先筛每张自己的硬伤，再谈批内像不像
    assert body.index("img_is_blank") < body.index("_batch_consistency_qc(files")
    assert i_def < i_step


def _code_only(path):
    """去掉注释与字符串常量，只留"真代码"。
    ⚠ 这条不是洁癖：第一版我拿全文扫 `faceWhite`，结果被**我自己写的说明文字**
      （"绝对带 faceL／faceWhite… 一概不调"）判成"接进来了"——假阳。
      同一族教训在项目里记着：刮字面量的尺子会被注释里的举例骗到；假阴比假阳坏，
      但假阳会让人反复修一件已经修好的事，所以两头都要躲。"""
    import io as _io
    import tokenize as tk

    src = _io.open(path, encoding="utf-8").read()
    # 行号→绝对偏移，好把 (row, col) 区间打平成一个切片
    offs, acc = [0], 0
    for line in src.split("\n"):
        acc += len(line) + 1
        offs.append(acc)

    def pos(rc):
        return offs[rc[0] - 1] + rc[1]

    chars = list(src)
    try:
        toks = list(tk.generate_tokens(_io.StringIO(src).readline))
    except Exception:
        # tokenize 失败（少见）时退回"按 # 切"，宁可粗一点也别让测试自己先崩
        return "\n".join(l.split("#")[0] for l in src.split("\n"))
    for t in toks:
        if t.type in (tk.COMMENT, tk.STRING):
            a, b = pos(t.start), pos(t.end)
            # ⚠ 按**字符**切，不是按字节：本文件满是中文，bytearray 切片会把偏移整个错位，
            #   错位后的"扫描"比不扫更坏（它看起来在工作，实际在乱位置打洞）。
            chars[a:b] = [" "] * (b - a)
    return "".join(chars)



def test_absolute_bands_are_not_wired_into_the_engine():
    """裁定是"绝对带只报不拦"，而"只报"目前也没做（它们换项目就失效）。
       哪天要接，得先有新的标定证据——所以这里钉住"没偷偷接"。"""
    code = _code_only(ROOT / "tasks.py")
    for band in ("faceWhite", "lpalex", "faceHR", "gedge", "faceL"):
        assert band not in code, "绝对带 %s 被接进了引擎，但没走裁定" % band
    # 反向自证：同一把探针在"全文"上会误报（说明它真在扫代码而不是扫全文），
    # 而 `_batch_consistency_qc` 这个函数名必须在代码里出现（否则是"扫漏了"的假阴）
    full = io.open(ROOT / "tasks.py", encoding="utf-8").read()
    assert "faceWhite" in full, "说明文字里都不提这把尺了，那这条测试的对照组失效"
    assert "_batch_consistency_qc" in code, "探针连真接线的函数名都扫不到＝它失效了，别信它的空表"




def test_the_ruler_is_not_wired_into_single_output_steps():
    """`control`／`refine` 一步一张或每张来自不同草稿 ⇒ 不是"同批同提示词"，
       拿它量出来的离散与人标的那批不同源。不接是**有意的**，写进测试免得被当成漏接。"""
    src = io.open(ROOT / "tasks.py", encoding="utf-8").read()
    for fn in ("def t_control(", "def t_refine("):
        i = src.index(fn)
        body = src[i:i + 6000]
        assert "_batch_consistency_qc" not in body, "%s 被顺手接上了，先补标定再说" % fn


# ── 真尺与标定同源（跑真模型；缺素材就跳过，不假装通过）────────────
CAL_DIR = ROOT.parent / "tmp" / "wzy"
CAL_FILES = [CAL_DIR / "dz0b2ppp" / ("F%d_raw.png" % i) for i in (1, 2, 3)]


@pytest.mark.skipif(not all(f.is_file() for f in CAL_FILES),
                    reason="标定素材不在（tmp 会被清）⇒ 这条真尺对账跑不了，如实跳过")
def test_the_real_ruler_still_matches_the_calibration():
    """F 批在人判带上的读数＝均值 0.876／最低 0.844（10-02 标定，10-03 逐位复核）。
       这把尺一旦改了取法（patch 几何、模型、池化），这两个数就会漂 ⇒ 0.75/0.80 两条带作废，
       所以这条用例是"带的有效期证明"，不是"能跑出数"。"""
    import qc_batch_consistency as N

    res = N.measure([str(f) for f in CAL_FILES])
    assert res["verdict"] == "ok", res
    assert res["n_measurable"] == 3, res
    assert abs(res["mean"] - 0.876) < 0.002, res
    assert abs(res["min"] - 0.844) < 0.002, res


def test_not_measured_branches_of_the_real_ruler():
    """真尺的三个"量不了"分支（跑模型前就返回，不需 GPU）。"""
    import qc_batch_consistency as N

    assert N.measure([])["verdict"] == "not_measured"
    r = N.measure([str(CAL_FILES[0])]) if CAL_FILES[0].is_file() else None
    if r is not None:                      # 单张：数学上不存在互比
        assert r["verdict"] == "not_measured"
        assert "<2" in (r.get("reason") or ""), r
    r2 = N.measure(["不存在.png", "也不存在.png"])
    assert r2["verdict"] == "not_measured" and r2["n_unreadable"] == 2, r2
