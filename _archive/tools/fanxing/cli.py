# -*- coding: utf-8 -*-
"""繁星系统 CLI：agent 自助接入 + 完整工作流 + 协议查看。"""
import argparse
import json
import os
import sys

from . import CONTRACT_ID, CONTRACT_PATH, __version__
from . import agents
from .workflow import run_workflow, STAGES


def _print_agent(rec, as_json=False):
    if as_json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return
    print("%-14s %-10s %-8s %s" % (
        rec.get("agent_id"), rec.get("name"), rec.get("status"),
        ",".join(rec.get("scopes") or [])))


def cmd_agent(args) -> int:
    if args.action == "join":
        try:
            rec = agents.join(
                args.id, args.name or args.id, args.owner or "",
                scopes=args.scope or None,
                accept_contract=args.accept_contract,
                force=args.force,
            )
        except agents.AgentError as e:
            print("[AGENT] %s" % e, file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(rec, ensure_ascii=False, indent=1))
            return 0
        print("[AGENT] joined %s · %s" % (rec["agent_id"], rec["contract"]))
        print("  agent_signature : %s…" % rec["agent_signature"][:16])
        print("  system_signature: %s…" % rec["system_signature"][:16])
        return 0
    if args.action == "list":
        rows = agents.list_agents()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                _print_agent(r)
                if not r.get("valid"):
                    print("  ! %s" % r.get("error"))
        return 0
    if args.action == "show":
        try:
            rec = agents.get(args.id)
        except agents.AgentError as e:
            print("[AGENT] %s" % e, file=sys.stderr)
            return 2
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    if args.action == "revoke":
        try:
            rec = agents.revoke(args.id)
        except agents.AgentError as e:
            print("[AGENT] %s" % e, file=sys.stderr)
            return 2
        print("[AGENT] revoked %s" % rec["agent_id"])
        return 0
    print("[AGENT] unknown action", file=sys.stderr)
    return 2


def cmd_workflow(args) -> int:
    try:
        wf = run_workflow(
            args.project, args.out, agent_id=args.agent, shots=args.shots,
            input_dir=args.input, through=args.through,
            skip_precheck=args.skip_precheck, skip_build=args.skip_build,
            execute_run=args.execute_run, registry=args.registry,
        )
    except (agents.AgentError, ValueError) as e:
        print("[WORKFLOW] %s" % e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(wf, ensure_ascii=False, indent=1))
    else:
        print("=" * 66)
        print("繁星工作流 · %s · %s" % (wf["run_id"], wf["overall"]))
        print("agent=%s  through=%s  shots=%s"
              % (wf["agent_id"], wf["through"],
                 ",".join(wf["shots"]) if wf.get("shots") else "all"))
        print("=" * 66)
        for s in wf["stages"]:
            extra = s.get("summary") or s.get("reason") or ""
            print("  %-8s %-8s %6s  %s" % (
                s["label"], s["status"],
                ("%.2fs" % s["duration_s"]) if s.get("duration_s") is not None else "-",
                extra))
        print("  workflow:", wf["path"])
    return 0 if wf["overall"] == "PASS" else 1


def cmd_contract(args) -> int:
    print("contract:", CONTRACT_ID)
    print("sha256  :", agents.contract_sha256())
    print("path    :", CONTRACT_PATH)
    return 0


