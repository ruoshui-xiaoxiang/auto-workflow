# -*- coding: utf-8 -*-
"""粗臂男设定图第二版对照板：A09（原·真人感）／A09b（上一版）／candA（纯文字）／candB（挂A09双锚）。
皮肤高频/噪点只作参考，不当闸。四张同管线、同尺寸，横向可比。"""
import io, json, os
import numpy as np, cv2

HERE = os.path.dirname(os.path.abspath(__file__))
CAST = os.path.join(HERE, 'kf_out', 'cast')
ASSET = r'E:\创作\武昭君仪\武昭君仪资产包'
OUT = os.path.join(HERE, 'qc_sheet')
GAP, BG = 10, (24, 24, 24)
ITEMS = [('A09 原（真人感）', os.path.join(ASSET, 'A09 粗臂男（混混）.png')),
         ('A09b 上一版', os.path.join(CAST, 'A09b 粗臂男（混混）·CG渲染版.png')),
         ('candA 纯文字', os.path.join(CAST, 'candA_puretext.png')),
         ('candB 挂A09双锚', os.path.join(CAST, 'candB_fromA09.png'))]


def L(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


def fit(im, w, h):
    s = min(w / im.shape[1], h / im.shape[0])
    r = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))), interpolation=cv2.INTER_AREA)
    c = np.full((h, w, 3), BG[0], np.uint8)
    y, x = (h - r.shape[0]) // 2, (w - r.shape[1]) // 2
    c[y:y + r.shape[0], x:x + r.shape[1]] = r
    return c


def hf_noise(im, box):
    x, y, w, h = box
    c = im[y:y + h, x:x + w].astype(np.float32)
    g = cv2.GaussianBlur(c, (0, 0), 1.2)
    m = cv2.medianBlur(c.astype(np.uint8), 3).astype(np.float32)
    return round(float((c - g).std()), 2), round(float((c - m).std()), 2)


def main():
    W, H = 1290, 726
    top = np.hstack([fit(L(p), W, H) for _, p in ITEMS])
    bar = np.full((H + 40, top.shape[1], 3), BG, np.uint8)
    bar[:H] = top
    for k, (lab, _) in enumerate(ITEMS):
        cv2.putText(bar, '%d.%s' % (k + 1, lab), (k * (W + 0) + 14, H + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    # 第一视图的脸＋上臂区放大（四张同一相对位置）
    crop = lambda im: im[int(im.shape[0] * .10):int(im.shape[0] * .52), int(im.shape[1] * .01):int(im.shape[1] * .20)]
    bot = np.hstack([fit(crop(L(p)), W, 520) for _, p in ITEMS])
    b2 = np.full((520 + 40, bot.shape[1], 3), BG, np.uint8)
    b2[:520] = bot
    cv2.putText(b2, 'view1 face + arm zoom (same relative box)', (14, 548),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    sheet = np.vstack([bar, np.full((GAP, bar.shape[1], 3), BG, np.uint8), b2])
    dst = os.path.join(OUT, '配角设定图_v2对照.jpg')
    cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(dst)
    st = {}
    for lab, p in ITEMS:
        im = L(p)
        h, w = im.shape[:2]
        hf, nz = hf_noise(im, (int(w * .045), int(h * .16), int(w * .045), int(h * .16)))
        st[lab] = dict(face_hf=hf, face_noise=nz)
    st['_note'] = '皮肤高频/噪点只作参考不当闸；四张同管线同尺寸故可横比。'
    io.open(os.path.join(CAST, 'cast_v2_metrics.json'), 'w', encoding='utf8').write(
        json.dumps(st, ensure_ascii=False, indent=1))
    print('→', dst, sheet.shape[1], 'x', sheet.shape[0])
    print(json.dumps(st, ensure_ascii=False))


if __name__ == '__main__':
    main()
