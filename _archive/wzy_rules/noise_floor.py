# -*- coding: utf-8 -*-
# 噪声底：闭环（诊断→改→重跑→再比对）的承重前提，没这个数，"改进"两个字不可信。
#
# 要回答的问题只有一个：**同一份提示词重新生成一次，指标会自己晃多少？**
# 晃幅 ≥ 我们的改进幅 → 那"重跑再比对"就是在追噪声，不该做。
# 现在手上的改进幅度样本（E批→F批）：lpalex 0.408→0.356（Δ0.052）、
#                                    dino 0.761→0.777（Δ0.016）、gedge 58→76（Δ18）。
# dino 的 Δ0.016 已经小得可疑，必须先量底。
#
# 两组各 3 张，共 6 张：
#   A 组 同提示词 + **同 seed**   → 测云端是否确定性；若 A 组极差≈0，噪声全部来自 seed
#   B 组 同提示词 + **不同 seed** → 测 seed 抖动，这才是闭环要对抗的底
# 提示词用人审通过的现行版 dz0b2ppp/F1.txt，锚点用现行脸锚＋风格锚（和生产同配置）。
#
# 跑法：py noise_floor.py --go      （不加 --go 只打印计划和预算，不发一次请求）
import io
import json
import os
import sys
import numpy as np

sys.path.insert(0, r'D:/AIWorkflow/tmp/jianlai_test')
D = r'D:/AIWorkflow/tmp/wzy'
OUT = os.path.join(D, 'noise_floor')
FACE = r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/junyi_face_jm2156.png'
STYLE = r'D:/AIWorkflow/tmp/wzy/anchors/dingzhuang/jm_9862_dual_look_labeled.png'
SEED0 = 2026104101
W, H = 1536, 2688
SOURCE = r'D:/AIWorkflow/tmp/wzy/run_dz0b2ppp.py'   # 真源：只从脚本取词，不读批次存档


def live_prompt():
    """执行脚本里 `res = []` 之前的赋值段，拿 PARTS——保证测的是现行版，不是 F 批当时的存档。"""
    src = open(SOURCE, encoding='utf-8').read().split('res = []')[0]
    ns = {}
    exec(compile(src, SOURCE, 'exec'), ns)
    return '\n\n'.join(ns['PARTS'])

PLAN = [('A1', SEED0), ('A2', SEED0), ('A3', SEED0),      # 同 seed ×3
        ('B1', SEED0 + 1), ('B2', SEED0 + 2), ('B3', SEED0 + 3)]

if '--go' not in sys.argv:
    sys.path.insert(0, r'D:/AIWorkflow/tmp/wzy')
    import importlib.util as _u
    _s = _u.spec_from_file_location('prompt_lint', os.path.join(D, 'prompt_lint.py'))
    _lint = _u.module_from_spec(_s)
    _s.loader.exec_module(_lint)
    pr = live_prompt()
    r = _lint.scan_text(pr)
    print('计划（未发任何请求）：')
    for tag, sd in PLAN:
        print('   %s  seed=%d' % (tag, sd))
    print('   张数 6，尺寸 %dx%d，锚点＝现行脸锚＋风格锚' % (W, H))
    print('   提示词＝真源 %s 的现行 PARTS（不读批次存档）' % os.path.basename(SOURCE))
    print('   出图前预检：肯定句点名 %d  装饰密度锁 %g  加权 %.2f  闸=%s'
          % (r['n_pos'], r['struct_miss'], r['score'], '放行' if _lint.gate(r) else '拦下'))
    for w in ('水光肌', '明艳红金'):
        print('     「%s」现在还在提示词里吗：%s' % (w, w in pr))
    print('   成本：Seedream 4-0 按张计，6 张约 ¥3（见 reference-ai-pricing）')
    print('   确认后执行： py noise_floor.py --go')
    sys.exit(0)

