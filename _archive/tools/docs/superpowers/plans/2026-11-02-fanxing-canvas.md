# 繁星画布（星图分镜板）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 3D 星图的「镜头」星系升级成可编辑分镜画布，支持三线型、镜头卡编辑、写回 `shots.yaml`、单镜/整批出片与 take A/B。

**Architecture:** 后端在 `D:\AIWorkflow\tools\h3_spider` 新增 `canvas_paths/store/edges/state/apply/jobs/api` 七个模块，挂到现有 8777 dashboard；前端在 `map3d.js` 暴露 `window.__fanxingMap`，新交互放 `storyboard.js`，纯逻辑放 `storyboard_model.js` 供 `node --test`。`shots.yaml` 是唯一生成真源，`.fanxing/canvas.json` 只存布局、连线、批注与 take 选用。

**Tech Stack:** Python 3.12、`ruamel.yaml`（新依赖）、PyYAML（已有）、ThreadingHTTPServer、pytest；Three.js（已有 vendor）、原生 ES module、`node --test`；ComfyUI 8189、`fanxing`/`h3_spider` 现有管线。

**Spec:** `D:\AIWorkflow\tools\docs\superpowers\specs\2026-11-02-fanxing-canvas-design.md`

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `h3_spider/canvas_paths.py` | 项目发现、路径白名单、最近项目 |
| `h3_spider/canvas_store.py` | ruamel YAML 读写、原子 JSON、`canvas.json` |
| `h3_spider/canvas_edges.py` | 三线型规则、拓扑排序、写回映射 |
| `h3_spider/canvas_state.py` | 组装镜头/锚点/状态/takes/资产列表 |
| `h3_spider/canvas_apply.py` | 差异校验、备份、写回、自动建稿+闸 |
| `h3_spider/canvas_jobs.py` | 单任务队列、子进程、日志环、取消 |
| `h3_spider/canvas_api.py` | `/api/projects`、`/api/canvas*` 路由 |
| `h3_spider/storyboard_model.js` | 纯函数：布局、吸附、框选、边类型、撤销栈 |
| `h3_spider/storyboard.js` | 3D 交互、镜头卡、A/B、项目切换 |
| `h3_spider/map3d.js` | 只加模式开关与 `window.__fanxingMap` 钩子 |
| `h3_spider/map3d.html` | 按钮、卡片容器、样式 |
| `h3_spider/tests/test_canvas_*.py` | 后端测试 |
| `h3_spider/tests_js/storyboard_model.test.mjs` | 前端纯函数测试 |

每个任务只 `git add` 自己涉及的文件，不碰仓库里已有的未提交改动。

---

## Milestone 0：依赖与地基

### Task 1: 安装 ruamel.yaml 并实现保注释 YAML 读写

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_store.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_store.py`

- [ ] **Step 1: 安装依赖**

Run:
```bash
cd /d/AIWorkflow/tools
py -3.12 -m pip install ruamel.yaml
py -3.12 -c "import ruamel.yaml; print(ruamel.yaml.__version__)"
```
Expected: 打印版本号，无报错。

- [ ] **Step 2: 写失败测试**

```python
# h3_spider/tests/test_canvas_store.py
# -*- coding: utf-8 -*-
import json

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


def test_json_atomic_roundtrip(tmp_path):
    p = tmp_path / "x.json"
    write_json_atomic({"a": 1, "中文": "值"}, str(p))
    assert read_json(str(p)) == {"a": 1, "中文": "值"}
    assert not (tmp_path / "x.json.tmp").exists()


def test_read_json_default_on_missing(tmp_path):
    assert read_json(str(tmp_path / "nope.json"), {"ok": False}) == {"ok": False}
```

- [ ] **Step 3: 跑测试确认失败**

Run:
```bash
cd /d/AIWorkflow/tools
py -3.12 -m pytest h3_spider/tests/test_canvas_store.py -q
```
Expected: FAIL，`ModuleNotFoundError: No module named 'h3_spider.canvas_store'`。

- [ ] **Step 4: 写最小实现**

```python
# h3_spider/canvas_store.py
# -*- coding: utf-8 -*-
"""画布持久化：ruamel YAML（保注释）+ 原子 JSON。"""
import io
import json
import os

from ruamel.yaml import YAML


def _yaml():
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    return y


def yaml_load(path):
    with open(path, "r", encoding="utf-8") as f:
        return _yaml().load(f)


