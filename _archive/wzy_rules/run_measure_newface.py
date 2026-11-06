# -*- coding: utf-8 -*-
'''即梦新脸锚 jm_face_v2 测量：SCRFD 框脸 + ArcFace vs jm_2156 + 四角烧字扫描 + 领口色域。'''
import numpy as np
import cv2, json, io
from insightface.app import FaceAnalysis

NEW = r'D:/AIWorkflow/tmp/wzy/jm_face_regen/jm_face_v2_raw.png'
REF = [r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/jm_2156_yuebai_bust.png',
       r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/jm_2313_huafu_bust.png',
       r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/jm_5628_jianxiu_bust.png',
       r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/jm_6135_riyong_bust.png']

def imread(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
app.prepare(ctx_id=-1, det_size=(640, 640))

def emb(img):
    fs = app.get(img)
    if not fs:
        return None
    f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
    return f

img = imread(NEW)
H, W = img.shape[:2]
f = emb(img)
out = {'size': [W, H]}
if f is None:
    out['face'] = None
else:
    x1, y1, x2, y2 = [int(v) for v in f.bbox]
    fw, fh = x2-x1, y2-y1
    out['face'] = {'box': [x1, y1, x2, y2], 'w': fw, 'h': fh, 'det': float(f.det_score)}
    # 裁脸锚：脸心左右各 1.35 倍脸宽、上下各延
    cx, cy = (x1+x2)//2, (y1+y2)//2
    m = int(fw*1.35)
    x1c, x2c = max(0, cx-m), min(W, cx+m)
    y1c, y2c = max(0, cy-int(fh*1.15)), min(H, cy+int(fh*1.85))
    crop = img[y1c:y2c, x1c:x2c]
    out['crop'] = [x1c, y1c, x2c, y2c]
    # 领口/肩部色域：脸底往下 0.5~1.5 脸高那条带
    band = img[min(H, y2+int(fh*0.3)):min(H, y2+int(fh*1.6)), max(0, cx-int(fw*1.8)):min(W, cx+int(fw*1.8))]
    lab = cv2.cvtColor(band, cv2.COLOR_BGR2LAB).astype(np.float32)
    out['collar_lab_mean'] = [round(v, 1) for v in lab.reshape(-1, 3).mean(0)]
    out['collar_bright_ratio'] = round(float((lab[:, :, 0] > 200).mean()), 4)
    out['collar_dark_ratio'] = round(float((lab[:, :, 0] < 80).mean()), 4)
    # 四角烧字扫描：每角 240x240
    corners = {'tl': img[:240, :240], 'tr': img[:240, W-240:], 'bl': img[H-240:, :240], 'br': img[H-240:, W-240:]}
    out['corners'] = {}
    for k, c in corners.items():
        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        out['corners'][k] = {'lap_var': round(float(cv2.Laplacian(g, cv2.CV_64F).var()), 1)}
    # 裁脸锚落盘
    cv2.imencode('.png', crop)[1].tofile(r'D:/AIWorkflow/tmp/wzy/jm_face_regen/jm_face_v2_crop.png')
    e_new = f.normed_embedding

# 与四张即梦正脸互判
out['arcface_vs'] = {}
for r in REF:
    ri = imread(r)
    rf = emb(ri)
    if rf is None:
        out['arcface_vs'][r.split('/')[-1]] = None
        continue
    s = float(np.dot(e_new, rf.normed_embedding))
    out['arcface_vs'][r.split('/')[-1]] = round(s, 4)

io.open(r'D:/AIWorkflow/tmp/wzy/jm_face_regen/measure.json', 'w', encoding='utf-8').write(
    json.dumps(out, ensure_ascii=False, indent=1, default=float))
print(json.dumps(out, ensure_ascii=False, indent=1, default=float))
