# -*- coding: utf-8 -*-
import copy
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from h3_spider.canvas_apply import (apply_draft, validate_draft, _backup_path,
                                    _build, _report_failures)
from h3_spider.canvas_paths import CanvasError
from h3_spider.canvas_store import yaml_dump_atomic, yaml_load

SRC = Path(r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3")


def _fixture(tmp_path):
    root = tmp_path / "Demo"
    proj = root / "h3"
    proj.mkdir(parents=True)
    for name in ("characters.yaml", "scenes.yaml", "shots.yaml", "lexicon.yaml"):
        shutil.copy(str(SRC / name), str(proj / name))
    (proj / "out").mkdir()
    shutil.copy(str(SRC / "out" / "U01.txt"), str(proj / "out" / "U01.txt"))
    return proj


def _shots(proj):
    doc = yaml_load(str(proj / "shots.yaml"))
    return {s["id"]: s for s in doc["shots"]}, doc


def test_validate_rejects_bad_duration(tmp_path):
    proj = _fixture(tmp_path)
    errs = validate_draft(str(proj), [{"id": "U01", "duration": 6.0}], [], {})
    assert any("17 帧" in e["message"] for e in errs)


def test_apply_writes_and_backs_up(tmp_path):
    proj = _fixture(tmp_path)
    before = (proj / "shots.yaml").read_text(encoding="utf-8")
    out = apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {}, run_gate=False)
    assert out["ok"] is True
    after = (proj / "shots.yaml").read_text(encoding="utf-8")
    assert "5.875" in after
    assert "#" in after
    assert list((proj / ".fanxing" / "backup").glob("shots.*.yaml"))


def test_apply_keeps_unchanged_shots(tmp_path):
    proj = _fixture(tmp_path)
    apply_draft(str(proj), [{"id": "U02", "duration": 5.875}], [], {}, run_gate=False)
    text = (proj / "shots.yaml").read_text(encoding="utf-8")
    assert "id: U01" in text and "id: U02" in text


def test_apply_rejects_builder_error_before_write(tmp_path):
    proj = _fixture(tmp_path)
    before = (proj / "shots.yaml").read_text(encoding="utf-8")
    with pytest.raises(Exception):
        apply_draft(str(proj), [{"id": "U02", "duration": 6.583}], [], {}, run_gate=False)
    assert (proj / "shots.yaml").read_text(encoding="utf-8") == before


def test_dry_run_returns_diff_without_writing(tmp_path):
    proj = _fixture(tmp_path)
    before = (proj / "shots.yaml").read_text(encoding="utf-8")
    out = apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {},
                      run_gate=False, dry_run=True)
    assert out["dry_run"] is True
    assert out["diff"]
    assert (proj / "shots.yaml").read_text(encoding="utf-8") == before


def test_add_and_delete_shot(tmp_path):
    from h3_spider.canvas_apply import add_shot, delete_shot
    proj = _fixture(tmp_path)
    nid = add_shot(str(proj), "U01")
    text = (proj / "shots.yaml").read_text(encoding="utf-8")
    assert "id: %s" % nid in text
    delete_shot(str(proj), nid)
    text = (proj / "shots.yaml").read_text(encoding="utf-8")
    assert "id: %s" % nid not in text


# ---------------------------------------------------------------- 边写回
def test_chain_edge_persists(tmp_path):
    """chain 写完必须落到 shots.yaml 的 image 上（不是只改内存副本）。"""
    proj = _fixture(tmp_path)
    out = apply_draft(
        str(proj), [{"id": "U02", "duration": 5.875}],
        [{"from": "U01", "to": "U02", "type": "chain", "binding": "b2.png"}],
        {}, run_gate=False)
    assert out["ok"] is True
    by_id, doc = _shots(proj)
    assert by_id["U02"]["image"] == "b2.png"
    assert [s["id"] for s in doc["shots"]][:2] == ["U01", "U02"]
    assert "#" in (proj / "shots.yaml").read_text(encoding="utf-8")


def test_ref_edge_persists(tmp_path):
    """ref 写完必须落到 images 上；原来没有 images 时要新建。"""
    proj = _fixture(tmp_path)
    by_id, _doc = _shots(proj)
    assert by_id["U03"].get("mode") == "ref2va"
    assert "images" not in by_id["U03"]
    out = apply_draft(
        str(proj), [{"id": "U03"}],
        [{"from": "U03", "to": "@cmdr", "type": "ref"}],
        {"cmdr": "cmdr"}, run_gate=False)
    assert out["ok"] is True
    by_id, _doc = _shots(proj)
    assert "cmdr" in list(by_id["U03"]["images"])