def yaml_dump_text(doc):
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def yaml_dump_atomic(doc, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(yaml_dump_text(doc))
    os.replace(tmp, path)


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
```

- [ ] **Step 5: 跑测试确认通过**

Run:
```bash
py -3.12 -m pytest h3_spider/tests/test_canvas_store.py -q
```
Expected: `3 passed`。

- [ ] **Step 6: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_store.py h3_spider/tests/test_canvas_store.py
git commit -m "feat(canvas): add comment-preserving yaml and atomic json store"
```

---

### Task 2: 项目发现与路径白名单

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_paths.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_paths.py`

- [ ] **Step 1: 写失败测试**

```python
# h3_spider/tests/test_canvas_paths.py
# -*- coding: utf-8 -*-
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


def test_recent_project_allows_outside(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "HUB_ROOT", tmp_path / "Projects")
    monkeypatch.setattr(P, "RECENT_PATH", tmp_path / "recent.json")
    outside = tmp_path / "Elsewhere" / "h3"
    outside.mkdir(parents=True)
    (outside / "shots.yaml").write_text("shots: []\n", encoding="utf-8")
    P.remember_project(str(outside))
    assert P.resolve_project(str(outside)) == str(outside.resolve())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_paths.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 写实现**

```python
# h3_spider/canvas_paths.py
# -*- coding: utf-8 -*-
"""项目发现与路径白名单。"""
import json
import os
from pathlib import Path

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
    RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECENT_PATH.write_text(
        json.dumps({"projects": items[:10]}, ensure_ascii=False, indent=1),
        encoding="utf-8")


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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_paths.py -q`
Expected: `4 passed`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_paths.py h3_spider/tests/test_canvas_paths.py
git commit -m "feat(canvas): add project discovery and path guard"
```

---

### Task 3: `.fanxing/canvas.json` 读写

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\canvas_store.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_store.py`

- [ ] **Step 1: 追加失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_store.py -q`
Expected: FAIL，`canvas_path` 未定义。

- [ ] **Step 3: 实现**

```python
# 追加到 h3_spider/canvas_store.py
import time
from pathlib import Path


def canvas_path(project):
    return Path(project) / ".fanxing" / "canvas.json"


def default_canvas(project):
    return {
        "version": 1,
        "project": str(project),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "view": {"camera_preset": "top", "bookmarks": {}},
        "nodes": {},
        "edges": [],
        "annotations": {},
        "takes": {},
    }


def load_canvas(project):
    p = canvas_path(project)
    if not p.is_file():
        return default_canvas(project)
    try:
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            raise ValueError("not an object")
        return doc
    except Exception:
        os.replace(str(p), str(p.with_suffix(".json.bak")))
        return default_canvas(project)


def save_canvas(project, patch):
    doc = load_canvas(project)
    for key in ("view", "nodes", "edges", "annotations"):
        if key in patch and isinstance(patch[key], (dict, list)):
            doc[key] = patch[key]
    doc["version"] = 1
    doc["project"] = str(project)
    doc["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    write_json_atomic(doc, str(canvas_path(project)))
    return doc


def merge_takes(project, takes):
    doc = load_canvas(project)
    current = doc.get("takes") or {}
    for sid, items in (takes or {}).items():
        current[sid] = items
    doc["takes"] = current
    write_json_atomic(doc, str(canvas_path(project)))
    return doc
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_store.py -q`
Expected: `6 passed`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_store.py h3_spider/tests/test_canvas_store.py
git commit -m "feat(canvas): persist layout, edges, annotations and takes"
```

---

## Milestone 1：后端规则与写回

### Task 4: 三线型与拓扑规则

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_edges.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_edges.py`

- [ ] **Step 1: 写失败测试**

```python
# h3_spider/tests/test_canvas_edges.py
# -*- coding: utf-8 -*-
import copy

import pytest

from h3_spider.canvas_edges import EdgeError, apply_edges, auto_edges, topo_order


SHOTS = [
    {"id": "U01", "image": "a.png", "mode": "i2va"},
    {"id": "U02", "image": "b.png", "mode": "ref2va", "images": ["cmdr"]},
    {"id": "U03", "image": "c.png", "mode": "ref2va"},
]


def test_topo_order_reorders():
    edges = [
        {"from": "U02", "to": "U01", "type": "order"},
        {"from": "U01", "to": "U03", "type": "order"},
    ]
    assert topo_order(["U01", "U02", "U03"], edges) == ["U02", "U01", "U03"]


def test_topo_order_rejects_cycle():
    edges = [
        {"from": "U01", "to": "U02", "type": "order"},
        {"from": "U02", "to": "U01", "type": "order"},
    ]
    with pytest.raises(EdgeError):
        topo_order(["U01", "U02"], edges)


def test_topo_order_without_edges_keeps_input():
    assert topo_order(["U01", "U02"], []) == ["U01", "U02"]


def test_no_order_edges_does_not_require_connectivity():
    assert topo_order(["U01", "U02", "U03"], []) == ["U01", "U02", "U03"]


def test_chain_sets_target_image():
    edges = [{"from": "U01", "to": "U02", "type": "chain", "binding": "U01_end.png"}]
    out = apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": "cmdr"})
    assert out[1]["image"] == "U01_end.png"


def test_chain_without_binding_rejected():
    edges = [{"from": "U01", "to": "U02", "type": "chain"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {})


def test_ref_adds_anchor_and_dedupes():
    edges = [
        {"from": "U03", "to": "@cmdr", "type": "ref"},
        {"from": "U03", "to": "@cmdr", "type": "ref"},
    ]
    out = apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": "cmdr"})
    assert out[2]["images"] == ["cmdr"]


def test_ref_rejects_i2va():
    edges = [{"from": "U01", "to": "@cmdr", "type": "ref"}]
    with pytest.raises(EdgeError):
        apply_edges(copy.deepcopy(SHOTS), edges, {"cmdr": "cmdr"})


def test_auto_edges_creates_order_chain():
    edges = auto_edges(SHOTS)
    assert [e["type"] for e in edges] == ["order", "order"]
    assert edges[0]["from"] == "U01" and edges[0]["to"] == "U02"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_edges.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 写实现**

```python
# h3_spider/canvas_edges.py
# -*- coding: utf-8 -*-
"""三线型规则：order / chain / ref。"""
from .canvas_paths import CanvasError


class EdgeError(CanvasError):
    def __init__(self, message):
        super().__init__(message, 422)


def auto_edges(shots):
    ids = [s["id"] for s in shots]
    return [
        {"id": "auto-%d" % i, "from": ids[i], "to": ids[i + 1], "type": "order"}
        for i in range(len(ids) - 1)
    ]


def topo_order(ids, edges):
    orders = [e for e in edges if e.get("type") == "order"]
    if not orders:
        return list(ids)
    known = set(ids)
    nxt = {}
    indeg = {i: 0 for i in ids}
    for e in orders:
        a, b = e.get("from"), e.get("to")
        if a not in known or b not in known:
            raise EdgeError("片序边引用了不存在的镜头：%s -> %s" % (a, b))
        if b in indeg and indeg[b] > 0:
            raise EdgeError("镜头 %s 有多个片序父节点" % b)
        indeg[b] += 1
        nxt[a] = b
    roots = [i for i in ids if indeg[i] == 0]
    if len(roots) != 1:
        raise EdgeError("片序必须只有一个起点，实际 %d 个" % len(roots))
    if len(orders) != len(ids) - 1:
        raise EdgeError("一旦使用片序边，所有镜头必须串成一条链")
    out, cur, seen = [], roots[0], set()
    while cur is not None:
        if cur in seen:
            raise EdgeError("片序存在环")
        seen.add(cur)
        out.append(cur)
        cur = nxt.get(cur)
    if len(out) != len(ids):
        raise EdgeError("片序有游离节点")
    return out


def apply_edges(shots, edges, anchors):
    """order/chain: from=上游, to=下游；ref: from=引用者, to=参考源(镜头或@锚点)。"""
    by_id = {s["id"]: s for s in shots}
    order = topo_order([s["id"] for s in shots], edges)
    for e in edges:
        kind = e.get("type")
        if kind == "order":
            continue
        if kind == "chain":
            source, target_id = e.get("from") or "", e.get("to")
        elif kind == "ref":
            source, target_id = e.get("to") or "", e.get("from")
        else:
            raise EdgeError("未知线型：%s" % kind)
        target = by_id.get(target_id)
        if target is None:
            raise EdgeError("边指向不存在的镜头：%s" % target_id)
        if kind == "chain":
            binding = e.get("binding")
            if not binding:
                raise EdgeError("首尾帧链 %s -> %s 未绑定末帧" % (source, target_id))
            target["image"] = binding
        else:
            if target.get("mode") not in ("ref2va", "multiref"):
                raise EdgeError("参考依赖只能连到 ref2va/multiref 镜头：%s" % target_id)
            if source.startswith("@"):
                name = source[1:]
                if name not in anchors:
                    raise EdgeError("锚点不存在：%s" % source)
                value = anchors[name]
            else:
                src = by_id.get(source)
                if src is None:
                    raise EdgeError("参考边引用了不存在的镜头：%s" % source)
                value = src.get("image")
                if not value:
                    raise EdgeError("参考源镜头没有 image：%s" % source)
            imgs = target.get("images")
            if not isinstance(imgs, list):
                imgs = []
                target["images"] = imgs
            if value not in imgs:
                imgs.append(value)
    return [by_id[i] for i in order]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_edges.py -q`
Expected: `9 passed`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_edges.py h3_spider/tests/test_canvas_edges.py
git commit -m "feat(canvas): add order, chain and reference edge rules"
```

---

### Task 5: 组装画布状态（镜头/锚点/状态/takes/资产）

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_state.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_state.py`

- [ ] **Step 1: 写失败测试**

```python
# h3_spider/tests/test_canvas_state.py
# -*- coding: utf-8 -*-
import json

from h3_spider.canvas_state import find_last_batch, list_assets, load_state, scan_takes


def _mk(tmp_path):
    proj = tmp_path / "Demo" / "h3"
    proj.mkdir(parents=True)
    (proj / "shots.yaml").write_text(
        "defaults:\n  scene: bridge\nshots:\n"
        "  - id: U01\n    mode: i2va\n    duration: 8.0\n    image: U01_start.png\n"
        "  - id: U02\n    mode: ref2va\n    duration: 5.875\n    image: cmdr\n    cast: {S1: cmdr}\n",
        encoding="utf-8")
    (proj / "characters.yaml").write_text(
        "roles:\n  cmdr:\n    role: the commander\n", encoding="utf-8")
    (proj / "scenes.yaml").write_text(
        "scenes:\n  bridge:\n    geometry: x\n", encoding="utf-8")
    (proj / "assets" / "crops").mkdir(parents=True)
    (proj / "assets" / "crops" / "cmdr.png").write_bytes(b"png")
    (proj.parent / "outputs").mkdir()
    (proj.parent / "outputs" / "KB23_U01_00001-audio.mp4.mp4").write_bytes(b"v")
    return proj


def test_load_state_shots_and_anchors(tmp_path):
    proj = _mk(tmp_path)
    st = load_state(str(proj))
    assert [s["id"] for s in st["shots"]] == ["U01", "U02"]
    assert st["anchors"][0]["id"] == "@cmdr"
    assert st["anchors"][0]["label"] == "cmdr"
    assert st["edges"][0]["type"] == "order"


def test_scan_takes_groups_by_shot(tmp_path):
    proj = _mk(tmp_path)
    takes = scan_takes(str(proj))
    assert takes["U01"][0]["path"].endswith(".mp4")


def test_list_assets_includes_crops(tmp_path):
    proj = _mk(tmp_path)
    assets = list_assets(str(proj))
    assert any(a["path"].endswith("crops/cmdr.png") for a in assets)


def test_find_last_batch_reads_marker(tmp_path):
    proj = _mk(tmp_path)
    qc = tmp_path / "qc"
    qc.mkdir()
    (qc / "batch_verdict.json").write_text('{"overall":"PASS","shots":{}}', encoding="utf-8")
    (proj / ".fanxing").mkdir()
    (proj / ".fanxing" / "last_batch.json").write_text(
        json.dumps({"batch_dir": str(qc)}), encoding="utf-8")
    assert find_last_batch(str(proj)) == str(qc)


def test_remember_run_is_scanned(tmp_path):
    from h3_spider.canvas_state import remember_run
    proj = _mk(tmp_path)
    run = tmp_path / "job_run"
    run.mkdir()
    (run / "U01_00003-audio.mp4").write_bytes(b"v")
    remember_run(str(proj), str(run))
    takes = scan_takes(str(proj))
    assert any(t["path"].endswith("U01_00003-audio.mp4") for t in takes["U01"])


def test_load_state_reads_prompt_preview(tmp_path):
    proj = _mk(tmp_path)
    (proj / "out").mkdir()
    (proj / "out" / "U01.txt").write_text("preview text", encoding="utf-8")
    st = load_state(str(proj))
    assert st["prompts"]["U01"].startswith("preview text")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_state.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 写实现**

```python
# h3_spider/canvas_state.py
# -*- coding: utf-8 -*-
"""把项目文件组装成画布需要的状态。"""
import os
import re
from pathlib import Path

from .canvas_edges import auto_edges
from .canvas_paths import project_root
from .canvas_store import load_canvas, read_json, write_json_atomic, yaml_load

SHOT_RE = re.compile(r"(U\d+|SH\d+)", re.I)
VIDEO_EXT = {".mp4", ".mov", ".webm"}


def load_state(project):
    proj = Path(project)
    root = Path(project_root(project))
    shots_doc = yaml_load(str(proj / "shots.yaml")) or {}
    shots = list(shots_doc.get("shots") or [])
    chars = _load_optional(proj / "characters.yaml")
    scenes = _load_optional(proj / "scenes.yaml")
    anchors = _anchors(chars, scenes)
    canvas = load_canvas(project)
    edges = canvas.get("edges") or auto_edges(shots)
    batch_dir = find_last_batch(project)
    status = _status(batch_dir)
    return {
        "project": str(proj.resolve()),
        "project_root": str(root),
        "defaults": dict(shots_doc.get("defaults") or {}),
        "shots": shots,
        "anchors": anchors,
        "edges": edges,
        "canvas": canvas,
        "batch_dir": batch_dir,
        "status": status,
        "takes": scan_takes(project),
        "prompts": _prompts(proj, shots),
        "assets": list_assets(project),
    }


def _prompts(proj, shots):
    out = {}
    for s in shots:
        p = Path(proj) / "out" / (s["id"] + ".txt")
        if p.is_file():
            try:
                out[s["id"]] = p.read_text(encoding="utf-8")[:8000]
            except Exception:
                pass
    return out


def _load_optional(p):
    if not p.is_file():
        return {}
    try:
        return yaml_load(str(p)) or {}
    except Exception:
        return {}


def _anchors(chars, scenes):
    out = []
    for name in (chars.get("roles") or {}):
        out.append({"id": "@" + name, "label": name, "kind": "cast"})
    for name in (scenes.get("scenes") or {}):
        out.append({"id": "@" + name, "label": name, "kind": "scene"})
    return out


def find_last_batch(project):
    marker = Path(project) / ".fanxing" / "last_batch.json"
    doc = read_json(str(marker), {}) or {}
    bd = doc.get("batch_dir")
    if bd and os.path.isfile(os.path.join(bd, "batch_verdict.json")):
        return bd
    return ""


def _status(batch_dir):
    if not batch_dir:
        return {}
    doc = read_json(os.path.join(batch_dir, "batch_verdict.json"), {}) or {}
    out = {}
    for sid, rec in (doc.get("shots") or {}).items():
        v = rec.get("verdict.json") or rec
        out[sid] = v.get("overall") or "?"
    return out


def scan_takes(project):
    root = Path(project_root(project))
    out = {}
    bases = [root / "outputs", root / "assets", root / "work"]
    bases += [Path(x) for x in _remembered_runs(project)]
    for base in bases:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in VIDEO_EXT:
                continue
            m = SHOT_RE.search(p.name)
            if not m:
                continue
            sid = m.group(1).upper()
            out.setdefault(sid, []).append({
                "id": p.stem + ":" + str(int(p.stat().st_mtime)),
                "path": str(p),
                "mtime": int(p.stat().st_mtime),
                "bytes": p.stat().st_size,
            })
    for sid in out:
        out[sid].sort(key=lambda x: x["mtime"], reverse=True)
    return out


RUNS_MARKER = ".fanxing/runs.json"


def _remembered_runs(project):
    return (read_json(str(Path(project) / RUNS_MARKER), {}) or {}).get("runs", [])


def remember_run(project, run_dir):
    p = Path(project) / RUNS_MARKER
    doc = read_json(str(p), {}) or {}
    runs = [x for x in doc.get("runs", []) if x != run_dir]
    runs.insert(0, run_dir)
    doc["runs"] = runs[:20]
    write_json_atomic(doc, str(p))


def list_assets(project):
    proj = Path(project)
    root = Path(project_root(project))
    roots = [proj / "assets" / "crops", proj / "assets", root / "assets",
             root / "合并_第二十三星区" / "04_外部依赖快照"]
    seen, out = set(), []
    for base in roots:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append({"path": key, "name": p.name,
                        "mtime": int(p.stat().st_mtime), "bytes": p.stat().st_size})
            if len(out) >= 500:
                return out
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_state.py -q`
Expected: `4 passed`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_state.py h3_spider/tests/test_canvas_state.py
git commit -m "feat(canvas): assemble project state for the board"
```

---

### Task 6: 写回校验、备份与自动闸门

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_apply.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_apply.py`

- [ ] **Step 1: 写失败测试**

```python
# h3_spider/tests/test_canvas_apply.py
# -*- coding: utf-8 -*-
import shutil
from pathlib import Path

import pytest

from h3_spider.canvas_apply import apply_draft, validate_draft

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_apply.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 写实现**

```python
# h3_spider/canvas_apply.py
# -*- coding: utf-8 -*-
"""差异校验、备份、写回 shots.yaml、自动建稿+闸。"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .canvas_edges import apply_edges
from .canvas_paths import CanvasError
from .canvas_store import yaml_load, yaml_dump_atomic

TOOLS = str(Path(__file__).resolve().parent.parent)
INPUT_DIR = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"
VALID = {4.5} | {round((17 * n + 5) / 24, 3) for n in range(7, 21)}
FIELDS = ("mode", "canvas", "duration", "image", "last_image", "images",
          "cast", "content", "dialogue", "soundscape", "music", "scene", "summary")


def validate_draft(project, drafts, edges, anchors):
    errors = []
    by_id = {}
    doc = yaml_load(os.path.join(project, "shots.yaml"))
    for shot in doc.get("shots") or []:
        by_id[shot["id"]] = shot
    for d in drafts:
        sid = d.get("id")
        if sid not in by_id:
            errors.append({"shot": sid, "message": "镜头不存在"})
            continue
        dur = float(d.get("duration", by_id[sid].get("duration", 0)))
        if round(dur, 3) not in VALID:
            errors.append({"shot": sid, "message": "时长 %.3f 不在 17 帧档位" % dur})
    if errors:
        return errors
    try:
        apply_edges([dict(x) for x in (doc.get("shots") or [])], edges, anchors)
    except CanvasError as e:
        errors.append({"shot": "", "message": str(e)})
    return errors


def _merge(doc, drafts):
    by_id = {s["id"]: s for s in (doc.get("shots") or [])}
    for d in drafts:
        shot = by_id.get(d.get("id"))
        if shot is None:
            raise CanvasError("镜头不存在：%s" % d.get("id"), 422)
        for key in FIELDS:
            if key not in d:
                continue
            if key == "content" and isinstance(d[key], dict):
                shot.setdefault("content", {}).update(d[key])
            elif key == "dialogue" and isinstance(d[key], list):
                cur = shot.setdefault("dialogue", [])
                for i, item in enumerate(d[key]):
                    if i < len(cur) and isinstance(item, dict):
                        cur[i].update(item)
                    else:
                        cur.append(item)
            else:
                shot[key] = d[key]
    return doc


def add_shot(project, template_id):
    import copy
    from ruamel.yaml.comments import CommentedMap
    from .canvas_store import yaml_load, yaml_dump_atomic
    path = str(Path(project) / "shots.yaml")
    doc = yaml_load(path)
    seq = doc["shots"]
    by_id = {s["id"]: s for s in seq}
    tpl = by_id.get(template_id)
    if tpl is None:
        raise CanvasError("模板镜头不存在：%s" % template_id, 422)
    nums = [int(s["id"][1:]) for s in seq
            if isinstance(s.get("id"), str) and s["id"][:1] == "U"
            and s["id"][1:].isdigit()]
    nid = "U%02d" % (max(nums) + 1) if nums else "SH01"
    shot = copy.deepcopy(tpl)
    shot["id"] = nid
    seq.append(CommentedMap(shot))
    _backup_shots(proj)
    yaml_dump_atomic(doc, path)
    return nid


def delete_shot(project, sid):
    from .canvas_store import yaml_load, yaml_dump_atomic
    proj = Path(project)
    path = str(proj / "shots.yaml")
    doc = yaml_load(path)
    seq = doc["shots"]
    keep = [s for s in seq if s["id"] != sid]
    if len(keep) == len(seq):
        raise CanvasError("镜头不存在：%s" % sid, 404)
    seq[:] = keep
    _backup_shots(proj)
    yaml_dump_atomic(doc, path)
    return sid


def _backup_shots(proj):
    backup = Path(proj) / ".fanxing" / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(str(Path(proj) / "shots.yaml"),
                 str(backup / ("shots.%s.adddel.yaml" % stamp)))


def apply_draft(project, drafts, edges, anchors, run_gate=True, dry_run=False):
    proj = Path(project)
    root = proj.parent
    shots_path = proj / "shots.yaml"
    doc = yaml_load(str(shots_path))
    errs = validate_draft(project, drafts, edges, anchors)
    if errs:
        raise CanvasError("；".join(e["message"] for e in errs), 422)
    doc = _merge(doc, drafts)
    shots = [dict(s) for s in (doc.get("shots") or [])]
    moved = apply_edges(shots, edges, anchors)
    seq = doc["shots"]
    order = {id(s): i for i, s in enumerate(seq)}
    by_obj = {s["id"]: s for s in seq}
    seq[:] = [by_obj[s["id"]] for s in moved]

    # 写盘前先用同一套 builder 在临时项目里预演；失败就一个字都不动
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="canvas_pre_"))
    try:
        for name in ("characters.yaml", "scenes.yaml", "lexicon.yaml"):
            src = proj / name
            if src.is_file():
                shutil.copy2(str(src), str(tmp / name))
        yaml_dump_atomic(doc, str(tmp / "shots.yaml"))
        (tmp / "out").mkdir()
        pre = _build(str(tmp), [d["id"] for d in drafts])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    pre_failed = [r for r in pre if not r.get("ok")]
    if pre_failed:
        raise CanvasError("；".join(
            "%s: %s" % (r.get("id"), " / ".join(r.get("errors") or []))
            for r in pre_failed), 422)

    if dry_run:
        import difflib
        from .canvas_store import yaml_dump_text
        before = shots_path.read_text(encoding="utf-8")
        after = yaml_dump_text(doc)
        return {"ok": True, "dry_run": True,
                "diff": list(difflib.unified_diff(
                    before.splitlines(), after.splitlines(),
                    fromfile="shots.yaml (before)", tofile="shots.yaml (after)",
                    lineterm=""))}

    backup = proj / ".fanxing" / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(str(shots_path), str(backup / ("shots.%s.yaml" % stamp)))
    yaml_dump_atomic(doc, str(shots_path))

    report = _build(project, [d["id"] for d in drafts])
    failed = [r for r in report if not r.get("ok")]
    out = {"ok": not failed, "backup": str(backup / ("shots.%s.yaml" % stamp)),
           "build": report, "batch_dir": "", "gate": None}
    if failed or not run_gate:
        return out

    batch_dir = str(Path(r"C:/Temp/fanxing_runs") / ("canvas_apply_" + stamp) / "qc")
    from .batch import run_batch
    run_batch(project, INPUT_DIR, batch_dir, shots=[d["id"] for d in drafts], force=True)
    marker = proj / ".fanxing" / "last_batch.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"batch_dir": batch_dir}, ensure_ascii=False), encoding="utf-8")
    from .gate import check_batch_gate
    ok, reasons, info = check_batch_gate(project, batch_dir, [d["id"] for d in drafts])
    out.update({"batch_dir": batch_dir, "gate": {"ok": ok, "reasons": reasons, "info": info}})
    out["ok"] = ok
    return out


def _build(project, ids):
    out_dir = Path(project) / "out"
    cmd = [sys.executable, "h3_prompt_builder.py", "build", "--project", project,
           "--out-dir", str(out_dir), "--only"] + list(ids)
    p = subprocess.run(cmd, cwd=TOOLS, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    report_path = out_dir / "build_report.json"
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return [{"id": ids[0] if ids else "?", "ok": False,
                 "errors": [p.stdout[-500:] + p.stderr[-500:]]}]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_apply.py -q`
Expected: `3 passed`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_apply.py h3_spider/tests/test_canvas_apply.py
git commit -m "feat(canvas): validate, back up and write shots.yaml, then gate"
```

---

### Task 7: 画布 API 与 8777 路由

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_api.py`
- Modify: `D:\AIWorkflow\tools\h3_spider\dashboard.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_api.py`

- [ ] **Step 1: 写失败测试**

```python
# h3_spider/tests/test_canvas_api.py
# -*- coding: utf-8 -*-
import json

from h3_spider import canvas_api


class Fake:
    def __init__(self):
        self.code = None
        self.obj = None
        self.body = b""

    def _json(self, obj, code=200):
        self.code, self.obj = code, obj

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.code, self.body = code, body


def test_projects_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "list_projects", lambda: [{"name": "X"}])
    h = Fake()
    canvas_api.handle(h, "GET", "/api/projects", "")
    assert h.code == 200
    assert h.obj["projects"][0]["name"] == "X"


def test_canvas_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "load_state", lambda p: {"shots": [{"id": "U01"}]})
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas", "project=P")
    assert h.obj["shots"][0]["id"] == "U01"


def test_save_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "save_canvas", lambda p, patch: {"ok": True, **patch})
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/save",
                      "", json.dumps({"project": "P", "nodes": {"U01": {}}}).encode())
    assert h.obj["ok"] is True


def test_apply_requires_shots(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/apply", "",
                      json.dumps({"project": "P", "shots": []}).encode())
    assert h.code == 400


def test_shot_add_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "add_shot", lambda p, t: "U13")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/shot", "",
                      json.dumps({"project": "P", "action": "add", "template": "U01"}).encode())
    assert h.obj["id"] == "U13"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_api.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 写实现**

```python
# h3_spider/canvas_api.py
# -*- coding: utf-8 -*-
"""画布 API：JSON 与只读资源。"""
import json
import mimetypes
import os
from urllib.parse import parse_qs, urlparse

from .canvas_apply import apply_draft, add_shot, delete_shot
from .canvas_paths import CanvasError, list_projects, remember_project, resolve_project
from .canvas_state import load_state
from .canvas_store import save_canvas


def handle(handler, method, path, query="", body=b""):
    u = urlparse(path)
    q = parse_qs(query)
    try:
        if method == "GET" and u.path == "/api/projects":
            handler._json({"projects": list_projects()})
            return True
        if method == "GET" and u.path == "/api/canvas":
            project = resolve_project(q.get("project", [""])[0])
            handler._json(load_state(project))
            return True
        if method == "GET" and u.path == "/api/canvas/asset":
            _asset(handler, q)
            return True
        if method == "POST" and u.path == "/api/canvas/save":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            remember_project(project)
            handler._json({"ok": True, "canvas": save_canvas(project, payload)})
            return True
        if method == "POST" and u.path == "/api/canvas/apply":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            drafts = payload.get("shots") or []
            if not drafts:
                raise CanvasError("没有要应用的镜头", 400)
            args = (project, payload.get("edges") or [], payload.get("anchors") or {})
            dry = bool(payload.get("dry_run"))
            if payload.get("per_shot") and len(drafts) > 1:
                results = []
                for d in drafts:
                    try:
                        r = apply_draft(project, [d], args[1], args[2], dry_run=dry)
                    except CanvasError as e:
                        r = {"ok": False, "error": str(e)}
                    results.append({"id": d.get("id"), **r})
                ok = all(x.get("ok") for x in results)
                handler._json({"ok": ok, "results": results}, 200 if ok else 422)
                return True
            result = apply_draft(project, drafts, args[1], args[2], dry_run=dry)
            handler._json(result, 200 if result.get("ok") else 422)
            return True
        if method == "POST" and u.path == "/api/canvas/shot":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            if payload.get("action") == "add":
                nid = add_shot(project, payload.get("template") or "U01")
                handler._json({"ok": True, "id": nid})
                return True
            if payload.get("action") == "delete":
                delete_shot(project, payload.get("id"))
                handler._json({"ok": True})
                return True
            raise CanvasError("action 只能是 add/delete", 400)
    except CanvasError as e:
        handler._json({"error": str(e)}, e.code)
        return True
    except Exception as e:
        handler._json({"error": "画布接口失败：%s" % e}, 500)
        return True
    return False


def _body(raw):
    if not raw:
        return {}
    if len(raw) > 1024 * 1024:
        raise CanvasError("请求体超过 1MB", 413)
    return json.loads(raw.decode("utf-8"))


def _asset(handler, q):
    from .canvas_state import _remembered_runs
    project = resolve_project(q.get("project", [""])[0])
    state = load_state(project)
    raw = q.get("path", [""])[0]
    target = os.path.abspath(raw)
    allowed = [os.path.abspath(state["project"]), os.path.abspath(state["project_root"])]
    allowed += [os.path.abspath(x) for x in _remembered_runs(project)]
    if not any(os.path.commonpath([target, a]) == a for a in allowed):
        raise CanvasError("资源路径越界", 403)
    if not os.path.isfile(target):
        raise CanvasError("资源不存在", 404)
    ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
    handler._send(200, open(target, "rb").read(), ctype)
```

- [ ] **Step 4: 接入 dashboard**

在 `dashboard.py` 的 `do_POST` 最前面加（只对画布路由读 body，别动 `/api/launch`）：

```python
        u = urlparse(self.path)
        if (u.path in ("/api/canvas/save", "/api/canvas/apply",
                       "/api/canvas/run", "/api/canvas/shot")
                or u.path.startswith("/api/canvas/jobs/")):
            from . import canvas_api
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if canvas_api.handle(self, "POST", self.path, "", body):
                return
```

在 `do_GET` 的最前面加（只拦 API）：

```python
        from . import canvas_api
        if u.path == "/api/projects" or u.path.startswith("/api/canvas"):
            if canvas_api.handle(self, "GET", self.path, u.query):
                return
```

在 `do_GET` 的静态路由里加 `/canvas`：

```python
        if u.path == "/canvas":
            p = os.path.join(HERE, "map3d.html")
            self._send(200, open(p, "rb").read(), "text/html; charset=utf-8")
            return
```

- [ ] **Step 5: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_api.py h3_spider/tests/test_canvas_store.py -q`
Expected: `10 passed`。

- [ ] **Step 6: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_api.py h3_spider/dashboard.py h3_spider/tests/test_canvas_api.py
git commit -m "feat(canvas): expose project, state, save and apply APIs on 8777"
```

---

## Milestone 2：星图画布模式

### Task 8: map3d 模式开关与 `window.__fanxingMap`

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.html`
- Create: `D:\AIWorkflow\tools\h3_spider\storyboard_model.js`
- Test: `D:\AIWorkflow\tools\h3_spider\tests_js\storyboard_model.test.mjs`

- [ ] **Step 1: 先写纯函数与失败测试**

```javascript
// h3_spider/storyboard_model.js
export function snap(v, step = 0.5) {
  return Math.round(v / step) * step;
}

export function ringLayout(ids, center = [0, 0, 0], radius = 5.5) {
  return ids.map((id, i) => {
    const a = (i / Math.max(1, ids.length)) * Math.PI * 2;
    return { id, pos: [center[0] + Math.cos(a) * radius, center[1], center[2] + Math.sin(a) * radius] };
  });
}

export function buildStoryboardModel(payload) {
  const shots = payload.shots || [];
  const anchors = payload.anchors || [];
  const nodes = [];
  shots.forEach((s, i) => {
    nodes.push({
      id: s.id, kind: 'node', label: s.id,
      sub: payload.status?.[s.id] || '未检',
      color: payload.status?.[s.id] === 'PASS' ? 0x3ddc97
        : payload.status?.[s.id] === 'BLOCK' ? 0xff6b6b : 0x7f909f,
      status: payload.status?.[s.id] === 'PASS' ? 'pass'
        : payload.status?.[s.id] === 'BLOCK' ? 'block' : 'muted',
      baseSize: 0.56, sizeMul: 1.0, shot: s, ringIndex: i % 3,
      rows: [['时长', s.duration], ['mode', s.mode], ['QC', payload.status?.[s.id] || '未检']]
    });
  });
  anchors.forEach((a) => {
    nodes.push({
      id: a.id, kind: 'anchor', label: a.label, sub: a.kind,
      color: a.kind === 'cast' ? 0xf5b955 : 0x38bdf8, status: 'ok',
      baseSize: 0.34, sizeMul: 0.8, anchor: a, ringIndex: 2,
      rows: [['类型', a.kind]]
    });
  });
  return {
    overall: 'CANVAS', passCount: 0, shotCount: shots.length,
    systems: [{
      id: 'storyboard', kind: 'system', label: '镜头', sub: `${shots.length} 镜`,
      color: 0x5eead4, center: [0, -3.5, 22], rings: [4.3, 6.2, 8.1],
      tilt: [0.30, -0.22], nodes
    }],
    shots: nodes.filter((n) => n.kind === 'node'),
    anchors: nodes.filter((n) => n.kind === 'anchor'),
    edges: payload.edges || [], canvas: payload.canvas || {},
    legs: [], slots: [], evidence: [], failures: 0, batchDir: payload.batch_dir || ''
  };
}
```

```javascript
// h3_spider/tests_js/storyboard_model.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { snap, ringLayout, buildStoryboardModel } from '../storyboard_model.js';

test('snap rounds to half unit', () => {
  assert.equal(snap(1.24), 1.0);
  assert.equal(snap(1.26), 1.5);
});

test('ringLayout places all ids', () => {
  const out = ringLayout(['U01', 'U02', 'U03'], [0, 0, 0], 5);
  assert.equal(out.length, 3);
  assert.ok(Math.abs(Math.hypot(out[0].pos[0], out[0].pos[2]) - 5) < 1e-6);
});

test('buildStoryboardModel marks PASS green', () => {
  const m = buildStoryboardModel({
    shots: [{ id: 'U01', duration: 8 }],
    status: { U01: 'PASS' }, anchors: [], edges: [], canvas: {}
  });
  assert.equal(m.systems[0].nodes[0].color, 0x3ddc97);
  assert.equal(m.systems[0].nodes[0].sub, 'PASS');
});
```

Run:
```bash
cd /d/AIWorkflow/tools
node --test h3_spider/tests_js/storyboard_model.test.mjs
```
Expected: PASS（文件先写好，测试即绿；后续 Task 9 再补失败用例）。

- [ ] **Step 2: 改 map3d.js 数据源**

在文件顶部加入：

```javascript
const QS = new URLSearchParams(location.search);
const MODE = QS.get('mode') === 'canvas' ? 'canvas' : 'qc';
const PROJECT = QS.get('project') || '';

async function loadCanvas() {
  const res = await fetch('/api/canvas?project=' + encodeURIComponent(PROJECT), { cache: 'no-store' });
  if (!res.ok) throw new Error('画布接口 HTTP ' + res.status);
  return res.json();
}
```

把 `boot()` 里的三路加载改为：

```javascript
    let data, workflow = null, kb = null;
    if (MODE === 'canvas') {
      const payload = await loadCanvas();
      const { buildStoryboardModel } = await import('/storyboard_model.js');
      data = { canvas: payload };
      model = buildStoryboardModel(payload);
    } else {
      [data, workflow, kb] = await Promise.all([loadData(), loadWorkflow(), loadKb()]);
      model = buildModel(data, workflow, kb);
    }
    // storyboard_model 不能 import three，这里补一次坐标类型转换
    model.systems.forEach((sys) => { sys.center = new THREE.Vector3(...sys.center); });
```

在 `makeSystem` 之后隐藏其他星系：

```javascript
    model.systems.forEach((sys) => {
      makeSystem(sys);
      if (MODE === 'canvas' && sys.id !== 'storyboard') sys.group.visible = false;
    });
    if (MODE === 'canvas' && coreGroup) coreGroup.visible = false;
```

在 `boot()` 末尾把现有 `window.__map` 扩展为：

```javascript
    window.__fanxingMap = {
      THREE, scene, camera, renderer, controls, raycaster, graph, labels,
      nodeMeshes, systemCores, select, focusNode, focusSystem, flyTo,
      makeNode, addLabel, mode: MODE, project: PROJECT,
      setOtherSystemsVisible(v) {
        model.systems.forEach((s) => { if (s.id !== 'storyboard' && s.group) s.group.visible = v; });
        if (coreGroup) coreGroup.visible = v;
      },
      frameHooks: [],
      onFrame(fn) { this.frameHooks.push(fn); }
    };
```

在 `animate()` 里 `composer.render()` 前加：

```javascript
  if (window.__fanxingMap && window.__fanxingMap.frameHooks) {
    window.__fanxingMap.frameHooks.forEach((fn) => fn(now));
  }
```

- [ ] **Step 3: 画布模式接管选中**

把 `select(target)` 改成：

```javascript
function select(target) {
  selected = target;
  clearSelectionVisuals();
  if (window.__fanxingMap && window.__fanxingMap.onSelect) {
    window.__fanxingMap.onSelect(target);
  }
  if (window.__fanxingMap && window.__fanxingMap.mode === 'canvas') return;
  if (!target) { showInspector(null); return; }
  if (target.kind === 'node') {
    target.mesh.material.uniforms.uSelected.value = 1;
    if (target.labelObj) target.labelObj.element.classList.add('sel');
  } else if (target.kind === 'system') {
    if (target.halo) target.halo.material.opacity = 1;
    if (target.labelObj) target.labelObj.element.classList.add('sel');
  } else if (target.kind === 'batch') {
    if (coreSprite) coreSprite.material.opacity = 1;
    if (coreLabel) coreLabel.element.classList.add('sel');
  }
  showInspector(target);
}
```

在 `boot()` 的 `showInspector(null);` 后加：

```javascript
    if (MODE === 'canvas') inspector.style.display = 'none';
    if (MODE === 'canvas') {
      camera.position.set(0, 26, 12);
      controls.target.set(0, -3.5, 22);
      controls.update();
    }
```

- [ ] **Step 4: map3d.html 加切换按钮**

在 `.hint` 之前加：

```html
    <a class="btn" id="mode-link" href="/map3d">质检视图</a>
```

在脚本里：

```html
<script>
  (function () {
    var a = document.getElementById('mode-link');
    if (!a) return;
    var qs = new URLSearchParams(location.search);
    if (qs.get('mode') === 'canvas') {
      a.textContent = '质检视图';
      a.href = '/map3d';
    } else {
      a.textContent = '分镜画布';
      a.href = '/canvas?project=' + encodeURIComponent(qs.get('project') || '');
    }
  })();
</script>
```

- [ ] **Step 4: 手工验证**

Run:
```bash
cd /d/AIWorkflow/tools
py -3.12 -m h3_spider.dashboard --port 8777
```
打开 `http://127.0.0.1:8777/canvas?project=C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3`。
Expected: 只显示镜头星系与锚点，12 个镜头节点；控制台 `window.__fanxingMap.mode === 'canvas'`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/map3d.js h3_spider/map3d.html h3_spider/storyboard_model.js h3_spider/tests_js/storyboard_model.test.mjs
git commit -m "feat(canvas): add storyboard mode to the 3d star map"
```

---

### Task 9: 吸附、框选、边类型与撤销栈

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\storyboard_model.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\tests_js\storyboard_model.test.mjs`

- [ ] **Step 1: 追加失败测试**

```javascript
import { screenRectSelect, edgeTypeForKey, CommandStack } from '../storyboard_model.js';

test('screenRectSelect picks points inside rect', () => {
  const pts = [
    { id: 'a', x: 10, y: 10 },
    { id: 'b', x: 200, y: 200 },
  ];
  assert.deepEqual(screenRectSelect(pts, { x: 0, y: 0, w: 50, h: 50 }), ['a']);
});

test('edgeTypeForKey maps 1/2/3', () => {
  assert.equal(edgeTypeForKey('1'), 'order');
  assert.equal(edgeTypeForKey('2'), 'chain');
  assert.equal(edgeTypeForKey('3'), 'ref');
  assert.equal(edgeTypeForKey('x'), null);
});

test('command stack undo redo', () => {
  const s = new CommandStack(3);
  let v = 0;
  s.push({ redo: () => { v = 1; }, undo: () => { v = 0; } });
  s.push({ redo: () => { v = 2; }, undo: () => { v = 1; } });
  s.undo(); assert.equal(v, 1);
  s.undo(); assert.equal(v, 0);
  s.redo(); assert.equal(v, 1);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `node --test h3_spider/tests_js/storyboard_model.test.mjs`
Expected: FAIL，`screenRectSelect is not a function`。

- [ ] **Step 3: 实现**

```javascript
// 追加到 storyboard_model.js
export function screenRectSelect(points, rect) {
  const x2 = rect.x + rect.w;
  const y2 = rect.y + rect.h;
  return points
    .filter((p) => p.x >= rect.x && p.x <= x2 && p.y >= rect.y && p.y <= y2)
    .map((p) => p.id);
}

export function edgeTypeForKey(key) {
  return { '1': 'order', '2': 'chain', '3': 'ref' }[key] || null;
}

export class CommandStack {
  constructor(limit = 50) {
    this.limit = limit;
    this.done = [];
    this.undone = [];
  }
  push(cmd) {
    cmd.redo();
    this.done.push(cmd);
    if (this.done.length > this.limit) this.done.shift();
    this.undone = [];
  }
  undo() {
    const cmd = this.done.pop();
    if (!cmd) return false;
    cmd.undo();
    this.undone.push(cmd);
    return true;
  }
  redo() {
    const cmd = this.undone.pop();
    if (!cmd) return false;
    cmd.redo();
    this.done.push(cmd);
    return true;
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `node --test h3_spider/tests_js/storyboard_model.test.mjs`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/storyboard_model.js h3_spider/tests_js/storyboard_model.test.mjs
git commit -m "feat(canvas): add snapping, marquee and undo primitives"
```

---

### Task 10: 在星图里渲染镜头、锚点与三种边

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\storyboard.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.js`（只加一行 import）
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.html`（加脚本与卡片容器）

- [ ] **Step 1: 写渲染模块**

```javascript
// h3_spider/storyboard.js
import { ringLayout, snap } from './storyboard_model.js';

const state = {
  map: null, data: null, nodes: new Map(), edgeObjs: [], group: null,
  selected: new Set(), currentType: 'order', dragging: null, connecting: null
};

const EDGE_STYLE = {
  order: { color: 0xbfe9ff, opacity: 0.75, dashed: false },
  chain: { color: 0xf5b955, opacity: 0.9, dashed: true },
  ref: { color: 0x5eead4, opacity: 0.45, dashed: true, gap: 0.18 }
};

export async function initStoryboard(project) {
  const map = window.__fanxingMap;
  state.map = map;
  const res = await fetch('/api/canvas?project=' + encodeURIComponent(project));
  state.data = await res.json();
  buildNodes();
  buildEdges();
  map.onFrame(update);
  map.onSelect = (t) => {
    if (t && t.kind === 'node' && t.shot) renderCard(t.id);
    if (!t) document.getElementById('sb-card').classList.remove('on');
  };
}

function buildNodes() {
  const map = state.map;
  const { THREE } = map;
  state.group = new THREE.Group();
  map.scene.add(state.group);
  const missing = state.data.shots
    .filter((s) => !state.data.canvas.nodes?.[s.id])
    .map((s) => s.id);
  const layout = ringLayout(missing, [0, -3.5, 22], 5.5);
  layout.forEach((x) => {
    state.data.canvas.nodes = state.data.canvas.nodes || {};
    state.data.canvas.nodes[x.id] = { pos: x.pos };
  });
  state.map.nodeMeshes.forEach((mesh) => {
    const n = mesh.userData.pick;
    if (!n) return;
    const saved = state.data.canvas.nodes?.[n.id];
    if (saved) {
      n.pos.fromArray(saved.pos);
      mesh.position.copy(n.pos);
      if (n.labelObj) n.labelObj.position.set(n.pos.x, n.pos.y + 0.62, n.pos.z);
    }
    state.nodes.set(n.id, n);
  });
}

function edgePoints(a, b) {
  const { THREE } = state.map;
  const mid = a.clone().add(b).multiplyScalar(0.5);
  mid.y += 1.2;
  return new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(32);
}

function buildEdges() {
  const { THREE } = state.map;
  state.edgeObjs.forEach((e) => state.group.remove(e.line));
  state.edgeObjs = [];
  (state.data.edges || []).forEach((e) => {
    const a = state.nodes.get(e.from);
    const b = state.nodes.get(e.to);
    if (!a || !b) return;
    const style = EDGE_STYLE[e.type] || EDGE_STYLE.order;
    const geo = new THREE.BufferGeometry().setFromPoints(edgePoints(a.pos, b.pos));
    const mat = style.dashed
      ? new THREE.LineDashedMaterial({ color: style.color, transparent: true,
          opacity: style.opacity, dashSize: 0.45, gapSize: style.gap || 0.3, depthWrite: false })
      : new THREE.LineBasicMaterial({ color: style.color, transparent: true,
          opacity: style.opacity, depthWrite: false });
    const line = new THREE.Line(geo, mat);
    if (style.dashed) line.computeLineDistances();
    line.userData.edge = e;
    state.group.add(line);
    state.edgeObjs.push({ line, edge: e });
  });
}

function update() {
  state.edgeObjs.forEach(({ line, edge }) => {
    const a = state.nodes.get(edge.from);
    const b = state.nodes.get(edge.to);
    if (!a || !b) return;
    line.geometry.setFromPoints(edgePoints(a.pos, b.pos));
    if (line.material.isLineDashedMaterial) line.computeLineDistances();
  });
}

export function selectShot(id) {
  const n = state.nodes.get(id);
  if (!n) return;
  state.map.select(n);
  renderCard(id);
}

function renderCard(id) {
  const host = document.getElementById('sb-card');
  const shot = state.data.shots.find((s) => s.id === id) || {};
  host.classList.add('on');
  host.innerHTML =
    '<div class="sb-head"><b>' + id + '</b><button id="sb-close">×</button></div>' +
    '<div class="sb-body">' +
    '<div class="sb-row"><span>mode</span><code>' + (shot.mode || '') + '</code></div>' +
    '<div class="sb-row"><span>时长</span><code>' + (shot.duration || '') + 's</code></div>' +
    '<div class="sb-row"><span>QC</span><code>' + (state.data.status?.[id] || '未检') + '</code></div>' +
    '<pre class="sb-prompt">' + ((shot.content && shot.content.shot_line) || '') + '</pre>' +
    '</div>';
  document.getElementById('sb-close').onclick = () => {
    host.classList.remove('on');
    state.map.select(null);
  };
}
```

- [ ] **Step 2: map3d.html 加容器和脚本**

在 `</main>` 前加：

```html
<div id="sb-card"></div>
```

在 `<script type="module" src="/map3d.js"></script>` 后加：

```html
<script type="module">
  if (new URLSearchParams(location.search).get('mode') === 'canvas') {
    import('/storyboard.js').then((m) => {
      const project = new URLSearchParams(location.search).get('project') || '';
      const wait = setInterval(() => {
        if (window.__fanxingMap) {
          clearInterval(wait);
          m.initStoryboard(project);
        }
      }, 100);
    });
  }
</script>
```

样式追加到既有 `<style>`：

```css
#sb-card{position:fixed;right:18px;top:64px;bottom:18px;width:420px;display:none;
  background:rgba(6,12,20,.92);border:1px solid #21384a;border-radius:12px;
  padding:14px;color:#d7e6f0;overflow:auto;z-index:20}
#sb-card.on{display:block}
.sb-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.sb-row{display:flex;justify-content:space-between;padding:3px 0;color:#8fa6b6}
.sb-row code{color:#d7e6f0}
.sb-prompt{white-space:pre-wrap;font-size:12px;line-height:1.5;color:#a9c1d1}
```

- [ ] **Step 3: 手工验证**

打开 `/canvas?project=...`：12 个镜头节点、角色/场景锚点、片序实线；点击节点右侧出现卡片；拖动节点后边跟随（Task 11 才持久化）。

- [ ] **Step 4: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/storyboard.js h3_spider/map3d.html
git commit -m "feat(canvas): render shot nodes, anchors and three edge styles"
```

---

### Task 11: 拖动、多选、连线创建与撤销

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\storyboard.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.html`（撤选框元素）

- [ ] **Step 1: 加交互代码**

在 `storyboard.js` 末尾追加：

```javascript
import { screenRectSelect, edgeTypeForKey, CommandStack } from './storyboard_model.js';

const undo = new CommandStack(50);

export function bindEditing() {
  const map = state.map;
  const canvas = map.renderer.domElement;
  const { THREE } = map;
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const hitPoint = new THREE.Vector3();

  function ray(e) {
    const r = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - r.left) / r.width) * 2 - 1,
      -((e.clientY - r.top) / r.height) * 2 + 1);
    map.raycaster.setFromCamera(ndc, map.camera);
    return map.raycaster.ray;
  }

  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const portHit = map.raycaster.intersectObjects(map.nodeMeshes, true)
      .find((h) => h.object.userData.port);
    if (portHit) return;  // 出线口交给连线逻辑
    const hit = map.raycaster.intersectObjects(map.nodeMeshes, false)[0];
    const node = hit && hit.object.userData.pick;
    if (!node || node.kind === 'system') return;
    map.controls.enabled = false;
    state.dragging = { id: node.id, start: node.pos.clone() };
  }, true);

  canvas.addEventListener('pointermove', (e) => {
    if (!state.dragging) return;
    const r = ray(e);
    const p = new THREE.Vector3();
    plane.constant = -state.dragging.start.y;
    if (!r.intersectPlane(plane, p)) return;
    const n = state.nodes.get(state.dragging.id);
    n.pos.set(snap(p.x), state.dragging.start.y, snap(p.z));
    n.mesh.position.copy(n.pos);
    if (n.labelObj) n.labelObj.position.set(n.pos.x, n.pos.y + 0.62, n.pos.z);
  }, true);

  canvas.addEventListener('pointerup', (e) => {
    if (!state.dragging) return;
    const n = state.nodes.get(state.dragging.id);
    const before = state.dragging.start.clone();
    const after = n.pos.clone();
    if (before.distanceTo(after) > 0.01) {
      undo.push({
        redo: () => { n.pos.copy(after); n.mesh.position.copy(after); },
        undo: () => { n.pos.copy(before); n.mesh.position.copy(before); }
      });
      state.data.canvas.nodes = state.data.canvas.nodes || {};
      state.data.canvas.nodes[n.id] = { pos: after.toArray() };
      saveLayout();
    }
    state.dragging = null;
    map.controls.enabled = true;
  }, true);

  window.addEventListener('keydown', (e) => {
    const t = edgeTypeForKey(e.key);
    if (t) state.currentType = t;
    if (e.key === 'z' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      e.shiftKey ? undo.redo() : undo.undo();
    }
  });
}

async function saveLayout() {
  const body = {
    project: state.data.project,
    nodes: state.data.canvas.nodes || {},
    edges: state.data.edges || [],
    annotations: state.data.canvas.annotations || {}
  };
  await fetch('/api/canvas/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}
```

在 `initStoryboard()` 里 `map.onFrame(update);` 后加 `bindEditing();`。

- [ ] **Step 2: 连线创建**

在 `bindEditing()` 里追加出线口与拖线逻辑：

```javascript
  const portGeo = new THREE.SphereGeometry(0.12, 12, 12);
  const portMat = new THREE.MeshBasicMaterial({ color: 0x5eead4 });
  state.nodes.forEach((n) => {
    const port = new THREE.Mesh(portGeo, portMat);
    port.position.set(0.45, 0, 0);
    port.userData.port = n.id;
    n.mesh.add(port);
  });

  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const hit = map.raycaster.intersectObjects(map.nodeMeshes, true)[0];
    const obj = hit && hit.object;
    if (obj && obj.userData.port) {
      state.connecting = { from: obj.userData.port };
      map.controls.enabled = false;
    }
  }, true);

  canvas.addEventListener('pointerup', (e) => {
    if (!state.connecting) return;
    const hit = map.raycaster.intersectObjects(map.nodeMeshes, false)[0];
    const node = hit && hit.object.userData.pick;
    if (node && node.id !== state.connecting.from) {
      const edge = {
        id: 'e' + Date.now(), from: state.connecting.from,
        to: node.id, type: state.currentType
      };
      if (edge.type === 'chain') {
        const bind = prompt('末帧文件名（例如 U01_end.png）');
        if (!bind) { state.connecting = null; return; }
        edge.binding = bind;
      }
      state.data.edges.push(edge);
      buildEdges();
      saveLayout();
      undo.push({ redo: () => {}, undo: () => {
        state.data.edges = state.data.edges.filter((x) => x.id !== edge.id);
        buildEdges(); saveLayout();
      }});
    }
    state.connecting = null;
    map.controls.enabled = true;
  }, true);

  // Shift 拖空白：屏幕空间框选
  const marquee = document.createElement('div');
  marquee.style.cssText = 'position:fixed;border:1px solid #5eead4;' +
    'background:rgba(94,234,212,.08);pointer-events:none;display:none;z-index:30';
  document.body.appendChild(marquee);
  let box = null;

  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || !e.shiftKey) return;
    if (map.raycaster.intersectObjects(map.nodeMeshes, false).length) return;
    box = { x: e.clientX, y: e.clientY };
    marquee.style.display = 'block';
    marquee.style.left = e.clientX + 'px';
    marquee.style.top = e.clientY + 'px';
    marquee.style.width = '0px';
    marquee.style.height = '0px';
  }, true);

  canvas.addEventListener('pointermove', (e) => {
    if (!box) return;
    const x = Math.min(box.x, e.clientX);
    const y = Math.min(box.y, e.clientY);
    marquee.style.left = x + 'px';
    marquee.style.top = y + 'px';
    marquee.style.width = Math.abs(e.clientX - box.x) + 'px';
    marquee.style.height = Math.abs(e.clientY - box.y) + 'px';
  }, true);

  canvas.addEventListener('pointerup', (e) => {
    if (!box) return;
    const rect = { x: Math.min(box.x, e.clientX), y: Math.min(box.y, e.clientY),
      w: Math.abs(e.clientX - box.x), h: Math.abs(e.clientY - box.y) };
    marquee.style.display = 'none';
    box = null;
    const cr = canvas.getBoundingClientRect();
    const pts = [...state.nodes.values()].map((n) => {
      const p = n.pos.clone().project(map.camera);
      return { id: n.id,
        x: cr.left + (p.x + 1) / 2 * cr.width,
        y: cr.top + (1 - p.y) / 2 * cr.height };
    });
    state.selected = new Set(screenRectSelect(pts, rect));
    map.nodeMeshes.forEach((m) => {
      const n = m.userData.pick;
      m.material.uniforms.uSelected.value = state.selected.has(n && n.id) ? 1 : 0;
    });
  }, true);

  // 双击删边；右键循环改线型
  function edgeAt(e) {
    const r = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - r.left) / r.width) * 2 - 1,
      -((e.clientY - r.top) / r.height) * 2 + 1);
    map.raycaster.setFromCamera(ndc, map.camera);
    map.raycaster.params.Line.threshold = 0.35;
    const hit = map.raycaster.intersectObjects(state.edgeObjs.map((o) => o.line), false)[0];
    return hit ? hit.object.userData.edge : null;
  }

  canvas.addEventListener('dblclick', (e) => {
    const edge = edgeAt(e);
    if (!edge || !confirm('删除这条线？')) return;
    state.data.edges = state.data.edges.filter((x) => x.id !== edge.id);
    buildEdges();
    saveLayout();
  });

  canvas.addEventListener('contextmenu', (e) => {
    const edge = edgeAt(e);
    if (!edge) return;
    e.preventDefault();
    const seq = ['order', 'chain', 'ref'];
    const next = seq[(seq.indexOf(edge.type) + 1) % seq.length];
    edge.type = next;
    if (next === 'chain') {
      const bind = prompt('末帧文件名（例如 U01_end.png）');
      if (!bind) { edge.type = 'order'; return; }
      edge.binding = bind;
    }
    buildEdges();
    saveLayout();
  });
