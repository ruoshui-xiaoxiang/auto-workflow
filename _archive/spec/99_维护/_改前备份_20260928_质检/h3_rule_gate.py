# -*- coding: utf-8 -*-
"""《H3 提示词工程规则方案》收录后的机器层。

真源（唯一）：D:/AIWorkflow/ComfyUI_H3/H3提示词工程规则方案.md
  v2（桌面 355 行快照）+ R16（一镜一场景）+ R17（时长＝信息单元 × ~1s）= 357 行版。
  桌面上的 `H3提示词工程规则方案.md` 是旧快照，本脚本跑完会把真源整份回写过去。

这个脚本做三件事，别的都不做：
  1) 把方案里**能静态检**的条款编成闸，对 h3_shots.SHOTS 的 23 镜逐条跑；
  2) 把**机器判不了**的条款登记成"生成后 VL 四问"（方案第十节）——供拼片前自检用；
  3) 登记方案与本管线**已经互相冲突的三处**，不替他裁决，只留痕。

编号用 H3R*（方案的第四节），和 prompt_rules.py 里的 R1–R5（项目措辞法条：矛头/金属/云肩/BJD/免责句）
是两套完全不同的东西，别混着引用。

只报不拦：本脚本不 SystemExit。闸的强度分级写在每条规则里，判废权仍归人（completed ≠ confirmed）。
"""
import importlib.util
import io
import os
import re
import sys
import contextlib

D = r'D:/AIWorkflow/tmp/wzy'
DOC = r'D:/AIWorkflow/ComfyUI_H3/H3提示词工程规则方案.md'
DESK = r'C:/Users/若水/Desktop/H3提示词工程规则方案.md'

# ---------------------------------------------------------------- 方案里可静态检的词表
# 第五节：H3 官方 13 类运镜。方案要求"运动类型＋幅度＋速度"，写成英文受控词。
CAM_EN = ['Zoom', 'Push', 'Pull', 'Pan', 'Tilt', 'Truck', 'Pedestal', 'Arc', 'Orbital',
          'Tracking', 'Static', 'Shake', 'Roll', 'POV']
CAM_ZH = {'推': 'Push In', '拉': 'Pull Out', '摇': 'Pan', '横移': 'Truck', '移': 'Truck',
          '升': 'Pedestal Up', '降': 'Pedestal Down', '环绕': 'Arc', '跟': 'Tracking',
          '固定': 'Static', '甩': 'Pan(whip)', '手持': 'Shake', '主观': 'POV',
          '上摇': 'Tilt Up', '下摇': 'Tilt Down', '俯': 'Tilt', '仰': 'Tilt'}
# 第五节反例：写"结果"不写"镜头动作"→官方实证无效
CAM_RESULT_ONLY = ['完整入镜', '始终可见', '保持在画面内', '不要出画', '充满画面']
# R8：光影必须用写实动词，"流出/击中/射出"会被实体化成激光束
LIGHT_NOUN = ['光', '霓虹', '灯', '辉', '冷光', '暖光', '反射']
LIGHT_BAD_V = ['流出', '射出', '击中', '射在', '打中', '射入', '喷']
# R5：生成式特效反例（H3 上禁令不计效，只登记不依赖）
FX_BAD = ['能量波', '激光', '冲击波', '光波', '爆炸']
FX_POS = ['细碎', '细小', '橙金', '半透明', '银白', '余辉', '碎屑', '尘', '火星']
# R13：抽象概念必须翻译成物理动作。方案自己（R10）又把「借力打力／章法」当推荐词用——见 CONFLICTS。
ABSTRACT = ['借力打力', '借力', '以柔克刚', '四两拨千斤', '章法', '专业', '干净利落',
            '迅速', '凌厉', '威猛', '气势', '气场', '高手风范', '从容', '熟练']
