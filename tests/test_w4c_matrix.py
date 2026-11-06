# -*- coding: utf-8 -*-
"""W4c 验收（V4c-1/V4c-2/V4c-3）：Ref2VA 官方 9/3/3/12 ＋ 全模式 × 配方矩阵。

V4c-1 9图/3视频/3音频可挂；10图/4视频/4音频/13文件/超 15s/音频单独 ⇒ 全拦
V4c-2 五模式标准配方都有真实模板；need_graph 格停在提交前并说清缺哪张图
V4c-3 每格 CLI/面板参数一致（同一 registry 派生）；R4 不出现在本批
"""
import collections
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
TOOLS = ENGINE.parent / "tools"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TOOLS))

import run_plan                       # noqa: E402
import tasks as T                      # noqa: E402
from check_preflight import run_checks  # noqa: E402

R9_TPL = "comfy/h3_i2v_ref2va9_api.json"
MODES_TPL = "comfy/h3_two_pass_modes_api.json"
R3_LORA = "minimax_h3_fl2v_turbo_4step_v0.1_comfyui_alpha8-T8-convert.safetensors"


def _tpl(rel):
    return json.loads((ENGINE / rel).read_text(encoding="utf-8"))


def _host(graph):
    return [n for n in graph.values()
            if str(n.get("class_type") or "") == "MiniMaxH3ReferenceToVideo"]


def _wire_images(n, tpl=R9_TPL):
    mats = {"images": [f"img{i}.png" for i in range(n)], "videos": [],
            "video_audios": [], "audios": []}
    return T.build_graph_video(_tpl(tpl), {"prompt": "P", "width": 736, "height": 416,
                                           "length": 124, "steps": 4,
                                           "lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
                                           "input_mode": "ref2va"}, 42,
                               extra_rep={}, ref_materials=mats)


# ------------------------------------------------------------------ V4c-1 建图
@pytest.mark.parametrize("n", [0, 1, 4, 9])
def test_ref2va_images_wire_exactly_n_slots(n):
    g = _wire_images(n)
    hosts = _host(g)
    assert hosts, "9 图模板必须有 ReferenceToVideo 节点"
    ins = hosts[0]["inputs"]
    keys = sorted(k for k in ins if str(k).startswith("ref_images."))
    assert len(keys) == n, (n, keys)
    assert len({k for k in g if g[k].get("class_type") == "LoadImage"}) == n, g

def test_full_9_3_3_graph_is_consistent():
    """9 图＋3 参考视频＋3 段视频原声 = 12 个上传文件（原声随视频同文件，不另算一份）。"""
    mats = {"images": [f"i{k}.png" for k in range(9)],
            "videos": [f"v{k}.mp4" for k in range(3)],
            "video_audios": [f"va{k}.wav" for k in range(3)],
            "audios": []}
    g = T.build_graph_video(_tpl(R9_TPL), {"prompt": "P", "width": 736, "height": 416,
                                           "length": 124, "input_mode": "ref2va"}, 42,
                            extra_rep={}, ref_materials=mats)
    ins = _host(g)[0]["inputs"]
    assert sum(1 for k in ins if k.startswith("ref_images.")) == 9
    assert sum(1 for k in ins if k.startswith("ref_videos.")) == 3
    assert sum(1 for k in ins if k.startswith("ref_video_audios.")) == 3
    assert not [k for k in ins if k.startswith("ref_audios.")]
    # 参考视频与它的原声必须共用同一个 GetVideoComponents（帧与声对得上号）
    vids = [ins[f"ref_videos.ref_video_{k}"][0] for k in range(3)]
    auds = [ins[f"ref_video_audios.ref_video_audio_{k}"][0] for k in range(3)]
    assert vids == auds, "视频原声取了另一段视频的声"
    assert all(g[vid]["class_type"] == "GetVideoComponents" for vid in vids)
    assert "__REF" not in json.dumps(g, ensure_ascii=False), "还有没填掉的占位符"


