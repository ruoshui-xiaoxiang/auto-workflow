# -*- coding: utf-8 -*-
"""坏样本语料审计器。

用法：
  cd D:/AIWorkflow/tools
  py -3.12 -m h3_spider.corpus.audit
  py -3.12 -m h3_spider.corpus.audit --json

语料是冻结稿（corpus/base/*.txt + base.json），不读活项目。
每条 case 只改一处，检查目标腿是否报出预期错误码。
"""
import argparse
import copy
import json
import os
from typing import Dict, List, Tuple

from ..lexer import tokenize
from ..legs import get_legs

HERE = os.path.dirname(os.path.abspath(__file__))


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_bases(corpus_dir=HERE):
    bases = _read_json(os.path.join(corpus_dir, "base.json"))
    for bid, b in bases.items():
        with open(os.path.join(corpus_dir, b["text_file"]), encoding="utf-8") as f:
            b["text"] = f.read()
    return bases


def _replace_once(text, old, new):
    if old not in text:
        raise ValueError("语料替换找不到原文：%r" % old[:80])
    return text.replace(old, new, 1)


def _edit_text(text, edit):
    op = edit["op"]
    if op == "replace":
        return _replace_once(text, edit["from"], edit["to"])
    if op == "insert_before":
        marker = edit["marker"]
        i = text.find(marker)
        if i < 0:
            raise ValueError("语料插入找不到标记：%r" % marker)
        return text[:i] + edit["text"] + text[i:]
    if op == "duplicate_line":
        prefix = edit["prefix"]
        for line in text.splitlines():
            if line.startswith(prefix):
                return text.replace(line, line + "\n" + line, 1)
        raise ValueError("语料复制找不到行前缀：%r" % prefix)
    raise ValueError("未知文本编辑：%r" % op)


def build_case(base, edits):
    text = base["text"]
    assets = copy.deepcopy(base.get("assets") or [])
    scenes = copy.deepcopy(base.get("scenes") or [])
    for e in edits:
        if e["target"] == "text":
            text = _edit_text(text, e)
        elif e["target"] == "asset":
            rec = next((a for a in assets if a.get("asset_id") == e["id"]), None)
            if rec is None:
                raise ValueError("语料找不到资产：%r" % e["id"])
            if e["op"] == "set":
                rec.update(copy.deepcopy(e["values"]))
            else:
                raise ValueError("未知资产编辑：%r" % e["op"])
        elif e["target"] == "scene":
            i = int(e.get("index") or 0)
            if i >= len(scenes):
                raise ValueError("语料找不到场景索引：%d" % i)
            if e["op"] == "set":
                scenes[i].update(copy.deepcopy(e["values"]))
            else:
                raise ValueError("未知场景编辑：%r" % e["op"])
        else:
            raise ValueError("未知编辑目标：%r" % e["target"])
    return text, assets, scenes


def run_legs(text, assets, scenes, meta, shot):
    tokens = tokenize(text)
    errors = []
    for leg in get_legs():
        if "token" in leg.node_types:
            for tid, (status, code, msg) in leg.run(tokens, text, "clean", shot,
                                                   ctx=meta).items():
                if status == "error":
                    errors.append({"leg": leg.id, "code": code, "msg": msg,
                                   "target": "token:%d" % tid})
        if "asset" in leg.node_types:
            for aid, (status, code, msg) in leg.run_assets(assets, "clean", shot,
                                                          ctx=meta).items():
                if status == "error":
                    errors.append({"leg": leg.id, "code": code, "msg": msg,
                                   "target": "asset:%s" % aid})
        if "scene" in leg.node_types:
            for sid, (status, code, msg) in leg.run_scenes(scenes, "clean", shot,
                                                          ctx=meta).items():
                if status == "error":
                    errors.append({"leg": leg.id, "code": code, "msg": msg,
                                   "target": "scene:%s" % sid})
    return errors


def _eval_cases(cases, bases):
    results = []
    for case in cases:
        base = bases[case["base"]]
        text, assets, scenes = build_case(base, case.get("edits") or [])
        errors = run_legs(text, assets, scenes, base["meta"], case["base"])
        hit = any(e["leg"] == case["leg"] and e["code"] == case["code"]
                  for e in errors)
        results.append({
            "id": case["id"], "base": case["base"],
            "expect": case["leg"] + "/" + case["code"],
            "hit": hit, "errors": errors,
            "why": case.get("why", ""), "source": case.get("source", ""),
        })
    return results


def evaluate(corpus_dir=HERE):
    bases = load_bases(corpus_dir)
    spec = _read_json(os.path.join(corpus_dir, "cases.json"))
    results = _eval_cases(spec["cases"], bases)

    hold_path = os.path.join(corpus_dir, "holdout.json")
    hold_spec = _read_json(hold_path) if os.path.isfile(hold_path) else {"cases": []}
    holdout = _eval_cases(hold_spec["cases"], bases)

    clean = []
    for bid in spec.get("clean") or []:
        base = bases[bid]
        errors = run_legs(base["text"], base["assets"], base["scenes"],
                          base["meta"], bid)
        clean.append({"base": bid, "ok": not errors, "errors": errors})

    hits = sum(1 for r in results if r["hit"])
    hold_hits = sum(1 for r in holdout if r["hit"])
    return {
        "total": len(results),
        "hits": hits,
        "recall": (hits / len(results)) if results else 1.0,
        "results": results,
        "holdout_total": len(holdout),
        "holdout_hits": hold_hits,
        "holdout_recall": (hold_hits / len(holdout)) if holdout else 1.0,
        "holdout_results": holdout,
        "clean": clean,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="蜘蛛坏样本语料审计")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args(argv)
    report = evaluate()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print("坏样本 %d 条 · 命中 %d · 召回 %.0f%%"
              % (report["total"], report["hits"], report["recall"] * 100))
        print("holdout %d 条 · 命中 %d · 召回 %.0f%%"
              % (report["holdout_total"], report["holdout_hits"],
                 report["holdout_recall"] * 100))
        for r in report["results"] + report["holdout_results"]:
            if not r["hit"]:
                got = ", ".join(sorted({e["leg"] + "/" + str(e["code"])
                                        for e in r["errors"]})) or "无错误"
                print("  MISS %-34s 期望 %-10s 实得 %s" % (r["id"], r["expect"], got))
        for c in report["clean"]:
            print("  干净基稿 %s：%s" % (c["base"], "0 error" if c["ok"] else
                                       ", ".join(e["leg"] + "/" + str(e["code"])
                                                 for e in c["errors"])))
    bad_clean = [c for c in report["clean"] if not c["ok"]]
    hold_bad = [r for r in report["holdout_results"] if not r["hit"]]
    return 0 if (report["hits"] == report["total"] and not bad_clean
                 and not hold_bad) else 1


if __name__ == "__main__":
    raise SystemExit(main())
