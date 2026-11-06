#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 N 条候选片/图拼成"带编号的呈审包"，供人工关口（H4 看片挑号 / H2 锚点选定）在会话里审。

为什么需要它：关口默认不走飞书了（手机端 Qoder 实测图与视频都能看），
所以呈审面就是聊天窗口 —— 而聊天里最怕的就是"第三个"说不清是哪条。
这个工具产出的每个文件都自带编号，且编号表打在 stdout，你回编号即可。

用法：
  py make_review_sheet.py --files "A.mp4,B.mp4" [--labels "纯图四锚,加参考视频"]
                          [--at 0.4]        # 取每条的相对位置抓静帧（可多值：0.1,0.5,0.9）
                          [--clip 4.2]      # 并排短片时长（秒）
                          [--height 480]    # 每格高度
                          [--out-name shot5_AB]

输出（默认 D:\\AIWorkflow\\tmp\\review\\<out-name>\\）：
  grid.png   每条 × 每个采样点 的编号静帧表
  clip.mp4   全部候选同高并排、时间对齐的无声短片（动效只能这样看）
  编号映射   打到 stdout，形如：1 = A.mp4 · 纯图四锚
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

OUT_ROOT = Path(r"D:\AIWorkflow\tmp\review")


def read_image(path: Path):
    raw = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(raw, cv2.IMREAD_COLOR)


def write_image(path: Path, img):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise RuntimeError(f"编码失败: {path}")
    path.write_bytes(buf.tobytes())


