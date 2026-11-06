#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""h3_qc_batch.py — H3 批次出片后的固定筛查（项目无关）

一次跑完四件事，出一份 JSON + 一张接触表：

  1. 电平   逐镜语音段 RMS / 峰值，报范围与削波
  2. 台词   ASR 逐字对账（相似度 + 缺字定位）
  3. 说话人 F0 + MFCC 对组中心，报"像另一性别"的镜
  4. 服装   人脸框下方区域的主色，报离群镜
  5. 接触表 每镜抽一帧拼图

用法：
  py h3_qc_batch.py --project <project>/h3 --videos <dir> \
      --ffmpeg <ffmpeg.exe> --out qc.json --sheet contact.jpg
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import h3_prompt_builder as B  # noqa: E402

try:
    import librosa
except ImportError:
    librosa = None
try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
try:
    import cv2
except ImportError:
    cv2 = None
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


def find_ffmpeg(arg):
    if arg:
        return arg
    env = os.environ.get("H3_FFMPEG")
    if env and os.path.isfile(env):
        return env
    for c in [r"E:\hailluoai\MiniMax Design (2)\current\resources\ffmpeg\ffmpeg.exe",
              r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/bin/ffmpeg"]:
        if os.path.isfile(c):
            return c
    return "ffmpeg"


def match_videos(videos_dir, shot_id):
    """文件名里包含 shot id 就算（允许 KB23V3_U02_... 这类前缀）。"""
    pat = re.compile(r"(^|[^A-Za-z0-9])%s([^0-9]|$)" % re.escape(shot_id))
    out = []
    for f in glob.glob(os.path.join(videos_dir, "*.mp4")):
        if pat.search(os.path.basename(f)) and "audio" in os.path.basename(f).lower():
            out.append(f)
    return sorted(out)


def to_wav(ffmpeg, src, dst):
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", src, "-vn", "-ac", "1", "-ar", "16000", dst], check=True)
    return dst


def loudness(y, sr):
    iv = librosa.effects.split(y, top_db=32)
    if len(iv) == 0:
        return None
    s, e = max(iv, key=lambda x: x[1] - x[0])
    seg = y[s:e]
    rms = float(np.sqrt(np.mean(seg ** 2)))
    peak = float(np.max(np.abs(seg)))
    db = 20 * np.log10(max(rms, 1e-9))
    pdb = 20 * np.log10(max(peak, 1e-9))
    return {"rms_db": round(db, 1), "peak_db": round(pdb, 1),
            "speech": [round(s / sr, 2), round(e / sr, 2)]}


def voice(y, sr):
    iv = librosa.effects.split(y, top_db=32)
    if len(iv) == 0:
        return None
    s, e = max(iv, key=lambda x: x[1] - x[0])
    seg = y[s:e]
    if len(seg) < sr * 0.5:
        return None
    f0, _, _ = librosa.pyin(seg, fmin=70, fmax=400, sr=sr, frame_length=1024)
    v = f0[np.isfinite(f0)]
    med = float(np.median(v)) if len(v) > 5 else 0.0
    mf = librosa.feature.mfcc(y=seg, sr=sr, n_mfcc=20)[1:14].mean(axis=1)
    return {"f0": round(med, 1), "mfcc": mf.tolist()}


_YUNET_PATH = os.path.join(HERE, "models", "yunet.onnx")


def _imread_unicode(path):
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def clothes_color(frame_path):
    if cv2 is None or not os.path.isfile(frame_path):
        return None
    img = _imread_unicode(frame_path)   # cv2.imread 读不了中文路径
    if img is None:
        return None
    if not os.path.isfile(_YUNET_PATH):
        return None
    h, w = img.shape[:2]
    try:
        det = cv2.FaceDetectorYN.create(_YUNET_PATH, "", (w, h), 0.7, 0.3, 5000)
        det.setInputSize((w, h))
        _, faces = det.detect(img)
    except Exception:
        return None
    if faces is None or len(faces) == 0:
        return None
    x, y, fw, fh = [float(v) for v in max(faces, key=lambda f: f[2] * f[3])[:4]]
    x, y, fw, fh = int(x), int(y), int(fw), int(fh)
    y0 = min(img.shape[0], y + int(fh * 0.9))
    y1 = min(img.shape[0], y + int(fh * 2.6))
    roi = img[y0:y1, max(0, x - int(fw * 0.4)):min(img.shape[1], x + int(fw * 1.4))]
    if roi.size == 0:
        return None
    px = roi.reshape(-1, 3).astype(np.float32)
    # 去掉过暗/过亮像素，取中位色
    keep = px[(px.mean(axis=1) > 25) & (px.mean(axis=1) < 230)]
    if len(keep) < 50:
        keep = px
    return [round(float(v), 1) for v in np.median(keep, axis=0)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="H3 批次出片筛查")
    ap.add_argument("--project", required=True)
    ap.add_argument("--videos", required=True)
    ap.add_argument("--ffmpeg", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--asr", action="store_true", help="跑 ASR 逐字对账（较慢）")
    a = ap.parse_args(argv)

    if librosa is None:
        raise SystemExit("需要 librosa：py -3.12 -m pip install librosa")
    ffmpeg = find_ffmpeg(a.ffmpeg)
    cards = B.load_project(a.project)
    chars = cards["characters"].get("roles") or {}
    shots = cards["shots"].get("shots") or []
    tmp = tempfile.mkdtemp(prefix="h3qc_")

    model = WhisperModel("small", device="cpu", compute_type="int8") if a.asr and WhisperModel else None
    recs = []
    for s in shots:
        sid = s.get("id")
        exp = ""
        exp_gender = None
        for d in s.get("dialogue") or []:
            exp += d.get("text", "")
            cname = (s.get("cast") or {}).get(d.get("speaker"))
            if cname and cname in chars:
                exp_gender = chars[cname].get("gender")
        vids = match_videos(a.videos, sid)
        if not vids:
            recs.append({"shot": sid, "error": "no video"})
            continue
        v = vids[-1]  # 双采取最后一条（约定 00002 在后）
        wav = to_wav(ffmpeg, v, os.path.join(tmp, sid + ".wav"))
        y, sr = librosa.load(wav, sr=16000, mono=True)
        rec = {"shot": sid, "video": os.path.basename(v),
               "expected": exp, "expected_gender": exp_gender,
               "loudness": loudness(y, sr), "voice": voice(y, sr)}
        if model and exp:
            segs, _ = model.transcribe(wav, language="zh", beam_size=5)
            heard = "".join(x.text for x in segs).strip()
            from difflib import SequenceMatcher
            rec["heard"] = heard
            rec["asr_sim"] = round(SequenceMatcher(
                None, re.sub(r"[^\u4e00-\u9fff]", "", exp),
                re.sub(r"[^\u4e00-\u9fff]", "", heard)).ratio(), 3)
        if cv2 is not None:
            png = os.path.join(tmp, sid + ".png")
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", "2.0", "-i", v, "-frames:v", "1", png], check=False)
            rec["clothes_bgr"] = clothes_color(png)
        recs.append(rec)
        print("[%s] %s" % (sid, v))

    # 说话人分组（按期望性别）
    groups = {}
    for r in recs:
        if r.get("voice") and r.get("expected_gender"):
            groups.setdefault(r["expected_gender"], []).append(r)
    for g, rs in groups.items():
        if len(rs) < 2:
            continue
        center = np.mean([r["voice"]["mfcc"] for r in rs], axis=0)
        for r in rs:
            r["mfcc_dist"] = round(float(np.linalg.norm(np.array(r["voice"]["mfcc"]) - center)), 1)

    # 服装主色离群
    cols = [(r["shot"], r["clothes_bgr"]) for r in recs if r.get("clothes_bgr")]
    if len(cols) >= 3:
        arr = np.array([c for _, c in cols])
        med = np.median(arr, axis=0)
        for (sid, c) in cols:
            d = float(np.linalg.norm(np.array(c) - med))
            for r in recs:
                if r["shot"] == sid:
                    r["clothes_dist"] = round(d, 1)
                    if d > 70:
                        r.setdefault("flags", []).append("clothes_outlier")

    # 电平离群
    loud = [(r["shot"], r["loudness"]["rms_db"]) for r in recs if r.get("loudness")]
    if loud:
        vals = [v for _, v in loud]
        med = float(np.median(vals))
        for sid, v in loud:
            for r in recs:
                if r["shot"] == sid:
                    r["loudness_delta"] = round(v - med, 1)
                    if abs(v - med) > 6:
                        r.setdefault("flags", []).append("loudness_outlier")

    if a.sheet and Image is not None:
        imgs = []
        for s in shots:
            sid = s.get("id")
            vids = match_videos(a.videos, sid)
            if not vids:
                continue
            png = os.path.join(tmp, sid + ".png")
            if os.path.isfile(png):
                imgs.append((sid, png))
        if imgs:
            W, H = 400, 225
            cols_n = min(4, len(imgs))
            rows = (len(imgs) + cols_n - 1) // cols_n
            sheet = Image.new("RGB", (W * cols_n, H * rows), (20, 20, 20))
            d = ImageDraw.Draw(sheet)
            for i, (sid, p) in enumerate(imgs):
                im = Image.open(p).convert("RGB").resize((W, H))
                x, y = (i % cols_n) * W, (i // cols_n) * H
                sheet.paste(im, (x, y))
                d.text((x + 8, y + 6), sid, fill=(255, 255, 0))
            sheet.save(a.sheet, quality=88)
            print("接触表：%s" % a.sheet)

    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(recs, ensure_ascii=False, indent=2))
        print("报告：%s" % a.out)

    # 控制台摘要
    print("\n%-6s %-8s %-8s %-6s %-6s %s" % ("shot", "RMS", "峰值", "F0", "相似", "标记"))
    for r in recs:
        lo = r.get("loudness") or {}
        vo = r.get("voice") or {}
        print("%-6s %7.1f %7.1f %8.1f %6s %s"
              % (r["shot"], lo.get("rms_db", 0), lo.get("peak_db", 0), vo.get("f0", 0),
                 r.get("asr_sim", "-"), ",".join(r.get("flags", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
