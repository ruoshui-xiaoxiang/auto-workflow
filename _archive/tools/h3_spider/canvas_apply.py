# -*- coding: utf-8 -*-
"""写回校验、备份、原子写 ``shots.yaml``，再自动建稿并过闸。

写盘顺序（任何一步失败都不留半成品）：

1. ``validate_draft``：时长档位 + 三线型规则；只读，而且校验的是**合并后**
   的副本——草稿把 ``mode`` 从 i2va 改成 ref2va 之后，ref 边才该判为合法，
   反之把 ref2va 改成 i2va 时 ref 边必须当场拒掉；
2. 合并草稿、应用边：校验通过后才改 ruamel 文档里的**真实镜头对象**，
   再按片序重排 ``doc["shots"]``，因此注释与 chain/ref 的写回都能落盘；
3. 预演：把候选项目复制到临时目录，用真 ``h3_prompt_builder.py`` 跑一遍；
   任何一镜不过就抛 422，真文件一个字节都不动；
4. 备份 → ``yaml_dump_atomic`` 写盘：同一把 ``_APPLY_LOCK`` 里做完，读盘后被
   别人改过就 409，不覆盖别人的写；然后跑真 builder；
5. ``run_gate`` 时再跑 spider 批跑 + ``check_batch_gate``，把批次目录记进
   ``.fanxing/last_batch.json``；走到这一步 shots.yaml 已经写了，批跑/闸再抛
   异常也只返回 ``ok=False`` + ``gate.error``，不往上抛。

时长档位与 ``h3_shots.py`` 同源：帧数落在 ``17n+5``（@24fps，124–362 帧），
另加 4.5s 的官方短镜特例；写成秒即 ``(17n+5)/24``，
所以 5.875 / 6.583 合法、6.0 不在档位。
"""
import copy
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from .canvas_edges import apply_edges
from .canvas_paths import CanvasError
from .canvas_store import (write_json_atomic, yaml_dump_atomic, yaml_dump_text,
                           yaml_load)

TOOLS = str(Path(__file__).resolve().parent.parent)
INPUT_DIR = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"
RUNS_ROOT_ENV = "FANXING_RUNS_ROOT"
DEFAULT_RUNS_ROOT = r"C:/Temp/fanxing_runs"
BUILD_TIMEOUT = 300
SHORT_SECONDS = 4.5
GRID_MIN, GRID_MAX = 124, 362
# 17 帧档位：帧数 = 17n+5（@24fps，124–362 帧），另有 4.5s 短镜特例
VALID = {SHORT_SECONDS} | {round((17 * n + 5) / 24, 3) for n in range(7, 21)}
FIELDS = ("mode", "canvas", "duration", "image", "last_image", "images",
          "cast", "content", "dialogue", "soundscape", "music", "scene", "summary")
# 同进程串行化 load→validate→merge→backup→write：两个 apply 的写不能交错
_APPLY_LOCK = threading.Lock()


# ---------------------------------------------------------------- 读文档
def _load_doc(project):
    """读 shots.yaml；结构不对就抛 CanvasError，不让下游 KeyError。"""
    path = Path(project) / "shots.yaml"
    if not path.is_file():
        raise CanvasError("缺 shots.yaml：%s" % path, 404)
    try:
        doc = yaml_load(str(path))
    except OSError as e:
        raise CanvasError("shots.yaml 读不了：%s" % e, 422)
    if not isinstance(doc, dict):
        raise CanvasError("shots.yaml 根节点不是映射：%s" % path, 422)
    seq = doc.get("shots")
    if not isinstance(seq, list) or not seq:
        raise CanvasError("shots.yaml 的 shots 不是非空列表：%s" % path, 422)
    return doc


def _sid(shot):
    sid = shot.get("id") if isinstance(shot, dict) else None
    return sid.strip() if isinstance(sid, str) and sid.strip() else ""