def probe(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 24.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    return {"frames": n, "fps": fps, "w": w, "h": h, "seconds": n / fps if n else 0.0}


def grab(path: Path, at_list):
    """图片返回它自己；视频按相对位置取若干帧。返回 [(标签后缀, BGR), ...]"""
    ext = path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        img = read_image(path)
        return [("静帧", img)] if img is not None else []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out = []
    for at in at_list:
        idx = int(round(max(0.0, min(0.999, at)) * max(0, n - 1)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if ok:
            out.append((f"{int(at*100)}%", fr))
    cap.release()
    return out


def label_tile(img, tag, cell_w, cell_h):
    h, w = img.shape[:2]
    s = min(cell_w / w, cell_h / h)
    img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))))
    cell = np.full((cell_h, cell_w, 3), 26, np.uint8)
    y0 = (cell_h - img.shape[0]) // 2
    x0 = (cell_w - img.shape[1]) // 2
    cell[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    cv2.rectangle(cell, (0, 0), (cell_w, 30), (40, 40, 40), -1)
    cv2.putText(cell, tag[:int(cell_w / 12)], (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
    return cell


def build_grid(cands, at_list, cell_h):
    tiles, mapping = [], []
    idx = 0
    for ci, (path, lab) in enumerate(cands, 1):
        frames = grab(path, at_list)
        if not frames:
            print(f"  ! 读不到 {path.name}，跳过", file=sys.stderr)
            continue
        row = []
        for si, (tag, fr) in enumerate(frames):
            idx += 1
            scale = 1.0 if si else 2.0        # 编号放大在第一格，手机上也好指
            cell = label_tile(fr, f"{idx}" if scale == 1 else f"{idx}",
                              int(cell_h * 9 / 16), cell_h)
            cv2.rectangle(cell, (cell.shape[1] - 92, 0), (cell.shape[1], 26), (40, 40, 40), -1)
            cv2.putText(cell, tag, (cell.shape[1] - 88, 19),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
            row.append(cell)
            mapping.append((idx, path.name, lab or "", tag))
        tiles.append(np.hstack(row))
    if not tiles:
        raise RuntimeError("一个候选都没读到，检查 --files 路径")
    return np.vstack(tiles) if len({t.shape[1] for t in tiles}) == 1 else \
        np.vstack([cv2.resize(t, (max(x.shape[1] for x in tiles), t.shape[0]))
                   for t in tiles]), mapping


def build_clip(cands, seconds, height, dst: Path):
    """同高并排、按最短一条截断、无声。动效对齐只能这样看，静帧会骗人。"""
    caps, meta = [], []
    for path, _ in cands:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            continue
        caps.append(cap)
        meta.append({"fps": float(cap.get(cv2.CAP_PROP_FPS) or 24.0) or 24.0})
    if not caps:
        raise RuntimeError("没有可用视频")
    fps = max(m["fps"] for m in meta)
    n = int(seconds * fps)
    w_cell = int(height * 9 / 16) if len(caps) <= 3 else int(height * 9 / 16 * 0.9)
    total_w = w_cell * len(caps)
    tmp = dst.parent / f".{dst.stem}.tmp.mp4"          # cv2 写不了非 ASCII 路径
    tmp.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (total_w, height))
    if not vw.isOpened():
        raise RuntimeError("VideoWriter 打不开（缺 mp4v 编码器？）")
    for i in range(n):
        row = []
        for ci, cap in enumerate(caps):
            ok, fr = cap.read()
            if not ok:
                fr = np.zeros((height, w_cell, 3), np.uint8)
            else:
                h, w = fr.shape[:2]
                s = height / h
                fr = cv2.resize(fr, (max(1, int(w * s)), height))
                if fr.shape[1] != w_cell:
                    pad = np.full((height, w_cell, 3), 20, np.uint8)
                    x = max(0, (w_cell - fr.shape[1]) // 2)
                    pad[:, x:x + min(fr.shape[1], w_cell)] = fr[:, :w_cell - x] if fr.shape[1] >= w_cell - x else fr
                    fr = pad
            cv2.rectangle(fr, (0, 0), (34, 30), (30, 30, 30), -1)
            cv2.putText(fr, str(ci + 1), (10, 23), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (255, 255, 255), 2, cv2.LINE_AA)
            row.append(fr)
        vw.write(np.hstack(row))
    vw.release()
    for cap in caps:
        cap.release()
    shutil.move(str(tmp), dst)
    return dst


def main():
    ap = argparse.ArgumentParser(description="关口呈审包：带编号的静帧表 + 并排短片")
    ap.add_argument("--files", required=True, help="逗号分隔的候选视频或图片")
    ap.add_argument("--labels", default="", help="逗号分隔的说明，与 --files 同序")
    ap.add_argument("--at", default="0.12,0.5,0.88", help="视频取帧的相对位置")
    ap.add_argument("--clip", type=float, default=4.2, help="并排短片时长（秒）")
    ap.add_argument("--height", type=int, default=460, help="每格/每列高度")
    ap.add_argument("--out-name", dest="out_name", default=time.strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--also-copy-to", dest="also", default="", help="成品再复制去的目录（批次夹）")
    a = ap.parse_args()

    files = [Path(x.strip()) for x in a.files.split(",") if x.strip()]
    labels = [x.strip() for x in a.labels.split(",")] if a.labels else [""] * len(files)
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        print("文件不存在：" + "，".join(missing), file=sys.stderr)
        return 2
    if len(labels) != len(files):
        print("--labels 数量与 --files 不符", file=sys.stderr)
        return 2
    at_list = [float(x) for x in a.at.split(",") if x.strip()]
    cands = list(zip(files, labels))

    out = OUT_ROOT / a.out_name
    out.mkdir(parents=True, exist_ok=True)
    print("== 候选体检 ==")
    for (f, lab) in cands:
        info = probe(f)
        if info:
            print(f"  {f.name} · {lab or '-'}  {info['w']}x{info['h']} "
                  f"{info['fps']:.1f}fps {info['frames']}帧 {info['seconds']:.2f}s")
        else:
            img = read_image(f)
            print(f"  {f.name} · {lab or '-'}  图 {img.shape[1]}x{img.shape[0]}"
                  if img is not None else f"  {f.name} 读不了")

    grid, mapping = build_grid(cands, at_list, a.height)
    gp = out / "grid.png"
    write_image(gp, grid)
    print(f"\n静帧表：{gp}  （{grid.shape[1]}x{grid.shape[0]}）")

    vids = [(f, l) for f, l in cands if f.suffix.lower() not in
            (".png", ".jpg", ".jpeg", ".webp", ".bmp")]
    cp = None
    if len(vids) > 1:
        cp = build_clip(vids, a.clip, a.height, out / "clip.mp4")
        print(f"并排短片：{cp}  （{a.clip}s，无声，左上角数字＝编号）")

    print("\n== 编号映射（回编号即可）==")
    for num, name, lab, tag in mapping:
        tail = f" · {lab}" if lab else ""
        tail += f" · 取帧 {tag}" if tag and tag != "静帧" else ""
        print(f"  {num} = {name}{tail}")
    if cp:
        print("  （短片里的数字按 --files 顺序编号，与上表同序）")
    if a.also:
        dst = Path(a.also)
        dst.mkdir(parents=True, exist_ok=True)
        for srcf in filter(None, [gp, cp]):
            shutil.copy2(srcf, dst / srcf.name)
            print(f"  已复制 {srcf.name} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
