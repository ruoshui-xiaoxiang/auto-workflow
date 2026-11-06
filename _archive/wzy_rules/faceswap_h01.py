# -*- coding: utf-8 -*-
"""H01 换脸：把武君仪正脸（junyi_face_ancient）逐帧换到 H3 草稿上，保留原音轨。"""
import os, sys, subprocess, tempfile
import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface.model_zoo import get_model

SRC = r'E:\图像影音资源池\武昭君仪\批次\20260926_212221\video\xn_20260926_212221_00001_.mp4'
FACE = r'E:/图像影音资源池/武昭君仪/素材/face_anchors/dingzhuang/junyi_face_real.png'  # 2026-10-19 迁出 tmp：锚点定妆资产正身在资源池（tmp 不是落点，而旧文档还写着tmp「用完即清」——照做就毁掉这 58 个不可再生文件）。tmp/wzy/anchors 现是指向它的 junction。
OUT = r'D:/AIWorkflow/tmp/wzy/faceswap_out/H01_hd_faceswap.mp4'
FFMPEG = r'D:/AIWorkflow/tools/ffmpeg.exe'

os.makedirs(os.path.dirname(OUT), exist_ok=True)

print('[1/4] 加载 FaceAnalysis + inswapper ...', flush=True)
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))
swapper = get_model(r'C:/Users/若水/.insightface/models/inswapper_128.onnx', download=False, download_zip=False)

print('[2/4] 读取目标脸 ...', flush=True)
def imread_u(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
tgt = imread_u(FACE)
tfs = app.get(tgt)
if not tfs:
    raise SystemExit('目标脸检测不到脸')
tface = max(tfs, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))

cap = cv2.VideoCapture(SRC)
fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
print('[3/4] 逐帧换脸 %d 帧 @ %dx%d ...' % (n, W, H), flush=True)

tmp = tempfile.mkdtemp(prefix='swap_')
idx = 0
swapped = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    faces = app.get(frame)
    for f in faces:
        if (f.bbox[2]-f.bbox[0]) < 40:   # 脸太小跳过（远景/背对）
            continue
        frame = swapper.get(frame, f, tface, paste_back=True)
        swapped += 1
    cv2.imwrite(os.path.join(tmp, 'f%05d.png' % idx), frame)
    idx += 1
    if idx % 30 == 0:
        print('  ... %d/%d 帧，换脸 %d 次' % (idx, n, swapped), flush=True)
cap.release()
print('[4/4] 重编码（保留原音轨）...', flush=True)

# 视频用换脸后的帧，音轨从原片复制
subprocess.run([FFMPEG, '-y', '-v', 'error', '-framerate', str(fps),
                '-i', os.path.join(tmp, 'f%05d.png'),
                '-i', SRC,
                '-map', '0:v', '-map', '1:a?',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', OUT], check=True)
print('DONE ->', OUT, '换脸', swapped, '次', flush=True)
