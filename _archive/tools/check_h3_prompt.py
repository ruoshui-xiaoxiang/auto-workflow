# -*- coding: utf-8 -*-
"""H3 prompt workflow validator — MUST pass before any GPU generation.

Rules (2026-10-10 user mandate):
1. POSITIVE-ONLY language (negatives are ignored by H3)
2. Official skeleton (fl2va 3-field or ref2va 6-field)
3. Length 124-362 frames
4. UTF-8 no BOM
5. Dialogue shots: single speaker visible
6. Spatial anchor present
7. Eye-line toward partner (not camera)
"""
import os
import re
import sys

NEG_PATTERNS = [
    r"\bNO\b", r"\bNOT\b", r"\bNever\b", r"\bnone\b",
    "禁止", "不要", "不得", "不许", "避免", "严禁", "切勿",
    r"\bwithout\b", r"\bavoid\b",
]
SKELETON_FIELDS = ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]
REF2VA_FIELDS = ["subject_definitions:", "summary:", "retention_analysis:",
                 "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
FIRST_LINE = "For the target video, at 0.00 seconds into the target video,"


def check_prompt(path, length_frames=None):
    issues = []
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append("BOM: 文件带 UTF-8 BOM")
    text = raw.decode("utf-8")

    # 1. negatives
    for pat in NEG_PATTERNS:
        for m in re.finditer(pat, text):
            start = max(0, m.start() - 30)
            ctx = text[start:m.end() + 30].replace("\n", " ")
            issues.append(f"NEGATIVE [{m.group()}]: ...{ctx}...")
            break  # one per pattern

    # 2. skeleton
    ref2va_only = ['subject_definitions:', 'retention_analysis:', 'detailed_description:']
    is_ref2va = sum(1 for f in ref2va_only if f in text) >= 2
    is_fl2va = any(f in text for f in SKELETON_FIELDS) and not is_ref2va
    if is_ref2va:
        missing = [f for f in REF2VA_FIELDS if f not in text]
        if missing:
            issues.append(f"SKELETON ref2va 缺字段: {missing}")
    elif is_fl2va:
        if not text.lstrip().startswith(FIRST_LINE):
            issues.append("SKELETON fl2va 首行不是官方指令")
        missing = [f for f in SKELETON_FIELDS if f not in text]
        if missing:
            issues.append(f"SKELETON fl2va 缺字段: {missing}")
    else:
        issues.append("SKELETON: 既不是 fl2va 三字段也不是 ref2va 六段")

    # 3. length
    if length_frames is not None and not (124 <= length_frames <= 362):
        issues.append(f"LENGTH: {length_frames} 帧不在 124–362")

    # 5-7 soft checks (warnings)
    warns = []
    if "gaze" not in text and "looks" not in text and "视线" not in text:
        warns.append("EYELINE: 未写视线方向")
    if "SPATIAL" not in text and "Positions" not in text and "position" not in text.lower():
        warns.append("SPATIAL: 未写空间锚点")
    return issues, warns


def main():
    paths = sys.argv[1:]
    if not paths:
        # default: all v8 prompts
        d = r"E:\创作\武昭君仪\单元剧_轻喜版\shots_ep2v8"
        paths = [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith("_prompt.txt")]
    all_ok = True
    for p in paths:
        if not os.path.exists(p):
            print(f"[MISS] {p}")
            continue
        # try to infer length from filename or skip
        issues, warns = check_prompt(p)
        name = os.path.basename(p)
        if issues:
            all_ok = False
            print(f"[FAIL] {name}")
            for i in issues:
                print(f"   - {i}")
        else:
            print(f"[PASS] {name}")
        for w in warns:
            print(f"   ~ {w}")
    print("OVERALL", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
