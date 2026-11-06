# -*- coding: utf-8 -*-
# 验证两件事：
# (1) 外部建议的"ArcFace 余弦>0.85 判同人"在我们这套画风上成不成立
# (2) "基准图池 + 多对多取最高分"能不能真的降低误判（这是那份建议里唯一我们没做的）
import numpy as np, cv2, os
from insightface.app import FaceAnalysis
os.chdir(r'D:/AIWorkflow/tmp/wzy')
app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'])
app.prepare(ctx_id=-1, det_size=(1024, 1024))

def imread(p): return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
def emb(p):
    fs = app.get(imread(p))
    if not fs: return None
    f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
    return f.normed_embedding.astype(np.float64)

POOL = {
    'jm_2156':  'anchors/dingzhuang/jm_2156_yuebai_bust.png',
    'jm_2313':  'anchors/dingzhuang/jm_2313_huafu_bust.png',
    'jm_5628':  'anchors/dingzhuang/jm_5628_jianxiu_bust.png',
    'jm_6135':  'anchors/dingzhuang/jm_6135_riyong_bust.png',
    'facev2':   'anchors/dingzhuang/junyi_face_jm2156.png',
}
pe = {k: emb(v) for k, v in POOL.items()}
pe = {k: v for k, v in pe.items() if v is not None}

S = [
    ('dz0b2_D1', 'dz0b2/D1_raw.png', 'rej'), ('dz0b2_D2', 'dz0b2/D2_raw.png', 'rej'), ('dz0b2_D3', 'dz0b2/D3_raw.png', 'rej'),
    ('D1p', "dz0b2p/D1'_raw.png", 'rej'), ('D2p', "dz0b2p/D2'_raw.png", 'rej'), ('D3p', "dz0b2p/D3'_raw.png", 'rej'),
    ('E1', 'dz0b2pp/E1_raw.png', 'rej'), ('E2', 'dz0b2pp/E2_raw.png', 'rej'), ('E3', 'dz0b2pp/E3_raw.png', 'rej'),
    ('F1', 'dz0b2ppp/F1_raw.png', 'good'), ('F2', 'dz0b2ppp/F2_raw.png', 'good'), ('F3', 'dz0b2ppp/F3_raw.png', 'good'),
]
print('池内成员互判（同一角色的不同即梦定妆，真值＝同人）：')
ks = list(pe)
for i in range(len(ks)):
    for j in range(i+1, len(ks)):
        print('   %-9s vs %-9s cos=%.3f  EUC=%.3f' % (ks[i], ks[j], np.dot(pe[ks[i]], pe[ks[j]]),
              np.linalg.norm(pe[ks[i]]-pe[ks[j]])))
print()
print('%-10s %-5s %8s %8s %8s   %s' % ('样本', '真值', '单锚cos', '池max', 'EUC', '按0.85判同人'))
res = []
for t, p, truth in S:
    e = emb(p)
    if e is None: continue
    single = float(np.dot(e, pe['facev2']))
    mx = max(float(np.dot(e, pe[k])) for k in pe)
    argmax = max(pe, key=lambda k: float(np.dot(e, pe[k])))
    euc = float(np.linalg.norm(e - pe['facev2']))
    res.append((truth, single, mx))
    print('%-10s %-5s %8.3f %8.3f %8.3f   %s' % (t, truth, single, mx, euc, '通过' if mx > 0.85 else '误判为不同人'))

def band(i, name):
    g = [r[i] for r in res if r[0] == 'good']
    b = [r[i] for r in res if r[0] == 'rej']
    print('%-10s good[%.3f,%.3f] rej[%.3f,%.3f] 分开=%s  good最低=%.3f rej最高=%.3f' % (
        name, min(g), max(g), min(b), max(b), '是' if min(g) > max(b) else '否', min(g), max(b)))
print()
band(1, '单锚cos'); band(2, '池maxcos')
print('\n外部建议阈值核对：ArcFace 余弦>0.85 判同人 → 上表有几张会被误杀？')
n = sum(1 for r in res if r[2] <= 0.85)
print('   按池max：12 张中 %d 张会被 0.85 阈值误判为"不是君仪"（含全部 good 批）' % n)