def test_standalone_audio_beyond_total_files_rejected():
    """9图＋3视频＝12 已占满 ⇒ 再加一段独立音频必须拦（额度算文件数）。"""
    mats = {"images": [f"i{k}.png" for k in range(9)],
            "videos": [f"v{k}.mp4" for k in range(3)],
            "video_audios": [], "audios": ["a.wav"]}
    with pytest.raises(ValueError) as ei:
        T.build_graph_video(_tpl(R9_TPL), {"prompt": "P", "width": 736, "height": 416,
                                           "length": 124, "input_mode": "ref2va"}, 42,
                            extra_rep={}, ref_materials=mats)
    assert "总文件 13" in str(ei.value), str(ei.value)


@pytest.mark.parametrize("mats,frag", [
    ({"images": [f"i{k}.png" for k in range(10)]}, "图 10 个 > 官方上限 9"),
    ({"videos": [f"v{k}.mp4" for k in range(4)], "images": ["i.png"]}, "视频 4 个 > 官方上限 3"),
    ({"images": ["i.png"], "videos": ["v.mp4"], "audios": ["a1.wav", "a2.wav", "a3.wav",
                                                           "a4.wav"]}, "独立音频 4 个 > 官方上限 3"),
    ({"images": [f"i{k}.png" for k in range(9)],
      "videos": ["v0.mp4", "v1.mp4", "v2.mp4"], "audios": ["a.wav"]},
     "总文件 13 > 官方上限 12"),
    ({"audios": ["a.wav"]}, "音频不能作为唯一输入"),
    ({"video_audios": ["va.wav"]}, "音频不能作为唯一输入"),
    ({"images": ["i.png"], "videos": ["v.mp4"], "video_audios": ["va0.wav", "va1.wav"]},
     "没有对应的第 2 段参考视频"),
])
def test_over_capacity_and_illegal_combos_fail_before_build(mats, frag):
    full = {"images": [], "videos": [], "video_audios": [], "audios": []}
    full.update(mats)
    with pytest.raises(ValueError) as ei:
        T.build_graph_video(_tpl(R9_TPL), {"prompt": "P", "width": 736, "height": 416,
                                           "length": 124, "input_mode": "ref2va"}, 42,
                            extra_rep={}, ref_materials=full)
    assert frag in str(ei.value), str(ei.value)


# ------------------------------------------------------------------ V4c-1 G4
def _write_wav(path, seconds):
    import numpy as np
    import soundfile as sf
    sr = 32000
    n = int(sr * seconds)
    data = (0.1 * np.sin(2 * 3.14159 * 220 * np.arange(n) / sr)).astype("float32")
    sf.write(str(path), data, sr)


def _write_mp4(path, seconds):
    """G4 会用 cv2 数参考视频的帧；假的 .mp4 字节会被读成 -1 帧，所以写真短片。"""
    import cv2
    import numpy as np
    fps, n = 24, max(2, int(round(seconds * 24)))
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (96, 96))
    assert vw.isOpened()
    for _ in range(n):
        vw.write(np.full((96, 96, 3), 60, np.uint8))
    vw.release()


def _spec(tmp_path, images=(), videos=(), vaudios=(), audios=()):
    def mk(names, kind):
        out = []
        for i, nm in enumerate(names):
            p = tmp_path / f"{nm}_{i}{kind}"
            if kind == ".wav":
                _write_wav(p, float(nm))      # 调用方用秒数当名字（"3"／"20"）
            elif kind == ".mp4":
                _write_mp4(p, float(nm))
            else:
                p.write_bytes(b"\x89PNG\r\n")
            out.append(str(p))
        return out
    return {"prompt": "x", "prompt_kind": "h3_ref2va", "input_mode": "ref2va",
            "refs": mk([str(x) for x in images], ".png"),
            "ref_videos": mk([str(x) for x in videos], ".mp4"),
            "ref_video_audios": mk([str(x) for x in vaudios], ".wav"),
            "ref_audios": mk([str(x) for x in audios], ".wav"),
            "w": 736, "h": 416, "length": 124, "provider": "local", "only": ["G4"],
            "workflow_json": str(ENGINE / R9_TPL),
            "output_root": str(tmp_path), "project": "无音",
            "project_aliases": {"无音": ["无音"]}}


