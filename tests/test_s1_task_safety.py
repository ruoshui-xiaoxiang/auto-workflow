# -*- coding: utf-8 -*-
"""S1 任务安全：真实执行者级行为测试（全程隔离，0 网络/0 GPU/0 真实提交）。

覆盖：
  · 取消意图在 t_video 提交前阻断；
  · h3_movie 多镜循环取消后不再提交下一镜；
  · 两次恢复同镜只提交 1 次；改 seed／同路径素材／模板后失效重跑；
  · 本 run 的崩溃回收只认本 run submission prefix，不认他批同镜号；
  · 原 prompt_id 迟到恢复不重渲；
  · run.py 的 resume 绑定按步骤失效（编译步可复用，生成/审核步不复用）。
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))

import tasks as T                      # noqa: E402
import task_state as TS                # noqa: E402
import run_plan as RP                  # noqa: E402
import run as R                        # noqa: E402

QC_OK = {"width": 736, "height": 416, "fps": 24.0, "frames": 124,
         "duration": 5.1667, "has_audio": True, "audio_sr": 32000}


def _png(path, data=b"\x89PNG\r\n"):
    path.write_bytes(data)
    return str(path)


# ============================================================ 绑定/失效判定
def _two_pass_args(tmp_path):
    wf = yaml.safe_load((ENGINE / "workflows" / "h3_two_pass_daily.yaml")
                        .read_text(encoding="utf-8"))
    img = _png(tmp_path / "ref.png")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("OFFLINE FIXTURE\n", encoding="utf-8")
    args = dict(wf.get("args") or {})
    args.update({"prompt_file": str(prompt), "ref_images": [img],
                 "prompt": "", "width": 736, "height": 416, "length": 124})
    return wf, args, img


def _bind(wf, args, engine_root=ENGINE):
    b = TS.build_binding(engine_root, "h3_two_pass_daily", wf, args)
    return TS.attach_steps(b, wf.get("steps") or [])


def test_resume_binding_unchanged_reuses_all_done_steps(tmp_path):
    wf, args, _img = _two_pass_args(tmp_path)
    b = _bind(wf, args)
    steps = wf.get("steps") or []
    dec = TS.select_resume_steps([s["id"] for s in steps], steps, b, b,
                                 prev_manifest={"args": args}, curr_args=args)
    assert dec["reusable"] == {s["id"] for s in steps}, dec
    assert not dec["invalidated"], dec


def test_resume_seed_change_invalidates_gate_and_gen_but_not_compile(tmp_path):
    wf, args, _img = _two_pass_args(tmp_path)
    b1 = _bind(wf, args)
    args2 = dict(args, seed=999)
    b2 = _bind(wf, args2)
    steps = wf.get("steps") or []
    dec = TS.select_resume_steps([s["id"] for s in steps], steps, b1, b2,
                                 prev_manifest={"args": args}, curr_args=args2)
    assert {"snapshot", "translate", "compile_check"} <= dec["reusable"], dec
    assert {"pre", "gen"} <= set(dec["invalidated"]), dec


def test_resume_same_path_media_change_invalidates_gate_and_gen(tmp_path):
    wf, args, img = _two_pass_args(tmp_path)
    b1 = _bind(wf, args)
    Path(img).write_bytes(b"\x89PNG\r\nDIFFERENT-CONTENT")
    b2 = _bind(wf, args)
    steps = wf.get("steps") or []
    dec = TS.select_resume_steps([s["id"] for s in steps], steps, b1, b2,
                                 prev_manifest={"args": args}, curr_args=args)
    assert {"snapshot", "translate", "compile_check"} <= dec["reusable"], dec
    assert {"pre", "gen"} <= set(dec["invalidated"]), dec


def test_resume_template_change_invalidates_gate_and_gen(tmp_path):
    wf, args, _img = _two_pass_args(tmp_path)
    root = tmp_path / "engine"
    (root / "workflows").mkdir(parents=True)
    (root / "comfy").mkdir()
    shutil.copy2(ENGINE / "workflows" / "h3_two_pass_daily.yaml",
                 root / "workflows" / "h3_two_pass_daily.yaml")
    tpl_rel = "comfy/h3_two_pass_api.json"
    shutil.copy2(ENGINE / tpl_rel, root / tpl_rel)
    b1 = _bind(wf, args, engine_root=root)
    (root / tpl_rel).write_bytes((root / tpl_rel).read_bytes() + b"\n# changed\n")
    b2 = _bind(wf, args, engine_root=root)
    steps = wf.get("steps") or []
    dec = TS.select_resume_steps([s["id"] for s in steps], steps, b1, b2,
                                 prev_manifest={"args": args}, curr_args=args)
    assert {"snapshot", "translate", "compile_check"} <= dec["reusable"], dec
    assert {"pre", "gen"} <= set(dec["invalidated"]), dec


def test_step_level_override_changes_gen_and_downstream_only(tmp_path):
    """R5：只改 gen 步骤的 lora_strength，gen 指纹必须变，上游编译步不变。"""
    wf, args, _img = _two_pass_args(tmp_path)
    steps = list(wf.get("steps") or []) + [
        {"id": "after", "task": "shell", "command": "echo after"}]
    wf1 = dict(wf, steps=steps)
    b1 = TS.attach_steps(
        TS.build_binding(ENGINE, "h3_two_pass_daily", wf1, args), steps)
    steps2 = []
    for s in steps:
        s2 = dict(s)
        if s2.get("id") == "gen":
            s2["lora_strength"] = 0.123
        steps2.append(s2)
    wf2 = dict(wf, steps=steps2)
    b2 = TS.attach_steps(
        TS.build_binding(ENGINE, "h3_two_pass_daily", wf2, args), steps2)
    assert b1["steps"]["gen"] != b2["steps"]["gen"], "步骤级覆盖没进指纹"
    assert b1["steps"]["snapshot"] == b2["steps"]["snapshot"], \
        "只改 gen 不应让上游编译步指纹变化"
    dec = TS.select_resume_steps([s["id"] for s in steps], steps2, b1, b2,
                                 prev_manifest={"args": args}, curr_args=args)
    assert {"snapshot", "translate", "compile_check"} <= dec["reusable"], dec
    assert "gen" in dec["invalidated"], dec
    assert "after" in dec["invalidated"], "下游步骤必须随 gen 失效"


def test_legacy_manifest_from_real_writer_reuses_compile_steps(tmp_path):
    """R2：用真实 write_manifest 产物验旧结构；不能手写符合函数预期的假 manifest。"""
    wf, args, img = _two_pass_args(tmp_path)
    b = _bind(wf, args)
    steps = wf.get("steps") or []
    compiled = tmp_path / "compiled.txt"
    compiled.write_text("COMPILED FIXTURE", encoding="utf-8")
    man = R.write_manifest(
        tmp_path / "manifest.json", "RUN", "h3_two_pass_daily",
        {"gen": {"files": ["x.mp4"], "prompt": "COMPILED FIXTURE", "seed": 42}},
        args=args,
        step_params={"gen": {"prompt_file": str(compiled), "ref_images": [img]}},
        cfg={"project": "无音"}, batch_dir=tmp_path, resume_binding=b)
    legacy = dict(man)
    legacy.pop("resume_binding")
    dec = TS.select_resume_steps([s["id"] for s in steps], steps, None, b,
                                 prev_manifest=legacy, curr_args=args)
    assert {"snapshot", "translate", "compile_check"} <= dec["reusable"], dec
    assert {"pre", "gen"} <= set(dec["invalidated"]), dec
    assert man["images"][0]["prompt_file"] == str(compiled)
    dec2 = TS.select_resume_steps([s["id"] for s in steps], steps, None, b,
                                  prev_manifest={}, curr_args=args)
    assert not dec2["reusable"], "没有旧 manifest 证据时不得复用任何步骤"


# ============================================================ 取消阻断提交
def test_restore_outputs_rejects_missing_empty_and_outside(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    ok = batch / "ok.mp4"
    ok.write_bytes(b"x")
    empty = batch / "empty.mp4"
    empty.write_bytes(b"")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    missing = batch / "not_there.mp4"

    def man_with(files, name):
        p = tmp_path / name
        p.write_text(json.dumps({"images": [
            {"step": "gen", "file": str(f), "prompt": "x"} for f in files]}),
            encoding="utf-8")
        return p

    out, invalid = R.restore_outputs_checked(
        man_with([missing], "m_missing.json"), {"gen"}, batch_dir=batch)
    assert "gen" not in out and invalid["gen"][0]["reason"] == "missing", (out, invalid)
    out, invalid = R.restore_outputs_checked(
        man_with([empty], "m_empty.json"), {"gen"}, batch_dir=batch)
    assert "gen" not in out and invalid["gen"][0]["reason"] == "empty", (out, invalid)
    out, invalid = R.restore_outputs_checked(
        man_with([outside], "m_outside.json"), {"gen"}, batch_dir=batch)
    assert "gen" not in out and invalid["gen"][0]["reason"] == "outside_batch", (out, invalid)
    out, invalid = R.restore_outputs_checked(
        man_with([ok, missing], "m_mixed.json"), {"gen"}, batch_dir=batch)
    assert "gen" not in out, "一步里混有缺失文件时整步不得恢复"
    out, invalid = R.restore_outputs_checked(
        man_with([ok], "m_ok.json"), {"gen"}, batch_dir=batch)
    assert out["gen"]["files"] == [str(ok)] and not invalid, (out, invalid)
    # 兼容包装（主审探针的调用形状）也不得返回缺失文件
    assert R.restore_outputs(man_with([missing], "m_wrap.json"), {"gen"}) == {}


def test_cancel_intent_write_failure_stops_before_any_post(tmp_path, monkeypatch):
    """R1：意图写不进去 ⇒ 0 POST、0 confirmed，明确 intent_write_failed。"""
    not_a_dir = tmp_path / "batch_is_a_file"
    not_a_dir.write_bytes(b"x")
    calls = {"post": 0}

    class Session:
        def post(self, *a, **kw):
            calls["post"] += 1
            raise AssertionError("意图写入失败后不许再发取消请求")
        def get(self, *a, **kw):
            raise AssertionError("意图写入失败后不许再读队列/历史")

    monkeypatch.setattr(T, "SESSION", Session())
    res = T.cancel_submission({"batch_dir": str(not_a_dir), "run_id": "R"},
                              "http://offline.invalid", "TARGET")
    assert calls["post"] == 0, calls
    assert res["state"] == "intent_write_failed", res
    assert res["confirmed"] is False and res["dispatched"] is False, res
    assert "取消意图写入失败" in str(res["error"]), res
    assert not (not_a_dir / "cancel_intent.json").exists()


def test_cancel_intent_blocks_t_video_before_submit(tmp_path, monkeypatch):
    batch = tmp_path / "batch"
    batch.mkdir()
    input_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    input_dir.mkdir()
    out_dir.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("OFFLINE FIXTURE\n", encoding="utf-8")
    png = _png(tmp_path / "ref.png")
    cfg = {"comfyui": {"base_url": "http://stub", "input_dir": str(input_dir),
                       "output_dir": str(out_dir)}, "preflight": "on"}
    ctx = {"cfg": cfg, "batch_dir": batch, "run_id": "CANCEL", "wf_root": ENGINE,
           "args": {}, "outputs": {}, "workflow": "test", "log": lambda m: None}
    calls = {"submit": 0}

    class Session:
        def post(self, url, **kw):
            calls["submit"] += 1
            raise AssertionError("取消意图已存在，仍在提交")

    monkeypatch.setattr(T, "SESSION", Session())
    monkeypatch.setattr(T, "preflight_or_die", lambda *a, **k: None)
    monkeypatch.setattr(T, "ensure_comfyui", lambda *a, **k: "http://stub")
    T.request_cancel(ctx, "pid-1", reason="test")
    p = {"workflow": "comfy/h3_i2v_fl2va_api.json",
         "prompt_file": str(prompt), "prompt_kind": "h3_i2va",
         "input_mode": "i2va", "ref_images": [png],
         "width": 736, "height": 416, "length": 124, "steps": 8,
         "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
         "head_chunks": 4, "prefix": "s1_cancel", "stage": "video",
         "timeout": 10}
    with pytest.raises(T.RunCancelled):
        T.t_video(p, ctx)
    assert calls["submit"] == 0, calls


# ============================================================ h3_movie 执行者
def _movie_harness(tmp_path, monkeypatch, seed_base=42, n_shots=1):
    batch = tmp_path / "batch"
    batch.mkdir()
    out_dir = tmp_path / "comfy_out"
    out_dir.mkdir()
    png = _png(tmp_path / "ref.png")
    calls = {"submit": 0, "paths": []}
    cfg = {"comfyui": {"base_url": "http://stub", "output_dir": str(out_dir),
                       "input_dir": str(tmp_path / "comfy_in")},
           "output_root": str(batch), "preflight": "on"}
    ctx = {"cfg": cfg, "batch_dir": batch, "run_id": "S1_MOVIE", "wf_root": ENGINE,
           "args": {}, "outputs": {}, "workflow": "h3_movie", "_msgs": []}
    ctx["log"] = lambda m: ctx["_msgs"].append(m)
    monkeypatch.setattr(T, "log", lambda c, m: c.setdefault("_msgs", []).append(m))

    def fake_t_video(vp, c):
        calls["submit"] += 1
        calls["paths"].append(vp.get("prefix"))
        out = out_dir / f"movie_{c['run_id']}_{vp['prefix'].split('_')[-2]}_a1.mp4"
        out.write_bytes(b"stub")
        if calls["submit"] == 1 and c.get("_cancel_after_first"):
            T.request_cancel(c, "pid-x", reason="test")
        return {"files": [str(out)], "elapsed": 0}

    monkeypatch.setattr(T, "t_video", fake_t_video)
    monkeypatch.setattr(T, "_video_qc", lambda *a, **k: dict(QC_OK))
    def fake_normalize(src, dst, c, **kw):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"norm")
        return dst
    monkeypatch.setattr(T, "_normalize_clip", fake_normalize)
    def fake_concat(clips, dst, c):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"final")
        return dst
    monkeypatch.setattr(T, "_concat_clips", fake_concat)
    shots = [{"id": f"s{i:02d}", "prompt": f"P{i}",
              "ref_images": [png]} for i in range(1, n_shots + 1)]
    manifest = {"profile": "stable_t8", "title": "s1", "seed_base": seed_base,
                "defaults": {"width": 736, "height": 416, "length": 124},
                "shots": shots}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    params = {"manifest": str(mp), "profile": "stable_t8",
              "output_width": 736, "output_height": 416, "fps": 24,
              "length": 124, "width": 736, "height": 416}
    return ctx, params, manifest, calls, batch, png, out_dir


def test_movie_cancel_after_first_shot_does_not_submit_second(tmp_path, monkeypatch):
    ctx, params, _man, calls, _batch, _png_path, _out = \
        _movie_harness(tmp_path, monkeypatch, n_shots=2)
    ctx["_cancel_after_first"] = True
    with pytest.raises(T.RunCancelled):
        T.t_h3_movie(params, ctx)
    assert calls["submit"] == 1, calls


def test_movie_two_resumes_submit_only_once(tmp_path, monkeypatch):
    ctx, params, _man, calls, _batch, _png_path, _out = \
        _movie_harness(tmp_path, monkeypatch, n_shots=1)
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 1, calls
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 1, "两次恢复同一镜不得重新提交"


def test_movie_seed_change_invalidates_done_shot(tmp_path, monkeypatch):
    ctx, params, _man, calls, batch, png, _out = \
        _movie_harness(tmp_path, monkeypatch, seed_base=42, n_shots=1)
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 1, calls
    state_path = batch / "h3_movie_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["shots"]["s01"]["resume_binding"]["params"]["seed"] == 42
    # 同参数第二次仍应跳过
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 1, "同参数恢复不应重提"
    # 改 seed_base 后，原 done 镜必须失效重跑
    man = json.loads(Path(params["manifest"]).read_text(encoding="utf-8"))
    man["seed_base"] = 43
    Path(params["manifest"]).write_text(json.dumps(man), encoding="utf-8")
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 2, "改 seed 后必须重跑，不得假跳过"


def test_movie_same_path_media_change_invalidates_done_shot(tmp_path, monkeypatch):
    ctx, params, _man, calls, batch, png, _out = \
        _movie_harness(tmp_path, monkeypatch, n_shots=1)
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 1, calls
    Path(png).write_bytes(b"\x89PNG\r\nNEW-CONTENT-SAME-PATH")
    T.t_h3_movie(params, ctx)
    assert calls["submit"] == 2, "同路径素材换内容后必须重跑，不得假跳过"


def test_movie_cross_run_glob_is_not_claimed(tmp_path, monkeypatch):
    ctx, params, _man, calls, batch, _png_path, out_dir = \
        _movie_harness(tmp_path, monkeypatch, n_shots=1)
    # 本 run 有提交记录，但目录里放一条**别的 run** 的同镜号成片
    T.persist_submission(
        {"batch_dir": batch, "run_id": "S1_MOVIE", "workflow": "h3_movie",
         "step_id": "gen"}, "pid-current",
        {"1": {"class_type": "X"}},
        {"prefix": "movie_S1_MOVIE_s01_a1", "stage": "shots/s01/raw"})
    foreign = out_dir / "movie_OTHER_RUN_s01_a1.mp4"
    foreign.write_bytes(b"foreign")
    T.t_h3_movie(params, ctx)
    state = json.loads((batch / "h3_movie_state.json").read_text(encoding="utf-8"))
    attempts = state["shots"]["s01"].get("attempts") or []
    assert not any(a.get("from_glob") for a in attempts), attempts
    assert calls["submit"] == 1, calls


def test_movie_stage_submission_is_flat_and_findable(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    ctx = {"batch_dir": batch, "run_id": "R1", "workflow": "h3_movie",
           "step_id": "gen"}
    _payload, path = T.persist_submission(
        ctx, "pid-1", {"1": {"class_type": "X"}},
        {"prefix": "movie_R1_s01_a1", "stage": "shots/s01/raw"},
        stage="shots/s01/raw")
    assert path.parent == batch, "submission 不许再埋进 shots/<sid>/ 子目录"
    assert path.name == "submission_R1_shots_s01_raw.json"
    found = T.submission_prefixes(ctx, "s01")
    assert found and found[0]["prefix"] == "movie_R1_s01_a1"
    assert found[0]["prompt_id"] == "pid-1"


def test_adopt_late_output_uses_prompt_id_only_and_never_submits(tmp_path, monkeypatch):
    out = tmp_path / "comfy_out"
    out.mkdir()
    (out / "mine.mp4").write_bytes(b"x")
    calls = {"post": 0}

    class Session:
        def get(self, url, timeout=None):
            class R:
                status_code = 200
                @staticmethod
                def json():
                    return {"pid-yes": {"outputs": {"12": {"videos": [
                        {"filename": "mine.mp4", "subfolder": ""}]}}}}
            return R()

        def post(self, *a, **kw):
            calls["post"] += 1
            raise AssertionError("adopt 不得提交新生成")

    monkeypatch.setattr(T, "SESSION", Session())
    ctx = {"cfg": {"comfyui": {"output_dir": str(out)}}, "run_id": "R"}
    got = T.adopt_late_output(ctx, "http://stub", "pid-yes")
    assert got and got["files"] == [str(out / "mine.mp4")], got
    assert calls["post"] == 0


def _late_setup(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    late = batch / "late.mp4"
    late.write_bytes(b"x")
    (batch / "comfy_out").mkdir()
    cfg = {"status_file": str(tmp_path / "status.json"),
           "comfyui": {"output_dir": str(batch / "comfy_out")},
           "output_root": str(batch)}
    entry = {"run_id": "RUN1", "status": "error",
             "manifest": str(batch / "manifest.json"),
             "steps": [{"id": "gen", "status": "failed"}]}
    Path(cfg["status_file"]).write_text(
        json.dumps({"history": [entry], "last_run": entry}, ensure_ascii=False),
        encoding="utf-8")
    T.persist_submission(
        {"batch_dir": batch, "run_id": "RUN1", "workflow": "h3_movie",
         "step_id": "gen"}, "PID", {"1": {"class_type": "X"}},
        {"prefix": "movie_RUN1_s01_a1", "stage": "shots/s01/raw"},
        stage="shots/s01/raw")
    return cfg, batch, late


def test_late_adoption_rejects_unknown_step(tmp_path):
    cfg, _batch, late = _late_setup(tmp_path)
    assert R.record_late_adoption(
        cfg, "RUN1", "UNKNOWN_STEP", "PID", [str(late)]) is False
    data = json.loads(Path(cfg["status_file"]).read_text(encoding="utf-8"))
    assert [s["id"] for s in data["history"][0]["steps"]] == ["gen"]
    assert data["history"][0]["steps"][0]["status"] == "failed"


def test_late_adoption_rejects_wrong_prompt_id(tmp_path):
    cfg, _batch, late = _late_setup(tmp_path)
    assert R.record_late_adoption(
        cfg, "RUN1", "gen", "PID-WRONG", [str(late)]) is False
    data = json.loads(Path(cfg["status_file"]).read_text(encoding="utf-8"))
    assert data["history"][0]["steps"][0]["status"] == "failed"


def test_late_adoption_rejects_bad_media_qc(tmp_path, monkeypatch):
    cfg, _batch, late = _late_setup(tmp_path)
    def bad_qc(path, ctx):
        raise RuntimeError("no decodable video stream")
    monkeypatch.setattr(R.tasks, "probe_video", bad_qc)
    assert R.record_late_adoption(
        cfg, "RUN1", "gen", "PID", [str(late)]) is False
    data = json.loads(Path(cfg["status_file"]).read_text(encoding="utf-8"))
    assert data["history"][0]["steps"][0]["status"] == "failed"
    assert not data["history"][0].get("adoptions")


def test_late_adoption_accepts_verified_original_prompt(tmp_path, monkeypatch):
    cfg, _batch, late = _late_setup(tmp_path)
    monkeypatch.setattr(R.tasks, "probe_video",
                        lambda p, c: {"fps": 24.0, "duration": 1.0})
    assert R.record_late_adoption(
        cfg, "RUN1", "gen", "PID", [str(late)]) is True
    data = json.loads(Path(cfg["status_file"]).read_text(encoding="utf-8"))
    assert len(data["history"]) == 1, "回填不得新建 run"
    h = data["history"][0]
    assert h["steps"][0]["status"] == "done"
    assert h["steps"][0]["restored"] is True
    assert h["adoptions"][0]["prompt_id"] == "PID"
    assert h["status"] == "success"
