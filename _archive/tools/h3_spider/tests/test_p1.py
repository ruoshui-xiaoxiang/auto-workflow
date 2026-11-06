# -*- coding: utf-8 -*-
import hashlib
import json
import os
import shutil

from h3_spider.body import verify
from h3_spider.engine import run
from h3_spider.launcher import build_full_case
from h3_spider.legs import get_legs

PROMPT = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3/out/U05.txt"
PROJ = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"
INPUT = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"


def make_full(tmp_path):
    text = open(PROMPT, encoding="utf-8").read()
    variants, manifest = build_full_case(text, "U05", "p1", str(tmp_path), PROJ, INPUT)
    run(get_legs(), variants, manifest, str(tmp_path))
    return variants, manifest


def test_context_has_state_timeline():
    from h3_spider.project import build_context
    meta = build_context(PROJ, "U05", INPUT)["meta"]
    assert "U05" in meta["state_timeline"]
    assert meta["state_timeline"]["U05"].startswith("roughly half the planet")
    assert meta["shot_ids"][:2] == ["U01", "U02"]


def test_full_pass(tmp_path):
    make_full(tmp_path)
    v, code = verify(str(tmp_path))
    assert code == 0 and v["overall"] == "PASS"
    assert v["canary"]["clean_errors"] == 0
    assert v["canary"]["mutant_errors"] == 8
    assert all(n["result"] == "ok" for n in v["nodes"])
    assert v["legs"]["L7"]["clean"]["checked_n"] == 3
    assert v["legs"]["L8"]["clean"]["checked_n"] == 1


def test_production_prompt_unchanged(tmp_path):
    make_full(tmp_path)
    assert (tmp_path / "clean.txt").read_text(encoding="utf-8") == \
        open(PROMPT, encoding="utf-8").read()


def test_capability_matrix(tmp_path):
    make_full(tmp_path)
    v, _ = verify(str(tmp_path))
    # 文本腿逐 token，资产腿只逐资产
    assert v["legs"]["L1"]["clean"]["checked_n"] > 500
    assert v["legs"]["L7"]["clean"]["checked_n"] == 3
    assert v["legs"]["L8"]["clean"]["checked_n"] == 1


def test_expected_mutant_codes(tmp_path):
    make_full(tmp_path)
    v, _ = verify(str(tmp_path))
    codes = {n["node_id"]: n["code"] for n in v["nodes"] if n["kind"] == "M"}
    assert codes == {
        "M-L1": "FMT-02", "M-L2": "DLG-01", "M-L3": "SUB-02",
        "M-L4": "PIC-02", "M-L5": "SPK-02", "M-L6": "SRC-01",
        "M-L7": "AST-02", "M-L8": "SCN-01",
    }


def test_asset_tamper(tmp_path):
    make_full(tmp_path)
    p = tmp_path / "assets_clean.json"
    data = json.load(open(p, encoding="utf-8"))
    for a in data:
        if a["asset_id"] == "cmdr":
            a["sha1"] = "0" * 40
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    v, code = verify(str(tmp_path))
    assert code == 1 and v["overall"] == "BLOCK"
    assert any(n["node_id"] == "C-L7" and n["result"] == "tampered" for n in v["nodes"])


def test_scene_tamper(tmp_path):
    make_full(tmp_path)
    p = tmp_path / "scenes_clean.json"
    data = json.load(open(p, encoding="utf-8"))
    data[0]["state_text"] += " (tampered)"
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    v, code = verify(str(tmp_path))
    assert code == 1 and v["overall"] == "BLOCK"
    assert any(n["node_id"] == "C-L8" and n["result"] == "tampered" for n in v["nodes"])


def test_untested_asset_leg(tmp_path):
    make_full(tmp_path)
    sp = tmp_path / "snapshots.jsonl"
    rows = [json.loads(l) for l in open(sp, encoding="utf-8") if l.strip()]
    kept = [r for r in rows if r["leg"] != "L7"]
    with open(sp, "w", encoding="utf-8", newline="\n") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v, code = verify(str(tmp_path))
    assert code == 1 and v["overall"] == "BLOCK"
    assert v["legs"]["L7"]["clean"]["untested"] is True


def test_offline_replay(tmp_path):
    from h3_spider.recover import recover
    make_full(tmp_path)
    recover(str(tmp_path), production_path=PROMPT, write=True)
    off = tmp_path / "offline"
    shutil.copytree(tmp_path, off)
    for name in ("clean.txt", "mutant.txt", "assets_clean.json",
                 "assets_mutant.json", "scenes_clean.json", "scenes_mutant.json"):
        (off / name).unlink()
    v, code = verify(str(off), offline=True)
    assert code == 0 and v["overall"] == "PASS"
    assert v["offline"] is True
    assert all(n["result"] == "ok" for n in v["nodes"])