def test_validate_does_not_mutate_document(tmp_path):
    """校验用深拷贝跑 apply_edges，不能顺手改盘上的文件。"""
    proj = _fixture(tmp_path)
    before = (proj / "shots.yaml").read_text(encoding="utf-8")
    errs = validate_draft(
        str(proj), [{"id": "U02"}],
        [{"from": "U01", "to": "U02", "type": "chain", "binding": "edge.png"}],
        {})
    assert errs == []
    assert (proj / "shots.yaml").read_text(encoding="utf-8") == before


def test_validate_rejects_unknown_shot(tmp_path):
    proj = _fixture(tmp_path)
    errs = validate_draft(str(proj), [{"id": "U99"}], [], {})
    assert any("不存在" in e["message"] for e in errs)


def test_validate_reports_non_numeric_duration(tmp_path):
    proj = _fixture(tmp_path)
    errs = validate_draft(str(proj), [{"id": "U01", "duration": "abc"}], [], {})
    assert any(e.get("shot") == "U01" for e in errs)


def test_duplicate_ids_rejected(tmp_path):
    """shots.yaml 里同 id 出现两次：校验拦下，apply 不动盘（否则 _merge 只填一个）。"""
    proj = _fixture(tmp_path)
    doc = yaml_load(str(proj / "shots.yaml"))
    doc["shots"].append(copy.deepcopy(doc["shots"][0]))
    yaml_dump_atomic(doc, str(proj / "shots.yaml"))
    before = (proj / "shots.yaml").read_bytes()
    errs = validate_draft(str(proj), [{"id": "U01"}], [], {})
    assert any("重复" in e["message"] and "U01" in e["message"] for e in errs)
    with pytest.raises(CanvasError):
        apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {},
                    run_gate=False)
    assert (proj / "shots.yaml").read_bytes() == before


# ---------------------------------------------------------------- 合并后校验
def test_validate_sees_merged_mode(tmp_path):
    """草稿把 U01 从 i2va 改成 ref2va 后，ref 边就该合法：校验必须看合并后的文档。"""
    proj = _fixture(tmp_path)
    by_id, _doc = _shots(proj)
    assert by_id["U01"]["mode"] == "i2va"
    errs = validate_draft(
        str(proj), [{"id": "U01", "mode": "ref2va"}],
        [{"from": "U01", "to": "@cmdr", "type": "ref"}], {"cmdr": "cmdr"})
    assert errs == []


def test_validate_rejects_ref_edge_after_mode_removed(tmp_path):
    """反向：真 ref2va 镜头被草稿改成 i2va，再挂 ref 边必须被拒。"""
    proj = _fixture(tmp_path)
    by_id, _doc = _shots(proj)
    assert by_id["U03"]["mode"] == "ref2va"
    errs = validate_draft(
        str(proj), [{"id": "U03", "mode": "i2va"}],
        [{"from": "U03", "to": "@cmdr", "type": "ref"}], {"cmdr": "cmdr"})
    assert any("ref2va" in e["message"] for e in errs)


def test_apply_rejects_ref_edge_after_mode_removed(tmp_path):
    """同一反向草稿走 apply：必须在写盘前 422，不能拖到 apply_edges 里炸。"""
    proj = _fixture(tmp_path)
    before = (proj / "shots.yaml").read_text(encoding="utf-8")
    with pytest.raises(CanvasError):
        apply_draft(str(proj), [{"id": "U03", "mode": "i2va"}],
                    [{"from": "U03", "to": "@cmdr", "type": "ref"}],
                    {"cmdr": "cmdr"}, run_gate=False)
    assert (proj / "shots.yaml").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------- 时长归一化
def test_string_duration_written_as_float(tmp_path):
    """草稿给字符串 "5.875"，落盘必须是浮点，不能写成带引号的字符串。"""
    proj = _fixture(tmp_path)
    out = apply_draft(str(proj), [{"id": "U01", "duration": "5.875"}], [], {},
                      run_gate=False)
    assert out["ok"] is True
    by_id, _doc = _shots(proj)
    assert isinstance(by_id["U01"]["duration"], float)
    assert by_id["U01"]["duration"] == 5.875
    text = (proj / "shots.yaml").read_text(encoding="utf-8")
    assert "'5.875'" not in text and '"5.875"' not in text


# ---------------------------------------------------------------- 备份唯一
def test_backup_paths_are_unique(tmp_path):
    proj = _fixture(tmp_path)
    a = _backup_path(str(proj), "apply")
    b = _backup_path(str(proj), "apply")
    assert a != b
    assert Path(a).name.startswith("shots.")
    assert Path(a).name.endswith(".apply.yaml")
    assert Path(a).match("shots.*.yaml")


