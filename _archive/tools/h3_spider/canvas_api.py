# -*- coding: utf-8 -*-
"""画布 API：JSON 与只读资源。

`handle` 是给 ``dashboard.Handler`` 用的分发器：返回 ``True`` 表示这个请求已经
处理并回过包，``False`` 表示不是画布路由（调用方继续走自己的 404）。所有异常
都在这里收口——参数/校验类走 ``CanvasError.code``，其余（shots.yaml 结构坏掉、
磁盘 IO 之类）统一 500，不给看板丢栈。

除 ``/api/canvas/save``、``/api/canvas/apply``、``/api/canvas/shot`` 之外的
路径都是只读的：``/api/canvas/asset`` 只发白名单目录里的文件。

写接口（所有 POST，含后续的 run/cancel）先过 Origin/Host 守卫：只认本机主机名，
挡掉别家网页 CSRF 与 DNS rebinding；两个头都缺时放行，方便 curl 和测试。
"""
import json
import mimetypes
import os
import queue
import sys
import time
import traceback
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .canvas_apply import add_shot, apply_draft, delete_shot
from .canvas_paths import (CanvasError, is_within, list_projects,
                           remember_project, resolve_project)
from .canvas_state import load_state
from .canvas_store import save_canvas

MAX_BODY = 1024 * 1024
# 写接口只认这两个主机名（不带端口比较）
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def handle(handler, method, path, query="", body=b""):
    u = urlparse(path)
    q = parse_qs(query)
    try:
        if method == "POST":
            _guard_write(handler)
        if method == "GET" and u.path == "/api/projects":
            handler._json({"projects": list_projects()})
            return True
        if method == "GET" and u.path == "/api/canvas":
            project = resolve_project(q.get("project", [""])[0])
            handler._json(load_state(project))
            return True
        if method == "GET" and u.path == "/api/canvas/asset":
            _asset(handler, q)
            return True
        if method == "POST" and u.path == "/api/canvas/save":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            remember_project(project)
            handler._json({"ok": True, "canvas": save_canvas(project, payload)})
            return True
        if method == "POST" and u.path == "/api/canvas/apply":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            drafts = payload.get("shots")
            if drafts is None:
                drafts = []
            if not isinstance(drafts, list):
                raise CanvasError("shots 必须是数组", 400)
            if not drafts:
                raise CanvasError("没有要应用的镜头", 400)
            edges = payload.get("edges") or []
            anchors = payload.get("anchors") or {}
            dry = bool(payload.get("dry_run"))
            if payload.get("per_shot") and len(drafts) > 1:
                results = []
                for d in drafts:
                    try:
                        r = apply_draft(project, [d], edges, anchors, dry_run=dry)
                    except CanvasError as e:
                        r = {"ok": False, "error": str(e)}
                    results.append({"id": d.get("id"), **r})
                ok = all(x.get("ok") for x in results)
                handler._json({"ok": ok, "results": results}, 200 if ok else 422)
                return True
            result = apply_draft(project, drafts, edges, anchors, dry_run=dry)
            handler._json(result, 200 if result.get("ok") else 422)
            return True
        if method == "POST" and u.path == "/api/canvas/shot":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            if payload.get("action") == "add":
                nid = add_shot(project, payload.get("template") or "U01")
                handler._json({"ok": True, "id": nid})
                return True
            if payload.get("action") == "delete":
                delete_shot(project, payload.get("id"))
                handler._json({"ok": True})
                return True
            raise CanvasError("action 只能是 add/delete", 400)
        if method == "POST" and u.path == "/api/canvas/run":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            shots = payload.get("shots") or []
            if not isinstance(shots, list) or not shots:
                raise CanvasError("没有选择镜头", 400)
            if not payload.get("confirm"):
                raise CanvasError("缺 confirm，拒绝提交 GPU", 400)
            stage = payload.get("stage") or "run"
            if stage not in ("gate", "run"):
                raise CanvasError("stage 只能是 gate/run", 400)
            if stage == "run" and not health_ok():
                raise CanvasError("8189 不可用，先启动 ComfyUI", 503)
            handler._json(_manager().start(project, shots, stage))
            return True
        if method == "GET" and u.path == "/api/canvas/jobs":
            handler._json(_manager().recent())
            return True
        if method == "GET" and u.path.startswith("/api/canvas/jobs/") and u.path.endswith("/events"):
            job_id = u.path.split("/")[4]
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            handler.send_header("Cache-Control", "no-cache")
            handler.end_headers()
            # 先订阅再读状态，避免“状态已读、任务刚好结束”之间漏掉终态。
            q = _manager().subscribe(job_id)
            job = _manager().get(job_id)
            if job:
                snap = {"type": "status", "status": job.get("status"),
                        "ended_at": job.get("ended_at"), "at": time.time()}
                try:
                    handler.wfile.write(("data: " + json.dumps(snap, ensure_ascii=False) +
                                         "\n\n").encode("utf-8"))
                    handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return True
                if job.get("status") in ("done", "failed", "cancelled",
                                         "gate_blocked", "interrupted"):
                    return True
            while True:
                try:
                    ev = q.get(timeout=15)
                    payload = ev if isinstance(ev, dict) else {"type": "log", "line": ev}
                    handler.wfile.write(("data: " + json.dumps(payload, ensure_ascii=False) +
                                         "\n\n").encode("utf-8"))
                except queue.Empty:
                    handler.wfile.write(b": ping\n\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                try:
                    handler.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
            return True
        if method == "GET" and u.path.startswith("/api/canvas/jobs/"):
            job_id = u.path.rstrip("/").rsplit("/", 1)[-1]
            job = _manager().get(job_id)
            if not job:
                raise CanvasError("任务不存在", 404)
            handler._json(job)
            return True
        if method == "POST" and u.path.startswith("/api/canvas/jobs/") and u.path.endswith("/cancel"):
            job_id = u.path.split("/")[4]
            handler._json(_manager().cancel(job_id))
            return True
    except CanvasError as e:
        handler._json({"error": str(e)}, e.code)
        return True
    except Exception:
        # 细节只进 stderr，别让磁盘路径/堆栈跟着响应跑出去
        sys.stderr.write("[canvas] %s %s 失败\n" % (method, u.path))
        traceback.print_exc(file=sys.stderr)
        handler._json({"error": "画布接口失败"}, 500)
        return True
    return False


def _body(raw):
    """解析请求体；坏 JSON/非对象一律 400，别把半截数据塞进下游。"""
    if not raw:
        return {}
    if len(raw) > MAX_BODY:
        raise CanvasError("请求体超过 1MB", 413)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise CanvasError("JSON 解析失败：%s" % e, 400)
    if not isinstance(payload, dict):
        raise CanvasError("请求体必须是 JSON 对象", 400)
    return payload


_JOB_MANAGER = None


def _manager():
    global _JOB_MANAGER
    if _JOB_MANAGER is None:
        from .canvas_jobs import JobManager
        _JOB_MANAGER = JobManager()
    return _JOB_MANAGER


def health_ok():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8189/system_stats", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _host_name(value):
    """从 ``Host``/``Origin`` 里取主机名（带端口也认）；取不出给空串。"""
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "//" in raw else "//" + raw)
        return (parsed.hostname or "").lower()
    except ValueError:
        return ""