def _bad_ids(seq):
    """缺 id / 不是映射的镜头下标（从 1 数，方便人看）。"""
    return [i + 1 for i, s in enumerate(seq) if not _sid(s)]


def _on_grid(seconds):
    """时长是否落在 17n+5 帧网格上（4.5s 是官方短镜特例）。

    先比 ``VALID`` 里写好的秒值，再退回按帧数判，容得下浮点噪声
    （5.166666 与 5.167 都算同一档）。
    """
    if any(abs(seconds - v) < 1e-3 for v in VALID):
        return True
    frames = int(round(seconds * 24))
    return GRID_MIN <= frames <= GRID_MAX and (frames - 5) % 17 == 0


def _report_failures(report):
    return [r for r in report if not (isinstance(r, dict) and r.get("ok"))]


def _failure_text(rows):
    parts = []
    for r in rows:
        if not isinstance(r, dict):
            parts.append(str(r))
            continue
        errs = [str(x) for x in (r.get("errors") or []) if str(x).strip()]
        parts.append("%s: %s" % (r.get("id") or "?", " / ".join(errs) or "未知失败"))
    return "；".join(parts)


# ---------------------------------------------------------------- 校验
def _validate_doc(doc, drafts, edges, anchors):
    """校验一份（已经合并过草稿的）文档，返回 ``[{"shot", "message"}]``。

    ``doc`` 必须是合并后的文档：草稿改了 ``mode``/``duration`` 之后才能按新值
    判。边规则跑 ``copy.deepcopy`` 的镜头副本——校验不能顺手改掉文档里的
    image/images。
    """
    seq = doc.get("shots") if isinstance(doc, dict) else None
    errors = []
    drafts = list(drafts or [])
    if not drafts:
        errors.append({"shot": "", "message": "没有要应用的镜头草稿"})
    if not isinstance(seq, list) or not seq:
        errors.append({"shot": "", "message": "shots 不是非空列表"})
        return errors
    bad = _bad_ids(seq)
    if bad:
        errors.append({"shot": "", "message": "shots.yaml 第 %s 条镜头缺 id"
                       % "、".join(str(i) for i in bad)})
    # 重复 id 必须先拦：by_id 会只剩最后一镜，合并草稿时静默丢内容
    seen = {}
    for s in seq:
        sid = _sid(s)
        if sid:
            seen[sid] = seen.get(sid, 0) + 1
    for sid, n in seen.items():
        if n > 1:
            errors.append({"shot": sid, "message": "重复镜头 id：%s" % sid})
    by_id = {_sid(s): s for s in seq if _sid(s)}
    for d in drafts:
        if not isinstance(d, dict):
            errors.append({"shot": "", "message": "草稿必须是对象"})
            continue
        sid = _sid(d)
        if not sid:
            errors.append({"shot": "", "message": "草稿缺 id"})
            continue
        shot = by_id.get(sid)
        if shot is None:
            errors.append({"shot": sid, "message": "镜头不存在：%s" % sid})
            continue
        # 合并后的镜头值就是最终要落盘的时长（草稿优先）
        raw = d.get("duration", shot.get("duration"))
        try:
            dur = float(raw)
        except (TypeError, ValueError):
            errors.append({"shot": sid, "message": "时长 %r 不是数字" % (raw,)})
            continue
        if not _on_grid(dur):
            errors.append({"shot": sid, "message": "时长 %.3f 不在 17 帧档位" % dur})
    if errors:
        return errors
    try:
        # 深拷贝：apply_edges 就地改 image/images，不能污染文档
        apply_edges(copy.deepcopy(list(seq)), list(edges or []), dict(anchors or {}))
    except CanvasError as e:
        errors.append({"shot": "", "message": str(e)})
    return errors


