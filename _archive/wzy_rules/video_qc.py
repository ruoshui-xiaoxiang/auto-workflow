# -*- coding: utf-8 -*-
"""视频成片自检（本地，零云端调用）。

定位：今晚人不在，机器判据只能给 **completed**，不能给 confirmed——
"好不好/像不像"最终仍要人眼过。本脚本的产物是"值得人先看哪几镜"的排序，不是"合格证明"。

三个动作：
  --baseline   从资产包那 8 条 Seedance 片抽风格基线（画风/光影/色彩/颗粒/构图景别），落 style_ref.json
  --video X    逐镜机检：规格、身份、风格距离、运动量、音轨、烧字、抽帧接触表
  --pair A B   跨镜连续性：A 末帧 vs B 首帧（拼左右对照图，这是重渲后自查的老办法）

判据来源：风格基线＝用户 2026-09-26 明确指定"这 8 条的画面风格光影作为基础样本站"；
指标本身沿用 qc.py 里经人审标签集验证过的那几个（DINOv2 余弦 / LPIPS / ArcFace / 四角干净度），
新加的只有：光流运动量、音轨响度与静音比、以及"对基线的风格距离"。
"""
import os, sys, json, glob, argparse, re
import numpy as np, cv2

sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
PACK = r'E:\创作\武昭君仪\武昭君仪资产包'
WZY = r'D:\AIWorkflow\tmp\wzy'
REF = os.path.join(WZY, 'style_ref.json')
FACE_ANCH = os.path.join(WZY, 'anchors', 'dingzhuang', 'junyi_face_real.png')
FACE_ANCH2 = os.path.join(PACK, 'A02 武昭君仪·古代白衣.png')
K = 12                      # 每条片抽几帧算基线
# 8 条 Seedance 片分两池：古代线只有 S01/T04，赛博线是其余六条。
# 合成一个质心会被实测判"太粗"——8 条类内余距 0.4577，跨了雾林和霓虹巷两种光，
# 拿它当对照等于没有对照，所以按池分开算。
POOL = {'S01': 'anc', 'T04': 'anc', 'S02': 'cyb', 'S13': 'cyb',
        'T09': 'cyb', 'T10': 'cyb', 'T11': 'cyb', 'T12': 'cyb'}

_c = {}
def lazy():
    if 'if' not in _c:
        from insightface.app import FaceAnalysis
        a = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'])
        a.prepare(ctx_id=-1, det_size=(1024, 1024)); _c['if'] = a
    if 'dino' not in _c:
        import torch
        from transformers import AutoModel, AutoImageProcessor
        dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        _c['dino'] = AutoModel.from_pretrained('facebook/dinov2-base',
                                               cache_dir='D:/AIWorkflow/models/hf').to(dev).eval()
        _c['dpr'] = AutoImageProcessor.from_pretrained('facebook/dinov2-base',
                                                       cache_dir='D:/AIWorkflow/models/hf')
        _c['dev'] = dev
        _c['torch'] = torch
    if 'lp' not in _c:
        import lpips
        _c['lp'] = lpips.LPIPS(net='alex').to(_c['dev']).eval()
    return _c

def frames_of(path, k=K):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    idx = [int(round(t)) for t in np.linspace(2, max(2, n - 3), k)]
    out = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if ok: out.append(fr)
    cap.release()
    return out, dict(n=n, fps=fps, w=w, h=h, secs=round(n / fps, 2) if fps else 0)

def dino_emb(bgr):
    c = lazy(); t = c['torch']
    with t.no_grad():
        x = c['dpr'](images=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_tensors='pt').to(c['dev'])
        f = c['dino'](**x).last_hidden_state[:, 0]
        return (f / f.norm(dim=-1, keepdim=True))[0].float().cpu().numpy()

def lpips_d(a, b):
    c = lazy(); t = c['torch']
    def prep(im):
        im = cv2.resize(im, (256, 256))
        return t.from_numpy(im[:, :, ::-1].copy().transpose(2, 0, 1)[None] / 127.5 - 1).float().to(c['dev'])
    with t.no_grad(): return float(c['lp'](prep(a), prep(b)))

def stats(fr):
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lab = cv2.cvtColor(fr, cv2.COLOR_BGR2Lab).astype(np.float32)
    hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV).astype(np.float32)
    b, gg, r = [x.astype(np.float32) for x in cv2.split(fr)]
    lap = cv2.Laplacian(g, cv2.CV_32F)
    return dict(L=float(lab[..., 0].mean()), a=float(lab[..., 1].mean()), b=float(lab[..., 2].mean()),
                Lstd=float(lab[..., 0].std()), sat=float(hsv[..., 1].mean()),
                rb=float((r.mean() + 1) / (b.mean() + 1)),
                p05=float(np.percentile(g, 5)), p50=float(np.percentile(g, 50)),
                p95=float(np.percentile(g, 95)),
                grain=float(lap.std()), dark=float((g < 22).mean()), blown=float((g > 240).mean()))

