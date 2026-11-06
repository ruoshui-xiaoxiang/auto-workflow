# h3_spider/tests/test_canvas_state.py
# -*- coding: utf-8 -*-
import json
import os

from h3_spider.canvas_state import find_last_batch, list_assets, load_state, scan_takes


def _mk(tmp_path, assets_dir=None):
    proj = tmp_path / "Demo" / "h3"
    proj.mkdir(parents=True)
    defaults = "defaults:\n  scene: bridge\n"
    if assets_dir:
        defaults += "  assets_dir: %s\n" % assets_dir.as_posix()
    (proj / "shots.yaml").write_text(
        defaults + "shots:\n"
        "  - id: U01\n    mode: i2va\n    duration: 8.0\n    image: U01_start.png\n"
        "  - id: U02\n    mode: ref2va\n    duration: 5.875\n    image: cmdr\n    cast: {S1: cmdr}\n",
        encoding="utf-8")
    (proj / "characters.yaml").write_text(
        "roles:\n  cmdr:\n    role: the commander\n", encoding="utf-8")
    (proj / "scenes.yaml").write_text(
        "scenes:\n  bridge:\n    geometry: x\n", encoding="utf-8")
    (proj / "assets" / "crops").mkdir(parents=True)
    (proj / "assets" / "crops" / "cmdr.png").write_bytes(b"png")
    (proj.parent / "outputs").mkdir()
    (proj.parent / "outputs" / "KB23_U01_00001-audio.mp4.mp4").write_bytes(b"v")
    return proj


def test_load_state_shots_and_anchors(tmp_path):
    proj = _mk(tmp_path)
    st = load_state(str(proj))
    assert [s["id"] for s in st["shots"]] == ["U01", "U02"]
    assert st["anchors"][0]["id"] == "@cmdr"
    assert st["anchors"][0]["label"] == "cmdr"
    assert st["edges"][0]["type"] == "order"


def test_scan_takes_groups_by_shot(tmp_path):
    proj = _mk(tmp_path)
    takes = scan_takes(str(proj))
    assert takes["U01"][0]["path"].endswith(".mp4")


def test_list_assets_includes_crops(tmp_path):
    proj = _mk(tmp_path)
    assets = list_assets(str(proj))
    assert any(a["path"].endswith("crops/cmdr.png") for a in assets)


def test_find_last_batch_reads_marker(tmp_path):
    proj = _mk(tmp_path)
    qc = tmp_path / "qc"
    qc.mkdir()
    (qc / "batch_verdict.json").write_text('{"overall":"PASS","shots":{}}', encoding="utf-8")
    (proj / ".fanxing").mkdir()
    (proj / ".fanxing" / "last_batch.json").write_text(
        json.dumps({"batch_dir": str(qc)}), encoding="utf-8")
    assert find_last_batch(str(proj)) == str(qc)


def test_remember_run_is_scanned(tmp_path):
    from h3_spider.canvas_state import remember_run
    proj = _mk(tmp_path)
    run = tmp_path / "job_run"
    run.mkdir()
    (run / "U01_00003-audio.mp4").write_bytes(b"v")
    remember_run(str(proj), str(run))
    takes = scan_takes(str(proj))
    assert any(t["path"].endswith("U01_00003-audio.mp4") for t in takes["U01"])


def test_load_state_reads_prompt_preview(tmp_path):
    proj = _mk(tmp_path)
    (proj / "out").mkdir()
    (proj / "out" / "U01.txt").write_text("preview text", encoding="utf-8")
    st = load_state(str(proj))
    assert st["prompts"]["U01"].startswith("preview text")


