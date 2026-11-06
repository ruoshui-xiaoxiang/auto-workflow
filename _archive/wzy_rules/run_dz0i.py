# -*- coding: utf-8 -*-
'''I 批：F 风格 + 高马尾锁死，10 张。纯文生图，不挂任何参考图。'''
import io
import json
import os
import sys

sys.path.insert(0, r'D:/AIWorkflow/tmp/jianlai_test')
import ark_img
from dz_prompts import prompt, FACES

OUT = r'D:/AIWorkflow/tmp/wzy/dz0i'
os.makedirs(OUT, exist_ok=True)
SEED0 = 2026100301

res = []
for i in range(len(FACES)):
    k = 'I%d' % (i + 1)
    pr = prompt(i)
    io.open(os.path.join(OUT, k + '.txt'), 'w', encoding='utf-8').write(pr)
    try:
        urls = ark_img.call(pr, [], SEED0 + i, 1536, 2688)
        p = ark_img.fetch(urls[0], os.path.join(OUT, k + '_raw.png'))
        sz = os.path.getsize(p) // 1024
        print('OK', k, sz, 'KB')
        res.append([k, 'ok', sz])
    except Exception as e:
        print('FAIL', k, repr(e)[:160])
        res.append([k, 'fail', repr(e)[:160]])

json.dump(res, io.open(os.path.join(OUT, 'dz0i_result.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('done', sum(1 for r in res if r[1] == 'ok'), '/', len(res))
