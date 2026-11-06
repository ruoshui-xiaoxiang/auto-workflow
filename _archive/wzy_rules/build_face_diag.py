# -*- coding: utf-8 -*-
"""生成一份人脸漂移诊断图：上排=参考图 / 下排=8 镜首帧关键人脸裁剪+ArcFace相似度标注。"""
import json
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

REF = Path(r'E:/创作/武昭君仪/首帧图/可灵参考素材')
OUT = Path(r'E:/创作/武昭君仪/首帧图/可灵机位图')
SAVE = Path(r'E:/创作/武昭君仪/首帧图/可灵机位图/_人物漂移诊断.jpg')

CJK_FONT = Path(r'C:/Windows/Fonts/msyh.ttc')
font = ImageFont.truetype(str(CJK_FONT), 22)
font_lg = ImageFont.truetype(str(CJK_FONT), 32)
font_sm = ImageFont.truetype(str(CJK_FONT), 18)

with open('D:/AIWorkflow/tmp/wzy/face_check.json', 'r', encoding='utf8') as f:
    fc = json.load(f)

def load_cv(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)

def cv_to_pil(cv_img):
    return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))

def crop_face_from_shot(shot_path, bbox):
    img = load_cv(shot_path)
    x1,y1,x2,y2 = bbox
    h, w = img.shape[:2]
    x1, y1 = max(0,x1), max(0,y1)
    x2, y2 = min(w,x2), min(h,y2)
    # pad 30%
    pw = int((x2-x1)*0.3); ph = int((y2-y1)*0.3)
    x1 = max(0, x1-pw); y1 = max(0, y1-ph)
    x2 = min(w, x2+pw); y2 = min(h, y2+ph)
    crop = img[y1:y2, x1:x2]
    crop = cv2.resize(crop, (180, 240), interpolation=cv2.INTER_LANCZOS4)
    return crop

# 参考人脸裁剪
ref_jy = load_cv(REF/'jy_正面.png')
ref_hh = load_cv(REF/'hh_正面.png')
# 简单按脸部区域裁剪（取上半身中心偏上）
ref_jy_crop = cv2.resize(ref_jy[40:520, 250:470], (180, 240), interpolation=cv2.INTER_LANCZOS4)
ref_hh_crop = cv2.resize(ref_hh[60:540, 200:480], (180, 240), interpolation=cv2.INTER_LANCZOS4)

# 构建大图：4 行 x 9 列
# 第 1 行：参考君仪 + 8 镜君仪裁剪
# 第 2 行：参考混混 + 8 镜混混裁剪
# 第 3 行：参考大图
# 第 4 行：8 镜大图（缩小）

shots = ['P1A','P1B','P1C','P1D','P2A','P2B','P2C','P2D']
N = len(shots)
cell_w, cell_h = 180, 240
header_h = 60
pad = 8

total_w = cell_w * (N + 1) + pad * (N + 2)
total_h = (cell_h + header_h) * 2 + 40

img = Image.new('RGB', (total_w, total_h), (245, 245, 248))
draw = ImageDraw.Draw(img)

# 第 1 行：君仪
y0 = 0
draw.text((10, y0+15), '君仪参考 → 8 镜君仪脸（sim=该脸vs参考的ArcFace余弦相似度，正常锁定应≥0.5）',
          fill=(20, 20, 20), font=font_lg)
img.paste(cv_to_pil(ref_jy_crop), (pad, y0+header_h))
draw.text((pad, y0+header_h+cell_h+2), '参考', fill=(0,0,0), font=font_sm)

for i, shot in enumerate(shots):
    x = pad + (i+1)*(cell_w+pad)
    shot_data = next((r for r in fc if r['shot']==shot), None)
    if not shot_data: continue
    # 找 sim_jy 最高的人脸
    faces = shot_data['faces']
    if not faces: continue
    best = max(faces, key=lambda f: f['sim_jy'])
    if best['sim_jy'] > 0.05:  # 至少有点相似
        crop = crop_face_from_shot(OUT/f'{shot}_首帧.png', best['bbox'])
        img.paste(cv_to_pil(crop), (x, y0+header_h))
        color = 'red' if best['sim_jy'] < 0.3 else ('orange' if best['sim_jy'] < 0.5 else 'green')
        draw.text((x, y0+header_h+cell_h+2), f'{shot}', fill=color, font=font_sm)
        draw.text((x+50, y0+header_h+cell_h+2), f'sim={best["sim_jy"]:.2f}', fill=color, font=font_sm)

# 第 2 行：混混
y0 = header_h + cell_h + 40
draw.text((10, y0-30), '混混参考 → 8 镜混混脸（同上）',
          fill=(20, 20, 20), font=font_lg)
img.paste(cv_to_pil(ref_hh_crop), (pad, y0))
draw.text((pad, y0+cell_h+2), '参考', fill=(0,0,0), font=font_sm)

for i, shot in enumerate(shots):
    x = pad + (i+1)*(cell_w+pad)
    shot_data = next((r for r in fc if r['shot']==shot), None)
    if not shot_data: continue
    faces = shot_data['faces']
    if not faces: continue
    best = max(faces, key=lambda f: f['sim_hh'])
    if best['sim_hh'] > 0.05:
        crop = crop_face_from_shot(OUT/f'{shot}_首帧.png', best['bbox'])
        img.paste(cv_to_pil(crop), (x, y0))
        color = 'red' if best['sim_hh'] < 0.3 else ('orange' if best['sim_hh'] < 0.5 else 'green')
        draw.text((x, y0+cell_h+2), f'{shot}', fill=color, font=font_sm)
        draw.text((x+50, y0+cell_h+2), f'sim={best["sim_hh"]:.2f}', fill=color, font=font_sm)

img.save(SAVE, quality=85)
print(f'已写 {SAVE}')