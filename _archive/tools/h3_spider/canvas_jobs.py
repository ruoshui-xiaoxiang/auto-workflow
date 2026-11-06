# -*- coding: utf-8 -*-
"""单 GPU 任务队列：状态机、结构化事件、日志环、取消、SSE 订阅。"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .canvas_paths import CanvasError
from .canvas_store import read_json, write_json_atomic

DEFAULT_RUNS_ROOT = r"C:/Temp/fanxing_runs"
ACTIVE_STATES = ("queued", "gating", "running")
TERMINAL_STATES = ("done", "failed", "cancelled", "gate_blocked", "interrupted")
MAX_EVENTS = 300
MAX_LOG = 400

_RUN_SHOT_RE = re.compile(r"^\s*\[([A-Za-z0-9_]+)\]\s*(.*)$")
_MINUTES_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*分钟")
_VIDEOS_RE = re.compile(r"([0-9]+)\s*个视频")


def _pid_alive(pid):
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % int(pid)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        return str(pid) in (out.stdout or "")
    except Exception:
        return False


def parse_run_line(line):
    """把 h3_run_project 的 [U05] ... 输出解析成 shot 事件；不认识的行返回 None。"""
    m = _RUN_SHOT_RE.match(str(line or ""))
    if not m:
        return None
    sid, rest = m.group(1), m.group(2).strip()
    if rest.startswith("提交"):
        return {"type": "shot", "shot": sid, "state": "running", "source": "run"}
    if rest.startswith("已等"):
        mins = _MINUTES_RE.search(rest)
        ev = {"type": "shot", "shot": sid, "state": "waiting", "source": "run"}
        if mins:
            ev["elapsed_s"] = round(float(mins.group(1)) * 60, 1)
        return ev
    if rest.startswith("✓"):
        mins = _MINUTES_RE.search(rest)
        videos = _VIDEOS_RE.search(rest)
        ev = {"type": "shot", "shot": sid, "state": "done", "source": "run"}
        if mins:
            ev["elapsed_s"] = round(float(mins.group(1)) * 60, 1)
        if videos:
            ev["videos"] = int(videos.group(1))
        return ev
    if rest.startswith("❌"):
        return {"type": "shot", "shot": sid, "state": "failed", "source": "run"}
    return None


def qc_shot_events(batch_dir, shots):
    """读 batch_verdict.json，给每镜发 pass/block；缺结果按 block 处理。"""
    path = os.path.join(batch_dir or "", "batch_verdict.json")
    try:
        with open(path, encoding="utf-8") as f:
            verdict = json.load(f)
    except Exception:
        return []
    got = verdict.get("shots") or {}
    out = []
    for sid in shots or []:
        item = got.get(sid) or {}
        state = "pass" if item.get("overall") == "PASS" else "block"
        out.append({"type": "shot", "shot": sid, "state": state, "source": "qc"})
    return out


class JobManager:
    def __init__(self, runs_root=None, runner=None):
        root = runs_root or os.environ.get("FANXING_RUNS_ROOT") or DEFAULT_RUNS_ROOT
        self.runs_root = Path(root)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.runner = runner or default_runner
        self.jobs = {}
        self.subs = {}
        self.lock = threading.Lock()
        self.active = None
        self.lock_path = self.runs_root / "canvas_jobs" / "active.lock"
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    def _load_existing(self):
        for p in (self.runs_root / "canvas_jobs").glob("*.json"):
            doc = read_json(str(p), {})
            if not doc.get("job_id"):
                continue
            # 只打断真正没跑完的任务；已完成的历史保留，供面板刷新后恢复。
            if doc.get("status") in ACTIVE_STATES or not doc.get("status"):
                doc["status"] = "interrupted"
            doc.setdefault("events", [])
            doc.setdefault("log", [])
            self.jobs[doc["job_id"]] = doc

    def _check_stale_lock(self):
        doc = read_json(str(self.lock_path), {}) or {}
        if not doc:
            return
        age = time.time() - float(doc.get("started_at") or 0)
        pid = doc.get("pid")
        if age < 12 * 3600 and pid and _pid_alive(pid):
            raise CanvasError("已有任务在跑：%s" % doc.get("job_id"), 409)
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    def _publish(self, job, ev):
        """事件写入环形缓存并推给当前 SSE 订阅者。"""
        if not isinstance(ev, dict):
            return {}
        item = dict(ev)
        item.setdefault("at", time.time())
        events = job.setdefault("events", [])
        events.append(item)
        if len(events) > MAX_EVENTS:
            del events[:-MAX_EVENTS]
        for q in list(self.subs.get(job["job_id"], [])):
            q.put(item)
        return item

    def start(self, project, shots, stage="run"):
        with self.lock:
            self._check_stale_lock()
            if self.active:
                cur = self.jobs.get(self.active) or {}
                if cur.get("status") in ACTIVE_STATES:
                    raise CanvasError("已有任务在跑：%s" % self.active, 409)
            job_id = "job_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
            job = {
                "job_id": job_id, "project": str(project), "shots": list(shots),
                "stage": stage, "status": "queued", "started_at": time.time(),
                "ended_at": None, "log": [], "events": [], "result": None,
            }
            self.jobs[job_id] = job
            self.subs[job_id] = []
            self.active = job_id
            write_json_atomic({"job_id": job_id, "pid": os.getpid(),
                               "started_at": time.time()}, str(self.lock_path))
            self._publish(job, {"type": "job", "job_id": job_id,
                                "project": str(project), "shots": list(shots),
                                "stage": stage, "started_at": job["started_at"]})
            self._persist(job)
            threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
            return dict(job)

    def _run(self, job_id):
        job = self.jobs[job_id]
        job["status"] = "gating"
        self._publish(job, {"type": "status", "status": "gating"})
        self._persist(job)

        def event(ev):
            self._publish(job, ev)

        def emit(line):
            text = str(line).rstrip()
            if not text:
                return
            job["log"].append(text)
            job["log"] = job["log"][-MAX_LOG:]
            self._publish(job, {"type": "log", "line": text})

        # 兼容现有 runner(job, emit)：事件入口挂在 emit 上，旧测试不用改签名。
        emit.event = event

        try:
            out = self.runner(job, emit) or {}
            job["result"] = out
            if job.get("status") != "cancelled":
                job["status"] = out.get("status") or "done"
        except Exception as e:
            if job.get("status") != "cancelled":
                job["status"] = "failed"
                job["result"] = {"error": str(e)}
                emit("ERROR " + str(e))
        finally:
            job["ended_at"] = time.time()
            self._publish(job, {"type": "status", "status": job.get("status"),
                                "ended_at": job["ended_at"]})
            self._persist(job)
            with self.lock:
                if self.active == job_id:
                    self.active = None
                doc = read_json(str(self.lock_path), {}) or {}
                if doc.get("job_id") == job_id:
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass

    def get(self, job_id):
        job = self.jobs.get(job_id)
        return dict(job) if job else {}

    def recent(self, limit=3):
        """当前任务 + 最近完成的任务，供刷新后恢复面板。"""
        jobs = sorted(self.jobs.values(),
                      key=lambda j: float(j.get("started_at") or 0), reverse=True)
        active = next((j for j in jobs if j.get("status") in ACTIVE_STATES), None)
        out = []
        for j in jobs:
            if active is not None and j["job_id"] == active["job_id"]:
                continue
            out.append(dict(j))
            if len(out) >= limit:
                break
        return {"active": dict(active) if active else None, "recent": out}

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            raise CanvasError("任务不存在", 404)
        if job.get("status") in TERMINAL_STATES:
            return dict(job)
        job["status"] = "cancelled"
        pid = (job.get("result") or {}).get("pid")
        if pid:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           capture_output=True)
        self._publish(job, {"type": "status", "status": "cancelled"})
        self._persist(job)
        return dict(job)

    def subscribe(self, job_id):
        q = queue.Queue()
        self.subs.setdefault(job_id, []).append(q)
        return q

    def _persist(self, job):
        d = self.runs_root / "canvas_jobs"
        d.mkdir(parents=True, exist_ok=True)
        write_json_atomic(job, str(d / (job["job_id"] + ".json")))


def default_runner(job, emit):
    from fanxing.workflow import run_workflow
    from .canvas_state import remember_run

    event = getattr(emit, "event", None)

    def bridge(ev):
        if event:
            event(ev)
        # 质检是全批一起跑：阶段开始先把本次镜头点亮，结束后再按 verdict 逐镜收口。
        if (event and ev.get("type") == "stage" and ev.get("stage") == "qc"
                and ev.get("status") == "running"):
            for sid in job.get("shots") or []:
                event({"type": "shot", "shot": sid, "state": "running",
                       "source": "qc"})

    root = os.environ.get("FANXING_RUNS_ROOT") or DEFAULT_RUNS_ROOT
    out = Path(root) / ("canvas_" + job["job_id"])
    wf = run_workflow(job["project"], str(out), agent_id="local",
                      shots=job["shots"], through="gate", on_event=bridge)
    emit("gate " + str(wf.get("overall") or "?"))
    if job.get("status") == "cancelled":
        return {"status": "cancelled"}
    if wf.get("overall") != "PASS":
        return {"status": "gate_blocked", "workflow": str(out / "workflow.json"),
                "reasons": [s.get("reason") for s in (wf.get("stages") or [])
                            if s.get("status") in ("block", "error")]}
    if job.get("stage") != "run":
        return {"status": "done", "workflow": str(out / "workflow.json")}
    batch = wf.get("batch_dir")
    cmd = [sys.executable, "h3_run_project.py", "--project", job["project"],
           "--out", str(out / "run"), "--spider-batch", batch, "--only"] + job["shots"]
    if event:
        event({"type": "status", "status": "running"})
        event({"type": "stage", "stage": "run", "label": "出片",
               "status": "running"})
    t0 = time.time()
    p = subprocess.Popen(
        cmd, cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1)
    job["result"] = {"pid": p.pid}
    seen = {}
    for line in p.stdout:
        emit(line)
        sev = parse_run_line(line)
        if sev:
            seen[sev["shot"]] = sev.get("state")
            if event:
                event(sev)
    code = p.wait()
    # 进程非零退出、或某镜根本没出结果时，不能把它留成“运行中”。
    # 手动取消不是失败，不要把还在跑的镜头刷成红色。
    if job.get("status") != "cancelled":
        for sid in job.get("shots") or []:
            if seen.get(sid) not in ("done", "failed"):
                if event:
                    event({"type": "shot", "shot": sid, "state": "failed",
                           "source": "run"})
    if event:
        event({"type": "stage", "stage": "run", "label": "出片",
               "status": "block" if job.get("status") == "cancelled"
               else ("ok" if code == 0 else "block"),
               "duration_s": round(time.time() - t0, 2),
               "summary": "已取消" if job.get("status") == "cancelled"
               else ("出片完成" if code == 0 else "出片失败")})
    remember_run(job["project"], str(out / "run"))
    return {"status": "done" if code == 0 else "failed",
            "run_dir": str(out / "run"), "exit": code}