BODY = ['手', '臂', '掌', '拳', '指', '肩', '背', '腰', '腿', '膝', '脚', '身', '头', '眼', '腕']
# R14：接触底线。出现身体部位＋攻防动词，就必须有一句写死的底线。
FIGHT_V = ['打', '扑', '抓', '挥', '击', '踢', '扫', '绊', '撞', '砸', '拽', '抡', '推', '刺']
FACE = ['脸', '面门', '头', '咽喉', '太阳穴']
底线_MARK = ['绝不', '没碰到', '未碰到', '不接触', '没有碰到', '绝对没', '不被']
# R16：场景名词族（低置信，只提示不判死）。同镜出现两族＝跨场景风险。
SCENE_FAMILY = {
    '古建夜行': ['院墙', '墙根', '青砖', '灯笼', '更鼓', '屋檐', '城门', '街', '巷口', '屋', '案', '砚'],
    '郊野黄昏': ['树影', '林', '雾', '泥', '土路', '荒野', '坡', '蝉'],
    '下层区赛博': ['霓虹', '高楼', '管道', '锈', '湿铺装', '下层', '全息', '招牌', '废土', '机油'],
    '室内赛博': ['舱', '控制台', '屏幕', '金属墙', '电缆'],
}
# 第十节：生成后 VL 四问（逐字按方案），拼片前自检用
VL_QUESTIONS = [
    '画面里的武器是枪还是剑？是一根还是两根？布有没有拆开？',
    '谁面对谁？有没有人站到了别人身后？',
    '【本镜事件脚本点名的动作】有没有全部演到位？',
    '这段打斗像高手过招、有章法，还是像乱扑乱抓？',
]
# 第十二节：动作容量甜点。剧烈 2–4 步，从容 6 步+。
VIOLENCE = ['打', '扑', '抓', '拳', '踢', '扫', '搏', '绊', '砸', '抡', '刺', '撞']


def load_shots():
    """导入真源模块拿 SHOTS（不跑它的主流程，避免重写 jobs.json）。"""
    spec = importlib.util.spec_from_file_location('h3_shots', os.path.join(D, 'h3_shots.py'))
    H = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(H)
        lines = H.load_ch1()
        H.build(lines)
        for s in H.SHOTS:
            s['costume_tag'] = 'A02' if s['style'] == 'anc' else 'A01'
            H.timing(s)
    return H, H.SHOTS


def steps(s):
    return [x.strip() for x in s['beat'].split('→') if x.strip()]


def chk(name, lvl, msg):
    return dict(name=name, lvl=lvl, msg=msg)


