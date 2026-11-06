#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""h3_run_project.py — 按项目卡跑 H3 批次（项目无关）

读 <project>/h3/{shots.yaml, characters.yaml, scenes.yaml, out/<id>.txt}，
把渲染好的提示词和卡上的素材接进 ComfyUI。

用法：
  py h3_run_project.py --project <project>/h3 --out <outputs dir> [--only U01 U02]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, r"C:\Temp\opencode")
import run_auto_v2 as R  # noqa: E402
import yaml  # noqa: E402

from h3_spider.gate import check_batch_gate  # noqa: E402

DEFAULT_SPIDER_BATCH = os.environ.get("H3_SPIDER_BATCH", r"C:/Temp/h3_spider/batch_p15")

CANVAS = {
    "fl2va": os.path.join(R.ROOT, r"01b_本机档适配版\F112_剑斗首尾帧模式workflowFL2VA_本机档.json"),
    "ref2va": os.path.join(R.ROOT, r"01b_本机档适配版\F102_MiniMax H3 Ref2VA - 双采轻量稳定版工作流_本机档.json"),
    "multiref": os.path.join(R.ROOT, r"01b_本机档适配版\F104_MiniMax H3多图参考工作流_本机档.json"),
}
# 沿用第一次 U05 实测有效的低档：0.52/0.55 → 992×544 / 1024×576。
# 1344×768 在 16GB 卡上对长镜容易 OOM，且观感并不更好。
BASE_MP = 0.52
CANVAS_LATEST = os.environ.get(
    "FANXING_CANVAS_LATEST",
    os.path.join(os.path.dirname(R.INPUT), "user", "default", "workflows",
                 "_fanxing_latest.json"))


def patch_ui_from_api(ui, api):
    """把 API 侧已经改好的值回写到 UI 节点 widgets，供 ComfyUI 画布加载。"""
    for n in ui.get("nodes") or []:
        aid = str(n.get("id"))
        av = api.get(aid)
        if not av:
            continue
        spec = (R.OI.get(n.get("type")) or {}).get("input") or {}
        wv = n.get("widgets_values")
        vals = av.get("inputs") or {}
        if isinstance(wv, dict):
            for k, v in vals.items():
                if not isinstance(v, (list, dict)) and k in wv:
                    wv[k] = v
            continue
        if not isinstance(wv, list):
            continue
        wid = 0
        for sec in ("required", "optional"):
            for name, decl in (spec.get(sec) or {}).items():
                it = decl[0] if isinstance(decl, list) else decl
                cfg = decl[1] if isinstance(decl, list) and len(decl) > 1 else {}
                if not R.is_widget(it, cfg):
                    continue
                if wid >= len(wv):
                    break
                v = vals.get(name)
                if v is not None and not isinstance(v, (list, dict)):
                    wv[wid] = v
                wid += 1
                if isinstance(cfg, dict) and cfg.get("control_after_generate") and wid < len(wv):
                    wid += 1
    return ui


def write_canvas_ui(ui, shot, tag, out_dir=None):
    """写 per-shot UI 工作流 + 最新同步文件；后者供画布轮询加载。"""
    payload = {
        "fanxing_sync": {
            "version": str(time.time_ns()),
            "shot": shot.get("id"),
            "tag": tag,
            "source": "h3_run_project",
        },
        "workflow": ui,
    }
    paths = []
    if out_dir:
        paths.append(os.path.join(out_dir, tag + "_workflow.json"))
    if os.environ.get("FANXING_CANVAS_SYNC", "1") != "0":
        paths.append(CANVAS_LATEST)
    for path in paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    return paths


def resolve_asset(p, proj_dir, assets_dir, cards):
    if os.path.isabs(p):
        return p
    names = set((cards["characters"].get("roles") or {}).keys()) | \
            set((cards["scenes"].get("scenes") or {}).keys())
    if p in names:
        return os.path.join(proj_dir, "assets", "crops", p + ".png")
    if assets_dir:
        return os.path.join(assets_dir, p)
    return os.path.join(proj_dir, p)


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(src, dst_dir):
    """把素材放进 ComfyUI input；同名文件按 sha1 判断，不一致就覆盖。

    旧版只判 exists，导致 input 里的同名旧图永远顶替新裁的图
    （2026-10-31 v4：9/12 镜用了 18:35 的旧军装图）。
    """
    name = os.path.basename(src)
    dst = os.path.join(dst_dir, name)
    src_h = _sha1(src)
    old_h = _sha1(dst) if os.path.exists(dst) else None
    if old_h != src_h:
        shutil.copy2(src, dst)
        print("   [stage] %s %s -> 覆盖旧 %s" % (name, src_h[:8], (old_h or "无")[:8]),
              flush=True)
    new_h = _sha1(dst)
    if new_h != src_h:
        raise RuntimeError("stage 校验失败：%s 的 sha1 是 %s，源是 %s"
                           % (dst, new_h, src_h))
    return name


