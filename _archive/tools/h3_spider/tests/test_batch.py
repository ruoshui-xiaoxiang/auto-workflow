# -*- coding: utf-8 -*-
import json
import os

from h3_spider.batch import run_batch

PROJ = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"
INPUT = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"
SHOTS = ["U%02d" % i for i in range(1, 13)]


def test_batch_pass(tmp_path):
    b = run_batch(PROJ, INPUT, str(tmp_path), SHOTS)
    assert b["overall"] == "PASS"
    assert len(b["shots"]) == 12
    assert all(v["overall"] == "PASS" for v in b["shots"].values())
    for leg, c in b["coverage"].items():
        assert c["T"] > 0 and c["M"] > 0, leg


def test_batch_clean_equals_production(tmp_path):
    run_batch(PROJ, INPUT, str(tmp_path), SHOTS)
    for sid in SHOTS:
        assert (tmp_path / sid / "clean.txt").read_text(encoding="utf-8") == \
            open(os.path.join(PROJ, "out", sid + ".txt"), encoding="utf-8").read()


def test_base_modes_skip_referent_legs(tmp_path):
    run_batch(PROJ, INPUT, str(tmp_path), ["U01", "U08", "U12"])
    for sid in ["U01", "U08", "U12"]:
        m = json.load(open(tmp_path / sid / "manifest.json", encoding="utf-8"))
        legs = {n["leg"] for n in m["nodes"]}
        assert "L3" not in legs and "L4" not in legs and "L6" not in legs
        assert {"L1", "L7", "L8"} <= legs


def test_u04_no_speaker_cascade(tmp_path):
    b = run_batch(PROJ, INPUT, str(tmp_path), ["U04"])
    assert b["shots"]["U04"]["canary"]["mutant_errors"] == 8
