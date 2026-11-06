# -*- coding: utf-8 -*-
import json

import pytest

from h3_spider import canvas_paths as P


def _project(tmp_path, name="Demo"):
    root = tmp_path / "Projects" / name
    h3 = root / "h3"
    h3.mkdir(parents=True)
    (h3 / "shots.yaml").write_text("shots: []\n", encoding="utf-8")
    return h3


def test_list_projects_only_with_shots(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "HUB_ROOT", tmp_path / "Projects")
    monkeypatch.setattr(P, "RECENT_PATH", tmp_path / "recent.json")
    (tmp_path / "Projects" / "Empty").mkdir(parents=True)
    h3 = _project(tmp_path)
    got = P.list_projects()
    assert [x["name"] for x in got] == ["Demo"]
    assert got[0]["path"] == str(h3)


def test_resolve_project_accepts_h3_or_root(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "HUB_ROOT", tmp_path / "Projects")
    monkeypatch.setattr(P, "RECENT_PATH", tmp_path / "recent.json")
    h3 = _project(tmp_path)
    assert P.resolve_project(str(h3)) == str(h3.resolve())
    assert P.resolve_project(str(h3.parent)) == str(h3.resolve())


def test_resolve_project_rejects_outside(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "HUB_ROOT", tmp_path / "Projects")
    monkeypatch.setattr(P, "RECENT_PATH", tmp_path / "recent.json")
    outside = tmp_path / "Outside" / "h3"
    outside.mkdir(parents=True)
    (outside / "shots.yaml").write_text("shots: []\n", encoding="utf-8")
    with pytest.raises(P.CanvasError) as e:
        P.resolve_project(str(outside))
    assert e.value.code == 403


def test_remember_project_writes_atomically(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "HUB_ROOT", tmp_path / "Projects")
    monkeypatch.setattr(P, "RECENT_PATH", tmp_path / "home" / ".fanxing" / "recent.json")
    outside = tmp_path / "Elsewhere" / "h3"
    outside.mkdir(parents=True)
    (outside / "shots.yaml").write_text("shots: []\n", encoding="utf-8")
    P.remember_project(str(outside))
    P.remember_project(str(outside))
    path = tmp_path / "home" / ".fanxing" / "recent.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["projects"] == [str(outside.resolve())]
    assert not list(path.parent.glob("*.tmp"))
    assert not list(path.parent.glob(".tmp-*"))


def test_recent_project_allows_outside(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "HUB_ROOT", tmp_path / "Projects")
    monkeypatch.setattr(P, "RECENT_PATH", tmp_path / "recent.json")
    outside = tmp_path / "Elsewhere" / "h3"
    outside.mkdir(parents=True)
    (outside / "shots.yaml").write_text("shots: []\n", encoding="utf-8")
    P.remember_project(str(outside))
    assert P.resolve_project(str(outside)) == str(outside.resolve())