def _parse_weights(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError("--weight 需 name=value：%r" % item)
        name, val = item.split("=", 1)
        out[name.strip()] = float(val)
    return out


def cmd_kb(args) -> int:
    from . import kb
    try:
        weights = _parse_weights(args.weight)
        collection_weights = _parse_weights(
            getattr(args, "collection_weight", None))
        if args.action in ("ingest", "build"):
            if args.collection == "all":
                results = []
                for c in kb.COLLECTIONS:
                    st = kb.build_index(args.index, args.config, args.model,
                                        collection=c)
                    results.append(st)
                    if not args.json:
                        print("KB %-7s files=%d unchanged=%d changed=%d removed=%d "
                              "chunks=%d (+%d)" % (
                                  c, st["files_indexed"], st["files_unchanged"],
                                  st["files_changed"], st["files_removed"],
                                  st["chunks_total"], st["chunks_new"]))
                if args.json:
                    print(json.dumps(results, ensure_ascii=False, indent=1))
                print("index:", os.path.abspath(args.index))
                return 0
            st = kb.build_index(args.index, args.config, args.model,
                                collection=args.collection)
            if args.json:
                print(json.dumps(st, ensure_ascii=False, indent=1))
            else:
                print("KB %s: files=%d unchanged=%d changed=%d removed=%d "
                      "chunks=%d (+%d)" % (
                          st.get("collection"), st["files_indexed"],
                          st["files_unchanged"], st["files_changed"],
                          st["files_removed"], st["chunks_total"],
                          st["chunks_new"]))
                print("index:", st.get("index_dir") or os.path.abspath(args.index))
            return 0
        if args.action == "search":
            rows = kb.search(args.index, args.query, k=args.k,
                             scope=args.scope, project=args.project,
                             mode=args.mode, rerank_on=args.rerank,
                             rerank_model=args.rerank_model,
                             rerank_n=args.rerank_n,
                             weights=weights,
                             collection_weights=collection_weights,
                             collection=args.collection)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
            else:
                for i, r in enumerate(rows, 1):
                    snippet = " ".join((r["text"] or "").split())[:180]
                    score = r.get("rerank_score", r["score"])
                    print("%2d. %.4f  [%s]  %s  [%s]  L%s-%s" % (
                        i, score, r.get("collection", "legacy"),
                        r["rel_path"], r["heading"] or "—",
                        r["line_start"], r["line_end"]))
                    print("    " + snippet)
            return 0
        if args.action == "stats":
            st = kb.stats(args.index, collection=args.collection)
            if args.json:
                print(json.dumps(st, ensure_ascii=False, indent=1))
            elif args.collection == "all":
                print("collections:", ", ".join(st.get("collections", {})))
                for c, x in st.get("collections", {}).items():
                    print("  %-8s files=%-5d chunks=%-6d fts=%-6d dupe_refs=%d" % (
                        c, x["files"], x["chunks"], x["fts_chunks"], x["dupe_refs"]))
                t = st.get("totals", {})
                print("  %-8s files=%-5d chunks=%-6d fts=%-6d" % (
                    "total", t.get("files", 0), t.get("chunks", 0),
                    t.get("fts_chunks", 0)))
            else:
                for k in ("collection", "index_dir", "files", "chunks",
                          "fts_chunks", "fts_version", "model", "dim",
                          "chunk_version", "built_at", "faiss_bytes"):
                    print("%-14s %s" % (k, st.get(k)))
            return 0
        if args.action == "audit":
            if args.collection == "all":
                reps = {}
                ok = True
                for c in kb.list_collections(args.index):
                    rep = kb.audit(args.index, args.config, args.questions,
                                   k=args.k, mode=args.mode,
                                   rerank_on=args.rerank,
                                   rerank_model=args.rerank_model,
                                   min_recall=args.min_recall,
                                   collection=c,
                                   collection_weights=collection_weights,
                                   split=args.split,
                                   min_support=args.min_support)
                    reps[c] = rep
                    ok = ok and rep["overall"] == "PASS"
                    if not args.json:
                        print("audit %-8s %s" % (c, rep["overall"]))
                        for x in rep["checks"]:
                            print("  %-11s %-5s %s" % (
                                x["id"], x["status"], x.get("summary", "")))
                if args.json:
                    print(json.dumps(reps, ensure_ascii=False, indent=1))
                return 0 if ok else 1
            rep = kb.audit(args.index, args.config, args.questions,
                           k=args.k, mode=args.mode,
                           rerank_on=args.rerank,
                           rerank_model=args.rerank_model,
                           min_recall=args.min_recall,
                           collection=args.collection,
                           collection_weights=collection_weights,
                           split=args.split,
                           min_support=args.min_support)
            if args.json:
                print(json.dumps(rep, ensure_ascii=False, indent=1))
            else:
                print("audit: %s" % rep["overall"])
                for c in rep["checks"]:
                    print("  %-11s %-5s %s" % (
                        c["id"], c["status"], c.get("summary", "")))
            return 0 if rep["overall"] == "PASS" else 1
        if args.action == "neardup":
            rep = kb.neardup(args.index, collection=args.collection,
                             threshold=args.threshold, shingle=args.shingle,
                             apply=args.apply)
            if args.json:
                print(json.dumps(rep, ensure_ascii=False, indent=1))
            else:
                items = (rep.items() if args.collection == "all"
                         else [(rep.get("collection"), rep)])
                for name, r in items:
                    if r.get("error"):
                        print("neardup %-8s ERROR %s" % (name, r["error"]))
                        continue
                    print("neardup %-8s chunks=%d groups=%d merged=%d refs=%d "
                          "threshold=%.2f" % (
                              name, r["chunks"], r["groups"],
                              r["chunks_merged"], r["refs_total"],
                              r["threshold"]))
                    for g in r["top"][:5]:
                        print("  cluster %d  score=%.3f  %s L%s" % (
                            g["size"], g["max_score"],
                            g["canonical"]["rel_path"],
                            g["canonical"]["line_start"]))
            return 0
        if args.action == "eval":
            rep = kb.evaluate(args.index, args.questions, k=args.k,
                              mode=args.mode, rerank_on=args.rerank,
                              rerank_model=args.rerank_model,
                              rerank_n=args.rerank_n,
                              weights=weights,
                              collection_weights=collection_weights,
                              collection=args.collection,
                              split=args.split)
            out_dir = os.path.dirname(os.path.abspath(args.questions))
            os.makedirs(out_dir, exist_ok=True)
            suffix = ("_" + args.collection) if args.collection else ""
            if args.split:
                suffix += "_" + args.split
            with open(os.path.join(out_dir, "report%s.json" % suffix), "w",
                      encoding="utf-8", newline="\n") as f:
                json.dump(rep, f, ensure_ascii=False, indent=1)
            if args.json:
                print(json.dumps(rep, ensure_ascii=False, indent=1))
            else:
                support_txt = ""
                if rep.get("support_total"):
                    support_txt = "  support@%d=%.2f" % (
                        rep["k"], rep["support_rate"])
                print("eval: %d/%d recall@%d=%.2f  MRR=%.3f%s" % (
                    rep["hits"], rep["total"], rep["k"], rep["recall"],
                    rep["mrr"], support_txt))
                for r in rep["results"]:
                    if not r["hit"]:
                        print("  MISS %-8s %s" % (r["id"], r["question"]))
                        print("        top: %s" % ", ".join(r["top"][:3]))
                    elif r.get("supported") is False:
                        print("  WEAK %-8s 命中但 top-k 无答案词" % r["id"])
            if args.min_recall is not None and rep["recall"] < args.min_recall:
                print("[KB] recall %.2f < %.2f" % (rep["recall"], args.min_recall),
                      file=sys.stderr)
                return 1
            return 0
    except Exception as e:
        print("[KB] %s" % e, file=sys.stderr)
        return 2
    print("[KB] unknown action", file=sys.stderr)
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="繁星系统（工作流 + agent 接入）")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("agent", help="agent 自助接入/查看/停用")
    a.add_argument("action", choices=["join", "list", "show", "revoke"])
    a.add_argument("--id", default="")
    a.add_argument("--name", default="")
    a.add_argument("--owner", default="")
    a.add_argument("--scope", action="append", default=None,
                   help="可重复；默认使用协议 scopes")
    a.add_argument("--accept-contract", action="store_true")
    a.add_argument("--force", action="store_true")
    a.add_argument("--registry", default=None)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_agent)

    w = sub.add_parser("workflow", help="跑完整工作流")
    w.add_argument("--agent", default="local")
    w.add_argument("--project", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--shots", nargs="*", default=None)
    w.add_argument("--input", default=None)
    w.add_argument("--through", choices=list(STAGES), default="gate")
    w.add_argument("--skip-precheck", action="store_true")
    w.add_argument("--skip-build", action="store_true")
    w.add_argument("--execute-run", action="store_true",
                   help="显式允许提交 GPU；默认只到闸门")
    w.add_argument("--registry", default=None)
    w.add_argument("--json", action="store_true")
    w.set_defaults(func=cmd_workflow)

    c = sub.add_parser("contract", help="打印共签协议路径与哈希")
    c.set_defaults(func=cmd_contract)

    k = sub.add_parser("kb", help="知识库 P0：ingest/search/stats/eval")
    k.add_argument("action",
                   choices=["ingest", "build", "search", "stats", "eval",
                            "audit", "neardup"])
    k.add_argument("--index", default=r"E:/繁星/60_知识库")
    k.add_argument("--config", default=r"E:/繁星/60_知识库/sources.json")
    k.add_argument("--model", default=None)
    k.add_argument("--query", default="")
    k.add_argument("--k", type=int, default=8)
    k.add_argument("--scope", default=None)
    k.add_argument("--project", default=None)
    k.add_argument("--collection", default=None,
                   choices=["core", "project", "archive", "skills", "memory", "all"],
                   help="分层 collection；不填走 legacy 根索引")
    k.add_argument("--questions", default=r"E:/繁星/60_知识库/eval/questions.json")
    k.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default="hybrid")
    k.add_argument("--split", choices=["dev", "holdout", "all"], default=None,
                   help="只跑 dev 或 holdout 题；默认全部")
    k.add_argument("--rerank", action="store_true",
                   help="用 bge-reranker-base 对候选重排")
    k.add_argument("--rerank-model", default=None,
                   help="默认 E:/Models/Reranker/bge-reranker-v2-m3")
    k.add_argument("--rerank-n", type=int, default=15)
    k.add_argument("--weight", action="append", default=None,
                   help="source 加权，可重复：公共记忆=1.5")
    k.add_argument("--collection-weight", action="append", default=None,
                   help="跨库 RRF 加权，可重复：core=1.2（默认等权）")
    k.add_argument("--threshold", type=float, default=0.90,
                   help="近似重复 Jaccard 阈值（默认 0.90）")
    k.add_argument("--shingle", type=int, default=5,
                   help="近似重复字符 shingle 长度（默认 5）")
    k.add_argument("--apply", action="store_true",
                   help="neardup 时真正合并；默认只报告")
    k.add_argument("--min-recall", type=float, default=None)
    k.add_argument("--min-support", type=float, default=None)
    k.add_argument("--json", action="store_true")
    k.set_defaults(func=cmd_kb)

    args = ap.parse_args(argv)
    if getattr(args, "registry", None):
        os.environ["FANXING_REGISTRY"] = os.path.abspath(args.registry)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)
