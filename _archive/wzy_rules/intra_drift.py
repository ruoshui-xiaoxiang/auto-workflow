# -*- coding: utf-8 -*-
"""镜内场景漂移的机器指标（渲染结束后跑，别在批中途跑——它要起 DINOv2，正是 03:39 停批的成因）。

原理：同一条镜的首/中/末三帧各取 DINOv2 CLS 向量，算"中-首"与"末-首"的余弦距离。
  同地点连续运镜 → 距离小；镜内换了地方 → 距离大。
基线不用我拍脑袋定：拿资产包 8 条 Seedance 的实测分布当带（它们是他指定的画风/站位基准样本）。
已知局限（写清楚，别当万能闸）：
  - 多镜蒙太奇条（S01/S02 那种本身带剪辑的）天然大，只能当上界参考，不能进"带内"统计；
  - 只抽三帧，中段闪出去又回来的会漏；
  - DINOv2 认的是"语义场景"，同一地点换个机位不算漂，这正是我们要的。
"""
import os, sys, glob, json
import numpy as np, cv2

sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
from video_qc import dino_emb                      # 复用同一套向量，别引第二个模型
PK = r'E:\创作\武昭君仪\武昭君仪资产包'
OUT = r'D:\AIWorkflow\tmp\wzy\h3\intra_drift.json'


def three(path):
    c = cv2.VideoCapture(path)
    n = int(c.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    E = []
    for k in (int(n * 0.02), n // 2, max(0, n - 3)):
        c.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, f = c.read()
        E.append(dino_emb(f) if ok else np.zeros_like(E[-1]) if E else None)
    c.release()
    if any(e is None for e in E): return None
    a, b, d = [e.reshape(-1) for e in E]
    a, b, d = a / np.linalg.norm(a), b / np.linalg.norm(b), d / np.linalg.norm(d)
    return float(1 - float(a @ b)), float(1 - float(a @ d))


def main():
    rows = {}
    for p in sorted(glob.glob(os.path.join(PK, '*.mp4'))):
        r = three(p)
        if r: rows[os.path.basename(p)[:26]] = r
    led = json.load(open(r'D:\AIWorkflow\tmp\wzy\h3\ledger.json', encoding='utf8'))
    for sid in sorted([k for k, v in led.items() if v.get('mp4')], key=lambda x: int(x[1:])):
        r = three(led[sid]['mp4'])
        if r: rows[sid] = r
    seed = [v for k, v in rows.items() if not k.startswith('H')]
    single = [v for k, v in seed if max(v) < 0.30]        # 剔掉自带剪辑的蒙太奇条
    band = float(np.percentile([max(v) for v in (single or seed)], 95)) if (single or seed) else 0.30
    print('Seedance 单地点条 %d/%d，首末距离 95 分位 = %.3f' % (len(single), len(seed), band))
    print('%-28s %8s %8s  %s' % ('条', '中-首', '末-首', '判定'))
    out = {'band': round(band, 4)}
    for k, v in rows.items():
        flag = '漂' if max(v) > band else ('—' if not k.startswith('H') else '带内')
        print('%-28s %8.3f %8.3f  %s' % (k, v[0], v[1], flag))
        out[k] = [round(v[0], 4), round(v[1], 4), flag]
    json.dump(out, open(OUT, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('落盘：', OUT)


if __name__ == '__main__':
    main()
