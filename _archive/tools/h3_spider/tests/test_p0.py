# -*- coding: utf-8 -*-
import difflib
import json
import os

from h3_spider.body import verify
from h3_spider.engine import run
from h3_spider.launcher import build_case
from h3_spider.legs import get_legs
from h3_spider.lexer import tokenize

PROMPT = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3/out/U05.txt"


def make_run(tmp_path):
    text = open(PROMPT, encoding="utf-8").read()
    variants, manifest = build_case(text, "U05", "t0", str(tmp_path))
    run(get_legs(["L2", "L5"]), variants, manifest, str(tmp_path))
    return variants, manifest


def test_tokenizer_offsets():
    text = open(PROMPT, encoding="utf-8").read()
    for t in tokenize(text):
        assert text[t.start:t.end] == t.text
        assert t.start < t.end


def test_pass(tmp_path):
    make_run(tmp_path)
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 0 and v["overall"] == "PASS"
    assert v["canary"]["clean_errors"] == 0
    assert v["canary"]["mutant_errors"] == 2
    assert all(n["result"] == "ok" for n in v["nodes"])


def test_missing_node(tmp_path):
    make_run(tmp_path)
    sp = tmp_path / "snapshots.jsonl"
    rows = [json.loads(l) for l in open(sp, encoding="utf-8") if l.strip()]
    for r in rows:
        if "T-L2" in (r.get("node_ids") or []):
            r["node_ids"].remove("T-L2")
    with open(sp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"
    assert any(n["node_id"] == "T-L2" and n["result"] == "missing" for n in v["nodes"])


def test_tampered_payload(tmp_path):
    make_run(tmp_path)
    p = tmp_path / "clean.txt"
    s = p.read_text(encoding="utf-8")
    assert "指挥官" in s
    p.write_text(s.replace("指挥官", "指挥管", 1), encoding="utf-8", newline="\n")
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"
    assert any(n["node_id"] == "C-L2" and n["result"] == "tampered" for n in v["nodes"])


def test_untested_leg(tmp_path):
    make_run(tmp_path)
    sp = tmp_path / "snapshots.jsonl"
    rows = [json.loads(l) for l in open(sp, encoding="utf-8") if l.strip()]
    kept = [r for r in rows if r["leg"] != "L2"]
    with open(sp, "w", encoding="utf-8", newline="\n") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"
    assert v["legs"]["L2"]["clean"]["untested"] is True


def test_unexpected_error(tmp_path):
    make_run(tmp_path)
    sp = tmp_path / "snapshots.jsonl"
    rows = [json.loads(l) for l in open(sp, encoding="utf-8") if l.strip()]
    for r in rows:
        if r["leg"] == "L5" and r["variant"] == "clean" and r["status"] == "ok":
            r["status"] = "error"
            r["code"] = "FOO"
            break
    with open(sp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"
    assert v["unexpected_errors"]


def test_manifest_tampered(tmp_path):
    make_run(tmp_path)
    mp = tmp_path / "manifest.json"
    m = json.load(open(mp, encoding="utf-8"))
    m["nodes"][0]["expected_status"] = "error"
    json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"
    assert v["run_meta"]["ok"] is False


def test_diff_only_mutations(tmp_path):
    variants, manifest = make_run(tmp_path)
    clean, mutant = variants["clean"], variants["mutant"]
    edits = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, clean, mutant).get_opcodes():
        if tag != "equal":
            edits.append((i1, i2, clean[i1:i2], mutant[j1:j2]))
    expected = sorted((n["edit_start"], n["edit_end"], n["edit_original"], n["edit_mutated"])
                      for n in manifest["nodes"] if n["kind"] == "M")
    assert len(edits) == len(expected) == 2
    # SequenceMatcher 会给出最小改动区间（(S1)->(S2) 只报 1->2），
    # 只要每个改动都落在某个 M 的 edit 区间内即可。
    for i1, i2, _a, _b in edits:
        assert any(e1 <= i1 and i2 <= e2 for e1, e2, _o, _m in expected), \
            "diff %r-%r 不在任何变异区间内" % (i1, i2)


def test_recover_payloads_and_manifest(tmp_path):
    from h3_spider.recover import recover
    make_run(tmp_path)
    rec = recover(str(tmp_path), production_path=PROMPT)
    assert rec["diff_ok"] is True
    assert rec["production_equal"] is True
    assert rec["all_nodes_ok"] is True
    assert (tmp_path / "recovered.json").is_file()
    verify(str(tmp_path), production_path=PROMPT, required_legs=("L2", "L5"))
    assert (tmp_path / "spider_manifest.json").is_file()


def test_recover_detects_shadow_tamper(tmp_path):
    from h3_spider.recover import recover
    make_run(tmp_path)
    p = tmp_path / "clean.txt"
    p.write_text(p.read_text(encoding="utf-8") + "\nshadow drift\n",
                 encoding="utf-8")
    rec = recover(str(tmp_path), production_path=PROMPT)
    assert rec["diff_ok"] is False
    v, code = verify(str(tmp_path), production_path=PROMPT,
                     required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"


def test_capability_validation():
    from h3_spider.legs import validate_capability
    skips = validate_capability([
        {"node_id": "bad-1", "leg": "L2", "node_type": "asset"},
        {"node_id": "bad-2", "leg": "L7", "node_type": "token"},
        {"node_id": "ok-1", "leg": "L2", "node_type": "token"},
    ])
    assert {x["node_id"] for x in skips} == {"bad-1", "bad-2"}
    assert all(x["reason"] == "skipped_by_capability" for x in skips)


def test_wrong_leg(tmp_path):
    make_run(tmp_path)
    sp = tmp_path / "snapshots.jsonl"
    rows = [json.loads(l) for l in open(sp, encoding="utf-8") if l.strip()]
    for r in rows:
        if r["leg"] == "L2" and "T-L2" in (r.get("node_ids") or []):
            r["node_ids"].remove("T-L2")
            break
    for r in rows:
        if r["leg"] == "L5":
            r.setdefault("node_ids", []).append("T-L2")
            break
    with open(sp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v, code = verify(str(tmp_path), required_legs=("L2", "L5"))
    assert code == 1 and v["overall"] == "BLOCK"
    assert any(n["node_id"] == "T-L2" and n["result"] == "wrong_leg"
               for n in v["nodes"])
