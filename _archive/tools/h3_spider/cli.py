# -*- coding: utf-8 -*-
"""P1 CLI：单镜 8 腿 + 12 镜批跑。"""
import argparse
import datetime
import json
import os
import sys

from .case import build_shot_case
from .batch import run_batch
from .engine import run
from .body import verify
from .legs import get_legs

DEFAULT_PROMPT = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3/out/U05.txt"
DEFAULT_PROJECT = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"
DEFAULT_INPUT = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"
DEFAULT_OUT = r"C:/Temp/h3_spider/u05_p1"
DEFAULT_BATCH_OUT = r"C:/Temp/h3_spider/batch_p15"


def _print_verdict(v: dict):
    print("=" * 68)
    print("繁星系统 · %s · %s" % (v["run_id"], v["overall"]))
    print("=" * 68)
    for leg, variants in v["legs"].items():
        for variant, st in variants.items():
            print("  %-3s %-6s checked=%-3d skipped=%-2d error=%-2d missing=%-2d untested=%s"
                  % (leg, variant, st["checked_n"], st["skipped_n"], st["error_n"],
                     st["missing_n"], st["untested"]))
    print("  canary:", json.dumps(v["canary"], ensure_ascii=False))
    print("  节点：")
    for n in v["nodes"]:
        print("    %-6s %-1s %-6s seen=%-5s status=%-5s code=%-6s -> %s"
              % (n["node_id"], n["kind"], n["variant"], n["seen"],
                 n["status"], n["code"], n["result"]))
    if v["unexpected_errors"]:
        print("  非预期错误：")
        for e in v["unexpected_errors"]:
            print("    ", e)
    print("  trace_sha1:", v["trace_sha1"][:12], " manifest_sha1:", v["manifest_sha1"][:12])


def cmd_run(args) -> int:
    if not os.path.isfile(args.prompt):
        print("[FAIL] 找不到提示词：%s" % args.prompt, file=sys.stderr)
        return 2
    text = open(args.prompt, encoding="utf-8").read()
    run_id = "spider_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    variants, manifest = build_shot_case(text, args.shot, run_id, args.out,
                                        args.project, args.input)
    legs = get_legs(args.legs.split(",") if args.legs else None)
    snaps = run(legs, variants, manifest, args.out)
    from .recover import recover
    recover(args.out, production_path=args.prompt, write=True)
    verdict, code = verify(args.out, production_path=args.prompt)
    _print_verdict(verdict)
    print("  快照 %d 条；输出目录：%s" % (len(snaps), args.out))
    return code


def cmd_verify(args) -> int:
    verdict, code = verify(args.run_dir, offline=args.offline)
    _print_verdict(verdict)
    return code


def cmd_recover(args) -> int:
    from .recover import recover
    rec = recover(args.run_dir, production_path=args.production, write=True)
    if args.json:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
    else:
        print("recover: diff=%s production=%s C_nodes=%d ok=%s" % (
            rec["diff_ok"], rec["production_equal"], len(rec["nodes"]),
            rec["all_nodes_ok"]))
    return 0 if rec["diff_ok"] and rec["all_nodes_ok"] and rec["production_equal"] is not False else 1


def cmd_batch(args) -> int:
    try:
        batch = run_batch(args.project, args.input, args.out, args.shots,
                          force=args.force)
    except ValueError as e:
        print("[BATCH] %s" % e, file=sys.stderr)
        return 2
    return 0 if batch["overall"] == "PASS" else 1


def cmd_selftest(args) -> int:
    text = open(args.prompt, encoding="utf-8").read()
    run_id = "spider_selftest_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    variants, manifest = build_shot_case(text, args.shot, run_id, args.out,
                                        args.project, args.input)
    legs = get_legs(["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"])
    run(legs, variants, manifest, args.out)
    verdict, code = verify(args.out, production_path=args.prompt)
    _print_verdict(verdict)

    failures = []
    if verdict["overall"] != "PASS":
        failures.append("overall=%s" % verdict["overall"])
    if verdict["canary"]["clean_errors"] != 0:
        failures.append("clean 有 %d 个错误" % verdict["canary"]["clean_errors"])
    if verdict["canary"]["mutant_errors"] != 8:
        failures.append("mutant 错误数=%d，期望 8" % verdict["canary"]["mutant_errors"])
    for n in verdict["nodes"]:
        if n["result"] != "ok":
            failures.append("%s=%s" % (n["node_id"], n["result"]))

    card_result = None
    if not getattr(args, "skip_cards", False):
        try:
            tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if tools_dir not in sys.path:
                sys.path.insert(0, tools_dir)
            import selftest_card_standards as CARD
            card_result = CARD.run_checks(args.project, verbose=True)
            total = len(card_result["checks"])
            bad = len(card_result["failed"])
            print("\n[卡片规则] %d/%d 通过（S1/S2/S3）" % (total - bad, total))
            for x in card_result["failed"]:
                failures.append("cards: %s" % x)
        except Exception as e:
            print("\n[卡片规则] 运行失败：%s" % e, file=sys.stderr)
            failures.append("cards: %s" % e)

    if failures:
        print("\n[SELFTEST FAIL] " + "; ".join(failures))
        return 1
    if card_result is not None:
        print("\n[SELFTEST PASS] 8 条腿 + 卡片规则（S1/S2/S3）："
              "T 为 ok、M 命中期望码、C 哈希一致、卡片坏例全红。")
    else:
        print("\n[SELFTEST PASS] 8 条腿：T 为 ok、M 命中期望码、C 哈希一致。")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="繁星系统 · H3 编译期质检（8 腿）")
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("--prompt", default=DEFAULT_PROMPT)
        p.add_argument("--shot", default="U05")
        p.add_argument("--out", default=DEFAULT_OUT)
        p.add_argument("--project", default=DEFAULT_PROJECT)
        p.add_argument("--input", default=DEFAULT_INPUT)

    p = sub.add_parser("run")
    add_common(p)
    p.add_argument("--legs", default="L1,L2,L3,L4,L5,L6,L7,L8")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("verify")
    p.add_argument("--run-dir", default=DEFAULT_OUT)
    p.add_argument("--offline", action="store_true",
                   help="只靠 manifest+snapshots+recovered.json 重放")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("replay")
    p.add_argument("--run-dir", default=DEFAULT_OUT)
    p.add_argument("--offline", action="store_true", default=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("selftest")
    add_common(p)
    p.add_argument("--skip-cards", action="store_true",
                   help="只跑 8 腿，跳过 S1/S2/S3 卡片规则坏例")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("recover")
    p.add_argument("--run-dir", default=DEFAULT_OUT)
    p.add_argument("--production", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_recover)

    p = sub.add_parser("batch")
    p.add_argument("--project", default=DEFAULT_PROJECT)
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--out", default=DEFAULT_BATCH_OUT)
    p.add_argument("--shots", nargs="*", default=None)
    p.add_argument("--force", action="store_true",
                   help="允许覆盖已有的不同镜头集合批次")
    p.set_defaults(func=cmd_batch)

    a = ap.parse_args(argv)
    if not getattr(a, "func", None):
        ap.print_help()
        return 2
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
