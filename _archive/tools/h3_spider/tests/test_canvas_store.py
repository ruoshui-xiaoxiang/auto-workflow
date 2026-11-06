# -*- coding: utf-8 -*-
import builtins
import json
import os
import re

import pytest

import h3_spider.canvas_store as canvas_store
from h3_spider.canvas_store import yaml_load, yaml_dump_atomic, read_json, write_json_atomic


SRC = """# top comment
defaults:
  scene: bridge  # inline default
shots:
  - id: U01
    duration: 8.0  # keep me
"""


def test_yaml_roundtrip_keeps_comments(tmp_path):
    p = tmp_path / "shots.yaml"
    p.write_text(SRC, encoding="utf-8")
    doc = yaml_load(str(p))
    doc["shots"][0]["duration"] = 5.875
    yaml_dump_atomic(doc, str(p))
    text = p.read_text(encoding="utf-8")
    assert "# top comment" in text
    assert "# inline default" in text
    assert "# keep me" in text
    assert "5.875" in text


def test_yaml_roundtrip_keeps_sequence_indent(tmp_path):
    src = """shots:
  - id: U01
    duration: 8.0
    cast:
      S1: cmdr
"""
    p = tmp_path / "shots.yaml"
    p.write_text(src, encoding="utf-8")
    doc = yaml_load(str(p))
    yaml_dump_atomic(doc, str(p))
    assert p.read_text(encoding="utf-8") == src