def test_base_mode_not_applicable_reason(tmp_path):
    from h3_spider.batch import run_batch
    b = run_batch(PROJ, INPUT, str(tmp_path), ["U01"])
    assert b["overall"] == "PASS"
    v = json.load(open(tmp_path / "U01" / "verdict.json", encoding="utf-8"))
    assert v["legs"]["L3"]["clean"]["not_applicable"] is True
    assert "subject_definitions" in v["legs"]["L3"]["clean"]["not_applicable_reason"]


def test_cli_module_entry_selftest(tmp_path):
    import subprocess
    import sys
    tools = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    r = subprocess.run(
        [sys.executable, "-m", "h3_spider.cli", "selftest", "--out", str(tmp_path)],
        cwd=tools, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SELFTEST PASS" in r.stdout


def test_normalization_offsets(tmp_path):
    import h3_prompt_builder as B
    from h3_spider.recover import sha1_text
    text = open(PROMPT, encoding="utf-8").read()
    old = "指挥官,这不合规矩."
    assert old in text
    new = B.normalize_punct(B.spell_numbers("3 秒后，指挥官，这不合规矩！"))
    assert "三 秒后" in new and "," in new and "!" in new
    text2 = text.replace(old, new, 1)
    variants, manifest = build_full_case(text2, "U05", "norm",
                                         str(tmp_path), PROJ, INPUT)
    run(get_legs(), variants, manifest, str(tmp_path))
    v, code = verify(str(tmp_path))
    assert code == 0 and v["overall"] == "PASS"
    for n in manifest["nodes"]:
        if n["node_type"] != "token":
            continue
        if n["kind"] == "T":
            assert text2[n["start"]:n["end"]] == n["original"], n["node_id"]
        if n["kind"] == "C":
            assert sha1_text(text2[n["start"]:n["end"]]) == n["payload_sha1"], n["node_id"]


def test_absent_leg_is_untested(tmp_path):
    make_full(tmp_path)
    mp = tmp_path / "manifest.json"
    m = json.load(open(mp, encoding="utf-8"))
    m["nodes"] = [n for n in m["nodes"] if n["leg"] != "L7"]
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    meta_p = tmp_path / "run_meta.json"
    meta = json.load(open(meta_p, encoding="utf-8"))
    meta["manifest_sha1"] = hashlib.sha1(mp.read_bytes()).hexdigest()
    with open(meta_p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    sp = tmp_path / "snapshots.jsonl"
    rows = [json.loads(l) for l in open(sp, encoding="utf-8") if l.strip()]
    kept = [r for r in rows if r["leg"] != "L7"]
    with open(sp, "w", encoding="utf-8", newline="\n") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    v, code = verify(str(tmp_path))
    assert code == 1 and v["overall"] == "BLOCK"
    assert v["legs"]["L7"]["clean"]["untested"] is True
    assert v["legs"]["L7"]["mutant"]["untested"] is True


def test_capability_skip_blocks(tmp_path):
    make_full(tmp_path)
    mp = tmp_path / "manifest.json"
    m = json.load(open(mp, encoding="utf-8"))
    bad = dict(next(n for n in m["nodes"] if n["node_id"] == "T-L1"))
    bad.update({"node_id": "BAD-L7", "leg": "L7", "node_type": "token"})
    m["nodes"].append(bad)
    m["capability_skips"] = [{"node_id": "BAD-L7", "leg": "L7",
                              "node_type": "token",
                              "reason": "skipped_by_capability"}]
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    meta_p = tmp_path / "run_meta.json"
    meta = json.load(open(meta_p, encoding="utf-8"))
    meta["manifest_sha1"] = hashlib.sha1(mp.read_bytes()).hexdigest()
    with open(meta_p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    v, code = verify(str(tmp_path))
    assert code == 1 and v["overall"] == "BLOCK"
    row = next(n for n in v["nodes"] if n["node_id"] == "BAD-L7")
    assert row["result"] == "skipped_by_capability"


def test_unverified_leg(tmp_path):
    make_full(tmp_path)
    mp = tmp_path / "manifest.json"
    m = json.load(open(mp, encoding="utf-8"))
    m["nodes"] = [n for n in m["nodes"] if n["node_id"] != "M-L1"]
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    meta_p = tmp_path / "run_meta.json"
    meta = json.load(open(meta_p, encoding="utf-8"))
    meta["manifest_sha1"] = hashlib.sha1(mp.read_bytes()).hexdigest()
    with open(meta_p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    v, code = verify(str(tmp_path))
    assert code == 1 and v["overall"] == "BLOCK"
    assert v["legs"]["L1"]["clean"]["unverified"] is True
