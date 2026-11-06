# -*- coding: utf-8 -*-
# 提示词静态 linter v2：在花钱出图之前，把本项目已踩过的病灶扫出来。
#
# v1 的问题（跑完四份已知提示词后暴露的）：
#   1) 「关节被点名」「禁令堆叠」在四份文件上得分恒定 → 纯偏置，零区分力，v2 降权为提示不算分；
#   2) 毒词只看"出没出现"，不看出现在**肯定描述句**还是**禁令括号列举**里。
#      实测反例：F1（人审通过）里写着"（肩甲、护臂、铆钉、胸甲、披膊一概不要）"——甲类词出现了 5 次却没出事；
#      而 D1'（被打回·变白）里"冷调瓷白肌肤"是**肯定描述**。差别在句位，不在词表。
#   → v2 对每个命中做句位判定：肯定句命中全额计分，禁令句命中只计 1/4。
#
# 验证口径：跑在四份"人已经判过"的提示词上，看分数能不能对上打回顺序，
# 并看 F1 的残留命中是否落在"禁令句"这一类。
import os
import re
import sys
import sys

D = r'D:/AIWorkflow/tmp/wzy'
os.chdir(D)
# 底座可能不在 sys.path 上（`importlib.util.spec_from_file_location` 那种导入方式不带路径），
# 先补一次；补不到就记进 PF_ERR，由 selftest／调用方当场说出来，不静默退回旧口径。
if D not in sys.path:
    sys.path.insert(0, D)

# ── 画风档（2026-09-25 深夜切换）───────────────────────────────────────────
# 他改了全片画风：从"即梦同款高精度 3D 半写实国漫"改判为"高精度 CG 半写实·写实赛博朋克"，
# 并给了要逐镜原句复用的《全局视觉风格基调》。于是原来那套毒词表**方向整个反过来**：
# 35mm／定焦／胶片／细颗粒／次表面散射／浅景深／写实／影视级 在国漫档里是"把整批渲成游戏 CG"的病灶词，
# 在写实档里是他点名要的规格。**不处理这个，闸会把每一张合规图都拦下。**
# 旧档保留（那四批人审标签是在它下面验出来的，不能悄悄毁掉标定证据），用 STYLE_PROFILE 切。
STYLE_PROFILE = os.environ.get('WZY_STYLE', 'realistic_cyber')

BASELINE = open(os.path.join(D, 'style_baseline.txt'), encoding='utf-8').read().strip()


def _norm(s):
    return re.sub(r'[\s，。、；：“”‘’（）()—-]', '', s)


RENDER_TOXIC_BY_PROFILE = {
    # 国漫档：写实／器材／电影词会把画风拖走
    'guoman_3d': ['35mm', '35 毫米', '定焦', '胶片', '细颗粒', '次表面散射', 'SSS', 'photorealistic',
                  'cinematic', '8K', '4K', '写实', '影视级', '浅景深', '镜头光晕', '散景', 'bokeh', '电影感'],
    # 写实档：反过来，卡通／平涂／游戏立绘那一路才是病灶
    'realistic_cyber': ['平涂', '厚描边', '赛璐璐', '二次元', '线稿', '游戏立绘', '立绘', '插画',
                        '卡通', '动漫', 'Q版', '硬边块面', '塑料廉价手游', '手游渲染', '亮片闪粉'],
}
REQUIRED_BY_PROFILE = {
    'guoman_3d': {'画幅': ['竖幅', '9:16'], '画风锚': ['半写实国漫', '渲染风格完全按第二张参考图']},
    'realistic_cyber': {'画幅': ['16:9', '横屏'], '体积光': ['体积光'], '湿反光': ['湿'],
                     '霓虹': ['霓虹'], '无烧字': ['无文字', '不要出现任何文字', '一个汉字']},
    # 古代线（T01–T05）：V3 总表 v3.4/v3.5 定案"纯古代约束"，霓虹/湿反光不是它的病灶，
    # 但画幅、体积光、无烧字这三条照样是硬规格，缺了就是规格漏写而不是风格选择。
    'realistic_ancient': {'画幅': ['16:9', '横屏'], '体积光': ['体积光'], '湿反光': ['湿'],
                     '无烧字': ['无文字', '不要出现任何文字', '一个汉字']},
}

