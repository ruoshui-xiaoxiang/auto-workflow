# -*- coding: utf-8 -*-
"""成片体检：参数 + 运动量 + 抽帧 + 音轨检测（不依赖 ffmpeg）"""
import sys, os, struct, json
import cv2, numpy as np

path = sys.argv[1]
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)

cap = cv2.VideoCapture(path)
fps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"fps={fps:.2f} frames={n} size={w}x{h} dur={n/fps:.2f}s")

frames, grays = [], []
while True:
    ok, f = cap.read()
    if not ok:
        break
    frames.append(f)
    grays.append(cv2.cvtColor(cv2.resize(f, (736, 416)), cv2.COLOR_BGR2GRAY))
cap.release()
print(f"decoded={len(frames)}")

mags = []
for i in range(1, len(grays)):
    flow = cv2.calcOpticalFlowFarneback(grays[i-1], grays[i], None, 0.5, 3, 15, 3, 5, 1.2, 0)
    mags.append(float(np.sqrt(flow[..., 0]**2 + flow[..., 1]**2).mean()))
mags = np.array(mags)
print(f"flow_mean={mags.mean():.3f} flow_med={np.median(mags):.3f} flow_p90={np.percentile(mags,90):.3f} "
      f"frozen={(mags<0.35).sum()} ({(mags<0.35).mean():.0%})")

# 抽 5 帧
picks = [0, len(frames)//4, len(frames)//2, len(frames)*3//4, len(frames)-1]
for idx in picks:
    p = os.path.join(outdir, f"f{idx:04d}.jpg")
    cv2.imwrite(p, frames[idx], [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("frame", p)

# Stability of the colossal mass: where its lower edge sits, and how much of the frame it occupies.
mass_bottom, mass_cov, top_luma = [], [], []
for f in frames:
    y = cv2.cvtColor(cv2.resize(f, (256, 144)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    dark = y < 90
    rows = dark.mean(axis=1)
    idx = np.where(rows > 0.30)[0]
    mass_bottom.append(int(idx.max()) if idx.size else -1)
    mass_cov.append(float(dark.mean()))
    top_luma.append(float(y[:29].mean()))
mb = np.array(mass_bottom, float)
cov = np.array(mass_cov, float)
print(f"mass_bottom: first={mb[0]:.0f} last={mb[-1]:.0f} std={mb.std():.2f} "
      f"min={mb.min():.0f} max={mb.max():.0f} (of 144)")
print(f"mass_coverage: first={cov[0]:.3f} last={cov[-1]:.3f} min={cov.min():.3f} max={cov.max():.3f}")
print(f"top_band_luma: first={top_luma[0]:.1f} last={top_luma[-1]:.1f}")

# Real container and audio decoding; string matches cannot prove stream validity.
import av
report = dict(file=path, width=w, height=h, fps=fps, decoded_frames=len(frames),
              duration_seconds=len(frames)/fps, flow_mean=float(mags.mean()),
              flow_median=float(np.median(mags)),
              low_motion_fraction=float((mags < 0.35).mean()))
with av.open(path) as media:
    report['streams'] = [dict(type=s.type, codec=s.codec_context.name,
        duration_seconds=float(s.duration*s.time_base) if s.duration is not None else None)
        for s in media.streams]
    if 'prompt' in media.metadata:
        try:
            report['generation_workflow'] = json.loads(media.metadata['prompt'])
        except ValueError:
            pass
    if media.streams.audio:
        peak, sumsq, count = 0.0, 0.0, 0
        for af in media.decode(audio=0):
            x = af.to_ndarray()
            denom = float(2**(np.iinfo(x.dtype).bits-1)) if np.issubdtype(x.dtype, np.integer) else 1.0
            x = x.astype(np.float64)/denom
            peak = max(peak, float(np.abs(x).max()))
            sumsq += float(np.square(x).sum()); count += x.size
        report['audio'] = dict(decoded_samples=count, peak_dbfs=float(20*np.log10(max(peak,1e-12))),
            rms_dbfs=float(10*np.log10(max(sumsq/max(count,1),1e-24))))
# Half-second contact sheets retain the complete frame for visual QA.
indices = list(range(0, len(frames), max(1, round(fps/2))))
if indices[-1] != len(frames)-1:
    indices.append(len(frames)-1)
for start in range(0, len(indices), 12):
    batch = indices[start:start+12]
    sheet = np.full((int(np.ceil(len(batch)/3))*206, 1080, 3), 245, np.uint8)
    for slot, idx in enumerate(batch):
        tile = cv2.resize(frames[idx], (360, 180))
        yy, xx = (slot//3)*206, (slot%3)*360
        sheet[yy:yy+180,xx:xx+360] = tile
        cv2.putText(sheet, f'{idx/fps:.2f}s | frame {idx}', (xx+8,yy+198),
                    cv2.FONT_HERSHEY_SIMPLEX,0.45,(20,20,20),1,cv2.LINE_AA)
    sp = os.path.join(outdir, f'contact_{start//12+1}.jpg')
    cv2.imencode('.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY,92])[1].tofile(sp)
    print('contact',sp)
with open(os.path.join(outdir, 'qa.json'), 'w', encoding='utf-8') as fp:
    json.dump(report, fp, ensure_ascii=False, indent=2)
print(json.dumps({k:v for k,v in report.items() if k != 'generation_workflow'}, ensure_ascii=False))
