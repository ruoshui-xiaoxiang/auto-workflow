# -*- coding: utf-8 -*-
"""繁星系统 · 主序星星图（协议 §6）

规则（照抄协议，不做扩展）：
- 每颗主序星 = 一个 active agent 的入口；星图只读，不承担路由。
- 只有 registry 里有真实记录、且该 agent 有工作流/知识/记忆数据时才显示星；
  没有数据不造星。
- 点击星只切换该 agent 的 scope/filter；真正的调用仍走 CLI/HTTP，带 agent_id。
- 星的颜色/大小来自真实状态与数据量，不做装饰性假数据。
- agent 改名不换星，只换标签；停用后星进入归档态，不删除历史。

用法：
  py -3.12 -m fanxing.starfield --runs C:/Temp/fanxing_runs --port 8788
"""
import argparse
import json
import math
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import CONTRACT_ID, HERE
from . import agents

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE_DIR, "starfield.html")
JS_PATH = os.path.join(HERE_DIR, "starfield.js")
DEFAULT_RUNS = os.environ.get("FANXING_RUNS_ROOT", r"C:/Temp/fanxing_runs")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _wf_shot_count(wf: dict, wf_path: str) -> int:
    """workflow.shots 为 None 表示“全部镜”；从批次结果里取真实镜数。"""
    shots = wf.get("shots")
    if isinstance(shots, list):
        return len(shots)
    bd = wf.get("batch_dir")
    if not bd:
        return 0
    if not os.path.isabs(bd):
        bd = os.path.join(os.path.dirname(wf_path), bd)
    vp = os.path.join(bd, "batch_verdict.json")
    try:
        return len(json.load(open(vp, encoding="utf-8")).get("shots") or {})
    except Exception:
        return 0


def _agg_one(agg: dict, wf: dict, wf_path: str):
    """把一个 workflow.json 聚合进统计表。"""
    aid = wf.get("agent_id") or "(unknown)"
    rec = agg.setdefault(aid, {
        "runs": 0, "pass": 0, "block": 0,
        "shots": 0, "duration_s": 0.0,
        "last_run": None, "run_ids": [],
    })
    rec["runs"] += 1
    if wf.get("overall") == "PASS":
        rec["pass"] += 1
    else:
        rec["block"] += 1
    try:
        rec["duration_s"] += float(wf.get("duration_s") or 0)
    except (TypeError, ValueError):
        pass
    shot_n = _wf_shot_count(wf, wf_path)
    rec["shots"] += shot_n
    rec["run_ids"].append(wf.get("run_id"))

    stamp = wf.get("ended_at") or wf.get("started_at") or ""
    cur = rec.get("last_run")
    if cur is None or stamp > (cur.get("ended_at") or ""):
        rec["last_run"] = {
            "run_id": wf.get("run_id"),
            "ended_at": wf.get("ended_at"),
            "overall": wf.get("overall"),
            "through": wf.get("through"),
            "execute_run": bool(wf.get("execute_run")),
            "shots": shot_n,
            "path": wf_path,
        }


def scan_runs(runs_root: str, extra_workflows=None):
    """扫描 <runs_root>/*/workflow.json，按 agent_id 聚合。

    只认 workflow.json 里真实写下的 agent_id；没有 workflow.json 的目录忽略。
    extra_workflows：额外计入的 workflow.json 路径（例如看板当前加载的那个），
    保证「当前正在看的批次」对应的 agent 也能出现在星图上。
    """
    agg = {}
    seen_paths = set()

    if runs_root and os.path.isdir(runs_root):
        for name in sorted(os.listdir(runs_root)):
            wf_path = os.path.join(runs_root, name, "workflow.json")
            if not os.path.isfile(wf_path):
                continue
            try:
                wf = _read_json(wf_path)
            except Exception:
                continue
            _agg_one(agg, wf, wf_path)
            seen_paths.add(os.path.abspath(wf_path))

    for wf_path in (extra_workflows or []):
        if not wf_path:
            continue
        p = os.path.abspath(wf_path)
        if p in seen_paths or not os.path.isfile(p):
            continue
        try:
            wf = _read_json(p)
        except Exception:
            continue
        _agg_one(agg, wf, p)
        seen_paths.add(p)

    return agg


def _magnitude(runs: int) -> float:
    """亮度 = 真实运行量，对数缩放；0 次运行给最低可见亮度。"""
    if runs <= 0:
        return 0.0
    return min(1.0, 0.30 + 0.18 * math.log2(1 + runs))


def _star_color(status: str, valid: bool, runs: int) -> str:
    if not valid:
        return "red"          # 签名失效
    if status != "active":
        return "muted"        # 归档态
    if runs <= 0:
        return "sky"          # 有记录无数据（理论上不显示）
    return "accent"           # 正常主序星