NEG = ['不要', '不许', '不可', '禁止', '没有', '去掉', '不出现', '不采用', '不添加', '一概不',
       '无需', '不描述', '看不见', '不露', '不画',
       # 09-28 补齐：这批是"否定副词＋能愿动词"的常用写法，旧表漏了它们——
       # 漏一个，那句"不得卡通化"就会被当成**肯定句点名**，把低危措辞报成高危（词表不闭合的代价）。
       # 全部 ≥2 字：裸「别」会把"情景别/景别"误判成禁令句（同"裸『无』撞无缝"那条教训）。
       '不得', '不准', '不应', '不宜', '切勿', '切莫', '严禁', '请勿', '绝不', '绝对不会',
       # 09-28 第二批补齐：`check_preflight.BAN_LEADS` 里有「切忌」而本表没有 ⇒ 同一句
       # "切忌三脚架入画"在**格式闸**算禁令句（低危）、在**词表闸**算肯定句点名（高危）。
       # 两张手写词表必然漂，故本表升为唯一词源：check_preflight 现在 import 本表。
       '切忌',
       # ── 10-03 批 16：英文否定引导词。这批**不是新加的判断**，是把 `check_preflight.BAN_LEADS_EN`
       #    已在用的那组搬进唯一词源（G7 认英文否定、词表闸不认 ⇒ 同一句 "do not show any tripod"
       #    在 G7 算禁令句、在词表闸算"肯定句点名"＝高危，正是 09-28 那条漂移的英文版）。
       #    带尾空格的条目（`no `／`not `／`never `）＝"后面紧跟一个词"的引导词形，
       #    由底座 `PF.term_pattern` 按子串语义处理，裸 `no` 不收（会撞进 nothing／notice）。
       'do not', 'does not', 'don\'t', 'never ', 'no ', 'not ', 'without', 'avoid',
       'with no', 'nor ', 'cannot']
# 裸「无」「别」已删：实测会撞上"无缝""景别"，把肯定句误判成禁令句；
# 而真正靠"无X"起禁令的行（"不要西方剪影（无立领包颈…）"）前面本来就带"不要"。
SEP = '、，（）()'          # 从句首往回扫时跨过去的分隔符
# 子串误撞白名单：命中词前面若这些字，则不算（"半写实"≠"写实"，"银灰色"里的"灰色"等同理可扩展）
EXCLUDE = {'写实': ('半',), '铠': ('无', '解')}

# 句末／子句边界与匹配语义统一走底座 `prompt_format`（10-03 批 16）：
# 旧写法 `SENT_END = '。！？；\n'` 只认中文标点 ⇒ 英文正文一整段里没有句末，
# `negated()` 的"往回扫到句首"退化成"扫到整篇开头"，任何一句里出现过的否定词
# 都会被算成管住了后面所有毒词 ⇒ 高危点名被洗成低危（假阴）。
try:
    import prompt_format as PF
except Exception as _e:      # 底座不在 ⇒ 明确降级，并让调用方看得见（不静默按旧口径）
    PF = None
    PF_ERR = str(_e)
else:
    PF_ERR = None


def _sent_marks():
    return PF.SENT_END_MARKS if PF else ('。', '！', '？', '；', '\n')


SENT_END = _sent_marks()


def _iter(txt, voc):
    """(条目, 起点) 序列：英文条目走词边界＋复数容忍，中文条目走子串（底座一处实现）。"""
    if PF:
        return list(PF.iter_terms(txt, voc))
    out = []
    low = (txt or "").lower()
    for w in voc:
        i = low.find(w.lower())
        while i >= 0:
            out.append((w, i))
            i = low.find(w.lower(), i + 1)
    return out

