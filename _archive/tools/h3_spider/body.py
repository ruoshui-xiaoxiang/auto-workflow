# -*- coding: utf-8 -*-
"""主体对账：期望节点 ↔ 快照 ↔ 回收哈希；支持 token/asset/scene。"""
import hashlib
import json
import os
import time
from typing import Dict, List, Tuple

from .launcher import sha1_text
from .lexer import TOKENIZER_VERSION
from .recover import recover as recover_run


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(v):
    return v if isinstance(v, str) else (v.get("text") or "")


def _assets(v):
    return [] if isinstance(v, str) else (v.get("assets") or [])


def _scenes(v):
    return [] if isinstance(v, str) else (v.get("scenes") or [])


def load_run(run_dir: str):
    manifest = json.load(open(os.path.join(run_dir, "manifest.json"), encoding="utf-8"))
    snapshots = []
    with open(os.path.join(run_dir, "snapshots.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                snapshots.append(json.loads(line))
    variants = {}
    for name, spec in manifest["variants"].items():
        if isinstance(spec, str):
            variants[name] = open(os.path.join(run_dir, spec), encoding="utf-8").read()
        else:
            variants[name] = {
                "text": open(os.path.join(run_dir, spec["text"]), encoding="utf-8").read(),
                "assets": json.load(open(os.path.join(run_dir, spec["assets"]), encoding="utf-8")),
                "scenes": json.load(open(os.path.join(run_dir, spec["scenes"]), encoding="utf-8")),
            }
    return manifest, snapshots, variants


def _node_key(n):
    return (n["variant"], n["leg"], n.get("node_type") or "token",
            n.get("target_id") if (n.get("node_type") in ("asset", "scene")) else n["start"],
            n.get("expected_code"))


def _snap_key(s):
    return (s["variant"], s["leg"], s.get("node_type") or "token",
            s.get("target_id") if (s.get("node_type") in ("asset", "scene")) else s["start"],
            s.get("code"))


def verify(run_dir: str, production_path: str = None,
           offline: bool = False,
           required_legs=None) -> Tuple[dict, int]:
    if offline:
        manifest = json.load(open(os.path.join(run_dir, "manifest.json"),
                                  encoding="utf-8"))
        snapshots = []
        with open(os.path.join(run_dir, "snapshots.jsonl"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    snapshots.append(json.loads(line))
        variants = {}
        rp = os.path.join(run_dir, "recovered.json")
        try:
            recovery = json.load(open(rp, encoding="utf-8"))
        except Exception as e:
            recovery = {"error": "缺 recovered.json：%s" % e,
                        "diff_ok": False, "production_equal": None, "nodes": {}}
    else:
        manifest, snapshots, variants = load_run(run_dir)
        try:
            recovery = recover_run(run_dir, production_path, write=False)
        except Exception as e:
            recovery = {"error": str(e), "diff_ok": False,
                        "production_equal": None, "nodes": {}}

    meta_path = os.path.join(run_dir, "run_meta.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.isfile(meta_path) else None
    manifest_sha1 = _sha1_file(os.path.join(run_dir, "manifest.json"))
    meta_ok = bool(meta) and meta.get("manifest_sha1") == manifest_sha1
    tokenizer_ok = manifest.get("tokenizer") == TOKENIZER_VERSION
    shadow_ok = bool(recovery.get("diff_ok")) and not recovery.get("error")
    production_equal = recovery.get("production_equal")

    cap_skips = {x.get("node_id"): x
                 for x in (manifest.get("capability_skips") or []) if x.get("node_id")}
    na_map = {x.get("leg"): x.get("reason") or ""
              for x in (manifest.get("not_applicable") or []) if x.get("leg")}
    if required_legs is None:
        required_legs = ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8")
    required_legs = tuple(required_legs)

    ok = True
    if not meta_ok or not tokenizer_ok or not shadow_ok or cap_skips:
        ok = False
    if production_equal is False:
        ok = False

    by_node: Dict[str, List[dict]] = {}
    by_node_any: Dict[str, List[dict]] = {}
    for s in snapshots:
        for nid in s.get("node_ids") or []:
            by_node.setdefault(nid, []).append(s)
            by_node_any.setdefault(nid, []).append(s)

    node_results = []
    rec_nodes = recovery.get("nodes") or {}
    for n in manifest["nodes"]:
        nid = n["node_id"]
        if nid in cap_skips:
            node_results.append({
                "node_id": nid, "kind": n["kind"], "leg": n["leg"],
                "node_type": n.get("node_type") or "token",
                "variant": n["variant"], "seen": False,
                "status": None, "code": None,
                "expected_code": n.get("expected_code"),
                "hash_ok": None, "result": "skipped_by_capability",
            })
            ok = False
            continue
        snaps = [s for s in by_node.get(nid, [])
                 if s["variant"] == n["variant"] and s["leg"] == n["leg"]]
        seen = bool(snaps)
        status = snaps[0]["status"] if snaps else None
        code = snaps[0].get("code") if snaps else None
        hash_ok = None
        if n["kind"] == "C":
            if nid in rec_nodes:
                hash_ok = rec_nodes[nid].get("ok")
            elif offline:
                hash_ok = False
            else:
                nt = n.get("node_type") or "token"
                if nt == "asset":
                    rec = next((a for a in _assets(variants[n["variant"]])
                                if a.get("asset_id") == n.get("target_id")), None)
                    actual = (rec or {}).get("sha1")
                elif nt == "scene":
                    rec = next((x for x in _scenes(variants[n["variant"]])
                                if x.get("scene_id") == n.get("target_id")), None)
                    actual = sha1_text(((rec or {}).get("state_text") or "") + "|" +
                                       ((rec or {}).get("state_source") or ""))
                else:
                    actual = sha1_text(_text(variants[n["variant"]])[n["start"]:n["end"]])
                hash_ok = actual == n.get("payload_sha1")

        if not seen:
            result = "wrong_leg" if nid in by_node_any else "missing"
            ok = False
        elif n["kind"] == "T":
            result = "ok" if status == "ok" else "mismatch"
            ok = ok and result == "ok"
        elif n["kind"] == "M":
            result = "ok" if (status == "error" and code == n["expected_code"]) else "mismatch"
            ok = ok and result == "ok"
        elif n["kind"] == "C":
            result = "ok" if hash_ok else "tampered"
            ok = ok and result == "ok"
        else:
            result = "unknown_kind"
            ok = False
        node_results.append({
            "node_id": nid, "kind": n["kind"], "leg": n["leg"],
            "node_type": n.get("node_type") or "token",
            "variant": n["variant"], "seen": seen, "status": status,
            "code": code, "expected_code": n.get("expected_code"),
            "hash_ok": hash_ok, "result": result,
        })

    expected_m = {_node_key(n) for n in manifest["nodes"] if n["kind"] == "M"}
    unexpected = []
    for s in snapshots:
        if s["status"] != "error":
            continue
        if _snap_key(s) not in expected_m:
            unexpected.append({"leg": s["leg"], "variant": s["variant"],
                               "node_type": s.get("node_type"),
                               "target_id": s.get("target_id"), "start": s["start"],
                               "code": s.get("code"), "text": s["text"]})
            ok = False

    legs = {}
    for leg in sorted(set(required_legs) | {s["leg"] for s in snapshots}
                      | {n["leg"] for n in manifest["nodes"]}):
        leg_nodes = [n for n in manifest["nodes"] if n["leg"] == leg]
        has_t = any(n["kind"] == "T" for n in leg_nodes)
        has_m = any(n["kind"] == "M" for n in leg_nodes)
        legs[leg] = {}
        for variant in manifest["variants"]:
            ss = [s for s in snapshots if s["leg"] == leg and s["variant"] == variant]
            missing_nodes = [n["node_id"] for n in leg_nodes
                             if n["variant"] == variant
                             and not by_node.get(n["node_id"])]
            na = (leg in na_map and not leg_nodes)
            unverified = bool(ss) and not (has_t and has_m) and not na
            missing_leg = leg not in {s["leg"] for s in snapshots}
            legs[leg][variant] = {
                "checked_n": len(ss),
                "skipped_n": sum(1 for s in ss if s["status"] == "skip"),
                "error_n": sum(1 for s in ss if s["status"] == "error"),
                "missing_n": len(missing_nodes),
                "untested": len(ss) == 0,
                "missing_leg": missing_leg,
                "missing_nodes": missing_nodes,
                "not_applicable": na,
                "not_applicable_reason": na_map.get(leg, ""),
                "unverified": unverified,
            }
            if len(ss) == 0 or missing_nodes or unverified or missing_leg:
                ok = False

    clean_errors = [s for s in snapshots if s["variant"] == "clean" and s["status"] == "error"]
    if clean_errors:
        ok = False
    m_count = sum(1 for n in manifest["nodes"] if n["kind"] == "M")
    mutant_errors = [s for s in snapshots if s["variant"] == "mutant" and s["status"] == "error"]
    if len(mutant_errors) != m_count:
        ok = False

    verdict = {
        "run_id": manifest["run_id"],
        "overall": "PASS" if ok else "BLOCK",
        "legs": legs,
        "nodes": node_results,
        "unexpected_errors": unexpected,
        "run_meta": {"present": bool(meta), "ok": meta_ok,
                     "recorded_sha1": (meta or {}).get("manifest_sha1"),
                     "current_sha1": manifest_sha1},
        "tokenizer": {"recorded": manifest.get("tokenizer"),
                      "current": TOKENIZER_VERSION, "ok": tokenizer_ok},
        "offline": bool(offline),
        "shadow": {"diff_ok": shadow_ok,
                   "error": recovery.get("error"),
                   "edits": len(recovery.get("edits") or []),
                   "production_equal": production_equal},
        "not_applicable": manifest.get("not_applicable") or [],
        "capability_skips": manifest.get("capability_skips") or [],
        "canary": {"passed": ok, "clean_errors": len(clean_errors),
                   "mutant_errors": len(mutant_errors), "expected_mutants": m_count},
        "trace_sha1": _sha1_file(os.path.join(run_dir, "snapshots.jsonl")),
        "manifest_sha1": manifest_sha1,
    }
    with open(os.path.join(run_dir, "verdict.json"), "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=1)

    spider = {
        "run_id": manifest["run_id"],
        "shot": manifest["shot"],
        "overall": verdict["overall"],
        "trace_sha1": verdict["trace_sha1"],
        "manifest_sha1": manifest_sha1,
        "tokenizer": manifest.get("tokenizer"),
        "canary": verdict["canary"],
        "shadow": verdict["shadow"],
        "not_applicable": verdict["not_applicable"],
        "capability_skips": verdict["capability_skips"],
        "recovered": {"diff_ok": recovery.get("diff_ok"),
                      "production_equal": production_equal,
                      "all_nodes_ok": recovery.get("all_nodes_ok")},
    }
    with open(os.path.join(run_dir, "spider_manifest.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(spider, f, ensure_ascii=False, indent=1)
    with open(os.path.join(run_dir, "run_status.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"status": "done", "shot": manifest["shot"],
                   "overall": verdict["overall"],
                   "snapshot_count": len(snapshots),
                   "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=1)
    return verdict, (0 if ok else 1)
