# -*- coding: utf-8 -*-
# 项目"新规"静态核对：把他自己在文档里白纸黑字写过的措辞禁令，变成机器闸。
#
# 为什么单独做这一层：prompt_lint 的毒词表是我从失败里归纳的，会滞后（只能查已知的病）。
# 但**他已经批准过的措辞新规不是"已知病"，是明写的法条**——法条不执行，就等于没立。
# 而且这类规则的力度比"肯定句点名"更狠：它们禁的是**这个字面本身**，
# 写在禁令里同样算违规（因为本项目已经验过：禁令即在点名，模型照着画）。
#
# 每条都带出处；出处用「关键词 + 当时的行号」两件事一起记（见 _locate）——
# **行号是易碎指针**：2026-09-27 那次文档升 v1.2，法条整段搬家，脚本里 `src='v1.md:86'`
# 当场指到空行。所以现在每次运行都拿关键词在活文档里重定位一次，对不上就喊漂移。
#
# 判区口径（2026-09-28 与提示词格式契约对齐）：
#   · 法条查的是**画面区**＝整份提示词剔掉 `<d>…</d>` 官方台词标签之后的部分。
#     台词里的"枪"保留原文（项目层 `WZJY-W1`：H18 角色原话就是"那也是枪"，
#     而 `<d>` 驱动的是音轨不是画面）；但台词命中**另外报出来**，不做静默吞掉。
#   · 十块格式里的中文引号**不当台词**（那多半是叙述句），要豁免必须显式带 `<d>` 标签。
import io
import os
import re
import sys

D = r'D:/AIWorkflow/tmp/wzy'
sys.path.insert(0, D)
DOC = r'E:/创作/武昭君仪/武昭君仪_剧本与资产盘点_v1.md'
SKEL = r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架'

RULES = [
    dict(id='R1', src='v1.md:892', anch='不出现「矛头／金属／刃」字样',
         say='提示词一律不出现「矛头／金属／刃」字样、不写免责句',
         bad=['矛头', '金属矛头', '铁杆', '刃口', '露刃', '见刃', '金属', '刃'],
         fix='只描述看得见的布：「一杆用白麻布从一端到另一端裹实的长条物，两端收严」；'
             '至于里面藏了什么，一个字都不要提'),
    # R2 已被真源自己覆写（`v1.md:128`「一处与他自己旧法条的冲突，留在这里不悄悄吞掉」）：
    # 旧写法"长枪→长矛"作废，现行＝**画面区一个"枪"字都不出现**，形态整个交给首帧像素。
    # 结案证据比原引用更硬：真源道具表自陈"病根是「枪」这个字，改后变异归零"⇒ 实测因果，不是风格偏好。
    dict(id='R2', src='v1.md:128', anch='一个"枪"字都不出现',
         say='视频提示词的画面区不出现「枪」字（旧"长枪一律改长矛"已被真源覆写）',
         bad=['枪'],
         # ✅ 作用域已裁（用户 2026-09-28 委托 Qoder 按建议裁定）：**这条只管"会进成片"的线**。
         # 理由：它防的病是"观众看见一颗子弹/一件火器"，而 previz/设计稿线的产物**不进片**，
         # 代价是画面参考而非成片缺陷；反过来，只要某条线的产物会进片，豁免立刻失效。
         # ⚠ 病根本身（H07 实测：缠白麻布的长杆被渲成一颗黄铜弹壳）是引擎级的，
         #    所以豁免只免"字面"，未免"形态锁"——R2 豁免的镜仍必须过 H3R1 道具形态锁。
         line_exempt=True,
         scope='作用域＝**会进成片的线**（A 线第一章及任何标称成片的稿）。三阶 P3「亮枪」属 previz 设计稿，'
               '按剧情就该有"枪"⇒ 记留痕不记违规（`WZJY-L1`：设计稿不许反向推翻成片纪律，'
               '反向也不许拿成片纪律否掉它的剧情）。豁免只免字面，**形态锁不免**',
         fix='四组替身（`v1.md:128`）：长枪→那根缠着白麻布的长杆／枪杆→长杆／'
             '枪头→布裹的那一端／枪尾→杆尾；招式词（枪花·枪尖·枪法·回马枪…）走 '
             'h3_shots.DEGUN 21 条全表，别裸兜底'),
    dict(id='R3', src='v1.md:1045', anch='要删掉「云肩」这个名词本身',
         say='想减肩甲别再写"不要肩甲"，要删掉「云肩」这个名词本身',
         bad=['云肩', '四合', '披膊', '补子'],
         fix='不写；肩部交给风格锚，文本只说"肩部全部是织物"'),
    dict(id='R4', src='v1.md:918', anch='删掉「BJD 人偶质感」这个词',
         say='不写「BJD／球形关节／人偶」——它是在召唤球形关节，禁令压不住',
         bad=['BJD', '球关节', '球形关节', '人偶'],
         fix='不写'),
    dict(id='R5', src='v1.md:938', anch='不写"不要 X"式的免责句',
         say='不写免责句（"若参考图里有X则不采用X"这类句子本身就是点名）',
         bad=['不采用它的金属', '两端露出金属', '露出金属矛头', '那杆两端'],
         fix='职责句只写正向取用：「第二张只用于款式与装饰密度」'),
]
# 锚职责/分工句里出现这些字面，仍算违规（新规禁的是字面，不分句位）——这正是要和 prompt_lint
# 的"禁令句低危"逻辑分开的地方：法条类规则不接受"我只是在禁止它"作为辩护。
CHECK_VOCAB_TOO = True

