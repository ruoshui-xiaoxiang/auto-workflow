"""Deduplicate images using perceptual hash (pHash)."""
import cv2
import numpy as np
import os
import glob
import sys
from collections import defaultdict

SRC_DIR = sys.argv[1] if len(sys.argv) > 1 else r"E:\图像影音资源池\无音\素材\wuyin_lora_faces_video"
DST_DIR = sys.argv[2] if len(sys.argv) > 2 else r"D:\AIWorkflow\training\datasets\无音\wuyin_lora_faces_video_deduped"
THRESHOLD = int(sys.argv[3]) if len(sys.argv) > 3 else 8  # Hamming distance threshold

os.makedirs(DST_DIR, exist_ok=True)

def phash(img, size=16):
    """Compute perceptual hash."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)
    # Compute DCT
    dct = cv2.dct(np.float32(resized))
    # Take top-left 8x8 (low frequencies)
    dct_low = dct[:8, :8]
    # Flatten and compute median
    flat = dct_low.flatten()
    median = np.median(flat)
    # Binary hash
    hash_bits = (flat > median).astype(np.uint8)
    return hash_bits

def hamming(h1, h2):
    return np.sum(h1 != h2)

# Load all images and compute hashes
files = sorted(glob.glob(os.path.join(SRC_DIR, "*.png")))
print(f"Total images: {len(files)}")

hashes = []
for f in files:
    img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        continue
    h = phash(img)
    hashes.append((f, h))

print(f"Valid images: {len(hashes)}")

# Greedy deduplication: keep first, skip similar
kept = []
skipped = 0
for f, h in hashes:
    is_dup = False
    for _, kh in kept:
        if hamming(h, kh) <= THRESHOLD:
            is_dup = True
            break
    if is_dup:
        skipped += 1
    else:
        kept.append((f, h))
        basename = os.path.basename(f)
        dst = os.path.join(DST_DIR, basename)
        # Copy file
        with open(f, 'rb') as src_f:
            data = src_f.read()
        with open(dst, 'wb') as dst_f:
            dst_f.write(data)

print(f"Kept: {len(kept)}")
print(f"Skipped (duplicates): {skipped}")
print(f"Output: {DST_DIR}")
