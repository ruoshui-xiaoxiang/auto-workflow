# -*- coding: utf-8 -*-
"""W5c 扫描器验收（V5c-1/V5c-2）：清单逐条有处置、引擎侧无 362 参数残留、扫描只读不改历史。

不重扫整资源池（那是一遍 1300＋ 台账的 IO）；这里验的是**判据与只读性**，
全量清单由 `tools/scan_362_refs.py` 实跑生成到 evidence/W5c/。
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
TOOLS = ENGINE.parent / "tools"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TOOLS))

spec = importlib.util.spec_from_file_location("scan362", TOOLS / "scan_362_refs.py")
SC = importlib.util.module_from_spec(spec)
sys.modules["scan362"] = SC
spec.loader.exec_module(SC)

EVIDENCE = Path(r"D:\AIWorkflow\evidence\W5c\scan_362.json")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ------------------------------------------------------------------ V5c-1
def test_no_362_parameter_left_in_engine_or_canvases():
    """引擎侧（流／模板／画布）不许再有**参数位**的 362，否则就是新增 362 提交的源头。"""
    bases = [(ENGINE / "workflows", "*.yaml"), (ENGINE / "comfy", "*.json"),
             (Path(r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\user\default\workflows"), "**/*.json")]
    bad = []
    for base, pattern in bases:
        if not base.is_dir():
            continue
        for p in sorted(base.glob(pattern)):
            if SC._hits_in_text(p):
                bad.append(str(p))
    assert not bad, f"仍有 362 参数位：{bad}"


def test_new_g6_rejects_362_before_submit():
    sys.path.insert(0, str(TOOLS))
    from check_preflight import run_checks
    rep = run_checks({"prompt": "x", "refs": [], "length": 362, "provider": "local",
                      "only": ["G6"], "output_root": str(Path.cwd()),
                      "project": "无音", "project_aliases": {"无音": ["无音"]}})
    assert any(g == "G6" for _lv, g, _m in rep.errors), rep.render()


# ------------------------------------------------------------------ 只读性
def test_scanner_does_not_modify_scanned_files(tmp_path):
    m = tmp_path / "x.manifest.json"
    m.write_text(json.dumps({"run_id": "R1", "workflow": "h3_i2va_batch",
                             "args": {"length": 362}, "step_params": {}, "shots": []}),
                 encoding="utf-8")
    before = _sha(m)
    info = SC._manifest_362(m)
    hits = SC._hits_in_text(m)
    assert info["hits"] == ["args.length"], info
    assert _sha(m) == before, "扫描器改了被扫文件"


def test_manifest_shapes_are_handled_without_crash(tmp_path):
    """shots 可能是 dict（state）、list[dict]（plan）、list[str]（产物名）——都不许炸。"""
    shapes = [
        ({"shots": {"s01": {"generation": {"length": 362}, "status": "qc_failed"}}}, "state:s01"),
        ({"shots": [{"id": "s01", "generation": {"length": 362}}]}, "shot:s01"),
        ({"shots": ["movie_a.mp4", "movie_b.mp4"]}, None),      # 产物名列表：不该炸，也不该命中
        ({"args": {"length": "362"}}, "args.length"),
    ]
    for i, (data, expect) in enumerate(shapes):
        f = tmp_path / f"m{i}.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        out = SC._manifest_362(f)
        assert out is not None, i
        if expect:
            assert expect in out["hits"], (i, out)
        else:
            assert out["hits"] == [], (i, out)


def test_produced_vs_unproduced_disposal(tmp_path):
    batch = tmp_path / "批次" / "R9"
    (batch / "shots" / "s01" / "raw").mkdir(parents=True)
    mp = batch / "h3_x_R9.manifest.json"
    mp.write_text(json.dumps({"run_id": "R9", "args": {"length": 362}}), encoding="utf-8")
    produced, hashes = SC._produced(batch)
    assert produced is False and hashes == {}     # 只有空目录，没有 mp4
    (batch / "shots" / "s01" / "raw" / "a.mp4").write_bytes(b"mp4-bytes")
    produced, hashes = SC._produced(batch)
    assert produced is True
    assert list(hashes) == [str(Path("shots") / "s01" / "raw" / "a.mp4")], hashes
    assert hashes[list(hashes)[0]] == hashlib.sha256(b"mp4-bytes").hexdigest(),         "成片本体必须进哈希，否则 V5c-2 只有半证"


# ------------------------------------------------------------------ V5c-1/2 清单
def test_evidence_manifest_exists_with_disposal_for_every_row():
    assert EVIDENCE.is_file(), f"清单缺失：先跑 py -3.12 -B {TOOLS}\\scan_362_refs.py"
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert data["old_frames"] == 362 and data["new_max_frames"] == 345
    assert data["total"] == len(data["rows"])
    for r in data["rows"]:
        assert r.get("disposal"), r
        assert Path(r["path"]).is_file(), r["path"]
        assert r.get("sha256"), r["path"]
        if r["scope"] == "batch_manifest":
            assert r.get("run_id") and "run_status" in r, r
            want = "已出片" if r["produced_mp4"] else "未出片"
            assert r["disposal"].startswith(want), r


def test_evidence_hashes_still_match_disk():
    """V5c-2：清单登记后历史产物哈希不得变化（等价 --verify，退出码 0）。"""
    data = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    changed = [r["path"] for r in data["rows"] if _sha(r["path"]) != r["sha256"]]
    assert not changed, f"历史批次台账被改动：{changed[:3]}"