def _put_batch_verdict(qc, payload):
    qc.mkdir(parents=True, exist_ok=True)
    (qc / "batch_verdict.json").write_text(
        json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    return qc


def _point_marker(proj, batch_dir):
    (proj / ".fanxing").mkdir(parents=True, exist_ok=True)
    (proj / ".fanxing" / "last_batch.json").write_text(
        json.dumps({"batch_dir": batch_dir}), encoding="utf-8")


def _norm(p):
    return os.path.normcase(os.path.abspath(str(p)))


def test_list_assets_includes_defaults_assets_dir(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "U01_start.png").write_bytes(b"png")
    proj = _mk(tmp_path, assets_dir=frames)

    assets = list_assets(str(proj))
    assert any(a["path"].endswith("U01_start.png") for a in assets)

    st = load_state(str(proj))
    assert any(a["path"].endswith("U01_start.png") for a in st["assets"])
    assert all(os.path.isabs(r) for r in st["asset_roots"])
    assert _norm(frames) in [_norm(r) for r in st["asset_roots"]]


def test_status_survives_non_dict_batch_root(tmp_path):
    proj = _mk(tmp_path)
    qc = _put_batch_verdict(tmp_path / "qc", "[]")
    _point_marker(proj, str(qc))

    st = load_state(str(proj))
    assert _norm(st["batch_dir"]) == _norm(qc)
    assert st["status"] == {}


def test_status_skips_unusable_shot_records(tmp_path):
    proj = _mk(tmp_path)
    qc = _put_batch_verdict(tmp_path / "qc", {
        "overall": "PASS",
        "shots": {"U01": "PASS", "U02": {"verdict.json": {"overall": "FAIL"}}, "U03": {}},
    })
    _point_marker(proj, str(qc))

    assert load_state(str(proj))["status"] == {"U01": "?", "U02": "FAIL", "U03": "?"}


def test_load_state_skips_malformed_shot_entries(tmp_path):
    proj = _mk(tmp_path)
    (proj / "shots.yaml").write_text(
        "defaults:\n  scene: bridge\n"
        "shots:\n"
        "  - U01_orphan\n"
        "  - 42\n"
        "  - mode: i2va\n    duration: 4.0\n"
        "  - id: U02\n    mode: ref2va\n    duration: 5.0\n",
        encoding="utf-8")

    st = load_state(str(proj))
    assert [s["id"] for s in st["shots"]] == ["U02"]


def test_find_last_batch_resolves_relative_marker(tmp_path):
    proj = _mk(tmp_path)
    qc = _put_batch_verdict(tmp_path / "Demo" / "runs" / "qc", {"shots": {}})
    _point_marker(proj, "runs/qc")

    assert find_last_batch(str(proj)) == os.path.abspath(str(qc))


def test_find_last_batch_falls_back_to_workflow_json(tmp_path, monkeypatch):
    proj = _mk(tmp_path)
    qc = _put_batch_verdict(tmp_path / "run_qc", {"shots": {}})
    job = tmp_path / "runs" / "canvas_job1"
    job.mkdir(parents=True)
    (job / "workflow.json").write_text(
        json.dumps({"project": str(proj), "batch_dir": str(qc)}), encoding="utf-8")
    monkeypatch.setenv("FANXING_RUNS_ROOT", str(tmp_path / "runs"))

    assert find_last_batch(str(proj)) == os.path.abspath(str(qc))


def test_find_last_batch_fallback_ignores_other_projects(tmp_path, monkeypatch):
    proj = _mk(tmp_path)
    other = tmp_path / "Other" / "h3"
    other.mkdir(parents=True)
    qc = _put_batch_verdict(tmp_path / "other_qc", {"shots": {}})
    job = tmp_path / "runs" / "canvas_other"
    job.mkdir(parents=True)
    (job / "workflow.json").write_text(
        json.dumps({"project": str(other), "batch_dir": str(qc)}), encoding="utf-8")
    monkeypatch.setenv("FANXING_RUNS_ROOT", str(tmp_path / "runs"))

    assert find_last_batch(str(proj)) == ""


def test_scan_takes_maps_lowercase_id_to_canonical(tmp_path):
    proj = _mk(tmp_path)
    (proj.parent / "outputs" / "u01_x.mp4").write_bytes(b"v")

    takes = scan_takes(str(proj))
    assert any(t["path"].endswith("u01_x.mp4") for t in takes["U01"])
    assert "u01" not in takes


def test_scan_takes_follows_canonical_shot_id_case(tmp_path):
    proj = _mk(tmp_path)
    (proj / "shots.yaml").write_text(
        "defaults:\n  scene: bridge\n"
        "shots:\n  - id: sh07\n    mode: i2va\n    duration: 4.0\n",
        encoding="utf-8")
    (proj.parent / "outputs" / "SH07_x.mp4").write_bytes(b"v")

    takes = scan_takes(str(proj))
    assert any(t["path"].endswith("SH07_x.mp4") for t in takes["sh07"])
    assert "SH07" not in takes
