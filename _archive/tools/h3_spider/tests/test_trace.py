# -*- coding: utf-8 -*-
import json

import h3_precheck as P
import h3_prompt_builder as B

PROJ = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"


def test_builder_trace(tmp_path):
    out = tmp_path / "out"
    rc = B.main(["build", "--project", PROJ, "--out-dir", str(out),
                 "--only", "U05", "--trace"])
    assert rc == 0
    p = out / "trace.json"
    assert p.is_file()
    tr = json.load(open(p, encoding="utf-8"))
    s = tr["shots"]["U05"]
    assert s["mode"] == "ref2va"
    assert len(s["fields"]) >= 6
    assert any(f["normalizers"] for f in s["fields"])
    assert s["sentences"]
    assert all(x["start"] < x["end"] for x in s["sentences"])
    card_sources = [src for sent in s["sentences"] for src in sent["sources"]
                    if src["kind"] == "card"]
    assert card_sources
    assert all(src["file"] and src["line"] > 0 for src in card_sources)
    tags = {t["tag"] for t in s["tags"]}
    assert "<Subject 1>" in tags
    assert any(t["role"] == "definition" for t in s["tags"])
    assert s["speakers"] and s["speakers"][0]["speaker"] == "S1"
    assert s["normalization"]["steps"]


def test_builder_trace_does_not_change_prompt(tmp_path):
    plain = tmp_path / "plain"
    traced = tmp_path / "traced"
    assert B.main(["build", "--project", PROJ, "--out-dir", str(plain),
                   "--only", "U05"]) == 0
    assert B.main(["build", "--project", PROJ, "--out-dir", str(traced),
                   "--only", "U05", "--trace"]) == 0
    assert (plain / "U05.txt").read_text(encoding="utf-8") == \
        (traced / "U05.txt").read_text(encoding="utf-8")


def test_speaker_order_multiple():
    from h3_trace import scan_speakers
    text = ('<Subject 1> (S1) says: <d>一</d> then '
            '<Subject 2> (S2) says, voice low: <d>二</d>')
    rows = scan_speakers(text, [])
    assert [r["speaker"] for r in rows] == ["S1", "S2"]
    assert [r["order"] for r in rows] == [1, 2]


def test_precheck_trace(tmp_path):
    p = tmp_path / "precheck_trace.json"
    rc = P.main(["--project", PROJ, "--trace", str(p)])
    assert rc == 0
    tr = json.load(open(p, encoding="utf-8"))
    assert tr["assets"] and tr["scenes"] and tr["shots"]
    a = next(x for x in tr["assets"] if x["name"] == "cmdr")
    assert a["source"].endswith(".png")
    assert len(a["crop"]) == 4
    assert a["crop_path"].endswith("cmdr.png")
    assert a["faces"] == 1
    assert a["chain_ok"] is True
    u02 = next(x for x in tr["shots"] if x["id"] == "U02")
    assert u02["state_source"] == "U01"


def test_selftest_includes_card_rules(tmp_path, capsys):
    import h3_spider.cli as C
    rc = C.main(["selftest", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "卡片规则" in out
    assert "S1" in out and "S2" in out and "S3" in out
