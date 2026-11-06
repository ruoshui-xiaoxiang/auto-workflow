# -*- coding: utf-8 -*-
'''量化"偏卡通"：按脸尺寸归一化的衣料纹理密度 + 中间调占比。
卡通 = 纹理密度低、中间调少、平整色块多。'''
import numpy as np, cv2, json, io, os
from insightface.app import FaceAnalysis
os.chdir(r'D:/AIWorkflow/tmp/wzy')
app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection'])
app.prepare(ctx_id=-1, det_size=(1024, 1024))

def imread(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

def garment_metrics(p, skin_lab=None):
    img = imread(p)
    H, W = img.shape[:2]
    fs = app.get(img)
    if not fs:
        return None
    f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
    x1, y1, x2, y2 = [int(v) for v in f.bbox]
    fw, fh = x2-x1, y2-y1
    cx = (x1+x2)//2
    # 衣料取样：下巴往下 0.2~1.8 脸高、脸心左右各 1.6 脸宽
    py1, py2 = int(y2+0.2*fh), int(y2+1.8*fh)
    px1, px2 = int(cx-1.6*fw), int(cx+1.6*fw)
    py1, py2 = max(0, py1), min(H, py2)
    px1, px2 = max(0, px1), min(W, px2)
    patch = img[py1:py2, px1:px2]
    if patch.size == 0:
        return None
    # 归一到固定尺寸 → 尺度无关
    patch = cv2.resize(patch, (256, 256), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0]
    # 高频能量（纹理密度）
    lap = cv2.Laplacian(g, cv2.CV_64F)
    # 梯度幅值均值（边缘密度）
    gx = cv2.Sobel(g, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_64F, 0, 1, ksize=3)
    gmag = np.sqrt(gx**2 + gy**2)
    # 中间调占比（明度层次是否饱满）
    mid = ((L > 60) & (L < 190)).mean()
    # 平整区占比（梯度很低＝色块感强）
    flat = (gmag < 8).mean()
    return {
        'face_px': [fw, fh],
        'texture_lapvar': round(float(lap.var()), 1),
        'edge_gmag_mean': round(float(gmag.mean()), 2),
        'midtone_ratio': round(float(mid), 4),
        'flat_ratio': round(float(flat), 4),
    }

ITEMS = [
    ('锚_jm9862(风格)', r'anchors/dingzhuang/jm_9862_dual_look_labeled.png'),
    ('锚_jmfacev2(脸)', r'anchors/dingzhuang/junyi_face_jm2156.png'),
    ("dz0b2p_D2p(变白批)", r"dz0b2p/D2'_raw.png"),
    ('dz0b2pp_E1', r'dz0b2pp/E1_raw.png'),
    ('dz0b2pp_E2', r'dz0b2pp/E2_raw.png'),
    ('dz0b2pp_E3', r'dz0b2pp/E3_raw.png'),
]
rows = []
for name, p in ITEMS:
    m = garment_metrics(p)
    if m:
        m['name'] = name
        rows.append(m)
        print('%-20s 纹理=%8.1f 边缘=%6.2f 中间调=%5.2f 平整区=%5.2f 脸=%sx%s' % (
            name, m['texture_lapvar'], m['edge_gmag_mean'], m['midtone_ratio'], m['flat_ratio'],
            m['face_px'][0], m['face_px'][1]))
io.open('cartoon_measure.json', 'w', encoding='utf-8').write(json.dumps(rows, ensure_ascii=False, indent=1, default=float))