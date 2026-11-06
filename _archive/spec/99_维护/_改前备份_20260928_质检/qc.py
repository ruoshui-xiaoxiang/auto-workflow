# -*- coding: utf-8 -*-
# -*- 一次性机检：身份 / 肤色 / 画风距离 / 构图景别 / 水印 / 跨图互比 -*-
#
# 阈值不是拍脑袋来的，全部由 qc_eval.py 在"人已经判过的 12 张 + 2 张锚图"上标定：
#   合格带 = 锚图(gold) 与 F 批(未被用户打回) 的实测值域
#   打回带 = dz0b2(画风漂) / dz0b2p(变白) / dz0b2pp(偏卡通) 共 9 张的实测值域
#   两带不重叠 → 才写进本文件当判据。重叠的指标（lap / fft_hi / flat / ssim / lbp）已剔除，
#   理由见文件末尾 REJECTED 注释。
#
# ⚠️ 已证实的陷阱：锚图分辨率低于产物 → 任何"纹理/细节"指标跟锚图比会反向（锚图反而分最低）。
#    所以纹理类只做「同管线内互比 + 绝对带」，绝不算「vs 锚图距离」。
#
# 用法:
#   python qc.py --dir dz0b2ppp
#   python qc.py --dir dz0b2ppp --face anchors/dingzhuang/junyi_face_jm2156.png
import os, sys, json, io, glob, argparse
import numpy as np, cv2, torch
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')

DEV = 'cuda' if torch.cuda.is_available() else 'cpu'
FACE_ANCH = r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/junyi_face_jm2156.png'
PATCH = 384

_app = None; _dino = None; _dpr = None; _lp = None

def lazy():
    global _app, _dino, _dpr, _lp
    if _app is None:
        from insightface.app import FaceAnalysis
        _app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'])
        _app.prepare(ctx_id=-1, det_size=(1024, 1024))
    if _dino is None:
        from transformers import AutoModel, AutoImageProcessor
        c = 'D:/AIWorkflow/models/hf'
        _dino = AutoModel.from_pretrained('facebook/dinov2-base', cache_dir=c).to(DEV).eval()
        _dpr = AutoImageProcessor.from_pretrained('facebook/dinov2-base', cache_dir=c)
    if _lp is None:
        import lpips
        _lp = lpips.LPIPS(net='alex').to(DEV).eval()

def imread(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

def save(img, p):
    cv2.imencode(os.path.splitext(p)[1])[1].tofile(p)

def face(img):
    lazy()
    fs = _app.get(img)
    if not fs: return None, None
    f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
    return f, [int(v) for v in f.bbox]

def norm_patch(img, size=PATCH):
    """按脸尺寸归一取「头+上身」→ 胸像与全身可比，消掉景别这个混杂变量。"""
    H, W = img.shape[:2]
    f, (x1, y1, x2, y2) = face(img)
    if f is None: return None
    fw, fh = x2-x1, y2-y1; cx = (x1+x2)//2
    a, b = max(0, int(cx-1.5*fw)), min(W, int(cx+1.5*fw))
    c, d = max(0, int(y1-0.9*fh)), min(H, int(y2+2.2*fh))
    crop = img[c:d, a:b]
    return None if crop.size == 0 else cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)

def _t(bgr):
    x = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)/255.0
    return torch.from_numpy(x).permute(2, 0, 1).unsqueeze(0).to(DEV)

def dino_emb(bgr):
    lazy()
    x = _dpr(images=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_tensors='pt').to(DEV)
    with torch.no_grad(): return _dino(**x).pooler_output[0].cpu().numpy().astype(np.float64)

def lpips_d(a, b):
    lazy()
    with torch.no_grad(): return float(_lp(_t(a), _t(b)).item())

def cos(a, b):
    return float(np.dot(a, b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-12))

def garment_patch(img, size=256):
    """只取下巴以下那段衣料。纹理类指标不能跟锚图比（锚图分辨率低反而分最低），
    只能做「同管线内的绝对带 + 批内互比」。"""
    H, W = img.shape[:2]
    f, (x1, y1, x2, y2) = face(img)
    if f is None: return None
    fw, fh = x2-x1, y2-y1; cx = (x1+x2)//2
    a, b = max(0, int(cx-1.6*fw)), min(W, int(cx+1.6*fw))
    c, d = max(0, int(y2+0.2*fh)), min(H, int(y2+1.8*fh))
    crop = img[c:d, a:b]
    return None if crop.size == 0 else cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)