def validate_draft(project, drafts, edges, anchors):
    """只读校验，返回 ``[{"shot", "message"}]``（空列表 = 通过）。

    在深拷贝上合并草稿再校验：这样草稿把 i2va 改成 ref2va 后挂 ref 边是合法的，
    而真 ref2va 被改成 i2va 时同一根 ref 边会被拒。盘上的文件一个字节都不动。
    """
    doc = _load_doc(project)
    drafts = list(drafts or [])
    work = copy.deepcopy(doc)
    # 合并失败（镜头不存在/时长不是数字）留给 _validate_doc 报，这里不抛
    _merge(work, drafts, strict=False)
    return _validate_doc(work, drafts, edges, anchors)


# ---------------------------------------------------------------- 合并草稿
def _merge(doc, drafts, strict=True):
    """把草稿写进文档里的真实镜头对象；content/dialogue 做字段级合并。

    ``duration`` 强制归一成 float：草稿给 ``"5.875"`` 也不能落盘成字符串，
    转换失败抛 422。``strict=False`` 时跳过不存在的镜头，让校验层统一报错。
    """
    by_id = {_sid(s): s for s in doc["shots"] if _sid(s)}
    for d in drafts:
        sid = _sid(d)
        shot = by_id.get(sid)
        if shot is None:
            if strict:
                raise CanvasError("镜头不存在：%s" % sid, 422)
            continue
        for key in FIELDS:
            if key not in d:
                continue
            val = d[key]
            if key == "duration":
                try:
                    shot[key] = float(val)
                except (TypeError, ValueError):
                    if strict:
                        raise CanvasError("时长 %r 不是数字" % (val,), 422)
                    continue
            elif key == "content" and isinstance(val, dict):
                cur = shot.get("content")
                if not isinstance(cur, dict):
                    cur = {}
                    shot["content"] = cur
                cur.update(val)
            elif key == "dialogue" and isinstance(val, list):
                cur = shot.get("dialogue")
                if not isinstance(cur, list):
                    cur = []
                    shot["dialogue"] = cur
                for i, item in enumerate(val):
                    if i < len(cur) and isinstance(item, dict) \
                            and isinstance(cur[i], dict):
                        cur[i].update(item)
                    else:
                        cur.append(item)
            else:
                shot[key] = val
    return doc


# ---------------------------------------------------------------- 备份
def _backup_path(proj, kind="apply"):
    """备份路径：``shots.<stamp>.<uuid8>.<kind>.yaml``（同秒并发也不撞名）。"""
    backup_dir = Path(proj) / ".fanxing" / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return str(backup_dir / ("shots.%s.%s.%s.yaml"
                             % (stamp, uuid.uuid4().hex[:8], kind)))


def _backup_shots(proj, kind="apply"):
    """把 shots.yaml 复制到 ``.fanxing/backup``，返回备份路径。"""
    src = Path(proj) / "shots.yaml"
    target = _backup_path(proj, kind)
    shutil.copy2(str(src), str(target))
    return target


# ---------------------------------------------------------------- 建稿
def _build_fail(ids, message):
    return [{"id": ids[0] if ids else "?", "ok": False, "errors": [message]}]


def _read_report(report_path):
    """读 build_report.json；读不到/不是非空列表都返回 None。"""
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, list) and report else None