def test_json_atomic_roundtrip(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic({"a": 1, "中文": "值"}, str(p))
    assert read_json(str(p)) == {"a": 1, "中文": "值"}
    assert not (tmp_path / "x.json.tmp").exists()


def test_read_json_default_on_missing(tmp_path):
    assert read_json(str(tmp_path / "nope.json"), {"ok": False}) == {"ok": False}


# 追加到 h3_spider/tests/test_canvas_store.py
from h3_spider.canvas_store import canvas_path, default_canvas, load_canvas, save_canvas, merge_takes


def test_canvas_default_and_save(tmp_path):
    proj = tmp_path / "h3"
    proj.mkdir()
    got = load_canvas(str(proj))
    assert got["version"] == 1
    assert got["nodes"] == {}
    saved = save_canvas(str(proj), {
        "nodes": {"U01": {"pos": [1, 2, 3]}},
        "edges": [{"id": "e1", "from": "U01", "to": "U02", "type": "order"}],
    })
    assert saved["nodes"]["U01"]["pos"] == [1, 2, 3]
    assert canvas_path(str(proj)).is_file()


def test_canvas_corrupt_backs_up(tmp_path):
    proj = tmp_path / "h3"
    (proj / ".fanxing").mkdir(parents=True)
    p = canvas_path(str(proj))
    p.write_text("{broken", encoding="utf-8")
    got = load_canvas(str(proj))
    assert got["version"] == 1
    assert got["nodes"] == {}
    assert p.with_suffix(".json.bak").is_file()


def test_merge_takes_keeps_layout(tmp_path):
    proj = tmp_path / "h3"
    proj.mkdir()
    save_canvas(str(proj), {"nodes": {"U01": {"pos": [0, 0, 0]}}})
    merge_takes(str(proj), {"U01": [{"id": "t1", "path": "a.mp4"}]})
    doc = load_canvas(str(proj))
    assert doc["nodes"]["U01"]["pos"] == [0, 0, 0]
    assert doc["takes"]["U01"][0]["id"] == "t1"


# --- 原子写加固（Task 1/2 复盘项）---
def test_write_json_accepts_path(tmp_path):
    p = tmp_path / "sub" / "x.json"
    write_json_atomic({"a": 1}, p)
    assert read_json(str(p)) == {"a": 1}
    assert not list(tmp_path.rglob("*.tmp"))
    # 唯一临时文件用 .tmp- 前缀，成功后不得残留
    assert [x.name for x in p.parent.iterdir()] == ["x.json"]


def test_yaml_dump_path_object_and_cleanup(tmp_path, monkeypatch):
    class Boom:
        def dump(self, doc, stream):
            raise RuntimeError("boom")

    monkeypatch.setattr(canvas_store, "_yaml", lambda: Boom())
    p = tmp_path / "deep" / "shots.yaml"
    with pytest.raises(RuntimeError):
        yaml_dump_atomic({"shots": []}, p)
    assert not (tmp_path / "deep" / "shots.yaml.tmp").exists()
    assert not p.exists()
    deep = tmp_path / "deep"
    assert ([] if not deep.is_dir() else [x.name for x in deep.iterdir()]) == []


def test_write_json_uses_unique_same_dir_tmp(tmp_path, monkeypatch):
    seen = []
    real_mkstemp = canvas_store.tempfile.mkstemp

    def spy_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        seen.append(name)
        return fd, name

    monkeypatch.setattr(canvas_store.tempfile, "mkstemp", spy_mkstemp)
    p = tmp_path / "sub" / "x.json"
    write_json_atomic({"a": 1}, str(p))
    write_json_atomic({"a": 2}, str(p))

    assert len(seen) == 2
    assert seen[0] != seen[1]
    for name in seen:
        assert os.path.dirname(name) == os.path.dirname(os.path.abspath(str(p)))
        assert os.path.basename(name).startswith(".tmp-")
        assert not os.path.exists(name)
    assert read_json(str(p)) == {"a": 2}


def test_write_json_failure_leaves_no_residue(tmp_path):
    p = tmp_path / "deep" / "x.json"
    with pytest.raises(TypeError):
        write_json_atomic({"bad": object()}, str(p))
    assert not p.exists()
    assert [x.name for x in p.parent.iterdir()] == []


# --- 复盘：IO 错误不算损坏，损坏备份不许被覆盖 ---
def _deny_open(monkeypatch, target):
    """target 的读取一律抛 PermissionError：同时拦住 builtins.open 与 Path.open
    （Path.read_bytes() 走的是 Path.open，不经过 builtins.open）。"""
    import pathlib

    real_open = builtins.open
    real_path_open = pathlib.Path.open

    def fake_open(file, *args, **kwargs):
        if str(file) == str(target):
            raise PermissionError(13, "denied", str(target))
        return real_open(file, *args, **kwargs)

    def fake_path_open(self, *args, **kwargs):
        if str(self) == str(target):
            raise PermissionError(13, "denied", str(target))
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(pathlib.Path, "open", fake_path_open)


def test_load_canvas_reraises_read_oserror(tmp_path, monkeypatch):
    proj = tmp_path / "h3"
    (proj / ".fanxing").mkdir(parents=True)
    p = canvas_path(str(proj))
    p.write_text('{"version": 1, "nodes": {}}', encoding="utf-8")

    _deny_open(monkeypatch, p)
    with pytest.raises(OSError):
        load_canvas(str(proj))
    monkeypatch.undo()

    # 不重命名、不静默返回默认值
    assert p.is_file()
    assert p.read_bytes() == b'{"version": 1, "nodes": {}}'
    assert not p.with_suffix(".json.bak").exists()
    assert not list(p.parent.glob("canvas.json.bak*"))


def test_load_canvas_second_corruption_keeps_first_backup(tmp_path):
    proj = tmp_path / "h3"
    (proj / ".fanxing").mkdir(parents=True)
    p = canvas_path(str(proj))

    p.write_text("{broken", encoding="utf-8")
    assert load_canvas(str(proj))["version"] == 1
    first_bak = p.with_suffix(".json.bak")
    assert first_bak.is_file()
    first_text = first_bak.read_text(encoding="utf-8")
    assert first_text == "{broken"

    p.write_text("{broken-again", encoding="utf-8")
    assert load_canvas(str(proj))["version"] == 1

    assert first_bak.is_file()
    assert first_bak.read_text(encoding="utf-8") == first_text
    stamped = sorted(p.parent.glob("canvas.json.bak.2*"))
    assert stamped, "第二次损坏应另存为 canvas.json.bak.<YYYYmmdd_HHMMSS>"
    assert stamped[-1].read_text(encoding="utf-8") == "{broken-again"


def test_load_canvas_non_object_backs_up(tmp_path):
    proj = tmp_path / "h3"
    (proj / ".fanxing").mkdir(parents=True)
    p = canvas_path(str(proj))
    p.write_text('["U01"]', encoding="utf-8")
    got = load_canvas(str(proj))
    assert got["nodes"] == {}
    assert got["version"] == 1
    assert p.with_suffix(".json.bak").is_file()


def test_load_canvas_invalid_utf8_backs_up(tmp_path):
    proj = tmp_path / "h3"
    (proj / ".fanxing").mkdir(parents=True)
    p = canvas_path(str(proj))
    p.write_bytes(b"\xff\xfe\x00")

    got = load_canvas(str(proj))
    assert got["version"] == 1
    assert got["nodes"] == {}
    assert p.with_suffix(".json.bak").is_file()


def test_merge_takes_refreshes_updated_at(tmp_path):
    proj = tmp_path / "h3"
    proj.mkdir()
    save_canvas(str(proj), {"nodes": {}})
    p = canvas_path(str(proj))
    stale = read_json(str(p))
    stale["updated_at"] = "2000-01-01T00:00:00"
    write_json_atomic(stale, str(p))

    doc = merge_takes(str(proj), {"U01": [{"id": "t1"}]})
    assert doc["version"] == 1
    assert doc["takes"]["U01"][0]["id"] == "t1"
    assert doc["updated_at"] != "2000-01-01T00:00:00"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", doc["updated_at"])
    assert read_json(str(p))["updated_at"] == doc["updated_at"]
