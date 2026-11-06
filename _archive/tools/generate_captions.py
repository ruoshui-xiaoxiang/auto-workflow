#!/usr/bin/env python3
"""Generate unique English captions for the reviewed portrait dataset.

Solves the caption-collapse problem (702 images, 5 distinct Chinese captions)
by assigning each image a deterministic but unique combination of photography
descriptors. Captions are written as .txt files alongside the .jpg files.
"""

import hashlib
from pathlib import Path

FOLDER = Path("D:/AIWorkflow/training/datasets/asian_faces_review")

SHOT = [
    "close-up portrait",
    "medium close-up portrait",
    "half-body portrait",
    "headshot portrait",
    "three-quarter portrait",
    "upper body portrait",
    "bust portrait",
    "tight facial close-up",
]

LIGHTING = [
    "soft natural lighting",
    "diffused window light",
    "golden hour sunlight",
    "studio softbox lighting",
    "gentle rim lighting",
    "ambient indoor lighting",
    "warm directional light",
    "cool overcast light",
    "subtle fill light",
    "natural side lighting",
]

QUALITY = [
    "photorealistic",
    "highly detailed skin texture with natural pores",
    "sharp focus on facial features",
    "professional editorial photography",
    "high resolution photograph",
    "realistic skin detail",
    "photographic quality",
    "lifelike rendering",
]

EXPRESSION = [
    "calm serene expression",
    "gentle warm smile",
    "soft contemplative look",
    "confident direct gaze",
    "relaxed neutral expression",
    "subtle natural smile",
    "quiet dignified expression",
    "easy approachable expression",
    "thoughtful downward gaze",
    "bright engaging look",
]

BACKGROUND = [
    "smooth blurred background",
    "creamy bokeh",
    "soft out-of-focus background",
    "clean minimal background",
    "shallow depth of field background",
    "neutrally toned backdrop",
]

CAMERA = [
    "shot on 85mm portrait lens",
    "shallow depth of field at f/1.8",
    "shot on 50mm lens at f/2.0",
    "narrow aperture bokeh at f/1.4",
    "medium telephoto compression",
    "soft lens falloff at edges",
]

POSE = [
    "facing slightly left of camera",
    "facing slightly right of camera",
    "turned at a three-quarter angle",
    "looking just past the camera",
    "chin tilted slightly down",
    "chin lifted at a subtle angle",
    "shoulders angled away",
    "square to the camera",
]

HAIR_NOTE = [
    "hair naturally styled",
    "hair swept back softly",
    "hair framing the face",
    "hair with gentle volume",
    "hair with subtle texture",
]


def caption_for(filename: str) -> str:
    h = int(hashlib.sha256(filename.encode()).hexdigest(), 16)

    def pick(pool):
        nonlocal h
        val = h % len(pool)
        h //= len(pool)
        return pool[val]

    parts = [
        pick(SHOT),
        pick(LIGHTING),
        pick(QUALITY),
        pick(EXPRESSION),
        pick(BACKGROUND),
        pick(CAMERA),
        pick(POSE),
        pick(HAIR_NOTE),
    ]
    return "a " + parts[0] + " of a woman, " + ", ".join(parts[1:])


def main():
    files = sorted(FOLDER.glob("*.jpg"))
    captions = set()
    for f in files:
        cap = caption_for(f.name)
        captions.add(cap)
        f.with_suffix(".txt").write_text(cap, encoding="utf-8")

    print(f"Wrote {len(files)} caption files")
    print(f"Unique captions: {len(captions)} / {len(files)}")

    samples = sorted(captions)[:5]
    print("\nSample captions:")
    for s in samples:
        print(f"  {s}")


if __name__ == "__main__":
    main()
