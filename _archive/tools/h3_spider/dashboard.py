# -*- coding: utf-8 -*-
"""繁星系统看板：本地只读 HTTP + 单页。

用法：
  py -3.12 -m h3_spider.dashboard --batch C:/Temp/h3_spider/batch_p15
  py -3.12 -m h3_spider.dashboard --batch ... --gate <outputs>/spider_gate.json
  py -3.12 -m h3_spider.dashboard --batch ... --kb E:/繁星/60_知识库
  py -3.12 -m h3_spider.dashboard --batch ... --workflow <run>/workflow.json
"""
import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "dashboard.html")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    batch_dir = ""
    gate_path = ""
    workflow_path = ""
    launchpad_path = ""
    kb_path = ""

    def log_message(self, fmt, *args):
        sys.stderr.write("[dash] " + (fmt % args) + "\n")

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype="application/octet-stream", chunk=65536):
        """流式发文件：视频不进内存；不做 Range，够看就行。"""
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        with open(path, "rb") as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                self.wfile.write(buf)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _canvas_body(self, cap):
        """读画布 POST 的 body，带上限（返回 ``(body, too_big)``）。

        先看 ``Content-Length``：声明超限就一个字节都不读，直接让调用方回 413；
        头缺失/无效时最多读 ``cap + 1`` 字节，多出来的按超限处理。
        """
        raw = self.headers.get("Content-Length")
        length = None
        if raw is not None:
            try:
                length = int(raw)
            except (TypeError, ValueError):
                length = None
        if length is not None:
            if length > cap:
                return b"", True
            if length <= 0:
                return b"", False
            return self.rfile.read(length), False
        data = self.rfile.read(cap + 1)
        if len(data) > cap:
            return b"", True
        return data, False

    def do_POST(self):
        u = urlparse(self.path)
        # 只有画布路由在这里读 body；/api/launch 自己读，别提前吃掉
        if (u.path in ("/api/canvas/save", "/api/canvas/apply",
                       "/api/canvas/run", "/api/canvas/shot")
                or u.path.startswith("/api/canvas/jobs/")):
            from . import canvas_api
            body, too_big = self._canvas_body(canvas_api.MAX_BODY)
            if too_big:
                self._json({"error": "请求体超过 1MB"}, 413)
                return
            if canvas_api.handle(self, "POST", self.path, "", body):
                return
        if u.path == "/api/launch":
            self._api_launch()
            return
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/projects" or u.path.startswith("/api/canvas"):
            from . import canvas_api
            if canvas_api.handle(self, "GET", self.path, u.query):
                return
        if u.path in ("/", "/index.html"):
            if not os.path.isfile(HTML_PATH):
                self._send(500, b"dashboard.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(HTML_PATH, "rb").read(), "text/html; charset=utf-8")
            return
        # 分镜画布不再是独立页：统一回主星图（项目参数保留）
        if u.path == "/canvas":
            proj = parse_qs(u.query).get("project", [""])[0]
            loc = "/map3d" + ("?project=" + quote(proj, safe="") if proj else "")
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if u.path in ("/map3d", "/map3d.html"):
            p = os.path.join(HERE, "map3d.html")
            if not os.path.isfile(p):
                self._send(404, b"map3d.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/html; charset=utf-8")
            return
        if u.path == "/map3d.js":
            p = os.path.join(HERE, "map3d.js")
            if not os.path.isfile(p):
                self._send(404, b"map3d.js missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/javascript; charset=utf-8")
            return
        # 画布模块：map3d.js 在 canvas 模式下动态 import；文件名写死，不吃用户路径
        if u.path == "/storyboard_model.js":
            p = os.path.join(HERE, "storyboard_model.js")
            if not os.path.isfile(p):
                self._send(404, b"storyboard_model.js missing",
                           "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/javascript; charset=utf-8")
            return
        if u.path == "/storyboard.js":
            p = os.path.join(HERE, "storyboard.js")
            if not os.path.isfile(p):
                self._send(404, b"storyboard.js missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/javascript; charset=utf-8")
            return
        # 实时数据流面板：纯归约 + DOM/SSE 两层，文件名写死
        if u.path in ("/live_panel_model.js", "/live_panel.js"):
            name = u.path.lstrip("/")
            p = os.path.join(HERE, name)
            if not os.path.isfile(p):
                self._send(404, (name + " missing").encode("utf-8"),
                           "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/javascript; charset=utf-8")
            return
        # 主序星独立入口与面板已于 2026-11-04 摘除（用户裁：不需要单独按钮和面板）。
        # 保留的只有数据层 `fanxing.starfield.build_starfield/scan_runs`——
        # 它是 /api/batch 里「主序群」星系的数据源（见本文件 agents_data），不是页面。
        if u.path.startswith("/vendor/"):
            rel = u.path[len("/vendor/"):]
            norm = os.path.normpath(rel).replace("\\", "/")
            root = os.path.abspath(os.path.join(HERE, "vendor"))
            p = os.path.abspath(os.path.join(root, norm))
            if (not norm.startswith("three/") or not norm.endswith(".js")
                    or os.path.commonpath([root, p]) != root or not os.path.isfile(p)):
                self._json({"error": "not found"}, 404)
                return
            self._send(200, open(p, "rb").read(), "text/javascript; charset=utf-8")
            return
        if u.path.startswith("/sky/"):
            rel = u.path[len("/sky/"):]
            norm = os.path.normpath(rel).replace("\\", "/")
            root = os.path.abspath(os.path.join(HERE, "assets", "sky"))
            p = os.path.abspath(os.path.join(root, norm))
            if (not norm.endswith((".jpg", ".jpeg", ".png"))
                    or os.path.commonpath([root, p]) != root
                    or not os.path.isfile(p)):
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
            self._send(200, open(p, "rb").read(), ctype)
            return
        if u.path == "/api/batch":
            self._api_batch()
            return
        if u.path == "/api/workflow":
            self._api_workflow()
            return
        if u.path == "/api/kb":
            self._api_kb()
            return
        if u.path in ("/launch", "/launchpad.html"):
            p = os.path.join(HERE, "launchpad.html")
            if not os.path.isfile(p):
                self._send(404, b"launchpad.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/html; charset=utf-8")
            return
        if u.path == "/api/launchpad":
            self._api_launchpad()
            return
        if u.path in ("/live", "/live.html"):
            p = os.path.join(HERE, "live.html")
            if not os.path.isfile(p):
                self._send(404, b"live.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(p, "rb").read(), "text/html; charset=utf-8")
            return
        if u.path == "/api/live":
            self._api_live(parse_qs(u.query).get("sid", [""])[0])
            return
        if u.path == "/api/shot":
            self._api_shot(parse_qs(u.query).get("sid", [""])[0])
            return
        if u.path == "/api/asset":
            q = parse_qs(u.query)
            self._api_asset(q.get("sid", [""])[0], q.get("asset", [""])[0])
            return
        self._json({"error": "not found"}, 404)

    def _api_batch(self):
        vp = os.path.join(self.batch_dir, "batch_verdict.json")
        if not os.path.isfile(vp):
            self._json({"error": "缺 batch_verdict.json", "batch_dir": self.batch_dir}, 404)
            return
        try:
            b = _read_json(vp)
        except Exception as e:
            self._json({"error": "batch_verdict 读不出: %s" % e}, 500)
            return
        shots = {}
        for sid in (b.get("shots") or {}):
            d = os.path.join(self.batch_dir, sid)
            rec = {"dir": d}
            for name in ("verdict.json", "manifest.json",
                         "assets_clean.json", "scenes_clean.json"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    try:
                        rec[name] = _read_json(p)
                    except Exception as e:
                        rec[name] = {"_error": str(e)}
            shots[sid] = rec
        gate = None
        if self.gate_path and os.path.isfile(self.gate_path):
            try:
                gate = _read_json(self.gate_path)
            except Exception as e:
                gate = {"_error": str(e)}
        agents_data = None
        try:
            from fanxing.starfield import build_starfield
            extra = [self.workflow_path] if self.workflow_path else []
            agents_data = build_starfield(
                runs_root=os.environ.get("FANXING_RUNS_ROOT", r"C:/Temp/fanxing_runs"),
                extra_workflows=extra)
        except Exception as e:
            agents_data = {"error": "starfield 不可用: %s" % e}
        try:
            from .legs import LEGS
            legs_meta = [{"id": cls.id, "check": cls.check,
                          "node_types": sorted(cls.node_types)}
                         for cls in LEGS.values()]
        except Exception as e:
            legs_meta = {"error": "legs 不可用: %s" % e}
        self._json({
            "batch": b,
            "shots": shots,
            "gate": gate,
            "gate_path": os.path.abspath(self.gate_path) if self.gate_path else "",
            "agents": agents_data,
            "legs": legs_meta,
            "batch_dir": os.path.abspath(self.batch_dir),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _launchpad_entries(self):
        p = self.launchpad_path
        if not p or not os.path.isfile(p):
            return []
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError("launchpad 读不出: %s" % e)
        entries = data.get("entries") or []
        return [e for e in entries if isinstance(e, dict) and e.get("id")]

    def _api_launchpad(self):
        try:
            entries = self._launchpad_entries()
        except Exception as e:
            self._json({"error": str(e)}, 500)
            return
        safe = [{k: e.get(k) for k in ("id", "name", "kind", "note", "target")}
                for e in entries]
        self._json({"entries": safe})

    def _api_launch(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self._json({"error": "local only"}, 403)
            return
        if self.headers.get("X-Fanxing-Launch") != "1":
            self._json({"error": "missing launch header"}, 403)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 4096:
            self._json({"error": "bad body"}, 400)
            return
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        entry_id = body.get("id")
        try:
            entries = self._launchpad_entries()
        except Exception as e:
            self._json({"error": str(e)}, 500)
            return
        entry = next((e for e in entries if e.get("id") == entry_id), None)
        if not entry:
            self._json({"error": "entry not found"}, 404)
            return
        target = os.path.normpath(os.path.expanduser(entry.get("target") or ""))
        if not target or not os.path.exists(target):
            self._json({"error": "target missing", "target": target}, 404)
            return
        kind = entry.get("kind")
        try:
            if kind == "folder":
                os.startfile(target)  # noqa: S606 - whitelist only
            elif kind == "bat":
                workdir = entry.get("workdir") or os.path.dirname(target)
                subprocess.Popen(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/c", target],
                    cwd=workdir, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            else:
                self._json({"error": "unsupported kind"}, 400)
                return
        except Exception as e:
            self._json({"error": "launch failed: %s" % e}, 500)
            return
        self._json({"ok": True, "id": entry_id, "name": entry.get("name") or entry_id})

    def _api_live(self, sid):
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", sid or ""):
            self._json({"error": "bad sid"}, 400)
            return
        d = os.path.join(self.batch_dir, sid)
        if not os.path.isdir(d):
            self._json({"error": "no such shot", "sid": sid}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        snap = os.path.join(d, "snapshots.jsonl")
        status_p = os.path.join(d, "run_status.json")
        verdict_p = os.path.join(d, "verdict.json")
        pos = 0
        last_status = None
        last_verdict = None
        last_ping = time.time()
        try:
            while True:
                if os.path.isfile(status_p):
                    try:
                        raw = open(status_p, encoding="utf-8").read()
                        if raw != last_status:
                            compact = json.dumps(json.loads(raw), ensure_ascii=False)
                            self.wfile.write(("event: status\ndata: " + compact + "\n\n")
                                             .encode("utf-8"))
                            self.wfile.flush()
                            last_status = raw
                    except (OSError, ValueError):
                        pass
                if os.path.isfile(snap):
                    with open(snap, encoding="utf-8") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for line in chunk.splitlines():
                        if line.strip():
                            self.wfile.write(("event: snapshot\ndata: " + line + "\n\n")
                                             .encode("utf-8"))
                    if chunk:
                        self.wfile.flush()
                if os.path.isfile(verdict_p):
                    try:
                        raw = open(verdict_p, encoding="utf-8").read()
                        if raw != last_verdict:
                            compact = json.dumps(json.loads(raw), ensure_ascii=False)
                            self.wfile.write(("event: verdict\ndata: " + compact + "\n\n")
                                             .encode("utf-8"))
                            self.wfile.flush()
                            last_verdict = raw
                            break
                    except (OSError, ValueError):
                        pass
                if time.time() - last_ping > 10:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.time()
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True

    def _api_kb(self):
        idx = os.path.abspath(self.kb_path or os.environ.get(
            "FANXING_KB_INDEX", r"E:/繁星/60_知识库"))
        if not os.path.isdir(idx):
            self._json({"error": "知识库目录不存在", "index": idx}, 404)
            return
        try:
            from fanxing import kb as KB
            st = KB.stats(idx, collection="all")
        except Exception as e:
            self._json({"error": "知识库 stats 失败: %s" % e, "index": idx}, 500)
            return
        cols = []
        for name in KB.COLLECTIONS:
            s = (st.get("collections") or {}).get(name)
            if not s:
                cols.append({"name": name, "status": "missing",
                             "audit": "missing", "files": 0, "chunks": 0})
                continue
            ap = os.path.join(KB.collection_dir(idx, name), "audit.json")
            audit = {}
            if os.path.isfile(ap):
                try:
                    audit = _read_json(ap)
                except Exception:
                    audit = {}
            checks = {c.get("id"): c.get("status")
                      for c in (audit.get("checks") or []) if isinstance(c, dict)}
            retro = next((c for c in (audit.get("checks") or [])
                          if c.get("id") == "retrieval"), {})
            cols.append({
                "name": name,
                "status": "ok" if audit.get("overall") == "PASS" else
                          ("block" if audit.get("overall") == "BLOCK" else "missing"),
                "audit": audit.get("overall") or "missing",
                "audit_generated_at": audit.get("generated_at"),
                "checks": checks,
                "retrieval": {"status": retro.get("status"),
                              "summary": retro.get("summary", "")},
                "files": s.get("files", 0),
                "chunks": s.get("chunks", 0),
                "fts_chunks": s.get("fts_chunks", 0),
                "dupe_refs": s.get("dupe_refs", 0),
                "built_at": s.get("built_at"),
                "path": s.get("index_dir") or KB.collection_dir(idx, name),
            })
        self._json({
            "index": idx,
            "collections": cols,
            "totals": st.get("totals") or {},
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    def _api_workflow(self):
        if not self.workflow_path or not os.path.isfile(self.workflow_path):
            self._json({"error": "no workflow", "path": self.workflow_path}, 404)
            return
        try:
            wf = _read_json(self.workflow_path)
        except Exception as e:
            self._json({"error": "workflow 读不出: %s" % e}, 500)
            return
        self._json(wf)

    def _api_asset(self, sid, asset_id):
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", sid or ""):
            self._json({"error": "bad sid"}, 400)
            return
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", asset_id or ""):
            self._json({"error": "bad asset"}, 400)
            return
        ap = os.path.join(self.batch_dir, sid, "assets_clean.json")
        if not os.path.isfile(ap):
            self._json({"error": "no assets"}, 404)
            return
        try:
            assets = _read_json(ap)
        except Exception as e:
            self._json({"error": "assets unreadable: %s" % e}, 500)
            return
        rec = next((a for a in assets if a.get("asset_id") == asset_id), None)
        if not rec:
            self._json({"error": "asset not found"}, 404)
            return
        path = rec.get("crop_path") if os.path.isfile(rec.get("crop_path") or "") else rec.get("staged")
        if not path or not os.path.isfile(path):
            self._json({"error": "asset file missing"}, 404)
            return
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self._send(200, open(path, "rb").read(), ctype)

    def _api_shot(self, sid):
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", sid or ""):
            self._json({"error": "bad sid"}, 400)
            return
        d = os.path.join(self.batch_dir, sid)
        if not os.path.isdir(d):
            self._json({"error": "no such shot", "sid": sid}, 404)
            return
        out = {"sid": sid, "dir": d}
        for name in ("manifest.json", "verdict.json", "recovered.json",
                     "spider_manifest.json", "run_status.json"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                out[name] = _read_json(p)
        for name in ("clean.txt", "mutant.txt"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                out[name.replace(".txt", "")] = _read_text(p)
        for name in ("assets_clean.json", "assets_mutant.json",
                     "scenes_clean.json", "scenes_mutant.json"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                out[name.replace(".json", "")] = _read_json(p)
        snaps = []
        p = os.path.join(d, "snapshots.jsonl")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        snaps.append(json.loads(line))
        out["snapshots"] = snaps
        self._json(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="繁星系统看板（本地只读）")
    ap.add_argument("--batch", default=r"C:/Temp/h3_spider/batch_p15")
    ap.add_argument("--gate", default="")
    ap.add_argument("--workflow", default=os.environ.get("FANXING_WORKFLOW", ""),
                    help="可选：fanxing 工作流的 workflow.json")
    ap.add_argument("--launchpad",
                    default=os.environ.get("FANXING_LAUNCHPAD",
                                           r"E:/繁星/00_启动台/launchpad.json"),
                    help="可选：启动台白名单 JSON")
    ap.add_argument("--kb", default=os.environ.get("FANXING_KB_INDEX",
                                                   r"E:/繁星/60_知识库"),
                    help="知识库索引目录（collections/）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    Handler.batch_dir = os.path.abspath(a.batch)
    Handler.gate_path = os.path.abspath(a.gate) if a.gate else ""
    Handler.workflow_path = os.path.abspath(a.workflow) if a.workflow else ""
    Handler.launchpad_path = os.path.abspath(a.launchpad) if a.launchpad else ""
    Handler.kb_path = os.path.abspath(a.kb) if a.kb else ""
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("繁星系统：%s" % url, flush=True)
    print("批次：%s" % Handler.batch_dir, flush=True)
    if Handler.gate_path:
        print("闸：%s" % Handler.gate_path, flush=True)
    if Handler.workflow_path:
        print("工作流：%s" % Handler.workflow_path, flush=True)
    if Handler.launchpad_path:
        print("启动台：%s" % Handler.launchpad_path, flush=True)
    if Handler.kb_path:
        print("知识库：%s" % Handler.kb_path, flush=True)
    if a.open:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
