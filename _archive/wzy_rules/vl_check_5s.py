# -*- coding: utf-8 -*-
"""5 秒视频 VL 内容核对：抽 6 帧 + qwen-vl-plus。用法:
python vl_check_5s.py <视频路径> <问题> <输出帧目录>
"""
import base64
import subprocess
import sys
from pathlib import Path

FFMPEG = "D:/AIWorkflow/tools/ffmpeg.exe"
src, question, frame_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
frame_dir.mkdir(parents=True, exist_ok=True)
for f in frame_dir.glob("*.png"):
    f.unlink()
subprocess.run([FFMPEG, "-y", "-v", "error", "-i", src,
                "-vf", "select='eq(n,0)+eq(n,24)+eq(n,49)+eq(n,74)+eq(n,99)+eq(n,123)'",
                "-vsync", "0", str(frame_dir / "f_%02d.png")], check=True)

KEY_FILE = Path("E:/密钥文件/阿里多模态.txt")
lines = KEY_FILE.read_text(encoding="utf-8").strip().splitlines()
key = lines[0].strip()
base = lines[1].strip().rstrip("/") if len(lines) > 1 else "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-vl-plus"

labels = ["0s", "1s", "2s", "3s", "4s", "5.2s"]
answers = []
for i, lbl in enumerate(labels, 1):
    img = frame_dir / f"f_{i:02d}.png"
    if not img.is_file():
        print(f"[{lbl}] 缺帧", flush=True)
        continue
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": question}]}],
        "max_tokens": 600,
    }
    r = __import__("requests").post(f"{base}/chat/completions",
                                    headers={"Authorization": f"Bearer {key}"},
                                    json=payload, timeout=120)
    try:
        ans = r.json()["choices"][0]["message"]["content"]
    except Exception:
        ans = "API错误: " + r.text[:200]
    answers.append(f"[{lbl}] {ans}")
    print(answers[-1], flush=True)
print("=====汇总=====")
print("\n".join(answers))
