#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""h3_crop.py — 按项目卡里的 crop 裁切参考图（项目无关）

裁切框写在 characters.yaml / scenes.yaml 的 reference.crop 上，这里只负责执行。
输出 <out-dir>/<角色或场景名>.png，供镜头表直接引用。

用法：
  py h3_crop.py --project <project>/h3 --out-dir <project>/h3/assets/crops
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402
import h3_prompt_builder as B  # noqa: E402


def crop_one(src, crop, dst):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if crop:
        x0, y0, x1, y1 = [float(v) for v in crop]
        box = (int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))
        im = im.crop(box)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, quality=95)
    return im.size


def main(argv=None):
    ap = argparse.ArgumentParser(description="按卡裁切参考图")
    ap.add_argument("--project", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)

    cards = B.load_project(a.project)
    proj = cards["dir"]
    plan = []
    for name, c in (cards["characters"].get("roles") or {}).items():
        plan.append((name, c.get("reference") or {}))
    for name, c in (cards["scenes"].get("scenes") or {}).items():
        plan.append((name, c.get("reference") or {}))

    bad = 0
    for name, ref in plan:
        src = ref.get("file")
        if not src:
            continue
        src = src if os.path.isabs(src) else os.path.normpath(os.path.join(proj, src))
        if not os.path.isfile(src):
            print("[MISS] %s -> %s" % (name, src))
            bad += 1
            continue
        dst = os.path.join(a.out_dir, name + ".png")
        size = crop_one(src, ref.get("crop"), dst)
        print("[ OK ] %-10s %s  %dx%d" % (name, dst, size[0], size[1]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