def _guard_write(handler):
    """写接口的 Origin/Host 守卫；两个头都缺（curl/测试）时放行。

    回包不回显客户端给的域名（避免反射内容），要排查就去看 stderr。
    """
    headers = getattr(handler, "headers", None) or {}
    origin = headers.get("Origin")
    if origin and _host_name(origin) not in LOCAL_HOSTS:
        raise CanvasError("Origin 不是本机", 403)
    host = headers.get("Host")
    if host and _host_name(host) not in LOCAL_HOSTS:
        raise CanvasError("Host 不是本机", 403)


def _is_drive_root(path):
    """``C:\\`` 这类盘根不能当白名单根（等于放行整盘）。"""
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return True
    return p.parent == p


def _allowed_roots(project, state):
    """白名单根：项目目录 + 项目根 + 素材根 + 记住过的 job 目录。

    只留真实存在的目录；空值、盘根一律丢掉——根不存在时没有可比的边界。
    """
    from .canvas_state import _remembered_runs
    raw = [state.get("project") or project]
    if state.get("project_root"):
        raw.append(state["project_root"])
    raw += list(state.get("asset_roots") or [])
    raw += _remembered_runs(project)
    out, seen = [], set()
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        p = os.path.abspath(item)
        if _is_drive_root(p) or not os.path.isdir(p):
            continue
        key = os.path.normcase(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _within(target, roots):
    """``target`` 是否在任一 ``root`` 之内。

    判定走 ``canvas_paths.is_within``（``Path.resolve`` + ``relative_to``），
    junction/symlink 先解析成真实路径：根内挂一个指向根外的联接，不会因为
    字面前缀相同被放行；跨盘符 ``relative_to`` 抛 ValueError，按越界处理。
    """
    if not isinstance(target, str) or not target.strip():
        return False
    for root in roots or []:
        if not isinstance(root, str) or not root.strip():
            continue
        if not os.path.isdir(root):
            continue
        try:
            if is_within(target, root):
                return True
        except (OSError, ValueError):
            continue
    return False


def _asset(handler, q):
    """只读资源：白名单 = 项目目录 + 项目根 + 素材根 + 记住过的 job 目录。"""
    raw = q.get("path", [""])[0]
    if not isinstance(raw, str) or not raw.strip():
        raise CanvasError("缺 path 参数", 400)
    project = resolve_project(q.get("project", [""])[0])
    state = load_state(project)
    target = os.path.abspath(raw)
    if not _within(target, _allowed_roots(project, state)):
        raise CanvasError("资源路径越界", 403)
    if not os.path.isfile(target):
        raise CanvasError("资源不存在", 404)
    ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
    stream = getattr(handler, "_send_file", None)
    if callable(stream):
        stream(target, ctype)
        return
    with open(target, "rb") as f:
        handler._send(200, f.read(), ctype)
