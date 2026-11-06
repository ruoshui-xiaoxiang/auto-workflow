#!/usr/bin/env python3
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   一次性人工过目工具：把通过 CLIP 审计的训练图平铺成一个夹子供人眼挑，
#   源文件一个不删，落 `asian_faces_review_manifest.json` 记录每张被丢的原因。
#   ⚠ 它**不是成片审片通路**（那是新加的三分类评审工具）——名字里的 review 指训练集筛选，
#     别把它当成片评审通路，也别拿它的产物当交付。
#   为什么没有调用方：LoRA 训练批是手动跑的（人决定何时重筛），所以永远不会出现在链路上。
"""Build a single flat folder of surviving training images for manual eyeballing.

Drops CLIP-audited contamination and images the trainer sees below 0.4 MP
(bucket_no_upscale semantics). Nothing is deleted -- source stays intact, and
asian_faces_review_manifest.json records every drop with its reason.
"""

import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

SRC = Path("D:/AIWorkflow/training/datasets/asian_faces_kohya_960")
DST = Path("D:/AIWorkflow/training/datasets/asian_faces_review")
DST_CLIP = Path("D:/AIWorkflow/training/datasets/_dropped_clip")
AUDIT = Path("D:/AIWorkflow/training/datasets/audit_report.json")
MANIFEST = Path("D:/AIWorkflow/training/datasets/asian_faces_review_manifest.json")

MIN_BUCKET_MP = 0.4
RESO_STEPS = 64
MAX_SIDE = 960

REGION_BY_CAPTION = {
    "古风": "cn",
    "日本": "jp",
    "韩国": "kr",
}


def bucket_for(w, h, steps=RESO_STEPS, max_side=MAX_SIDE):
    scale = min(1.0, max_side / max(w, h))
    bw = max(steps, int(w * scale) // steps * steps)
    bh = max(steps, int(h * scale) // steps * steps)
    return bw, bh


def region_of(caption):
    for key, code in REGION_BY_CAPTION.items():
        if key in caption:
            return code
    return "xx"


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    bad = {str(Path(s["path"])): s.get("top_label", "?") for s in audit["suspicious"]}

    keep, drops = [], defaultdict(list)
    for img in sorted(list(SRC.rglob("*.jpg")) + sorted(SRC.rglob("*.png"))):
        key = str(img)
        if key in bad:
            drops["contaminated"].append((img, bad[key]))
            continue
        txt = img.with_suffix(".txt")
        caption = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
        try:
            with Image.open(img) as im:
                w, h = im.size
        except Exception as e:
            drops["unreadable"].append((img, str(e)))
            continue
        bw, bh = bucket_for(w, h)
        if bw * bh / 1e6 < MIN_BUCKET_MP:
            drops["lowres"].append((img, f"{bw}x{bh}={bw * bh / 1e6:.2f}MP"))
            continue
        keep.append((img, caption, (w, h), (bw, bh)))

    DST.mkdir(parents=True, exist_ok=True)
    for old in DST.glob("*.jpg"):
        old.unlink()

    # group by region -> person, and number sequentially so rejects can be
    # reported by index
    order = sorted(keep, key=lambda k: (region_of(k[1]), k[0].parent.name, k[0].name))
    entries = []
    for i, (img, caption, orig, bucket) in enumerate(order, 1):
        person = img.parent.name.split("_", 1)[-1]
        name = f"{i:03d}_{region_of(caption)}__{person}__{img.stem}.jpg"
        shutil.copy2(img, DST / name)
        entries.append({
            "idx": i,
            "file": name,
            "src": str(img),
            "person": person,
            "region": region_of(caption),
            "caption": caption,
            "orig_wh": list(orig),
            "bucket_wh": list(bucket),
        })

    kept_people = {e["person"] for e in entries}
    all_people = {p.name.split("_", 1)[-1] for p in SRC.iterdir() if p.is_dir()}
    per_person = Counter(e["person"] for e in entries)

    if DST_CLIP.exists():
        shutil.rmtree(DST_CLIP)
    for img, label in drops["contaminated"]:
        sub = DST_CLIP / label.replace(" ", "_").replace("/", "-")
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, sub / f"{img.parent.name}__{img.name}")

    MANIFEST.write_text(json.dumps({
        "source": str(SRC),
        "min_bucket_mp": MIN_BUCKET_MP,
        "kept": len(entries),
        "dropped": {k: len(v) for k, v in drops.items()},
        "drop_detail": {k: [[str(p), r] for p, r in v] for k, v in drops.items()},
        "entries": entries,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"total source images : {len(keep) + sum(len(v) for v in drops.values())}")
    print(f"kept                : {len(entries)}")
    for k in ("contaminated", "lowres", "unreadable"):
        print(f"  dropped {k:14s}: {len(drops[k])}")
    print(f"\npeople kept         : {len(kept_people)} / {len(all_people)}")
    lost = sorted(all_people - kept_people)
    if lost:
        print(f"  lost entirely ({len(lost)}): {', '.join(lost)}")
    thin = sorted(p for p, n in per_person.items() if n < 3)
    print(f"  with <3 images ({len(thin)}): {', '.join(thin)}")
    print(f"\nreview folder : {DST}")
    print(f"clip spot-check: {DST_CLIP}")
    print(f"manifest      : {MANIFEST}")
    mp = [e["bucket_wh"][0] * e["bucket_wh"][1] / 1e6 for e in entries]
    mp.sort()
    print(f"\nkept bucket area: median {mp[len(mp) // 2]:.2f} MP "
          f"min {mp[0]:.2f} max {mp[-1]:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
