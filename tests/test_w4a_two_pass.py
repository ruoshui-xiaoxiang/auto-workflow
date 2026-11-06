# -*- coding: utf-8 -*-
"""W4a 验收（V4a-1/V4a-3/V4a-4）：R3 二采是配方不是模式。

V4a-1 修正后的模板节点 14 与**已验证 runner** 的有效图等价
V4a-3 归属/失败信息可读（这里测"缺参数就停在提交前"的那半，真超时归属在 W5b）
V4a-4 配方变化只改声明字段；2.0 撞已知崩溃边界要一次确认；Bunny 不默认注入
V4a-2（中性 1.25 实际尺寸/帧数与记录一致）需要真出片 ⇒ 本文件**不冒充**，见计划 §7 记未执行。
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))

import run_plan  # noqa: E402
import tasks as T  # noqa: E402

TPL_REL = "comfy/h3_two_pass_api.json"
RUNNER = Path(r"E:\创作\三材两风_试片\00_计划\run_tp_fast.py")
R3_LORA = "minimax_h3_fl2v_turbo_4step_v0.1_comfyui_alpha8-T8-convert.safetensors"
BASE_P = {"prompt": "P", "width": 736, "height": 416, "length": 124, "steps": 8,
          "lora": R3_LORA, "lora_strength": 1.0, "head_chunks": 4, "prefix": "tp",
          "two_pass": True, "two_pass_coarse_steps": 4, "two_pass_refine_steps": 4,
          "scale_by": 1.25}


def _tpl():
    return json.loads((ENGINE / TPL_REL).read_text(encoding="utf-8"))


def _build(p=None, extra=None, drop=()):
    pp = dict(BASE_P)
    pp.update(p or {})
    for k in drop:
        pp.pop(k, None)
    extra = extra or {"__REF1__": "wfref_1_a.png"}
    return T.build_graph_video(_tpl(), pp, 42, extra_rep=extra)


def _leftover_placeholders(g):
    return sorted({m for m in re.findall(r"__[A-Z0-9_]+__", json.dumps(g, ensure_ascii=False))})


# ------------------------------------------------------------------ V4a-1
@pytest.mark.skipif(not RUNNER.is_file(), reason="已验证 runner 不在盘上")
def test_node14_equals_validated_runner():
    """模板节点 14 必须与已验证 runner 重建的那一份逐字段相同。"""
    spec = importlib.util.spec_from_file_location("run_tp_ref", str(RUNNER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_tp_ref"] = mod
    spec.loader.exec_module(mod)
    theirs = mod.build_graph("in.png", "P", 736, 416, 124, 42, "out")["14"]["inputs"]
    mine = _build()["14"]["inputs"]
    assert mine["length"] == 124 and theirs["length"] == 124
    for key in ("task_type", "audio_mode", "audio_denoise_strength", "add_source_as_reference",
                "prompt_primary_audio_ordinal", "strict_prompt_tags", "ref_image_size",
                "reference_video_policy", "allow_above_reference_area", "width", "height",
                "first_frame", "clip", "video_vae", "audio_vae"):
        assert mine[key] == theirs[key], (key, mine[key], theirs[key])


def test_node14_is_no_longer_shifted():
    """旧坏图的特征：length 装宽、task_type 装高、audio_mode 装帧数。"""
    ins = _build()["14"]["inputs"]
    assert ins["task_type"] == "I2VA", ins
    assert ins["audio_mode"] == "native", ins
    assert ins["length"] == 124, ins
    assert ins["width"] == ["13", 1] and ins["height"] == ["13", 2], ins
    assert isinstance(ins["audio_denoise_strength"], float), ins


def test_no_placeholder_survives_substitution():
    g = _build()
    assert _leftover_placeholders(g) == [], "占位没填完就会被当字面量提交给 ComfyUI"


# ------------------------------------------------------------------ V4a-4
def test_scale_by_is_explicit_no_default():
    with pytest.raises(ValueError) as ei:
        _build(drop=("scale_by",))
    assert "scale_by" in str(ei.value)


@pytest.mark.parametrize("scale", [1.0, 1.25, 2.0])
def test_declared_scale_lands_on_upscale_node(scale):
    p = {"scale_by": scale, "confirm_big_scale": "true"}
    ins = _build(p)["13"]["inputs"]
    assert float(ins["scale_by"]) == scale, ins


def test_big_scale_boundary_needs_one_confirmation():
    p = {"scale_by": 2.0, "length": 264, "confirm_big_scale": ""}
    with pytest.raises(ValueError) as ei:
        _build(p)
    msg = str(ei.value)
    assert "264" in msg and "confirm_big_scale" in msg, msg
    assert _build(dict(p, confirm_big_scale="true"))["13"]["inputs"]["scale_by"] == 2.0


def test_steps_are_declared_not_hidden_behind_standard8():
    g = _build()
    assert int(g["8"]["inputs"]["steps"]) == 8
    plan = g["9"]["inputs"]
    assert (plan["base_steps"], plan["coarse_steps"], plan["refine_steps"]) == (8, 4, 4), plan
    g2 = _build({"two_pass_coarse_steps": 3, "two_pass_refine_steps": 3})
    assert (g2["9"]["inputs"]["coarse_steps"], g2["9"]["inputs"]["refine_steps"]) == (3, 3)
    assert int(g2["8"]["inputs"]["steps"]) == 8, "改 4+4 不该顺带动第一遍步数"


def test_bunny_not_injected_by_default():
    g = _build()
    names = json.dumps(g, ensure_ascii=False)
    assert "Bunny" not in names, "中性日用默认不许悄悄挂打斗增强 LoRA"
    assert all(n["class_type"] != "LoraLoaderModelOnly" for n in g.values()), \
        "lora2 为空时不该多出增强 LoRA 节点"


def test_bunny_injected_and_wired_when_declared():
    g = _build({"lora2": "Bunny_weapon_combatV1.safetensors", "bunny_strength": 0.5})
    enh = [n for n in g.values() if n["class_type"] == "LoraLoaderModelOnly"]
    assert len(enh) == 1 and "Bunny" in enh[0]["inputs"]["lora_name"], enh
    eid = [k for k, v in g.items() if v is enh[0]][0]
    assert enh[0]["inputs"]["model"] == ["5", 0], "增强节点接在基底 LoRA 之后"
    assert g["8"]["inputs"]["model"] == [eid, 0] and g["16"]["inputs"]["model"] == [eid, 0], \
        "两个采样段的 model 必须改接到增强节点"
    assert enh[0]["inputs"]["strength_model"] == 0.5


def test_wrong_template_says_so():
    p = dict(BASE_P)
    with pytest.raises(ValueError) as ei:
        T.build_graph_video(json.loads((ENGINE / "comfy/h3_i2v_fl2va_api.json")
                                       .read_text(encoding="utf-8")), p, 42,
                             extra_rep={"__REF1__": "a.png"})
    assert "不是二采图" in str(ei.value), str(ei.value)


# ------------------------------------------------------------------ plan 侧
def _plan(**over):
    wf = yaml.safe_load((ENGINE / "workflows" / "h3_two_pass_daily.yaml").read_text(encoding="utf-8"))
    sets = ["input_mode=i2va", "prompt=PROMPT TEXT", "width=736", "height=416",
            "length=124", "steps=8", f"lora={R3_LORA}", "lora_strength=1.0",
            "two_pass=true", "two_pass_coarse_steps=4", "two_pass_refine_steps=4",
            "scale_by=1.25"]
    img = Path(over.pop("img", None) or "")
    sets.append("ref_images=" + str(img))
    for k, v in over.items():
        sets.append(f"{k}={v}")
    cli = run_plan.parse_sets(sets)
    args, sources = run_plan.merge_args(wf.get("args") or {}, {}, cli)
    return run_plan.build_run_plan(ENGINE, "h3_two_pass_daily", wf, args, sources,
                                   cfg={"project": "无音"}, tier="draft")


def test_plan_marks_r3_as_recipe_not_mode(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n")
    p = _plan(img=png)
    assert p["inputs"]["input_mode"] == "i2va", "二采不是第六种输入模式"
    assert p["recipe"]["second_pass"] is True
    assert p["recipe"]["recipe_id"].startswith("r3-2p"), p["recipe"]["recipe_id"]
    assert p["recipe"]["scale"] == 1.25 and p["recipe"]["coarse_steps"] == 4
    assert str(p["recipe"]["pairing"]).startswith("verified(R3"), p["recipe"]["pairing"]
    assert "二采   R3" in run_plan.render_summary(p)
    # lora2 为空 ⇒ Bunny 显示"未选"，不能把 YAML 里的 0.5 当成"这批开了 Bunny"
    assert p["recipe"]["bunny"] is None and p["recipe"]["bunny_lora"] is None, p["recipe"]
    assert "Bunny=未选" in run_plan.render_summary(p)
    p2 = _plan(img=png, lora2="Bunny_weapon_combatV1.safetensors")
    assert p2["recipe"]["bunny"] == 0.5 and p2["recipe"]["bunny_lora"] == \
        "Bunny_weapon_combatV1.safetensors", p2["recipe"]


def test_plan_rejects_wrong_base_lora(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n")
    with pytest.raises(run_plan.PlanError) as ei:
        _plan(img=png, lora="minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors")
    assert "alpha8" in str(ei.value), str(ei.value)


# ------------------------------------------------------------------ registry
def test_registry_recipes_are_not_modes():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    assert len(reg["input_modes"]["modes"]) == 5, "输入模式仍是官方五种"
    recipes = reg["recipes"]["recipes"]
    assert set(recipes) >= {"single8", "clean20", "ref2v4", "r3_two_pass"}
    r3 = recipes["r3_two_pass"]
    assert r3["two_pass"] is True and r3["daily_default_scale"] == 1.25
    assert Path(ENGINE / r3["template"]).is_file()
    assert Path(ENGINE / "workflows" / (r3["workflow"] + ".yaml")).is_file()
    assert r3["optional_enhance"]["default"] == "", "Bunny 默认关"