def _build(project, ids):
    """跑真 builder，读 ``out/build_report.json``；任何异常都返回失败报告。"""
    ids = [str(x) for x in (ids or [])]
    out_dir = Path(project) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "build_report.json"
    if report_path.exists():
        try:
            # 旧报告必须先删：否则 builder 挂了会读到上一次的假成功
            report_path.unlink()
        except OSError as e:
            return _build_fail(ids, "删不掉旧 build_report.json（%s），"
                                    "不读可能过期的报告" % e)
    cmd = [sys.executable, "h3_prompt_builder.py", "build",
           "--project", str(project), "--out-dir", str(out_dir), "--only"] + ids
    try:
        p = subprocess.run(cmd, cwd=TOOLS, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return _build_fail(ids, "builder 超时（>%d 秒）：%s"
                           % (BUILD_TIMEOUT, " ".join(cmd)))
    except OSError as e:
        return _build_fail(ids, "builder 起不来：%s" % e)
    tail = ((p.stdout or "")[-500:] + (p.stderr or "")[-500:]).strip()
    report = _read_report(report_path)
    if report is None:
        msg = tail or "builder 没有写出 build_report.json"
        if p.returncode != 0:
            msg = "builder 退出码 %s：%s" % (p.returncode, msg)
        return _build_fail(ids, msg)
    if p.returncode != 0 and not _report_failures(report):
        # 退出码非零却报全绿：不能采信，免得把假成功当真
        return _build_fail(ids, "builder 退出码 %s 但报告全绿：%s"
                           % (p.returncode, tail or "无输出"))
    return report


def _preflight(project, doc, ids):
    """在临时项目里预演一遍建稿；失败抛 422，真项目一个字节都不动。"""
    proj = Path(project)
    tmp = Path(tempfile.mkdtemp(prefix="canvas_pre_"))
    try:
        for name in ("characters.yaml", "scenes.yaml", "lexicon.yaml"):
            src = proj / name
            if src.is_file():
                shutil.copy2(str(src), str(tmp / name))
        yaml_dump_atomic(doc, str(tmp / "shots.yaml"))
        (tmp / "out").mkdir()
        report = _build(str(tmp), ids)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    failed = _report_failures(report)
    if failed:
        raise CanvasError("建稿预演失败：%s" % _failure_text(failed), 422)
    return report


# ---------------------------------------------------------------- 写回
def _file_sig(path):
    """写盘前比对用的文件指纹（inode/mtime/size），变了说明别人刚写过。"""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _prepare(project, drafts, edges, anchors):
    """取锁读盘 → 合并副本校验 → 合并真文档并应用边。返回 ``(doc, sig)``。"""
    shots_path = Path(project) / "shots.yaml"
    with _APPLY_LOCK:
        doc = _load_doc(project)
        sig = _file_sig(shots_path)
        # 校验必须看合并后的文档：草稿改完 mode 才轮到边规则判 ref 边
        work = copy.deepcopy(doc)
        _merge(work, drafts, strict=False)
        errs = _validate_doc(work, drafts, edges, anchors)
        if errs:
            raise CanvasError("；".join(e["message"] for e in errs), 422)
        # 校验通过才动真文档（注释跟着真实对象走，才能落盘）
        _merge(doc, drafts)
        seq = doc["shots"]
        by_id = {_sid(s): s for s in seq if _sid(s)}
        moved = apply_edges(list(seq), edges, anchors)
        seq[:] = [by_id[_sid(s)] for s in moved]
    return doc, sig


def _write(project, doc, sig, kind="apply"):
    """取锁备份 + 原子写盘；读盘后被别人改过就 409，不覆盖别人的写。"""
    shots_path = Path(project) / "shots.yaml"
    with _APPLY_LOCK:
        if _file_sig(shots_path) != sig:
            raise CanvasError("shots.yaml 在本次应用期间被改过，请重试", 409)
        backup = _backup_shots(project, kind)
        yaml_dump_atomic(doc, str(shots_path))
    return backup


def apply_draft(project, drafts, edges, anchors, run_gate=True, dry_run=False):
    """校验 → 预演 → 备份 → 写盘 → 建稿 →（可选）批跑与闸。

    ``dry_run`` 只跑到预演，返回 unified diff，不备份也不写盘。
    建稿失败返回 ``ok=False`` 并带上备份路径；闸不过同样 ``ok=False``，
    闸的结论放在 ``gate`` 里。闸/批跑抛异常也只用 ``ok=False + gate.error``
    收尾——那时候 shots.yaml 已经写了，不能把结果整条冲掉。
    """
    drafts = list(drafts or [])
    edges = list(edges or [])
    anchors = dict(anchors or {})
    proj = Path(project)
    shots_path = proj / "shots.yaml"
    ids = [_sid(d) for d in drafts]
    doc, sig = _prepare(project, drafts, edges, anchors)

    # 预演要跑真 builder，费时；放在锁外，写回时再比对指纹
    report = _preflight(project, doc, ids)

    if dry_run:
        before = shots_path.read_text(encoding="utf-8")
        after = yaml_dump_text(doc)
        return {"ok": True, "dry_run": True, "shots": ids, "build": report,
                "diff": list(difflib.unified_diff(
                    before.splitlines(), after.splitlines(),
                    fromfile="shots.yaml (before)", tofile="shots.yaml (after)",
                    lineterm=""))}

    backup = _write(project, doc, sig)

    report = _build(project, ids)
    failed = _report_failures(report)
    out = {"ok": not failed, "shots": ids, "backup": backup,
           "build": report, "batch_dir": "", "gate": None}
    if failed or not run_gate:
        if failed:
            out["error"] = _failure_text(failed)
        return out

    stamp = time.strftime("%Y%m%d_%H%M%S")
    runs_root = os.environ.get(RUNS_ROOT_ENV) or DEFAULT_RUNS_ROOT
    batch_dir = str(Path(runs_root) / ("canvas_apply_%s_%s"
                                       % (stamp, uuid.uuid4().hex[:8])) / "qc")
    out["batch_dir"] = batch_dir
    try:
        from .batch import run_batch
        run_batch(project, INPUT_DIR, batch_dir, shots=ids, force=True)
    except Exception as e:  # 批跑起不来也要给结论，不要把写回结果冲掉
        out["ok"] = False
        out["gate"] = {"ok": False, "error": str(e), "info": {},
                       "reasons": ["spider 批跑失败：%s" % e]}
        return out
    try:
        marker = proj / ".fanxing" / "last_batch.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic({"batch_dir": batch_dir}, str(marker))
        from .gate import check_batch_gate
        ok, reasons, info = check_batch_gate(project, batch_dir, ids)
    except Exception as e:  # 闸炸了也要给结论：写盘已经完成
        out["ok"] = False
        out["gate"] = {"ok": False, "error": str(e), "info": {},
                       "reasons": ["闸门异常：%s" % e]}
        return out
    out["gate"] = {"ok": ok, "reasons": reasons, "info": info}
    out["ok"] = bool(ok)
    return out


# ---------------------------------------------------------------- 增删镜头
def add_shot(project, template_id):
    """按模板镜头复制一镜，id 取下一个空位；写前备份。返回新 id。"""
    proj = Path(project)
    path = str(proj / "shots.yaml")
    with _APPLY_LOCK:
        doc = _load_doc(project)
        seq = doc["shots"]
        by_id = {_sid(s): s for s in seq if _sid(s)}
        tpl = by_id.get(template_id)
        if tpl is None:
            raise CanvasError("模板镜头不存在：%s" % template_id, 422)
        nums = [int(s["id"][1:]) for s in seq
                if _sid(s) and s["id"][:1] == "U" and s["id"][1:].isdigit()]
        if nums:
            n = max(nums) + 1
            while ("U%02d" % n) in by_id:
                n += 1
            nid = "U%02d" % n
        else:
            n = 1
            while ("SH%02d" % n) in by_id:
                n += 1
            nid = "SH%02d" % n
        shot = copy.deepcopy(tpl)
        shot["id"] = nid
        seq.append(CommentedMap(shot))
        _backup_shots(proj, "add")
        yaml_dump_atomic(doc, path)
    return nid


def delete_shot(project, sid):
    """删一镜；写前备份。项目至少留一镜。"""
    proj = Path(project)
    path = str(proj / "shots.yaml")
    with _APPLY_LOCK:
        doc = _load_doc(project)
        seq = doc["shots"]
        keep = [s for s in seq if _sid(s) != sid]
        if len(keep) == len(seq):
            raise CanvasError("镜头不存在：%s" % sid, 404)
        if not keep:
            raise CanvasError("最后一个镜头不能删：%s" % sid, 422)
        seq[:] = keep
        _backup_shots(proj, "delete")
        yaml_dump_atomic(doc, path)
    return sid
