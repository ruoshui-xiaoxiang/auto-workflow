# -*- coding: utf-8 -*-
'''尺度归一后的材质细节对照：他的画稿 vs 我们的出图。

为什么必须先归一尺度：画稿只有 691x526（0.36MP），里面还画了四个人，
单个人物大约 130x450 px；我们出图 1536x2688（4.13MP），人物约 900x2400 px。
**他每个人物分到的像素只有我们的十几分之一。** 所以"他更有质感"绝不可能是分辨率造成的，
反而说明差距在渲染本身。不归一就直接比，等于拿放大镜看我们、拿远视镜看他。

做法：两边都把人物重采样到 1000 px 高（双三次），再取同一相对位置的裙段做指标，
指标给四个，不押一个（Laplacian 会奖励糊，单看不算数）。
'''
import os
import numpy as np
import cv2

D = r'D:/AIWorkflow/tmp/wzy'
ART = os.path.join(D, 'ref/style_bjd_art.png')
OURS = [os.path.join(D, 'dz0o/O%d.png' % i) for i in (1, 2, 4, 5, 6)]
FIG_H = 1000


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def metrics(im, tag):
    """在等尺度裁片上量四项：微对比、高频占比、边缘密度、明度动态范围。"""
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lap = cv2.Laplacian(g, cv2.CV_32F).var()
    f = np.abs(np.fft.rfft2(g))
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w // 2 + 1]
    r = np.sqrt((yy - h / 2) ** 2 + (xx - w / 2) ** 2) / max(h, w)
    hi = f[r > 0.10].sum() / (f.sum() + 1e-9)
    ed = (cv2.Canny(g.astype(np.uint8), 60, 150) > 0).mean()
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2Lab).astype(np.float32)
    rng = np.percentile(lab[:, :, 0], 98) - np.percentile(lab[:, :, 0], 2)
    print('%-22s %4dx%-4d  微对比%7.1f  高频占比%5.1f%%  边缘密度%5.1f%%  明度范围%5.1f' % (
        tag, im.shape[1], im.shape[0], lap, hi * 100, ed * 100, rng))
    return lap, hi * 100, ed * 100, rng


def norm_crop(im, box_rel, tag):
    """把人物缩放到 FIG_H 高，再按相对框取裙段。"""
    h, w = im.shape[:2]
    s = FIG_H / h
    big = cv2.resize(im, (int(w * s), FIG_H), interpolation=cv2.INTER_CUBIC)
    H, W = big.shape[:2]
    x0, y0, x1, y1 = [int(v * W) if k % 2 == 0 else int(v * H)
                      for k, v in enumerate(box_rel)]
    crop = big[max(0, y0):y1, max(0, x0):x1]
    cv2.imencode('.png', crop)[1].tofile(os.path.join(D, 'mat_%s.png' % tag))
    return crop


def main():
    art = imread_u(ART)
    print('画稿 %dx%d，里面 4 个人物；我们出图 1536x2688 单人' % (art.shape[1], art.shape[0]))
    # 画稿：中间正面人物大约 x 0.36-0.55，裙段取 y 0.45-0.92
    c = norm_crop(art, (0.375, 0.50, 0.525, 0.92), 'art_front')
    m1 = metrics(c, '画稿·正面裙段')
    # 画稿：右二侧身人物
    c = norm_crop(art, (0.55, 0.50, 0.70, 0.92), 'art_side')
    m2 = metrics(c, '画稿·侧身裙段')
    print()
    rows = [m1, m2]
    for p in OURS:
        k = os.path.basename(p)[:-4]
        c = norm_crop(imread_u(p), (0.30, 0.50, 0.70, 0.92), k)
        rows.append(metrics(c, '我们·%s 裙段' % k))
    a = np.array(rows)
    print('\n汇总（越高＝该指标上细节越多）：')
    print('  画稿均值   微对比%7.1f  高频%5.1f%%  边缘%5.1f%%  明度%5.1f' % tuple(a[:2].mean(0)))
    print('  我们均值   微对比%7.1f  高频%5.1f%%  边缘%5.1f%%  明度%5.1f' % tuple(a[2:].mean(0)))
    d = a[2:].mean(0) - a[:2].mean(0)
    print('  差(我们-画稿)  微对比%+.1f  高频%+.1f%%  边缘%+.1f%%  明度%+.1f' % tuple(d))


if __name__ == '__main__':
    main()