def test_apply_keeps_both_backups(tmp_path):
    """连跑两次写回，两份备份都在（同秒也不能互相覆盖）。"""
    proj = _fixture(tmp_path)
    a = apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {},
                    run_gate=False)["backup"]
    b = apply_draft(str(proj), [{"id": "U01", "duration": 6.583}], [], {},
                    run_gate=False)["backup"]
    assert a != b
    assert Path(a).is_file() and Path(b).is_file()
    assert len(list((proj / ".fanxing" / "backup").glob("shots.*.yaml"))) == 2


# ---------------------------------------------------------------- 写盘后的闸
def _stub_batch(monkeypatch, tmp_path):
    """批跑别真跑；runs 根落到临时目录，别污染 C:/Temp。"""
    import h3_spider.batch as batch_mod
    monkeypatch.setattr(batch_mod, "run_batch", lambda *a, **k: {"ok": True})
    monkeypatch.setenv("FANXING_RUNS_ROOT", str(tmp_path / "runs"))


def test_gate_exception_after_write_returns_not_ok(tmp_path, monkeypatch):
    """闸抛异常时写回已经成功：要返回 ok=False + gate.error，而不是往上抛。"""
    import h3_spider.gate as gate_mod
    proj = _fixture(tmp_path)
    _stub_batch(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("闸炸了")

    monkeypatch.setattr(gate_mod, "check_batch_gate", boom)
    out = apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {},
                      run_gate=True)
    assert out["ok"] is False
    assert out["gate"]["ok"] is False
    assert "闸炸了" in out["gate"]["error"]
    assert out["build"] and out["backup"] and out["batch_dir"]
    by_id, _doc = _shots(proj)
    assert by_id["U01"]["duration"] == 5.875


def test_run_batch_exception_after_write_returns_not_ok(tmp_path, monkeypatch):
    import h3_spider.batch as batch_mod
    proj = _fixture(tmp_path)
    monkeypatch.setenv("FANXING_RUNS_ROOT", str(tmp_path / "runs"))

    def boom(*a, **k):
        raise RuntimeError("spider 挂了")

    monkeypatch.setattr(batch_mod, "run_batch", boom)
    out = apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {},
                      run_gate=True)
    assert out["ok"] is False
    assert "spider 挂了" in out["gate"]["error"]
    by_id, _doc = _shots(proj)
    assert by_id["U01"]["duration"] == 5.875


def test_batch_dir_uses_env_root_and_uuid_suffix(tmp_path, monkeypatch):
    import h3_spider.gate as gate_mod
    proj = _fixture(tmp_path)
    _stub_batch(monkeypatch, tmp_path)
    monkeypatch.setattr(gate_mod, "check_batch_gate",
                        lambda *a, **k: (True, [], {}))
    out = apply_draft(str(proj), [{"id": "U01", "duration": 5.875}], [], {},
                      run_gate=True)
    assert out["ok"] is True
    batch_dir = Path(out["batch_dir"])
    assert batch_dir.parent.parent == tmp_path / "runs"
    assert re.match(r"canvas_apply_\d{8}_\d{6}_[0-9a-f]{8}$",
                    batch_dir.parent.name)
    assert (proj / ".fanxing" / "last_batch.json").is_file()


# ---------------------------------------------------------------- 建稿加固
def test_build_timeout_reports_failure(tmp_path, monkeypatch):
    import h3_spider.canvas_apply as mod
    proj = _fixture(tmp_path)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="builder", timeout=300)

    monkeypatch.setattr(mod.subprocess, "run", boom)
    report = _build(str(proj), ["U01"])
    assert _report_failures(report)
    assert any("超时" in str(x) for r in report for x in (r.get("errors") or []))


def test_build_nonzero_exit_without_report_fails(tmp_path, monkeypatch):
    import h3_spider.canvas_apply as mod
    proj = _fixture(tmp_path)
    stale = proj / "out" / "build_report.json"
    if stale.exists():
        stale.unlink()

    class _P:
        returncode = 3
        stdout = "builder 炸了"
        stderr = "traceback"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _P())
    report = _build(str(proj), ["U01"])
    assert _report_failures(report)
    assert any("退出码" in str(x) for r in report for x in (r.get("errors") or []))


def test_build_refuses_to_read_stale_report(tmp_path, monkeypatch):
    """删不掉旧报告就别往下跑：读到的可能是上一次的假成功。"""
    import h3_spider.canvas_apply as mod
    proj = _fixture(tmp_path)
    stale = proj / "out" / "build_report.json"
    stale.write_text('[{"id": "U01", "ok": true}]', encoding="utf-8")

    def no_unlink(self, *a, **k):
        raise PermissionError("占用中")

    monkeypatch.setattr(Path, "unlink", no_unlink)
    report = _build(str(proj), ["U01"])
    assert _report_failures(report)