def test_g4_allows_nine_images_on_dynamic_template(tmp_path):
    rep = run_checks(_spec(tmp_path, images=[f"a{i}" for i in range(9)],
                           videos=["2", "3"], vaudios=["2", "3"]))
    assert not [g for _lv, g, _m in rep.errors], rep.render()


def test_g4_does_not_apply_static_slot_count_to_dynamic_template(tmp_path):
    """9 图版没有固定槽：3 张也必须过（此前静态模板会误报"少挂 1 张"）。"""
    rep = run_checks(_spec(tmp_path, images=["a", "b", "c"]))
    assert not any("槽" in m for _lv, _g, m in rep.errors), rep.render()


def test_g4_rejects_over_capacity(tmp_path):
    rep = run_checks(_spec(tmp_path, images=[f"a{i}" for i in range(10)]))
    assert any(g == "G4" and "9" in m for _lv, g, m in rep.errors), rep.render()
    rep2 = run_checks(_spec(tmp_path, images=[f"a{i}" for i in range(9)],
                            videos=["3", "3", "3"], vaudios=["3"], audios=["3"]))
    assert any(g == "G4" and "13" in m for _lv, g, m in rep2.errors), rep2.render()


def test_g4_rejects_audio_only(tmp_path):
    rep = run_checks(_spec(tmp_path, audios=["3"]))
    assert any(g == "G4" and "单独" in m for _lv, g, m in rep.errors), rep.render()


def test_g4_checks_audio_segment_duration(tmp_path):
    """每段参考音频 2–15s：20 秒必须拦，3 秒放行。"""
    rep = run_checks(_spec(tmp_path, images=["a"], audios=["20"]))
    assert any(g == "G4" and "2–15s" in m for _lv, g, m in rep.errors), rep.render()
    rep_ok = run_checks(_spec(tmp_path, images=["a"], audios=["3"]))
    assert not [e for e in rep_ok.errors], rep_ok.render()


def test_g4_checks_audio_total(tmp_path):
    rep = run_checks(_spec(tmp_path, images=["a"], audios=["8", "8"]))
    assert any(g == "G4" and "音频合计" in m for _lv, g, m in rep.errors), rep.render()


# ------------------------------------------------------------------ R3 全模式图
def _build_modes(mode, images=(), videos=(), vaudios=(), audios=(), extra=None):
    p = {"prompt": "P", "width": 736, "height": 416, "length": 124, "steps": 8,
         "lora": R3_LORA, "lora_strength": 1.0, "head_chunks": 4,
         "input_mode": mode, "two_pass": True, "scale_by": 1.25}
    p.update(extra or {})
    rep_extra = {f"__REF{i + 1}__": f"r{i}.png" for i in range(len(images))}
    mats = None
    if mode == "ref2va" or videos or vaudios or audios:
        mats = {"images": [rep_extra[f"__REF{i + 1}__"] for i in range(len(images))],
                "videos": [f"v{k}.mp4" for k in range(len(videos))],
                "video_audios": [f"va{k}.wav" for k in range(len(vaudios))],
                "audios": [f"a{k}.wav" for k in range(len(audios))]}
    return T.build_graph_video(_tpl(MODES_TPL), p, 42, extra_rep=rep_extra,
                              ref_materials=mats)


def _cond_nodes(g):
    return [n for n in g.values()
            if str(n.get("class_type") or "") == "MiniMaxH3AudioConditioningT8"]


