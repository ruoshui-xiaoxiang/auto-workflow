# -*- coding: utf-8 -*-
"""项目发现与路径白名单。"""
import json
from pathlib import Path

from .canvas_store import write_json_atomic

HUB_ROOT = Path(r"C:\Users\若水\Movies\Hub\Projects")
RECENT_PATH = Path.home() / ".fanxing" / "canvas_recent.json"


class CanvasError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def is_within(child, root):
    try:
        Path(child).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def recent_paths():
    try:
        data = json.loads(RECENT_PATH.read_text(encoding="utf-8"))
        return [str(Path(x)) for x in data.get("projects", [])]
    except Exception:
        return []


def remember_project(project):
    p = str(Path(project).resolve())
    items = [x for x in recent_paths() if x != p]
    items.insert(0, p)
    write_json_atomic({"projects": items[:10]}, str(RECENT_PATH))


def list_projects():
    out = []
    if not HUB_ROOT.is_dir():
        return out
    for d in sorted(HUB_ROOT.iterdir()):
        h3 = d / "h3"
        shots = h3 / "shots.yaml"
        if not shots.is_file():
            continue
        out.append({
            "name": d.name,
            "path": str(h3.resolve()),
            "mtime": int(shots.stat().st_mtime),
            "shot_count": _count_shots(shots),
        })
    return out


def _count_shots(path):
    try:
        from .canvas_store import yaml_load
        doc = yaml_load(str(path)) or {}
        return len(doc.get("shots") or [])
    except Exception:
        return 0


def resolve_project(raw):
    if not raw:
        raise CanvasError("缺 project 参数", 400)
    p = Path(raw).resolve()
    if p.name != "h3" and (p / "h3" / "shots.yaml").is_file():
        p = p / "h3"
    if not (p / "shots.yaml").is_file():
        raise CanvasError("缺 shots.yaml：%s" % p, 404)
    allowed = [HUB_ROOT.resolve()] + [Path(x).resolve() for x in recent_paths()]
    if not any(is_within(p, root) for root in allowed):
        raise CanvasError("项目不在允许范围：%s" % p, 403)
    return str(p)


def project_root(project):
    return str(Path(project).resolve().parent)
