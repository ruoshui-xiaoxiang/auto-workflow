# -*- coding: utf-8 -*-
"""繁星完整工作流：预检 → 建稿 → 质检 → 跑前闸 →（显式）出片。

每一步都写 workflow.json；失败即 BLOCK，后续阶段标记 skipped，
不把“没跑”伪装成“通过”。
"""
import json
import os
import subprocess
import sys
import time
import uuid
from typing import Dict, List, Optional

from h3_spider import __version__ as SPIDER_VERSION

from . import CONTRACT_ID, TOOLS_DIR, __version__
from . import agents

DEFAULT_INPUT = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"
STAGES = ("precheck", "build", "qc", "gate", "run")
LABELS = {"precheck": "预检", "build": "建稿", "qc": "质检",
          "gate": "跑前闸", "run": "出片"}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _run_cmd(cmd: List[str], log_path: str, timeout: int = 6 * 3600) -> Dict:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=TOOLS_DIR, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        rc = 124
        out = e.stdout or ""
        err = (e.stderr or "") + "\n[timeout] %ss" % timeout
    dur = round(time.time() - t0, 2)
    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("$ " + " ".join(cmd) + "\n\n")
        f.write(out + "\n--- stderr ---\n" + err)
    return {"rc": rc, "duration_s": dur, "stdout": out, "stderr": err,
            "log": log_path}


def _event(on_event, **ev):
    """向前端/任务队列发结构化事件；UI 故障不能拖垮生产。"""
    if not on_event:
        return
    ev.setdefault("at", time.time())
    try:
        on_event(ev)
    except Exception:
        pass


def _stage(stages, sid, status, started=None, on_event=None, **kw):
    item = {
        "id": sid, "label": LABELS[sid], "status": status,
        "started_at": started or _now(), "ended_at": _now(),
        "duration_s": round(time.time() - (kw.pop("_t0") or time.time()), 2)
        if "_t0" in kw else None,
    }
    item.update({k: v for k, v in kw.items() if v is not None})
    stages.append(item)
    _event(on_event, type="stage", stage=sid, label=LABELS[sid],
           status=status, duration_s=item.get("duration_s"),
           summary=item.get("summary"), reason=item.get("reason"),
           error=item.get("error"))
    return item


def _skipped(stages, sid, reason, on_event=None):
    item = {
        "id": sid, "label": LABELS[sid], "status": "skipped",
        "started_at": None, "ended_at": None, "duration_s": None,
        "reason": reason,
    }
    stages.append(item)
    _event(on_event, type="stage", stage=sid, label=LABELS[sid],
           status="skipped", reason=reason)
    return item


def _emit_qc_shots(on_event, batch_dir, shots):
    """质检完成后逐镜发 pass/block；缺结果的镜头按 block 收口。"""
    if not on_event:
        return
    got = {}
    try:
        with open(os.path.join(batch_dir or "", "batch_verdict.json"),
                  encoding="utf-8") as f:
            got = (json.load(f).get("shots") or {})
    except Exception:
        got = {}
    ids = list(shots) if shots else list(got.keys())
    for sid in ids:
        item = got.get(sid) or {}
        state = "pass" if item.get("overall") == "PASS" else "block"
        _event(on_event, type="shot", shot=sid, state=state, source="qc")