@pytest.mark.parametrize("mode,imgs,tt,slots", [
    ("t2va", [], "T2VA", set()),
    ("i2va", ["a"], "I2VA", {"first_frame"}),
    ("l2va", ["a"], "L2VA", {"last_frame"}),
    ("fl2va", ["a", "b"], "FL2VA", {"first_frame", "last_frame"}),
])
def test_two_pass_modes_template_covers_all_keyframe_modes(mode, imgs, tt, slots):
    g = _build_modes(mode, images=imgs)
    conds = _cond_nodes(g)
    assert len(conds) == 2, "二采两遍条件化都要带帧"
    for c in conds:
        assert c["inputs"]["task_type"] == tt, (mode, c["inputs"]["task_type"])
        present = {k for k in ("first_frame", "last_frame") if k in c["inputs"]}
        assert present == slots, (mode, present)
    assert not any(isinstance(v, list) and str(v[0]) not in g
                   for c in conds for v in c["inputs"].values()
                   if isinstance(v, list)), "帧槽指向了被删掉的节点"
    assert "__TASK_TYPE__" not in json.dumps(g, ensure_ascii=False)


def test_two_pass_modes_ref2va_wires_refs_on_both_passes():
    g = _build_modes("ref2va", images=["a", "b"], videos=["v"], vaudios=["va"])
    conds = _cond_nodes(g)
    assert len(conds) == 2
    for c in conds:
        assert c["inputs"]["task_type"] == "Ref2VA"
        assert sum(1 for k in c["inputs"] if str(k).startswith("ref_images.")) == 2
        assert sum(1 for k in c["inputs"] if str(k).startswith("ref_videos.")) == 1
        assert sum(1 for k in c["inputs"] if str(k).startswith("ref_video_audios.")) == 1
        assert "first_frame" not in c["inputs"], "Ref2VA 不该再挂首帧槽"
    # 两遍共用同一批加载节点，不重复建
    assert sum(1 for n in g.values() if n.get("class_type") == "LoadImage") == 2


def test_two_pass_modes_fl2va_creates_missing_tail_loader():
    g = _build_modes("fl2va", images=["a", "b"])
    loads = [n["inputs"]["image"] for n in g.values() if n.get("class_type") == "LoadImage"]
    assert sorted(loads) == ["r0.png", "r1.png"], loads


@pytest.mark.parametrize("mode,imgs", [("i2va", []), ("fl2va", ["a"]), ("l2va", ["a", "b"]),
                                       ("t2va", ["a"])])
def test_wrong_image_count_still_fails_on_modes_template(mode, imgs):
    with pytest.raises(ValueError):
        _build_modes(mode, images=imgs)


# ------------------------------------------------------------------ V4c-2/3 矩阵
def _matrix():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    return reg["recipe_matrix"]


def test_matrix_covers_every_mode_and_recipe():
    m = _matrix()
    modes, recipes = m["axes"]["modes"], m["axes"]["recipes"]
    assert sorted(modes) == ["fl2va", "i2va", "l2va", "ref2va", "t2va"]
    assert "r4_pdd" not in " ".join(recipes), "R4 不进本批（B2 裁定）"
    for mode in modes:
        assert set(m["cells"][mode]) == set(recipes), mode
        for key, cell in m["cells"][mode].items():
            assert cell["state"] in ("available", "need_graph", "not_applicable"), (mode, key)
            if cell["state"] == "available":
                assert (ENGINE / cell["template"]).is_file(), (mode, key, cell["template"])
                assert (ENGINE / "workflows" / f"{cell['workflow']}.yaml").is_file(), cell
            else:
                assert cell.get("reason"), (mode, key, "need_graph 必须写清缺什么")


