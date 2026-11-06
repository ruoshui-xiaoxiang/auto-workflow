# -*- coding: utf-8 -*-
# 闭环检测升级：给"只会找人命名的病"的 linter，补上不吃毒词表的**结构检测器**。
#
# 为什么要补：prompt_lint 的词表是照着已踩的坑抄的，它天然查不出下一类新病。
# 三条与词表无关的结构判据：
#   S1 裸禁令  —— 写了"不要X"，但全文没有任何落在同一分句里的正面锁/委托接住 X 所属的属性
#                 ⇒ 那个空位会被模型自己填（本项目反复踩的那条规律的机器化版本）
#   S2 缺必填  —— 定妆镜该写死的规格（画幅/人数/景别/背景/无烧字）没写
#                 ⇒ 缺规格＝把决定权白送，比写错词更容易翻车
#   S3 值矛盾  —— 同一属性在两处给了不同的值，**只在肯定句里数**
#                 （v1 把禁令里的"不要立领""不许横在身体前面"也数进去，四批全假阳，已修）
#
# v2 又修掉一处假接住：锁词"自然"被 F1 的"自然的结构阴影"满足，等于没锁
#   ⇒ 现在要求**正面锁与该域的主语名词出现在同一分句里**。
#
# 状态：S1/S2/S3 目前只当**报告项**，不并进闸门。新判据要先在四批已知数据上验过、
# 且不产生恒定假阳，才有资格进闸——纪律来自"裁判打分只能算 completed"。
import importlib.util
import os
import re

D = r'D:/AIWorkflow/tmp/wzy'
_s = importlib.util.spec_from_file_location('prompt_lint', os.path.join(D, 'prompt_lint.py'))
L = importlib.util.module_from_spec(_s)
_s.loader.exec_module(L)

DOMAINS = {
    '肤色肤质': dict(cues=['水光', '油光', '油亮', '瓷白', '惨白', '亮白', '塑料感', '提亮', '更白', '泛白'],
                  locks=['哑光', '柔雾'], deleg=True),
    '妆感': dict(cues=['浓妆', '艳唇', '眼线', '眼影', '烟熏', '唇', '眉'],
              locks=['伪素颜', '淡粉', '唇色自然'], deleg=False),
    '配色': dict(cues=['红金', '珠光', '彩虹', '泛粉', '泛紫', '朱砂'],
              locks=['上下同色', '同一色深'], deleg=True),
    '金属甲件': dict(cues=['肩甲', '披膊', '胸甲', '护臂', '铆钉', '鳞甲', '金属片', '甲'],
                 locks=['全部是织物', '全是布', '看不见任何金属'], deleg=True),
    '武器': dict(cues=['矛头', '刃', '枪头', '枪尾', '金属杆', '扳机', '枪托'],
              locks=['白麻布', '完全缠绕', '全裹'], deleg=True),
    '幼态关节': dict(cues=['幼态', '娃娃', '关节', '人偶', '球形', '圆眼', '大眼'],
                 locks=['骨骼成熟', '下颌利落', '年龄感'], deleg=False),
    '平涂画风': dict(cues=['平涂', '厚描边', '赛璐璐', '线稿', '硬边', '块面', '亮片', '闪粉', '手游', '二次元'],
                 locks=['经纬织纹', '缎面丝光', '连续过渡', '渲染风格'], deleg=True),
    '排版文字': dict(cues=['设定表', '多视图', '分格', '标签', '水印', '签名', '印章', '题字', '出现两次', '文字'],
                 locks=['单个人物', '单一姿势'], deleg=False),
    '西方剪影': dict(cues=['立领', '紧身胸衣', '裙撑', '羽翼', '抹胸', '吊带', '露肩', '露沟', '湿纱', '球状'],
                 locks=['交领右衽'], deleg=True),
    '脏旧': dict(cues=['泥渍', '沙渍', '污渍'], locks=['干净', '使用痕迹'], deleg=False),
    '发色': dict(cues=['灰白', '白发', '掉色', '染色'], locks=['墨黑'], deleg=False),
    '上下同料明度': dict(cues=['两种不同面料', '更亮', '更平', '两种面料'],
                   locks=['上下同料', '同一色深', '同一套工艺', '同一种布'], deleg=True),
}
# 每域的主语名词——正面锁必须与它同句出现，否则等于没锁
NOUNS = {
    '肤色肤质': ['肤', '皮肤', '脸', '肌肤'],
    '妆感': ['唇', '眉', '妆', '眼', '素颜'],
    '配色': ['色', '配色', '衣缘'],
    '金属甲件': ['肩', '袖', '胸', '金属', '甲'],
    '武器': ['枪', '长条物', '武器', '麻布'],
    '幼态关节': ['脸', '骨骼', '关节', '年龄', '下颌'],
    '平涂画风': ['渲染', '画风', '布', '织物', '质感', '明度'],
    '排版文字': ['画面', '人物', '图', '排版'],
    '西方剪影': ['领', '肩', '裙', '袖', '剪影', '衣'],
    '脏旧': ['布', '衣', '渍', '痕迹'],
    '发色': ['发', '头发', '马尾'],
    '上下同料明度': ['上身', '下身', '下裙', '面料', '衣'],
}
REQUIRED = [('画幅', ['竖幅', '9:16']), ('人数', ['单个', '一人', '单一姿势']),
            ('景别', ['全身', '半身', '胸像', '特写']), ('背景', ['背景']),
            ('无烧字', ['不要出现任何文字', '一个汉字', '不要任何文字'])]


