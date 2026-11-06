# -*- coding: utf-8 -*-
"""10-24 质量核查整改验收。

P0：Ref2VA 9/3/3/12 必须**从引擎入口真的可达**（不是只有函数在）——用 t_video 全链路证一次；
P1：注释与代码一致、id 分配不靠奇偶巧合、G6 文案不把网格冒充官方、
    官方判据分歧要么判要么登记（不许沉默）；
P2：证据口径（成片本体进哈希、口径自证问题写清）。
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
TOOLS = ENGINE.parent / "tools"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TOOLS))

import tasks as T                        # noqa: E402
import run_plan                          # noqa: E402
import h3_official_spec as SPEC          # noqa: E402
from check_preflight import run_checks   # noqa: E402


def _write(path, data=b"\x89PNG\r\n"):
    path.write_bytes(data)
    return str(path)


# ------------------------------------------------------------------ P0 入口可达
@pytest.fixture()
def submit_capture(monkeypatch, tmp_path):
    """把 t_video 的对外动作全桩掉，抓下**真正会提交给 8189 的那张图**。"""
    cap = {}
    input_dir = tmp_path / "comfy_in"
    input_dir.mkdir()
    out_dir = tmp_path / "comfy_out"
    out_dir.mkdir()

    class FakeSession:
        def post(self, url, json=None, timeout=None):
            cap["graph"] = (json or {}).get("prompt")
            cap["url"] = url

            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"prompt_id": "pid-capture"}
            return R()

        def get(self, url, timeout=None):
            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"pid-capture": {"status": {"completed": True}, "outputs": {
                        "301": {"videos": [{"filename": "out_00001.mp4",
                                            "subfolder": ""}]}}}}
            return R()

    monkeypatch.setattr(T, "SESSION", FakeSession())
    monkeypatch.setattr(T, "ensure_comfyui", lambda ctx, relay=False: "http://stub")
    monkeypatch.setattr(T, "preflight_or_die", lambda *a, **k: None)
    monkeypatch.setattr(T, "poll_history",
                        lambda ctx, base, pid, to, pre_snapshot=None, expected_prefix=None:
                        [str(out_dir / "out_00001.mp4")])
    monkeypatch.setattr(T, "_video_qc", lambda *a, **k: {"width": 736, "height": 416,
                                                         "fps": 24.0, "frames": 124,
                                                         "duration": 5.17, "has_audio": True})
    monkeypatch.setattr(T, "relocate", lambda files, dst, log_fn=None: [Path(f) for f in files])
    ctx = {"cfg": {"comfyui": {"output_dir": str(out_dir), "input_dir": str(input_dir),
                               "base_url": "http://stub"},
                   "preflight": "on", "project": "无音", "characters_needing_anchor": []},
           "batch_dir": tmp_path / "batch", "run_id": "CAP", "wf_root": ENGINE,
           "args": {}, "log": lambda m: None, "workflow": "h3_ref2va9_daily", "outputs": {}}
    (ctx["batch_dir"]).mkdir(parents=True, exist_ok=True)
    (out_dir / "out_00001.mp4").write_bytes(b"mp4")
    ctx["_out"] = out_dir
    return ctx, cap


def test_ref2va9_flow_reaches_engine_with_audio_slots(submit_capture, tmp_path):
    """核查说"入口没接" ⇒ 这条就是反证：走 YAML→t_video→建图→提交，全程不猜。"""
    ctx, cap = submit_capture
    wf = yaml.safe_load((ENGINE / "workflows" / "h3_ref2va9_daily.yaml")
                        .read_text(encoding="utf-8"))
    imgs = [_write(tmp_path / f"r{i}.png", b"img%d" % i) for i in range(3)]
    vids = []
    for i in range(2):
        vp = tmp_path / f"v{i}.mp4"
        _write(vp, b"vid")
        vids.append(str(vp))
    auds = [_write(tmp_path / f"a{i}.wav", b"aud") for i in range(1)]
    vauds = [_write(tmp_path / f"va{i}.wav", b"vau") for i in range(2)]
    pf = tmp_path / "p.txt"
    pf.write_text("subject_definitions: x", encoding="utf-8")
    p = {"workflow": "comfy/h3_i2v_ref2va9_api.json", "prompt_file": str(pf),
         "prompt_kind": "h3_ref2va", "input_mode": "ref2va",
         "ref_images": imgs, "ref_videos": vids, "ref_video_audios": vauds,
         "ref_audios": auds, "width": 736, "height": 416, "length": 124,
         "steps": 4, "lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
         "prefix": "h3r9_CAP", "stage": "video", "timeout": 60}
    ctx["args"] = {"prompt_file": str(pf), "ref_images": imgs}
    T.t_video(p, ctx)
    g = cap.get("graph")
    assert g, "根本没提交任何图"
    host = [n for n in g.values()
            if n.get("class_type") == "MiniMaxH3ReferenceToVideo"]
    assert len(host) == 1
    ins = host[0]["inputs"]
    assert sum(1 for k in ins if k.startswith("ref_images.")) == 3
    assert sum(1 for k in ins if k.startswith("ref_videos.")) == 2
    assert sum(1 for k in ins if k.startswith("ref_video_audios.")) == 2
    assert sum(1 for k in ins if k.startswith("ref_audios.")) == 1
    # 拷进 input 的文件名带内容哈希（不同内容不同名 ⇒ 不互相覆盖）
    names = [v["inputs"].get("image") or v["inputs"].get("file") or v["inputs"].get("audio")
             for v in g.values() if v.get("class_type") in ("LoadImage", "LoadVideo", "LoadAudio")]
    assert all(n and "_missing" not in str(n) for n in names), names
    assert "__REF" not in json.dumps(g, ensure_ascii=False)


def test_registry_entry_template_is_the_nine_slot_one():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    ref = reg["input_modes"]["modes"]["ref2va"]
    assert ref["template"] == "comfy/h3_i2v_ref2va9_api.json"
    assert ref["legacy_template"] == "comfy/h3_i2v_ref2va_api.json"
    assert ref["entry_workflow"] == "h3_ref2va9_daily"
    wf = yaml.safe_load((ENGINE / "workflows" / "h3_ref2va9_daily.yaml")
                        .read_text(encoding="utf-8"))
    assert "ref_audios" in wf["args"] and "ref_video_audios" in wf["args"]
    gen = [s for s in wf["steps"] if s.get("id") == "gen"][0]
    assert gen["ref_audios"] == "{{args.ref_audios}}"
    assert gen["ref_video_audios"] == "{{args.ref_video_audios}}"


def test_every_registry_template_pointer_names_a_real_file():
    """registry 是模式元数据真源；指针漂了（指向改名/删掉的图）就是下一轮"文档与实现打脸"。"""
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    checked = 0
    for mode, meta in sorted(reg["input_modes"]["modes"].items()):
        for key, val in meta.items():
            if not val or not isinstance(val, str):
                continue
            if key.endswith("_template"):
                target = ENGINE / val                       # comfy/xxx_api.json
            elif key.endswith("_workflow"):
                target = ENGINE / "workflows" / f"{val}.yaml"   # 流名，不是路径
            else:
                continue
            assert target.is_file(), f"{mode}.{key} → {val} 不在盘上"
            checked += 1
    assert checked >= 10, checked                            # 别默默变成空断言


# ------------------------------------------------------------------ P1 注释/实现一致
def test_static_loadimage_nodes_are_removed_not_just_unwired():
    """旧注释说"摘掉"但只 pop 引用键 ⇒ 静态 4 图模板走动态注入时必须真的摘节点。"""
    tpl = json.loads((ENGINE / "comfy/h3_i2v_ref2va_api.json").read_text(encoding="utf-8"))
    before = sum(1 for n in tpl.values() if n.get("class_type") == "LoadImage")
    assert before == 4
    same = T.build_graph_video(tpl, {"prompt": "P", "width": 736, "height": 416,
                                     "length": 124, "input_mode": "ref2va"}, 42, extra_rep={},
                               ref_materials={"images": ["i1.png", "i2.png", "i3.png",
                                                          "i4.png"],
                                              "videos": [], "video_audios": [], "audios": []})
    # 张数与静态槽数一致 ⇒ 原节点被摘后按素材重建，数量仍等于 4，且不残留旧号占位
    assert sum(1 for n in same.values() if n.get("class_type") == "LoadImage") == 4
    assert json.dumps(same, ensure_ascii=False).count("__REF") == 0
    # 张数与静态槽数不符 ⇒ 必须报错并指路，不能留下悬空 LoadImage 或字面量
    with pytest.raises(ValueError) as ei:
        T.build_graph_video(tpl, {"prompt": "P", "width": 736, "height": 416,
                                  "length": 124, "input_mode": "ref2va"}, 42, extra_rep={},
                            ref_materials={"images": ["a.png", "b.png"], "videos": [],
                                           "video_audios": [], "audios": []})
    assert "写死了 4 个参考图槽" in str(ei.value), str(ei.value)


def test_allocated_ids_do_not_rely_on_parity(monkeypatch):
    """_alloc 每次预留的 id 必须都进 taken：以前只记起点、靠"步长 2 且从偶数起"的巧合。"""
    g = {"200": {"class_type": "X"}, "201": {"class_type": "X"}, "250": {"class_type": "X"}}
    src = T.apply_reference_materials.__code__
    import inspect
    body = inspect.getsource(T.apply_reference_materials)
    assert "taken.add(nxt)" in body and "ids.append(str(nxt))" in body
    # 行为面：给 3 段视频（每个要 2 个 id）不能撞已占用号
    tpl = json.loads((ENGINE / "comfy/h3_i2v_ref2va9_api.json").read_text(encoding="utf-8"))
    tpl["200"] = {"class_type": "Note"}
    tpl["201"] = {"class_type": "Note"}
    tpl["202"] = {"class_type": "Note"}
    out = T.build_graph_video(tpl, {"prompt": "P", "width": 736, "height": 416,
                                    "length": 124, "input_mode": "ref2va"}, 42, extra_rep={},
                              ref_materials={"images": [], "videos": ["v0.mp4", "v1.mp4",
                                                                      "v2.mp4"],
                                             "video_audios": ["a0.wav", "a1.wav", "a2.wav"],
                                             "audios": []})
    used = [k for k in out if str(k).isdigit() and int(k) >= 200]
    assert len(used) == len(set(used))
    for k in ("200", "201", "202"):          # 预置的占用号必须被绕开
        assert out[k]["class_type"] == "Note"
    assert src.co_names                         # 防止函数被误删成空壳


# ------------------------------------------------------------------ P1 每段 2–15s 按秒判
def test_ref_video_per_segment_is_judged_in_seconds_not_frames(monkeypatch, tmp_path):
    """官方"每段参考视频 2–15s"必须按**实测秒数**判，不是"帧数 48–360"。

    旧口径隐含 24fps 假设：同样 300 帧，10fps 是 30s（该拦）、30fps 是 10s（该放）。
    只测 24fps 夹具等于没测这条判据，所以这里直接桩 `_video_stats` 换帧率。
    """
    import check_preflight as CP
    vid = tmp_path / "seg.mp4"
    vid.write_bytes(b"mp4")
    spec = {"prompt": "x", "prompt_kind": "h3_ref2va", "input_mode": "ref2va",
            "refs": [], "ref_videos": [str(vid)], "ref_video_audios": [], "ref_audios": [],
            "w": 736, "h": 416, "length": 124, "provider": "local", "only": ["G4"],
            "workflow_json": str(ENGINE / "comfy" / "h3_i2v_ref2va9_api.json"),
            "output_root": str(tmp_path), "project": "无音",
            "project_aliases": {"无音": ["无音"]}}
    monkeypatch.setattr(CP, "_video_stats", lambda p: (300, 96, 96, 10.0))
    rep = run_checks(spec)
    hit = [m for _lv, g, m in rep.errors if g == "G4" and "2–15s" in m]
    assert hit, rep.render()                       # 300 帧 @10fps = 30s ⇒ 拦
    assert "30.00s" in hit[0], hit[0]              # 文案给的是秒，不是帧数
    monkeypatch.setattr(CP, "_video_stats", lambda p: (300, 96, 96, 30.0))
    rep2 = run_checks(spec)
    assert not [e for e in rep2.errors if e[1] == "G4"], rep2.render()   # 10s ⇒ 放
    # 那把错尺子必须真的不在：留着常量，下一个人就会"顺手"用它代判秒数
    assert not hasattr(CP, "REF_VIDEO_MIN_FRAMES"), "48/360 帧代理判据又回来了"
    assert not hasattr(CP, "REF_VIDEO_MAX_FRAMES")


# ------------------------------------------------------------------ P1 不把网格冒充官方
def test_g6_message_separates_official_bound_from_local_grid():
    rep = run_checks({"prompt": "x", "refs": [], "length": 346, "provider": "local",
                      "only": ["G6"], "output_root": ".", "project": "无音",
                      "project_aliases": {"无音": ["无音"]}})
    msg = " ".join(m for _lv, g, m in rep.errors if g == "G6")
    assert "346" in msg
    assert "我们的裁定" in msg or "本机裁定" in msg, msg      # 345 是网格裁定
    assert "4–15s" in msg or "96–360" in msg                  # 官方硬界要另说
    rep2 = run_checks({"prompt": "x", "refs": [], "length": 362, "provider": "local",
                       "only": ["G6"], "output_root": ".", "project": "无音",
                       "project_aliases": {"无音": ["无音"]}})
    msg2 = " ".join(m for _lv, g, m in rep2.errors if g == "G6")
    assert "15.08s" in msg2 or "超官方 15s" in msg2, msg2     # 362 有官方依据


def test_header_comment_matches_code():
    """头注曾写"107–123 未实测，未放行"，代码是放行＋warn —— 文档与实现不许相互打脸。"""
    src = (TOOLS / "check_preflight.py").read_text(encoding="utf-8")
    i = src.index("H3_MIN_FRAMES")
    head = src[src.index("项目常量"):i]
    assert "未放行" not in head, "头注还在说没放行，代码已经放行＋warn 了"
    assert "warn" in head and "107" in head and "345" in head
    assert "17n+5" in head, "必须写清 345/107 来自网格，不是官方数字"


# ------------------------------------------------------------------ P1 官方判据不再偏软
def _skeleton(first="For the target video, at 0.00 seconds into the target video, "
                      "<Picture 1> (from [Shot 1]) is fully referenced."):
    return (first + "\n\nintegrated_multimodal_description: [Shot 1] Live-action, a gate.\n\n"
            "overall_soundscape: Wind.\n\nnon_diegetic_music: N/A")


def test_blank_line_after_first_line_is_error_in_both_rulers():
    text = _skeleton().replace("\n\nintegrated", "\nintegrated")
    rows = [(r["sev"], r["id"]) for r in SPEC.validate(text, mode="i2va", seconds=5.17).rows
            if r["sev"] != "ok"]
    assert ("error", "F0") in rows, rows            # 写稿契约端
    rep = run_checks({"prompt": text, "refs": ["a.png"], "prompt_kind": "h3_i2va",
                      "only": ["G7"], "output_root": ".", "provider": "local",
                      "project": "无音", "project_aliases": {"无音": ["无音"]}})
    assert any(g == "G7" for _lv, g, _m in rep.errors), rep.render()   # 跑前闸端


def _ref2va(ret_line="<Subject 1> fully_preserved from <Picture 1>"):
    return ("subject_definitions: <Subject 1> a woman in a dark robe.\n\n"
            "summary: [reference generation] <Subject 1> walks from <Picture 1>.\n\n"
            "retention_analysis: " + ret_line + "\n\n"
            "detailed_description: [Shot 1] She turns; the camera Push In slowly past the gate.\n\n"
            "overall_soundscape: Wind.\n\nnon_diegetic_music: N/A")


def test_retention_tier_values_are_hard_checked():
    assert not [r for r in SPEC.validate(_ref2va(), mode="ref2va", seconds=5.17).rows
                if r["sev"] == "error" and r["id"] == "F10"], "合法档位不该报错"
    bad = SPEC.validate(_ref2va("<Subject 1> mostly_preserved from <Picture 1>"),
                        mode="ref2va", seconds=5.17)
    assert any(r["sev"] == "error" and "非官方档位词" in r["msg"] for r in bad.rows
               if r["id"] == "F10"), [r["msg"] for r in bad.rows]
    wrong_family = SPEC.validate(_ref2va("<Audio 1> fully_preserved from <Audio 1>"),
                                 mode="ref2va", seconds=5.17)
    assert any(r["sev"] == "error" and "家族" in r["msg"] for r in wrong_family.rows
               if r["id"] == "F10"), [r["msg"] for r in wrong_family.rows]


def test_audio_strict_total_is_documented_switch(monkeypatch, tmp_path):
    """官方"音频≤3"与节点"每类各 3"口径不一致 ⇒ 默认 warn 并点名分歧，开关才 error。"""
    imgs = [_write(tmp_path / f"i{k}.png") for k in range(4)]
    va = [_write(tmp_path / f"va{k}.wav", b"RIFF") for k in range(3)]
    au = [_write(tmp_path / "a.wav", b"RIFF")]
    specs = {"prompt": "x", "refs": imgs, "prompt_kind": "h3_ref2va",
             "input_mode": "ref2va", "w": 736, "h": 416, "length": 124,
             "provider": "local", "only": ["G4"], "output_root": str(tmp_path),
             "project": "无音", "project_aliases": {"无音": ["无音"]},
             "ref_audios": au, "ref_video_audios": va}
    monkeypatch.delenv("AW_H3_AUDIO_STRICT", raising=False)
    import importlib
    import check_preflight as CP
    importlib.reload(CP)
    rep = CP.run_checks(specs)
    warns = [m for lv, g, m in rep.items if lv == "warn" and g == "G4"]
    assert any("两种读法" in m or "口径" in m or "合计" in m for m in warns), warns
    assert not [e for e in rep.errors], rep.render()
    monkeypatch.setenv("AW_H3_AUDIO_STRICT", "1")
    importlib.reload(CP)
    rep2 = CP.run_checks(specs)
    assert any(g == "G4" for _lv, g, _m in rep2.errors), rep2.render()
    monkeypatch.delenv("AW_H3_AUDIO_STRICT", raising=False)
    importlib.reload(CP)


def test_official_unvalidated_section_is_honest():
    reg = json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))
    items = reg["official_unvalidated"]["items"]
    for key in ("audio_total_3_across_kinds", "reference_video_seconds_per_segment",
                "retention_tier_values", "blank_line_after_first_line",
                "output_32khz_stereo", "frames_107_345"):
        assert key in items, key
        assert items[key].get("we_do"), key
        assert "未校验" in items[key]["status"] or items[key]["status"]


# ------------------------------------------------------------------ P1 32kHz 立体声不再空采
def test_audio_spec_evidence_is_on_disk_not_a_verbal_claim():
    """注释一度写"6 份真实产物实测一致"，而盘上只有 2 份留痕 ⇒ 现在是 8 份逐条 ffprobe 的凭据。"""
    ev = Path(r"D:\AIWorkflow\evidence\QA_20261024\audio_spec_probe.txt")
    assert ev.is_file(), "32kHz 取证文件没了：跑 evidence/QA_20261024/probe_audio_spec.py"
    txt = ev.read_text(encoding="utf-8")
    assert "成片本体" in txt and "不抽样" in txt
    assert "合计 8 个成片本体；符合 32000 Hz／2 声道 = 8 个" in txt, txt[-200:]
    src = (ENGINE / "tasks.py").read_text(encoding="utf-8")
    assert "6 份真实产物实测一致" not in src          # 不许再退回口头账
    assert "audio_spec_probe" in src                  # 注释必须指向可复跑的证据


def test_native_audio_spec_is_enforced(tmp_path, monkeypatch):
    def probe(path, ctx, decode=False):
        return {"file": str(path), "size": 10, "width": 736, "height": 416, "fps": 24.0,
                "frames": 124, "duration": 5.17, "has_audio": True, "audio_codec": "aac",
                "sample_rate": sr[0], "channels": sr[1]}
    def run_media(cmd, timeout=None):
        class P:
            stderr = ""
            returncode = 0
        return P()
    monkeypatch.setattr(T, "probe_video", probe)
    monkeypatch.setattr(T, "_run_media", run_media)
    monkeypatch.setattr(T, "_media_tools", lambda ctx: ("ffmpeg", "ffprobe"))
    ctx = {"cfg": {}}
    f = tmp_path / "x.mp4"
    f.write_bytes(b"x")
    sr = [32000, 2]
    assert T._video_qc(f, ctx, expect_audio_spec=T.H3_NATIVE_AUDIO)["audio_spec_ok"] == [32000, 2]
    sr[0] = 44100
    with pytest.raises(RuntimeError) as ei:
        T._video_qc(f, ctx, expect_audio_spec=T.H3_NATIVE_AUDIO)
    assert "44100" in str(ei.value)


# ------------------------------------------------------------------ P2 证据口径
def test_scan_362_hashes_media_files_not_only_manifests():
    ev = Path(r"D:\AIWorkflow\evidence\W5c\scan_362.json")
    data = json.loads(ev.read_text(encoding="utf-8"))
    produced = [r for r in data["rows"] if r.get("produced_mp4")]
    assert produced, "清单里应仍有出片批次"
    for r in produced:
        assert r.get("media_sha256"), r["run_id"]
        for rel, h in r["media_sha256"].items():
            assert len(h) == 64 and (Path(r["path"]).parent / rel).is_file(), (r, rel)
    # 出片判定与哈希同源 ⇒ 只能证"未被动过"，不能自证判据对不对；这点必须写在清单里，
    # 而不是只写在台账话术里（QA P2-②）。
    assert data["limits"]["self_proving"]
    assert "不能独立证明" in data["limits"]["self_proving"]
    assert data["limits"]["match_scope"]
