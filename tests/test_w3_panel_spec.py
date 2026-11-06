# -*- coding: utf-8 -*-
"""W3 验收（V3-1/V3-3）：面板控件全部由 registry 派生，与 CLI 同一份 RunPlan。

V3-1 面板"先看计划"与命令行 --inspect 得到同一份计划（同一构造器＋同一解析器）
V3-3 模式/配方页签可选；不可提交的格子在面板上就禁选，不出现"点了才炸"
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
PANEL = Path(r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\custom_nodes\comfyui-entertainment-panel")
sys.path.insert(0, str(ENGINE))

spec = importlib.util.spec_from_file_location("ep", str(PANEL / "__init__.py"))
EP = importlib.util.module_from_spec(spec)
sys.modules["ep"] = EP
spec.loader.exec_module(EP)          # 拿不到 PromptServer 时 register() 会安静跳过

import run_plan                       # noqa: E402


def _wf(name):
    return yaml.safe_load((ENGINE / "workflows" / f"{name}.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 单一真源
def test_panel_has_no_second_mode_table():
    src = (PANEL / "__init__.py").read_text(encoding="utf-8")
    for dead in ("图生视频·锁首帧", "跑着玩·两头夹", "跑着玩·干净档"):
        assert dead not in src, f"面板里还留着硬编码模式表：{dead}"
    assert "MODES.get(mode)" not in src


def test_frontend_does_not_hardcode_modes():
    html = (PANEL / "web" / "index.html").read_text(encoding="utf-8")
    assert "/entertainment/spec" in html, "前端必须拉派生 spec，而不是自带表"
    for dead in ("图生视频·锁首帧", "两头夹", "干净档"):
        assert dead not in html, f"前端写死了模式标签：{dead}"


def test_spec_mirrors_registry():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    s = EP.build_spec()
    assert [m["key"] for m in s["modes"]] == reg["panel"]["mode_tabs"]
    assert [r["key"] for r in s["recipes"]] == reg["panel"]["recipe_tabs"]
    assert s["caps"] == reg["panel"]["material_caps"]
    assert s["frames"] == reg["panel"]["frames_options"] == [107, 124, 192, 243, 345]
    assert s["compile_required"] is True and s["project_readonly"] is True
    assert s["project"], "项目要能从引擎 config 读出来（只读显示，不是面板自己定）"
    for m, row in s["cells"].items():
        for r, st in row.items():
            assert st == ((reg["recipe_matrix"]["cells"].get(m, {}).get(r) or {})
                          .get("state") or "unregistered"), (m, r, st)


# ------------------------------------------------------------------ 格子门禁
def test_available_cell_resolves_to_real_flow():
    wf, why = EP.resolve_workflow("l2va", "single8")
    assert why is None and wf == "h3_keyframe_modes", (wf, why)
    assert (ENGINE / "workflows" / f"{wf}.yaml").is_file()


@pytest.mark.parametrize("mode,recipe,frag", [
    ("i2va", "ref2v4", "not_applicable"),
    ("nope", "single8", "unregistered"),
])
def test_bad_cell_refuses_with_readable_reason(mode, recipe, frag):
    wf, why = EP.resolve_workflow(mode, recipe)
    assert wf is None and frag in why, (mode, recipe, why)


def _planted_registry(tmp_path, monkeypatch, mode, recipe, **cell):
    """把某一格改成指定状态，种在临时 registry 里（真数据一个字不动）。

    10-24 08:15 用户裁定「三格都建」之后，真 registry 里已经没有 need_graph 格；
    但这条**禁选/不起进程**的分支仍要天天被验，所以种临时表——
    而不是为了有靶子可打，故意把某格留在 need_graph 上。
    """
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    target = reg["recipe_matrix"]["cells"][mode][recipe]
    target.clear()
    target.update(cell)
    f = tmp_path / "channels_registry.json"
    f.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(EP, "REGISTRY_PATH", str(f))


def test_need_graph_branch_still_guarded_though_no_real_cell_is_missing(tmp_path, monkeypatch):
    wf, why = EP.resolve_workflow("t2va", "clean20")
    assert wf and why is None, (wf, why)              # 真表里这格已建成
    _planted_registry(tmp_path, monkeypatch, "t2va", "clean20",
                      state="need_graph", reason="种进去的假格子：缺一张 nolora 可选首尾帧图")
    wf2, why2 = EP.resolve_workflow("t2va", "clean20")
    assert wf2 is None and "need_graph" in why2, why2


def test_spawn_never_launches_for_unusable_cell(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("不可提交的格子不许起进程")
    monkeypatch.setattr(EP.subprocess, "Popen", boom)
    _planted_registry(tmp_path, monkeypatch, "l2va", "clean20",
                      state="need_graph", reason="同 t2va：需要 nolora 图（为验证分支而种）")
    rid, err = EP._spawn("l2va", "clean20", "", {})
    assert rid is None and "need_graph" in err, err


# ------------------------------------------------------------------ clean20 三格（10-24 建图）
def test_clean20_three_new_cells_resolve_to_real_flows():
    for mode, flow in (("t2va", "h3_keyframe_modes_clean"),
                       ("l2va", "h3_keyframe_modes_clean"),
                       ("ref2va", "h3_ref2va9_clean")):
        wf, why = EP.resolve_workflow(mode, "clean20")
        assert why is None and wf == flow, (mode, wf, why)
        d = _wf(flow)
        gen = [s for s in d["steps"] if s.get("id") == "gen"][0]
        assert gen["workflow"].endswith("nolora_api.json"), gen["workflow"]
        assert d["args"]["steps"] == 20 and d["args"]["lora"] == "", d["args"]
        # gen 的步数必须引用 args：写死成数字等于 --set steps=… 静默失效
        assert gen["steps"] == "{{args.steps}}", gen["steps"]


def test_panel_spec_exposes_audio_reading_mode():
    """监督方 10-24 终局那条：读法不许只活在注释里——面板 spec 要把它带下来。"""
    ar = EP.build_spec().get("audio_reading") or {}
    assert ar.get("reading") in ("node_per_kind_max3", "official_one_class_max3"), ar
    assert ar.get("switch") == "AW_H3_AUDIO_STRICT", ar
    html = (PANEL / "web" / "index.html").read_text(encoding="utf-8")
    assert "audioBadge" in html and "s.audio_reading" in html, "前端没把读法显示出来"


# ------------------------------------------------------------------ 素材上限
def test_build_sets_maps_materials_and_respects_caps():
    sets = EP.build_sets("ref2va", "r3_two_pass", "p.txt",
                         {"ref_images": ["a.png", "b.png"], "ref_videos": ["v.mp4"],
                          "ref_audios": []}, length=192)
    assert "input_mode=ref2va" in sets and "prompt_file=p.txt" in sets
    assert "ref_images=a.png,b.png" in sets and "ref_videos=v.mp4" in sets
    assert "two_pass=true" in sets and "length=192" in sets
    with pytest.raises(ValueError):
        EP.build_sets("ref2va", "single8", "", {"ref_images": ["x"] * 10})


# ------------------------------------------------------------------ S3 接线
def test_spec_exposes_geometry_defaults():
    gd = EP.build_spec().get("geometry_defaults") or {}
    assert gd.get("width") == 736 and gd.get("height") == 416, gd


def test_build_sets_carries_all_materials_and_geometry():
    sets = EP.build_sets("ref2va", "r3_two_pass", "p.txt",
                         {"ref_images": ["a.png"], "ref_videos": ["v.mp4"],
                          "ref_video_audios": ["va.wav"], "ref_audios": ["au.wav"]},
                         length=124, width=576, height=1024)
    for want in ("ref_images=a.png", "ref_videos=v.mp4",
                 "ref_video_audios=va.wav", "ref_audios=au.wav",
                 "length=124", "width=576", "height=1024", "two_pass=true"):
        assert want in sets, (want, sets)
    with pytest.raises(ValueError):
        EP.build_sets("ref2va", "single8", "", {"ref_videos": ["v"] * 4})


def test_orchestration_selection_is_enforced_not_decorative():
    assert EP.resolve_workflow("i2va", "single8", "batch")[0] == "h3_i2va_batch"
    assert EP.resolve_workflow("i2va", "single8", "review_pack")[0] == "h3_batch_review"
    wf, why = EP.resolve_workflow("fl2va", "single8", "review_pack")
    assert wf is None and "只接了" in why, (wf, why)
    wf, why = EP.resolve_workflow("i2va", "single8", "movie")
    assert wf is None and "manifest" in why, (wf, why)
    wf, why = EP.resolve_workflow("i2va", "single8", "relay")
    assert wf is None and "manifest" in why and "CLI" in why, (wf, why)
    assert EP.resolve_workflow("i2va", "single8", "single")[0] == "h3_keyframe_modes"


def test_relay_orchestration_is_wired_to_real_flow():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    relay = reg["orchestrations"]["values"]["relay"]
    assert relay["state"] == "available" and "h3_relay_movie" in relay["flows"], relay
    wf = _wf("h3_relay_movie")
    gen = [s for s in wf["steps"] if s.get("id") == "movie"][0]
    assert gen["task"] == "h3_movie", gen
    assert gen["relay_ctx"] == "{{args.relay_ctx}}", gen
    assert (ENGINE / "comfy" / "h3_relay_parent_api.json").is_file()
    assert (ENGINE / "comfy" / "h3_relay_cont_api.json").is_file()


def test_jobs_persist_across_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(EP, "JOBS_DIR", tmp_path / "jobs")
    EP.JOBS.clear()
    EP.JOBS["R1"] = {"status": "awaiting_human", "log": ["a", "b"],
                     "returncode": 3, "mode": "i2va", "workflow": "wf"}
    EP._save_job("R1")
    EP.JOBS.clear()
    EP._load_jobs()
    assert EP.JOBS["R1"]["status"] == "awaiting_human"
    assert EP.JOBS["R1"]["log"] == ["a", "b"]


def test_frontend_sends_tier_geometry_materials_and_restores_jobs():
    html = (PANEL / "web" / "index.html").read_text(encoding="utf-8")
    for token in ('id="width"', 'id="height"', 'id="refVideos"',
                  'id="refVideoAudios"', 'id="refAudios"', "ref_video_audios",
                  "orchestration:", "$('#tier').value", "updateRunLabel",
                  "restoreJobs", "/entertainment/jobs"):
        assert token in html, token
    src = (PANEL / "__init__.py").read_text(encoding="utf-8")
    assert '"--inspect", "--tier"' in src, "inspect 没把所选档位传给引擎"
    assert "resolve_workflow(mode, recipe, orchestration)" in src


# ------------------------------------------------------------------ V3-1 同计划
def test_panel_inspect_equals_cli_runplan(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n")
    pf = tmp_path / "p.txt"
    pf.write_text("For the target video, at 0.00 seconds into the target video, "
                  "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
                  "integrated_multimodal_description: [Shot 1] Live-action, a gate.\n\n"
                  "overall_soundscape: Wind.\n\nnon_diegetic_music: N/A", encoding="utf-8")
    sets = EP.build_sets("i2va", "single8", str(pf), {"ref_images": [str(png)]}, length=124)
    wf, why = EP.resolve_workflow("i2va", "single8")
    assert why is None
    r = subprocess.run([sys.executable, "-B", "run.py", wf, "--inspect"]
                       + sum([["--set", s] for s in sets], []),
                       cwd=str(ENGINE), capture_output=True, text=True,
                       encoding="utf8", errors="replace", timeout=180)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    panel_plan = json.loads(r.stdout.split("--- run_plan ---", 1)[1])

    # CLI 侧独立解析（不借道面板）：同一组 --set 必须解出同一份计划
    cli = run_plan.parse_sets(sets)
    wfy = _wf(wf)
    args, sources = run_plan.merge_args(wfy.get("args") or {}, {}, cli)
    cli_plan = run_plan.build_run_plan(ENGINE, wf, wfy, args, sources,
                                       cfg={"project": panel_plan["identity"]["project"]},
                                       tier="play")
    diff = {k for k in ("inputs", "recipe", "geometry", "text")
            if panel_plan[k] != cli_plan[k]}
    assert not diff, sorted(diff)
    assert panel_plan["inputs"]["input_mode"] == "i2va"
    assert panel_plan["recipe"]["matrix"]["state"] == "available"


# ------------------------------------------------------------------ 图片链（2026-10-26）
def test_spec_exposes_image_modes_from_registry():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    s = EP.build_spec()
    keys = [x["key"] for x in s.get("image_modes") or []]
    assert keys == ["image_t2i", "image_i2i"], keys
    for e in s["image_modes"]:
        assert e["kind"] == "image" and e["state"] == "available", e
        assert (ENGINE / "workflows" / f"{e['workflow']}.yaml").is_file(), e
        assert e["workflow"] in ("image_draft_batch", "image_i2i"), e
    assert s["image_modes"] == [dict({"key": k}, **v)
                                for k, v in reg["panel"]["extra_entries"].items()
                                if v.get("kind") == "image"]


def test_build_image_sets_t2i_maps_and_rejects_out_of_range():
    sets = EP.build_image_sets("image_t2i", {
        "prompt": "  白猫\n坐在窗台上  ", "count": 2,
        "width": 832, "height": 1216, "steps": 8})
    for want in ("prompt=白猫 坐在窗台上", "count=2", "width=832",
                 "height=1216", "steps=8", "use_llm_polish=false",
                 "resolution_tier=draft", "enable_audio=false"):
        assert want in sets, (want, sets)
    for bad in ({"prompt": ""}, {"prompt": "x", "count": 9},
                {"prompt": "x", "width": 830}, {"prompt": "x", "steps": 5},
                {"prompt": "x", "resolution_tier": "bogus"}):
        with pytest.raises(ValueError):
            EP.build_image_sets("image_t2i", bad)


def test_build_image_sets_i2i_requires_source_and_denoise_range(tmp_path):
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG\r\n")
    sets = EP.build_image_sets("image_i2i", {
        "prompt": "改成雨夜赛博朋克", "src_image": str(src),
        "denoise": 0.6, "width": 736, "height": 416, "steps": 8})
    for want in (f"src_image={src}", "prompt=改成雨夜赛博朋克",
                 "denoise=0.6", "width=736", "height=416", "steps=8",
                 "use_llm_polish=false", "resolution_tier=draft", "enable_audio=false"):
        assert want in sets, (want, sets)
    with pytest.raises(ValueError):
        EP.build_image_sets("image_i2i", {"prompt": "x", "src_image": str(src),
                                          "denoise": 0.9})
    with pytest.raises(ValueError):
        EP.build_image_sets("image_i2i", {"prompt": "x", "denoise": 0.6})


def test_spawn_image_never_launches_on_bad_input(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("图片参数不合法时不许起进程")
    monkeypatch.setattr(EP.subprocess, "Popen", boom)
    rid, err = EP._spawn_image("image_t2i", {"prompt": ""})
    assert rid is None and "提示词" in err, err
    rid, err = EP._spawn_image("nope", {"prompt": "x"})
    assert rid is None and "没登记" in err, err


def test_frontend_exposes_image_pane_and_uses_same_run_route():
    html = (PANEL / "web" / "index.html").read_text(encoding="utf-8")
    for token in ('id="imagePane"', 'id="imgPrompt"', 'id="imgSrc"',
                  'id="imgDenoise"', 'id="imgCount"', 'id="imgInspect"',
                  'id="imgRun"', 'id="imgResTier"', "imageBody", "kind: 'image'",
                  "resolution_tier", "enable_audio", "SPEC.image_modes",
                  "/entertainment/inspect", "/entertainment/run"):
        assert token in html, token
    src = (PANEL / "__init__.py").read_text(encoding="utf-8")
    assert "def _spawn_image" in src and "build_image_sets" in src
    assert 'ent["workflow"]' in src, "图片流应取 registry 的 workflow，不在面板里写死"


def test_upload_material_saves_under_root_and_rejects_bad_input(tmp_path):
    p = EP._save_material("image", "../../evil name.png", b"abc", root=tmp_path)
    assert p.is_file()
    assert "evil_name" in p.name and ".." not in str(p.relative_to(tmp_path))
    with pytest.raises(ValueError):
        EP._save_material("image", "x.exe", b"x", root=tmp_path)
    with pytest.raises(ValueError):
        EP._save_material("image", "x.png", b"", root=tmp_path)
    with pytest.raises(ValueError):
        EP._save_material("video", "x.mp4", b"1234", root=tmp_path, max_bytes=3)


def test_frontend_material_upload_controls_exist():
    html = (PANEL / "web" / "index.html").read_text(encoding="utf-8")
    for token in ('id="refFiles"', 'id="refUpload"', 'id="refList"',
                  'id="refVideoFiles"', 'id="refVideoUpload"',
                  'id="refAudioFiles"', 'id="refAudioUpload"',
                  'id="imgSrcFile"', 'id="imgSrcUpload"',
                  "/entertainment/upload-material", "uploadMaterial", "uploadImageSrc"):
        assert token in html, token
    src = (PANEL / "__init__.py").read_text(encoding="utf-8")
    assert '"/entertainment/upload-material"' in src
