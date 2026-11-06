# -*- coding: utf-8 -*-
"""把项目文件组装成画布需要的状态。

一次 ``load_state`` 输出画布 API 需要的全部数据：镜头、锚点、三线型边、
上一批目录与状态、takes、提示词预览、素材清单与素材根。``load_state`` 本身
只读项目文件，唯一的例外是 ``load_canvas`` 遇到损坏的 ``canvas.json`` 时会
把它移到 ``.json.bak``（隔离后返回默认画布）；除此之外的写入只有
``remember_run`` 记录 job 运行目录（``.fanxing/runs.json``）。

镜头字典直接来自 ``shots.yaml``，``load_state`` 不改写它们；后续任务若调用
``canvas_edges.apply_edges``（会就地改 ``image``/``images``）需要自行复制。
"""
import os
import re
from pathlib import Path

from .canvas_edges import auto_edges
from .canvas_paths import project_root
from .canvas_store import load_canvas, read_json, write_json_atomic, yaml_load

SHOT_RE = re.compile(r"(U\d+|SH\d+)", re.I)
VIDEO_EXT = {".mp4", ".mov", ".webm"}
FFMPEG = r"D:/AIWorkflow/tools/ffmpeg.exe"


def ensure_poster(project, video_path):
    """缓存 take 的首帧 jpg；失败返回空串，不阻塞版本列表。"""
    import hashlib
    import subprocess
    proj = Path(project)
    key = hashlib.sha1(str(video_path).encode("utf-8")).hexdigest()[:12]
    out = proj / ".fanxing" / "posters" / (key + ".jpg")
    if out.is_file():
        return out.as_posix()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "0.2", "-i", str(video_path),
                        "-frames:v", "1", str(out)], capture_output=True, timeout=30)
    except Exception:
        return ""
    return out.as_posix() if out.is_file() else ""
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
RUNS_MARKER = ".fanxing/runs.json"
RUNS_ROOT_ENV = "FANXING_RUNS_ROOT"
DEFAULT_RUNS_ROOT = r"C:/Temp/fanxing_runs"
MAX_RUN_DIRS = 50
# 外部快照/工作目录里可能混进版本库与缓存，整棵跳过，省掉无谓遍历
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache"}


def load_state(project):
    proj = Path(project)
    root = Path(project_root(project))
    shots_doc = yaml_load(str(proj / "shots.yaml")) or {}
    if not isinstance(shots_doc, dict):
        shots_doc = {}
    shots = _clean_shots(shots_doc.get("shots"))
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
        "takes": scan_takes(project, shots),
        "prompts": _prompts(proj, shots),
        "assets": list_assets(project, shots_doc),
        "asset_roots": asset_roots(project, shots_doc),
    }


def _clean_shots(raw):
    """只保留有可用 ``id`` 的镜头字典；坏条目跳过，不让整块看板崩掉。"""
    out = []
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid.strip():
            continue
        out.append(s)
    return out


def _prompts(proj, shots):
    out = {}
    for s in shots:
        p = Path(proj) / "out" / (s["id"] + ".txt")
        if p.is_file():
            try:
                out[s["id"]] = p.read_text(encoding="utf-8")[:8000]
            except (OSError, UnicodeDecodeError):
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
    """上一批的 ``batch_verdict.json`` 目录（绝对路径），读不到返回 ``""``。

    先看 ``.fanxing/last_batch.json`` 的 ``batch_dir``（相对路径按项目根解析），
    标记缺失/失效时退到最近一次 ``<runs>/*/workflow.json`` 里 project 匹配的
    ``batch_dir``。
    """
    root = Path(project_root(project))
    found = _marker_batch_dir(Path(project), root) or _marker_batch_dir(root, root)
    return found or _fallback_batch_dir(project)


def _marker_batch_dir(base, root):
    doc = _read_json_safe(Path(base) / ".fanxing" / "last_batch.json", {})
    if not isinstance(doc, dict):
        return ""
    raw = doc.get("batch_dir")
    if not isinstance(raw, str) or not raw.strip():
        return ""
    p = Path(raw.strip())
    if not p.is_absolute():
        p = Path(root) / p
    p = os.path.abspath(str(p))
    if os.path.isfile(os.path.join(p, "batch_verdict.json")):
        return p
    return ""


def _fallback_batch_dir(project):
    """按 workflow.json 的 project 匹配最近的 run 目录。"""
    runs_root = os.environ.get(RUNS_ROOT_ENV) or DEFAULT_RUNS_ROOT
    entries = []
    try:
        with os.scandir(runs_root) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        entries.append((entry.stat().st_mtime, entry.path))
                except OSError:
                    continue
    except OSError:
        return ""
    entries.sort(key=lambda x: x[0], reverse=True)
    want = _normcase_abs(project)
    for _, run_dir in entries[:MAX_RUN_DIRS]:
        wf = _read_json_safe(Path(run_dir) / "workflow.json", {})
        if not isinstance(wf, dict) or _normcase_abs(wf.get("project")) != want:
            continue
        bd = wf.get("batch_dir")
        if not isinstance(bd, str) or not bd.strip():
            continue
        bd = bd.strip()
        if not os.path.isabs(bd):
            bd = os.path.join(run_dir, bd)
        bd = os.path.abspath(bd)
        if os.path.isfile(os.path.join(bd, "batch_verdict.json")):
            return bd
    return ""


def _normcase_abs(path):
    """比较路径用（Windows 下大小写不敏感）；非法输入给空串，永远不匹配。"""
    try:
        raw = os.fspath(path)
    except TypeError:
        return ""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    return os.path.normcase(os.path.abspath(raw.strip()))