def gedge(bgr):
    """Sobel 梯度幅值均值（不是 Canny 占比——两者量纲不同，阈值只对前者成立）。
    标定值域：偏卡通打回带 58.5–71.9 / F 批 76.3–86.3。"""
    g0 = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(g0, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(g0, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.sqrt(gx**2 + gy**2).mean())

def corners_clean(img, n=240):
    """四角高频扫描。水印是小块集中高方差；衣褶是沿一条边分布。这里只报数，判定交人工。"""
    H, W = img.shape[:2]
    out = {}
    for k, c in {'tl': img[:n, :n], 'tr': img[:n, W-n:], 'bl': img[H-n:, :n], 'br': img[H-n:, W-n:]}.items():
        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        out[k] = float(cv2.Laplacian(g, cv2.CV_32F).astype(np.float64).var())
    return out

# ---------- 阈值（来源见文件头；由人审标签集标定）----------
TH = {
    'arc':      {'fail_lo': 0.50, 'warn_lo': 0.65, 'note': '对脸锚身份相似度。<0.50 不是同人；<0.65 是 F 批以下＝画风/渲染档不够'},
    'faceWhite':{'fail_hi': 0.050, 'warn_hi': 0.030, 'note': '人脸近白像素占比。打回带 0.077–0.293 / 合格带 ≤0.016'},
    'faceL':    {'fail_hi': 118.0, 'warn_hi': 112.0, 'note': '人脸 L*。打回带 123–154 / 合格带 103–108'},
    'faceA':    {'fail_lo': 132.0, 'warn_lo': 134.0, 'note': '人脸暖度 a*。打回带 127–131 / 合格带 134–138'},
    'lpalex':   {'fail_hi': 0.460, 'warn_hi': 0.410, 'note': 'LPIPS-alex vs 脸锚归一patch。打回 0.408–0.552 / F批 0.356–0.405'},
    'dino':     {'fail_lo': 0.700, 'warn_lo': 0.760, 'note': 'DINOv2 余弦 vs 脸锚patch。打回 0.573–0.761 / F批 0.765–0.777'},
    'gedge':    {'fail_lo': 70.0, 'warn_lo': 76.0, 'note': '衣料边缘密度（只量下巴以下，同管线内比）。偏卡通打回带 58.5–71.9 / F批 76.3–86.3。⚠️各只 3 张，带是拟合出来的，新画风出现后要重标'},
    'faceHR':   {'fail_hi': 0.140, 'warn_hi': 0.105, 'note': '脸高/画高。全身立像实测 0.074–0.092；F1 半身漂到 0.120'},
}

def one(path, ref_patch, ref_dino, ref_arc):
    img = imread(path); H = img.shape[0]
    f, box = face(img)
    r = {'file': os.path.basename(path)}
    if f is None:
        r['fatal'] = '检不到脸'; return r
    x1, y1, x2, y2 = box
    fac = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2LAB).astype(np.float32)
    r['arc'] = cos(f.normed_embedding, ref_arc)
    r['faceL'] = float(fac[:, :, 0].mean())
    r['faceA'] = float(fac[:, :, 1].mean())
    r['faceWhite'] = float((fac[:, :, 0] > 210).mean())
    r['faceHR'] = (y2-y1)/H
    p = norm_patch(img)
    if p is None:
        r['fatal'] = '取不到归一patch'; return r
    r['lpalex'] = lpips_d(p, ref_patch)
    r['dino'] = cos(dino_emb(p), ref_dino)
    gp = garment_patch(img)
    r['gedge'] = gedge(gp) if gp is not None else None
    r['corner'] = corners_clean(img)
    r['_patch'] = p
    return r

def flag(k, v):
    t = TH[k]
    if 'fail_hi' in t and v > t['fail_hi']: return 'FAIL'
    if 'fail_lo' in t and v < t['fail_lo']: return 'FAIL'
    if 'warn_hi' in t and v > t['warn_hi']: return 'warn'
    if 'warn_lo' in t and v < t['warn_lo']: return 'warn'
    return 'ok'

AXES = [('arc', '身份'), ('faceL', '肤色L*'), ('faceWhite', '近白%'), ('faceA', '暖度a*'),
        ('lpalex', 'LPIPS距'), ('dino', 'DINO似'), ('gedge', '衣料边密'), ('faceHR', '脸/画高')]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--face', default=FACE_ANCH)
    ap.add_argument('--pat', default='*_raw.png')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, a.pat)))
    if not files:
        print('没有匹配文件', a.dir, a.pat); return
    fi = imread(a.face)
    ff, _ = face(fi)
    ref_patch = norm_patch(fi)
    ref_dino = dino_emb(ref_patch)
    rows = [one(p, ref_patch, ref_dino, ff.normed_embedding.astype(np.float64)) for p in files]

    # 跨图互比（同批内身份/画风自洽）
    embs = [r.pop('_patch') for r in rows if '_patch' in r]
    arcs = [r['arc'] for r in rows if r.get('arc') is not None]
    print('%-15s' % '文件' + ''.join('%-11s' % n for _k, n in AXES) + '判定')
    print('%-15s' % '(指标含义)' + ''.join('%-11s' % k for k, _n in AXES))
    bad = 0
    for r in rows:
        cells, st = [], []
        for k, _n in AXES:
            v = r.get(k)
            if v is None: cells.append('-'); continue
            s = flag(k, v)
            cells.append('%.3f %s' % (v, {'ok': '  ', 'warn': '⚠', 'FAIL': '✗'}[s]))
            if s == 'FAIL': st.append(k)
            elif s == 'warn': bad += 0
        print('%-15s' % r['file'] + ''.join('%-11s' % c for c in cells) + ('FAIL:' + ','.join(st) if st else 'ok'))
    if len(embs) > 1:
        m = np.array([[cos(dino_emb(x), dino_emb(y)) for y in embs] for x in embs])
        iu = np.triu_indices(len(embs), 1)
        s = 'FAIL' if m[iu].min() < 0.75 else ('warn' if m[iu].mean() < 0.80 else 'ok')
        print('\n批内 DINO 互比: 均值 %.3f 最低 %.3f → %s  （已知带：画风漂批 0.770/0.727＝最差，F批 0.876/0.844＝最好）'
              % (m[iu].mean(), m[iu].min(), s))
    io.open(os.path.join(a.dir, 'qc.json'), 'w', encoding='utf-8').write(
        json.dumps([{k: v for k, v in r.items() if k != '_patch'} for r in rows], ensure_ascii=False, indent=1, default=float))
    print('\n阈值来源: 人审标签集 qc_eval.py（合格带=锚图+F批未打回；打回带=dz0b2/dz0b2p/dz0b2pp 共9张）')
    print('已剔除的无效指标: lap(奖励糊,锚图反而最低) fft_hi(被DC主导,全为99.x) flat(组间重叠) ssim(无像素对齐) lbp(无区分力)')

if __name__ == '__main__':
    main()