# -*- coding: utf-8 -*-
"""arm1（现行·A09 真人感卡）vs arm6（只换第五张锚为 A09b 渲染感卡）对照板。

四行两列：整图 / 男性区 / 君仪区 / 配角卡本身。左列＝arm1，右列＝arm6（第四行＝A09／A09b）。
附：皮肤高频/噪点两列数字——**只作参考，不当闸**（已实测一图内两值、侧脸检不到）。
"""
import io, json, os, sys
import numpy as np, cv2

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.join(HERE, 'kf_out', 'ab')
CAST = os.path.join(HERE, 'kf_out', 'cast')
ASSET = r'E:\创作\武昭君仪\武昭君仪资产包'
OUT = os.path.join(HERE, 'qc_sheet')
os.makedirs(OUT, exist_ok=True)
GAP, BG = 10, (24, 24, 24)


def L(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


def fit(im, w, h):
    s = min(w / im.shape[1], h / im.shape[0])
    r = cv2.resize(im, (max(1, int(im.shape[1] * s)), max(1, int(im.shape[0] * s))),
                   interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    c = np.full((h, w, 3), BG[0], np.uint8)
    y, x = (h - r.shape[0]) // 2, (w - r.shape[1]) // 2
    c[y:y + r.shape[0], x:x + r.shape[1]] = r
    return c


def hf_noise(im, box):
    x, y, w, h = box
    c = im[y:y + h, x:x + w].astype(np.float32)
    g = cv2.GaussianBlur(c, (0, 0), 1.2)
    m = cv2.medianBlur(c.astype(np.uint8), 3).astype(np.float32)
    return float((c - g).std()), float((c - m).std())


def row(left, right, lw, rh, title):
    a, b = fit(left, lw, rh), fit(right, lw, rh)
    band = np.hstack([a, np.full((rh, GAP, 3), BG, np.uint8), b])
    bar = np.full((rh + 34, band.shape[1], 3), BG, np.uint8)
    bar[:rh] = band
    cv2.putText(bar, title, (12, rh + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2, cv2.LINE_AA)
    return bar


def main():
    a1, a6 = L(os.path.join(AB, 'arm1_base.png')), L(os.path.join(AB, 'arm6_render_cast.png'))
    c9, c9b = L(os.path.join(ASSET, 'A09 粗臂男（混混）.png')), L(os.path.join(CAST, 'A09b 粗臂男（混混）·CG渲染版.png'))
    H, W = a1.shape[:2]
    male = lambda im: im[int(H * .10):int(H * .74), int(W * .14):int(W * .52)]
    girl = lambda im: im[int(H * .16):int(H * .56), int(W * .58):int(W * .86)]
    lw = 1180
    rows = [row(a1, a6, lw, 664, 'FULL  left=arm1 (A09 photoreal card)   right=arm6 (A09b CG card)'),
            row(male(a1), male(a6), lw, 560, 'MALE region  left=arm1   right=arm6'),
            row(girl(a1), girl(a6), lw, 560, 'JUNYI region  left=arm1   right=arm6'),
            row(c9, c9b, lw, 620, 'CAST CARD  left=A09 original   right=A09b new CG card')]
    wmax = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.hstack([r, np.full((r.shape[0], wmax - r.shape[1], 3), BG, np.uint8)]) if r.shape[1] < wmax else r for r in rows])
    dst = os.path.join(OUT, 'arm1_vs_arm6_换锚对照.jpg')
    cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(dst)
    print('→', dst, sheet.shape[1], 'x', sheet.shape[0])

    st = {}
    for name, im in [('arm1', a1), ('arm6', a6)]:
        mh, mn = hf_noise(im, (int(W * .22), int(H * .18), int(W * .18), int(H * .30)))
        gh, gn = hf_noise(im, (int(W * .66), int(H * .24), int(W * .10), int(H * .18)))
        st[name] = dict(male_hf=round(mh, 2), male_noise=round(mn, 2),
                        girl_hf=round(gh, 2), girl_noise=round(gn, 2))
    st['_note'] = '皮肤高频/噪点只作参考，已实测不能当闸（一图内两值、侧脸检不到）；判以目视为准。'
    io.open(os.path.join(AB, 'arm6_metrics.json'), 'w', encoding='utf8').write(
        json.dumps(st, ensure_ascii=False, indent=1))
    print(json.dumps(st, ensure_ascii=False))


if __name__ == '__main__':
    main()