```

- [ ] **Step 3: 手工验证**

1. 拖动 U01，刷新后位置保持；
2. `Ctrl+Z` 回到原位；
3. 从 U01 出线口拖到 U02，按 `1/2/3` 生成不同线型；
4. 画三条边后 JSON 里 `edges` 增加。

- [ ] **Step 4: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/storyboard.js h3_spider/map3d.html
git commit -m "feat(canvas): drag, undo and edge creation in the star map"
```

---

### Task 12: 镜头卡只读页签、批注与布局保存

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\storyboard.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.html`

- [ ] **Step 1: 扩展卡片**

把 `renderCard()` 替换为五页签版本（内容/提示词/资产/版本/QC），资产缩略图用：

```javascript
function assetUrl(path) {
  return '/api/canvas/asset?project=' + encodeURIComponent(state.data.project) +
    '&path=' + encodeURIComponent(path);
}
```

资产页签（点缩略图设首帧，Shift+点设末帧）：

```javascript
const assetsHtml = '<div class="sb-assets">' + (state.data.assets || []).slice(0, 120).map((a) =>
  '<img data-asset="' + a.path + '" src="' + assetUrl(a.path) + '" title="' +
  a.name + '（点=首帧，Shift+点=末帧）">').join('') + '</div>';
```

提示词页签显示 `state.data.prompts` 的生成稿：

```javascript
const promptText = (state.data.prompts || {})[id] || '（尚未建稿）';
const promptHtml = '<pre class="sb-prompt">' + promptText + '</pre>';
```

在 `renderCard()` 末尾绑定：

```javascript
host.querySelectorAll('[data-asset]').forEach((img) => {
  img.onclick = (e) => {
    const key = e.shiftKey ? 'last_image' : 'image';
    const el = host.querySelector('[data-k="' + key + '"]');
    if (!el) return;
    el.value = img.dataset.asset;
    el.dispatchEvent(new Event('change'));
  };
});
```

批注状态红点（3D 节点旁）：

```javascript
function ensureIssueDots() {
  if (state.issueDots) return;
  const { THREE } = state.map;
  const geo = new THREE.SphereGeometry(0.09, 8, 8);
  const mat = new THREE.MeshBasicMaterial({ color: 0xff6b6b });
  state.issueDots = new Map();
  state.nodes.forEach((n) => {
    const dot = new THREE.Mesh(geo, mat);
    dot.position.set(0.28, 0.22, 0);
    dot.visible = false;
    n.mesh.add(dot);
    state.issueDots.set(n.id, dot);
  });
}