def load_prompt(proj_dir, sid):
    p = os.path.join(proj_dir, "out", sid + ".txt")
    with open(p, encoding="utf-8") as f:
        return f.read().strip()


def build(shot, tag, proj_dir, assets_dir, cards, out_dir=None):
    canvas = shot.get("canvas") or shot["mode"]
    ui = json.load(open(CANVAS[canvas], encoding="utf-8"))
    api = R.patch(R.to_api(R.ui_pre(ui)), tag)

    for v in api.values():
        if v["class_type"] == "PrimitiveFloat":
            v["inputs"]["value"] = float(shot["duration"])

    rs = sorted([(int(k), v) for k, v in api.items() if v["class_type"] == "ResolutionSelector"])
    for i, (k, v) in enumerate(rs):
        # 保留第一次实测的双档：992×544 与 1024×576。
        v["inputs"]["megapixels"] = round(BASE_MP + 0.03 * i, 3)

    prompt = load_prompt(proj_dir, shot["id"])
    cond = None
    for k, v in api.items():
        if v["class_type"] == "MiniMaxH3AudioConditioningT8":
            cond = k
            v["inputs"]["prompt"] = prompt
            for kk in [x for x in v["inputs"]
                       if x.startswith("ref_audios") or x in ("drive_audio", "final_audio")]:
                v["inputs"].pop(kk)
        elif v["class_type"] == "MiniMaxH3ImageToVideo":
            cond = k

    if canvas == "fl2va":
        for k, v in api.items():
            if v["class_type"] == "PrimitiveStringMultiline":
                v["inputs"]["value"] = prompt

    loads = sorted([(int(k), k) for k, v in api.items() if v["class_type"] == "LoadImage"])

    def img(name):
        return stage(resolve_asset(name, proj_dir, assets_dir, cards), R.INPUT)

    if canvas == "fl2va":
        api[loads[0][1]]["inputs"]["image"] = img(shot["image"])
        if shot.get("last_image"):
            api[loads[1][1]]["inputs"]["image"] = img(shot["last_image"])
        else:
            api[cond]["inputs"].pop("last_frame", None)
    elif canvas == "ref2va":
        api[loads[0][1]]["inputs"]["image"] = img(shot["image"])
    else:
        for i, name in enumerate(shot["images"]):
            if i < len(loads):
                api[loads[i][1]]["inputs"]["image"] = img(name)

    for v in api.values():
        if v["class_type"] == "VHS_VideoCombine":
            v["inputs"]["filename_prefix"] = tag
    patch_ui_from_api(ui, api)
    write_canvas_ui(ui, shot, tag, out_dir=out_dir)
    return api


def copy_outputs(pid, h, tag, out_dir):
    """把某次 prompt 的 mp4 从 ComfyUI output 收回 run 目录。"""
    files = []
    for vv in (h.get(pid, {}).get("outputs") or {}).values():
        for key in ("gifs", "images", "video"):
            for item in vv.get(key) or []:
                fn = item.get("filename")
                pth = os.path.join(R.OUTD, item.get("subfolder", ""), fn or "")
                if fn and os.path.exists(pth) and pth.lower().endswith((".mp4", ".webm")):
                    dst = os.path.join(out_dir, "%s_%s.mp4" % (tag, os.path.basename(fn)))
                    shutil.copy(pth, dst)
                    files.append(dst)
    return files


