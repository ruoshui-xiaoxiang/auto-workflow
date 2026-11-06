# -*- coding: utf-8 -*-
"""遍历引擎：文本腿逐 token，资产腿逐资产，场景腿逐场景；腿保持盲。"""
import hashlib
import json
import os
import time
from typing import Dict, List, Tuple

from .model import Snapshot
from .lexer import tokenize


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parts(v):
    if isinstance(v, str):
        return {"text": v, "assets": [], "scenes": [], "meta": {}}
    return {
        "text": v.get("text") or "",
        "assets": v.get("assets") or [],
        "scenes": v.get("scenes") or [],
        "meta": v.get("meta") or {},
    }


def run(legs, variants, manifest: dict, out_dir: str) -> List[Snapshot]:
    nodes = manifest.get("nodes") or []
    text_nodes: Dict[Tuple[str, int], List[str]] = {}
    asset_nodes: Dict[Tuple[str, str], List[str]] = {}
    scene_nodes: Dict[Tuple[str, str], List[str]] = {}
    for n in nodes:
        if n.get("node_type") == "token":
            text_nodes.setdefault((n["variant"], n["start"]), []).append(n["node_id"])
        elif n.get("node_type") == "asset":
            asset_nodes.setdefault((n["variant"], n.get("target_id") or ""), []).append(n["node_id"])
        elif n.get("node_type") == "scene":
            scene_nodes.setdefault((n["variant"], n.get("target_id") or ""), []).append(n["node_id"])

    snapshots: List[Snapshot] = []
    seq = 0
    shot = manifest["shot"]
    os.makedirs(out_dir, exist_ok=True)
    snap_path = os.path.join(out_dir, "snapshots.jsonl")
    snap_f = open(snap_path, "w", encoding="utf-8", newline="\n")
    with open(os.path.join(out_dir, "run_status.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"status": "running", "shot": shot,
                   "started_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=1)

    def emit(s: Snapshot):
        snapshots.append(s)
        snap_f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
        snap_f.flush()

    def add(variant, leg, node_type, target_id, text, status, code, node_ids):
        nonlocal seq
        emit(Snapshot(
            run_id=manifest["run_id"], variant=variant, shot=shot,
            leg=leg.id, check=leg.check,
            token_id=-1 if node_type != "token" else 0,
            start=0, end=0, text=text,
            status=status, code=code,
            node_type=node_type, target_id=target_id,
            node_ids=node_ids, seq=seq,
        ))
        seq += 1

    for variant, raw in variants.items():
        parts = _parts(raw)
        ctx = parts["meta"]
        tokens = tokenize(parts["text"])
        for leg in legs:
            if "token" in leg.node_types:
                results = leg.run(tokens, parts["text"], variant, shot, ctx=ctx)
                for t in tokens:
                    status, code, _msg = results.get(t.id, ("ok", None, ""))
                    if status not in ("ok", "error", "skip"):
                        status = "error"
                    emit(Snapshot(
                        run_id=manifest["run_id"], variant=variant, shot=shot,
                        leg=leg.id, check=leg.check,
                        token_id=t.id, start=t.start, end=t.end, text=t.text,
                        status=status, code=code, node_type="token", target_id=None,
                        node_ids=text_nodes.get((variant, t.start), []), seq=seq,
                    ))
                    seq += 1

            if "asset" in leg.node_types:
                results = leg.run_assets(parts["assets"], variant, shot, ctx=ctx)
                for a in parts["assets"]:
                    aid = a["asset_id"]
                    status, code, _msg = results.get(aid, ("ok", None, ""))
                    add(variant, leg, "asset", aid, aid, status, code,
                        asset_nodes.get((variant, aid), []))

            if "scene" in leg.node_types:
                results = leg.run_scenes(parts["scenes"], variant, shot, ctx=ctx)
                for sc in parts["scenes"]:
                    sid = sc["scene_id"]
                    status, code, _msg = results.get(sid, ("ok", None, ""))
                    add(variant, leg, "scene", sid, sid, status, code,
                        scene_nodes.get((variant, sid), []))

    snap_f.close()
    with open(os.path.join(out_dir, "run_status.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"status": "snapshotted", "shot": shot,
                   "snapshot_count": len(snapshots),
                   "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=1)

    meta = {
        "run_id": manifest["run_id"],
        "shot": manifest["shot"],
        "tokenizer": manifest.get("tokenizer"),
        "manifest_sha1": _sha1_file(os.path.join(out_dir, "manifest.json")),
        "snapshot_count": len(snapshots),
    }
    with open(os.path.join(out_dir, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return snapshots
