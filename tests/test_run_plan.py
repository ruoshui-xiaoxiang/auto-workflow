# -*- coding: utf-8 -*-
"""W1 RunPlan 验收（V1-1~V1-4）：纯解析、不提交、模式切换的差异有界。

V1-1 CLI／面板同一组输入 → 同一 RunPlan（逐字段比对）
V1-2 旧预设归一图与改前一致（golden graph 哈希钉在下面，采集于 2026-10-23 改前）
V1-3 缺尾图／多图／混用格式／图形不存在／LoRA 与步数不配对 → 提交前可解释地失败
V1-4 仅切模式时，差异只落在模式、素材槽、模板指针、首行相关字段
"""
import hashlib
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

# V1-2 基线：由 `D:\AIWorkflow\evidence\W1\build_golden_before.py` 对账生成——
# before(10-19 原 builder 备份) / mid(W5a 之后) / now(现役) 三个 builder 对同一模板
# ＋同一固定参数＋seed=42 建出的图，规范化 JSON sha256 **完全相同**（2026-10-23 实跑，
# all_equal=True，见 evidence/W1/golden_graph_before.json）。
# 下面钉的就是这份实测值，不再是"注释声称改前采集"。
GOLDEN = {
    "i2va": ("comfy/h3_i2v_fl2va_api.json",
             "a3a6e17bc364eda5ea77a3adcd962b85fc3eaa89fc5ee1476d2e18eb4a676796"),
    "fl2va": ("comfy/h3_i2v_fl2va_dual_api.json",
              "e8edd2977861139d669eb0a7e9583d808f749e6024b29a7d88fce2de7b6db9bf"),
    "ref2va": ("comfy/h3_i2v_ref2va_api.json",
               "c6ab8c4242ee7d237640b611b69ac93bf468892d545d469ad9dfcf783eeb1b6b"),
}

# 仅切模式时允许变化的字段前缀（V1-4）
MODE_ONLY_PREFIXES = (
    "inputs.input_mode", "inputs.mode_basis", "inputs.materials", "inputs.counts",
    "inputs.template_capabilities", "text.prompt_kind", "text.detected_skeleton_mode",
    "text.declared_prompt_kind",
    "versions.template", "versions.yaml", "identity.workflow", "registry",
    "sources",
    # W4c：格子由"模式 × 配方"决定，切模式必然换格；配方数值本身仍须逐字不变
    "recipe.matrix",
    # W4b：编排按 registry 的 flows 表查（合成探针流没登记 ⇒ unregistered），也随模式变
    "flow.orchestration", "flow.orchestration_basis",
)

# 各用例共用的几何/文本底座（合成工作流没有 YAML 默认值，必须显式给）
BASE = ["width=736", "height=416", "length=124", "prompt=TEST PROMPT"]


