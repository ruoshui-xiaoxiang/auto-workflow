"""Face detection and cropping using OpenCV 5.x FaceDetectorYN (YuNet)."""
import cv2
import numpy as np
import os
import glob
import sys

SRC_DIR = sys.argv[1] if len(sys.argv) > 1 else r"D:\AIWorkflow\training\datasets\无音\wuyin_lora_candidates"
DST_DIR = sys.argv[2] if len(sys.argv) > 2 else r"D:\AIWorkflow\training\datasets\无音\wuyin_lora_faces"
TARGET_SIZE = int(sys.argv[3]) if len(sys.argv) > 3 else 768

os.makedirs(DST_DIR, exist_ok=True)

# Create YuNet face detector
MODEL_PATH = r"D:\AIWorkflow\models\face\face_detection_yunet_2023mar.onnx"
detector = cv2.FaceDetectorYN.create(MODEL_PATH, "", (320, 320), 0.5, 0.3, 5000)

def detect_face(img):
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(img)
    if faces is None or len(faces) == 0:
        return None
    # Sort by face area, take largest
    faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
    x, y, fw, fh = faces[0][:4]
    return (int(x + fw/2), int(y + fh/2), int(fw), int(fh))

def crop_face(img_path, dst_dir, target_size):
    img = cv2.imdecode(np.fromfile(img_path, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return False

    face = detect_face(img)
    basename = os.path.splitext(os.path.basename(img_path))[0]

    if face is None:
        print(f"  [NO FACE] {os.path.basename(img_path)}")
        # Save full image, center-cropped to square
        h, w = img.shape[:2]
        side = min(w, h)
        x1 = (w - side) // 2
        y1 = (h - side) // 2
        cropped = img[y1:y1+side, x1:x1+side]
        resized = cv2.resize(cropped, (target_size, target_size), interpolation=cv2.INTER_LANCZOS4)
        out_path = os.path.join(dst_dir, f"{basename}_noface.png")
        cv2.imencode('.png', resized)[1].tofile(out_path)
        return True

    cx, cy, fw, fh = face
    face_size = max(fw, fh)

    # Crop ratio 2.0 x 2.5 around face center (head + shoulders)
    crop_w = int(face_size * 2.0)
    crop_h = int(face_size * 2.5)

    h, w = img.shape[:2]
    crop_w = min(crop_w, w)
    crop_h = min(crop_h, h)

    x1 = max(0, cx - crop_w // 2)
    y1 = max(0, cy - crop_h // 2)
    x2 = min(w, x1 + crop_w)
    y2 = min(h, y1 + crop_h)

    cropped = img[y1:y2, x1:x2]
    ch, cw = cropped.shape[:2]

    # Resize so the longer side = target_size
    scale = target_size / max(cw, ch)
    resized = cv2.resize(cropped, (int(cw*scale), int(ch*scale)), interpolation=cv2.INTER_LANCZOS4)

    out_path = os.path.join(dst_dir, f"{basename}_face.png")
    cv2.imencode('.png', resized)[1].tofile(out_path)
    print(f"  [OK] {os.path.basename(img_path):40s} face={face_size:4d}px -> {resized.shape[1]}x{resized.shape[0]}")
    return True

# Process only root-level files (user's selection)
extensions = ["*.png", "*.jpg", "*.jpeg", "*.webp"]
files = []
for ext in extensions:
    files.extend(glob.glob(os.path.join(SRC_DIR, ext)))
# Filter to only files directly in SRC_DIR (not subdirectories)
src_norm = os.path.normpath(os.path.abspath(SRC_DIR))
files = [f for f in files if os.path.normpath(os.path.dirname(os.path.abspath(f))) == src_norm]
files.sort()

print(f"Processing {len(files)} images | Output: {DST_DIR} | Target: {TARGET_SIZE}px")
print()

success = 0
for f in files:
    if crop_face(f, DST_DIR, TARGET_SIZE):
        success += 1

print(f"\nDone: {success}/{len(files)}")
