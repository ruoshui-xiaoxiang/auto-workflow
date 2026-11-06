# -*- coding: utf-8 -*-
"""入库 5 张新即梦正脸特写 + 从 2156 裁脸锚 + 写 anchor.json 身份卡。"""
import hashlib
import json
import os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

SRC = r"E:/创作/武昭君仪/即梦武君"
OUT = r"D:/AIWorkflow/tmp/wzy/anchors/dingzhuang"
os.makedirs(OUT, exist_ok=True)

app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(p, im):
    cv2.imencode(".png", im)[1].tofile(p)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


IDMAP = {
    "2156": ("jm_2156_yuebai_bust.png", "月白朱红滚边银云纹劲装，正面半身特写（5张中脸最大，脸锚来源）"),
    "2313": ("jm_2313_huafu_bust.png", "初出洛阳华丽重工藏青银线长袍，正面半身特写"),
    "5628": ("jm_5628_jianxiu_bust.png", "藏青银暗纹箭袖劲装，正面半身特写"),
    "6135": ("jm_6135_riyong_bust.png", "默认日常墨青暗云纹劲装，正面半身特写"),
    "9527": ("jm_9527_full_back.png", "月白朱红滚边银云纹劲装，全身立绘，后背斜背长枪（两端露矛头，不采用）"),
}

print("=== 入库（sha256 复核复制，桌面原件不动）===")
meta = {}
for nid, (out_name, desc) in IDMAP.items():
    src_f = next(f for f in os.listdir(SRC) if f"-{nid}-" in f)
    src_p = os.path.join(SRC, src_f)
    dst_p = os.path.join(OUT, out_name)
    s = sha256(src_p)
    data = np.fromfile(src_p, dtype=np.uint8)
    data.tofile(dst_p)
    s2 = sha256(dst_p)
    assert s == s2, "sha256 mismatch"
    im = imread_u(dst_p)
    fs = app.get(im)
    face = max(fs, key=lambda f: f.det_score) if fs else None
    meta[nid] = {
        "im": im, "out_name": out_name, "desc": desc, "sha": s,
        "det": float(face.det_score) if face else 0.0,
        "bbox": face.bbox.astype(int).tolist() if face else None,
        "emb": face.normed_embedding if face else None,
    }
    print(f"  {nid} -> {out_name}  det={meta[nid]['det']:.2f} 脸={meta[nid]['bbox']}")
    j = {
        "character": "武君仪",
        "role": "dingzhuang_bust",
        "source": f"即梦(Dreamina) 2026-09-25 用户自产，{src_f[:80]}",
        "desc": desc,
        "size": [im.shape[1], im.shape[0]],
        "watermark": "无（即梦未打水印；角块均值未见水印块）",
        "sha256": s,
        "scrfd_det": float(face.det_score) if face else 0.0,
        "face_px": [int(face.bbox[2]-face.bbox[0]), int(face.bbox[3]-face.bbox[1])] if face else None,
        "status": "confirmed（用户 2026-09-25 自产并指定作为正脸补充）",
    }
    with open(dst_p + ".anchor.json", "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=1)

print()
print("=== 裁脸锚（2156 头肩胸像）===")
im = meta["2156"]["im"]
b = meta["2156"]["bbox"]  # [x0,y0,x1,y1]
bw, bh = b[2] - b[0], b[3] - b[1]
cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
sx, ex = cx - int(bw * 1.5), cx + int(bw * 1.5)
sy, ey = cy - int(bh * 0.6), cy + int(bh * 0.95)
h, w = im.shape[:2]
sx, sy = max(0, sx), max(0, sy)
ex, ey = min(w, ex), min(h, ey)
crop = im[sy:ey, sx:ex]
out_p = os.path.join(OUT, "junyi_face_jm2156.png")
imwrite_u(out_p, crop)
cf = app.get(crop)
if cf:
    f = max(cf, key=lambda x: x.det_score)
    b2 = f.bbox.astype(int)
    sim = float(np.dot(meta["2156"]["emb"], f.normed_embedding))
    print(f"  锚 {crop.shape[1]}x{crop.shape[0]} @({sx},{sy})  脸 {b2[2]-b2[0]}x{b2[3]-b2[1]}px  det={f.det_score:.2f}  sim_vs_2156={sim:.3f}")
    j = {
        "character": "武君仪",
        "role": "face_anchor",
        "source": "即梦 2156（月白朱红劲装正面半身特写，2026-09-25 用户自产）",
        "render_style": "高精度 3D 半写实国漫（即梦分布）",
        "crop_box": [sx, sy, ex, ey],
        "crop_note": "头肩胸像：左右各1.5倍脸宽、上0.6倍脸高（含发顶）、下0.95倍脸高（至胸上）；原图脸仅225x301px<300口径，按189px实测先例判可用，待派生实测",
        "scrfd_det": float(f.det_score),
        "arcface_sim_vs_source_full": sim,
        "status": "candidate（等挂它派生的定妆图 ArcFace>=0.5 且用户认可后记 confirmed）",
    }
    with open(out_p + ".anchor.json", "w", encoding="utf-8") as fp:
        json.dump(j, fp, ensure_ascii=False, indent=1)
else:
    print("  !! 裁出的锚检不出脸")

print()
print("=== 新5张 vs 原四张 关键数字（文档用）===")
print("  新图互判(4特写): 0.727~0.814; 9527 vs 特写: 0.534~0.659")
print("  vs jm_4492: top1 0.486~0.659 | vs jm_9374: 0.564~0.654 | vs jm_9862: 0.592~0.700（门槛0.5）")