def check_shot(H, s, prompt):
    """返回 [(规则号, [chk,...])]；只收录有命中项的规则。"""
    out = []
    vis = H._DLG_SPAN.sub('', prompt)          # 视觉描述区（台词剔掉）
    st = steps(s)
    n = len(st)
    violent = any(v in s['beat'] for v in VIOLENCE)

    # ---- H3R3 / H3R11 / H3R15：一镜一主动作、容量＝步数×剧烈度
    lvl = 'ok'
    if violent and n > 4:
        lvl = 'warn'
    if not violent and n > 6:
        lvl = 'warn'
    out.append(('H3R3/11/15', [chk('步数', lvl,
                '%d 步·%s（甜点：剧烈 2–4，从容 6+；超出＝糊＋漂，不是硬吞）→ %s'
                % (n, '剧烈' if violent else '从容', ' / '.join(st)))]))

    # ---- H3R7：收尾留时间。判据只认"末步还是别人在出招"——
    #      我们的 beat 链是叙事节拍（不是逐拍动作脚本），尾步本身常常就是收势，
    #      所以不能因为末步没出现"收/立/停"就报缺陷（第一版这样报，23 镜中了 20 条＝纯噪声）。
    if st:
        tail = st[-1]
        risk = any(w in tail for w in ['逼近', '扑', '冲来', '再打', '挥', '抓', '追'])
        out.append(('H3R7', [chk('收势', 'warn' if risk else 'ok',
                   '末步「%s」仍是对方在出招⇒收势会被挤掉，最后 1s 要留给自己收势' % tail if risk
                   else '末步「%s」' % tail)]))

    # ---- H3R17：时长 ≈ 信息单元 × 0.9–1.2s
    #      超载侧（塞不下）保留 warn：那是 R17 的实测来源（P1A 8 单元硬塞 5 秒）。
    #      空转侧（多给时间）2026-09-27 已实测否证 ⇒ 降为参考级，只报不判、不作返工依据。
    #      依据：wzy/motion_curve.py 跑已渲 8 镜的光流衰减比，"秒/单元"与"尾塌"相关性
    #            Pearson 0.63 / Spearman 0.36（n=8），方向还与"拖长"相反 ⇒ 空转不预测拖长。
    #            全片 20/23 镜按字面都"超配"，若当缺陷＝整章返工，代价必须实测付过才能要。
    #      详见 h3/R17空转实测.md（与 G6 底线句同一处理逻辑：分界线＝有没有实测数据）。
    units = n * 1.0 + len(s['dlg']) * 1.75
    if s['secs'] < units * 0.9:
        out.append(('H3R17', [chk('超载', 'warn',
                   '信息单元 %.2f（%d 动作 + %d 句台词×1.75）需要 ≥%.1fs，实给 %.2fs ⇒ H3 会拖长前面的动作凑时长'
                   % (units, n, len(s['dlg']), units * 0.9, s['secs']))]))
    elif s['secs'] > units * 1.5:
        out.append(('H3R17', [chk('空转', 'info',
                   '单元 %.2f 给了 %.2fs（%.2f×上限，参考级：8 镜实测此比值不预测拖长，别据此返工）'
                   % (units, s['secs'], s['secs'] / (units * 1.2)))]))
    else:
        out.append(('H3R17', [chk('时长', 'ok', '单元 %.2f / %.2fs，落在 0.9–1.2s×单元' % (units, s['secs']))]))

    # ---- H3R9 + 第七节：声音必写、且除 N/A 外别处不出现"音乐"
    hits = []
    if not s['snd'].strip():
        hits.append(chk('声音', 'error', '【声音】空 ⇒ 会出乱码杂音'))
    if 'non_diegetic_music: N/A' not in prompt:
        hits.append(chk('N/A', 'error', '缺 non_diegetic_music: N/A'))
    for m in re.finditer('音乐', vis):
        hits.append(chk('泄漏', 'warn', '正文出现「音乐」二字（除 N/A 外别处写了就可能漏进来）'))
    out.append(('H3R9/§七', hits or [chk('声音', 'ok', '环境声已写 + N/A 在场 + 正文无"音乐"')]))

    # ---- §五：镜头用官方受控词，且写动作不写结果
    cam = s['cam']
    zh = [v for k, v in CAM_ZH.items() if k in cam]
    en = [v for v in CAM_EN if v in cam]
    res = [w for w in CAM_RESULT_ONLY if w in cam or w in vis]
    lvl = 'ok' if (zh or en) and not res else ('warn' if res else 'info')
    msg = '中文动词→官方词：%s；英文受控词：%s' % ('、'.join(zh) or '无', '、'.join(en) or '无')
    if res:
        msg += '；⚠ 写了"结果"没写"镜头动作"：%s' % '、'.join(res)
    if zh and not en:
        msg += '；提示词里运镜是中文，官方受控词表（英文）未出现＝可选加码'
    out.append(('§五', [chk('运镜', lvl, msg)]))

    # ---- H3R8：光影动词写实
    #      判据＝"光"当主语＋会射出去/打人的动词。先把「反射」挖掉再扫，
    #      否则基调里的"霓虹反**射在**黑色湿铺装"会被误判成激光（第一版就误报了 18/23）。
    bad = []
    for line in re.split(r'[。；;]', vis.replace('反射', '映照')):
        if any(w in line for w in LIGHT_NOUN) and any(v in line for v in LIGHT_BAD_V):
            bad.append(line.strip()[:34])
    msg = ('光被写成会射出去的东西：' + ' ｜ '.join(bad[:3])) if bad else '无「光＋流出/击中/射出」'
    out.append(('H3R8', [chk('光影', 'warn' if bad else 'ok', msg)]))

    # ---- H3R5（真源 v2.1 改判后）：判据＝正向物理描述在不在；排除句不计效、也不算缺陷
    pos = [w for w in FX_POS if w in vis]
    bad = [w for w in FX_BAD if w in vis]
    if bad:
        out.append(('H3R5', [chk('特效', 'warn' if not pos else 'info',
                   '画面里有特效词（%s）而正向物理描述=%s。v2.1 口径：排除句压不住（禁令即在点名），'
                   '判据只有"看得见的材质与形状"＋首帧' % ('、'.join(bad), '、'.join(pos) or '缺失')
                   if not pos else '特效词 %s 有正向质感描述兜着（%s），排除句不计效' % ('、'.join(bad), '、'.join(pos)))]))

    # ---- H3R13：抽象概念要落成物理动作（本条与 R10 在方案内部互相打脸，见 CONFLICTS）
    bad = []
    for clause in re.split(r'[，。；、]', vis):
        for w in ABSTRACT:
            if w in clause and not any(b in clause for b in BODY):
                bad.append(clause.strip()[:24])
    msg = ('抽象词单独成句、同一子句里没有身体部位：' + '"、"'.join(bad[:3])) if bad \
        else '抽象词都与具体身体动作同句'
    out.append(('H3R13', [chk('抽象词', 'warn' if bad else 'ok', msg)]))

    # ---- H3R14 / G6 底线写死：2026-09-27 他批"暂时作为所有镜参考，实测补完后再说"
    #      ⇒ 从"只查打斗镜"放宽到全片参考，但**降为参考级**（info），不升成 warn/闸；
    #        升级判据留给 H11–H15 那五镜成片：写了底线句的镜是否真的没出现"拳打中脸"。
    if any(f in s['beat'] + s['main'] + s['begin'] + s['end'] for f in FACE):
        has = any(m in vis for m in 底线_MARK)
        tail = '已写死底线' if has else '未写"绝不/没碰到"这类可画面验的否定'
        msg = '本镜叙事点到脸/头/咽喉，' + tail + '（G6 现为参考级，等 H11–H15 实测再决定是否升级）'
        out.append(('H3R14', [chk('底线', 'ok' if has else 'info', msg)]))

    # ---- H3R16：一镜一场景（低置信，只提示不判死）
    #      扫描范围＝本镜叙事（beat＋三句切片），不含全局基调：
    #      基调里"古风武侠与赛博朋克并置"是全片对照语，扫它会 23 镜全命中两族＝无信息。
    narr = s['beat'] + s['begin'] + s['main'] + s['end']
    fam = {f for f, ws in SCENE_FAMILY.items() if sum(w in narr for w in ws) >= 2}
    out.append(('H3R16', [chk('场景', 'warn' if len(fam) > 1 else 'ok',
               '本镜叙事命中 %d 个场景族 %s（场景锚=%s）⇒ 跨场景要拆镜' % (
                   len(fam), '、'.join(sorted(fam)) or '无', s['scene']))]))

    # ---- H3R1/R2：道具形态锁 / 朝向锁（R1 可静态查有无锁句，R2 只能 VL）
    lock = '形态、数量' in vis and '不拆开' in vis
    out.append(('H3R1', [chk('道具锁', 'ok' if lock else 'warn',
               '【保持一致】里的形态/数量/比例锁句%s' % ('在场' if lock else '缺失'))]))
    return out


