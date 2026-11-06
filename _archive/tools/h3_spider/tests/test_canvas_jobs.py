# -*- coding: utf-8 -*-
import json
import threading
import time
from pathlib import Path

import pytest

from h3_spider.canvas_jobs import (JobManager, parse_run_line,
                                   qc_shot_events)


def _wait(m, job_id, states=("done", "failed", "cancelled", "gate_blocked"), timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        job = m.get(job_id)
        if job.get("status") in states:
            return job
        time.sleep(0.03)
    return m.get(job_id)


def test_start_and_done(tmp_path):
    def runner(job, emit):
        emit("hello")
        emit("world")
        return {"status": "done", "run_dir": str(tmp_path)}
    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    got = _wait(m, job["job_id"])
    assert got["status"] == "done"
    assert got["log"][-2:] == ["hello", "world"]
    assert (tmp_path / "canvas_jobs" / (job["job_id"] + ".json")).is_file()


def test_one_active_job(tmp_path):
    gate = threading.Event()

    def runner(job, emit):
        gate.wait(2)
        return {"status": "done"}
    m = JobManager(str(tmp_path), runner=runner)
    first = m.start("P", ["U01"], "run")
    with pytest.raises(Exception) as e:
        m.start("P", ["U02"], "run")
    assert getattr(e.value, "code", 0) == 409
    gate.set()
    _wait(m, first["job_id"])


def test_cancel_sticks(tmp_path):
    def runner(job, emit):
        time.sleep(1.2)
        return {"status": "done"}
    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    time.sleep(0.1)
    m.cancel(job["job_id"])
    got = _wait(m, job["job_id"], timeout=3)
    assert got["status"] == "cancelled"


def test_stale_lock_cleared(tmp_path):
    d = tmp_path / "canvas_jobs"
    d.mkdir(parents=True)
    (d / "active.lock").write_text(json.dumps({
        "job_id": "old", "pid": 999999, "started_at": time.time() - 13 * 3600
    }), encoding="utf-8")

    def runner(job, emit):
        return {"status": "done"}
    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "gate")
    assert _wait(m, job["job_id"])["status"] == "done"


def test_runner_failure_marks_failed(tmp_path):
    def runner(job, emit):
        raise RuntimeError("boom")
    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    got = _wait(m, job["job_id"])
    assert got["status"] == "failed"
    assert "boom" in (got["result"] or {}).get("error", "")


def test_existing_jobs_marked_interrupted(tmp_path):
    d = tmp_path / "canvas_jobs"
    d.mkdir(parents=True)
    (d / "job_x.json").write_text(json.dumps({"job_id": "job_x", "status": "running"}),
                                 encoding="utf-8")
    m = JobManager(str(tmp_path), runner=lambda j, e: {"status": "done"})
    assert m.get("job_x")["status"] == "interrupted"


def test_parse_run_line_states():
    assert parse_run_line("[U05] 提交 abc (multiref 4.5s)") == {
        "type": "shot", "shot": "U05", "state": "running", "source": "run"}
    waiting = parse_run_line("  [U05] 已等 4.0 分钟...")
    assert waiting["state"] == "waiting" and waiting["elapsed_s"] == 240.0
    done = parse_run_line("[U05] ✓ 6.0 分钟, 2 个视频")
    assert done["state"] == "done" and done["videos"] == 2
    assert done["elapsed_s"] == 360.0
    assert parse_run_line("[U05] ❌ 执行错误")["state"] == "failed"
    assert parse_run_line("[SPIDER] PASS PASS") is None
    assert parse_run_line("plain text") is None


def test_qc_shot_events_map_pass_block_and_missing(tmp_path):
    (tmp_path / "batch_verdict.json").write_text(json.dumps({
        "shots": {"U01": {"overall": "PASS"}, "U02": {"overall": "BLOCK"}}
    }), encoding="utf-8")
    got = qc_shot_events(str(tmp_path), ["U01", "U02", "U03"])
    assert [(x["shot"], x["state"]) for x in got] == [
        ("U01", "pass"), ("U02", "block"), ("U03", "block")]


def test_events_structured_persisted_and_final_status(tmp_path):
    def runner(job, emit):
        emit.event({"type": "stage", "stage": "precheck", "status": "running"})
        emit("hello")
        emit.event({"type": "shot", "shot": "U01", "state": "done"})
        return {"status": "done"}

    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    got = _wait(m, job["job_id"])
    types = [e.get("type") for e in got["events"]]
    assert types[0] == "job"
    assert "gating" in [e.get("status") for e in got["events"] if e["type"] == "status"]
    assert "stage" in types and "log" in types and "shot" in types
    assert got["events"][-1]["type"] == "status"
    assert got["events"][-1]["status"] == "done"
    saved = json.loads((tmp_path / "canvas_jobs" / (job["job_id"] + ".json"))
                       .read_text(encoding="utf-8"))
    assert len(saved["events"]) == len(got["events"])
    assert saved["events"][-1]["status"] == "done"


def test_recent_returns_last_finished_job(tmp_path):
    def runner(job, emit):
        return {"status": "done"}

    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "gate")
    _wait(m, job["job_id"])
    doc = m.recent()
    assert doc["active"] is None
    assert doc["recent"][0]["job_id"] == job["job_id"]


def test_recent_keeps_active_job(tmp_path):
    gate = threading.Event()

    def runner(job, emit):
        gate.wait(2)
        return {"status": "done"}

    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "gate")
    time.sleep(0.1)
    doc = m.recent()
    assert doc["active"]["job_id"] == job["job_id"]
    gate.set()
    _wait(m, job["job_id"])


def test_cancel_publishes_status_event(tmp_path):
    def runner(job, emit):
        time.sleep(1.0)
        return {"status": "done"}

    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    time.sleep(0.1)
    m.cancel(job["job_id"])
    got = _wait(m, job["job_id"], timeout=3)
    assert any(e.get("type") == "status" and e.get("status") == "cancelled"
               for e in got["events"])


def test_done_job_survives_restart(tmp_path):
    d = tmp_path / "canvas_jobs"
    d.mkdir(parents=True)
    (d / "job_done.json").write_text(json.dumps({
        "job_id": "job_done", "status": "done", "events": []
    }), encoding="utf-8")
    m = JobManager(str(tmp_path), runner=lambda j, e: {"status": "done"})
    assert m.get("job_done")["status"] == "done"