SKIN_TOXIC = ['瓷白', '冷白', '冷调', '通透', '白皙', '水光肌', '玻璃肌', '雪白', '惨白', '亮白', '柔润']
RENDER_TOXIC = RENDER_TOXIC_BY_PROFILE[STYLE_PROFILE]
ARMOR_TOXIC = ['肩甲', '披膊', '云肩', '胸甲', '鳞甲', '护臂', '铆钉', '甲片', '四合', '补子', '护心镜', '铠', '肩片']
WEAPON_TOXIC = ['长枪', '枪头', '枪尾', '枪尖', '枪托', '扳机', '革套', '剑', '方天画戟']
DOLL_TOXIC = ['BJD', '球关节', '人偶', '可动人偶']
# 妆感轴：词表不是我自己发明的，全部抄自他文档里已经人审定案的诊断
# （武昭君仪_剧本与资产盘点_v1.md 第 817 行："真正主因＝妆感词：'唇形饱满'→红唇、'眉色深'→浓眉，
#   加上'不要浓妆艳唇'是点名式禁令"；F 轮实测"眼变圆、烟熏眼妆、唇更红"＝妆感漂，但身份 0.799 反而最好）
MAKEUP_TOXIC = ['唇形饱满', '眉色深', '浓妆', '艳唇', '红唇', '唇釉', '烟熏', '眼影', '眼线', '水光唇']
COLOR_WORDS = ['奶白', '朱砂', '月白', '银灰', '淡烟青', '烟墨', '深海蓝', '藏蓝', '墨青', '米白',
               '象牙白', '深褐', '赤金', '明艳红金', '主色', '配色以']
DECOR_WORDS = ['纹样', '提花', '绣', '饰件', '流苏', '密度', '珠链', '透纱', '层叠', '银点', '花纹',
               '图案', '照搬', '一处都不许', '不许简化']
STRUCT_ONLY = ['形制', '款式', '剪影', '版型']
DELEGATE = ['让第二张参考图决定', '让参考图决定', '完全按第二张参考图', '按第一张参考图',
            '按第一张', '完全沿用第二张', '让第一张参考图决定']

# 每项：词表、单词权重、句位判定是否生效
AXES = {
    '肤色漂白':  (SKIN_TOXIC,   2, True),
    '画风漂写实': (RENDER_TOXIC, 2, True),
    '甲类被点名': (ARMOR_TOXIC,  1, True),
    '武器被点名': (WEAPON_TOXIC, 1, True),
    '关节被点名': (DOLL_TOXIC,   1, True),
    '妆感被点名': (MAKEUP_TOXIC, 2, True),
}


def negated(txt, pos):
    """命中点往前扫：先撞到否定词＝禁令句；先撞到句末＝肯定描述句。"""
    # 紧邻前缀否定：「无唇釉」「非红唇」这种紧贴的写法先判掉，
    # 比把裸「无」塞进 NEG 安全（裸"无"会撞上"无缝"，把肯定句误判成禁令句）。
    if pos > 0 and txt[pos - 1] in '无非不':
        return True
    if PF:
        start = PF.sent_start(txt, pos)
    else:
        start = max((txt.rfind(e, 0, pos) for e in SENT_END), default=-1) + 1
    seg = txt[start:pos]
    segl = seg.lower()          # 英文引导词按大小写不敏感（句首的 "Do not" 也是引导词）
    best, blen = -1, 0
    for n in NEG:
        i = segl.rfind(n.lower())
        if i > best:
            best, blen = i, len(n)
    if best < 0:
        return False
    # 否定词之后若又出现句末以外的独立谓语（如"不要X，她穿着Y"）则不算管住这个词。
    # 尾巴按**该否定词自身长度**切：旧写法一律 +2，遇上"绝对不会/一概不"会把切点落在词中间。
    tail = seg[best + blen:]
    if any(e in tail for e in SENT_END):
        return False
    return True


def find_terms(txt, voc):
    """返回 [(词, 是否禁令句)]，同一个词多次出现分别判定。"""
    out = []
    for w, s in _iter(txt, voc):
        exc = EXCLUDE.get(w, ())
        if any(txt[:s].endswith(p) for p in exc):
            continue          # 撞子串（如"半写实"命中"写实"）→ 不算
        out.append((w, negated(txt, s)))
    return out