# ---------------------------------------------------------------- 作用域（2026-09-27 加）
# 为什么要这张表：本项目并存三条产物线（A 第一章 H3／B 万相 3.0／C 三阶打斗 12 镜，C 由另一条工具线写的），
# 而"锁某个道具当前状态"的条款不是全片真理——A 线是"全程不拆布"，C 线 P3 的剧情就是"解布亮枪"。
# 闸不标作用域会犯两种错：拿 A 线纪律去否掉 C 线的剧情，或让下一个工具以为"这项目不许出现枪"。
SCOPE = [
    ('视觉描述区零"枪"字（h3_shots 硬闸）', '仅 A 线·裹布阶段（H01–H23）',
     'C 线 P3「亮枪／不裹布」按剧情就该有"枪"——不算违规，但它也没过本闸；三线规格不同，产物不可混剪'),
    ('SPEAR_LOCK 全程不拆开·不露本体', '仅 A 线·裹布阶段',
     '若"两章内不拆布"这条设定被 C 线推翻，要改的是设定不是闸'),
    ('法条 R1 不出现 矛头/金属/刃', '全片通用', '它防"被实体化"，与道具处于哪个阶段无关'),
    ('台词逐字＝正文 c12_source.txt', '全片通用',
     'other_lines_check.py 实测：C 线 12 份里 7 条正文查无且换了说话人；B 线逐字全对'),
    ('词表闸＋结构闸 G7＋管线闸', '仅 A 线（编译路径上）',
     'B/C 各走自己脚本，35 份外来提示词 0 份被看过 ⇒ 用 other_lines_check.py 补审计，只报不拦'),
]