function syncIssueDots() {
  ensureIssueDots();
  const ann = state.data.canvas.annotations || {};
  state.issueDots.forEach((dot, id) => {
    dot.visible = (ann[id] || {}).status === 'issue';
  });
}
```

在 `initStoryboard()` 里调用一次 `syncIssueDots()`；每次标问题后也调用。

批注输入：

```javascript
  host.insertAdjacentHTML('beforeend',
    '<div class="sb-anno"><textarea id="sb-note" placeholder="批注（100 字）" maxlength="100"></textarea>' +
    '<div class="sb-flags"><button data-flag="ok">标 OK</button><button data-flag="issue">标问题</button></div></div>');
  const note = state.data.canvas.annotations?.[id] || {};
  const ta = document.getElementById('sb-note');
  ta.value = note.text || '';
  ta.onchange = () => {
    state.data.canvas.annotations = state.data.canvas.annotations || {};
    state.data.canvas.annotations[id] = { status: note.status || 'ok', text: ta.value };
    saveLayout();
  };
  host.querySelectorAll('[data-flag]').forEach((b) => {
    b.onclick = () => {
      state.data.canvas.annotations = state.data.canvas.annotations || {};
      state.data.canvas.annotations[id] = { status: b.dataset.flag, text: ta.value };
      saveLayout();
      syncIssueDots();
    };
  });
