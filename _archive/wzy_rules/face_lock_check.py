# -*- coding: utf-8 -*-
"""用 ArcFace (insightface buffalo_l) 对比 8 镜首帧与参考图的人脸相似度，确认人物漂移情况。"""
import sys, json
from pathlib import Path
import numpy as np
import cv2
from insightface.app import FaceAnalysis

REF = Path(r'E:/创作/武昭君仪/首帧图/可灵参考素材')
OUT = Path(r'E:/创作/武昭君仪/首帧图/可灵机位图')
PY312 = r'C:/Users/若水/AppData/Local/Programs/Python/Python312/python.exe'

app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

def best_face(img):
    """返回图中最大人脸的 embedding（512 维），无人脸返回 None。"""
    if img is None:
        return None
    faces = app.get(img)
    if not faces:
        return None
    faces = sorted(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]), reverse=True)
    return faces[0].normed_embedding

def crop_face_box(img, face):
    """裁剪出人脸 bbox 区域。"""
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    return img[y1:y2, x1:x2]

def cos(a, b):
    return float(np.dot(a, b))

def load(path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    return img

# 参考人脸
jy_ref = best_face(load(REF / 'jy_正面.png'))
hh_ref = best_face(load(REF / 'hh_正面.png'))

if jy_ref is None or hh_ref is None:
    print('参考图未检测到人脸'); sys.exit(1)

print(f'参考: 君仪(jy_正面) embedding={jy_ref.shape}, 混混(hh_正面) embedding={hh_ref.shape}')
print()

# 8 镜首帧
shots = ['P1A', 'P1B', 'P1C', 'P1D', 'P2A', 'P2B', 'P2C', 'P2D']
results = []
for shot in shots:
    img = load(OUT / f'{shot}_首帧.png')
    if img is None:
        continue
    faces = app.get(img)
    faces = sorted(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]), reverse=True)
    print(f'[{shot}] 检测到 {len(faces)} 张人脸')
    info = {'shot': shot, 'faces': []}
    for i, f in enumerate(faces[:3]):
        s_jy = cos(f.normed_embedding, jy_ref)
        s_hh = cos(f.normed_embedding, hh_ref)
        x1,y1,x2,y2 = [int(v) for v in f.bbox]
        print(f'  face{i} bbox=({x1},{y1},{x2},{y2}) area={(x2-x1)*(y2-y1)} sim_jy={s_jy:.3f} sim_hh={s_hh:.3f}')
        info['faces'].append({'bbox': (x1,y1,x2,y2), 'area': (x2-x1)*(y2-y1),
                              'sim_jy': s_jy, 'sim_hh': s_hh})
    results.append(info)

# 关键结论
print()
print('=== 关键发现 ===')
for r in results:
    shot = r['shot']
    if not r['faces']:
        print(f'{shot}: 无人脸'); continue
    # 找最大的两个人脸：按 x 坐标判断左右
    faces = sorted(r['faces'], key=lambda f: f['area'], reverse=True)[:2]
    faces = sorted(faces, key=lambda f: (f['bbox'][0]+f['bbox'][2])//2)  # 左→右
    if len(faces) >= 2:
        l, rt = faces[0], faces[1]
        l_label = '君仪' if l['sim_jy'] > l['sim_hh'] else '混混'
        rt_label = '君仪' if rt['sim_jy'] > rt['sim_hh'] else '混混'
        print(f"{shot}: 左侧像{('君仪' if l['sim_jy']>l['sim_hh'] else '混混')}(jy_sim={l['sim_jy']:.2f}/hh_sim={l['sim_hh']:.2f})  "
              f"右侧像{('君仪' if rt['sim_jy']>rt['sim_hh'] else '混混')}(jy_sim={rt['sim_jy']:.2f}/hh_sim={rt['sim_hh']:.2f})")
    else:
        f = faces[0]
        label = '君仪' if f['sim_jy'] > f['sim_hh'] else '混混'
        print(f"{shot}: 唯一人脸像{label}(jy_sim={f['sim_jy']:.2f}/hh_sim={f['sim_hh']:.2f})")

# 保存
Path('D:/AIWorkflow/tmp/wzy/face_check.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
print()
print('已写 face_check.json')