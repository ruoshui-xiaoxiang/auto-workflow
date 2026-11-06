# -*- coding: utf-8 -*-
"""验证 newest_mp4 的两条找法都能命中 03:30 那次被误判的真实 stdout。"""
import os, sys, json
sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
import run_batch as R

led = json.load(open(R.LEDGER, encoding='utf8'))
tail = led['H05']['tail']
print('regex hits :', R._FILE_RE.findall(tail))
p = R.newest_mp4(1770000000, tail)          # 一个很早的 ts，只看 stdout 这条路
print('via stdout :', p, os.path.isfile(p) if p else None)
p2 = R.newest_mp4(os.path.getmtime(r'E:\图像影音资源池\武昭君仪\批次\20260926_022703\video') - 5, '')
print('via scan   :', p2, os.path.isfile(p2) if p2 else None)
