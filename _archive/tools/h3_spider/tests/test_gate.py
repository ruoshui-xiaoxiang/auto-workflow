# -*- coding: utf-8 -*-
import json
import os
import shutil

from h3_spider.gate import check_batch_gate

PROJ = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"
BATCH = r"C:/Temp/h3_spider/batch_p15"


def copy_project(tmp_path):
    p = tmp_path / "project"
    (p / "out").mkdir(parents=True)
    for name in ("characters.yaml", "scenes.yaml", "shots.yaml", "lexicon.yaml"):
        src = os.path.join(PROJ, name)
        if os.path.isfile(src):
            shutil.copy(src, p / name)
    shutil.copy(os.path.join(PROJ, "out", "U05.txt"), p / "out" / "U05.txt")
    return p


def test_gate_pass_real():
    ok, reasons, info = check_batch_gate(PROJ, BATCH, ["U05"])
    assert ok, reasons
    assert info["overall"] == "PASS"


def test_gate_missing_batch(tmp_path):
    ok, reasons, _ = check_batch_gate(PROJ, str(tmp_path / "nope"), ["U05"])
    assert not ok
    assert any("batch_verdict" in r for r in reasons)


def test_gate_prompt_changed(tmp_path):
    p = copy_project(tmp_path)
    ok, reasons, _ = check_batch_gate(str(p), BATCH, ["U05"])
    assert ok, reasons
    q = p / "out" / "U05.txt"
    q.write_text(q.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    ok, reasons, _ = check_batch_gate(str(p), BATCH, ["U05"])
    assert not ok
    assert any("渲染稿" in r for r in reasons)


def test_gate_card_changed(tmp_path):
    p = copy_project(tmp_path)
    ok, reasons, _ = check_batch_gate(str(p), BATCH, ["U05"])
    assert ok, reasons
    c = p / "characters.yaml"
    c.write_text(c.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    ok, reasons, _ = check_batch_gate(str(p), BATCH, ["U05"])
    assert not ok
    assert any("卡文件" in r for r in reasons)


def test_runner_refuses_bad_batch(tmp_path):
    import h3_run_project
    bad = tmp_path / "bad"
    bad.mkdir()
    json.dump({"overall": "BLOCK", "shots": {}, "project_hashes": {}},
              open(bad / "batch_verdict.json", "w", encoding="utf-8"))
    code = h3_run_project.main(["--project", PROJ, "--out", str(tmp_path / "out"),
                                "--only", "U05", "--spider-batch", str(bad),
                                "--dry-run"])
    assert code == 2
    gate = json.load(open(tmp_path / "out" / "spider_gate.json", encoding="utf-8"))
    assert gate["ok"] is False


def test_runner_dry_run_passes(tmp_path):
    import h3_run_project
    code = h3_run_project.main(["--project", PROJ, "--out", str(tmp_path / "out"),
                                "--only", "U05", "--spider-batch", BATCH,
                                "--dry-run"])
    assert code == 0
    gate = json.load(open(tmp_path / "out" / "spider_gate.json", encoding="utf-8"))
    assert gate["ok"] is True
