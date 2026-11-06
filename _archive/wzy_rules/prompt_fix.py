# -*- coding: utf-8 -*-
# 缺陷轴 → 自动改法，并生成单变量候选阶梯。
#
# 为什么要"阶梯"而不是"一次全改"：一次全改就算出图变好，也不知道是哪一条改法起的作用，
# 记录不下来可复用的因果。这里每级只在上一级基础上多修一个缺陷轴，
# 出图后用 qc.py 逐张打分，相邻两级的差＝那一条改法的贡献。
#
# 改法不是凭空写的，全部来自本项目已经人审通过的现行提示词（dz0b2ppp/F1.txt）里的原句，
# 也就是"人最后手改出来的那几句话"，只是这次由缺陷检测器决定该动哪一句。
#
# 零成本验证：改完再过一遍 prompt_lint 的闸，并量每级候选与人审通过的 F1 的行重合度。
import os
import re
import importlib.util

D = r'D:/AIWorkflow/tmp/wzy'
os.chdir(D)

spec = importlib.util.spec_from_file_location('prompt_lint', os.path.join(D, 'prompt_lint.py'))
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)

# ── 现行通过版（F1）里的标准句，作为各缺陷轴的替换文本 ──────────────────────────
REPL = {
    '肤色漂白': '**肤色按第一张参考图**（不要提亮、不要改成更白的肤色）。'
               '皮肤是哑光的，有细腻的皮肤质感与柔和的明暗过渡，鼻梁、眼窝、下颌、颈部都有自然的结构阴影。',
    '画风漂写实': '**渲染风格完全按第二张参考图**（即梦同款高精度 3D 半写实国漫）。'
                 '整幅画的明度层次要密：亮部、中间调、暗部都要有连续过渡，布面上不许出现大片平整的单色块面。',
    '武器被点名': '她背后斜背一杆用白麻布从一端到另一端完全缠绕包裹的长条物，两端收严，'
               '整根看不见任何金属、看不见刃；这根长条物在人物身后，不许横在身体前面。'
               '武器的两端与材质完全按道具参考图渲染，文本不逐一描述。',
    '委托未交全': '配色、纹样、材质全部让第二张参考图决定，文本不另写颜色名词。',
    '主语覆盖': '**第二张参考图上的所有装饰，密度、位置、层次全部照搬，一处都不许简化、不许省掉**——'
              '布面上满铺的暗银提花纹样（卷云、折枝花、以及散落的细密银点）、腰封上那一整圈雕花银饰、'
              '腰侧垂落的银流苏与佩饰、肩上与外罩那一层层半透明的薄纱、袖口的层次——全都要画出来，'
              '装饰密度必须与原图相当。',
    '妆感被点名': '唇色自然淡粉、无唇釉无高光；眉形细而利落、不浓不粗；整体伪素颜。',
}

# 例外：**不能整行换**的轴。妆感词和"窄长脸／下颌利落／狭长凤眸"这套骨相描述在同一行里，
# 而骨相描述是他文档实测**帮了身份锁**的（ArcFace 0.616→0.799），整行换掉会把它一起扔了。
# 所以这一轴只换出问题的半句。改法文字抄自他文档 ⑤ 号方案（未点头，先当候选）。
SUBS = {
    '妆感被点名': [('眉形细而利落、眉色深；唇形饱满', '眉形细而利落、不浓不粗；唇色自然淡粉、无唇釉无高光'),
                  ('眉形细而利落、眉色深', '眉形细而利落、不浓不粗'),
                  ('唇形饱满', '唇色自然淡粉、无唇釉无高光'),
                  ('不要浓妆艳唇', '整体伪素颜')],
}

# 各轴删哪些词（肯定句里出现就删；只活在"不要X"里的不动，那是人已接受的写法）
DROP = {
    '肤色漂白': lint.SKIN_TOXIC,
    '画风漂写实': lint.RENDER_TOXIC,
    '武器被点名': lint.WEAPON_TOXIC,
    '委托未交全': lint.COLOR_WORDS,
    '妆感被点名': lint.MAKEUP_TOXIC,
}


def positive_lines(txt, voc):
    """返回含"肯定句点名"的行号集合。"""
    out = set()
    lines = txt.split('\n')
    for i, ln in enumerate(lines):
        for w in voc:
            for m in re.finditer(re.escape(w), ln):
                if not lint.negated(ln, m.start()):
                    out.add(i)
    return out