def _status(batch_dir):
    """批次状态；batch_verdict.json 结构坏掉时给空表，不抛异常。"""
    if not batch_dir:
        return {}
    doc = _read_json_safe(Path(batch_dir) / "batch_verdict.json", {})
    if not isinstance(doc, dict):
        return {}
    shots = doc.get("shots")
    if not isinstance(shots, dict):
        return {}
    out = {}
    for sid, rec in shots.items():
        if not isinstance(rec, dict):
            out[str(sid)] = "?"
            continue
        v = rec.get("verdict.json")
        if not isinstance(v, dict):
            v = rec
        overall = v.get("overall")
        out[str(sid)] = overall if isinstance(overall, str) and overall else "?"
    return out


def scan_takes(project, shots=None):
    """按镜头归并 outputs/assets/work 与记住过的 job 目录里的视频。

    文件名里的 shot id 不区分大小写，归到 ``shots.yaml`` 里写的那个 id 上
    （免得 ``u01_x.mp4`` 单独长成一个小写孤儿分组）。
    """
    root = Path(project_root(project))
    canonical = _canonical_ids(project, shots)
    bases = [root / "outputs", root / "assets", root / "work"]
    bases += [Path(x) for x in _remembered_runs(project)]
    out, seen = {}, set()
    for base in _scan_roots(bases):
        for p in _walk_files(base):
            if p.suffix.lower() not in VIDEO_EXT:
                continue
            m = SHOT_RE.search(p.name)
            if not m:
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key in seen:
                continue
            try:
                st = p.stat()
            except OSError:
                # 生成中的目录随时可能删掉半成品，跳过即可
                continue
            seen.add(key)
            raw = m.group(1)
            sid = canonical.get(raw.lower(), raw.upper())
            out.setdefault(sid, []).append({
                "id": p.stem + ":" + str(int(st.st_mtime)),
                "path": p.as_posix(),
                "poster": ensure_poster(project, str(p)),
                "mtime": int(st.st_mtime),
                "bytes": st.st_size,
            })
    for sid in out:
        out[sid].sort(key=lambda x: x["mtime"], reverse=True)
    return out


def _canonical_ids(project, shots=None):
    """``{小写 id: shots.yaml 里的原样 id}``。"""
    if shots is None:
        doc = _load_optional(Path(project) / "shots.yaml")
        shots = _clean_shots(doc.get("shots") if isinstance(doc, dict) else None)
    return {s["id"].strip().lower(): s["id"].strip() for s in shots}


def _remembered_runs(project):
    doc = _read_json_safe(Path(project) / RUNS_MARKER, {}) or {}
    return [x for x in doc.get("runs") or [] if isinstance(x, str) and x]


def remember_run(project, run_dir):
    """记住 job 运行目录（最新的排最前，最多 20 条）。"""
    p = Path(project) / RUNS_MARKER
    doc = _read_json_safe(p, {}) or {}
    target = str(Path(run_dir).resolve())
    runs = [x for x in doc.get("runs") or [] if x != target]
    runs.insert(0, target)
    doc["runs"] = runs[:20]
    write_json_atomic(doc, str(p))


def _asset_bases(project, shots_doc=None):
    """素材根，按 spec §4.1 的优先级：crops → assets_dir → 项目 assets → …"""
    proj = Path(project)
    root = Path(project_root(project))
    if shots_doc is None:
        shots_doc = _load_optional(proj / "shots.yaml")
    defaults = shots_doc.get("defaults") if isinstance(shots_doc, dict) else None
    bases = [proj / "assets" / "crops"]
    raw = (defaults or {}).get("assets_dir") if isinstance(defaults, dict) else None
    if isinstance(raw, str) and raw.strip():
        extra = Path(raw.strip())
        # 相对路径按项目目录（不是项目根）解析，和 shots.yaml 的读法一致
        bases.append(extra if extra.is_absolute() else proj / extra)
    bases += [proj / "assets", root / "assets",
              root / "合并_第二十三星区" / "04_外部依赖快照"]
    return bases


def asset_roots(project, shots_doc=None):
    """素材根的绝对路径（去重、保持优先级），供 API 做路径白名单。"""
    out, seen = [], set()
    for base in _asset_bases(project, shots_doc):
        p = os.path.abspath(str(base))
        key = os.path.normcase(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def list_assets(project, shots_doc=None):
    """素材候选：crops → assets_dir → 项目 assets → 根 assets → 外部快照，上限 500。"""
    seen, out = set(), []
    for base in _scan_roots(_asset_bases(project, shots_doc)):
        for p in _walk_files(base):
            if p.suffix.lower() not in IMAGE_EXT:
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key in seen:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            seen.add(key)
            out.append({"path": p.as_posix(), "name": p.name,
                        "mtime": int(st.st_mtime), "bytes": st.st_size})
            if len(out) >= 500:
                return out
    return out


def _scan_roots(bases):
    """按优先级去重的扫描根：已被前一个根覆盖的目录不再重复遍历。

    去重用 normcase 后的绝对路径（Windows 下大小写不敏感），但遍历仍用原始
    大小写的路径，避免展示路径被压成小写。
    """
    out, seen = [], set()
    for b in bases:
        key = os.path.normcase(os.path.abspath(b))
        if any(key == s or key.startswith(s + os.sep) for s in seen):
            continue
        if not os.path.isdir(key):
            continue
        seen.add(key)
        out.append(Path(os.path.abspath(b)))
    return out


def _walk_files(base):
    """遍历文件，顺手跳过 .git/缓存目录与隐藏目录。"""
    for cur, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            yield Path(cur) / name


def _read_json_safe(path, default=None):
    try:
        return read_json(str(path), default)
    except (OSError, ValueError):
        return default