def _sentences(txt):
    return [s for s in re.split(r'[。！;；\n]', txt) if s.strip()]


# 禁令引导词**从 prompt_lint.NEG 单源取**（旧写法在这里另抄一份"不要|不许|禁止|切忌"，
# 两份词表一旦分开维护，S1 裸禁令就会漏认新写的"不得X/严禁X"——同一次 09-28 补词就撞上过）。
BAN_WORDS = sorted({n for n in L.NEG if len(n) >= 2}, key=len, reverse=True)
BAN_RE = re.compile(u'(?:' + u'|'.join(BAN_WORDS) + u')')


def ban_items(txt):
    """每条禁令宾语 + 它所在的分句（分句让括号里的列举能继承域）。"""
    out = []
    for sent in _sentences(txt):
        for m in BAN_RE.finditer(sent):
            body = sent[m.end():]
            par = re.search(r'[（(]([^）)]*)[）)]', body)
            pieces = re.split(u'[、，,；;]|——|' + u'|'.join(BAN_WORDS), body)
            if par:
                pieces += re.split(u'[、，,；;]', par.group(1))
            for pc in pieces:
                pc = pc.replace('**', '').strip()
                pc = re.sub(u'^(采用它的|再|把|出现|任何|新添加的|使用|成|为)', '', pc).strip()
                if 2 <= len(pc) <= 14 and (pc, sent) not in out:
                    out.append((pc, sent))   # 去重：一条禁令被两个否定词各切一次时不重复报
    return out


def domains_of(item, ctx):
    src = item + ctx
    return [k for k, v in DOMAINS.items() if any(c in src for c in v['cues'])]


def covered(txt, dom):
    """接住＝同一分句里同时出现该域主语名词 + 正面锁词；
    或该域允许委托、且某分句同时出现该域名词与委托语。"""
    nouns, locks = NOUNS[dom], DOMAINS[dom]['locks']
    for s in _sentences(txt):
        if not any(n in s for n in nouns):
            continue
        if any(lk in s for lk in locks):
            return True
        if DOMAINS[dom]['deleg'] and any(d in s for d in L.DELEGATE):
            return True
    return False


def s1_bare_bans(txt):
    bare, unknown, duty, seen = [], [], [], set()
    for it, ctx in ban_items(txt):
        dom = domains_of(it, ctx)
        if not dom:
            # 锚分工排除句（"不要采用它的构图/景别/背景"）不是属性禁令，是职责声明——单列，别混进"新病"堆
            if any(d in ctx for d in ['采用', '参考图', '第一张', '第二张']):
                duty.append(it)
            else:
                unknown.append(it)
            continue
        open_dom = [k for k in dom if not covered(txt, k)]
        if open_dom:
            key = (it, tuple(open_dom))
            if key not in seen:
                seen.add(key)
                bare.append((it, '/'.join(open_dom)))
    return bare, unknown, duty


def s2_required(txt):
    return [n for n, cues in REQUIRED if not any(c in txt for c in cues)]


VALUE_CONFLICTS = {
    '裙长': [['脚踝', '及地', '脚面'], ['及膝', '膝上', '短裙']],
    '领型': [['交领'], ['圆领', 'V 领', 'v领']],
    '武器位置': [['背后', '身后'], ['身侧', '胸前', '横在身体前面', '手持']],
    '画幅': [['竖幅', '9:16'], ['横幅', '16:9', '1:1']],
}


def _pos_hit(txt, word):
    """该值有没有被"肯定描述"用到（只活在禁令/分工句里的不算表态）。"""
    return any(not L.negated(txt, m.start()) for m in re.finditer(re.escape(word), txt))


def s3_conflicts(txt):
    out = []
    for attr, groups in VALUE_CONFLICTS.items():
        on = [g for g in groups if any(_pos_hit(txt, w) for w in g)]
        if len(on) > 1:
            out.append('%s：肯定句里同时给了 %s' % (attr, ' 与 '.join('+'.join(g) for g in on)))
    return out