def scan_text(txt):
    hits, score, detail = [], 0, {}
    n_pos = 0                       # 「肯定句点名」总次数——v2 实测出的主判据
    for ax, (voc, wgt, use_pos) in AXES.items():
        found = find_terms(txt, voc)
        if not found:
            continue
        pos_terms = sorted({w for w, neg in found if not neg})
        neg_terms = sorted({w for w, neg in found if neg})
        n_pos += len(pos_terms)
        s = len(pos_terms) * wgt + 0.25 * wgt * len(neg_terms)
        detail[ax] = round(s, 2)
        if pos_terms:
            hits.append('%-12s 肯定句点名 %s  ← 高危：这是描述不是禁令' % (ax, '/'.join(pos_terms)))
        if neg_terms and not pos_terms:
            hits.append('%-12s 仅出现在禁令句 %s  （低危，按实测压不住但也没翻车）'
                        % (ax, '/'.join(neg_terms[:6])))
        score += s
    # 委托未交全：说了"按参考图"，却仍留着**肯定句里的**颜色词
    if any(d in txt for d in DELEGATE):
        c = [w for w, neg in find_terms(txt, COLOR_WORDS) if not neg]
        if c:
            hits.append('委托未交全     写了"按参考图"却仍有颜色词作描述：%s → 文本会压掉锚图' % '/'.join(c))
            score += 4 * len(c)
            n_pos += len(c)
            detail['委托未交全'] = 4 * len(c)
    # 主语覆盖：说了形制/款式、或把服装交给参考图，却没把装饰密度写进句子
    need_decor = any(w in txt for w in STRUCT_ONLY) or '服装' in txt or '第二张参考图' in txt
    has_decor = any(w in txt for w in DECOR_WORDS)
    if need_decor and not has_decor:
        hits.append('主语覆盖不足   只锁"形制/款式"，纹样·饰件·密度没进句子 → 装饰被简化＝偏卡通')
        score += 5
        detail['主语覆盖'] = 5
    elif need_decor and not any(w in txt for w in ['密度', '照搬', '一处都不许', '不许简化']):
        hits.append('主语覆盖偏弱   提到装饰但没锁"密度/不许省" → 模型会取最低成本那维')
        score += 2
        detail['主语覆盖'] = 2
    n_ban = len(re.findall(r'不要[^\n，。；]{0,12}', txt))
    return {'score': round(score, 2), 'hits': hits, 'detail': detail,
            'n_pos': n_pos,                 # 肯定句里点名的毒词数——实测主判据
            'struct_miss': detail.get('主语覆盖', 0),
            'n_ban': n_ban, 'profile': STYLE_PROFILE}


def scan(p):
    return scan_text(open(p, encoding='utf-8').read())


def gate(r):
    """出图前的零成本闸：两条都不触发才放行。"""
    return r['n_pos'] == 0 and r['struct_miss'] == 0


def norm(t):
    # 破折号放字符类末尾：写成 \- 在 py3.12 是 invalid escape（SyntaxWarning），语义不变
    return re.sub(r'[\s，。、；：""''（）,.;:()—-]+', '', t)


def profile_check(txt, profile=None, baseline=None):
    """基调原句 + 必填规格：与 scan() 分开算。
       scan() 的四档标定（12/4/0/2）是在旧口径上验的，把这项折进 score 会作废那份标定，
       所以这里只做独立一条硬检查，由调用方（H3 真源）自己决定拦不拦。"""
    profile = profile or STYLE_PROFILE
    baseline = baseline or BASELINE
    out = []
    b = norm(baseline)
    n = norm(txt)
    if b in n:
        pass
    elif n.find(b[:40]) >= 0:
        out.append('基调被改写（前 40 字对得上、后面不一样）+3')
    else:
        out.append('基调缺失（未逐字复用《全局视觉风格基调》原句）+6')
    for k, alts in REQUIRED_BY_PROFILE.get(profile, {}).items():
        if not any(norm(a) in n for a in alts):
            out.append('必填规格缺项：%s（%s）+3' % (k, '/'.join(alts)))
    return out


FILES = [('dz0b2/D1.txt', '画风漂（打回）'),
         ("dz0b2p/D1'.txt", '变白（打回）'),
         ('dz0b2pp/E1.txt', '偏卡通（打回）'),
         ('dz0b2ppp/F1.txt', '未打回·妆感漂已知待修')]
# ⚠️ 第四份不是"通过版"：他文档第 817/821 行记着 F 轮"眼变圆、烟熏眼妆、唇更红"＝妆感漂，
#    ⑤ 号修复方案还挂着等他点头。它只是"没被打回＋待拍板"，标签别再写成"通过"。

