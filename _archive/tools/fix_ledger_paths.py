#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_ledger_paths.py — 修 E:\\创作\\无音项目\\ledger\\shots.csv 里的死链 path 列

背景：那份台账的 path 列硬编码指向 `C:\\Users\\若水\\Desktop\\无音项目\\图\\定妆\\*.jpg`，
该目录早已不在（项目迁到 E 盘、且即梦产物换了命名）。本脚本**不猜**：
按 basename 在 `E:\\创作\\无音项目\\图\\` 下搜索，
  恰好命中 1 个 → 改写为新路径
  命中多个      → 保留原值并标 AMBIGUOUS（附候选）
  命中 0 个     → 标 MISSING:<原值>（显式化，不再静默死链）

原文件先归档到池 MANIFEST 目录（沿用归档留痕惯例），再原地写回。

用法: py -3.12 fix_ledger_paths.py [--dry-run]
"""

import os, csv, io, shutil, argparse
from datetime import datetime

LEDGER = r"E:\创作\无音项目\ledger\shots.csv"
ASSET_ROOT = r"E:\创作\无音项目\图"
ARCHIVE = r"E:\图像影音资源池\_归档_MANIFEST"
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def index_assets():
    idx = {}
    for dp, dns, fns in os.walk(ASSET_ROOT):
        dns[:] = [d for d in dns if d not in ("__pycache__",)]
        for fn in fns:
            stem, ext = os.path.splitext(fn)
            if ext.lower() in IMG_EXT:
                idx.setdefault(stem, []).append(os.path.join(dp, fn))
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    with io.open(LEDGER, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys())
    idx = index_assets()

    fixed, amb, miss, ok = [], [], [], 0
    for r in rows:
        old = (r.get("path") or "").strip()
        if not old:
            continue
        if os.path.isfile(old):
            ok += 1
            continue
        stem = os.path.splitext(os.path.basename(old.replace("\\", "/")))[0]
        hits = idx.get(stem, [])
        if len(hits) == 1:
            r["path"] = hits[0].replace("\\", "/")
            fixed.append((old, r["path"]))
        elif len(hits) > 1:
            r["path"] = f"AMBIGUOUS:{old}"
            amb.append((old, hits))
        else:
            r["path"] = f"MISSING:{old}"
            miss.append(old)

    print(f"台账 {LEDGER}")
    print(f"  行数 {len(rows)}｜原路径有效 {ok}｜可修 {len(fixed)}｜歧义 {len(amb)}｜找不到 {len(miss)}")
    for o, n in fixed[:8]:
        print(f"    ✔ {os.path.basename(o)}  →  {n}")
    if len(fixed) > 8:
        print(f"    … 另有 {len(fixed)-8} 条")
    for o, h in amb[:5]:
        print(f"    ? 歧义 {os.path.basename(o)} → {len(h)} 个候选")
    for o in miss[:8]:
        print(f"    ✘ 找不到 {o}")

    if a.dry_run:
        print("\n[dry-run] 未写入")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    adir = os.path.join(ARCHIVE, stamp)
    os.makedirs(adir, exist_ok=True)
    shutil.copy2(LEDGER, os.path.join(adir, "shots_修复前.csv"))
    with io.open(LEDGER, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\n[fix] 已原地写回；修复前副本归档在 {adir}\\shots_修复前.csv")


if __name__ == "__main__":
    main()
