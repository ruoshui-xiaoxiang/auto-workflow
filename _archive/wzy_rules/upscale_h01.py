# -*- coding: utf-8 -*-
"""H01 换脸视频超分：拆帧 -> ComfyUI 4x-UltraSharp -> 缩放 1080p -> 重编码保留音轨。"""
import os, sys, subprocess, tempfile, json, time, shutil, urllib.request

SRC = r'D:/AIWorkflow/tmp/wzy/faceswap_out/H01_faceswap.mp4'
OUT = r'D:/AIWorkflow/tmp/wzy/faceswap_out/H01_faceswap_1080p.mp4'
FFMPEG = r'D:/AIWorkflow/tools/ffmpeg.exe'
HOST = 'http://127.0.0.1:8189'
INPUT_DIR = r'D:/AIWorkflow/ComfyUI_H3/ComfyUI/input'
OUTPUT_DIR = r'D:/AIWorkflow/ComfyUI_H3/output'
PREFIX = 'sr_h01_' + str(int(time.time()))[-6:]

def http_json(method, url, data=None):
    req = urllib.request.Request(url, method=method)
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, body, timeout=600) as r:
        return json.loads(r.read().decode('utf-8'))

# 1. 拆帧
work = tempfile.mkdtemp(prefix='sr_', dir='D:/AIWorkflow/tmp/')
subprocess.run([FFMPEG, '-y', '-v', 'error', '-i', SRC, os.path.join(work, 'f%05d.png')], check=True)
frames = sorted(f for f in os.listdir(work) if f.endswith('.png'))
print('拆帧', len(frames), '帧', flush=True)

wf = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "__F__"}},
    "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x-UltraSharp.pth"}},
    "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
    "4": {"class_type": "ImageScale", "inputs": {"image": ["3", 0], "upscale_method": "lanczos",
            "width": 1920, "height": 1080, "crop": "disabled"}},
    "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": PREFIX}},
}

def submit_one(fname):
    g = json.loads(json.dumps(wf).replace('__F__', fname))
    r = http_json('POST', HOST + '/prompt', {'prompt': g})
    pid = r['prompt_id']
    while True:
        h = http_json('GET', HOST + '/history/' + pid)
        if pid in h and h[pid].get('outputs'):
            for node_out in h[pid]['outputs'].values():
                for im in node_out.get('images', []):
                    src = os.path.join(OUTPUT_DIR, im.get('subfolder', ''), im['filename'])
                    if os.path.isfile(src):
                        return src
        time.sleep(2)

tmp_in = os.path.join(INPUT_DIR, 'sr_h01_tmp.png')
seq = os.path.join(work, 'seq')
os.makedirs(seq, exist_ok=True)
for i, f in enumerate(frames):
    shutil.copyfile(os.path.join(work, f), tmp_in)
    src = submit_one('sr_h01_tmp.png')
    shutil.copy2(src, os.path.join(seq, 'f%05d.png' % i))
    if (i + 1) % 30 == 0:
        print('  超分 %d/%d' % (i + 1, len(frames)), flush=True)
if os.path.isfile(tmp_in):
    os.remove(tmp_in)
print('超分完成', len(frames), '帧', flush=True)

subprocess.run([FFMPEG, '-y', '-v', 'error', '-framerate', '24',
                '-i', os.path.join(seq, 'f%05d.png'), '-i', SRC,
                '-map', '0:v', '-map', '1:a?',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', OUT], check=True)
print('DONE ->', OUT, flush=True)
