# -*- coding: utf-8 -*-
# 项目"新规"静态核对：把他自己在文档里白纸黑字写过的措辞禁令，变成机器闸。
#
# 为什么单独做这一层：prompt_lint 的毒词表是我从失败里归纳的，会滞后（只能查已知的病）。
# 但**他已经批准过的措辞新规不是"已知病"，是明写的法条**——法条不执行，就等于没立。
# 而且这类规则的力度比"肯定句点名"更狠：它们禁的是**这个字面本身**，
# 写在禁令里同样算违规（因为本项目已经验过：禁令即在点名，模型照着画）。
#
# 每条都带出处（文档行号），冲突时以文档为准，不以本脚本为准。
import importlib.util
import io
import os
import re
import sys

D = r'D:/AIWorkflow/tmp/wzy'
DOC = r'C:/Users/若水/Desktop/武昭君仪/武昭君仪_剧本与资产盘点_v1.md'

RULES = [
    dict(id='R1', src='v1.md:86',
         say='提示词一律不出现「矛头／金属／刃」字样、不写免责句',
         bad=['矛头', '金属', '金属矛头', '铁杆', '刃口', '露刃', '见刃', '刃'],
         fix='只描述看得见的布：「一杆用白麻布从一端到另一端裹实的长条物，两端收严」；'
             '至于里面藏了什么，一个字都不要提'),
    dict(id='R2', src='v1.md:634',
         say='全片提示词凡出现「长枪」一律改「长矛」',
         bad=['长枪', '枪头', '枪尾', '枪杆', '枪身', '枪托', '火枪', '枪尖'],
         fix='长矛／槊'),
    dict(id='R3', src='v1.md:102 / :165',
         say='想减肩甲别再写"不要肩甲"，要删掉「云肩」这个名词本身',
         bad=['云肩', '四合', '披膊', '补子'],
         fix='不写；肩部交给风格锚，文本只说"肩部全部是织物"'),
    dict(id='R4', src='v1.md:112',
         say='措辞上删掉「BJD 人偶质感」这个词——它是在召唤球形关节',
         bad=['BJD', '球关节', '球形关节', '人偶'],
         fix='不写'),
    dict(id='R5', src='v1.md:85',
         say='不写免责句（"若参考图里有X则不采用X"这类句子本身就是点名）',
         bad=['不采用它的金属', '两端露出金属', '露出金属矛头', '那杆两端'],
         fix='职责句只写正向取用：「第二张只用于款式与装饰密度」'),
]
# 锚职责/分工句里出现这些字面，仍算违规（新规禁的是字面，不分句位）——这正是要和 prompt_lint
# 的"禁令句低危"逻辑分开的地方：法条类规则不接受"我只是在禁止它"作为辩护。
CHECK_VOCAB_TOO = True


def _doc_lines():
    try:
        return open(DOC, encoding='utf-8').read().split('\n')
    except Exception:
        return []


def live_dingzhuang():
    src = open(os.path.join(D, 'run_dz0b2ppp.py'), encoding='utf-8').read().split('res = []')[0]
    ns = {}
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, 'run_dz0b2ppp.py', 'exec'), ns)
    return '\n\n'.join(ns['PARTS'])


def qiang_anchor():
    src = open(os.path.join(D, 'run_qiang.py'), encoding='utf-8').read().split('res = []')[0]
    ns = {}
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, 'run_qiang.py', 'exec'), ns)
    doc0 = ns.get('__doc__')
    parts = [v for k, v in ns.items()
             if isinstance(v, str) and len(v) > 20 and k[:1] != '_' and v is not doc0
             and 'D:/' not in v and '.png' not in v and re.search(r'[一-鿿]', v)]
    return '\n\n'.join(parts)


def invariant_block():
    ls = _doc_lines()
    for i, l in enumerate(ls):
        if l.startswith('**共用不变量**'):
            return l
    return ''


SOURCES = [
    ('现行定妆真源 run_dz0b2ppp.py（72 镜每一张都继承它）', live_dingzhuang),
    ('枪锚真源 run_qiang.py（∶416 已判废降为设定档、不出片；留着当复用警戒）', qiang_anchor),
    ('文档「共用不变量」段（写明每镜一字不改带上）', invariant_block),
]


def scan_rules(txt):
    hits = []
    for r in RULES:
        found = []
        for w in r['bad']:
            for m in re.finditer(re.escape(w), txt):
                line = txt[:m.start()].count('\n') + 1
                found.append((w, line))
        if found:
            uniq = sorted({w for w, _ in found})
            hits.append((r, uniq, sorted({ln for _, ln in found})))
    return hits


if __name__ == '__main__':
    print('=== 项目措辞新规静态核对（禁令里出现字面也算违规）===')
    total = 0
    for name, fn in SOURCES:
        try:
            txt = fn()
        except Exception as e:
            print('%-46s 读取失败：%r' % (name, e))
            continue
        if not txt.strip():
            print('%-46s 空，跳过' % name)
            continue
        hits = scan_rules(txt)
        n = sum(len(u) for _r, u, _l in hits)
        total += n
        print('\n【%s】 违规字面 %d 处' % (name, n))
        for r, uniq, lines in hits:
            print('   %s（%s）「%s」' % (r['id'], r['src'], r['say']))
            print('      命中：%s   （行 %s）' % ('、'.join(uniq), ','.join(map(str, lines[:6]))))
            print('      该换成：%s' % r['fix'])
        if not hits:
            print('   全部合规')
    print('\n合计 %d 处。判据：活口（现行定妆词＋全片共用不变量）必须为 0；' % total)
    print('剩下的若都在已判废的设定档脚本里（如枪锚），属"复用警戒"，不必改，但别复制进新批。')