def run_workflow(project: str, out_root: str, agent_id: str = "local",
                 shots: Optional[List[str]] = None,
                 input_dir: Optional[str] = None,
                 through: str = "gate",
                 skip_precheck: bool = False,
                 skip_build: bool = False,
                 execute_run: bool = False,
                 registry: Optional[str] = None,
                 on_event=None) -> Dict:
    if through not in STAGES:
        raise ValueError("through 只能是 %s" % "/".join(STAGES))
    if registry:
        os.environ["FANXING_REGISTRY"] = registry
    if agent_id == "local":
        rec = agents.ensure_local()
    else:
        rec = agents.get(agent_id, require_scope="workflow:run")
    if "workflow:run" not in (rec.get("scopes") or []):
        raise agents.AgentError("agent %s 缺 workflow:run" % agent_id)

    project = os.path.abspath(project)
    out_root = os.path.abspath(out_root)
    input_dir = os.path.abspath(input_dir or DEFAULT_INPUT)
    os.makedirs(out_root, exist_ok=True)
    run_id = "fanxing_%s_%s" % (time.strftime("%Y%m%d_%H%M%S"),
                                uuid.uuid4().hex[:6])
    started_at = _now()
    t_all = time.time()
    stages: List[Dict] = []
    batch_dir = os.path.join(out_root, "qc")
    gate_path = os.path.join(out_root, "gate.json")
    blocked = False

    def may_run(sid):
        return (not blocked) and STAGES.index(sid) <= STAGES.index(through)

    # 1) 预检
    if not may_run("precheck"):
        _skipped(stages, "precheck",
                 "到达 --through 之前" if not blocked else "上游 BLOCK",
                 on_event=on_event)
    elif skip_precheck:
        _skipped(stages, "precheck", "--skip-precheck", on_event=on_event)
    else:
        t0 = time.time()
        _event(on_event, type="stage", stage="precheck",
               label=LABELS["precheck"], status="running")
        pj = os.path.join(out_root, "precheck.json")
        cmd = [sys.executable, "h3_precheck.py", "--project", project,
               "--json", pj]
        if input_dir:
            cmd += ["--comfy-input", input_dir]
        r = _run_cmd(cmd, os.path.join(out_root, "logs", "precheck.log"))
        issues = []
        if os.path.isfile(pj):
            try:
                issues = json.load(open(pj, encoding="utf-8"))
            except Exception:
                issues = []
        errs = sum(1 for i in issues if i.get("level") == "error")
        warns = sum(1 for i in issues if i.get("level") == "warn")
        ok = r["rc"] == 0 and not errs
        _stage(stages, "precheck", "ok" if ok else "block", _t0=t0,
               summary="%d error / %d warn" % (errs, warns),
               artifacts={"json": pj}, log=r["log"], on_event=on_event)
        if not ok:
            blocked = True

    # 2) 建稿
    if not may_run("build"):
        _skipped(stages, "build",
                 "到达 --through 之前" if not blocked else "上游 BLOCK",
                 on_event=on_event)
    elif skip_build:
        _skipped(stages, "build", "--skip-build（使用项目 out/ 现稿）",
                 on_event=on_event)
    else:
        t0 = time.time()
        _event(on_event, type="stage", stage="build",
               label=LABELS["build"], status="running")
        prompt_dir = os.path.join(project, "out")
        cmd = [sys.executable, "h3_prompt_builder.py", "build",
               "--project", project, "--out-dir", prompt_dir]
        if shots:
            cmd += ["--only"] + list(shots)
        r = _run_cmd(cmd, os.path.join(out_root, "logs", "build.log"))
        report_path = os.path.join(prompt_dir, "build_report.json")
        report = []
        if os.path.isfile(report_path):
            try:
                report = json.load(open(report_path, encoding="utf-8"))
            except Exception:
                report = []
        failed = [x for x in report if not x.get("ok")]
        ok = r["rc"] == 0 and not failed
        _stage(stages, "build", "ok" if ok else "block", _t0=t0,
               summary="%d 镜 / %d 失败" % (len(report), len(failed)),
               artifacts={"dir": prompt_dir, "report": report_path},
               log=r["log"], on_event=on_event)
        if not ok:
            blocked = True

    # 3) QC
    if not may_run("qc"):
        _skipped(stages, "qc",
                 "到达 --through 之前" if not blocked else "上游 BLOCK",
                 on_event=on_event)
    else:
        t0 = time.time()
        _event(on_event, type="stage", stage="qc",
               label=LABELS["qc"], status="running")
        try:
            from h3_spider.batch import run_batch
            batch = run_batch(project, input_dir, batch_dir, shots=shots)
            ok = batch.get("overall") == "PASS"
            summary = "%s · %d 镜 / %d 失败" % (
                batch.get("overall"), len(batch.get("shots") or {}),
                len(batch.get("failures") or []))
            _stage(stages, "qc", "ok" if ok else "block", _t0=t0,
                   summary=summary,
                   artifacts={"batch_dir": batch_dir,
                              "batch_verdict": os.path.join(batch_dir, "batch_verdict.json")},
                   log=None, on_event=on_event)
            _emit_qc_shots(on_event, batch_dir, shots)
            if not ok:
                blocked = True
        except Exception as e:
            _stage(stages, "qc", "error", _t0=t0, error=str(e),
                   artifacts={"batch_dir": batch_dir}, on_event=on_event)
            for sid in shots or []:
                _event(on_event, type="shot", shot=sid, state="block", source="qc")
            blocked = True

    # 4) 闸
    if not may_run("gate"):
        _skipped(stages, "gate",
                 "到达 --through 之前" if not blocked else "上游 BLOCK",
                 on_event=on_event)
    else:
        t0 = time.time()
        _event(on_event, type="stage", stage="gate",
               label=LABELS["gate"], status="running")
        try:
            from h3_spider.gate import check_batch_gate
            ok, reasons, info = check_batch_gate(project, batch_dir, shots)
            with open(gate_path, "w", encoding="utf-8") as f:
                json.dump({"ok": ok, "reasons": reasons, "info": info},
                          f, ensure_ascii=False, indent=1)
            _stage(stages, "gate", "ok" if ok else "block", _t0=t0,
                   summary="PASS" if ok else "拒跑：%d 条原因" % len(reasons),
                   artifacts={"gate": gate_path}, on_event=on_event)
            if not ok:
                blocked = True
        except Exception as e:
            _stage(stages, "gate", "error", _t0=t0, error=str(e),
                   on_event=on_event)
            blocked = True

    # 5) 出片（显式）
    if not may_run("run"):
        _skipped(stages, "run",
                 "到达 --through 之前" if not blocked else "上游 BLOCK",
                 on_event=on_event)
    elif not execute_run:
        _skipped(stages, "run", "未显式 --execute-run（不提交 GPU）",
                 on_event=on_event)
    else:
        t0 = time.time()
        _event(on_event, type="stage", stage="run",
               label=LABELS["run"], status="running")
        run_out = os.path.join(out_root, "run")
        cmd = [sys.executable, "h3_run_project.py", "--project", project,
               "--out", run_out, "--spider-batch", batch_dir]
        if shots:
            cmd += ["--only"] + list(shots)
        r = _run_cmd(cmd, os.path.join(out_root, "logs", "run.log"))
        ok = r["rc"] == 0
        _stage(stages, "run", "ok" if ok else "block", _t0=t0,
               summary="出片完成" if ok else "出片失败/拒跑",
               artifacts={"dir": run_out}, log=r["log"], on_event=on_event)
        if not ok:
            blocked = True

    overall = "BLOCK" if blocked or any(
        s["status"] in ("block", "error") for s in stages) else "PASS"
    wf = {
        "version": 1,
        "run_id": run_id,
        "agent_id": agent_id,
        "agent_name": rec.get("name"),
        "contract": CONTRACT_ID,
        "fanxing_version": __version__,
        "spider_version": SPIDER_VERSION,
        "project": project,
        "input_dir": input_dir,
        "shots": list(shots) if shots else None,
        "through": through,
        "execute_run": bool(execute_run),
        "overall": overall,
        "started_at": started_at,
        "ended_at": _now(),
        "duration_s": round(time.time() - t_all, 2),
        "batch_dir": batch_dir,
        "gate": gate_path,
        "stages": stages,
    }
    wf_path = os.path.join(out_root, "workflow.json")
    with open(wf_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(wf, f, ensure_ascii=False, indent=1)
    wf["path"] = wf_path
    _event(on_event, type="workflow", overall=overall, run_id=run_id,
           duration_s=wf["duration_s"], path=wf_path)
    agents.touch(agent_id)
    return wf
