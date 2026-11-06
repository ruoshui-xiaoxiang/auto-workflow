# -*- coding: utf-8 -*-
'''量化"人物变白"：各图人脸区 Lab 统计 + 整图亮点比例。
对照链：jm_2156原脸锚 / jm_face_v2新脸锚 / jm_9862风格锚 / dz0b'漂移版D1 / dz0b2'三张'''
import numpy as np, cv2, json, io
from insightface.app import FaceAnalysis
import os
os.chdir(r'D:/AIWorkflow/tmp/wzy')

app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection'])
app.prepare(ctx_id=-1, det_size=(1024, 1024))

ITEMS = [
    ('jm_2156原脸锚', r'anchors/dingzhuang/jm_2156_yuebai_bust.png'),
    ('jm_face_v2新脸锚', r'jm_face_regen/jm_face_v2_raw.png'),
    ('jm_9862风格锚', r'anchors/dingzhuang/jm_9862_dual_look_labeled.png'),
    ('dz0b_D1漂移版', r'dz0b2/D1_raw.png'),
    ('dz0b2p_D1p', r"dz0b2p/D1'_raw.png"),
    ('dz0b2p_D2p', r"dz0b2p/D2'_raw.png"),
    ('dz0b2p_D3p', r"dz0b2p/D3'_raw.png"),
]

def imread(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

rows = []
for name, p in ITEMS:
    img = imread(p)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0]
    allL = L.reshape(-1)
    rec = {'name': name, 'size': list(img.shape[1::-1])}
    rec['all_L_mean'] = round(float(allL.mean()), 1)
    rec['all_bright_gt200_ratio'] = round(float((allL > 200).mean()), 4)
    rec['all_dark_lt80_ratio'] = round(float((allL < 80).mean()), 4)
    fs = app.get(img)
    if fs:
        f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
        x1, y1, x2, y2 = [int(v) for v in f.bbox]
        x1, y1 = max(0, x1), max(0, y1)
        fl = L[y1:y2, x1:x2]
        ab = lab[y1:y2, x1:x2, 1:]
        rec['face_box'] = [x1, y1, x2, y2]
        rec['face_L_mean'] = round(float(fl.mean()), 1)
        rec['face_L_std'] = round(float(fl.std()), 1)      # 越小＝越平＝越没有明暗层次
        rec['face_L_p90_p10_span'] = round(float(np.percentile(fl, 90) - np.percentile(fl, 10)), 1)
        rec['face_a_mean'] = round(float(ab[:, :, 0].mean()), 1)   # >128 偏红/暖
        rec['face_b_mean'] = round(float(ab[:, :, 1].mean()), 1)   # >128 偏黄/暖
        rec['face_white_ratio'] = round(float((fl > 210).mean()), 4)  # 近白像素占比
    else:
        rec['face'] = None
    rows.append(rec)

io.open('blanch_measure.json', 'w', encoding='utf-8').write(json.dumps(rows, ensure_ascii=False, indent=1, default=float))
hdr = ['name', 'face_L_mean', 'face_L_std', 'face_L_p90_p10_span', 'face_a_mean', 'face_b_mean', 'face_white_ratio', 'all_L_mean', 'all_bright_gt200_ratio']
print(' | '.join(hdr))
for r in rows:
    print(' | '.join(str(r.get(h, '-')) for h in hdr))