# ── 留一验证：词表检测器到底有多少本事是"背下来的" ──────────────────────────────
# 做法：对每份文件，把"只有这一份里出现、其余三份都没有"的肯定句毒词从词表里临时抽掉，
# 重扫这一份，看闸门还拦不拦得住。拦不住＝这一批的检出**全靠背词**，遇到没见过的词就瞎。
VOC_LISTS = [L.SKIN_TOXIC, L.RENDER_TOXIC, L.ARMOR_TOXIC, L.WEAPON_TOXIC, L.DOLL_TOXIC,
             L.MAKEUP_TOXIC, L.COLOR_WORDS]


def pos_terms(txt):
    s = set()
    for voc in VOC_LISTS:
        for w, neg in L.find_terms(txt, voc):
            if not neg:
                s.add(w)
    return s


def leave_one_out(texts):
    per = [pos_terms(t) for _, t in texts]
    out = []
    for i, (name, t) in enumerate(texts):
        others = set().union(*[per[j] for j in range(len(texts)) if j != i]) if len(texts) > 1 else set()
        uniq = sorted(per[i] - others)
        saved = [list(v) for v in VOC_LISTS]
        try:
            for voc in VOC_LISTS:
                for w in uniq:
                    if w in voc:
                        voc.remove(w)
            r = L.scan_text(t)
        finally:
            for voc, old in zip(VOC_LISTS, saved):
                voc[:] = old
        out.append((name, uniq, r))
    return out


FILES = [('dz0b2/D1.txt', '画风漂（打回）'), ("dz0b2p/D1'.txt", '变白（打回）'),
         ('dz0b2pp/E1.txt', '偏卡通（打回）'), ('dz0b2ppp/F1.txt', '未打回·妆感漂已知')]


def report(txt):
    r = L.scan_text(txt)
    bare, unk, duty = s1_bare_bans(txt)
    return r, bare, unk, duty, s2_required(txt), s3_conflicts(txt)


if __name__ == '__main__':
    print('=== 结构检测器（不吃毒词表）在四批已知数据上 ===')
    print('%-18s %-18s %8s %8s %8s %6s' % ('文件', '人审', '词表点名', '裸禁令', '缺必填', '值矛盾'))
    rows = []
    for p, v in FILES:
        res = report(open(os.path.join(D, p), encoding='utf-8').read())
        rows.append((p, v) + res)
        print('%-18s %-18s %8d %8d %8d %6d'
              % (p, v, res[0]['n_pos'], len(res[1]), len(res[4]), len(res[5])))
    print()
    for p, v, r, bare, unk, duty, miss, conf in rows:
        print('### %s（%s）' % (p, v))
        if bare:
            print('  S1 裸禁令 %d 条（禁了，但全文没有同分句的正面锁/委托接住）：' % len(bare))
            for it, dm in bare:
                print('     · 不要%-14s → 空位【%s】' % (it, dm))
        if miss:
            print('  S2 缺必填规格：%s' % '、'.join(miss))
        if conf:
            print('  S3 值矛盾：%s' % '；'.join(conf))
        if duty:
            print('  （锚分工排除句 %d 条，正常，不计分）：%s' % (len(duty), '、'.join(duty[:8])))
        if unk:
            print('  ⚠ 未归类禁令 %d 条（检测器没见过的病，交人工判）：%s' % (len(unk), '、'.join(unk[:12])))
        if not (bare or miss or conf):
            print('  结构检测全清')
        print()

    print('=== 留一验证：抽掉"只在这份里出现过"的毒词，词表检测器还拦得住吗 ===')
    texts = [(p, open(os.path.join(D, p), encoding='utf-8').read()) for p, _ in FILES]
    for name, uniq, r in leave_one_out(texts):
        vocab_only = (r['n_pos'] > 0) or (r['struct_miss'] > 0)
        b2, _u2, _d2 = s1_bare_bans(dict(texts)[name])
        c2 = s3_conflicts(dict(texts)[name])
        struct_only = bool(b2) or bool(c2)
        print('  %-18s 抽掉 %2d 个独有词 %-26s 词表闸=%-6s 结构闸=%s'
              % (name, len(uniq), ('／'.join(uniq))[:26] or '（无独有词）',
                 '仍拦' if vocab_only else '漏', '仍拦' if struct_only else '漏'))
    print('  读法：词表闸抽词就漏＝那一批的检出是**记忆**不是能力；结构闸仍拦＝它不靠背词。')
    print('  ⇒ 两闸互补：词表闸答"用了哪个毒词"，结构闸答"这个属性有没有人接住"。')
    print('     上表凡是"词表闸=漏 而 结构闸=仍拦"的那一行，就是结构检测在补背词的盲区。')
