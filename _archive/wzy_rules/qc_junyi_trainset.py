# -*- coding: utf-8 -*-
"""君仪训练集批 1 的身份自检：每张 Jxx 里最大的脸 vs 三个身份参照。

参照：junyi_face_real（赛博线脸锚）／A01 红衣／A02 白衣。
判读口径沿用本机既有共识：**>0.6 同一人，0.4–0.6 灰区，<0.4 不同人**；
⚠️ 脸太小（<约 150px 高）时 ArcFace 本身不稳，数字只能当"检出了脸"，不能当身份判据 ⇒ 单独标出来。
裁判只能说 completed，剔不剔张由人看。
"""
import glob, io, json, os, sys
import numpy as np, cv2
from insightface.app import FaceAnalysis

DS = r'D:\AIWorkflow\training\datasets\君仪\1_junyi'
REFS = {'face_real': r'D:\AIWorkflow\tmp\wzy\anchors\dingzhuang\junyi_face_real.png',
        'A01': r'E:\创作\武昭君仪\武昭君仪资产包\A01 武君仪·赛博红衣基线.png',
        'A02': r'E:\创作\武昭君仪\武昭君仪资产包\A02 武君仪·古代白衣.png'}


def emb_of(app, p, want_big=True):
    im = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    r = 1024 / max(im.shape[:2]); sm = cv2.resize(im, None, fx=r, fy=r)
    fs = app.get(sm)
    if not fs:
        return None, 0, 0
    b = max(fs, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    h = int(b.bbox[3] - b.bbox[1]) / r          # 还原到原图尺度
    return b.normed_embedding, int(h), len(fs)


def main():
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    ref = {}
    for k, p in REFS.items():
        e, h, n = emb_of(app, p)
        ref[k] = e
        print('参照 %-10s 脸高 %4dpx  %s' % (k, h, 'OK' if e is not None else '检不到脸'))
    rows = {}
    for p in sorted(glob.glob(os.path.join(DS, 'J*.png'))):
        jid = os.path.basename(p)[:-4]
        e, h, n = emb_of(app, p)
        if e is None:
            rows[jid] = dict(face='未检出', nface=0)
            print('%-5s 未检出人脸  ← 训练集里这种张要剔（或裁出脸再测）' % jid); continue
        sims = {k: round(float(np.dot(e, v)), 3) for k, v in ref.items() if v is not None}
        best = max(sims.values()) if sims else 0
        flag = 'OK' if best > 0.6 else ('灰区' if best >= 0.4 else '不同人')
        if h < 150:
            flag += '·脸太小数字不可信'
        rows[jid] = dict(face_h=h, nface=n, sims=sims, verdict=flag)
        print('%-5s 脸高%4dpx 检出%d张  %s  ⇒ %s' % (
            jid, h, n, ' '.join('%s %.3f' % kv for kv in sims.items()), flag))
    io.open(os.path.join(DS, 'qc_identity.json'), 'w', encoding='utf8').write(
        json.dumps(rows, ensure_ascii=False, indent=1))
    print('\n→', os.path.join(DS, 'qc_identity.json'))


if __name__ == '__main__':
    main()