def test_need_graph_cell_refuses_before_submit(tmp_path):
    """need_graph 这条拦人分支**本身**要有覆盖——真格子已被用户裁定建成 available 了（10-24 08:15）。

    所以这里不借真数据，而是在临时 engine 里种一个 need_graph 格子：
    将来谁把某格改回 need_graph，正向那条测试会红；这里保证"改了也不会静默提交"。
    """
    import shutil
    fake = tmp_path / "engine"
    (fake / "comfy").mkdir(parents=True)
    (fake / "workflows").mkdir()
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    cell = reg["recipe_matrix"]["cells"]["t2va"]["clean20"]
    cell.clear()
    cell.update({"state": "need_graph", "reason": "种进去的假格子：要一张不挂 LoRA 且首尾帧可选的 nolora 图"})
    (fake / "channels_registry.json").write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(run_plan.PlanError) as ei:
        run_plan.matrix_cell(fake, "t2va", {"lora": "", "steps": 20})
    assert "需要新建图" in str(ei.value) and "nolora" in str(ei.value), str(ei.value)


def test_three_formerly_missing_cells_are_now_available():
    """用户 10-24 08:15 裁定「三格都建」⇒ 这三格必须 available，且模板与流都真在盘上。"""
    for mode, tpl, wf in (
            ("t2va", "comfy/h3_keyframes_optional_nolora_api.json", "h3_keyframe_modes_clean"),
            ("l2va", "comfy/h3_keyframes_optional_nolora_api.json", "h3_keyframe_modes_clean"),
            ("ref2va", "comfy/h3_i2v_ref2va9_nolora_api.json", "h3_ref2va9_clean")):
        cell = run_plan.matrix_cell(ENGINE, mode, {"lora": "", "steps": 20})
        assert cell["state"] == "available", (mode, cell)
        assert cell["template"] == tpl, (mode, cell)
        assert cell["workflow"] == wf, (mode, cell)
        assert (ENGINE / tpl).is_file() and (ENGINE / "workflows" / (wf + ".yaml")).is_file()
    # 矩阵里不该再有 need_graph（有就表示有人把建好的图又退回去了）
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    states = [c.get("state") for row in reg["recipe_matrix"]["cells"].values() for c in row.values()]
    assert "need_graph" not in states, collections.Counter(states)
    assert collections.Counter(states)["available"] == 16, collections.Counter(states)


def test_clean20_templates_really_have_no_lora_node_and_build(tmp_path):
    """nolora 图必须**真的**没有 LoraLoaderModelOnly（传空 lora 会被 ComfyUI 判无效 LoRA 名），
    而且三格都能建出无残留占位符的提交图。"""
    for tpl in ("comfy/h3_keyframes_optional_nolora_api.json", "comfy/h3_i2v_ref2va9_nolora_api.json"):
        g = json.loads((ENGINE / tpl).read_text(encoding="utf-8"))
        assert not [n for n in g.values() if n.get("class_type") == "LoraLoaderModelOnly"], tpl
        assert "__LORA__" not in json.dumps(g, ensure_ascii=False), tpl
        assert g["4"]["inputs"]["model"] == ["2", 0], tpl          # UNETLoader 直连 Attention
    tpl = json.loads((ENGINE / "comfy/h3_keyframes_optional_nolora_api.json").read_text(encoding="utf-8"))
    par = {"prompt": "P", "width": 736, "height": 416, "length": 107,
           "lora": "", "steps": 20, "lora_strength": 1.0, "head_chunks": 4}
    for mode, names in (("t2va", []), ("i2va", ["first.png"]),
                        ("l2va", ["last.png"]), ("fl2va", ["first.png", "last.png"])):
        # 帧槽张数由 __REFi__ 占位符个数决定（W1c 的口径），所以这里给的就是张数
        extra = {"__REF%d__" % i: n for i, n in enumerate(names, 1)}
        g2 = T.build_graph_video(tpl, dict(par), 42, extra_rep=extra, input_mode=mode)
        s = json.dumps(g2, ensure_ascii=False)
        assert "__" not in s, (mode, sorted(k for k in ("__LORA__", "__REF1__", "__REF2__",
                                                       "__STEPS__", "__LEN__") if k in s))
        assert "LoraLoaderModelOnly" not in s, mode
        host = [n for n in g2.values()
                if n.get("class_type") == "MiniMaxH3ImageToVideo"][0]["inputs"]
        assert ("first_frame" in host) == (mode in ("i2va", "fl2va")), (mode, list(host))
        assert ("last_frame" in host) == (mode in ("l2va", "fl2va")), (mode, list(host))
        assert sum(1 for n in g2.values()
                   if n.get("class_type") == "LoadImage") == len(names), mode
    # Ref2VA 干净档：素材注入也要成立
    tpl9 = json.loads((ENGINE / "comfy/h3_i2v_ref2va9_nolora_api.json").read_text(encoding="utf-8"))
    g3 = T.build_graph_video(tpl9, {"prompt": "P", "width": 736, "height": 416, "length": 124,
                                    "input_mode": "ref2va", "lora": "", "steps": 20}, 42,
                             extra_rep={},
                             ref_materials={"images": ["i.png"], "videos": ["v.mp4"],
                                            "video_audios": ["va.wav"], "audios": ["a.wav"]})
    ins = [n for n in g3.values() if n.get("class_type") == "MiniMaxH3ReferenceToVideo"][0]["inputs"]
    assert sum(1 for k in ins if k.startswith("ref_images.")) == 1
    assert sum(1 for k in ins if k.startswith("ref_audios.")) == 1
    assert "LoraLoaderModelOnly" not in json.dumps(g3, ensure_ascii=False)


