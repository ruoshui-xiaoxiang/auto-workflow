# -*- coding: utf-8 -*-
"""把线稿机位版12镜拼成3x4网格预览。"""
import cv2, numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(r'D:/AIWorkflow/tmp/wzy/preview')
CJK = Path(r'C:/Windows/Fonts/msyh.ttc')
font = ImageFont.truetype(str(CJK), 24)
font_lg = ImageFont.truetype(str(CJK), 36)

shots = ['P1A','P1B','P1C','P1D','P2A','P2B','P2C','P2D','P3A','P3B','P3C','P3D']
imgs = []
for s in shots:
    p = OUT / f'{s}_small.png'
    if not p.exists():
        imgs.append(None); continue
    img = Image.open(p)
    imgs.append(img)

# 3 行 × 4 列
W, H = imgs[0].size
ratio = W/H
nw = 560
nh = int(nw / ratio)
gap = 8
labels_h = 30

total_w = nw * 4 + gap * 5
total_h = (nh + labels_h) * 3 + gap * 4 + 60
canvas = Image.new('RGB', (total_w, total_h), (240, 240, 245))
draw = ImageDraw.Draw(canvas)

draw.text((10, 8), '线稿主体库重出 12 镜首帧（P1A-P3D 全套）—— 身形/发型/服装/武器/机械臂结构均按线稿锁定',
          fill=(20,20,20), font=font_lg)
draw.text((10, 48), 'P1 空手八极 → P2 裹布棍法 → P3 解布裸枪法',
          fill=(80,80,80), font=font)

stage_colors = {'P1':(80,140,200), 'P2':(200,140,80), 'P3':(200,80,80)}

for i, (s, img) in enumerate(zip(shots, imgs)):
    row = i // 4
    col = i % 4
    x = gap + col * (nw + gap)
    y = 80 + row * (nh + labels_h + gap)
    if img is None:
        draw.text((x, y), s + ' (空)', fill='red', font=font)
        continue
    rsz = img.resize((nw, nh), Image.LANCZOS)
    canvas.paste(rsz, (x, y))
    stage = s[:2]
    color = stage_colors.get(stage, (20,20,20))
    draw.text((x, y + nh + 4), s, fill=color, font=font)

save_path = Path(r'E:/创作/武昭君仪/首帧图/线稿机位图/_预览线稿版12镜.jpg')
canvas.save(save_path, quality=85)
print('saved', save_path)