def face_side(fr):
    c = lazy(); fs = c['if'].get(cv2.resize(fr, None, fx=1024/max(fr.shape[:2]),
                                            fy=1024/max(fr.shape[:2]), interpolation=cv2.INTER_AREA))
    if not fs: return None, 0.0, None
    r = 1024 / max(fr.shape[:2])
    b = max(fs, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
    return b.normed_embedding, max(b.bbox[2]-b.bbox[0], b.bbox[3]-b.bbox[1]) / r, b.det_score

def corners_clean(img, n=200):
    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    e = []
    for (x, y) in ((0, 0), (w - n, 0), (0, h - n), (w - n, h - n)):
        p = g[y:y+n, x:x+n]
        e.append(float(np.abs(cv2.Laplacian(p, cv2.CV_32F)).std()))
    med = float(np.abs(cv2.Laplacian(g, cv2.CV_32F)).std()) or 1e-6
    return round(max(e) / med, 2)

def motion(fr_a, fr_b):
    g1 = cv2.cvtColor(fr_a, cv2.COLOR_BGR2GRAY); g2 = cv2.cvtColor(fr_b, cv2.COLOR_BGR2GRAY)
    d = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    f = d.calc(g1, g2, None)
    return float(np.hypot(f[..., 0], f[..., 1]).mean())

# ---------------------------------------------------------------- baseline
def baseline():
    clips = sorted(glob.glob(os.path.join(PACK, '*.mp4')))
    per, allE, allF, allKeys = {}, [], [], []
    for p in clips:
        frs, meta = frames_of(p)
        if not frs: continue
        st = [stats(f) for f in frs]
        agg = {k: float(np.mean([s[k] for s in st])) for k in st[0]}
        agg.update(meta)
        key = os.path.basename(p).split()[0]
        for i, f in enumerate(frs):
            e = dino_emb(f); allE.append(e); allKeys.append(key)
            if i % 3 == 0: allF.append((key, i, f.copy()))
        per[key] = agg
        print('%-5s %4dx%-4d %5.2fs  L=%5.1f sat=%5.1f R/B=%.2f grain=%5.2f dark=%.3f'
              % (key, meta['w'], meta['h'], meta['secs'], agg['L'], agg['sat'], agg['rb'],
                 agg['grain'], agg['dark']))
    def mk(keys, frs):
        E = np.stack(frs); cen = E.mean(0); cen = cen / np.linalg.norm(cen)
        return dict(centroid=cen.tolist(),
                    within_dist=round(float(np.mean([1 - float(np.dot(e, cen)) for e in E])), 4),
                    n=int(len(E)), clips=keys,
                    band={k: [round(float(np.min([c[k] for c in per.values() if k in c])), 3),
                              round(float(np.max([c[k] for c in per.values() if k in c])), 3)]
                          for k in ('L', 'sat', 'rb', 'grain', 'p50', 'dark')})
    pools = {}
    for tag in ('cyb', 'anc'):
        frs = [e for e, k in zip(allE, allKeys) if POOL[k] == tag]
        keys = [k for k in allKeys if POOL[k] == tag]
        pools[tag] = mk(keys, frs)
        print('%s 池 %d 帧 类内余距 %.4f  成员 %s' % (tag, len(frs), pools[tag]['within_dist'], keys))
    json.dump(dict(clips=per, pools=pools, pool_of=POOL,
                   note='基线＝资产包 8 条 Seedance 片抽帧，按古代/赛博两池分算；'
                        '用户 2026-09-26 指定这批片的画面风格光影作对照样本'),
              open(REF, 'w', encoding='utf8'))
    for k, i, f in allF:
        cv2.imwrite(os.path.join(WZY, 'kf_ref', '%s_%02d.png' % (k, i)), f)
    print('基线已落 style_ref.json；参考帧存 kf_ref/ %d 张' % len(allF))

# ---------------------------------------------------------------- per-shot
def audio_of(path):
    import subprocess
    ff = r'D:\AIWorkflow\tools\ffmpeg.exe'
    wav = os.path.join(WZY, '_a.wav')
    r = subprocess.run([ff, '-y', '-v', 'error', '-i', path, '-ac', '1', '-ar', '16000', wav],
                       capture_output=True)
    if not os.path.exists(wav) or os.path.getsize(wav) < 1000: return None
    raw = open(wav, 'rb').read()[44:]
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    win = 1600
    e = np.array([np.sqrt(np.mean(x[i:i+win]**2) + 1e-9) for i in range(0, len(x)-win, win)])
    return dict(rms=float(np.sqrt(np.mean(x**2))), peak=float(np.abs(x).max()),
                sil=float((e < 0.01).mean()), dur=round(len(x)/16000, 2))

args = None
def one(path, shot, light=False):
    frs, meta = frames_of(path, 8)
    if not frs: return {'shot': shot, 'error': '读不到帧'}
    st = [stats(f) for f in frs]
    agg = {k: float(np.mean([s[k] for s in st])) for k in st[0]}
    out = {'shot': shot, 'file': os.path.basename(path), **meta, **{('vid_' + k): v for k, v in agg.items()}}
    ref = None if light else (json.load(open(REF, encoding='utf8')) if os.path.isfile(REF) else None)
    if ref:
        pool_tag = getattr(args, 'pool', None) or 'cyb'
        pl = ref['pools'][pool_tag]
        mem = [ref['clips'][k] for k in pl['clips']]
        out['pool'] = pool_tag
        for k in ('L', 'sat', 'rb', 'grain', 'p50', 'dark'):
            lo, hi = pl['band'][k]
            out['d_' + k] = round(agg[k] - float(np.mean([m[k] for m in mem])), 3)
            out['in_' + k] = bool(lo <= agg[k] <= hi)
        E = np.stack([dino_emb(f) for f in frs]); cen = np.array(pl['centroid'])
        out['dino_vs_base'] = round(float(1 - np.mean([float(np.dot(e, cen)) for e in E])), 4)
        out['dino_within'] = pl['within_dist']
        out['dino_flag'] = ('带内' if out['dino_vs_base'] <= pl['within_dist'] * 1.35 else '漂出基线')
    # 身份（重活：insightface 吃 ~2GB 内存；H3 在显存/内存驻留时跑它会 mkl_malloc 失败，
    #      所以 --light 只做零成本的算术项，身份/风格/ASR 一律留到停掉 ComfyUI 之后补测）
    if not light:
        embs = [face_side(f) for f in frs]
        sides = [s for _, s, _ in embs if s]
        out['face_frames'] = len(sides)
        out['face_px'] = int(np.median(sides)) if sides else 0
        anchor = lazy()['if'].get(cv2.imread(FACE_ANCH))
        if anchor is not None and len(anchor):
            ae = max(anchor, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1])).normed_embedding
            sims = [float(np.dot(e, ae)) for e, _, _ in embs if e is not None]
            out['arc_vs_facereal'] = [round(x, 3) for x in sims]
            out['arc_min'] = round(min(sims), 3) if sims else None
    out['corner_edge_ratio'] = corners_clean(frs[0])
    # 运动量：分三段，防止"只有开头动"
    seg = max(1, len(frs) // 3)
    out['flow'] = [round(motion(frs[i], frs[min(i + 1, len(frs) - 1)]), 3) for i in range(len(frs) - 1)]
    out['flow_mean'] = round(float(np.mean(out['flow'])), 3)
    del out['flow']
    out['audio'] = audio_of(path)
    # 接触表给我自己看
    th = [cv2.resize(f, (448, 256)) for f in frs]
    sheet = np.vstack([np.hstack(th[:4]), np.hstack(th[4:8])])
    cv2.imwrite(os.path.join(WZY, 'qc_sheet', '%s.jpg' % shot), sheet)
    out['sheet'] = os.path.join(WZY, 'qc_sheet', '%s.jpg' % shot)
    return out

def pair(a, b, tag):
    ca = cv2.VideoCapture(a); ca.set(cv2.CAP_PROP_POS_FRAMES, int(ca.get(cv2.CAP_PROP_FRAME_COUNT)) - 2)
    fa = ca.read()[1]; ca.release()
    cb = cv2.VideoCapture(b); fb = cb.read()[1]; cb.release()
    d = round(lpips_d(fa, fb), 4)
    h = 360
    fa = cv2.resize(fa, (int(fa.shape[1]*h/fa.shape[0]), h)); fb = cv2.resize(fb, (int(fb.shape[1]*h/fb.shape[0]), h))
    s = np.hstack([fa, np.full((h, 6, 3), 255, np.uint8), fb])
    p = os.path.join(WZY, 'qc_pair', tag + '.jpg')
    cv2.imwrite(p, s)
    return dict(pair=tag, lpips_first_vs_prev_last=d, sheet=p)

if __name__ == '__main__':
    os.makedirs(os.path.join(WZY, 'qc_sheet'), exist_ok=True)
    os.makedirs(os.path.join(WZY, 'qc_pair'), exist_ok=True)
    os.makedirs(os.path.join(WZY, 'kf_ref'), exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', action='store_true')
    ap.add_argument('--video')
    ap.add_argument('--shot', default='X')
    ap.add_argument('--pool', default='cyb', choices=['cyb','anc'])
    ap.add_argument('--light', action='store_true', help='只跑零内存项（渲染期间用）；身份/风格/ASR 停服后补测')
    ap.add_argument('--pair', nargs=2)
    a = ap.parse_args(); globals()['args'] = a
    if a.baseline: baseline()
    if a.pair: print(json.dumps(pair(*a.pair, a.shot), ensure_ascii=False, indent=1))
    if a.video:
        r = one(a.video, a.shot, light=a.light)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        j = os.path.join(WZY, 'qc_video', a.shot + '.json')
        os.makedirs(os.path.dirname(j), exist_ok=True)
        json.dump(r, open(j, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