DLG_SPAN = re.compile(r'<d>.*?</d>|<d\s*/>', re.S)


def split_dialogue(txt):
    """返回 (画面区, 台词区列表)。只认官方 `<d>` 标签——中文引号不算台词，别拿它当豁免口。"""
    dlg = DLG_SPAN.findall(txt)
    return DLG_SPAN.sub(lambda m: ' ' * len(m.group(0)), txt), [d for d in dlg]


def _doc_lines():
    try:
        return open(DOC, encoding='utf8').read().split('\n')
    except Exception:
        return []


def locate(rule):
    """拿关键词在活文档里重定位这条法条。返回 (实测行号 or None, 记的行号, 是否漂移)。"""
    ls = _doc_lines()
    want = rule['src']
    got = None
    for i, l in enumerate(ls, 1):
        if rule['anch'] in l:
            got = i
            break
    try:
        want_ln = int(want.split(':')[1])
    except (IndexError, ValueError):
        return got, want, False
    return got, want, (got is not None and got != want_ln)


def scan_rules(txt):
    """法条命中（**按位置去重**）：单字「刃」会同时被 '刃' 和 '刃口' 命中同一处，
       旧写法按"词"去重 ⇒ 一处违规报成两三条，数量不可信。"""
    visual, _dlg = split_dialogue(txt)
    hits = []
    for r in RULES:
        marks = {}                                  # pos -> (词, 起, 止)，长词优先
        for w in r['bad']:
            for m in re.finditer(re.escape(w), visual):
                for p in range(m.start(), m.end()):
                    old = marks.get(p)
                    if old is None or (m.end() - m.start()) > (old[2] - old[1]):
                        marks[p] = (w, m.start(), m.end())
        if not marks:
            continue
        seen, found = set(), []
        for p in sorted(marks):
            w, s, e = marks[p]
            if (w, s) in seen:
                continue
            seen.add((w, s))
            found.append((w, visual[:s].count('\n') + 1))
        hits.append((r, sorted({w for w, _ in found}), sorted({ln for _, ln in found})))
    return hits


def dialogue_hits(txt):
    """台词区里的法条字面——不拦（`WZJY-W1` 明确豁免），但必须报出来让人看见。"""
    _visual, dlg = split_dialogue(txt)
    words = sorted({w for r in RULES for w in r['bad']})
    return sorted({w for w in words for d in dlg if w in d})


def live_dingzhuang():
    src = open(os.path.join(D, 'run_dz0b2ppp.py'), encoding='utf8').read().split('res = []')[0]
    ns = {}
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, 'run_dz0b2ppp.py', 'exec'), ns)
    return '\n\n'.join(ns['PARTS'])


def qiang_anchor():
    src = open(os.path.join(D, 'run_qiang.py'), encoding='utf8').read().split('res = []')[0]
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


def skel_line():
    """三阶 12 镜（H3 官方骨架真源）逐份交回来：09-28 起这条线是**新真源**，
       不扫它，法条闸就只查得到已定妆的旧资产，查不到要出片的这 12 份。
       必须**逐份**报——拼成一大坨的话，行号会指错文件，等于没法定位。"""
    if not os.path.isdir(SKEL):
        return []
    out = []
    for f in sorted(os.listdir(SKEL)):
        if f.startswith('wuzhaojunyi_三阶') and f.endswith('.txt'):
            out.append((f[:-4], open(os.path.join(SKEL, f), encoding='utf8').read()))
    return out