```

- [ ] **Step 2: 手工验证**

刷新后批注还在；标问题后节点旁出现红点，改回 OK 红点消失。

- [ ] **Step 3: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/storyboard.js h3_spider/map3d.html
git commit -m "feat(canvas): shot card tabs, annotations and layout autosave"
```

---

## Milestone 3：编辑与生成

### Task 13: 编辑草稿、校验与应用

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\storyboard.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.html`

- [ ] **Step 1: 卡片加编辑态**

在 `state` 初始化里加 `currentShot: null, drafts: {}, dirty: new Set()`，并在 `renderCard(id)` 第一行写 `state.currentShot = id;`。

内容页改成这些字段：

```javascript
const dlg = (shot.dialogue || [])[0];
const contentHtml =
  '<label class="sb-field"><span>时长</span>' +
  '<input data-k="duration" type="number" step="0.001" value="' + (shot.duration || '') + '"></label>' +
  '<label class="sb-field"><span>mode</span><select data-k="mode">' +
  ['i2va', 'fl2va', 'ref2va', 'multiref'].map((m) =>
    '<option' + (shot.mode === m ? ' selected' : '') + '>' + m + '</option>').join('') +
  '</select></label>' +
  '<label class="sb-field"><span>首帧</span><input data-k="image" value="' + (shot.image || '') + '"></label>' +
  '<label class="sb-field"><span>末帧</span><input data-k="last_image" value="' + (shot.last_image || '') + '"></label>' +
  '<label class="sb-field"><span>动作</span><textarea data-k="content.shot_line">' +
  ((shot.content || {}).shot_line || '') + '</textarea></label>' +
  (dlg
    ? '<label class="sb-field"><span>台词</span><textarea data-k="dialogue.0.text">' +
      (dlg.text || '') + '</textarea></label>'
    : '<div class="muted small">本镜无台词</div>');
