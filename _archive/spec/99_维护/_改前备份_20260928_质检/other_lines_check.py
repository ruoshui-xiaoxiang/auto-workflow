# -*- coding: utf-8 -*-
"""另两条产物线（WorkBuddy 的三阶打斗 12 镜 ＋ 万相 3.0 第一章 23 镜稿）过同一批闸的结果。

为什么要这个：第一章这条线有四道闸（词表闸/法条闸/结构闸 G7/枪硬闸）＋台词逐字纪律，
另两条线的提示词是**另一个工具写的、一份都没过过闸**。归属没定之前，先把差距量出来。
只读、只报，不改它们任何一份提示词，也不生成任何东西。
"""
import json
import os
import re
import sys

D = r'D:/AIWorkflow/tmp/wzy'
PR = r'D:/AIWorkflow/ComfyUI_H3/prompts'
SRC = os.path.join(D, 'c12_source.txt')          # 第一章正文（台词唯一真源）
DLG = re.compile(r'<d>\[中文\](.*?)</d>', re.S)          # 第一章：官方对白标签
DLG2 = re.compile(r'["“]([^"”“]{2,40})["”]')  # 万相：说:"…" 引号式

sys.path.insert(0, D)
import prompt_lint as L                            # noqa: E402
import prompt_rules as R                           # noqa: E402

# 第一章立的字面纪律（另两条线要不要一起受约束＝归属问题的一部分）
LITERAL_BAN = ['枪', '金属', '刃', '矛头', '云肩', '披膊', 'BJD', '人偶']
TEXT = open(SRC, encoding='utf8').read()


def verbatim(q):
    """台词是否逐字存在于正文（去掉标点空格后做子串判定）。"""
    k = re.sub(r'[^\w]', '', q)
    return k in re.sub(r'[^\w]', '', TEXT)


def report(tag, files):
    print('\n' + '=' * 72)
    print('【%s】%d 份' % (tag, len(files)))
    rows = []
    for f in files:
        t = open(f, encoding='utf8').read()
        dl = [d.strip() for d in DLG.findall(t)] or [d.strip() for d in DLG2.findall(t)]
        miss = [q for q in dl if not verbatim(q)]
        hits = sorted({w for w in LITERAL_BAN if w in t})
        r = L.scan_text(t)
        law = R.scan_rules(t)
        g7 = 'PASS' if 'integrated_multimodal_description:' in t else '非官方骨架（中文十块）'
        rows.append((os.path.basename(f), len(dl), len(miss), len(hits), r['n_pos'],
                     sum(len(u) for _r, u, _l in law), g7, hits[:4], miss[:2]))
    print('%-30s %3s %4s %4s %5s %4s  %s' % ('文件', '台词', '非原文', '违字面', '肯定点名', '法条', '骨架'))
    for b, nd, nm, nh, npos, nlaw, g7, hits, miss in rows:
        print('%-30s %3d %4d %4d %5d %4d  %s%s' % (b[:29], nd, nm, nh, npos, nlaw, g7,
              ('   字面:' + '、'.join(hits)) if nh else ''))
        if miss:
            print('%33s⚠ 台词正文查无：%s' % ('', ' / '.join('「%s」' % m[:18] for m in miss)))
    tot_d = sum(x[2] for x in rows)
    print('小结：台词非原文 %d 条／字面违规命中 %d 处' % (tot_d, sum(x[3] for x in rows)))
    return rows


if __name__ == '__main__':
    files = sorted(f for f in os.listdir(PR) if f.startswith('wuzhaojunyi_三阶'))
    report('三阶打斗 12 镜（H3，WorkBuddy 写的提示词）', [os.path.join(PR, f) for f in files])
    w = json.load(open(os.path.join(D, 'wan_ch1_prompts.json'), encoding='utf8'))
    tmp = os.path.join(D, 'tmp_wan')
    os.makedirs(tmp, exist_ok=True)
    for s in w:
        open(os.path.join(tmp, '%s_wan.txt' % s['id']), 'w', encoding='utf8').write(s['prompt'])
    files = sorted(os.path.join(tmp, f) for f in os.listdir(tmp))
    report('万相 3.0 第一章 23 镜提示词稿（其中 10 镜已出片 480P）', files)
    print('\n注：本报告不判废、不拦截——它只回答一个问题：另两条线相对第一章纪律，缺了哪几道检查。')
