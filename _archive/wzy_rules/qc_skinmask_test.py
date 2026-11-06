# -*- coding: utf-8 -*-
# 实验：把"变白"判据从「SCRFD 人脸框」换成「框内皮肤掩码」，看分离度是否真的变好。
# 动机：框里混了黑发（拉低 L*）和灰背景（拉高 L*），角色碎发压面时污染更重。
import numpy as np, cv2
from insightface.app import FaceAnalysis

app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection'])
app.prepare(ctx_id=-1, det_size=(1024, 1024))

def imread(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

S = [
    ('dz0b2_D1', 'dz0b2/D1_raw.png', 'rej_style'),
    ('dz0b2_D2', 'dz0b2/D2_raw.png', 'rej_style'),
    ('dz0b2_D3', 'dz0b2/D3_raw.png', 'rej_style'),
    ('D1p', "dz0b2p/D1'_raw.png", 'rej_skin'),
    ('D2p', "dz0b2p/D2'_raw.png", 'rej_skin'),
    ('D3p', "dz0b2p/D3'_raw.png", 'rej_skin'),
    ('E1', 'dz0b2pp/E1_raw.png', 'rej_style'),
    ('E2', 'dz0b2pp/E2_raw.png', 'rej_style'),
    ('E3', 'dz0b2pp/E3_raw.png', 'rej_style'),
    ('F1', 'dz0b2ppp/F1_raw.png', 'pend'),
    ('F2', 'dz0b2ppp/F2_raw.png', 'pend'),
    ('F3', 'dz0b2ppp/F3_raw.png', 'pend'),
    ('锚facev2', 'anchors/dingzhuang/junyi_face_jm2156.png', 'gold'),
    ('锚9862', 'anchors/dingzhuang/jm_9862_dual_look_labeled.png', 'gold'),
]

def both(img):
    fs = app.get(img)
    if not fs: return None
    f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
    x1, y1, x2, y2 = [int(v) for v in f.bbox]
    crop = img[max(0, y1):y2, max(0, x1):x2]
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)[:, :, 0]
    ycc = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
    m = cv2.inRange(ycc, (0, 133, 77), (255, 180, 130))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    k = int((m > 0).sum())
    if k < 200: return None
    Ls = lab[m > 0]
    return (float(lab.mean()), float((lab > 210).mean())*100,
            float(Ls.mean()), float((Ls > 210).mean())*100, k/float(lab.size)*100)

print('%-10s %-10s %8s %9s %9s %11s %9s' % ('样本', '人审', '框L*', '框近白%', '皮肤L*', '皮肤近白%', '皮肤占框%'))
res = {}
for t, p, v in S:
    r = both(imread(p))
    if r is None:
        print('%-10s %-10s  皮肤像素不足' % (t, v)); continue
    res[t] = (v, r)
    print('%-10s %-10s %8.1f %8.2f%% %9.1f %10.2f%% %8.1f%%' % (t, v, r[0], r[1], r[2], r[3], r[4]))

def band(i, name):
    ok = [res[t][1][i] for t in res if res[t][0] in ('gold', 'pend')]
    bad = [res[t][1][i] for t in res if res[t][0] == 'rej_skin']
    ov = min(bad) <= max(ok)
    gap = min(bad) - max(ok)
    print('%-10s 合格带[%6.2f,%6.2f]  变白带[%6.2f,%6.2f]  重叠=%s  安全边距=%+.2f' % (
        name, min(ok), max(ok), min(bad), max(bad), '有' if ov else '无', gap))

print()
band(0, '框L*'); band(2, '皮肤L*')
band(1, '框近白'); band(3, '皮肤近白')