```

提交时收集（支持嵌套路径）：

```javascript
function setPath(obj, path, val) {
  const keys = path.split('.');
  let cur = obj;
  for (let i = 0; i < keys.length - 1; i += 1) {
    const k = keys[i];
    const next = keys[i + 1];
    if (cur[k] == null) cur[k] = /^\d+$/.test(next) ? [] : {};
    cur = cur[k];
  }
  cur[keys[keys.length - 1]] = val;
}

function collectDraft() {
  const out = { id: state.currentShot };
  document.querySelectorAll('#sb-card [data-k]').forEach((el) => {
    setPath(out, el.dataset.k, el.type === 'number' ? Number(el.value) : el.value);
  });
  return out;
}
```

输入变化就记草稿：

```javascript
host.querySelectorAll('[data-k]').forEach((el) => {
  el.onchange = () => {
    state.drafts[id] = collectDraft();
    state.dirty.add(id);
  };
});
```

应用分两步：先 `dry_run` 拿 diff 让用户确认，再真写。

```javascript
async function postApply(drafts, dryRun, perShot = false) {
  const shots = Array.isArray(drafts) ? drafts : [drafts];
  const res = await fetch('/api/canvas/apply', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project: state.data.project, shots, dry_run: dryRun, per_shot: perShot,
      edges: state.data.edges,
      anchors: Object.fromEntries((state.data.anchors || []).map((a) => [a.label, a.label]))
    })
  });
  return { ok: res.ok, out: await res.json() };
}

