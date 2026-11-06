# -*- coding: utf-8 -*-
"""V5a-5：原片 raw QC 失败的镜不得进入归一化/拼接（计划 W5a 第 5 条）。

离线注入：t_video／_video_qc／_normalize_clip／_concat_clips／ensure_comfyui 全部桩掉，
0 网络、0 提交、0 GPU；断言的是**调用次数与入参**，不是返回值好不好看。
"""
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))

import tasks as T  # noqa: E402

QC_OK = {"width": 736, "height": 416, "fps": 24.0, "frames": 124,
         "duration": 5.1667, "has_audio": True, "audio_sr": 32000}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    calls = {"normalize": [], "concat": [], "qc": [], "submit": 0}
    batch = tmp_path / "batch"
    batch.mkdir()
    cfg = {"comfyui": {"base_url": "http://127.0.0.1:8189",
                       "output_dir": str(tmp_path / "comfy_out"),
                       "input_dir": str(tmp_path / "comfy_in")},
           "output_root": str(batch), "preflight": "on"}
    ctx = {"cfg": cfg, "batch_dir": batch, "run_id": "QC_TEST", "wf_root": ENGINE,
           "args": {}, "outputs": {}, "workflow": "h3_movie",
           "explicit_args": [], "_msgs": []}
    # tasks.py 里有的地方把 ctx["log"] 当**可调用**用（relocate(..., ctx["log"])）
    ctx["log"] = lambda m: ctx["_msgs"].append(m)
    monkeypatch.setattr(T, "log", lambda c, m: c.setdefault("_msgs", []).append(m))

    png = tmp_path / "first.png"
    png.write_bytes(b"\x89PNG\r\n")

    def fake_t_video(vp, c):
        calls["submit"] += 1
        sid = vp["prefix"].split("_")[-2]
        out = tmp_path / "comfy_out" / f"{sid}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"stub")
        return {"files": [str(out)], "elapsed": 0}

    def fake_qc(path, c, require_audio=True, expected_fps=24.0, expected_length=None,
                expect_audio_spec=None):
        p = Path(str(path))
        calls["qc"].append(p.name)
        if p.name == "s01.mp4":            # 注入：第 1 镜的原片QC 失败
            raise RuntimeError("raw QC 失败：实测 120 帧 ≠ 预期 124 帧")
        return dict(QC_OK)

    def fake_normalize(src, dst, c, **kw):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"norm")
        calls["normalize"].append(Path(str(src)).name)
        return dst

    def fake_concat(clips, dst, c):
        calls["concat"].append([str(x) for x in clips])
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"final")
        return dst

    monkeypatch.setattr(T, "t_video", fake_t_video)
    monkeypatch.setattr(T, "_video_qc", fake_qc)
    monkeypatch.setattr(T, "_normalize_clip", fake_normalize)
    monkeypatch.setattr(T, "_concat_clips", fake_concat)
    monkeypatch.setattr(T, "ensure_comfyui", lambda c, relay=False: "http://stub")
    monkeypatch.setattr(T, "preflight_or_die", lambda *a, **k: None)

    manifest = {"profile": "stable_t8", "title": "qc_gate", "seed_base": 42,
                "defaults": {"width": 736, "height": 416, "length": 124},
                "shots": [{"id": "s01", "prompt": "P1", "ref_images": [str(png)]},
                          {"id": "s02", "prompt": "P2", "ref_images": [str(png)]}]}
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    ctx["_batch"] = batch
    ctx["_tmp"] = tmp_path
    return ctx, mp, calls, batch


def test_failed_raw_never_reaches_normalize_or_concat(harness):
    ctx, mp, calls, batch = harness
    out = T.t_h3_movie({"manifest": str(mp), "profile": "stable_t8",
                        "output_width": 736, "output_height": 416, "fps": 24,
                        "length": 124, "width": 736, "height": 416}, ctx)

    # ① QC 失败镜没有进过归一化：normalize 只收到 s02 的原片
    assert calls["normalize"] == ["s02.mp4"], calls
    # ② 拼接入参里没有 s01 的归一片，只有 s02 一份
    assert len(calls["concat"]) == 1 and len(calls["concat"][0]) == 1, calls
    assert "s01" not in calls["concat"][0][0], calls["concat"]
    assert "s02" in calls["concat"][0][0], calls["concat"]
    # ③ state 里 s01 明确是 qc_failed＋raw_qc_passed=False，不是 done 也不是"生成失败"
    state = json.loads((batch / "h3_movie_state.json").read_text(encoding="utf-8"))
    s01, s02 = state["shots"]["s01"], state["shots"]["s02"]
    assert s01["status"] == "qc_failed" and s01["raw_qc_passed"] is False, s01
    assert "120" in s01["raw_qc_error"]
    assert s02["status"] == "done" and s02["raw_qc_passed"] is True, s02
    # ④ 成片计数只算进过的镜；没被伪造成 2 镜
    assert out["shots"] == 1, out
    # ⑤ 全程 0 真实提交（t_video 是桩，计数只为证明循环没多跑）
    assert calls["submit"] == 2, calls


def test_qc_failed_shot_not_recounted_on_resume(harness):
    """续跑时 qc_failed 的镜必须重新过一遍，不能被当成"已完成"跳过。"""
    ctx, mp, calls, batch = harness
    T.t_h3_movie({"manifest": str(mp), "profile": "stable_t8",
                  "output_width": 736, "output_height": 416, "fps": 24,
                  "length": 124, "width": 736, "height": 416}, ctx)
    state_path = batch / "h3_movie_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["shots"]["s01"]["status"] == "qc_failed"
    assert state["shots"]["s01"].get("normalized") is None, \
        "qc_failed 镜不许留下归一片路径（否则续跑会认领废片）"


def test_all_shots_failed_never_produces_empty_final(tmp_path, monkeypatch, harness):
    """全镜 QC 失败 ⇒ 明确报错，不拼空表、不写 done。"""
    ctx, mp, calls, batch = harness
    # 让两份原片都失败
    def always_fail(path, c, **kw):
        raise RuntimeError("raw QC 失败：实测帧数不符")
    monkeypatch.setattr(T, "_video_qc", always_fail)
    with pytest.raises(RuntimeError) as ei:
        T.t_h3_movie({"manifest": str(mp), "profile": "stable_t8",
                      "output_width": 736, "output_height": 416, "fps": 24,
                      "length": 124, "width": 736, "height": 416}, ctx)
    assert "没有任何一镜通过 raw QC" in str(ei.value), str(ei.value)
    assert calls["concat"] == [], "空归一表不许进 concat"
    assert not (batch / "final").exists() or not list((batch / "final").glob("*.mp4"))
    state = json.loads((batch / "h3_movie_state.json").read_text(encoding="utf-8"))
    assert state.get("status") != "done", state