def _img(tmp_path, name, data=b"\x89PNG\r\n"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _vid(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"\x00")
    return str(p)


def _wf(name):
    return yaml.safe_load((ENGINE / "workflows" / f"{name}.yaml").read_text(encoding="utf-8"))


def _bleed_plan(wf, name, sets, tier="draft"):
    """走 CLI 语义（--set 字符串）解析出一份计划。"""
    cli = run_plan.parse_sets(sets)
    args, sources = run_plan.merge_args(wf.get("args") or {}, {}, cli)
    return run_plan.build_run_plan(ENGINE, name, wf, args, sources,
                                   cfg={"project": "无音"}, tier=tier)


def _diff_paths(a, b, prefix=""):
    out = set()
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            out |= _diff_paths(a.get(k), b.get(k), f"{prefix}{k}.")
    elif isinstance(a, list) and isinstance(b, list):
        if a != b:
            out.add(prefix.rstrip("."))
    elif a != b:
        out.add(prefix.rstrip("."))
    return out


# ------------------------------------------------------------------ V1-1
def test_cli_and_panel_produce_same_plan(tmp_path):
    wf = _wf("h3_i2va_video")
    a = _img(tmp_path, "a.png")
    extra = {"steps": "8"}
    # CLI 形态：--set 的旧逗号字符串
    cli_sets = [f"ref_images={a}"] + BASE + [f"{k}={v}" for k, v in extra.items()]
    p_cli = _bleed_plan(wf, "h3_i2va_video", cli_sets)
    # 面板形态：已具名的 dict（列表就是列表，数值已 cast）
    panel = {"ref_images": [a], "steps": 8, "width": 736, "height": 416,
             "length": 124, "prompt": "TEST PROMPT"}
    args, sources = run_plan.merge_args(wf.get("args") or {}, {}, panel)
    p_panel = run_plan.build_run_plan(ENGINE, "h3_i2va_video", wf, args, sources,
                                      cfg={"project": "无音"}, tier="draft")
    assert p_cli == p_panel, sorted(_diff_paths(p_cli, p_panel))
    assert p_cli["inputs"]["input_mode"] == "i2va"


def test_parse_sets_comma_and_json_and_pick_preserved():
    assert run_plan.parse_sets(["ref_images=a.png,b.png"])["ref_images"] == ["a.png", "b.png"]
    assert run_plan.parse_sets(['ref_images=["a.png", "b.png"]'])["ref_images"] == ["a.png", "b.png"]
    # pick 必须保持逗号字符串：resolve_pick 按字符串切
    assert run_plan.parse_sets(["pick=3,7"])["pick"] == "3,7"
    assert run_plan.parse_sets(["ref_images="])["ref_images"] == []


def test_parse_sets_rejects_broken_json():
    with pytest.raises(run_plan.PlanError) as ei:
        run_plan.parse_sets(["ref_images=[a.png,b.png"])
    assert "JSON" in str(ei.value)


# ------------------------------------------------------------------ V1-2
@pytest.mark.parametrize("mode", sorted(GOLDEN))
def test_old_preset_graph_hash_unchanged(mode):
    rel, want = GOLDEN[mode]
    cases = {
        "i2va": ({"prompt": "GOLDEN PROMPT", "width": 736, "height": 416, "length": 124,
                  "steps": 8, "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                  "lora_strength": 0.7, "head_chunks": 4, "prefix": "golden"},
                 {"__REF1__": "wfref_1_a.png", "__REF2__": "wfref_2_b.png",
                  "__REF3__": "wfref_3_c.png", "__REF4__": "wfref_4_d.png"}),
        "fl2va": ({"prompt": "GOLDEN PROMPT", "width": 864, "height": 1536, "length": 124,
                   "steps": 8, "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                   "lora_strength": 0.7, "head_chunks": 4, "prefix": "golden"},
                  {"__REF1__": "wfref_1_a.png", "__REF2__": "wfref_2_b.png"}),
        "ref2va": ({"prompt": "GOLDEN PROMPT", "width": 736, "height": 416, "length": 124,
                    "steps": 4, "lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
                    "lora_strength": 1.0, "head_chunks": 4, "prefix": "golden"},
                   {"__REF1__": "wfref_1_a.png", "__REF2__": "wfref_2_b.png",
                    "__REF3__": "wfref_3_c.png", "__REF4__": "wfref_4_d.png"}),
    }[mode]
    params, extra = cases
    tpl = json.loads((ENGINE / rel).read_text(encoding="utf-8"))
    g = build_graph_video(tpl, dict(params), 42, extra_rep=extra, ref_videos=None)
    canon = json.dumps(g, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == want, \
        f"{mode} 旧预设归一图变了：模板 {rel} 或 build_graph_video 被改动过"


def test_v1_2_evidence_file_agrees_with_golden_constants():
    """证据文件必须真在盘上，且三模式哈希与本文件钉的常量逐字相同。"""
    ev = Path(r"D:\AIWorkflow\evidence\W1\golden_graph_before.json")
    assert ev.is_file(), f"V1-2 证据缺失：{ev}（先跑 {ev.parent}\\build_golden_before.py）"
    data = json.loads(ev.read_text(encoding="utf-8"))
    assert data["all_equal"] is True, data.get("all_equal")
    for mode, (rel, want) in GOLDEN.items():
        row = data["cases"][mode]
        assert row["template"] == rel, mode
        for label in ("before", "mid", "now"):
            assert row["graph_sha256"][label] == want, (mode, label)


def test_run_plan_points_at_same_templates_as_golden():
    """V1-2 的覆盖边界要说清：golden 只钉 **三条单遍固定参数图**
    （i2va/fl2va/ref2va 的现役静态模板）。二采图不在其中——它由
    tests/test_w4a_two_pass.py 的 test_node14_equals_validated_runner 拿
    已验证 runner 逐字段对账，两处的实跑输出（退出码/相等性）都另存证据。"""
    reg = run_plan.load_input_modes(ENGINE)
    assert reg["i2va"]["template"] == GOLDEN["i2va"][0]
    assert reg["fl2va"]["template"] == GOLDEN["fl2va"][0]
    # ref2va 的入口模板 W4c 起换成 9 图动态版，golden 对的是**兼容用的旧 4 图版**
    assert reg["ref2va"]["legacy_template"] == GOLDEN["ref2va"][0]
    assert reg["ref2va"]["template"] == "comfy/h3_i2v_ref2va9_api.json"


def test_registry_matches_live_yaml_and_templates():
    """registry 是模式元数据真源：模板指针必须与现役 YAML 引用的模板一致，
    prompt_kind 必须与 G7 认的词一致——否则就是第二份会漂的真源。"""
    reg = run_plan.load_input_modes(ENGINE)
    for mode, wf_name in (("i2va", "h3_i2va_video"), ("fl2va", "h3_fl2va_dual_play")):
        assert run_plan.find_template(_wf(wf_name)) == reg[mode]["template"], mode
    # ref2va 有两条入口：W4c 新链用 9 图动态模板，老链仍用 legacy 4 图模板
    assert run_plan.find_template(_wf("h3_ref2va9_daily")) == reg["ref2va"]["template"]
    assert run_plan.find_template(_wf("h3_ref2va_video")) == reg["ref2va"]["legacy_template"]
    assert reg["i2va"]["prompt_kind"] == "h3_i2va"
    assert reg["fl2va"]["prompt_kind"] == "h3_fl2va"
    assert reg["l2va"]["prompt_kind"] == "h3_l2va"
    assert reg["t2va"]["prompt_kind"] == "h3_t2va"
    assert reg["ref2va"]["prompt_kind"] == "h3_ref2va"


def test_real_misnamed_yaml_detected_as_i2va(tmp_path):
    """h3_fl2va_clean_play 名字带 fl2va，模板却只有 first_frame ⇒ 必须按图判成 I2VA。"""
    png = _img(tmp_path, "a.png")
    plan = _bleed_plan(_wf("h3_fl2va_clean_play"), "h3_fl2va_clean_play",
                       [f"ref_images={png}", "prompt=TEST PROMPT"])
    assert plan["inputs"]["input_mode"] == "i2va", plan["inputs"]["mode_basis"]
    assert plan["text"]["prompt_kind"] == "h3_i2va"
    assert plan["recipe"]["steps"] == 20
    assert plan["recipe"]["pairing"] == "verified"


# ------------------------------------------------------------------ V1-3
def _dual_wf():
    return {"name": "h3_fl2va_probe",
            "steps": [{"task": "video", "id": "v",
                       "workflow": "comfy/h3_i2v_fl2va_dual_api.json"}]}


def test_missing_tail_frame_fails_before_submit(tmp_path):
    a = _img(tmp_path, "a.png")
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(_dual_wf(), "h3_fl2va_probe", [f"ref_images={a}"] + BASE)
    msg = str(ei.value)
    assert "缺尾帧" in msg and "h3_i2v_fl2va_api.json" in msg, msg


def test_too_many_ref_images_fails(tmp_path):
    five = [_img(tmp_path, f"r{i}.png") for i in range(5)]
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(_wf("h3_ref2va_video"), "h3_ref2va_video",
                    ["ref_images=" + ",".join(five)] + BASE)
    msg = str(ei.value)
    assert "4 个参考图槽" in msg, msg


def test_mixed_format_fails(tmp_path):
    png = _img(tmp_path, "a.png")
    mp4 = _vid(tmp_path, "clip.mp4")
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(_wf("h3_ref2va_video"), "h3_ref2va_video",
                    [f"ref_images={png},{mp4},{png},{png}"] + BASE)
    assert "混用格式" in str(ei.value), str(ei.value)


def test_missing_template_fails(tmp_path):
    wf = {"name": "probe", "steps": [{"task": "video", "id": "v",
                                      "workflow": "comfy/不存在_api.json"}]}
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(wf, "probe", ["ref_images=" + _img(tmp_path, "a.png")] + BASE)
    assert "图形不存在" in str(ei.value)


def test_lora_steps_mismatch_fails(tmp_path):
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(_wf("h3_i2va_video"), "h3_i2va_video",
                    ["ref_images=" + _img(tmp_path, "a.png")] + BASE + ["steps=4"])
    assert "steps=8" in str(ei.value), str(ei.value)


def test_missing_size_or_length_fails(tmp_path):
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(_wf("h3_i2va_video"), "h3_i2va_video",
                    ["ref_images=" + _img(tmp_path, "a.png"), "prompt=TEST PROMPT",
                     "width=", "height="])
    assert "画布尺寸" in str(ei.value)


def test_numeric_garbage_raises_plan_error(tmp_path):
    """steps/length/fps 非数字必须是可读 PlanError，不许漏成裸 ValueError traceback。"""
    png = _img(tmp_path, "a.png")
    for bad in ("steps=abc", "length=abc", "fps=xx"):
        with pytest.raises(run_plan.PlanError) as ei:
            _bleed_plan(_wf("h3_i2va_video"), "h3_i2va_video",
                        [f"ref_images={png}"] + BASE + [bad])
        assert "不是数字" in str(ei.value), (bad, str(ei.value))


def test_20_steps_with_lora_rejected(tmp_path):
    """20 步是干净配方（不挂 LoRA）；挂了 LoRA 属已知错配。"""
    png = _img(tmp_path, "a.png")
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(_wf("h3_i2va_video"), "h3_i2va_video",
                    [f"ref_images={png}"] + BASE + ["steps=20"])
    assert "20" in str(ei.value) and "lora" in str(ei.value).lower(), str(ei.value)


def test_pending_wiring_mode_refuses(tmp_path):
    """L2VA 在 registry 里是 pending_wiring：选了也要说清"待接入"，不许假装能跑。"""
    wf = {"name": "probe", "steps": [{"task": "video", "id": "v",
                                      "workflow": "comfy/h3_i2v_fl2va_api.json"}]}
    with pytest.raises(run_plan.PlanError) as ei:
        _bleed_plan(wf, "probe", ["input_mode=l2va",
                                  "ref_images=" + _img(tmp_path, "a.png")] + BASE)
    assert "last_frame" in str(ei.value) or "待接入" in str(ei.value), str(ei.value)


# ------------------------------------------------------------------ V1-4
def test_mode_switch_diff_is_bounded(tmp_path):
    a = _img(tmp_path, "a.png")
    b = _img(tmp_path, "b.png")
    # 配方/几何在两侧显式给同一组值（合成 wf 没有 YAML 默认值），
    # 这样差异只可能来自"模式"本身。
    same = ["steps=8", "lora=minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
            "lora_strength=0.7", "head_chunks=4"]
    p_i2va = _bleed_plan(_wf("h3_i2va_video"), "h3_i2va_video",
                         [f"ref_images={a}"] + BASE + same)
    p_fl2va = _bleed_plan(_dual_wf(), "h3_fl2va_probe",
                          [f"ref_images={a},{b}"] + BASE + same)
    diff = _diff_paths(p_i2va, p_fl2va)
    strays = {d for d in diff if not d.startswith(MODE_ONLY_PREFIXES)}
    assert not strays, f"仅切模式却改动了约定范围外的字段：{sorted(strays)}"
    # 几何/声音必须完全一致；配方除"格子"外必须完全一致
    # （matrix 由 模式 × 配方 决定；编排两字段随"这条流有没有登记"变 ——
    #   合成探针流没登记 ⇒ 如实报 unregistered，这正是 W4b 要的"查表不猜名字"）
    for grp in ("geometry", "sound"):
        assert p_i2va[grp] == p_fl2va[grp], grp
    ignore = {"orchestration", "orchestration_basis"}
    f1 = {k: v for k, v in p_i2va["flow"].items() if k not in ignore}
    f2 = {k: v for k, v in p_fl2va["flow"].items() if k not in ignore}
    assert f1 == f2, "flow"
    assert p_i2va["flow"]["orchestration"] == "single", p_i2va["flow"]
    assert p_fl2va["flow"]["orchestration"] == "unregistered", p_fl2va["flow"]
    r1 = {k: v for k, v in p_i2va["recipe"].items() if k != "matrix"}
    r2 = {k: v for k, v in p_fl2va["recipe"].items() if k != "matrix"}
    assert r1 == r2, "recipe"
    for m in (p_i2va["recipe"]["matrix"], p_fl2va["recipe"]["matrix"]):
        assert m["state"] == "available", m
    # 配方一族：steps/lora/强度逐项相同（模式切换不带配方漂移）
    for k in ("steps", "lora", "lora_strength", "recipe_id", "pairing"):
        assert p_i2va["recipe"][k] == p_fl2va["recipe"][k], k


# ------------------------------------------------------------------ V1-1/3 入口
def test_inspect_cli_parses_and_submits_nothing(tmp_path):
    """--inspect 真跑 run.py：只解析不提交，不建批次夹、不写状态。"""
    img = _img(tmp_path, "a.png")
    prompt = tmp_path / "p.txt"
    prompt.write_text("TEST PROMPT", encoding="utf-8")
    cfg = yaml.safe_load(Path(os.environ["AW_CONFIG_PATH"]).read_text(encoding="utf8"))
    status = Path(cfg["status_file"])
    out_root = Path(cfg["output_root"])
    before_status = status.read_text(encoding="utf8") if status.exists() else None
    before_dirs = {p.name for p in out_root.iterdir()} if out_root.exists() else set()

    r = subprocess.run(
        [sys.executable, "run.py", "h3_i2va_video", "--inspect",
         "--set", f"ref_images={img}", "--set", f"prompt_file={prompt}"],
        cwd=str(ENGINE), capture_output=True, text=True, encoding="utf8",
        errors="replace", timeout=120)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    assert "--- run_plan ---" in r.stdout
    plan = json.loads(r.stdout.split("--- run_plan ---", 1)[1])
    assert plan["schema_version"] == "1"
    assert plan["inputs"]["input_mode"] == "i2va"
    assert plan["execution"]["prompt_id"] is None and plan["execution"]["submit_intent"] is None

    after_status = status.read_text(encoding="utf8") if status.exists() else None
    assert after_status == before_status, " --inspect 不该写 status"
    after_dirs = {p.name for p in out_root.iterdir()} if out_root.exists() else set()
    assert after_dirs == before_dirs, f"--inspect 不该建批次夹：{after_dirs - before_dirs}"


def test_inspect_cli_reports_readable_error(tmp_path):
    r = subprocess.run(
        [sys.executable, "run.py", "h3_i2va_video", "--inspect",
         "--set", f"ref_images={_img(tmp_path, 'a.png')}"],
        cwd=str(ENGINE), capture_output=True, text=True, encoding="utf8",
        errors="replace", timeout=120)
    # 该工作流 prompt 默认为空 ⇒ 必须在提交前报"提示词为空"
    assert r.returncode == 2, r.stdout[-400:]
    assert "提示词为空" in r.stderr, r.stderr[-400:]