def test_not_applicable_cell_refuses(tmp_path):
    with pytest.raises(run_plan.PlanError) as ei:
        run_plan.matrix_cell(ENGINE, "i2va",
                             {"lora": "minimax_h3_ref2v_turbo_4step.safetensors", "steps": 4})
    assert "不该存在的格子" in str(ei.value), str(ei.value)


def test_available_cell_names_real_files_and_matches_flow():
    cell = run_plan.matrix_cell(ENGINE, "ref2va",
                                {"lora": "minimax_h3_ref2v_turbo_4step.safetensors",
                                 "steps": 4})
    assert cell["state"] == "available" and cell["template"] == R9_TPL
    import yaml
    wf = yaml.safe_load((ENGINE / "workflows" / "h3_ref2va9_daily.yaml").read_text(encoding="utf-8"))
    assert run_plan.find_template(wf) == cell["template"], "registry 说的模板要和流里真用的一致"


def test_matrix_plan_inspect_l2va_two_pass(tmp_path):
    """同一格从 CLI 解析出来的模板＝registry 派的格，二者不许各说一套。"""
    import yaml
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n")
    wf = yaml.safe_load((ENGINE / "workflows" / "h3_two_pass_modes.yaml")
                        .read_text(encoding="utf-8"))
    sets = ["input_mode=l2va", f"ref_images={png}", "prompt=TEST PROMPT",
            "width=736", "height=416", "length=124", "steps=8", f"lora={R3_LORA}",
            "lora_strength=1.0", "two_pass=true", "two_pass_coarse_steps=4",
            "two_pass_refine_steps=4", "scale_by=1.25"]
    cli = run_plan.parse_sets(sets)
    args, sources = run_plan.merge_args(wf.get("args") or {}, {}, cli)
    plan = run_plan.build_run_plan(ENGINE, "h3_two_pass_modes", wf, args, sources,
                                   cfg={"project": "无音"}, tier="draft")
    assert plan["inputs"]["input_mode"] == "l2va"
    assert plan["recipe"]["matrix"]["state"] == "available"
    assert plan["recipe"]["matrix"]["template"] == plan["versions"]["template"]["path"]
    assert "格子   available" in run_plan.render_summary(plan)