def fix_axis(txt, axis):
    """修一个缺陷轴。
    关键教训：v1 在句子里"抠词"，改完留下"用白麻布从到完全缠绕""肌肤带轻微、表面平滑"这种断句——
    词删对了、句子废了。v2 改成**整句替换**：带肯定句点名的那一行，整行换成标准委托句，
    多余的中毒行直接丢掉（同一句只保留一份）。
    """
    acts = []
    if axis in SUBS:
        for old, new in SUBS[axis]:
            if old in txt and new not in txt:
                txt = txt.replace(old, new)
                acts.append('半句替换：%s → %s' % (old[:16], new[:20]))
        if any(not neg for _, neg in lint.find_terms(txt, lint.MAKEUP_TOXIC)) and REPL[axis] not in txt:
            txt = txt.rstrip('\n') + '\n' + REPL[axis] + '\n'
            acts.append('补妆感正面描述句（+1 段）')
        return txt, acts
    if axis == '主语覆盖':
        if REPL['主语覆盖'] not in txt:
            txt = txt.rstrip('\n') + '\n' + REPL['主语覆盖'] + '\n'
            acts.append('补装饰密度逐项点名句（+1 段）')
        return txt, acts
    voc = DROP.get(axis, [])
    bad = sorted(positive_lines(txt, voc))
    if not bad:
        return txt, acts
    lines = txt.split('\n')
    rep = REPL[axis]
    keep_rep_at = None if rep in txt else bad[0]
    for i in bad:
        acts.append('第 %d 行整行替换为%s标准句（该行含肯定句点名毒词）' % (i + 1, axis))
        lines[i] = rep if i == keep_rep_at else None
    out = [l for l in lines if l is not None]
    txt = '\n'.join(out) + '\n'
    return txt, acts


LADDER = ['肤色漂白', '画风漂写实', '委托未交全', '武器被点名', '主语覆盖', '妆感被点名']

# ── 结构闸（prompt_gate.S1 裸禁令）发现的空位 → 正面锁文本 ──────────────────────
# 这些句子不是新创作：全部取自本项目已经被接受过的措辞，或由它的最小正例构成。
_s2 = importlib.util.spec_from_file_location('prompt_gate', os.path.join(D, 'prompt_gate.py'))
gate = importlib.util.module_from_spec(_s2)
import contextlib
import io as _io
with contextlib.redirect_stdout(_io.StringIO()):
    _s2.loader.exec_module(gate)

LOCKS = {
    '脏旧': '布面整体干净，只在衣缘有极淡的使用痕迹。',
    '妆感': REPL['妆感被点名'],
    '肤色肤质': '**皮肤是哑光的**，明暗过渡柔和，不反光。',
    '配色': '配色、纹样、材质全部让第二张参考图决定，文本不另写颜色名词。',
    '平涂画风': REPL['画风漂写实'],
    '金属甲件': '肩部与手臂全部是织物，看不见任何金属件。',
    '西方剪影': '形制为交领右衽，东方剪影。',
    '排版文字': '单个人物、单一姿势的全身立像，画面里不出现任何排版与文字。',
    '幼态关节': '骨骼成熟、下颌利落，成年人比例。',
    '发色': '发色必须墨黑，不许灰白。',
    '上下同料明度': '上下同料、上下同色：上身与下裙同一种布、同一套工艺、同一色深。',
}


def fix_structural(txt):
    """结构闸报"这个属性没人接住" → 把对应正面锁补进文末（迭代到不动点里跑）。"""
    acts = []
    bare, _unk, _duty = gate.s1_bare_bans(txt)
    for it, doms in bare:
        for dm in doms.split('/'):
            lock = LOCKS.get(dm)
            if lock and lock not in txt:
                txt = txt.rstrip('\n') + '\n' + lock + '\n'
                acts.append('补【%s】正面锁：%s' % (dm, lock[:24]))
    return txt, acts


def active_axes(txt):
    """当前文本上还活着的缺陷轴（按检测器实判，不按原批次的历史结论）。"""
    r = lint.scan_text(txt)
    out = []
    for ax in ('肤色漂白', '画风漂写实', '武器被点名', '妆感被点名'):
        for w, neg in lint.find_terms(txt, DROP.get(ax, [])):
            if not neg:
                out.append(ax)
                break
    if any(d in txt for d in lint.DELEGATE):
        if any(not neg for _, neg in lint.find_terms(txt, lint.COLOR_WORDS)):
            out.append('委托未交全')
    if r['struct_miss']:
        out.append('主语覆盖')
    return [a for a in LADDER if a in set(out)]


def all_gates(txt):
    """两闸一起看：词表闸（prompt_lint）+ 结构闸（裸禁令/值矛盾）。"""
    r = lint.scan_text(txt)
    bare, _u, _d = gate.s1_bare_bans(txt)
    conf = gate.s3_conflicts(txt)
    return {'vocab': lint.gate(r), 'struct': not (bare or conf),
            'n_pos': r['n_pos'], 'struct_miss': r['struct_miss'],
            'bare': len(bare), 'conf': len(conf), 'score': r['score']}


def both_green(g):
    return g['vocab'] and g['struct']


