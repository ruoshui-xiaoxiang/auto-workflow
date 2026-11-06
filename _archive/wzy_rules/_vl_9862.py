# -*- coding: utf-8 -*-
"""VL 描述 9862 图布局"""
import base64, requests, glob
from pathlib import Path
from PIL import Image

img = Path(glob.glob(r'E:/创作/武昭君仪/武昭君仪资产包/*9862*.png')[0])
im = Image.open(img)
print('file:', img.name[:70], img.stat().st_size, 'size', im.size)
b64 = base64.b64encode(img.read_bytes()).decode()
lines = Path('E:/密钥文件/阿里多模态.txt').read_text(encoding='utf-8').strip().splitlines()
key = lines[0].strip()
base = lines[1].strip().rstrip('/') if len(lines) > 1 else 'https://dashscope.aliyuncs.com/compatible-mode/v1'
q = ("这是一张武君仪造型展示图。请详细描述画面布局："
     "1)画面里一共有几个人物；"
     "2)每个人物在画面的什么位置（左/中/右，用画面宽度的百分比区间描述，例如最左侧人物约占左起0%到25%的区域）；"
     "3)每个人物的姿势（正面/侧面/背面、全身/半身）；"
     "4)每个人物的服装颜色与款式；"
     "5)指出哪个人物是完整正面全身，并给出它的精确百分比区间。")
payload = {"model": "qwen-vl-plus", "messages": [{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    {"type": "text", "text": q}]}], "max_tokens": 700}
r = requests.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                  json=payload, timeout=120)
print(r.json()["choices"][0]["message"]["content"])