def selftest():
    """词表闸的**自检**（教训⑧：表不闭合，闸自己不知道）。跑在 import 之后由调用方执行。"""
    bad = []
    if PF is None:
        bad.append('底座 prompt_format 没加载（%s）⇒ 句末边界与英文词条匹配退回旧口径，'
                   '英文正文的否定句会被算成肯定句点名' % PF_ERR)
    for n in NEG:
        if len(n) < 2:
            bad.append('NEG 有单字词「%s」：会把"景别/无缝"误判成禁令句' % n)
    if len(set(NEG)) != len(NEG):
        bad.append('NEG 有重复项：%s' % [n for n in set(NEG) if NEG.count(n) > 1])
    # 英文否定引导词必须在场（10-03 批 16）：少了它，`negated()` 在英文正文上恒 False，
    # "do not show any text" 这种句子会被算成**肯定句点名**＝把低危措辞报成高危。
    _en = [n for n in NEG if n.isascii()]
    if len(_en) < 5:
        bad.append('NEG 里英文引导词只有 %d 条 ⇒ 英文正文的禁令句判定等于没做' % len(_en))
    for ax, (voc, wgt, _u) in AXES.items():
        if not voc:
            bad.append('轴「%s」词表为空' % ax)
        if len(set(voc)) != len(voc):
            bad.append('轴「%s」词表有重复' % ax)
        if wgt <= 0:
            bad.append('轴「%s」权重非正' % ax)
    if STYLE_PROFILE not in RENDER_TOXIC_BY_PROFILE:
        bad.append('画风档 %s 没有毒词表 ⇒ 会拿别的档的表来判它' % STYLE_PROFILE)
    if set(RENDER_TOXIC_BY_PROFILE) - set(REQUIRED_BY_PROFILE):
        bad.append('有毒词表却没配必填规格的档：%s'
                   % (set(RENDER_TOXIC_BY_PROFILE) - set(REQUIRED_BY_PROFILE)))
    # 跨档互斥自检：同一个词同时是 A 档毒词又是 B 档毒词，说明有一档标定错了
    a, b = RENDER_TOXIC_BY_PROFILE['guoman_3d'], RENDER_TOXIC_BY_PROFILE['realistic_cyber']
    both = sorted(set(a) & set(b))
    if both:
        bad.append('两档毒词表交集非空（互相矛盾）：%s' % both)
    print('prompt_lint 词表自检：%s' % ('✓ 通过（档=%s，NEG %d 词，%d 轴）'
                                  % (STYLE_PROFILE, len(NEG), len(AXES)) if not bad else ''))
    for x in bad:
        print('   ✗ %s' % x)
    return not bad


if __name__ == '__main__':
    selftest()
    print('主判据＝「肯定句点名数」：毒词写在描述句里才计分，只写在"不要X"里按 1/4 计。')
    print('%-18s %-22s %8s %8s %8s' % ('提示词', '人审结果', '肯定句点名', '主语覆盖', '加权分'))
    print('-' * 74)
    rows = []
    for p, verdict in FILES:
        r = scan(p)
        rows.append((p, verdict, r))
        print('%-18s %-22s %8d %8s %8s'
              % (p, verdict, r['n_pos'], r['struct_miss'], r['score']))
    print()
    print('判据核对（现场算，不写死）：')
    for p, verdict, r in rows:
        gate = '放行' if (r['n_pos'] == 0 and r['struct_miss'] == 0) else '拦下'
        why = []
        if r['n_pos']:
            why.append('肯定句点名%d' % r['n_pos'])
        if r['struct_miss']:
            why.append('主语覆盖缺密度锁')
        print('   %-18s 人审=%-20s 闸=%s%s' % (p, verdict, gate,
              ('（' + '+'.join(why) + '）') if why else ''))
    print("→ 闸门是**按轴**判的，不是按总分排名：不同缺陷之间没有可比的大小，")
    print("  总分只用来看「这一份离干净还有多远」，不用来给批次分高下。")
    print("  每条改法上线后重跑本表，目标是被拦的理由逐条减少、直到全部放行。")
    print()
    for p, verdict, r in rows:
        print('### %s  肯定句点名 %d / 加权 %.2f（%s）' % (p, r['n_pos'], r['score'], verdict))
        if r['detail']:
            print('    分项: ' + '  '.join('%s=%s' % kv for kv in sorted(
                r['detail'].items(), key=lambda x: -x[1])))
        for x in r['hits']:
            print('    ', x)
        if not r['hits']:
            print('     无命中')
        print()