async function applyDraft() {
  const draft = state.drafts[state.currentShot] || collectDraft();
  const dry = await postApply(draft, true);
  if (!dry.ok || !dry.out.ok) {
    return alert((dry.out.error || '校验失败') + '\n' +
      JSON.stringify(dry.out.build || dry.out.gate || {}, null, 1));
  }
  const diff = (dry.out.diff || []).slice(0, 40).join('\n');
  if (!confirm('将要修改 shots.yaml：\n\n' + diff)) return;
  const res = await postApply(draft, false);
  if (!res.ok || !res.out.ok) {
    return alert((res.out.error || '应用失败') + '\n' +
      JSON.stringify(res.out.build || res.out.gate || {}, null, 1));
  }
  state.dirty.delete(state.currentShot);
  await refreshState();
}
```

`canvas_api.py` 的 apply 分支把 `dry_run` 透传：

```python
            result = apply_draft(project, drafts, payload.get("edges") or [],
                                 payload.get("anchors") or {},
                                 dry_run=bool(payload.get("dry_run")))
```

卡片底部加按钮并绑定：

```html
<div class="sb-actions"><button id="sb-apply">应用到项目</button></div>
```

```javascript
async function refreshState() {
  const res = await fetch('/api/canvas?project=' + encodeURIComponent(state.data.project));
  state.data = await res.json();
  renderCard(state.currentShot);
}

document.getElementById('sb-apply').onclick = applyDraft;
```

- [ ] **Step 2: 应用后刷新质检状态**

`applyDraft()` 成功后调用 `refreshState()`；节点颜色按新 `status` 更新（遍历 `state.nodes` 改 `n.color` 并重设材质 uniform）。

- [ ] **Step 3: 手工验证**

改 U02 时长为 `6.0` → 服务返回 422 并提示“不在 17 帧档位”；改 `5.875` → 写回成功，`shots.yaml` 注释保留。

- [ ] **Step 4: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/storyboard.js h3_spider/map3d.html
git commit -m "feat(canvas): edit shots and apply with validation"
```

---

### Task 14: 单任务 JobManager

**Files:**
- Create: `D:\AIWorkflow\tools\h3_spider\canvas_jobs.py`
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_jobs.py`

- [ ] **Step 1: 写失败测试**

```python
# h3_spider/tests/test_canvas_jobs.py
# -*- coding: utf-8 -*-
import threading
import time

import pytest

from h3_spider.canvas_jobs import JobManager


def test_start_and_done(tmp_path):
    def runner(job, emit):
        emit("hello")
        return {"status": "done", "run_dir": str(tmp_path)}
    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    for _ in range(50):
        got = m.get(job["job_id"])
        if got["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert got["status"] == "done"
    assert "hello" in got["log"][-1]


def test_one_active_job(tmp_path):
    gate = threading.Event()

    def runner(job, emit):
        gate.wait(2)
        return {"status": "done"}
    m = JobManager(str(tmp_path), runner=runner)
    m.start("P", ["U01"], "run")
    with pytest.raises(Exception) as e:
        m.start("P", ["U02"], "run")
    assert getattr(e.value, "code", 0) == 409
    gate.set()


def test_cancel(tmp_path):
    def runner(job, emit):
        for _ in range(20):
            time.sleep(0.05)
        return {"status": "done"}
    m = JobManager(str(tmp_path), runner=runner)
    job = m.start("P", ["U01"], "run")
    m.cancel(job["job_id"])
    assert m.get(job["job_id"])["status"] == "cancelled"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_jobs.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 写实现**

```python
# h3_spider/canvas_jobs.py
# -*- coding: utf-8 -*-
"""单 GPU 任务队列：状态机、日志环、取消、SSE 订阅。"""
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .canvas_paths import CanvasError
from .canvas_store import read_json, write_json_atomic


class JobManager:
    def __init__(self, runs_root, runner=None):
        self.runs_root = Path(runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.runner = runner or default_runner
        self.jobs = {}
        self.subs = {}
        self.lock = threading.Lock()
        self.active = None
        self.lock_path = self.runs_root / "canvas_jobs" / "active.lock"
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    def _load_existing(self):
        for p in (self.runs_root / "canvas_jobs").glob("*.json"):
            doc = read_json(str(p), {})
            if doc.get("job_id"):
                doc["status"] = "interrupted"
                self.jobs[doc["job_id"]] = doc

    def _check_stale_lock(self):
        doc = read_json(str(self.lock_path), {}) or {}
        if not doc:
            return
        age = time.time() - float(doc.get("started_at") or 0)
        pid = doc.get("pid")
        if age < 12 * 3600 and pid and _pid_alive(pid):
            raise CanvasError("已有任务在跑：%s" % doc.get("job_id"), 409)
        self.lock_path.unlink(missing_ok=True)

    def start(self, project, shots, stage="run"):
        with self.lock:
            self._check_stale_lock()
            if self.active:
                cur = self.jobs.get(self.active) or {}
                if cur.get("status") in ("queued", "gating", "running"):
                    raise CanvasError("已有任务在跑：%s" % self.active, 409)
            job_id = "job_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
            job = {"job_id": job_id, "project": project, "shots": list(shots),
                   "stage": stage, "status": "queued", "started_at": time.time(),
                   "log": [], "result": None}
            self.jobs[job_id] = job
            self.subs[job_id] = []
            self.active = job_id
            write_json_atomic({"job_id": job_id, "pid": os.getpid(),
                               "started_at": time.time()}, str(self.lock_path))
            self._persist(job)
            threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
            return job

    def _run(self, job_id):
        job = self.jobs[job_id]
        job["status"] = "gating"
        self._persist(job)

        def emit(line):
            job["log"].append(str(line))
            job["log"] = job["log"][-400:]
            for q in self.subs.get(job_id, []):
                q.put(str(line))

        try:
            out = self.runner(job, emit) or {}
            job["result"] = out
            if job.get("status") != "cancelled":
                job["status"] = out.get("status") or "done"
        except Exception as e:
            job["status"] = "failed"
            job["result"] = {"error": str(e)}
            emit("ERROR " + str(e))
        finally:
            job["ended_at"] = time.time()
            self._persist(job)
            with self.lock:
                if self.active == job_id:
                    self.active = None
                doc = read_json(str(self.lock_path), {}) or {}
                if doc.get("job_id") == job_id:
                    self.lock_path.unlink(missing_ok=True)

    def get(self, job_id):
        return self.jobs.get(job_id) or {}

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            raise CanvasError("任务不存在", 404)
        job["status"] = "cancelled"
        pid = (job.get("result") or {}).get("pid")
        if pid:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                           capture_output=True)
        self._persist(job)
        return job

    def subscribe(self, job_id):
        q = queue.Queue()
        self.subs.setdefault(job_id, []).append(q)
        return q

    def _persist(self, job):
        d = self.runs_root / "canvas_jobs"
        d.mkdir(parents=True, exist_ok=True)
        write_json_atomic(job, str(d / (job["job_id"] + ".json")))


def default_runner(job, emit):
    import sys
    from fanxing.workflow import run_workflow
    from pathlib import Path
    from .canvas_state import remember_run
    out = Path(r"C:/Temp/fanxing_runs") / ("canvas_" + job["job_id"])
    wf = run_workflow(job["project"], str(out), agent_id="local",
                      shots=job["shots"], through="gate")
    emit("gate " + (wf.get("overall") or "?"))
    if job.get("status") == "cancelled":
        return {"status": "cancelled"}
    if wf.get("overall") != "PASS":
        return {"status": "gate_blocked", "workflow": str(out / "workflow.json")}
    if job["stage"] != "run":
        return {"status": "done", "workflow": str(out / "workflow.json")}
    batch = wf.get("batch_dir")
    cmd = [sys.executable, "h3_run_project.py", "--project", job["project"],
           "--out", str(out / "run"), "--spider-batch", batch, "--only"] + job["shots"]
    p = subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent.parent),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
    job["result"] = {"pid": p.pid}
    for line in p.stdout:
        emit(line.rstrip())
    code = p.wait()
    remember_run(job["project"], str(out / "run"))
    return {"status": "done" if code == 0 else "failed",
            "run_dir": str(out / "run"), "exit": code}


def _pid_alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid)],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return str(pid) in out
    except Exception:
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_jobs.py -q`
Expected: `3 passed`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_jobs.py h3_spider/tests/test_canvas_jobs.py
git commit -m "feat(canvas): single-job manager with cancel and log ring"
```

---

### Task 15: run / jobs / SSE / cancel 接口与 8189 健康检查

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\canvas_api.py`
- Modify: `D:\AIWorkflow\tools\h3_spider\dashboard.py`（把 JobManager 挂到 Handler）
- Test: `D:\AIWorkflow\tools\h3_spider\tests\test_canvas_api.py`

- [ ] **Step 1: 追加测试**

```python
def test_run_requires_confirm(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/run", "",
                      json.dumps({"project": "P", "shots": ["U01"]}).encode())
    assert h.code == 400


def test_run_returns_job(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    class M:
        def start(self, project, shots, stage): return {"job_id": "j1", "status": "queued"}
    monkeypatch.setattr(canvas_api, "_manager", lambda: M())
    monkeypatch.setattr(canvas_api, "health_ok", lambda: True)
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/run", "",
                      json.dumps({"project": "P", "shots": ["U01"], "confirm": True}).encode())
    assert h.obj["job_id"] == "j1"
```

- [ ] **Step 2: 实现**

在 `canvas_api.py` 加入（注意 `import queue`）：

```python
import queue
import urllib.request
_JOB_MANAGER = None


def _manager():
    global _JOB_MANAGER
    if _JOB_MANAGER is None:
        from .canvas_jobs import JobManager
        _JOB_MANAGER = JobManager(r"C:/Temp/fanxing_runs")
    return _JOB_MANAGER


def health_ok():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8189/system_stats", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False
```

在 `handle()` 的 POST 分支加：

```python
        if method == "POST" and u.path == "/api/canvas/run":
            payload = _body(body)
            project = resolve_project(payload.get("project"))
            shots = payload.get("shots") or []
            if not payload.get("confirm"):
                raise CanvasError("缺 confirm，拒绝提交 GPU", 400)
            if not shots:
                raise CanvasError("没有选择镜头", 400)
            stage = payload.get("stage") or "run"
            if stage == "run" and not health_ok():
                raise CanvasError("8189 不可用，先启动 ComfyUI", 503)
            job = _manager().start(project, shots, stage)
            handler._json(job)
            return True
        if method == "GET" and u.path.startswith("/api/canvas/jobs/") and u.path.endswith("/events"):
            job_id = u.path.split("/")[4]
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Cache-Control", "no-cache")
            handler.end_headers()
            q = _manager().subscribe(job_id)
            while True:
                try:
                    line = q.get(timeout=15)
                    handler.wfile.write(("data: " + json.dumps({"line": line}, ensure_ascii=False) + "\n\n").encode("utf-8"))
                except queue.Empty:
                    handler.wfile.write(b": ping\n\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                handler.wfile.flush()
            return True
        if method == "GET" and u.path.startswith("/api/canvas/jobs/"):
            job_id = u.path.rsplit("/", 1)[-1]
            handler._json(_manager().get(job_id))
            return True
        if method == "POST" and u.path.startswith("/api/canvas/jobs/") and u.path.endswith("/cancel"):
            job_id = u.path.split("/")[4]
            handler._json(_manager().cancel(job_id))
            return True
```

- [ ] **Step 3: 跑测试**

Run: `py -3.12 -m pytest h3_spider/tests/test_canvas_api.py -q`
Expected: `6 passed`。

- [ ] **Step 4: 手工验证任务**

```bash
curl -X POST http://127.0.0.1:8777/api/canvas/run -H "Content-Type: application/json" -d "{\"project\":\"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3\",\"shots\":[\"U01\"],\"stage\":\"gate\",\"confirm\":true}"
```
Expected: 返回 `job_id`；`curl /api/canvas/jobs/<id>` 最终 `status=done` 或 `gate_blocked`。

- [ ] **Step 5: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_api.py h3_spider/dashboard.py h3_spider/tests/test_canvas_api.py
git commit -m "feat(canvas): run jobs, SSE progress, cancel and 8189 health"
```

---

### Task 16: takes、poster 与 A/B 对比

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\canvas_state.py`
- Modify: `D:\AIWorkflow\tools\h3_spider\canvas_api.py`
- Modify: `D:\AIWorkflow\tools\h3_spider\storyboard.js`

- [ ] **Step 1: poster 缓存**

在 `canvas_state.py` 加入：

```python
FFMPEG = r"D:/AIWorkflow/tools/ffmpeg.exe"


def ensure_poster(project, video_path):
    import hashlib
    import subprocess
    proj = Path(project)
    h = hashlib.sha1(str(video_path).encode("utf-8")).hexdigest()[:12]
    out = proj / ".fanxing" / "posters" / (h + ".jpg")
    if out.is_file():
        return str(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "0.2", "-i", str(video_path),
                    "-frames:v", "1", str(out)], capture_output=True)
    return str(out) if out.is_file() else ""
```

`scan_takes` 每条记录加：

```python
            item["poster"] = ensure_poster(project, str(p))
```

- [ ] **Step 2: 版本页与 A/B**

在 `renderCard()` 的“版本”页：

```javascript
const takes = state.data.takes[id] || [];
const rows = takes.map((t, i) =>
  '<div class="sb-take"><video src="' + assetUrl(t.path) + '" muted preload="metadata"></video>' +
  '<span>' + (i === 0 ? '最新' : '#' + i) + '</span>' +
  '<button data-ab="' + i + '">A/B</button>' +
  '<button data-pick="' + i + '">选用</button></div>').join('');
```

A/B 点击后打开两个 `<video>` 并同步：

```javascript
host.querySelectorAll('[data-pick]').forEach((b) => {
  b.onclick = () => {
    state.data.canvas.nodes = state.data.canvas.nodes || {};
    state.data.canvas.nodes[id] = state.data.canvas.nodes[id] || {};
    state.data.canvas.nodes[id].selected_take = takes[Number(b.dataset.pick)].id;
    saveLayout();
  };
});
```

```javascript
function openAB(shotId, idx) {
  const takes = state.data.takes[shotId] || [];
  const other = takes[idx === 0 ? 1 : 0];
  if (!other) return alert('只有一个 take');
  const a = document.createElement('video'); a.src = assetUrl(takes[idx].path); a.controls = true;
  const b = document.createElement('video'); b.src = assetUrl(other.path); b.controls = true;
  const win = window.open('', '_blank', 'width=960,height=600');
  win.document.body.style.background = '#03060c';
  win.document.body.append(a, b);
  a.onplay = () => b.play();
  b.onplay = () => a.play();
}
```

- [ ] **Step 3: 手工验证**

U01 的版本页出现 1 条 take 与 poster；点 A/B 两个窗口同步播放；标选用写入 `canvas.json`。

- [ ] **Step 4: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_state.py h3_spider/canvas_api.py h3_spider/storyboard.js
git commit -m "feat(canvas): takes, posters and A/B comparison"
```

---

### Task 17: 整批出片、项目切换与顶部工具栏

**Files:**
- Modify: `D:\AIWorkflow\tools\h3_spider\canvas_api.py`
- Modify: `D:\AIWorkflow\tools\h3_spider\storyboard.js`
- Modify: `D:\AIWorkflow\tools\h3_spider\map3d.html`

- [ ] **Step 1: 整批确认与预计时长**

顶部工具栏：

```html
<div id="sb-toolbar">
  <select id="sb-project"></select>
  <button id="sb-add">+ 镜头</button>
  <button id="sb-del">删镜头</button>
  <button id="sb-apply-all">批量应用</button>
  <button id="sb-gate">跑整批闸</button>
  <button id="sb-run">整批出片</button>
  <span id="sb-est" class="muted"></span>
</div>
```

逻辑：

```javascript
async function loadProjects() {
  const r = await fetch('/api/projects');
  const { projects } = await r.json();
  const sel = document.getElementById('sb-project');
  sel.innerHTML = projects.map((p) =>
    '<option value="' + p.path + '">' + p.name + ' (' + p.shot_count + ')</option>').join('');
  sel.value = state.data.project;
  sel.onchange = () => {
    if (state.dirty.size && !confirm('有未应用的编辑，切项目会丢失。继续？')) {
      sel.value = state.data.project;
      return;
    }
    location.href = '/canvas?project=' + encodeURIComponent(sel.value);
  };
}

function batchRun(stage) {
  const shots = state.data.shots.map((s) => s.id);
  const est = Math.round(shots.length * 7);
  if (!confirm(`共 ${shots.length} 镜，预计约 ${est} 分钟。闸门未过会拒绝。继续？`)) return;
  document.getElementById('sb-est').textContent = '任务已提交';
  fetch('/api/canvas/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: state.data.project, shots, stage, confirm: true })
  }).then((r) => r.json()).then((j) => {
    if (j.error) return alert(j.error);
    const es = new EventSource('/api/canvas/jobs/' + j.job_id + '/events');
    es.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      document.getElementById('sb-est').textContent = data.line.slice(0, 80);
    };
  });
}
```

- [ ] **Step 2: 绑定按钮**

```javascript
document.getElementById('sb-add').onclick = async () => {
  const template = state.currentShot || (state.data.shots[0] || {}).id;
  if (!template) return alert('没有可复制的模板镜头');
  const r = await fetch('/api/canvas/shot', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: state.data.project, action: 'add', template })
  });
  const out = await r.json();
  if (out.error) return alert(out.error);
  location.href = '/canvas?project=' + encodeURIComponent(state.data.project);
};

