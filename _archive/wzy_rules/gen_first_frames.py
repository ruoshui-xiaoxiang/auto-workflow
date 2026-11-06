# -*- coding: utf-8 -*-
"""云端 Seedream 出首帧 H01 / H06 / H13（复用 h3_shots 的 kf_refs + ark_img）。"""
import sys, os
sys.path.insert(0, r'D:/AIWorkflow/tmp/jianlai_test')
import ark_img
sys.path.insert(0, r'D:/AIWorkflow/tmp/wzy')
import h3_shots as H

KF_OUT = r'D:/AIWorkflow/tmp/wzy/kf_out'
os.makedirs(KF_OUT, exist_ok=True)
FF = {'H01': 'H01_first.png', 'H06': 'H06_first.png', 'H13': 'H13b_s0.png'}
SEED = 20260926
W, H_ = 1344, 768

by = {s['id']: s for s in H.SHOTS}
for sid in ('H01', 'H06', 'H13'):
    s = by[sid]
    prompt = open(os.path.join(H.OUT, '%s_kf.txt' % sid), encoding='utf-8').read().strip()
    refs = H.kf_refs(s)
    imgs = [ark_img.data_uri(p) for p in refs]
    print('[生成 %s] 提示词 %d 字 / 锚点 %d 张' % (sid, len(prompt), len(refs)), flush=True)
    try:
        urls = ark_img.call(prompt, imgs, SEED, W, H_)
        dst = os.path.join(KF_OUT, FF[sid])
        ark_img.fetch(urls[0], dst)
        print('  OK %s -> %s (%d KB)' % (sid, FF[sid], os.path.getsize(dst) // 1024), flush=True)
    except Exception as e:
        print('  FAIL %s: %s' % (sid, str(e)[:200]), flush=True)
print('DONE', flush=True)
