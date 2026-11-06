# -*- coding: utf-8 -*-
r"""成片响度量测（loudness_check.py）· R8-04 执行者，只报不拦，exit 恒 0。

## 它为什么长这样
R8-04 的口径 `I=-16 / TP=-1.5` 在 2026-10-03 草案清点时明标"没在任何成片上标定过"。
2026-10-15 起它有标定证据了（见 R8-04 出处），本脚本把量测固化：
- **只量不判**：报 integrated LUFS / true peak (dBTP) / LRA，外加逐段量测；
- 目标口径与容差可传参（默认 -16 LUFS ±3 → 偏出才 warn），**恒 exit 0**（10-03 裁定：
  AAC 过冲＋纯原声片本就该轻，拦容易假阳，降 `[报]`）；
- 单遍 loudnorm 分析即量测（ffmpeg 7.1-essentials，EBU R128），口径写在报表头。

## 用法
    python loudness_check.py <媒体文件> [--segments 54.2-56.6,56.9-59.2] [--target -16] [--tol 3]
逐段示例：修单句前后把本句与前后邻窗各量一段，三窗齐平即与"峰值法"互证。

## 复现对照
对 `E:\10月14日 (1)_BGM.mp4` 整体量测应复现：I≈-17.0 / TP≈-0.1 / LRA≈9.8（2026-10-15 首测）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FFMPEG = "D:/AIWorkflow/tools/ffmpeg.exe"
JSON_BLOCK_RE = re.compile(r"\{\s*\"input_i\".*?\}", re.S)


def measure(media, ss=None, dur=None):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "info"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.3f}", "-t", f"{dur:.3f}"]
    cmd += ["-i", str(media), "-af", "loudnorm=print_format=json", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    m = JSON_BLOCK_RE.search(r.stderr or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def fmt(stats, target, tol):
    if stats is None:
        return "量测失败（ffmpeg/loudnorm 无输出）", None
    i = float(stats["input_i"]) if stats["input_i"] not in ("-inf", "inf") else None
    tp = float(stats["input_tp"]) if stats["input_tp"] not in ("-inf", "inf") else None
    lra = float(stats["input_lra"])
    line = (f"I={stats['input_i']} LUFS  TP={stats['input_tp']} dBTP  LRA={lra} LU")
    if i is not None and abs(i - target) > tol:
        line += f"  ! warn 偏离目标 {target:+.0f} LUFS 超过 ±{tol:g} LU"
    return line, i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--segments", default="", help="逗号分隔的 ss-ss 窗，如 54.2-56.6,56.9-59.2")
    ap.add_argument("--target", type=float, default=-16.0)
    ap.add_argument("--tol", type=float, default=3.0)
    args = ap.parse_args()

    media = Path(args.media)
    print(f"R8-04 响度量测 ｜ EBU R128 via ffmpeg loudnorm 单遍分析 ｜ 目标 I={args.target:+.0f} "
          f"LUFS ±{args.tol:g} LU ｜ 只报不拦 exit 0")
    if not media.is_file():
        print(f"  ✗ error 文件不存在：{media}")
        return 0

    stats = measure(media)
    line, _ = fmt(stats, args.target, args.tol)
    print(f"  整体  {media.name}: {line}")

    for seg in [s for s in args.segments.split(",") if s.strip()]:
        a, b = seg.split("-")
        ss, ee = float(a), float(b)
        line, _ = fmt(measure(media, ss, ee - ss), args.target, args.tol)
        print(f"  {ss:6.2f}-{ee:6.2f}s: {line}")

    print("结论：只报不拦，exit 0（阈值升拦需用户点名，见 R8-04 边界）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
