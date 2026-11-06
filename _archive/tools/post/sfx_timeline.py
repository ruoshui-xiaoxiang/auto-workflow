# -*- coding: utf-8 -*-
"""音效点位表 → ffmpeg 采样级摆放（P5：把"音效时刻"从生成侧转移到剪辑侧）。

用法:
  py -3.12 sfx_timeline.py <job.json> [--out out.mp4] [--verify]

job.json:
{
  "video": "D:/.../in.mp4",
  "sfx": [
    {"at": 1.20, "file": "click.wav", "gain_db": -4.0},
    {"at": 3.75, "file": "thud.wav",  "gain_db": -6.0}
  ]
}

口径:
- 混音用 `amix=...:normalize=0`（房内规矩：amix 必须显式带 normalize），且 duration=first 保视频长度不被拉长；
- 每个音效 `adelay=<ms>:all=1` 落点，ms 级（48k 采样下 1ms=48 样本）；验证器另按互相关量实际落点（±5ms 内算过）；
- 视频流直拷（-c:v copy），只重编音频。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

FF = r"D:\AIWorkflow\tools\ffmpeg.exe"


def build_cmd(job, out_path):
    inputs = [FF, "-hide_banner", "-loglevel", "error", "-y", "-i", str(job["video"])]
    for e in job["sfx"]:
        inputs += ["-i", str(e["file"])]
    parts, mix = [], ["[0:a]"]
    for i, e in enumerate(job["sfx"], 1):
        ms = int(round(float(e["at"]) * 1000))
        gain = float(e.get("gain_db", 0.0))
        parts.append(f"[{i}:a]adelay={ms}:all=1,volume={gain}dB[s{i}]")
        mix.append(f"[s{i}]")
    filt = ";".join(parts + ["".join(mix) + f"amix=inputs={len(job['sfx'])+1}:normalize=0:duration=first[outa]"])
    return inputs + ["-filter_complex", filt, "-map", "0:v", "-map", "[outa]",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out_path)]


def decode_mono(path, sr=48000):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-i", str(path),
           "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0


def verify(job, out_path):
    mixed = decode_mono(out_path)
    ok_all = True
    for e in job["sfx"]:
        sfx = decode_mono(e["file"])
        if len(sfx) == 0:
            print(f"  [verify] {e['file']} 空文件，跳过"); continue
        center = int(float(e["at"]) * 48000)
        w = 0.25
        lo, hi = max(0, center - int(w * 48000)), min(len(mixed) - len(sfx), center + int(w * 48000))
        seg = mixed[lo:hi + len(sfx)]
        corr = np.correlate(seg, sfx, mode="valid")
        lag = int(np.argmax(np.abs(corr)))
        measured = (lo + lag) / 48000.0
        off_ms = (measured - float(e["at"])) * 1000
        ok = abs(off_ms) <= 5.0
        ok_all &= ok
        print(f"  [verify] {Path(e['file']).name} @ {e['at']:.3f}s → 实测 {measured:.3f}s（偏差 {off_ms:+.1f}ms）"
              f" {'PASS' if ok else 'FAIL'}")
    return ok_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--out")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8"))
    out_path = Path(a.out) if a.out else Path(job["video"]).with_name(Path(job["video"]).stem + "_sfx.mp4")
    cmd = build_cmd(job, out_path)
    print("[sfx] " + " ".join(cmd[:8]) + " ...")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-800:]); return 2
    print(f"[sfx] 输出: {out_path}")
    if a.verify:
        ok = verify(job, out_path)
        print("[verify] 全部点位", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