SOURCES = [
    ('现行定妆真源 run_dz0b2ppp.py（72 镜每一张都继承它）', live_dingzhuang, '成片'),
    ('枪锚真源 run_qiang.py（∶416 已判废降为设定档、不出片；留着当复用警戒）', qiang_anchor, '设定档'),
    ('文档「共用不变量」段（写明每镜一字不改带上）', invariant_block, '成片'),
    ('三阶 12 镜 H3 骨架真源 prompts_H3官方骨架/（C 线 previz，WorkBuddy 写的）', skel_line, 'previz'),
]


def expand(res):
    """源函数可以返回一大段文本，也可以返回 [(标签, 文本), …]（逐份的源）。"""
    return res if isinstance(res, list) else [('（整份）', res)]


def classify(hits, line):
    """按线的用途把命中分成 (违规, 留痕)。

    `previz`＝设计稿线：产物不进成片 ⇒ 带 `line_exempt` 的字面条（现只有 R2 零「枪」字）记留痕。
    其余条（R1 矛头/金属/刃、R3 云肩、R4 BJD、R5 免责句）**一律不豁免**——它们防的是
    "被实体化/被点名"，与这条线进不进片无关（作用域见手册 G4-03／登记表 C13）。
    """
    bad, note = [], []
    for r, uniq, ln in hits:
        (note if (line == 'previz' and r.get('line_exempt')) else bad).append((r, uniq, ln))
    return bad, note


if __name__ == '__main__':
    print('=== 项目措辞新规静态核对（禁令里出现字面也算违规；画面区为准，台词另报）===')
    print('--- 先核对法条锚点（行号易碎，关键词才是主定位）')
    for r in RULES:
        got, want, drift = locate(r)
        mark = '✗ 漂移' if drift else ('✓' if got else '✗ 文档里找不到锚句')
        print('   %s %s 记：%s｜实测行：%s｜锚句「%s」' % (mark, r['id'], want, got, r['anch']))
    total = 0
    for name, fn, line in SOURCES:
        try:
            res = fn()
        except Exception as e:
            print('%-52s 读取失败：%r' % (name, e))
            continue
        parts = expand(res)
        if not parts:
            print('\n【%s】 源取不到 ⇒ **不判 ok**（目录被改名/搬走时这里必须响）' % name)
            continue
        clean, nbad, per_rule, per_note = [], 0, {}, {}
        for label, txt in parts:
            if not txt.strip():
                clean.append('%s（空）' % label[:12])
                continue
            bad, note = classify(scan_rules(txt), line)
            nbad += sum(len(u) for _r, u, _l in bad)
            total += sum(len(u) for _r, u, _l in bad)
            if not bad and not note:
                clean.append(label[:12])
                continue
            for bucket, items in ((per_rule, bad), (per_note, note)):
                for r, uniq, _ln in items:
                    e = bucket.setdefault(r['id'], [r, set(), set()])
                    e[1].update(uniq)
                    e[2].add(label)
        print('\n【%s】共 %d 份｜线＝%s｜画面区**违规** %d 处' % (name, len(parts), line, nbad))
        for rid in sorted(per_rule):
            r, words, labels = per_rule[rid]
            print('   %s（%s）「%s」' % (r['id'], r['src'], r['say']))
            ls = sorted(labels)
            who = '、'.join(ls) if len(ls) <= 3 else '%s …（全部 %d 份）' % ('、'.join(ls[:3]), len(ls))
            print('      命中：%s   ——  %d 份：%s' % ('、'.join(sorted(words)), len(ls), who))
            if r.get('scope'):
                print('      ⚠ %s' % r['scope'])
            print('      该换成：%s' % r['fix'])
            dh = sorted({w for lb in labels for w in dialogue_hits(dict(parts)[lb])})
            if dh:
                print('      台词区也有这些字面（%s）——不拦，仅留痕（WZJY-W1：`<d>` 驱动音轨）'
                      % '、'.join(dh))
        for rid in sorted(per_note):
            r, words, labels = per_note[rid]
            ls = sorted(labels)
            print('   ◦ %s（%s）「%s」命中 —— **作用域外，记留痕不记违规**（%d 份）'
                  % (r['id'], r['src'], '、'.join(sorted(words)), len(ls)))
            print('     豁免理由：%s' % r['scope'].split('⇒')[-1].strip())
            print('     ⚠ 豁免只免**字面**，未免形态：这些镜仍须过 H3R1 道具形态锁'
                  '（病根是引擎级的：H07 把缠白麻布的长杆渲成一颗黄铜弹壳）')
        if clean:
            print('   ✓ 画面区合规：%s' % '、'.join(clean))
    print('\n合计画面区 %d 处。判据：活口（现行定妆词＋全片共用不变量）必须为 0；' % total)
    print('剩下的若都在已判废的设定档脚本里（如枪锚），属"复用警戒"，不必改，但别复制进新批。')
