# -*- coding: utf-8 -*-
"""运动衰减实测：验证 R17「时长＝信息单元×~1s」到底是不是真缺陷。

为什么跑这个：拿现行分镜表算 秒数÷信息单元，23 镜里 20 镜超出 R17 上限的 1.6 倍以上
（全片约多给 116 秒）。但"多给时间"有两种可能：① H3 把已有动作拖长凑时长（＝R17 说的
缺陷，实测过的翻车）；② 多给的时间本来就该给氛围/运镜（＝我的单元计数漏算了非动作内容）。
这两种在提示词上区分不了，**在成片上能区分**：拖长＝运动量随时间衰减、尾段趋零；
氛围＝全程匀速不塌。已渲的 8 镜（H01–H05/H07/H08/H13）就是现成的对照样本，零花费。

只读：不改提示词、不动账本、不删产物。
用法：python motion_curve.py
"""
import os, sys, json, shutil, tempfile
import cv2
import numpy as np

WZY = os.path.dirname(os.path.abspath(__file__))
LED = os.path.join(WZY, 'h3', 'ledger.json')
OUT = os.path.join(WZY, 'h3', '运动衰减实测.json')
WORK = os.path.join(WZY, 'qc_motion')
STEP = 2          # 每 2 帧算一次光流（24fps → 12 次/秒）
NORM_W = 480      # 归一到同一宽度，1344 与 736 才可比

def load():
    led = json.load(open(LED, encoding='utf8'))
    items = []
    for sid in sorted(led):
        m = led[sid].get('mp4')
        if m and os.path.exists(m):
            items.append((sid, led[sid]['verdict'], m))
    return led, items


def curves(path):
    """返回 (每秒平均运动量列表, 元数据)。cv2 打不开中文路径 → 先复制到 ASCII 临时名。"""
    tmp = os.path.join(WORK, 'clip_%d.mp4' % os.getpid())
    shutil.copyfile(path, tmp)
    cap = cv2.VideoCapture(tmp)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    d = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    ok, prev = cap.read()
    vals, idx = [], 0
    while True:
        ok, fr = cap.read()
        idx += 1
        if not ok:
            break
        if idx % STEP:
            continue
        if prev is None:
            prev = fr
            continue
        sc = NORM_W / float(fr.shape[1])
        a = cv2.resize(cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY), None, fx=sc, fy=sc)
        b = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), None, fx=sc, fy=sc)
        f = d.calc(a, b, None)
        vals.append(float(np.hypot(f[..., 0], f[..., 1]).mean()))
        prev = fr
    cap.release()
    try:
        os.remove(tmp)
    except OSError:
        pass
    return np.array(vals), dict(n=n, fps=fps, secs=round(n / fps, 2))


def main():
    os.makedirs(WORK, exist_ok=True)
    led, items = load()
    if not items:
        print('账本里没有可播的成片'); return
    print('镜   判定    秒   全程均值  前1/4  后1/4  后25%/峰值  最静1秒(s)  形态')
    rows = {}
    for sid, verdict, path in items:
        v, meta = curves(path)
        if len(v) < 8:
            print('%s  帧太少' % sid); continue
        q = max(1, len(v) // 4)
        head, tail = v[:q].mean(), v[-q:].mean()
        peak = np.array([v[i:i + 24].mean() for i in range(max(1, len(v) - 24))]).max() if len(v) > 30 else v.max()
        # 最静的 2 秒在时间轴上的位置
        w = 12
        sil = [(v[i:i + w].mean(), i / (12.0)) for i in range(max(1, len(v) - w))]
        sil.sort()
        quiet_pos = sil[0][1]
        decay = tail / max(head, 1e-6)
        shape = ('尾塌（拖长嫌疑）' if decay < 0.55 else
                 '头轻（起势慢/接打断层）' if decay > 1.6 else '匀速（时间给氛围/运镜）')
        print('%s %-6s %5.1f %8.3f %8.3f %8.3f %8.2f      %5.1fs      %s' % (
            sid, verdict, meta['secs'], v.mean(), head, tail, tail / max(peak, 1e-6), quiet_pos, shape))
        rows[sid] = dict(secs=meta['secs'], mean=round(float(v.mean()), 4),
                         head=round(float(head), 4), tail=round(float(tail), 4),
                         decay=round(float(decay), 3), quiet_at=round(float(quiet_pos), 1),
                         shape=shape, curve=[round(float(x), 4) for x in v])
    json.dump(rows, open(OUT, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('\n曲线已存 %s' % OUT)

    ok = [r for r in rows.values()]
    if ok:
        print('\n—— 汇总 ——')
        for tag in ('尾塌（拖长嫌疑）', '匀速（时间给氛围/运镜）', '头轻（起势慢/接打断层）'):
            ids = [k for k, r in rows.items() if r['shape'] == tag]
            if ids:
                print('  %-16s %2d 镜：%s' % (tag, len(ids), ', '.join(sorted(ids))))
        print('  衰减比（后1/4 ÷ 前1/4）中位数：%.2f' % np.median([r['decay'] for r in ok]))


if __name__ == '__main__':
    main()
