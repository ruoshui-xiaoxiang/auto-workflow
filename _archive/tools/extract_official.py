# -*- coding: utf-8 -*-
"""从用户给的提示词全集 txt 里原样抽出 12 镜，存成引擎可读的 .txt。

严格逐字提取代码块内容，不做任何修改（用户要求"不用做改动，直接用"）。
用法：python extract_official.py
"""
import io
import re
from pathlib import Path

SRC = Path(r'E:/创作/_待审文档/新建 文本文档.txt')
OUT = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts_官方三段式')

txt = SRC.read_text(encoding='utf8')
OUT.mkdir(parents=True, exist_ok=True)

# 匹配 "#### P1A · 拦路｜中幅度慢速 Push In" 之后第一个代码块
pat = re.compile(r'####\s*(P\d[A-D])\s*·\s*([^｜\n]+)｜([^\n]+)\n+```\n(.*?)\n```', re.S)
hits = pat.findall(txt)
print('抽到 %d 镜' % len(hits))
for sid, name, cam, body in hits:
    body = body.strip()
    p = OUT / ('wuzhaojunyi_三阶%s_%s.txt' % (sid, name.strip()))
    p.write_text(body + '\n', encoding='utf8')
    first = body.split('\n')[0]
    print('  %s %-4s %5d 字  首行=%s' % (sid, name.strip(), len(body), first[:40]))
print('\n落盘目录：', OUT)
