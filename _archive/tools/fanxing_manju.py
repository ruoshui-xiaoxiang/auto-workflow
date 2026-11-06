#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fanxing_manju.py — 繁星 · MiniMax Design 专用漫剧通路

定位：繁星 workflow 的兄弟入口，不改动 fanxing 原有代码。
在既有 h3 工具链（precheck / prompt_builder / spider batch / gate / run_project）之上，
加一层「漫剧专用闸」：台词时长、画幅一致、角色锚点、微动约束、镜间与跨集连续性。

身份：硬锁 agent_id = minimax-design（协议 §1 的 id 不可变；不额外写注册表字段，遵守 §7）。

阶段：identity → cards → dramagate → precheck → build → style → qc → gate → run → manifest
用法：
  py -3.12 fanxing_manju.py --project <项目目录> --out <输出目录> --through dramagate
  py -3.12 fanxing_manju.py --project ... --out ... --through run --execute-run
"""
import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import yaml

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from fanxing import agents  # noqa: E402

AGENT_ID = "minimax-design"
FORMS = {"2d-comic", "3d-narrated", "live-action-drama"}
STAGES = ("identity", "cards", "dramagate", "precheck", "build",
          "style", "qc", "gate", "run", "manifest")
LABELS = {"identity": "身份", "cards": "读卡", "dramagate": "漫剧闸",
          "precheck": "预检", "build": "建稿", "style": "注入画风",
          "qc": "质检", "gate": "跑前闸", "run": "出片", "manifest": "交付清单"}

# 大幅运镜词：漫剧要"局部微动"，不该出现这些
BIG_MOVE = ("推镜", "拉镜", "摇镜", "环绕", "甩镜", "航拍", "dolly", "zoom in",
            "zoom out", "pan ", "orbit", "crane shot", "tracking shot")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _sha1(path: str) -> str:
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_yaml(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _stage(stages: List[Dict], sid: str, status: str, **kw) -> Dict:
    item = {"id": sid, "label": LABELS[sid], "status": status, "at": _now()}
    item.update({k: v for k, v in kw.items() if v is not None})
    stages.append(item)
    return item


def _skipped(stages: List[Dict], sid: str, reason: str) -> None:
    stages.append({"id": sid, "label": LABELS[sid], "status": "skipped",
                   "at": _now(), "reason": reason})


def _run_cmd(cmd: List[str], log_path: str, timeout: int = 6 * 3600) -> Dict:
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=TOOLS, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        rc, out, err = p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as e:
        rc, out, err = 124, e.stdout or "", (e.stderr or "") + "\n[timeout]"
    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("$ " + " ".join(cmd) + "\n\n" + out + "\n--- stderr ---\n" + err)
    return {"rc": rc, "duration_s": round(time.time() - t0, 2),
            "stdout": out, "stderr": err, "log": log_path}


# ---------- 卡 ----------

def _aspect_str(v) -> str:
    """YAML 1.1 会把未加引号的 16:9 解析成六十进制整数（969），这里还原。"""
    if isinstance(v, str):
        return v
    if isinstance(v, int) and v > 0:
        a, b = divmod(v, 60)
        return "%d:%d" % (a, b)
    return str(v)

def load_project(project: str) -> Dict:
    m = _load_yaml(os.path.join(project, "manju.yaml")) or {}
    if m.get("aspect") is not None:
        m["aspect"] = _aspect_str(m["aspect"])
    doc = _load_yaml(os.path.join(project, "shots.yaml")) or {}
    for s in (doc.get("shots") or []):
        if isinstance(s, dict) and s.get("aspect") is not None:
            s["aspect"] = _aspect_str(s["aspect"])
    return {
        "manju": m,
        "shots": doc,
        "characters": _load_yaml(os.path.join(project, "characters.yaml")) or {},
        "scenes": _load_yaml(os.path.join(project, "scenes.yaml")) or {},
        "lexicon": _load_yaml(os.path.join(project, "lexicon.yaml")) or {},
    }


def _cast_names(shot: Dict) -> List[str]:
    """卡里用 cast: {S1: cmdr}；也兼容 characters: [cmdr]。"""
    cast = shot.get("cast")
    if isinstance(cast, dict):
        return [str(v) for v in cast.values() if v]
    if isinstance(cast, (list, tuple)):
        return [str(v) for v in cast if v]
    names = shot.get("characters") or []
    return [str(v) for v in names if v]


def _dialogue_texts(shot: Dict) -> List[str]:
    """卡里用 dialogue: [{speaker, voice, text, after}]；兼容字符串与 narration。"""
    out: List[str] = []
    dlg = shot.get("dialogue")
    if isinstance(dlg, list):
        for d in dlg:
            out.append(str(d.get("text") or "") if isinstance(d, dict) else str(d or ""))
    elif isinstance(dlg, dict):
        out.append(str(dlg.get("text") or ""))
    elif isinstance(dlg, str):
        out.append(dlg)
    if shot.get("narration"):
        out.append(str(shot.get("narration") or ""))
    return [x for x in out if x]


def validate_cards(project: str, c: Dict) -> List[str]:
    """结构校验；空列表 = 通过。不做审美判断。"""
    errs = []
    m = c["manju"]
    if not m:
        errs.append("缺 manju.yaml（漫剧卡）：至少需要 episode / form / aspect")
    else:
        if not m.get("episode"):
            errs.append("manju.yaml 缺 episode")
        if m.get("form") not in FORMS:
            errs.append("manju.yaml 的 form 必须是 %s 之一，现在是 %r"
                        % ("/".join(sorted(FORMS)), m.get("form")))
        if not m.get("aspect"):
            errs.append("manju.yaml 缺 aspect（如 9:16 / 16:9）")
    if not c["shots"].get("shots"):
        errs.append("shots.yaml 没有 shots 列表")
    if not c["characters"].get("roles"):
        errs.append("characters.yaml 没有 roles（漫剧必须锚定角色）")
    if not c["scenes"].get("scenes"):
        errs.append("scenes.yaml 没有 scenes")
    return errs


def dramagate(project: str, c: Dict, out_dir: Optional[str] = None) -> Dict:
    """漫剧专用闸：画幅 / 台词时长 / 角色锚点 / 场景 / 空镜 / 微动 / 跨集连续性。"""
    m, doc = c["manju"], c["shots"]
    aspect = m.get("aspect")
    voice = m.get("voice") or {}
    rate = float(voice.get("chars_per_second") or 4.1)
    strict = bool(voice.get("strict") or False)
    style_prefix = ((m.get("style") or {}).get("prompt_prefix") or "").strip()
    roles = c["characters"].get("roles") or {}
    scenes = c["scenes"].get("scenes") or {}
    crops = os.path.join(project, "assets", "crops")
    shots = doc.get("shots") or []
    defaults = doc.get("defaults") or {}

    errors: List[str] = []
    warns: List[str] = []
    dialogue_shots = 0
    total_chars = 0
    info = {"shots": len(shots), "form": m.get("form"), "aspect": aspect,
            "chars_per_second": rate, "style_prefix": bool(style_prefix)}

    for raw in shots:
        sid = str(raw.get("id") or "?")
        shot = dict(defaults)
        shot.update(raw)

        # 1) 画幅（全集统一；单镜可覆盖但必须一致）
        asp = shot.get("aspect") or aspect
        if asp != aspect:
            errors.append("%s 画幅 %r 与全集 %r 不一致" % (sid, asp, aspect))

        # 2) 台词/旁白时长
        texts = _dialogue_texts(shot)
        if texts:
            dialogue_shots += 1
        chars = len("".join("".join(texts).split()))
        total_chars += chars
        dur = float(shot.get("duration") or 0)
        if chars and dur:
            need = chars / rate
            if need > dur:
                msg = ("%s 台词 %d 字需要 %.1fs，镜头只有 %.1fs（按 %.1f 字/秒）"
                       % (sid, chars, need, dur, rate))
                (errors if strict else warns).append(msg)
            elif need < dur * 0.3:
                warns.append("%s 台词 %d 字只占 %.1fs 里约 %.0f%%，镜头可能偏空"
                             % (sid, chars, dur, 100.0 * need / dur))

        # 3) 角色锚点
        names = _cast_names(shot)
        if not names:
            errors.append("%s 没有 cast（漫剧每镜必须锚定角色）" % sid)
        for name in names:
            if name not in roles:
                errors.append("%s 的角色 %r 不在 characters.yaml 的 roles 里" % (sid, name))
                continue
            img = os.path.join(crops, name + ".png")
            if not os.path.isfile(img):
                errors.append("%s 的角色 %r 缺锚点图 %s" % (sid, name, img))

        # 4) 场景
        sc = shot.get("scene")
        if sc and sc not in scenes:
            errors.append("%s 的场景 %r 不在 scenes.yaml 里" % (sid, sc))

        # 5) 空镜
        if not (shot.get("image") or shot.get("images") or shot.get("last_image") or sc):
            errors.append("%s 既无参考图也无场景，漫剧不允许空镜" % sid)

        # 6) 微动（有现稿才查）
        p = os.path.join(project, "out", sid + ".txt")
        if os.path.isfile(p):
            text = open(p, encoding="utf-8").read()
            hits = [w for w in BIG_MOVE if w.lower() in text.lower()]
            if hits:
                warns.append("%s 提示词含大幅运镜词 %s（漫剧应为局部微动）"
                             % (sid, "/".join(hits[:3])))
            if style_prefix and style_prefix not in text:
                warns.append("%s 现稿未含画风前缀，style 阶段会补" % sid)

    # 7) 跨集连续性
    series = m.get("series") or {}
    prev = series.get("prev_episode_dir")
    if series.get("id") and prev and os.path.isdir(prev):
        old = (_load_yaml(os.path.join(prev, "characters.yaml")) or {}).get("roles") or {}
        for name in roles:
            o = old.get(name)
            if o is None:
                warns.append("系列 %s：上一集没有角色 %r（新角色）" % (series.get("id"), name))
                continue
            a = os.path.join(crops, name + ".png")
            b = os.path.join(prev, "assets", "crops", name + ".png")
            if os.path.isfile(a) and os.path.isfile(b) and _sha1(a) != _sha1(b):
                errors.append("系列 %s：角色 %r 的锚点图与上一集不一致（跨集一致性会崩）"
                              % (series.get("id"), name))

    info["dialogue_shots"] = dialogue_shots
    info["dialogue_chars"] = total_chars
    return {"ok": not errors, "errors": errors, "warnings": warns, "info": info}

# ---------- 主流程 ----------

def run(project: str, out_root: str, through: str = "dramagate",
        execute_run: bool = False, registry: Optional[str] = None) -> Dict:
    if through not in STAGES:
        raise ValueError("through 只能是 %s" % "/".join(STAGES))
    if registry:
        os.environ["FANXING_REGISTRY"] = registry

    project = os.path.abspath(project)
    out_root = os.path.abspath(out_root)
    os.makedirs(out_root, exist_ok=True)
    stages: List[Dict] = []
    blocked = False
    batch_dir = os.path.join(out_root, "qc")
    cards = load_project(project)
    gate_report = {"ok": False, "errors": [], "warnings": []}

    def may(sid: str) -> bool:
        return (not blocked) and STAGES.index(sid) <= STAGES.index(through)

    # identity
    rec = None
    if not may("identity"):
        _skipped(stages, "identity", "到达 --through 之前")
    else:
        try:
            rec = agents.get(AGENT_ID, require_scope="workflow:run")
            if rec.get("agent_id") != AGENT_ID:
                raise agents.AgentError("agent 不是 %s" % AGENT_ID)
            _stage(stages, "identity", "ok", summary="%s · %s"
                   % (rec.get("name"), rec.get("contract")))
        except Exception as e:
            _stage(stages, "identity", "block", error=str(e))
            blocked = True

    # cards
    if not may("cards"):
        _skipped(stages, "cards", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        errs = validate_cards(project, cards)
        _stage(stages, "cards", "ok" if not errs else "block",
               summary="%d error" % len(errs), errors=errs or None)
        if errs:
            blocked = True

    # dramagate
    if not may("dramagate"):
        _skipped(stages, "dramagate", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        try:
            gate_report = dramagate(project, cards)
            gp = os.path.join(out_root, "manju_gate.json")
            with open(gp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(gate_report, f, ensure_ascii=False, indent=1)
            _stage(stages, "dramagate", "ok" if gate_report["ok"] else "block",
                   summary="%d error / %d warn" % (len(gate_report["errors"]),
                                                   len(gate_report["warnings"])),
                   artifacts={"json": gp})
            if not gate_report["ok"]:
                blocked = True
        except Exception as e:
            _stage(stages, "dramagate", "error", error=str(e))
            blocked = True

    # precheck
    if not may("precheck"):
        _skipped(stages, "precheck", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        pj = os.path.join(out_root, "precheck.json")
        r = _run_cmd([sys.executable, "h3_precheck.py", "--project", project,
                      "--json", pj], os.path.join(out_root, "logs", "precheck.log"))
        issues = []
        if os.path.isfile(pj):
            try:
                issues = json.load(open(pj, encoding="utf-8"))
            except Exception:
                issues = []
        e = sum(1 for i in issues if i.get("level") == "error")
        w = sum(1 for i in issues if i.get("level") == "warn")
        ok = r["rc"] == 0 and not e
        _stage(stages, "precheck", "ok" if ok else "block", _t0=None,
               summary="%d error / %d warn" % (e, w), log=r["log"],
               artifacts={"json": pj})
        if not ok:
            blocked = True

    # build
    if not may("build"):
        _skipped(stages, "build", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        prompt_dir = os.path.join(project, "out")
        r = _run_cmd([sys.executable, "h3_prompt_builder.py", "build",
                      "--project", project, "--out-dir", prompt_dir],
                     os.path.join(out_root, "logs", "build.log"))
        rp = os.path.join(prompt_dir, "build_report.json")
        report = []
        if os.path.isfile(rp):
            try:
                report = json.load(open(rp, encoding="utf-8"))
            except Exception:
                report = []
        failed = [x for x in report if not x.get("ok")]
        ok = r["rc"] == 0 and not failed
        _stage(stages, "build", "ok" if ok else "block",
               summary="%d 镜 / %d 失败" % (len(report), len(failed)),
               log=r["log"], artifacts={"report": rp})
        if not ok:
            blocked = True

    # style
    if not may("style"):
        _skipped(stages, "style", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        prefix = (((cards.get("manju") or {}).get("style") or {})
                  .get("prompt_prefix") or "").strip()
        if not prefix:
            _skipped(stages, "style", "manju.yaml 未配置 style.prompt_prefix")
        else:
            fixed = []
            for raw in (cards["shots"].get("shots") or []):
                p = os.path.join(project, "out", str(raw.get("id")) + ".txt")
                if not os.path.isfile(p):
                    continue
                text = open(p, encoding="utf-8").read()
                if prefix in text:
                    continue
                with open(p, "w", encoding="utf-8", newline="\n") as f:
                    f.write(prefix + "\n" + text)
                fixed.append(raw.get("id"))
            _stage(stages, "style", "ok", summary="补 %d 镜" % len(fixed),
                   changed=fixed or None)

    # qc
    if not may("qc"):
        _skipped(stages, "qc", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        try:
            from h3_spider.batch import run_batch
            b = run_batch(project, os.environ.get("H3_INPUT") or
                          r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input", batch_dir)
            ok = b.get("overall") == "PASS"
            _stage(stages, "qc", "ok" if ok else "block",
                   summary="%s · %d 镜 / %d 失败" % (b.get("overall"),
                                                     len(b.get("shots") or {}),
                                                     len(b.get("failures") or [])),
                   artifacts={"batch_dir": batch_dir})
            if not ok:
                blocked = True
        except Exception as e:
            _stage(stages, "qc", "error", error=str(e))
            blocked = True

    # gate
    if not may("gate"):
        _skipped(stages, "gate", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        try:
            from h3_spider.gate import check_batch_gate
            ok, reasons, gi = check_batch_gate(project, batch_dir)
            gp = os.path.join(out_root, "gate.json")
            with open(gp, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"ok": ok, "reasons": reasons, "info": gi},
                          f, ensure_ascii=False, indent=1)
            _stage(stages, "gate", "ok" if ok else "block",
                   summary="PASS" if ok else "拒跑：%d 条" % len(reasons),
                   artifacts={"gate": gp})
            if not ok:
                blocked = True
        except Exception as e:
            _stage(stages, "gate", "error", error=str(e))
            blocked = True

    # run
    if not may("run"):
        _skipped(stages, "run", "到达 --through 之前" if not blocked else "上游 BLOCK")
    elif not execute_run:
        _skipped(stages, "run", "未显式 --execute-run（不提交 GPU）")
    else:
        run_out = os.path.join(out_root, "run")
        r = _run_cmd([sys.executable, "h3_run_project.py", "--project", project,
                      "--out", run_out, "--spider-batch", batch_dir],
                     os.path.join(out_root, "logs", "run.log"))
        ok = r["rc"] == 0
        _stage(stages, "run", "ok" if ok else "block",
               summary="出片完成" if ok else "出片失败/拒跑",
               log=r["log"], artifacts={"dir": run_out})
        if not ok:
            blocked = True

    # manifest
    if not may("manifest"):
        _skipped(stages, "manifest", "到达 --through 之前" if not blocked else "上游 BLOCK")
    else:
        run_out = os.path.join(out_root, "run")
        items = []
        for raw in (cards["shots"].get("shots") or []):
            sid = str(raw.get("id"))
            videos = []
            if os.path.isdir(run_out):
                videos = sorted(f for f in os.listdir(run_out)
                                if f.startswith("H3_" + sid + "_") and f.endswith(".mp4"))
            items.append({
                "shot": sid, "duration": raw.get("duration"),
                "characters": raw.get("characters") or [],
                "scene": raw.get("scene"),
                "prompt": os.path.join(project, "out", sid + ".txt"),
                "videos": [os.path.join(run_out, v) for v in videos],
                "canvas_role": "分镜" if not videos else "成片",
            })
        manifest = {"episode": (cards["manju"].get("episode")),
                    "form": (cards["manju"].get("form")),
                    "aspect": (cards["manju"].get("aspect")),
                    "agent_id": AGENT_ID,
                    "shots": items,
                    "blocked_before_run": blocked}
        mp = os.path.join(out_root, "manju_manifest.json")
        with open(mp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        _stage(stages, "manifest", "ok",
               summary="%d 镜 / %d 镜有成片"
               % (len(items), sum(1 for i in items if i["videos"])),
               artifacts={"json": mp})

    overall = "BLOCK" if blocked or any(
        s["status"] in ("block", "error") for s in stages) else "PASS"
    wf = {"version": 1, "tool": "fanxing_manju", "agent_id": AGENT_ID,
          "agent_name": (rec or {}).get("name"), "project": project,
          "through": through, "execute_run": bool(execute_run),
          "overall": overall, "started_at": _now(),
          "duration_s": None, "stages": stages,
          "dramagate": {"ok": gate_report.get("ok"),
                        "errors": gate_report.get("errors") or [],
                        "warnings": gate_report.get("warnings") or [], "info": gate_report.get("info") or {}}}
    wp = os.path.join(out_root, "workflow.json")
    with open(wp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(wf, f, ensure_ascii=False, indent=1)
    wf["path"] = wp
    try:
        agents.touch(AGENT_ID)
    except Exception:
        pass
    return wf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="繁星 · MiniMax Design 专用漫剧通路")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--through", default="dramagate", choices=list(STAGES))
    ap.add_argument("--execute-run", action="store_true",
                    help="显式允许提交 GPU（默认只到闸门）")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    try:
        wf = run(a.project, a.out, a.through, a.execute_run, a.registry)
    except agents.AgentError as e:
        print("[MANJU] 身份错误：%s" % e, file=sys.stderr)
        return 2
    except ValueError as e:
        print("[MANJU] 用法错误：%s" % e, file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps(wf, ensure_ascii=False, indent=1))
    else:
        print("=" * 66)
        print("漫剧通路 · %s" % wf["overall"])
        print("agent=%s  through=%s  form=%s  aspect=%s"
              % (wf["agent_id"], wf["through"],
                 ((wf.get("dramagate") or {}).get("info") or {}).get("form") or "-",
                 ((wf.get("dramagate") or {}).get("info") or {}).get("aspect") or "-"))
        print("=" * 66)
        for s in wf["stages"]:
            extra = s.get("summary") or s.get("reason") or s.get("error") or ""
            print("  %-6s %-8s %s" % (s["label"], s["status"], extra))
        print("  workflow: %s" % wf["path"])
        dg = wf.get("dramagate") or {}
        for e in dg.get("errors") or []:
            print("  [error] %s" % e)
        for w in (dg.get("warnings") or [])[:10]:
            print("  [warn ] %s" % w)
    return 0 if wf["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())