# -*- coding: utf-8 -*-
r"""光影结构提取器（10-04）·把一条参考片**按镜头切开**，逐镜量光，出一张「光影结构表」。

为什么要切开：`light_scopes.py` 是均匀抽帧，报的是"第几帧"，不报"第几个镜头"。
要把参考片转成提示词，得知道**每一镜**的黑位／光比／光的方向／冷暖分区长什么样——
所以这里只做两件事：① 找切点分镜；② 每镜取代表帧，调 `light_scopes` 现成的量法。
**算法一份不重写**（亮度方程、摆幅口径、肤色窗、冷暖分区全在 light_scopes 里）。

⚠ 切点是**启发式**（帧差中位数＋k×MAD），不是真理：漏切会把两镜并成一镜，
多切会把一镜拆成两镜。所以报表里把每帧的原始帧差一起落盘，切得对不对人眼一扫就知道。
本脚本只量只切，不判好坏、不建闸。

用法：
    python light_structure.py --in <视频> [--out 目录] [--step 5] [--cut-k 8] [--rep 2]
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

import numpy as np

TOOLS_POST = r"D:\AIWorkflow\tools\post"
if TOOLS_POST not in sys.path:
    sys.path.insert(0, TOOLS_POST)
import light_scopes as ls      # noqa: E402  亮度方程／摆幅口径／肤色窗／冷暖分区都吃它这一份


def coarse_diff(a, b, grid=8):
    """两帧亮度面的粗格帧差（＋色度差一点），当切点分数。"""
    ya = a[::grid, ::grid].astype(np.float32)
    yb = b[::grid, ::grid].astype(np.float32)
    d = float(np.abs(ya - yb).mean())
    return d


def find_cuts(scores, k):
    """中位数＋k×MAD 当线（MAD＝绝对偏差中位数，抗离群）。返回切点下标（在 scores 里）。"""
    if not scores:
        return []
    arr = np.asarray(scores, dtype=np.float32)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med))) or 1e-6
    line = med + k * mad
    return [i for i, v in enumerate(arr) if v > line], med, mad, line


def shots_from_cuts(frame_no, cut_pos, n):
    """切点把采样序列切成段。**切点那一帧就是新镜的第一帧**（帧差标在后一帧上），
    所以段界直接用切点位置，不要 ±1——早先写成 `c+1` 会把新镜的首帧留在上一镜末尾，
    看着像"同一镜里两张脸对不上"，其实是分镜错了。"""
    bounds = [0] + list(cut_pos) + [n]
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b > a:
            out.append((frame_no[a], frame_no[b - 1], list(range(a, b))))
    return out


def rep_frames(shot, rep):
    """一镜里取代表帧：均匀取 rep 张（默认 2 张：中段与偏后），别拿切点当帧。"""
    rng = shot[2]
    if rep <= 1 or len(rng) == 1:
        return [rng[len(rng) // 2]]
    return [rng[int(round(i * (len(rng) - 1) / (rep - 1)))] for i in range(rep)]


def probe_fps(path):
    """帧率从盘上现读，不写死 30。"""
    tool, kind = ls.find_probe()
    if kind != "ffprobe":
        return None
    out = subprocess.run([tool, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=r_frame_rate", "-of", "csv=p=0", path],
                         capture_output=True).stdout.decode("utf-8", "replace").strip()
    try:
        num, den = out.split("/")
        return float(num) / float(den) if float(den) else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="光影结构提取：按镜头切开＋逐镜量光（只量不判）")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", default=r"D:\AIWorkflow\tmp\light_structure")
    ap.add_argument("--step", type=int, default=5, help="每几个帧取一帧（30fps／step5＝6 秒 12 帧）")
    ap.add_argument("--cut-k", type=float, default=8.0, help="切点线＝中位数＋k×MAD，k 越小越易判切")
    ap.add_argument("--rep", type=int, default=2, help="每镜取几张代表帧")
    ap.add_argument("--range", default="auto", choices=["auto", "full", "limited"])
    a = ap.parse_args()

    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "light_scopes")
    if not os.path.isdir(tmp):
        os.makedirs(tmp)
    w, h, total = ls.probe_geometry(a.inp)
    if not total:
        print("ffprobe 没给出总帧数，没法均匀切")
        return 1
    idxs = list(range(0, total, max(a.step, 1)))
    rng, rng_note = (a.range, "显式指定") if a.range != "auto" else ls.probe_range(a.inp, True)
    got, note = ls.coded_frames_from_video(a.inp, idxs, tmp)
    if not got:
        print("取帧失败：%s" % note)
        return 1
    planes = [p[1][0] for p in got]                     # 只取亮度面做切点
    fps = probe_fps(a.inp) or 0.0
    tags = [t for t, _ in got]
    frame_no = [int(t[1:]) for t in tags]               # 标签是 "f<帧号>"，帧号从盘上的取帧结果来
    scores = [None] + [coarse_diff(planes[i - 1], planes[i]) for i in range(1, len(planes))]
    cuts, med, mad, line = find_cuts([s for s in scores if s is not None], a.cut_k)
    # find_cuts 的下标是"非 None 序列"里的，往前挪一格回到 planes 坐标
    cuts = [c + 1 for c in cuts]
    shots = shots_from_cuts(frame_no, cuts, len(planes))
    rows = []
    for si, (f0, f1, seg) in enumerate(shots):
        reps = rep_frames((f0, f1, seg), a.rep)
        per = []
        for r in reps:
            tag, pl = got[r]
            per.append((tag, ls.measure_frame(*ls.payload_to_frame(pl, rng), want_subject=True)))
        rows.append({"shot": si + 1, "from": f0, "to": f1,
                     "dur_s": round((f1 - f0) / fps, 2) if fps else None,
                     "reps": [{"tag": t, "m": m} for t, m in per]})
    out = {"src": os.path.basename(a.inp), "range": rng, "range_note": rng_note,
           "frames_note": note, "step": a.step, "cut_k": a.cut_k,
           "cut_line": {"median": round(med, 3), "mad": round(mad, 3), "line": round(line, 3)},
           "scores": [{"tag": tags[i], "diff": (None if scores[i] is None else round(scores[i], 3)),
                       "cut": (i in cuts)} for i in range(len(tags))],
           "shots": rows}
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    jp = os.path.join(a.out, "光影结构_%s.json" % stamp)
    io.open(jp, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
    md = [u"# 光影结构表（按镜头切开·只量不判）", "",
          u"- 输入：`%s`｜总帧 %d｜每 %d 帧取一帧 ⇒ %d 帧｜摆幅 **%s**（%s）" % (
              os.path.basename(a.inp), total, a.step, len(got), rng, rng_note),
          u"- 取帧：%s" % note,
          u"- 切点判据：**启发式**——粗格亮度帧差 > 中位数 %.2f ＋ %s×MAD %.2f ⇒ 线 %.2f｜"
          u"切出 %d 处（漏切会把两镜并一镜，判错了改 `--cut-k`）" % (med, a.cut_k, mad, line, len(cuts)),
          u"- 量法与口径全部吃 `light_scopes.py` 那一份，不在这里重写",
          u"",
          u"| 镜 | 帧范围 | 秒 | 代表帧 | p1 | p50 | p95 | p99.5 | 对比档 | 主体左右档(亮侧) | "
          u"肤色角 | 冷暖Δ（附暗/亮落点 IRE） | 超白%（>合法白） | 亮面≥70／≥90 % |",
          u"|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        dur = (u"%.1f" % r["dur_s"]) if r["dur_s"] is not None else u"—"
        for j, rp in enumerate(r["reps"]):
            m = rp["m"]
            if m["ire_p50"] < 0.5:      # 黑场／淡出：不当成一镜的样子，只标出来
                md.append(u"| %s | %d–%d | %s | `%s` | 黑场（淡出，不取为镜样） |"
                          % (u"%d" % r["shot"] if j == 0 else "", r["from"], r["to"],
                             dur if j == 0 else "", rp["tag"]))
                continue
            tone = u"—"
            if m.get("shadow_angle_deg") is not None and m.get("highlight_angle_deg") is not None:
                # 把暗部落点一起报出来：暗部接近没数据时它的色相是噪声，角度看着大不能当真
                tone = u"%+.1f（暗 %.1f IRE／亮 %.1f IRE）" % (
                    m["tone_sep_deg"], m["shadow_ire_p50"], m["highlight_ire_p50"])
            md.append(u"| %s | %d–%d | %s | `%s` | %.1f | %.1f | %.1f | %.1f | %s | %s（%s） | %s | %s | %.2f | %s／%s |"
                      % (u"%d" % r["shot"] if j == 0 else "", r["from"], r["to"],
                         dur if j == 0 else "",
                         rp["tag"], m["ire_p1"], m["ire_p50"], m["ire_p95"], m["ire_p99.5"],
                         m["contrast_stops_p95_p5"], m["subject_side_stops"],
                         m["subject_brighter_side"],
                         m.get("skin_angle_deg") if m.get("skin_angle_deg") is not None else "n/a",
                         tone, m["over_white_pct"], m["bright70_pct"], m["bright90_pct"]))
    mdp = os.path.join(a.out, "光影结构_%s.md" % stamp)
    io.open(mdp, "w", encoding="utf-8").write(u"\n".join(md))
    print(u"摆幅 %s｜切点线 %.2f（中位 %.2f＋%s×MAD %.2f）｜切 %d 处 ⇒ %d 镜"
          % (rng, line, med, a.cut_k, mad, len(cuts), len(rows)))
    for r in rows:
        m = next((rp["m"] for rp in r["reps"] if rp["m"]["ire_p50"] >= 0.5), r["reps"][0]["m"])
        dur = ("%.1f" % r["dur_s"]) if r["dur_s"] is not None else "—"
        print(u"  镜%-3d 帧%-5d–%-5d %-6ss p50=%-5.1f 对比%-5s 左右%-5s(%s) 肤角%-6s 冷暖%s"
              % (r["shot"], r["from"], r["to"], dur, m["ire_p50"], m["contrast_stops_p95_p5"],
                 m["subject_side_stops"], m["subject_brighter_side"],
                 m.get("skin_angle_deg"),
                 u"%+.1f" % m["tone_sep_deg"] if m.get("tone_sep_deg") is not None else "—"))
    print(u"报表：%s\n      %s" % (mdp, jp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
