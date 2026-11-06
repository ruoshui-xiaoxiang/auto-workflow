# -*- coding: utf-8 -*-
"""拼片前置验证：H3 的 7:4 产物和 Seedance 的 16:9 素材，两条都要能归一到 1280x720。
03:50 这一步不是走过场——旧裁切式对 1344x768 直接报错，早上才发现就晚了。"""
import os, sys, subprocess, glob, cv2
sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
import finish_ch1 as F

os.makedirs(F.BUILD, exist_ok=True)
H3MP4 = r'E:\图像影音资源池\武昭君仪\批次\20260926_022703\video\xn_20260926_022703_00001_.mp4'
seed = sorted(glob.glob(os.path.join(F.PK if hasattr(F, 'PK') else
           r'E:\创作\武昭君仪\武昭君仪资产包', '*.mp4')))
cases = [('H3 1344x768', H3MP4)] + [('Seedance', p) for p in seed[:8]]
for tag, src in cases:
    if not os.path.isfile(src):
        print('%-12s 缺文件 %s' % (tag, os.path.basename(src))); continue
    dst = os.path.join(F.BUILD, 'probe_%s.mp4' % os.path.splitext(os.path.basename(src))[0][:14])
    ok = F.norm_to_720(src, dst)
    if not ok:
        print('%-12s FAIL %s' % (tag, os.path.basename(src))); continue
    c = cv2.VideoCapture(dst)
    n = int(c.get(cv2.CAP_PROP_FRAME_COUNT)); w = int(c.get(3)); h = int(c.get(4))
    c.release()
    print('%-12s %-28s -> %dx%d %.1fs %s  src=%s audio=%s' % (
        tag, os.path.basename(src)[:28], w, h, n / 24.0,
        'OK' if (w, h) == (1280, 720) else '画幅不对', F.probe(src), F.probe(dst)[1]))
