# -*- coding: utf-8 -*-
"""回收：重算影子文件 diff 与节点 payload，写 recovered.json。"""
import difflib
import hashlib
import json
import os
from typing import Dict, List, Optional, Tuple

def sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def diff_edits(clean: str, mutant: str) -> List[Dict]:
    """返回 clean→mutant 的非 equal 区间，含两侧 offset。"""
    out = []
    sm = difflib.SequenceMatcher(None, clean, mutant)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        out.append({
            "tag": tag,
            "start": i1, "end": i2,
            "m_start": j1, "m_end": j2,
            "original": clean[i1:i2],
            "mutated": mutant[j1:j2],
        })
    return out


def _canon_edits(items: List[Dict]) -> List[Tuple]:
    return sorted((x.get("tag"), int(x.get("start", 0)), int(x.get("end", 0)),
                   int(x.get("m_start", 0)), int(x.get("m_end", 0)),
                   x.get("original", ""), x.get("mutated", ""))
                  for x in (items or []))


def _payload_actual(node: Dict, variants: Dict) -> Optional[str]:
    variant = node.get("variant")
    raw = variants.get(variant)
    if raw is None:
        return None
    nt = node.get("node_type") or "token"
    if nt == "asset":
        assets = raw if isinstance(raw, dict) else {}
        rec = next((a for a in (assets.get("assets") or [])
                    if a.get("asset_id") == node.get("target_id")), None)
        return (rec or {}).get("sha1")
    if nt == "scene":
        scenes = (raw.get("scenes") or []) if isinstance(raw, dict) else []
        rec = next((x for x in scenes if x.get("scene_id") == node.get("target_id")), None)
        return sha1_text(((rec or {}).get("state_text") or "") + "|" +
                         ((rec or {}).get("state_source") or ""))
    text = raw.get("text") if isinstance(raw, dict) else raw
    return sha1_text((text or "")[int(node.get("start") or 0):
                                  int(node.get("end") or 0)])


def recover(run_dir: str, production_path: Optional[str] = None,
            write: bool = True) -> Dict:
    mp = os.path.join(run_dir, "manifest.json")
    if not os.path.isfile(mp):
        raise FileNotFoundError("缺 manifest.json：%s" % mp)
    manifest = json.load(open(mp, encoding="utf-8"))
    variants = {}
    for name, spec in (manifest.get("variants") or {}).items():
        if isinstance(spec, str):
            variants[name] = open(os.path.join(run_dir, spec), encoding="utf-8").read()
        else:
            variants[name] = {
                "text": open(os.path.join(run_dir, spec["text"]), encoding="utf-8").read(),
                "assets": json.load(open(os.path.join(run_dir, spec["assets"]),
                                         encoding="utf-8")),
                "scenes": json.load(open(os.path.join(run_dir, spec["scenes"]),
                                         encoding="utf-8")),
            }
    clean = (variants.get("clean") or {})
    clean_text = clean.get("text") if isinstance(clean, dict) else clean
    mutant = (variants.get("mutant") or {})
    mutant_text = mutant.get("text") if isinstance(mutant, dict) else mutant

    current_edits = diff_edits(clean_text or "", mutant_text or "")
    expected_edits = manifest.get("edits")
    diff_ok = expected_edits is None or _canon_edits(current_edits) == _canon_edits(expected_edits)

    prod_equal = None
    prod_sha = None
    if production_path and os.path.isfile(production_path):
        prod_sha = _sha1_file(production_path)
        clean_sha = sha1_text(clean_text or "")
        prod_equal = prod_sha == clean_sha

    nodes = {}
    for n in manifest.get("nodes") or []:
        if n.get("kind") != "C":
            continue
        actual = _payload_actual(n, variants)
        expected = n.get("payload_sha1")
        nodes[n["node_id"]] = {
            "expected": expected, "actual": actual,
            "ok": bool(expected) and actual == expected,
            "node_type": n.get("node_type") or "token",
            "target_id": n.get("target_id"),
        }

    rec = {
        "run_id": manifest.get("run_id"),
        "shot": manifest.get("shot"),
        "diff_ok": bool(diff_ok),
        "edits": current_edits,
        "expected_edits": expected_edits,
        "production_path": os.path.abspath(production_path) if production_path else None,
        "production_sha1": prod_sha,
        "clean_sha1": sha1_text(clean_text or ""),
        "production_equal": prod_equal,
        "nodes": nodes,
        "all_nodes_ok": all(x["ok"] for x in nodes.values()),
    }
    if write:
        with open(os.path.join(run_dir, "recovered.json"), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    return rec