def run_shot(shot, proj_dir, assets_dir, cards, out_dir, timeout_min=None):
    tag = "H3_" + shot["id"]
    if timeout_min is None:
        # 长镜在大分辨率下可能要一小时以上；按成片时长给时间，别再用固定 45 分钟。
        timeout_min = max(60.0, float(shot.get("duration") or 5) * 10)
    api = build(shot, tag, proj_dir, assets_dir, cards, out_dir=out_dir)
    res = R.http_json(R.HOST + "/prompt", {"prompt": api, "client_id": str(uuid.uuid4())})
    pid = res["prompt_id"]
    print("[%s] 提交 %s (%s/%s %.1fs)"
          % (shot["id"], pid, shot.get("canvas"), shot["mode"], shot["duration"]), flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout_min * 60:
        time.sleep(20)
        el = time.time() - t0
        try:
            h = R.http_json(R.HOST + "/history/%s" % pid)
        except Exception:
            continue
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                try:
                    em = [m for m in st.get("messages", []) if m[0] == "execution_error"][0][1]
                    print("[%s] ❌ %s | %s" % (shot["id"], em.get("node_type"),
                                               str(em.get("exception_message"))[:200]), flush=True)
                except Exception:
                    print("[%s] ❌ 执行错误" % shot["id"], flush=True)
                return None
            files = copy_outputs(pid, h, tag, out_dir)
            print("[%s] ✓ %.1f 分钟, %d 个视频" % (shot["id"], el / 60, len(files)), flush=True)
            if not files:
                print("[%s] ❌ 任务完成但没有视频输出" % shot["id"], flush=True)
                return None
            for p in files:
                r = subprocess.run([R.FFPROBE, "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=width,height,nb_frames",
                                    "-show_entries", "format=duration", "-of", "json", p],
                                   capture_output=True, text=True)
                d = json.loads(r.stdout or "{}")
                s = (d.get("streams") or [{}])[0]
                print("   %s %sx%s %sf %.2fs" % (os.path.basename(p), s.get("width"),
                      s.get("height"), s.get("nb_frames"),
                      float((d.get("format") or {}).get("duration") or 0)), flush=True)
            return files
        if int(el) % 240 < 20:
            print("  [%s] 已等 %.1f 分钟..." % (shot["id"], el / 60), flush=True)
    # 超时边界上任务可能刚好出完；再查一次，别把已经成功的片子判死。
    try:
        h = R.http_json(R.HOST + "/history/%s" % pid)
        if pid in h and h[pid].get("status", {}).get("status_str") != "error":
            files = copy_outputs(pid, h, tag, out_dir)
            if files:
                print("[%s] ✓ %.1f 分钟（超时后补收）, %d 个视频"
                      % (shot["id"], (time.time() - t0) / 60, len(files)), flush=True)
                return files
    except Exception:
        pass
    print("[%s] 超时" % shot["id"], flush=True)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="按项目卡跑 H3 批次")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--spider-batch", default=DEFAULT_SPIDER_BATCH,
                    help="spider 批跑目录（含 batch_verdict.json）")
    ap.add_argument("--skip-spider", action="store_true",
                    help="显式跳过 spider 跑前闸（会写进 spider_gate.json）")
    ap.add_argument("--timeout-min", type=float, default=None,
                    help="单镜等待上限；缺省按成片时长自动算（至少 60 分钟）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只跑 spider 闸，不提交任何镜头")
    a = ap.parse_args(argv)

    proj_dir = os.path.abspath(a.project)
    with open(os.path.join(proj_dir, "shots.yaml"), encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    with open(os.path.join(proj_dir, "characters.yaml"), encoding="utf-8") as f:
        chars = yaml.safe_load(f) or {}
    with open(os.path.join(proj_dir, "scenes.yaml"), encoding="utf-8") as f:
        scenes = yaml.safe_load(f) or {}
    cards = {"characters": chars, "scenes": scenes, "shots": doc}
    defaults = doc.get("defaults") or {}
    assets_dir = defaults.get("assets_dir")
    os.makedirs(a.out, exist_ok=True)

    gate_path = os.path.join(a.out, "spider_gate.json")
    if a.skip_spider:
        gate_info = {"skipped": True,
                     "warning": "--skip-spider：本次未验证 spider 批跑结果",
                     "batch": a.spider_batch}
        with open(gate_path, "w", encoding="utf-8") as f:
            json.dump(gate_info, f, ensure_ascii=False, indent=1)
        print("[SPIDER] WARNING 已显式跳过跑前闸：%s" % a.spider_batch, flush=True)
    else:
        ok, reasons, info = check_batch_gate(proj_dir, a.spider_batch, a.only)
        gate_info = {"skipped": False, "ok": ok, "reasons": reasons, "info": info,
                     "checked_shots": a.only}
        with open(gate_path, "w", encoding="utf-8") as f:
            json.dump(gate_info, f, ensure_ascii=False, indent=1)
        if not ok:
            print("[SPIDER] 拒跑：spider 批跑结果对不上当前项目", file=sys.stderr, flush=True)
            for r in reasons:
                print("  - %s" % r, file=sys.stderr, flush=True)
            return 2
        print("[SPIDER] PASS %s（%s）" % (info.get("overall"), info.get("batch_dir")),
              flush=True)

    if a.dry_run:
        print("[SPIDER] dry-run：闸已通过，未提交任何镜头", flush=True)
        return 0

    failed = 0
    for raw in doc.get("shots") or []:
        sid = raw.get("id")
        if a.only and sid not in a.only:
            continue
        shot = dict(defaults)
        shot.update(raw)
        if shot.get("mode") == "multiref":
            shot["canvas"], shot["mode"] = "multiref", "ref2va"
        shot.setdefault("canvas", shot["mode"])
        files = run_shot(shot, proj_dir, assets_dir, cards, a.out,
                         timeout_min=a.timeout_min)
        if files is None:
            failed += 1
            # 超时/报错时上一镜可能还在 GPU 上；继续提交下一镜会把显存挤爆。
            print("[BATCH] %s 失败，停止后续镜头" % sid, flush=True)
            break
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
