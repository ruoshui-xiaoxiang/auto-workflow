# -*- coding: utf-8 -*-
# 一致性指标验证台：拿"人已经判过的批次"当标签，看每个候选指标能不能在人工之前就把坏批分开。
# 判据不用 AUC（每批只 3 张，AUC 是噪声），用「组间零重叠」：坏批的值域与好批不重叠＝能提前抓到。
import os, json, io
import numpy as np, cv2, torch
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
from insightface.app import FaceAnalysis
from skimage.feature import local_binary_pattern
from skimage.metrics import structural_similarity as ssim

D = r'D:/AIWorkflow/tmp/wzy'
os.chdir(D)
DEV = 'cuda' if torch.cuda.is_available() else 'cpu'

# ---------- 模型 ----------
app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'])
app.prepare(ctx_id=-1, det_size=(1024, 1024))

from transformers import AutoModel, AutoImageProcessor
_cache = 'D:/AIWorkflow/models/hf'
dino = AutoModel.from_pretrained('facebook/dinov2-base', cache_dir=_cache).to(DEV).eval()
dpr = AutoImageProcessor.from_pretrained('facebook/dinov2-base', cache_dir=_cache)
import lpips
lp_alex = lpips.LPIPS(net='alex').to(DEV).eval()
# LPIPS-vgg 不启用：骨干 vgg16 要另下 528MB，download.pytorch.org 在本机网络会被重置；alex 是 LPIPS 默认推荐档
lp_vgg = None

def imread(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)

def face_box(img):
    fs = app.get(img)
    if not fs: return None, None
    f = max(fs, key=lambda x: (x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
    return f, [int(v) for v in f.bbox]

def norm_patch(img, size=384):
    """按脸尺寸归一化取「头+上身」区域 → 胸像与全身可比（去掉景别这个混杂变量）。"""
    H, W = img.shape[:2]
    f, (x1, y1, x2, y2) = face_box(img)
    if f is None: return None, None
    fw, fh = x2-x1, y2-y1
    cx = (x1+x2)//2
    px1, px2 = int(cx-1.5*fw), int(cx+1.5*fw)
    py1, py2 = int(y1-0.9*fh), int(y2+2.2*fh)
    px1, py1 = max(0, px1), max(0, py1)
    px2, py2 = min(W, px2), min(H, py2)
    crop = img[py1:py2, px1:px2]
    if crop.size == 0: return None, None
    return cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA), (fw, fh)

def to_t(bgr):
    x = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)/255.0
    return torch.from_numpy(x).permute(2, 0, 1).unsqueeze(0).to(DEV)

def dino_emb(bgr):
    x = dpr(images=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_tensors='pt').to(DEV)
    with torch.no_grad():
        return dino(**x).pooler_output[0].cpu().numpy()

def lpips_d(a, b, net):
    m = lp_alex if net == 'alex' else lp_vgg
    with torch.no_grad():
        return float(m(to_t(a), to_t(b)).item())

