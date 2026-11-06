# -*- coding: utf-8 -*-
r"""本地出图 vs 范例结构卡——同一把尺（light_scopes）两头量，逐项摆一起看差在哪。

口径：范例是带 `tv` 旗的视频（0–100 IRE ＝ 码值 16–235），本地产物是 PNG（full，0–100 IRE ＝ 0–255）。
**两边的 IRE 都是显示归一，黑位／中灰／白位／对比档／亮面／肤色角／冷暖Δ 可比**；
只有「超出合法白」不可比（PNG 没有 235 这条线）。

`--labels "二轮=b,三轮c=c"` 里的等号右边是**文件名后缀**：K3b／K3c 这种。
不写后缀就是第一轮（`K3`）。每个号取自己那一行的读数，缺就报 `—`。
本脚本只对照读数，不判好坏（好不好看由人报号）。
"""
import argparse
import csv
import io
import json
import os
import re

ITEMS = [("黑位 p1", "ire_p1", "%.1f"),
         ("中灰 p50", "ire_p50", "%.1f"),
         ("白位 p95", "ire_p95", "%.1f"),
         ("亮面≥70 %", "bright70_pct", "%.1f"),
         ("近白≥90 %", "bright90_pct", "%.2f"),
         ("对比档 p95/p5", "contrast_stops_p95_p5", "%.2f"),
         ("主体左右档", "subject_side_stops", "%.2f"),
         ("肤色角", "skin_angle_deg", "%.1f"),
         ("饱和 R", "skin_sat_R", "%.1f"),
         ("冷暖Δ", "tone_sep_deg", "%+.1f")]


def load(path):
    out = {}
    for r in csv.DictReader(io.open(path, encoding="utf-8-sig")):
        m = re.search(r"K(\d)([a-z]?)_", r["src"])
        if not m:
            continue
        base, suf = "K" + m.group(1), m.group(2)
        out.setdefault(base, {})[suf] = r
    return out


def ref_range(path, shot):
    d = json.load(io.open(path, encoding="utf-8"))
    for s in d["shots"]:
        if s["shot"] == shot:
            ms = [r["m"] for r in s["reps"] if r["m"]["ire_p50"] >= 0.5]
            out = {}
            for _, key, _f in ITEMS:
                vals = [m[key] for m in ms if m.get(key) is not None]
                out[key] = (min(vals), max(vals)) if vals else None
            return out
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-csv", required=True, help="一个 CSV（产物夹全量跑检光出的）")
    ap.add_argument("--ref-json", required=True)
    ap.add_argument("--labels", default="一轮=,二轮=b,三轮c=c,三轮d=d",
                    help="表头=文件名后缀，逗号分隔")
    ap.add_argument("--only", default="K1,K3,K4,K5")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    data = load(a.gen_csv)
    labels = [(x.split("=", 1)[0].strip(), x.split("=", 1)[1].strip())
              for x in a.labels.split(",") if x.strip()]
    bases = [x.strip() for x in a.only.split(",") if x.strip()]
    lines = [u"# 本地出图 · 逐轮梯子 vs 范例（同一把尺）", "",
             u"- 范例：`%s`（视频 limited）｜本地：PNG full｜IRE 两边都是显示归一，可比"
             % os.path.basename(a.ref_json),
             u"- 每个后缀＝一轮，**每轮只动一根轴**：一轮原词｜二轮 `b` 只加明度词｜"
             u"三轮 `c` 只加发光体与雾｜三轮 `d` 在 c 上只加去饱和。种子四组一致（配对）",
             u"",
             u"| 号 | 项 | 范例区间 | " + u" | ".join(l for l, _ in labels) + u" | 最新一轮进区间? |",
             u"|--|--|--|" + "---|" * (len(labels) + 2)]
    for base in bases:
        shot = int(re.search(r"K(\d)", base).group(1))
        ref = ref_range(a.ref_json, shot)
        if not ref:
            print("没有镜 %d 的数据" % shot)
            continue
        rows = {suf: data.get(base, {}).get(suf) for _, suf in labels}
        print("\n=== %s ↔ 镜%d ===" % (base, shot))
        for label, key, fmt in ITEMS:
            rv = ref.get(key)
            if not rv:
                continue
            lo, hi = rv
            cells, last = [], None
            for _, suf in labels:
                r = rows.get(suf)
                v = r.get(key) if r else None
                if v in (None, "", "None"):
                    cells.append(u"—")
                else:
                    cells.append(fmt % float(v))
                    last = float(v)
            verdict = u"—" if last is None else (u"✓ 进" if lo <= last <= hi else
                                                u"✗ 差 %.1f" % abs(last - (hi if last > hi else lo)))
            print(u"  %-12s 范例 %-14s｜%s｜%s" % (
                label, u"%s～%s" % (fmt % lo, fmt % hi), u"｜".join(cells), verdict))
            lines.append(u"| %s | %s | %s～%s | %s | %s |" % (
                base, label, fmt % lo, fmt % hi, u" | ".join(cells), verdict))
    if a.out:
        io.open(a.out, "w", encoding="utf-8").write(u"\n".join(lines) + u"\n")
        print(u"\n梯子对照表：%s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
