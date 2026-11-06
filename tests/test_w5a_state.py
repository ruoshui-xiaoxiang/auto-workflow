# -*- coding: utf-8 -*-
"""W5a 状态止血回归（V5a-2/3/4；V5a-1 在 test_gate_e2e，V5a-6 由 W0 隔离日志证明）。

V5a-2 多个待批时 --resume last 选最近一个，run_id 正确
V5a-3 启动 B 不把 A 的 running 无条件抹成 error
V5a-4 play→draft 后 allow_degrade 不残留（含显式 --set）
"""
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

import run as R  # noqa: E402


def _cfg():
    return yaml.safe_load(Path(os.environ["AW_CONFIG_PATH"]).read_text(encoding="utf8"))


def _status_path():
    return Path(_cfg()["status_file"])


def _seed_history(hist):
    sf = _status_path()
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({"history": hist}, ensure_ascii=False, indent=2),
                  encoding="utf-8")


def _run_cli(*args, timeout=120):
    return subprocess.run([sys.executable, "run.py", *args], cwd=str(ENGINE),
                          capture_output=True, text=True, encoding="utf8",
                          errors="replace", timeout=timeout)


# ------------------------------------------------------------------ V5a-2
def test_resume_last_picks_newest_pending():
    _seed_history([
        {"workflow": "ghost_wf", "run_id": "newest_001", "status": "awaiting_human",
         "time": "2026-10-23 17:00:00"},
        {"workflow": "ghost_wf", "run_id": "middle_001", "status": "awaiting_human",
         "time": "2026-10-23 12:00:00"},
        {"workflow": "ghost_wf", "run_id": "oldest_001", "status": "awaiting_human",
         "time": "2026-10-23 09:00:00"},
    ])
    r = _run_cli("--resume", "last")
    assert "newest_001" in r.stdout, r.stdout + r.stderr
    assert "oldest_001" not in r.stdout.split("---")[0]
    # ghost_wf 不存在 ⇒ 选完就在工作流检查处停下，没进入执行（更不可能碰 GPU）
    assert r.returncode == 2
    assert "工作流不存在" in r.stderr


def test_resume_last_skips_success_and_error():
    _seed_history([
        {"workflow": "ghost_wf", "run_id": "done_001", "status": "success"},
        {"workflow": "ghost_wf", "run_id": "bad_001", "status": "error"},
        {"workflow": "ghost_wf", "run_id": "waiting_001", "status": "awaiting_human"},
    ])
    r = _run_cli("--resume", "last")
    assert "waiting_001" in r.stdout, r.stdout + r.stderr


# ------------------------------------------------------------------ V5a-3
def test_starting_b_does_not_mark_a_error():
    _seed_history([{"workflow": "a_wf", "run_id": "A_RUN", "status": "running",
                    "time": "2026-10-23 16:00:00"}])
    cfg = _cfg()
    R.update_status(cfg, "b_wf", "B_RUN", "running")
    hist = json.loads(_status_path().read_text(encoding="utf-8"))["history"]
    a = next(h for h in hist if h["run_id"] == "A_RUN")
    # 隔离下 8189 探活恒 False ⇒ 只能标待确认，不能断言"进程崩了"
    assert a["status"] == "pending_confirm", a
    assert a["status"] != "error"


def test_starting_b_keeps_own_running_entry():
    _seed_history([])
    cfg = _cfg()
    R.update_status(cfg, "b_wf", "B_RUN", "running")
    hist = json.loads(_status_path().read_text(encoding="utf-8"))["history"]
    assert hist[0]["run_id"] == "B_RUN" and hist[0]["status"] == "running"


def test_live_queue_alone_is_not_proof_of_crash(monkeypatch):
    """8189 活着也不等于"那次运行崩了"：台账没记 prompt_id，只能待确认。"""
    import tasks as T
    monkeypatch.setattr(T, "http_ok", lambda *a, **kw: True)
    _seed_history([{"workflow": "a_wf", "run_id": "A_RUN", "status": "running"}])
    R.update_status(_cfg(), "b_wf", "B_RUN", "running")
    a = next(h for h in json.loads(_status_path().read_text(encoding="utf-8"))["history"]
             if h["run_id"] == "A_RUN")
    assert a["status"] == "pending_confirm", a
    assert "探活可达" in a["detail"]


# ------------------------------------------------------------------ V5a-4
def _img(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(b"\x89PNG\r\n")
    return str(p)


def _prompt(tmp_path):
    p = tmp_path / "p.txt"
    p.write_text("TEST PROMPT", encoding="utf-8")
    return str(p)


def _inspect_plan(tmp_path, tier, extra=()):
    args = ["h3_i2va_video", "--inspect", "--tier", tier,
            "--set", f"ref_images={_img(tmp_path)}",
            "--set", f"prompt_file={_prompt(tmp_path)}"]
    for s in extra:
        args += ["--set", s]
    r = _run_cli(*args)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    return json.loads(r.stdout.split("--- run_plan ---", 1)[1])


def test_draft_clears_explicit_allow_degrade(tmp_path):
    plan = _inspect_plan(tmp_path, "draft", ["allow_degrade=true"])
    assert plan["flow"]["degrade_allowed"] is False, \
        "draft 档显式 --set allow_degrade=true 必须被按档位重算清掉"


def test_final_clears_allow_degrade(tmp_path):
    plan = _inspect_plan(tmp_path, "final")
    assert plan["flow"]["degrade_allowed"] is False
    assert plan["flow"]["approval_basis"]["preflight_strict"] == "on"


def test_play_sets_allow_degrade(tmp_path):
    plan = _inspect_plan(tmp_path, "play")
    assert plan["flow"]["degrade_allowed"] is True
