# -*- coding: utf-8 -*-
"""W4b（Bunny 可选＋多镜编排）与 W5b 审核点链的离线验收。

V4b 侧：Bunny 只在显式声明时进图；编排判据查 registry 不猜名字。
V5b-4 侧：四个审核点都在链上、都是 human、批准键绑参数与媒体。
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))

import run_plan                       # noqa: E402
import tasks as T                     # noqa: E402


def _wf(name):
    return yaml.safe_load((ENGINE / "workflows" / f"{name}.yaml").read_text(encoding="utf-8"))


def _reg():
    return json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 编排判据
def test_orchestration_comes_from_registry_not_name():
    """`*_play` 名字里带 play 是参数预设；编排必须查表，查不到就说没登记。"""
    assert run_plan._orchestration_of(ENGINE, "h3_one_click_movie") == (
        "movie", "registry.orchestrations.movie.flows")
    assert run_plan._orchestration_of(ENGINE, "h3_i2va_batch")[0] == "batch"
    assert run_plan._orchestration_of(ENGINE, "h3_two_pass_daily")[0] == "single"
    key, basis = run_plan._orchestration_of(ENGINE, "h3_瞎起的名字")
    assert key == "unregistered" and "没登记" in basis


def test_every_orchestration_flow_exists():
    for key, spec in (_reg()["orchestrations"]["values"].items()):
        assert spec.get("state") in ("available", "need_flow", "not_applicable"), key
        for flow in spec.get("flows") or []:
            assert (ENGINE / "workflows" / f"{flow}.yaml").is_file(), (key, flow)


# ------------------------------------------------------------------ Bunny 可选
def test_bunny_declared_adds_one_node_only():
    tpl = json.loads((ENGINE / "comfy/h3_two_pass_modes_api.json").read_text(encoding="utf-8"))
    base = {"prompt": "P", "width": 736, "height": 416, "length": 124, "steps": 8,
            "lora": "minimax_h3_fl2v_turbo_4step_v0.1_comfyui_alpha8-T8-convert.safetensors",
            "input_mode": "i2va", "two_pass": True, "scale_by": 1.25}
    plain = T.build_graph_video(tpl, dict(base), 42,
                                extra_rep={"__REF1__": "a.png"})
    bunnyed = T.build_graph_video(tpl, dict(base, lora2="Bunny_weapon_combatV1.safetensors",
                                            lora2_strength=0.5), 42,
                                  extra_rep={"__REF1__": "a.png"})
    assert sum(1 for n in plain.values()
               if n.get("class_type") == "LoraLoaderModelOnly") == 0
    assert sum(1 for n in bunnyed.values()
               if n.get("class_type") == "LoraLoaderModelOnly") == 1
    assert T.content_hash8.__doc__          # 顺带确认哈希函数在


# ------------------------------------------------------------------ 审核点链
def test_batch_review_flow_has_four_human_review_points():
    w = _wf("h3_batch_review")
    gates = [s for s in w["steps"] if s.get("task") == "gate"]
    human = [s for s in gates if str(s.get("mode")) == "human"]
    assert [s["id"] for s in human] == ["RP1", "RP2", "RP3", "RP4"], [s["id"] for s in human]
    # 每个审核点都要能"有牙"：附件或提示词至少有一样，否则等于没审
    for s in human:
        assert any(k in s for k in ("files", "videos", "show_prompt")), s["id"]
    # 审核点必须排在机械预检之后、正式提交前后各两个
    order = [s["id"] for s in w["steps"]]
    assert order.index("pre") < order.index("RP1") < order.index("gen") < order.index("RP4")
    # 提示词包审的是编译稿，不是原稿
    assert "prompt_compile" in _by(w, "RP1")["prompt_file"]
    assert _by(w, "RP1")["prompt_file"] == _by(w, "gen")["prompt_file"], \
        "审的那份和提交的那份必须是同一份"


def test_draft_point_uses_cheap_four_step_recipe():
    w = _wf("h3_batch_review")
    draft = _by(w, "draft")
    assert str(draft["steps"]) == "{{args.draft_steps}}"
    assert draft["lora"] == "" and float(draft["lora_strength"]) == 0.0, \
        "4 步草稿不挂 8 步 LoRA，否则草稿与正片不是一套东西"
    assert _by(w, "RP3")["steps"] == "{{args.draft_steps}}"


def _by(wf, sid):
    return [s for s in wf["steps"] if s.get("id") == sid][0]


def test_review_point_gate_digest_moves_with_declared_params(tmp_path, monkeypatch):
    """审核点键必须随 seed/steps 变；同参数重跑才允许沿用批准。"""
    import _isolation
    cfg, _p = _isolation.isolated_config(tmp_path)
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n")
    pf = tmp_path / "p.txt"
    pf.write_text("EN prompt", encoding="utf-8")
    monkeypatch.setattr(T, "push_gate_review",
                        lambda c, cap, f, v, logf: {"pushed": False})
    monkeypatch.setattr(T, "write_pending_note", lambda *a, **k: None)
    monkeypatch.setattr(T, "toast", lambda *a, **k: None)
    batch = tmp_path / "batch"
    batch.mkdir()
    ctx = {"cfg": cfg, "args": {}, "run_id": "R", "workflow": "h3_batch_review",
           "batch_dir": batch, "wf_root": ENGINE, "step_id": "RP1", "log": lambda m: None}
    base = {"mode": "human", "gate_id": "RP1", "prompt_file": str(pf),
            "refs": [str(png)], "width": 736, "height": 416, "length": 124,
            "lora": "x.safetensors", "seed": 42, "steps": 8, "lora_strength": 0.7,
            "workflow_json": "comfy/h3_keyframes_optional_api.json"}
    keys = []
    for over in ({}, {"seed": 43}, {"steps": 8}, {"input_mode": "i2va"}):
        T.write_approvals(cfg, {"pending": {}, "approved": {}, "denied": {}})
        p = dict(base)
        p.update(over)
        with pytest.raises(T.GateAwaiting):
            T.t_gate(p, ctx)
        pend = T.read_approvals(cfg).get("pending") or {}
        assert len(pend) == 1, pend
        keys.append(next(iter(pend)))
    assert keys[0] == keys[2], "同参数重跑必须命中同一个批准键"
    assert len({keys[0], keys[1]}) == 2, "换 seed 必须另开批准"
