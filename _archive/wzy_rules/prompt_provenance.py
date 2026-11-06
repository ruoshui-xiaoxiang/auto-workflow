# -*- coding: utf-8 -*-
"""成片↔提示词 版本对应核查：引擎在批次 manifest 里存了 prompt 全文与 prompt_sha256，
所以"这张成片是哪版词渲的"不必靠猜——直接和现行 h3/Hxx_video.txt 比哈希，不一致就打出差异。
（这条能力是 09-27 找 C6 悬案时发现的：账本里没记指纹，但 manifest 里有。）"""
import glob
import hashlib
import json
import os
import re
import difflib

POOL = r'E:/图像影音资源池/武昭君仪/批次'
H3 = r'D:/AIWorkflow/tmp/wzy/h3'
LED = json.load(open(os.path.join(H3, 'ledger.json'), encoding='utf8'))
CUR = {}
for f in glob.glob(os.path.join(H3, 'H*_video.txt')):
    sid = os.path.basename(f)[:3]
    b = open(f, 'rb').read()
    CUR[sid] = (hashlib.sha256(b).hexdigest(), b.decode('utf8'))


# 差异分级：字面相似度会骗人（0.97 的差别里可以藏着"基调收窄"这种承重改动），
# 所以逐条比对语义载荷，而不是只看比值。
CARRIERS = [
    ('基调已按镜收窄（古代线不再并列赛博场景）', '与赛博朋克并置',
     lambda old, cur: ('与赛博朋克并置' in old) and ('与赛博朋克并置' not in cur)),
    ('法条字面已清（旧版含"金属材质写实"）', '金属',
     lambda old, cur: ('金属' in old) and ('金属' not in cur)),
    ('道具封口锁已升级（旧版只说"不外露别的"）', '封口',
     lambda old, cur: ('完全封口' in cur) and ('完全封口' not in old)),
    ('防克隆句缺失（旧版无"彼此可辨"）', '彼此可辨',
     lambda old, cur: ('彼此可辨' in cur) and ('彼此可辨' not in old)),
    ('动作衔接句缺失（旧版无 Motion: every movement）', 'Motion',
     lambda old, cur: ('Motion: every movement' in cur) and ('Motion: every movement' not in old)),
    ('尺度锁缺失（旧版无"长度与她身高相当"）', '尺度',
     lambda old, cur: ('身高相当' in cur) and ('身高相当' not in old)),
    ('攻防交互/底线句缺失（旧版无 two-person fight）', '底线',
     lambda old, cur: ('two-person fight' in cur) and ('two-person fight' not in old)),
]


def carriers(old, cur):
    return [name for name, _k, f in CARRIERS if old and f(old, cur)]


rows = []
for mf in sorted(glob.glob(os.path.join(POOL, '*', '*.manifest.json'))):
    try:
        m = json.load(open(mf, encoding='utf8'))
    except Exception:
        continue
    a = m.get('args', {}) or {}
    pf = a.get('prompt_file') or ''
    sid = (re.search(r'(H\d\d)_video', pf) or re.search(r'\b(H\d\d)\b', str(m.get('args', {}).get('theme', ''))) or [None, '?'])[1]
    for im in (m.get('images') or []):
        sh = im.get('prompt_sha256') or ''
        p = im.get('prompt') or ''
        if not sh and p:
            sh = hashlib.sha256(p.encode('utf8')).hexdigest()
        rows.append(dict(shot=sid, dir=os.path.basename(os.path.dirname(mf)), sha=sh, prompt=p,
                         file=(im.get('file') or '').split(os.sep)[-1], n=im.get('length'),
                         w=a.get('width'), h=a.get('height')))

print('%-5s %-18s %-10s %s  ※字面相似度会骗人，判定看"承重差异"' % ('镜', '批次目录', '与现行词', '说明'))
for r in sorted(rows, key=lambda x: (x['shot'], x['dir'])):
    if r['shot'] not in CUR:
        continue
    cur_sha, cur = CUR[r['shot']]
    if not r['sha']:
        verdict, note = '存疑', 'manifest 无提示词全文/哈希'
    elif r['sha'] == cur_sha:
        verdict, note = '一致', '成片＝现行提示词渲的'
    else:
        ratio = difflib.SequenceMatcher(None, r['prompt'][:4000], cur[:4000]).ratio() if r['prompt'] else 0
        # 找差异关键词（哪些纪律句是后加的）
        added = [k for k in ('Keep unchanged throughout', 'Motion: every movement', 'two-person fight',
                             'anti-clone', '彼此可辨', '陌生的中年女人', '长度与她身高相当')
                 if k in cur and k not in r['prompt']]
        car = carriers(r['prompt'], cur)
        # 承重差异条数决定建议：0 条＝可留；含"基调并列/法条字面"这类已知致缺陷来源＝建议重跑
        hard = [c for c in car if '基调' in c or '法条' in c or '尺度锁' in c or '防克隆' in c]
        verdict, note = '不一致', '相似度 %.2f ⇒ 建议%s；承重差异 %d 条：%s' % (
            ratio, '重跑' if hard else '可留', len(car), '；'.join(car) or '只有句式/胶水句差异')
    print('%-5s %-18s %-10s %s  [%sx%s %s帧]' % (r['shot'], r['dir'], verdict, note, r['w'], r['h'], r['n']))

print('\n账本在册镜：%s' % ', '.join('%s=%s' % (k, v.get('verdict')) for k, v in LED.items()))