document.getElementById('sb-del').onclick = async () => {
  if (!state.currentShot) return alert('先选一个镜头');
  if (!confirm('删除 ' + state.currentShot + '？会直接写 shots.yaml')) return;
  const r = await fetch('/api/canvas/shot', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: state.data.project, action: 'delete', id: state.currentShot })
  });
  const out = await r.json();
  if (out.error) return alert(out.error);
  location.href = '/canvas?project=' + encodeURIComponent(state.data.project);
};

document.getElementById('sb-gate').onclick = () => batchRun('gate');
document.getElementById('sb-run').onclick = () => batchRun('run');
document.getElementById('sb-apply-all').onclick = async () => {
  const ids = [...state.dirty];
  if (!ids.length) return alert('没有改动的镜头');
  const drafts = ids.map((id) => state.drafts[id]);
  const dry = await postApply(drafts, true, true);
  if (!dry.ok || !dry.out.ok) {
    return alert((dry.out.error || '校验失败') + '\n' +
      JSON.stringify(dry.out.results || dry.out.build || {}, null, 1));
  }
  const diff = dry.out.results
    ? dry.out.results.map((r) => '--- ' + r.id + '\n' + (r.diff || []).join('\n')).join('\n').slice(0, 4000)
    : (dry.out.diff || []).slice(0, 60).join('\n');
  if (!confirm('将修改 ' + ids.length + ' 镜：\n\n' + diff)) return;
  const res = await postApply(drafts, false, true);
  if (!res.ok || !res.out.ok) {
    return alert((res.out.error || '应用失败') + '\n' +
      JSON.stringify(res.out.results || res.out.gate || {}, null, 1));
  }
  state.dirty.clear();
  state.drafts = {};
  await refreshState();
};
loadProjects();
```

- [ ] **Step 3: 手工验证**

切换项目后布局互不串；整批确认框显示 12 镜 / 约 84 分钟；取消后状态 `cancelled`。

- [ ] **Step 4: 提交**

```bash
cd /d/AIWorkflow/tools
git add h3_spider/canvas_api.py h3_spider/storyboard.js h3_spider/map3d.html
git commit -m "feat(canvas): batch run, project switch and toolbar"
```

---

### Task 18: 端到端验收与回归

**Files:**
- Modify: `D:\AIWorkflow\tools\docs\superpowers\specs\2026-11-02-fanxing-canvas-design.md`（仅在验收结果需要记录时追加一节“验收记录”）
- No new code files.

- [ ] **Step 1: 跑 Python 全量测试**

```bash
cd /d/AIWorkflow/tools
py -3.12 -m pytest h3_spider/tests -q
```
Expected: 现有 112 条 + 新增 canvas 测试全部 passed；若出现既有 4 条 gate 漂移，先重跑 `py -3.12 -m h3_spider batch` 再测。

- [ ] **Step 2: 跑 Node 测试**

```bash
node --test h3_spider/tests_js/storyboard_model.test.mjs
```
Expected: 全部 PASS。

- [ ] **Step 3: 按规格第 11 节执行 10 条手工清单**

逐条记录结果（通过/失败+截图路径）；重点：
- 拖动 U01 刷新保持；
- 改 U02 时长越档被拦；
- apply 后注释保留；
- 单镜 gate→run；
- 8189 关闭时 run 被拒；
- 取消后进程树消失；
- A/B 同步；
- 切项目布局不串；
- 越界 asset 403。

- [ ] **Step 4: 记录目视待调项**

在规格末尾追加：

```markdown
## 15. 验收记录（2026-11-02 起）

- 目视待调：相机俯视角度、标签密度、虚线/点线在暗背景的可见度、拖拽吸附手感。
- 每次调整只改 `storyboard.js` 的相机预设/材质参数，不改后端契约。
```

- [ ] **Step 5: 最终提交**

```bash
cd /d/AIWorkflow/tools
git add docs/superpowers/specs/2026-11-02-fanxing-canvas-design.md
git commit -m "docs(canvas): record e2e checklist and visual tuning notes"
```

---

## 目视调整清单（用户已确认后续再调）

这些项不阻塞实现，M1/M4 打开画布后按实际观感调：

1. 俯视相机角度（当前 `top` 预设偏 10°）。
2. 节点大小与标签距离（59 镜时的密度）。
3. 三种线在深空背景上的亮度/透明度。
4. 拖拽吸附步长（当前 0.5）。
5. 卡片面板宽度与页签顺序。

调整只动 `storyboard.js` 与 `map3d.html` 的样式/常量，不改 `shots.yaml` 与 API。
