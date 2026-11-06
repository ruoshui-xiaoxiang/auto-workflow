# -*- coding: utf-8 -*-
"""画布持久化：ruamel YAML（保注释）+ 原子 JSON。"""
import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from ruamel.yaml import YAML


# 同进程串行化 canvas.json 的 read-modify-write（ThreadingHTTPServer 多线程）。
# 只在这两个函数内持锁，不覆盖函数外的其它文件 IO。
_CANVAS_LOCK = threading.Lock()


def _yaml():
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _discard_tmp(tmp):
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass


def _atomic_write(path, write_fn):
    """同目录唯一临时文件 → 原子替换；失败时清掉半成品，不留残渣。"""
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            write_fn(f)
        os.replace(tmp, path)
    finally:
        # 成功时 tmp 已被 rename，不会残留；失败时清掉半成品再抛
        _discard_tmp(tmp)


def yaml_load(path):
    with open(path, "r", encoding="utf-8") as f:
        return _yaml().load(f)


def yaml_dump_text(doc):
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def yaml_dump_atomic(doc, path):
    _atomic_write(path, lambda f: f.write(yaml_dump_text(doc)))


def read_json(path, default=None):
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(obj, path):
    _atomic_write(path, lambda f: json.dump(obj, f, ensure_ascii=False, indent=1))


def canvas_path(project):
    return Path(project) / ".fanxing" / "canvas.json"


def default_canvas(project):
    return {
        "version": 1,
        "project": str(project),
        "updated_at": _stamp(),
        "view": {"camera_preset": "top", "bookmarks": {}},
        "nodes": {},
        "edges": [],
        "annotations": {},
        "takes": {},
    }


def _backup_target(p):
    """首个损坏存 .json.bak；之后的损坏另存 .json.bak.<时间戳>，不覆盖旧备份。"""
    plain = p.with_suffix(".json.bak")
    if not plain.exists():
        return plain
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = p.with_suffix(".json.bak." + stamp)
    n = 1
    while target.exists():
        target = p.with_suffix(".json.bak.%s-%d" % (stamp, n))
        n += 1
    return target


def load_canvas(project):
    p = canvas_path(project)
    if not p.is_file():
        return default_canvas(project)
    try:
        # 读盘错误（权限/IO）不是损坏：OSError 不在下面的捕获里，直接上抛
        raw = p.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        # 非法 UTF-8 字节、JSON 语法错误、根类型异常都算损坏
        doc = None
    if not isinstance(doc, dict):
        # 仅解码/JSON 解析失败或根不是对象，才视为损坏
        os.replace(str(p), str(_backup_target(p)))
        return default_canvas(project)
    return doc


def save_canvas(project, patch):
    with _CANVAS_LOCK:
        doc = load_canvas(project)
        for key in ("view", "nodes", "edges", "annotations"):
            if key in patch and isinstance(patch[key], (dict, list)):
                doc[key] = patch[key]
        doc["version"] = 1
        doc["project"] = str(project)
        doc["updated_at"] = _stamp()
        write_json_atomic(doc, str(canvas_path(project)))
        return doc


def merge_takes(project, takes):
    with _CANVAS_LOCK:
        doc = load_canvas(project)
        current = doc.get("takes") or {}
        for sid, items in (takes or {}).items():
            current[sid] = items
        doc["takes"] = current
        doc["version"] = 1
        doc["updated_at"] = _stamp()
        write_json_atomic(doc, str(canvas_path(project)))
        return doc

