#!/usr/bin/env python3
"""Measure whether the LoRA collapses face variation across seeds.

Pipeline: Haar face detect -> aligned crop -> 160x160 normalised descriptor ->
  A) within-group mean pairwise distance (higher = more diverse faces)
  B) same-seed LoRA-vs-base distance (how much the LoRA actually moves the face)

Caveat: pixel-space distance also carries lighting/pose, so A is a relative
comparison between LoRA and base under identical prompts/seeds, not an absolute
identity metric.
"""

import argparse
import sys
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

OUT = Path("D:/AIWorkflow/tmp/staging")
CANDIDATES = []
try:
    CANDIDATES.append(Path(cv2.data.haarcascades))
except AttributeError:
    pass
CANDIDATES += [
    Path("D:/AIWorkflow/training/toolkits/ai-toolkit/.venv/Lib/site-packages/cv2/data"),
    Path("C:/Users/若水/AppData/Local/Programs/Python/Python312/Lib/site-packages/cv2/data"),
]
NAME = "haarcascade_frontalface_default.xml"
CASCADE = next((d / NAME for d in CANDIDATES if (d / NAME).exists()), None)
SIZE = 160


def load(path: Path):
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot decode {path}")
    return img


def face_crop(img, cascade):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(int(img.shape[0] * 0.08),) * 2)
    if len(faces):
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        pad = int(0.15 * max(w, h))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(img.shape[1], x + w + pad), min(img.shape[0], y + h + pad)
        crop = img[y0:y1, x0:x1]
    else:
        # fallback: upper-centre region where a portrait face usually sits
        h, w = img.shape[:2]
        crop = img[int(h * 0.10):int(h * 0.55), int(w * 0.28):int(w * 0.72)]
    crop = cv2.resize(crop, (SIZE, SIZE))
    desc = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    desc = (desc - desc.mean()) / (desc.std() + 1e-6)
    return desc, len(faces) > 0


def mean_pairwise_cos_dist(items):
    dists = []
    for (sa, va), (sb, vb) in combinations(items, 2):
        va, vb = va.flatten(), vb.flatten()
        dists.append(1.0 - float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb))))
    return float(np.mean(dists)), dists


def main():
    if CASCADE is None:
        print(f"{NAME} not found, tried: " + ", ".join(str(d) for d in CANDIDATES))
        return 1
    cascade = cv2.CascadeClassifier(str(CASCADE))
    if cascade.empty():
        print("failed to load haar cascade")
        return 1

    ap = argparse.ArgumentParser()
    ap.add_argument("--lora-prefix", default="div_lora_")
    ap.add_argument("--base-prefix", default="div_base_")
    ap.add_argument("--strength-tag", default="",
                    help="suffix on the LoRA filename, e.g. '_s11' -> div_lora_11_s11")
    ap.add_argument("seeds", nargs="*", type=int)
    args = ap.parse_args()
    seeds = args.seeds or [11, 22, 33, 44]

    lora_items, base_items, paired, lora_all = [], [], [], []
    for seed in seeds:
        lp = next(iter(OUT.glob(f"{args.lora_prefix}{seed}{args.strength_tag}_*.png")), None)
        bp = next(iter(OUT.glob(f"{args.base_prefix}{seed}_*.png")), None)
        ld = face_crop(load(lp), cascade)[0] if lp else None
        bd = face_crop(load(bp), cascade)[0] if bp else None
        if ld is not None:
            lora_all.append((seed, ld))
        if ld is None or bd is None:
            print(f"  seed {seed}: {'lora' if ld is None else ''}"
                  f"{' & base' if bd is None else ''} missing -> unpaired")
            continue
        lora_items.append((seed, ld))
        base_items.append((seed, bd))
        paired.append((seed, 1.0 - float(np.dot(ld.flatten(), bd.flatten())
                                          / (np.linalg.norm(ld) * np.linalg.norm(bd)))))
        print(f"  seed {seed}: paired")

    if len(lora_items) < 2:
        print("not enough pairs")
        return 1

    ldiv, ldist = mean_pairwise_cos_dist(lora_items)
    bdiv, bdist = mean_pairwise_cos_dist(base_items)
    print("\n" + "=" * 60)
    print(f"paired seeds: {[s for s, _ in lora_items]}")
    print(f"face diversity across seeds  LoRA = {ldiv:.4f}   base = {bdiv:.4f}")
    print(f"  ratio LoRA/base = {ldiv / bdiv:.2f}  (<1 means LoRA makes faces more alike)")
    if len(lora_all) > len(lora_items):
        adiv, _ = mean_pairwise_cos_dist(lora_all)
        print(f"LoRA diversity over all {len(lora_all)} seeds = {adiv:.4f}")
    print(f"same-seed LoRA shift on face region: "
          + ", ".join(f"seed{s}={d:.4f}" for s, d in paired))
    print(f"  mean shift = {np.mean([d for _, d in paired]):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