def to_fixed_point(txt, max_pass=6):
    """一遍过会漏：补了委托句才激活颜色词罚分（耦合），补了正面锁才让结构闸闭上。
    所以扫一遍→改→重扫，两闸同时绿才停。"""
    trace = []
    for k in range(max_pass):
        g = all_gates(txt)
        trace.append(('第%d轮 起点' % (k + 1), g, []))
        if both_green(g):
            break
        axes = active_axes(txt)
        txt2, acts = fix_structural(txt)
        for ax in axes:
            txt2, a2 = fix_axis(txt2, ax)
            acts += a2
        if not acts:
            break
        g2 = all_gates(txt2)
        trace.append(('第%d轮 改后' % (k + 1), g2, acts))
        txt = txt2
        if both_green(g2):
            break
    return txt, trace


def ladder(src_txt):
    """逐级修：第 k 级 = 前 k 个轴各修一次。每级只比上一级多一个变量。"""
    cands, t, notes = [('V0 原文', src_txt, [])], src_txt, []
    for k, ax in enumerate(LADDER, 1):
        t2, acts = fix_axis(t, ax)
        if acts:
            notes.append('V%d +%s：%s' % (k, ax, '；'.join(acts)))
            t = t2
        cands.append(('V%d 修到%s' % (k, ax), t, acts))
    return cands, notes


def norm_lines(txt):
    s = set()
    for ln in txt.split('\n'):
        ln = re.sub(r'[\s*#—、，。；：（）]', '', ln)
        if len(ln) >= 12:
            s.add(ln)
    return s


FILES = [("dz0b2/D1.txt", "画风漂·游戏CG（打回）"),
         ("dz0b2p/D1'.txt", "变白（打回）"),
         ("dz0b2pp/E1.txt", "偏卡通（打回）"),
         ("dz0b2ppp/F1.txt", "未打回·妆感漂已知待修")]
GOLD = open('dz0b2ppp/F1.txt', encoding='utf-8').read()
gold = norm_lines(GOLD)

print('== 每条标准替换句／正面锁的自检（只查"肯定句点名"；主语覆盖是整篇性质、片段上无意义）==')
bad = 0
for k, v in list(REPL.items()) + [('锁·' + k, v) for k, v in LOCKS.items()]:
    r = lint.scan_text(v)
    if r['n_pos']:
        bad += 1
        print('   !! %-12s 肯定句点名 %d：%s' % (k, r['n_pos'], v[:40]))
print('   替换文本自带毒词：%d 处（0 才合格——否则改完反而投毒）' % bad)
print()

def show(tag, g):
    print('     %-14s 词表点名%2d 密度锁%g 裸禁令%d 矛盾%d 加权%6.2f  词表闸=%s 结构闸=%s'
          % (tag, g['n_pos'], g['struct_miss'], g['bare'], g['conf'], g['score'],
             '放行' if g['vocab'] else '拦下', '放行' if g['struct'] else '拦下'))


def run_one(p, src, verdict):
    g0 = all_gates(src)
    print('=' * 78)
    print('原提示词 %s（人审：%s）起点：' % (p, verdict), end='')
    show('V0', g0)
    cands, notes = ladder(src)
    print('  A) 一遍过（每条改法只上一次，只喂词表闸）：')
    for tag, t, _ in cands:
        show(tag, all_gates(t))
    fp, trace = to_fixed_point(src)
    print('  B) 两闸一起迭代到不动点：')
    for tag, g, acts in trace:
        show(tag, g)
        for a in acts:
            print('          ·', a)
    gf = all_gates(fp)
    ok_lines = [l for l in fp.split('\n') if l.strip()]
    orig = set()
    for l in src.split('\n'):
        if not l.strip():
            continue
        cand = {l.strip()}
        for _ax, pairs in SUBS.items():
            for old, new in pairs:
                cand |= {c.replace(old, new) for c in cand}
        orig |= cand
    reps = set(LOCKS.values()) | set(REPL.values())
    foreign = [l.strip() for l in ok_lines if l.strip() not in orig and l.strip() not in reps]
    print('  结果：一遍过=%s  两闸迭代=%s  文本完整性=%s'
          % ('放行' if both_green(all_gates(cands[-1][1])) else '仍拦下',
             '两闸全绿' if both_green(gf) else '仍拦下',
             '无断句' if not foreign else '拼出 %d 行：%s' % (len(foreign), foreign[:2])))
    return fp, gf


for p, verdict in FILES:
    run_one(p, open(p, encoding='utf-8').read(), verdict)

# 现行真源（跑批 1 之前最该过闸的一份）
_src = open('run_dz0b2ppp.py', encoding='utf-8').read().split('res = []')[0]
_ns = {}
exec(compile(_src, 'run_dz0b2ppp.py', 'exec'), _ns)
run_one('真源 run_dz0b2ppp.py（现行定妆词）', '\n\n'.join(_ns['PARTS']), '待拍板')