CONFLICTS = [
    ('R10 vs R13（方案内部）',
     'R10 让写「马步沉腰／枪花一抖／借力打力／收放有度」这类"章法词"；'
     '第十一节和 R13 又说「借力打力／以柔克刚」是抽象词、H3 读不懂，"专业有章法"无效。'
     '⇒ 收录口径：章法词只能跟在具体身体动作后面当标签，不能单独成句；'
     'R13 是本机检的实际判据（抽象词同句无身体部位＝warn）。'),
    ('R5 的禁令句 vs 本机已验的"H3 禁令无效" ——已裁：2026-09-27 他批准 A 方案，真源改判到 v2.1',
     '原冲突：方案标准写法是"不得画成能量波、激光束、爆炸"，而 09-22 实测＋09-26 夜跑的枪字泄漏都表明'
     'H3 上禁令即在点名、压不住。⇒ 已把真源 R5 改成：**正向物理描述＝判据**，排除句降级为"可留但不计效"。'
     '本脚本随之只查"正向物理描述在不在"（不在＝warn）；排除句本身不再算缺陷。'),
    ('§九／§十一 的字面 vs 本管线永久"枪"硬闸',
     '方案示例逐字用「长枪／枪杆／枪头／枪花一抖／端枪／白麻布裹严」；'
     '而 h3_shots.py 的硬闸是"视频提示词视觉描述区一个『枪』字都不许出现"（H07 把缠布长杆渲成子弹换来的）。'
     'DEGUN 表覆盖 长枪/枪杆/枪头/枪尾/枪身/提枪/端枪/握枪/裹枪/收枪，'
     '但**没覆盖 枪花／枪尖／枪法／枪缨／枪柄／回马枪／一杆枪／舞花**——实测走裸兜底（「枪」→「长杆」）产出：'
     '枪花→长杆花、枪尖→长杆尖、枪法→长杆法、回马枪→回马长杆、一杆枪→一杆长杆。'
     '字面闸查不出来（"枪"确实没了），但中文是坏的。'
     '⇒ 招式表要能用，得先补这张映射（见下）；已给建议，未擅自改方案原文。'),
    ('§六 素材绑定 vs fl2va/ref2va 互斥',
     '方案第六节是 Ref2VA 的"图1 管身份、图2 管道具、冲突以图1 为准"。'
     '本管线走 fl2va（只有一张首帧、没有 ref_images），所以第六节在这条线上不适用，'
     '一致性全部前移到首帧生成那一步（云端 Seedream 挂锚）。⇒ 收录为"仅 ref2va 线适用"。'),
]
# 建议补进 DEGUN 的招式映射（去枪化、保留攻防因果）
SPEAR_MOVE_MAP = [
    ('拦', '杆身横摆，格开对方抓来的手'), ('拿', '杆身下沉一压，黏住对方手臂'),
    ('扎', '缠布的那一端直线向前刺出'), ('崩', '杆身由下往上一抖，弹开对方'),
    ('点', '缠布端向下一沉，快速点向对方手腕'), ('穿', '从对方手臂下方穿进'),
    ('压', '杆身向下压住对方'), ('劈', '高高扬起、向下劈落'),
    ('缠', '绕对方手臂转一圈绞住'), ('舞花', '在身体两侧翻飞划圆'),
    ('回马枪', '假意转身败走、突然反身回刺'), ('枪花', '手腕一抖、缠布的杆在身前翻一圈'),
]
# 领域词表：打戏线以后还会写到的含"枪"名词。用来跑"词形覆盖自检"。
DOMAIN_WORDS = ['长枪', '枪杆', '枪头', '枪尾', '枪身', '提枪', '端枪', '握枪', '裹枪', '收枪',
                '枪花', '枪尖', '枪法', '枪缨', '枪柄', '回马枪', '一杆枪', '舞花', '扎枪', '拿枪']


def degun_coverage(H):
    """替换表覆盖自检：领域词逐条过 degun()，凡是靠裸兜底过的＝表没闭合（输出会是坏中文）。"""
    explicit = {a for a, _b in H.DEGUN if a != '枪'}
    gap = []
    for w in DOMAIN_WORDS:
        out = H.degun(w)
        if out != w and w not in explicit:
            gap.append((w, out))
    return explicit, gap