import ark_img
os.makedirs(OUT, exist_ok=True)
pr = live_prompt()
uris = [ark_img.data_uri(FACE), ark_img.data_uri(STYLE)]
done = {}
for tag, sd in PLAN:
    dst = os.path.join(OUT, '%s.png' % tag)
    if os.path.exists(dst):
        done[tag] = dst
        print('%s 已存在，跳过' % tag)
        continue
    urls = ark_img.call(pr, uris, sd, W, H)
    ark_img.fetch(urls[0], dst)
    done[tag] = dst
    print('%s seed=%d -> %s' % (tag, sd, os.path.basename(dst)))

# ── 逐张量指标：只取闭环真正会用来判"改好了"的那几项 ──────────────────────────
sys.path.insert(0, r'D:/AIWorkflow/tmp/wzy')
import cv2
import qc

ref_im = qc.imread(FACE)
rf, rbox = qc.face(ref_im)
ref_patch = qc.norm_patch(ref_im)          # 参考侧也走同一个"按脸归一"裁片
ref_dino = qc.dino_emb(ref_patch)         # ⚠️ 必须是 patch 的 embedding，不是整图（qc.one 就是这么配的）
ref_arc = rf.normed_embedding             # 与 qc.one 里的 cos(f.normed_embedding, ref_arc) 对齐
if ref_patch is None:
    sys.exit('脸锚取不到归一 patch，先修锚点')

rows = {}
for tag, p in sorted(done.items()):
    im = qc.imread(p)
    rows[tag] = qc.one(p, ref_patch, ref_dino, ref_arc)
    print('  %s  ' % tag + '  '.join('%s=%.4g' % (k, v) for k, v in sorted(rows[tag].items())
                                     if isinstance(v, (int, float))))

METRICS = ['arc', 'faceL', 'faceA', 'faceWhite', 'faceHR', 'lpalex', 'dino', 'gedge', 'corner']
keys = [k for k in METRICS if all(isinstance(rows[t].get(k), (int, float)) for t in rows)]
missing = set(METRICS) - set(keys)
if missing:
    print('!! 这些指标缺值，不参与定底：%s' % ','.join(sorted(missing)))
print('\n=== 噪声底（组内极差 = 同一提示词重生成一次的自然晃动）===')
print('%-10s %8s %8s %10s %10s   %s' % ('指标', 'A组极差', 'B组极差', 'A相对%', 'B相对%', '闭环能不能用它判改进'))
IMPROVE = {'lpalex': 0.052, 'dino': 0.016, 'gedge': 18.0, 'arc': 0.040, 'faceL': 5.0}
verdict = {}
for k in keys:
    a = [rows[t][k] for t in ('A1', 'A2', 'A3') if t in rows]
    b = [rows[t][k] for t in ('B1', 'B2', 'B3') if t in rows]
    if not a or not b:
        continue
    ra, rb = max(a) - min(a), max(b) - min(b)
    mu = float(np.mean(b)) or 1e-9
    imp = IMPROVE.get(k)
    if imp is None:
        use = '（无对应改进样本，仅记录）'
    else:
        use = '可用，Δ需>%.3f' % (2 * rb) if rb * 2 < imp else '**不可用**：噪声底 %.4g ≥ 改进幅 %.4g' % (rb, imp)
    verdict[k] = rb
    print('%-10s %8.4g %8.4g %9.2f%% %9.2f%%   %s'
          % (k, ra, rb, 100 * ra / (float(np.mean(a)) or 1e-9) if a else 0, 100 * rb / mu, use))

json.dump({'per_image': rows, 'noise_range': verdict, 'seeds': dict(PLAN)},
          open(os.path.join(OUT, 'noise_floor.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=float)
print('\n明细已写 %s' % os.path.join(OUT, 'noise_floor.json'))
print('下一步：闭环 harness 用这里的 noise_range 当最小可检变化（MDC），Δ<2×噪声底一律记"看不出"，不许写"改好了"。')
