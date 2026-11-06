# -*- coding: utf-8 -*-
"""君仪训练集批 1 目检板：上排四张整图缩略、中排四张、下排＝每张检出最大的脸放大（配 ArcFace 分数）。"""
import glob, io, json, os
import numpy as np, cv2

DS = r'D:\AIWorkflow\training\datasets\君仪\1_junyi'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'qc_sheet')
from insightface.app import FaceAnalysis

TW, TH = 620, 620          # 整图格（方格内居中）
FW = 300


def L(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


def cell(im, w, h):
    s = min(w / im.shape[1], h / im.shape[0])
    r = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))),
                   interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    c = np.full((h, w, 3), 18, np.uint8)
    y, x = (h - r.shape[0]) // 2, (w - r.shape[1]) // 2
    c[y:y + r.shape[0], x:x + r.shape[1]] = r
    return c


def main():
    qc = json.load(io.open(os.path.join(DS, 'qc_identity.json'), encoding='utf8')) if os.path.isfile(
        os.path.join(DS, 'qc_identity.json')) else {}
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    ids = [os.path.basename(p)[:-4] for p in sorted(glob.glob(os.path.join(DS, 'J*.png')))]
    full, faces = [], []
    for jid in ids:
        im = L(os.path.join(DS, jid + '.png'))
        full.append(cell(im, TW, TH))
        small = cv2.resize(im, None, fx=1024 / max(im.shape[:2]), fy=1024 / max(im.shape[:2]),
                           interpolation=cv2.INTER_AREA)
        k = max(im.shape[:2]) / 1024.0          # ⚠️ bbox 是小图坐标，裁原图必须乘回去
        fs = app.get(small)
        if fs:
            b = max(fs, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
            x0, y0, x1, y1 = [int(v * k) for v in b.bbox]
            pad = int((y1 - y0) * .35)
            crop = im[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
            crop = cell(crop, FW, 200)
        else:
            crop = np.full((200, FW, 3), 40, np.uint8)
        ch = min(200, crop.shape[0])
        t = np.full((200 + 30, max(FW, crop.shape[1]), 3), 18, np.uint8)
        t[:ch, :crop.shape[1]] = crop
        q = qc.get(jid, {})
        sims = q.get('sims', {})
        txt = '%s  %s' % (jid, ' '.join('%s%.2f' % (k.replace('face_real', 'FR'), v) for k, v in sims.items()))
        cv2.putText(t, txt[:44], (4, 222), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(t, 'nface=%d h=%s %s' % (q.get('nface', 0), q.get('face_h', '?'), q.get('verdict', '')),
                    (4, 242), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 220, 255), 1, cv2.LINE_AA)
        faces.append(cell(t, TW, 230))
    per = 4
    rows = []
    for k in range(0, len(ids), per):
        grp = lambda arr: np.hstack([arr[i] if i < len(arr) else np.full_like(arr[0], 18)
                                     for i in range(k, min(k + per, len(ids)))])
        r1, r2 = grp(full), grp(faces)
        if r2.shape[1] < r1.shape[1]:
            r2 = np.hstack([r2, np.full((r2.shape[0], r1.shape[1] - r2.shape[1], 3), 18, np.uint8)])
        rows.append(np.vstack([r1, np.full((6, r1.shape[1], 3), 40, np.uint8), r2]))
    wmax = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.hstack([r, np.full((r.shape[0], wmax - r.shape[1], 3), 18, np.uint8)]) if r.shape[1] < wmax else r
                       for r in rows])
    dst = os.path.join(OUT, '君仪训练集_批1目检.jpg')
    cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(dst)
    print('→', dst, sheet.shape[1], 'x', sheet.shape[0])


if __name__ == '__main__':
    main()
