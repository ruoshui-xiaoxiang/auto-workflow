# -*- coding: utf-8 -*-
"""繁星系统 · 主序星**数据层**（协议 §6）

⚠ 2026-11-04 用户裁定：「不需要单独的主序星按钮和面板，直接删掉」。
本文件因此**只剩数据**，独立页（starfield.html / starfield.js）与 8788 服务已摘除，
`py -m fanxing.starfield` 不再是入口。留在这里的 `scan_runs()` / `build_starfield()`
仍是 `/api/batch` 里「主序群」星系的数据源，也是 `test_fanxing.py::test_starfield_counts_batch_shots`
的被测对象——**别当死代码删**。协议 §6 本身没动（改它会翻 contract_sha256，6 个已注册 agent 全变
contract_stale 需重签；11-01 已裁"先不动"）。

规则（照抄协议，不做扩展）：
- 每颗主序星 = 一个 active agent 的入口；星图只读，不承担路由。
- 只有 registry 里有真实记录、且该 agent 有工作流/知识/记忆数据时才显示星；
  没有数据不造星。
- 点击星只切换该 agent 的 scope/filter；真正的调用仍走 CLI/HTTP，带 agent_id。
- 星的颜色/大小来自真实状态与数据量，不做装饰性假数据。
- agent 改名不换星，只换标签；停用后星进入归档态，不删除历史。
"""
import json
import math
import os
import sys
import time
from . import CONTRACT_ID, HERE
from . import agents

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
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

# ── 以下原为 8788 独立面板的 HTTP 服务（class Handler / main / __main__），
# ── 2026-11-04 按用户裁定摘除。摘除前整份备份在
# ── E:\归档区\_摘除_20261104_主序星面板\starfield.py
