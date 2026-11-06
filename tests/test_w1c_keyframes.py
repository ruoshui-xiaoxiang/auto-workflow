# -*- coding: utf-8 -*-
"""W1c 验收（V1c-1~V1c-4）：可选首尾帧单模板 + 单流入口。

V1c-1 T2VA 无 LoadImage/first/last；I2VA 只有 first；L2VA 只有 last；FL2VA 两端都有
V1c-2 各模式 prompt_kind 与模式一致；缺尾图在提交前失败
V1c-3 同一输入 CLI／面板得到同一 RunPlan（Graph 由同一份 Plan 生成）
V1c-4 旧 I2VA/FL2VA 模板回归不改结果（golden 已在 test_run_plan.py 钉住）
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))

import run_plan  # noqa: E402
from tasks import build_graph_video  # noqa: E402

OPT = "comfy/h3_keyframes_optional_api.json"
BASE = ["width=736", "height=416", "length=124"]
PARAMS = {"prompt": "TEST PROMPT", "width": 736, "height": 416, "length": 124,
          "steps": 8, "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
          "lora_strength": 0.7, "head_chunks": 4, "prefix": "w1c"}


def _tpl():
    return json.loads((ENGINE / OPT).read_text(encoding="utf-8"))


def _host(g):
    for nid, node in g.items():
        if isinstance(node, dict) and node.get("class_type") == "MiniMaxH3ImageToVideo":
            return nid, node
    raise AssertionError("模板里找不到 H3 首尾帧节点")


def _loads(g):
    return {k: v for k, v in g.items() if v.get("class_type") == "LoadImage"}


def _build(mode, refs=("a.png", "b.png")):
    extra = {f"__REF{i}__": n for i, n in enumerate(refs, 1)}
    return build_graph_video(_tpl(), dict(PARAMS), 42, extra_rep=extra, input_mode=mode)


# ------------------------------------------------------------------ V1c-1
def test_t2va_graph_has_no_images():
    g = _build("t2va", refs=())
    assert not _loads(g), f"T2VA 不许残留 LoadImage：{_loads(g)}"
    _nid, host = _host(g)
    assert "first_frame" not in host["inputs"] and "last_frame" not in host["inputs"]
    assert "_meta" not in g


def test_i2va_graph_only_first():
    g = _build("i2va", refs=("a.png",))
    loads = _loads(g)
    assert len(loads) == 1, loads
    _nid, host = _host(g)
    assert "first_frame" in host["inputs"] and "last_frame" not in host["inputs"]
    assert list(loads.values())[0]["inputs"]["image"] == "a.png"
    assert "_meta" not in g


def test_l2va_graph_only_last_and_uses_the_only_image():
    g = _build("l2va", refs=("tail.png",))
    loads = _loads(g)
    assert len(loads) == 1, loads
    _nid, host = _host(g)
    assert "last_frame" in host["inputs"] and "first_frame" not in host["inputs"]
    assert list(loads.values())[0]["inputs"]["image"] == "tail.png", \
        "L2VA 唯一一张图必须落在 last_frame，不能留 __REF2__ 字面量"


def test_fl2va_graph_has_both():
    g = _build("fl2va", refs=("a.png", "b.png"))
    loads = _loads(g)
    assert len(loads) == 2, loads
    _nid, host = _host(g)
    assert "first_frame" in host["inputs"] and "last_frame" in host["inputs"]
    imgs = sorted(v["inputs"]["image"] for v in loads.values())
    assert imgs == ["a.png", "b.png"], imgs


@pytest.mark.parametrize("mode,refs", [
    ("i2va", ()), ("i2va", ("a.png", "b.png")),
    ("l2va", ("a.png", "b.png")), ("fl2va", ("a.png",)),
    ("t2va", ("a.png",)),
])
def test_wrong_image_count_fails_before_graph(mode, refs):
    with pytest.raises(ValueError) as ei:
        _build(mode, refs=refs)
    assert "收到" in str(ei.value), str(ei.value)


def test_old_single_first_template_still_accepts_i2va():
    """V1c-4：旧单首帧模板的行为不动（不给 input_mode 时更是一字不改）。"""
    tpl = json.loads((ENGINE / "comfy/h3_i2v_fl2va_api.json").read_text(encoding="utf-8"))
    g = build_graph_video(tpl, dict(PARAMS), 42, extra_rep={"__REF1__": "a.png"})
    _nid, host = _host(g)
    assert "first_frame" in host["inputs"] and "last_frame" not in host["inputs"]
    assert len(_loads(g)) == 1


# ------------------------------------------------------------------ prompt / plan
def _prompt(tmp_path, mode):
    first = {
        "i2va": "For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> (from [Shot 1]) is fully referenced.",
        "fl2va": "How the reference pictures align with the target video — "
                 "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                 "Picture 2 (from Shot 1) aligns with the 5.00-second mark of the target video.",
        "l2va": "How the reference pictures align with the target video — "
                "<Picture 1> (from [Shot 1]) aligns with the 5.00-second mark of the target video.",
        "t2va": None,
    }[mode]
    body = ("integrated_multimodal_description: [Shot 1] Live-action, cinematic, a stone gate.\n\n"
            "overall_soundscape: Wind and distant stone rumble.\n\n"
            "non_diegetic_music: N/A")
    text = f"{first}\n\n{body}" if first else body
    p = tmp_path / f"{mode}.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _img(tmp_path, name="a.png"):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n")
    return str(p)


def _plan(wf, name, sets, tier="draft"):
    cli = run_plan.parse_sets(sets)
    args, sources = run_plan.merge_args(wf.get("args") or {}, {}, cli)
    return run_plan.build_run_plan(ENGINE, name, wf, args, sources,
                                   cfg={"project": "无音"}, tier=tier)


def _wf():
    return yaml.safe_load((ENGINE / "workflows" / "h3_keyframe_modes.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode,n", [("t2va", 0), ("i2va", 1), ("l2va", 1), ("fl2va", 2)])
def test_plan_mode_and_prompt_kind_consistent(tmp_path, mode, n):
    """V1c-2：模式、首行、registry prompt_kind 三者一致。"""
    imgs = [_img(tmp_path, f"r{i}.png") for i in range(n)]
    sets = [f"input_mode={mode}", f"prompt_file={_prompt(tmp_path, mode)}"] + BASE
    if imgs:
        sets.append("ref_images=" + ",".join(imgs))
    p = _plan(_wf(), "h3_keyframe_modes", sets)
    assert p["inputs"]["input_mode"] == mode
    assert p["text"]["detected_skeleton_mode"] == mode
    assert p["text"]["prompt_kind"] == f"h3_{mode}"
    assert p["text"]["declared_prompt_kind"] in (None, "", f"h3_{mode}")
    # 素材落位
    m = p["inputs"]["materials"]
    if mode == "t2va":
        assert m["first_frame"] is None and m["last_frame"] is None
    elif mode == "i2va":
        assert m["first_frame"] and m["last_frame"] is None
    elif mode == "l2va":
        assert m["last_frame"] and m["first_frame"] is None
    else:
        assert m["first_frame"] and m["last_frame"]


def test_fl2va_missing_tail_fails_before_submit(tmp_path):
    sets = ["input_mode=fl2va", f"prompt_file={_prompt(tmp_path, 'fl2va')}",
            f"ref_images={_img(tmp_path)}"] + BASE
    with pytest.raises(run_plan.PlanError) as ei:
        _plan(_wf(), "h3_keyframe_modes", sets)
    assert "缺尾帧" in str(ei.value) or "2 张" in str(ei.value), str(ei.value)


def test_t2va_with_image_fails(tmp_path):
    sets = ["input_mode=t2va", f"prompt_file={_prompt(tmp_path, 't2va')}",
            f"ref_images={_img(tmp_path)}"] + BASE
    with pytest.raises(run_plan.PlanError) as ei:
        _plan(_wf(), "h3_keyframe_modes", sets)
    assert "T2VA 不接图" in str(ei.value), str(ei.value)


# ------------------------------------------------------------------ V1c-3
def test_cli_and_panel_same_plan_for_l2va(tmp_path):
    img = _img(tmp_path)
    pf = str(_prompt(tmp_path, "l2va"))
    cli = _plan(_wf(), "h3_keyframe_modes",
                ["input_mode=l2va", f"ref_images={img}", f"prompt_file={pf}"] + BASE)
    panel = {"input_mode": "l2va", "ref_images": [img], "prompt_file": pf,
             "width": 736, "height": 416, "length": 124}
    args, sources = run_plan.merge_args(_wf().get("args") or {}, {}, panel)
    p2 = run_plan.build_run_plan(ENGINE, "h3_keyframe_modes", _wf(), args, sources,
                                 cfg={"project": "无音"}, tier="draft")
    assert cli == p2


def test_g4_uses_optional_template_real_slots(tmp_path):
    """G4 必须按模式数真实槽位：T2VA 0 图不算缺图，FL2VA 只给 1 图要报缺尾帧。"""
    sys.path.insert(0, str(ENGINE.parent / "tools"))
    from check_preflight import run_checks
    tpl = str(ENGINE / "comfy" / "h3_keyframes_optional_api.json")
    png = _img(tmp_path, "a.png")

    def _spec(mode, imgs):
        return {"prompt": str(_prompt(tmp_path, mode).read_text(encoding="utf-8")),
                "refs": imgs, "ref_videos": [], "prompt_kind": "h3_" + mode,
                "input_mode": mode, "w": 736, "h": 416, "length": 124,
                "provider": "local", "only": ["G4"], "workflow_json": tpl,
                "output_root": str(tmp_path), "project": "无音",
                "project_aliases": {"无音": ["无音"]}}

    assert not run_checks(_spec("t2va", [])).errors, "T2VA 0 图不该被判缺图"
    assert not run_checks(_spec("i2va", [png])).errors
    assert not run_checks(_spec("l2va", [png])).errors
    assert not run_checks(_spec("fl2va", [png, _img(tmp_path, "b.png")])).errors
    rep = run_checks(_spec("fl2va", [png]))
    assert any(g == "G4" for _lv, g, _m in rep.errors), rep.render()
    assert "缺尾帧" in " ".join(m for _lv, _g, m in rep.errors), rep.render()


# ------------------------------------------------------------------ 真 CLI
def _inspect(tmp_path, mode, extra_sets=()):
    cfg = yaml.safe_load(Path(os.environ["AW_CONFIG_PATH"]).read_text(encoding="utf8"))
    status = Path(cfg["status_file"])
    before = status.read_text(encoding="utf8") if status.exists() else None
    cmd = [sys.executable, "run.py", "h3_keyframe_modes", "--inspect",
           "--set", f"input_mode={mode}",
           "--set", f"prompt_file={_prompt(tmp_path, mode)}"]
    for s in extra_sets:
        cmd += ["--set", s]
    r = subprocess.run(cmd, cwd=str(ENGINE), capture_output=True, text=True,
                       encoding="utf8", errors="replace", timeout=120)
    after = status.read_text(encoding="utf8") if status.exists() else None
    assert after == before, "--inspect 不许写 status"
    return r


def test_cli_inspect_l2va_derives_prompt_kind(tmp_path):
    img = _img(tmp_path, "tail.png")
    r = _inspect(tmp_path, "l2va", [f"ref_images={img}"])
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    plan = json.loads(r.stdout.split("--- run_plan ---", 1)[1])
    assert plan["inputs"]["input_mode"] == "l2va"
    assert plan["text"]["prompt_kind"] == "h3_l2va"
    assert plan["text"]["declared_prompt_kind"] == "h3_l2va", \
        "run.py 没按 input_mode 派生 prompt_kind"
    assert plan["recipe"]["steps"] == 8


def test_cli_inspect_t2va_needs_zero_images(tmp_path):
    r = _inspect(tmp_path, "t2va")
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    plan = json.loads(r.stdout.split("--- run_plan ---", 1)[1])
    assert plan["inputs"]["input_mode"] == "t2va"
    assert plan["inputs"]["counts"]["images"] == 0


def test_cli_rejects_unknown_input_mode(tmp_path):
    r = subprocess.run(
        [sys.executable, "run.py", "h3_keyframe_modes", "--inspect",
         "--set", "input_mode=xxva", "--set", f"prompt_file={_prompt(tmp_path, 't2va')}"],
        cwd=str(ENGINE), capture_output=True, text=True, encoding="utf8",
        errors="replace", timeout=120)
    assert r.returncode == 2
    assert "input_mode" in r.stderr
