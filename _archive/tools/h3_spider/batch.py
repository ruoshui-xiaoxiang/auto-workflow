# -*- coding: utf-8 -*-
"""12 镜批跑：逐镜建 case → 8 腿 → 对账 → 汇总覆盖率。"""
import hashlib
import json
import os
import sys

import h3_prompt_builder as B
from . import __version__ as SPIDER_VERSION
from .lexer import TOKENIZER_VERSION

from .case import build_shot_case
from .engine import run
from .recover import recover
from .body import verify
from .legs import get_legs, LEGS


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_batch(project: str, input_dir: str, out_root: str, shots=None,
              force: bool = False) -> dict:
    cards = B.load_project(project)
    ids = shots or [s["id"] for s in cards["shots"]["shots"]]
    os.makedirs(out_root, exist_ok=True)
    vp = os.path.join(out_root, "batch_verdict.json")
    if os.path.isfile(vp) and not force:
        try:
            old = json.load(open(vp, encoding="utf-8"))
            old_ids = set((old.get("shots") or {}).keys())
        except Exception:
            old_ids = set()
        if old_ids and old_ids != set(ids):
            raise ValueError(
                "输出目录已有另一组镜头的批次（%d 镜 vs 本次 %d 镜）："
                "换 --out，或加 --force 覆盖" % (len(old_ids), len(ids)))

    results = {}
    failures = []
    for sid in ids:
        prompt_path = os.path.join(project, "out", sid + ".txt")
        if not os.path.isfile(prompt_path):
            failures.append("%s: 缺 %s" % (sid, prompt_path))
            continue
        text = open(prompt_path, encoding="utf-8").read()
        run_dir = os.path.join(out_root, sid)
        run_id = "batch_%s_%s" % (sid, os.path.basename(out_root))
        variants, manifest = build_shot_case(text, sid, run_id, run_dir,
                                             project, input_dir)
        run(get_legs(), variants, manifest, run_dir)
        recover(run_dir, production_path=prompt_path, write=True)
        verdict, _code = verify(run_dir, production_path=prompt_path)
        results[sid] = verdict
        if verdict["overall"] != "PASS":
            failures.append("%s: %s" % (sid, ", ".join(
                "%s=%s" % (n["node_id"], n["result"])
                for n in verdict["nodes"] if n["result"] != "ok") or "BLOCK"))
        print("%-4s %-5s  nodes=%-2d  clean_err=%d  mutant_err=%d/%d"
              % (sid, verdict["overall"], len(verdict["nodes"]),
                 verdict["canary"]["clean_errors"],
                 verdict["canary"]["mutant_errors"],
                 verdict["canary"]["expected_mutants"]))

    coverage = {}
    for leg in LEGS:
        t = m = 0
        checked = 0
        shots_with = []
        na_shots = []
        for sid, v in results.items():
            man = json.load(open(os.path.join(out_root, sid, "manifest.json"),
                                 encoding="utf-8"))
            nt = sum(1 for n in man["nodes"] if n["leg"] == leg and n["kind"] == "T")
            nm = sum(1 for n in man["nodes"] if n["leg"] == leg and n["kind"] == "M")
            t += nt
            m += nm
            lv = v["legs"].get(leg) or {}
            checked += (lv.get("clean", {}).get("checked_n", 0) +
                        lv.get("mutant", {}).get("checked_n", 0))
            if nt or nm:
                shots_with.append(sid)
            if any(x.get("leg") == leg for x in (man.get("not_applicable") or [])):
                na_shots.append(sid)
        all_na = len(na_shots) == len(results) and not shots_with
        coverage[leg] = {"T": t, "M": m, "checked_n": checked,
                         "shots": len(shots_with),
                         "not_applicable": all_na,
                         "not_applicable_shots": na_shots}
        if (t == 0 or m == 0) and not all_na:
            failures.append("%s: 覆盖率不足 T=%d M=%d" % (leg, t, m))

    overall = "PASS" if (not failures and all(
        v["overall"] == "PASS" for v in results.values())) else "BLOCK"

    project_hashes = {
        "cards": {name: _sha1_file(os.path.join(project, name))
                  for name in ("characters.yaml", "scenes.yaml", "shots.yaml", "lexicon.yaml")
                  if os.path.isfile(os.path.join(project, name))},
        "prompts": {sid: _sha1_file(os.path.join(project, "out", sid + ".txt"))
                    for sid in results},
        "assets": {},
        "tokenizer": TOKENIZER_VERSION,
        "spider_version": SPIDER_VERSION,
    }
    for sid in results:
        ap = os.path.join(out_root, sid, "assets_clean.json")
        if not os.path.isfile(ap):
            continue
        for a in json.load(open(ap, encoding="utf-8")):
            for key in ("crop_path", "staged"):
                path = a.get(key)
                if path and os.path.isfile(path):
                    project_hashes["assets"][path] = _sha1_file(path)

    batch = {
        "overall": overall,
        "project": project,
        "shots": {sid: {
            "overall": v["overall"],
            "canary": v["canary"],
            "legs": {k: {"clean": vv.get("clean", {}).get("checked_n", 0),
                         "mutant": vv.get("mutant", {}).get("checked_n", 0)}
                     for k, vv in v["legs"].items()},
            "trace_sha1": v["trace_sha1"],
        } for sid, v in results.items()},
        "coverage": coverage,
        "project_hashes": project_hashes,
        "failures": failures,
    }
    with open(os.path.join(out_root, "batch_verdict.json"), "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=1)

    print("\n覆盖率（8 腿 × T/M）")
    for leg in sorted(coverage):
        c = coverage[leg]
        print("  %-3s T=%-3d M=%-3d checked=%-5d shots=%d"
              % (leg, c["T"], c["M"], c["checked_n"], c["shots"]))
    print("\n批次判定：%s" % overall)
    if failures:
        for x in failures:
            print("  -", x)
    return batch