def vl_plan(SH):
    print('\n—— 第十节 生成后 VL 四问（机器判不了的，交给拼片前自检）——')
    for i, q in enumerate(VL_QUESTIONS, 1):
        print('  %d. %s' % (i, q if '【本镜' not in q else
                            q.replace('【本镜事件脚本点名的动作】', '该镜 beat 链逐步（逐镜展开成具体问句）')))
    print('  覆盖规则：H3R1 道具形态 / H3R2 朝向 / H3R3·11 动作到位 / H3R10 质感层次')
    print('  注：单帧识别分不清"运镜转走"与"主体消失"⇒ 逐镜按秒抽 3 帧分别问，别笼统问"有没有瑕疵"。')


if __name__ == '__main__':
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    H, SH = load_shots()
    print('真源方案：%s（%d 字节，含 R16/R17）' % (DOC, os.path.getsize(DOC)))
    print('桌面快照：%s' % DESK)
    same = (os.path.isfile(DESK) and open(DESK, 'rb').read() == open(DOC, 'rb').read())
    print('两份是否逐字一致：%s' % ('是' if same else '否 ⇒ 桌面是旧版，见下方同步'))

    # R16/R17 在不在真源里，逐字核一遍（防"收录了个旧版"）
    d = open(DOC, encoding='utf-8').read()
    for k in ('R16', 'R17'):
        print('  真源含 %s：%s' % (k, '是' if re.search(r'^\| %s ' % k, d, re.M) else '否'))

    cnt = dict(ok=0, info=0, warn=0, error=0)
    hit = {}
    print('\n镜号  触发项（ok 不列）')
    for s in SH:
        pth = os.path.join(D, 'h3', '%s_video.txt' % s['id'])
        if not os.path.isfile(pth):
            print('%-5s 无已编译提示词，跳过（先跑 h3_shots.py）' % s['id'])
            continue
        prompt = open(pth, encoding='utf8').read()
        rows = []
        for rid, chks in check_shot(H, s, prompt):
            for c in chks:
                cnt[c['lvl']] += 1
                if c['lvl'] in ('warn', 'error'):
                    hit.setdefault(rid, []).append('%s:%s' % (s['id'], c['msg'][:56]))
                    rows.append('%s %s' % (rid, c['msg'][:78]))
        if rows:
            print('%-5s %s' % (s['id'], '\n      '.join(rows)))
    print('\n合计 ok=%d info=%d warn=%d error=%d' % (cnt['ok'], cnt['info'], cnt['warn'], cnt['error']))
    print('\n—— 触发次数排序（先修命中最多的那条轴）——')
    for r, v in sorted(hit.items(), key=lambda kv: -len(kv[1]))[:8]:
        print('  %-12s %2d 镜：%s' % (r, len(v), v[0][:70]))

    print('\n—— 作用域：哪条纪律管哪条线（闸不跨线时，别把本线纪律当全片真理）——')
    for nm, sc, why in SCOPE:
        print('  · %-30s 作用域=%-24s %s' % (nm, sc, why))

    print('\n—— 冲突登记（不代裁，等他拍）——')
    for t, b in CONFLICTS:
        print('  · %s\n    %s' % (t, b))
    print('\n—— 建议补进 DEGUN 的招式映射（让第十一节招式表在去枪闸下可用）——')
    print('  ' + '；'.join('%s→%s' % (a, b) for a, b in SPEAR_MOVE_MAP[:6]))
    print('  ' + '；'.join('%s→%s' % (a, b) for a, b in SPEAR_MOVE_MAP[6:]))
    explicit, gap = degun_coverage(H)
    print('\n—— 替换表词形覆盖自检（第⑧条的落地：字面闸查不出"坏中文"，所以要单独跑这一步）——')
    print('  DEGUN 显式词形 %d 个：%s' % (len(explicit), '、'.join(sorted(explicit))))
    if gap:
        print('  ⚠ 靠裸兜底「枪」→「长杆」过关的 %d 个（输出已不是中文词，补映射或让兜底报错）：' % len(gap))
        for w, o in gap:
            print('     %-8s → %s' % (w, o))
    else:
        print('  词形闭合，无裸兜底命中')
    vl_plan(SH)

    if not same and '--sync' in sys.argv:
        import shutil
        shutil.copyfile(DOC, DESK)
        print('\n已把真源整份回写桌面快照：%s' % DESK)