def build_starfield(registry_path=None, runs_root: str = DEFAULT_RUNS,
                    extra_workflows=None) -> dict:
    """按 §6 组装星图数据。"""
    if registry_path:
        os.environ["FANXING_REGISTRY"] = registry_path

    try:
        reg = agents.load_registry()
    except Exception as e:
        return {"error": "registry 读不出: %s" % e,
                "contract": CONTRACT_ID, "generated_at": _now()}

    run_stats = scan_runs(runs_root, extra_workflows=extra_workflows)
    stars, hidden = [], []

    for aid, rec in (reg.get("agents") or {}).items():
        try:
            agents.verify_record(rec)
            valid, err = True, None
        except Exception as e:
            valid, err = False, str(e)

        st = run_stats.get(aid, {"runs": 0, "pass": 0, "block": 0,
                                 "shots": 0, "duration_s": 0.0,
                                 "last_run": None})
        runs = st["runs"]
        has_data = runs > 0          # §6：有工作流/知识/记忆数据才算有数据
        star = {
            "agent_id": aid,
            "name": rec.get("name") or aid,
            "owner": rec.get("owner") or "",
            "status": rec.get("status"),
            "scopes": rec.get("scopes") or [],
            "joined_at": rec.get("joined_at"),
            "last_seen": rec.get("last_seen"),
            "contract": rec.get("contract"),
            "valid": valid,
            "valid_error": err,
            "runs": runs,
            "pass": st["pass"],
            "block": st["block"],
            "shots": st["shots"],
            "duration_s": round(st["duration_s"], 2),
            "last_run": st["last_run"],
            "magnitude": _magnitude(runs),
            "color": _star_color(rec.get("status"), valid, runs),
            "archived": rec.get("status") != "active",
        }

        # §6：没有数据不造星（但停用的要进归档，不删历史）
        if not has_data and rec.get("status") == "active":
            hidden.append({
                "agent_id": aid,
                "name": star["name"],
                "reason": "无工作流数据（§6 不造星）",
            })
            continue
        stars.append(star)

    # 有运行记录但 registry 里没有 → 孤儿，单独列出，不造星
    orphans = []
    known = set((reg.get("agents") or {}).keys())
    for aid, st in run_stats.items():
        if aid not in known:
            orphans.append({
                "agent_id": aid,
                "runs": st["runs"],
                "reason": "有 workflow.json 但未注册",
            })

    stars.sort(key=lambda s: (-s["runs"], s["agent_id"]))

    return {
        "contract": CONTRACT_ID,
        "contract_sha256": reg.get("contract_sha256"),
        "registry": agents.registry_path(),
        "runs_root": os.path.abspath(runs_root) if runs_root else "",
        "generated_at": _now(),
        "counts": {
            "stars": len(stars),
            "active": sum(1 for s in stars if s["status"] == "active"),
            "archived": sum(1 for s in stars if s["archived"]),
            "hidden": len(hidden),
            "orphans": len(orphans),
            "total_runs": sum(s["runs"] for s in stars),
        },
        "stars": stars,
        "hidden": hidden,
        "orphans": orphans,
    }


class Handler(BaseHTTPRequestHandler):
    registry_path = ""
    runs_root = DEFAULT_RUNS

    def log_message(self, fmt, *args):
        sys.stderr.write("[star] " + (fmt % args) + "\n")

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            if not os.path.isfile(HTML_PATH):
                self._send(500, b"starfield.html missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(HTML_PATH, "rb").read(), "text/html; charset=utf-8")
            return
        if u.path == "/starfield.js":
            if not os.path.isfile(JS_PATH):
                self._send(404, b"starfield.js missing", "text/plain; charset=utf-8")
                return
            self._send(200, open(JS_PATH, "rb").read(), "text/javascript; charset=utf-8")
            return
        if u.path == "/api/starfield":
            try:
                self._json(build_starfield(self.registry_path or None, self.runs_root))
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        self._json({"error": "not found"}, 404)


def main(argv=None):
    ap = argparse.ArgumentParser(description="繁星系统 · 主序星星图（只读）")
    ap.add_argument("--registry", default="")
    ap.add_argument("--runs", default=DEFAULT_RUNS)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)

    Handler.registry_path = os.path.abspath(a.registry) if a.registry else ""
    Handler.runs_root = os.path.abspath(a.runs) if a.runs else ""

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("繁星系统 · 主序星：%s" % url, flush=True)
    print("registry：%s" % agents.registry_path(), flush=True)
    print("runs    ：%s" % (Handler.runs_root or "(未指定)"), flush=True)
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