def lbp_hist(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lbp = local_binary_pattern(g, 24, 3, method='uniform')
    h, _ = np.histogram(lbp.ravel(), bins=26, range=(0, 26), density=True)
    return h

def chi2(a, b):
    return float(np.sum((a-b)**2/(a+b+1e-9)))

def patch_metrics(bgr):
    g0 = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    g = g0.astype(np.float32)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    L = lab[:, :, 0]
    f = np.abs(np.fft.rfft2(g))
    h, w = g.shape
    yy, xx = np.mgrid[0:h, 0:w//2+1]
    r = np.sqrt((yy-h/2)**2 + (xx-w/2)**2)/max(h, w)
    gx = cv2.Sobel(g0, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(g0, cv2.CV_32F, 0, 1, ksize=3)
    gmag = np.sqrt(gx.astype(np.float64)**2 + gy.astype(np.float64)**2)
    return {
        'lap': float(cv2.Laplacian(g0, cv2.CV_32F).astype(np.float64).var()),
        'fft_hi': float(f[r > 0.10].sum()/(f.sum()+1e-9)*100),
        'edge': float((cv2.Canny(g0, 60, 150) > 0).mean()*100),
        'flat': float((gmag < 8).mean()),
        'pL': float(L.mean()), 'pLsd': float(L.std()),
        'pa': float(lab[:, :, 1].mean()), 'pb': float(lab[:, :, 2].mean()),
        'pmid': float(((L > 60) & (L < 190)).mean()),
        'lbp': lbp_hist(bgr),
    }

# ---------- 样本 + 人审标签 ----------
# verdict: 'rej_style'(画风打回) 'rej_skin'(变白打回) 'ok'(未打回/权威)
SAMPLES = [
    ('dz0b2_D1',   'dz0b2/D1_raw.png',    'rej_style'),
    ('dz0b2_D2',   'dz0b2/D2_raw.png',    'rej_style'),
    ('dz0b2_D3',   'dz0b2/D3_raw.png',    'rej_style'),
    ('dz0b2p_D1p', "dz0b2p/D1'_raw.png",  'rej_skin'),
    ('dz0b2p_D2p', "dz0b2p/D2'_raw.png",  'rej_skin'),
    ('dz0b2p_D3p', "dz0b2p/D3'_raw.png",  'rej_skin'),
    ('dz0b2pp_E1', 'dz0b2pp/E1_raw.png',  'rej_style'),
    ('dz0b2pp_E2', 'dz0b2pp/E2_raw.png',  'rej_style'),
    ('dz0b2pp_E3', 'dz0b2pp/E3_raw.png',  'rej_style'),
    ('dz0b2ppp_F1','dz0b2ppp/F1_raw.png', 'pend'),
    ('dz0b2ppp_F2','dz0b2ppp/F2_raw.png', 'pend'),
    ('dz0b2ppp_F3','dz0b2ppp/F3_raw.png', 'pend'),
    ('锚_facev2',  'anchors/dingzhuang/junyi_face_jm2156.png', 'gold'),
    ('锚_9862',    'anchors/dingzhuang/jm_9862_dual_look_labeled.png', 'gold'),
]
REFS = {'facev2': 'anchors/dingzhuang/junyi_face_jm2156.png',
        '9862': 'anchors/dingzhuang/jm_9862_dual_look_labeled.png'}

refdat = {}
for rk, rp in REFS.items():
    im = imread(rp)
    if rk == '9862':
        # 六宫格：只取最左「华丽版·正面」那一格，否则 norm_patch 会在 6 张脸里随机挑
        W = im.shape[1]
        im = im[:, 0:int(0.22*W)]
    p, _ = norm_patch(im)
    refdat[rk] = {'patch': p, 'dino': dino_emb(p), 'lbp': patch_metrics(p)['lbp']}

emb_by_tag = {}
rows = []
for tag, path, verdict in SAMPLES:
    img = imread(path)
    f, box = face_box(img)
    p, _ = norm_patch(img)
    r = {'tag': tag, 'verdict': verdict}
    if p is None:
        rows.append(r); continue
    pm = patch_metrics(p)
    r['lap'] = pm['lap']; r['fft_hi'] = pm['fft_hi']; r['edge'] = pm['edge']
    r['flat'] = pm['flat']; r['pL'] = pm['pL']; r['pLsd'] = pm['pLsd']
    r['pa'] = pm['pa']; r['pb'] = pm['pb']; r['pmid'] = pm['pmid']
    de = dino_emb(p)
    for rk in REFS:
        rd = refdat[rk]['dino']
        r['dino_'+rk] = float(np.dot(de, rd)/(np.linalg.norm(de)*np.linalg.norm(rd)))
        r['lpalex_'+rk] = lpips_d(p, refdat[rk]['patch'], 'alex')
        r['ssim_'+rk] = ssim(cv2.cvtColor(p, cv2.COLOR_BGR2GRAY), cv2.cvtColor(refdat[rk]['patch'], cv2.COLOR_BGR2GRAY))
        r['lbp_'+rk] = chi2(pm['lbp'], refdat[rk]['lbp'])
    x1, y1, x2, y2 = box
    fac = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2LAB).astype(np.float32)
    fl = fac[:, :, 0]
    r['faceL'] = float(fl.mean()); r['faceWhite'] = float((fl > 210).mean())
    r['faceA'] = float(fac[:, :, 1].mean())
    r['face_px'] = int(x2-x1)
    r['arc'] = None
    emb_by_tag[tag] = f.normed_embedding
    rows.append(r)

# 身份：单独用脸锚算
arc_ref = emb_by_tag['锚_facev2']
for r in rows:
    r['arc'] = float(np.dot(emb_by_tag[r['tag']], arc_ref))

io.open('qc_eval.json', 'w', encoding='utf-8').write(json.dumps(rows, ensure_ascii=False, indent=1, default=float))

# ---------- 报表：按人审分组，看组间是否零重叠 ----------
KEYS = ['arc', 'faceL', 'faceWhite', 'faceA', 'pL', 'pa', 'pmid',
        'lap', 'fft_hi', 'edge', 'flat',
        'dino_facev2', 'dino_9862', 'lpalex_facev2', 'lpalex_9862',
        'ssim_facev2', 'lbp_facev2', 'lbp_9862']
print('\n===== 逐张 =====')
PK = ['arc', 'faceL', 'faceWhite', 'pa', 'lap', 'fft_hi', 'edge', 'flat',
      'dino_facev2', 'dino_9862', 'lpalex_facev2', 'lpalex_9862', 'ssim_facev2', 'lbp_facev2']
print('%-13s %-10s' % ('样本', '人审') + ''.join('%-12s' % k for k in PK))
for r in rows:
    print('%-13s %-10s' % (r['tag'], r['verdict']) + ''.join(
        '%-12s' % ('%8.3f' % r[k] if r.get(k) is not None else '-') for k in PK))

GROUPS = ['rej_style', 'rej_skin', 'pend', 'gold']
print('\n===== 分组（均值 [最小,最大]）=====')
print('%-16s' % '指标' + ''.join('%-19s' % g for g in GROUPS))
for k in KEYS:
    line = '%-16s' % k
    for g in GROUPS:
        vs = [r[k] for r in rows if r['verdict'] == g and r.get(k) is not None]
        line += '%-19s' % ('%6.2f [%5.2f,%5.2f]' % (np.mean(vs), min(vs), max(vs)) if vs else '-')
    print(line)
print('\n(每格＝组均值 [最小,最大])  gold=锚图权威  rej_style=画风打回  rej_skin=变白打回  pend=F批未表态')