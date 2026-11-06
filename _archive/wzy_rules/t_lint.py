# -*- coding: utf-8 -*-
"""看 decor 规则到底被哪个词点着的——H07 改前 0 分、改后 5 分，得知道差在哪个词。"""
import sys, io
sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
import prompt_lint as L
import h3_shots as H

p = io.open(r'D:\AIWorkflow\tmp\wzy\h3\H07_video.txt', encoding='utf8').read()
old = p.replace('白麻布裹长杆', '白麻布裹枪')          # 复原改动前的基调写法做对照
for tag, t in (('改后', p), ('近似改前', old)):
    print(tag, 'STRUCT命中:', [w for w in L.STRUCT_ONLY if w in t],
          '| 服装:', '服装' in t, '| DECOR命中:', [w for w in L.DECOR_WORDS if w in t])
print('DECOR_WORDS:', sorted(L.DECOR_WORDS))
print('STRUCT_ONLY:', sorted(L.STRUCT_ONLY))
