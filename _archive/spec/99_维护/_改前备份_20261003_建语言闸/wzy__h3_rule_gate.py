# -*- coding: utf-8 -*-
"""《H3 提示词工程规则方案》收录后的机器层。

真源（唯一）：D:/AIWorkflow/ComfyUI_H3/H3提示词工程规则方案.md
  R1–R20 全集（R18 空间一致性／R19 特写镜质感／R20 一击干脆 2026-09-30 加）；2026-09-28 起 §3.3 的**格式契约已换成官方 I2VA 骨架**（中文十块剥离到云端 SD 通道）。
  桌面上的 `H3提示词工程规则方案.md` 是 --sync 回写的快照。

这个脚本做四件事，别的都不做：
  1) 把方案里**能静态检**的条款编成闸，对 h3_shots.SHOTS 的 23 镜逐条跑；
  2) **格式契约判定**（2026-09-28 加）：先认格式、再按格式判，骨架/六段/十块/图片四类互不套用；
     混用（十块块名进 H3 稿、骨架字段进云端稿…）单独报出来；
  3) 把**机器判不了**的条款登记成"生成后 VL 四问"（方案第十节）——供拼片前自检用；
  4) 登记方案与本管线**已经互相冲突的几处**，不替他裁决，只留痕。

★判区的唯一来源是 `prompt_format.py`（共用底座）。**本脚本内不再自己按【】切区**——
  骨架格式里没有【】，按块名切会静默切成空 ⇒ 所有词表判定假阴通过，比误报危险得多。

用法：
  python h3_rule_gate.py                       # A 线 23 镜（默认）
  python h3_rule_gate.py --dir <提示词目录>     # 审任意一批纯文本稿（C 线三阶等）
  python h3_rule_gate.py --files a.txt,b.txt   # 只审指定几份
  python h3_rule_gate.py --sync                # 把真源整份回写桌面快照

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
DESK = r'E:/创作/_待审文档/H3提示词工程规则方案.md'
# 现行 H3 视频层真源目录（2026-09-28 起；旧十块稿在 prompts\ 与 prompts_官方三段式\，别再当权威）
SKEL_DIR = r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架'

if D not in sys.path:
    sys.path.insert(0, D)
import prompt_format as PF            # 共用底座：认格式 + 切职责区

# ---------------------------------------------------------------- 方案里可静态检的词表
# 第五节运镜匹配表：**这不是第二份可写清单**，是宽进匹配表。
# 可写集权威在官方 §4.3（`prompts\official_h3\base-en.txt`）＝12 行；本表 14 项 =
# 12 行拆掉双向合并（Push In／Pull Out 各算一项）＋同义词 `Orbital`（= Arc）。
# 只用来判"英文受控词有没有出现"（未出现＝中文运镜，记 info，不拦），所以宽进无害。
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
# H3R1 的作用域豁免：**解布**是 C 线 P3 的剧情动作，不是状态锁失效。
# 没有这一组，P3A/P3B/P3D 会被 A 线"全程不拆布"的纪律假报成缺陷（闸犯第二种错：拿本线纪律否掉别线剧情）。
UNWRAP = ['扯下', '扯落', '抖落', '解下', '解开', '布落地', '布散', '露出枪', '露出杆',
          '裸杆', '金属裸露', '寒光', '亮出']


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


# ---------------------------------------------------------------- 格式契约判定（2026-09-28 加）
# 为什么要这一节：09-28 把 H3 视频层的提示词格式**整体换成官方 I2VA 骨架**，中文十块剥给云端 SD 通道，
# 目的是**避免两套格式混用**。而混用是静默的——十块稿塞进 H3 不会报错，只会演出台词乱码；
# 反过来骨架稿贴到云端也没人拦。所以判定层必须自己认格式，并且把"混"字报出来。

def check_format(prompt, channel='h3'):
    """返回 [(规则号, [chk,...])]，只有一条：'H3R0 格式契约'。"""
    kind = PF.detect(prompt)
    hits = []
    mix = PF.mixing(prompt, want=channel)
    for m in mix:
        hits.append(chk('混用', 'error', m))

    if channel == 'h3' and kind == 'h3_skeleton':
        # G7 同判据的**只报版**：让本闸提前告诉你"这份稿子提交会不会被 preflight 拦"
        if PF.SKELETON_INSTRUCTION not in prompt:
            hits.append(chk('首行', 'error', '缺官方首帧指令行（逐字，且后面要空一行）'))
        nfield = [f for f in PF.BASE_FIELDS if prompt.count(f) == 1]
        if len(nfield) != 3:
            got = {f: prompt.count(f) for f in PF.BASE_FIELDS}
            hits.append(chk('三字段', 'error', '基础三字段必须各恰出现一次：%s' % got))
        idx = [prompt.find(f) for f in PF.BASE_FIELDS]
        if len(set(idx)) == 3 and idx != sorted(idx):
            hits.append(chk('字段序', 'error', '三字段顺序不对（须 integrated → soundscape → music）'))
        body = PF._shot_body(prompt)
        if not body.lstrip().startswith('[Shot'):
            hits.append(chk('Shot', 'error', '正文没有以 [Shot 1] 开头'))
        pics = sorted({int(n) for n in re.findall(r'<Picture\s*(\d+)>', prompt)})
        if pics and pics != [1]:
            hits.append(chk('槽位', 'error', '骨架只挂 <Picture 1>，实挂/引用了 %s ⇒ 多锚要走六段' % pics))
        six = [f for f in PF.REF2VA_ONLY if f in prompt]
        if six:
            hits.append(chk('模式', 'error', '骨架里混进全参考六段字段：%s' % six))
        if not hits:
            hits.append(chk('骨架', 'ok',
                            '官方 I2VA 骨架五条齐（首行/三字段/顺序/[Shot 1]/只挂 Picture 1）'))
    elif channel == 'h3' and kind == 'h3_ref2va':
        hits.append(chk('骨架', 'info', '按全参考六段判（ref2va 线不吃骨架五条）'))
    elif channel == 'cloud' and kind == 'sd_tenblock':
        miss = [b for b in PF.CORE_BLOCKS if u'【%s】' % b not in prompt]
        hits.append(chk('五块', 'error' if miss else 'ok',
                        '缺核心分块 %s' % miss if miss else '云端 SD 十块核心五块齐'))
    elif kind == 'plain':
        hits.append(chk('格式', 'info', '无结构格式（图片/previz 稿口径：只查共性坑）'))
    else:
        hits.append(chk('格式', 'warn', '识别为 %s，与目标通道 %s 不同形' % (kind, channel)))
    return [('H3R0', hits)]


def synth_shot(prompt):
    """把一份**纯文本提示词**折算成 check_shot 需要的 shot 结构（给 C 线等外来稿用）。

    关键纪律：**取不到不等于没问题。**
      · 没有可解析的时间戳拍 ⇒ s['beat'] 留空，判定层必须降级成 info/判不了，不许当"步数 0＝通过"。
      · 时长取不到 ⇒ s['secs']＝None，R17 那一条报 info，不报 ok。
    """
    r = PF.regions(prompt)
    bs = PF.beats(prompt)
    beats_txt = u'→'.join(c for _, _, c in bs)
    secs = bs[-1][1] if bs and bs[-1][1] else None
    return dict(id='(文本)', beat=beats_txt, dlg=r['dialog'], snd=r['sound'],
                cam=r['camera'], secs=secs, style='', begin='', main='', end='',
                scene='', nbeats=len(bs), regions=r)


def check_shot(H, s, prompt):
    """返回 [(规则号, [chk,...])]；只收录有命中项的规则。"""
    out = []
    # 视觉描述区＝整篇剔掉台词、声音值与字段名（宁滥勿漏，绝不切空）。见 prompt_format.visual_zone。
    vis = PF.visual_zone(prompt)
    text_only = s.get('regions') is not None        # 由 synth_shot 折算出来的外来稿（无 beat 元数据）
    st = steps(s)
    n = len(st)
    violent = any(v in s['beat'] for v in VIOLENCE)

    # ---- H3R3 / H3R11 / H3R15：一镜一主动作、容量＝步数×剧烈度
    if not st and text_only:
        out.append(('H3R3/11/15', [chk('步数', 'info',
                   '判不了：这份稿子里解析不到可数的节拍（既无 `→` 链也无 时间戳拍）'
                   '⇒ 不判 ok。要么它真是一镜一拍，要么就是节拍写法不在闸的射程内')]))
    else:
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
    #      超载侧（塞不下）：2026-09-28 起**用实测安全点上浮定分界**，不再按公式字面判——
    #        依据：P1A 同 seed 实测 7.5 单元/5.17s 三句台词全准、改 175 帧反两句乱码。
    #        ⇒ 公式说"塞不下"不等于塞不下；只有密度明显越过已验安全点才值得 warn。
    #      空转侧（多给时间）2026-09-27 已实测否证 ⇒ 降为参考级，只报不判、不作返工依据。
    #      依据：wzy/motion_curve.py 跑已渲 8 镜的光流衰减比，"秒/单元"与"尾塌"相关性
    #            Pearson 0.63 / Spearman 0.36（n=8），方向还与"拖长"相反 ⇒ 空转不预测拖长。
    #      详见 h3/R17空转实测.md 与 h3/三阶打斗编排_v2.md §三（与 G6 底线句同一处理逻辑：
    #      分界线＝有没有实测数据；没数据的那一侧不许当闸）。
    units = n * 1.0 + len(s['dlg']) * 1.75
    # 超载侧的**分界用实测点定，不用公式定**：P1A 实测 7.5 单元 / 5.17s（1.45 单元每秒）三句台词全准，
    # 改到 175 帧反而两句乱码 ⇒ "超载就返工"这个字面读法已被否证一次。
    # 所以：≤ SAFE_CEIL（实测安全点上浮 10%）只记 info，超过才 warn。定值出处见 h3/三阶打斗编排_v2.md §三。
    SAFE_CEIL = 1.6
    dense = units / s['secs'] if s.get('secs') else None
    if not s.get('secs'):
        out.append(('H3R17', [chk('时长', 'info',
                   '判不了：稿面上取不到时长/帧数（骨架正文不写死秒数时就靠 cfg）'
                   '⇒ 不判 ok；单位数 %.2f（%d 拍 + %d 句台词×1.75）' % (units, n, len(s['dlg'])))]))
    elif units * 0.9 > s['secs'] and dense > SAFE_CEIL:
        out.append(('H3R17', [chk('超载', 'warn',
                   '信息单元 %.2f（%d 动作 + %d 句台词×1.75）需要 ≥%.1fs，实给 %.2fs，'
                   '密度 %.2f 单元/秒 ＞实测安全上限 %.2f ⇒ H3 会拖长前面的动作凑时长'
                   % (units, n, len(s['dlg']), units * 0.9, s['secs'], dense, SAFE_CEIL))]))
    elif units * 0.9 > s['secs']:
        out.append(('H3R17', [chk('超载', 'info',
                   '公式说塞不下（%.2f 单元 / %.2fs＝%.2f 单元每秒），但在实测安全区内（≤%.2f）：'
                   'P1A 同 seed 7.5 单元/5.17s 三句台词全准、拉到 175 帧反两句乱码 ⇒ 别据此返工'
                   % (units, s['secs'], dense, SAFE_CEIL))]))
    elif s['secs'] > units * 1.5:
        out.append(('H3R17', [chk('空转', 'info',
                   '单元 %.2f 给了 %.2fs（%.2f×上限，参考级：8 镜实测此比值不预测拖长，别据此返工）'
                   % (units, s['secs'], s['secs'] / (units * 1.2)))]))
    else:
        out.append(('H3R17', [chk('时长', 'ok', '单元 %.2f / %.2fs，落在 0.9–1.2s×单元' % (units, s['secs']))]))

    # ---- H3R9 + 第七节：声音必写、且除 N/A 外别处不出现"音乐"
    hits = []
    r9 = s.get('regions') or PF.regions(prompt)
    if not (s['snd'] or r9['sound']).strip():
        hits.append(chk('声音', 'error',
                        '声音区空 ⇒ H3 会自加杂音（骨架＝overall_soundscape 的值；十块＝【声音】）'))
    # 官方骨架里 `non_diegetic_music:` 的**值可以同行也可以次行**（A 线同行、C 线次行，两种都合法）。
    # 旧判据写死单行字面量 `non_diegetic_music: N/A` ⇒ 指到 12 份新真源上会 12/12 假 error。
    mv = (PF.field_value(prompt, 'non_diegetic_music:') or '').strip()
    if mv.upper().replace(u'．', '.') not in ('N/A', 'NA'):
        hits.append(chk('N/A', 'error',
                        'non_diegetic_music 的值不是 N/A（实为 %r）⇒ 可能自加背景音乐' % mv[:24]))
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
    #      锁句落点按通道不同：骨架＝正文里的不变量句（官方落点在 `Throughout:` 段），十块＝【保持一致】。
    #      判据必须吃**同义写法**：A 线编译进去的是"形态、数量…不拆开"，C 线手写的是
    #      "始终为一件／白麻布裹严／不露本体／不变形"——只认前者会 12/12 假报缺失（实测踩过）。
    LOCK_SHAPE = ['形态、数量', '形态数量', '始终为一件', '始终为一根', '数量不变', '形态不变']
    LOCK_STATE = ['不拆开', '不露本体', '不变形', '不生分支', '不替换',
                  '裹严', '裹着白麻布', '缠着白麻布']
    # 英文同义表（2026-10-01 补）：SOP §2 要求正文编译成英文（只有台词留中文），
    # 只认中文词 ⇒ 任何英文稿必然假报缺失（实测：已验收的 段2_t2va.txt、本练习件母版
    # 光炮v2_法阵_t2va.txt 都报 H3R1）。
    # ⚠️ 英文侧**只收正向锁句**：H3 无负面通道，"never splits / does not change shape"
    #    是在给模型点名那个概念（§9 与 R5 同判），不算锁，别为了过闸去写禁令。
    LOCK_SHAPE_EN = ['exactly one', 'exactly two', 'exactly three', 'exactly four',
                     'exactly five', 'exactly six', 'one single', 'a single flat',
                     'the same figure', 'same figure in every shot', 'identical in every shot',
                     'count unchanged', 'the same number of']
    LOCK_STATE_EN = ['stays a single', 'stays intact', 'stays flat', 'stays the same',
                     'holds its shape', 'keeps its shape', 'keeps the same shape',
                     'remains one', 'remains a single', 'unchanged through', 'in every shot']
    vlo = vis.lower()
    has_shape = any(w in vis for w in LOCK_SHAPE) or any(w in vlo for w in LOCK_SHAPE_EN)
    has_state = any(w in vis for w in LOCK_STATE) or any(w in vlo for w in LOCK_STATE_EN)
    where = {'h3_skeleton': '骨架不变量段（Throughout／正文末段）',
             'h3_ref2va': '六段 detailed_description 的不变量句',
             'sd_tenblock': '【保持一致】块'}.get(PF.detect(prompt), '正文')
    miss = []
    if not has_shape:
        miss.append('形态/数量词')
    if not has_state:
        miss.append('状态锁（不拆开/不露本体/裹严…）')
    if not miss:
        out.append(('H3R1', [chk('道具锁', 'ok', '%s 里形态/数量锁与状态锁都在场' % where)]))
    elif has_state:                      # 状态锁在、只是措辞与 A 线不同形 ⇒ 判据过窄，不是稿件缺陷
        out.append(('H3R1', [chk('道具锁', 'info',
                   '%s 未命中形态/数量词，但状态锁在场（%s）⇒ 本闸词表偏窄，按"写法不同形"记，不当缺陷'
                   % (where, u'、'.join(m for m in miss if '状态' not in m) or '形态/数量词'))]))
    elif any(w in vis for w in UNWRAP):
        # 作用域豁免：**"解布/裸杆"本身就是这一镜的剧情**（C 线 P3 的四拍就是扯下布亮出枪杆）。
        # 拿 A 线"全程不拆布"的状态锁去否掉 C 线剧情＝闸犯的第二种错（见 SCOPE 表头注释）。
        out.append(('H3R1', [chk('道具锁', 'info',
                   '%s 无"不拆开/裹严"状态锁，但本镜写的是解布动作（命中 %s）'
                   '⇒ 属作用域外：状态锁只管 A 线裹布阶段与 C 线 P1–P2，P3 亮枪按剧情就该拆开'
                   % (where, u'、'.join(w for w in UNWRAP if w in vis)[:3]))]))
    else:
        out.append(('H3R1', [chk('道具锁', 'warn',
                  '%s 缺 %s ⇒ 道具会长出分支/换形（H09 长枪变长剑、P2D 长出两根杆都是这一格）'
                  % (where, u'、'.join(miss)))]))
    return out


# ---------------------------------------------------------------- H3R18 空间一致性（2026-09-30 加）
# 出处：《算盘与崩山》段2 缠身版 v2 人审——"链子又往侧面跑了、男子站位总是背对女子"。
# 逐帧回查，四条病灶里**三条是稿子自己写的**：镜3 顶视角拍他的背、镜6 地面高度拍他的背，
# 镜2 明写"被这一圈的惯性带着转四分之一圈"（本来就该面对她，又把他转开 90°），
# 镜2 中景只框他一个人（敌我轴线在画面里根本看不见）。⇒ 这不是"演得对不对"的问题
# （那归出片后的 qc_face.py 量），是**稿子有没有把轴线交代清楚**的问题，可以静态判。
#
# 口径（六条，18c/18d 是 error，其余 warn；单人镜一律不判）：
#   18a 每镜要声明相机在敌我轴线的哪一侧。不声明 ⇒ 模型自己选边，实测常选成背面。
#   18b 双方同框且有交接动作（打/缠/拽/飞到）⇒ 同镜必须有"面对"词。
#   18c 出现"背/后背/后颈/从背后/背面机位"类词，且同镜没有"面对"词 ⇒ error（等于自己放弃轴线）。
#   18d 出现"转开"类旋转词，且同镜没有"面对/转回"词 ⇒ error。
#   18e 投射物（链/鞭/镖/武器）飞行 ⇒ "朝目标"与"沿两人连线"两组词都要在，缺则 warn。
#   18f 跨镜侧别漂移：某主体的 frame left/right 换了、而本镜没有位移动词 ⇒ warn。
PARTY_CAND = ['woman', 'man', 'girl', 'boy', 'warrior', 'monk', 'fighter', 'priest',
              'beast', 'opponent', 'adversary']
P_SIDE = r'(?:frame\s+)?(?:left|right)'
AXIS_SIDE = [r'\bin front of\b', r'\bfrom in front\b', r'\bfacing the camera\b',
             r'\b(?:toward|to)\s+the\s+camera\b', r"\b(?:woman|man|girl|boy)'s side\b",
             r'\bfrom behind (?:the )?(?:woman|man|girl|boy)\b',
             r'\bover[- ]the (?:shoulder|shoulders)\b', r"\bover (?:his|her) shoulder\b",
             r'\btop[- ]down\b', r'\bfrom above\b', r'\bfrom the (?:other|far|same) side\b',
             r'\b(?:eye[- ]level|low[- ]angle|high[- ]angle)\b', r'\b(?:side|two[- ]shot)\b',
             r'\bthree[- ]quarter\b', r'\bat ground level\b', r'\bcamera level\b']
# ⚠️ 词表纪律：**不收裸 "face"**。"face-first""face down" 是摔趴的方向，不是朝向对方；
#    收了它，18c/18d 会被"脸朝下砸地"这类句子挡掉＝闸自己把病灶洗白。必须带**关系对象**。
FACING = [r'\bfacing\b', r'\bface-to-face\b', r'\bface\s+(?:turned\s+)?toward\b',
          r'\blooking at (?:each other|him|her)\b',
          r'\btoward(?:s)? (?:her|him|the woman|the man)\b', r'\bpoint(?:ed|s)? at (?:her|him)\b',
          r'\baimed at\b', r'\bturned to face\b', r'\bchest[^.]{0,30}?(?:toward|to)\b',
          u'面对面', u'正对', u'朝向', u'面对']
BACK = [r'\b(?:his|her) back\b', r'\bback of (?:his|her) (?:neck|shoulder|chest|head)\b',
        r'\bback view\b', r'\bviewed from behind\b', r'\bseen from behind\b',
        r'\bfrom behind (?:him|her)\b', r'\bhis back and shoulders\b',
        u'他的背', u'她的背', u'后背', u'后颈', u'背面']
ROTATE_AWAY = [r'\bturn(?:ed|s)? (?:him|her)?self?\b', r'\bturned a quarter\b',
               r'\bquarter (?:of a )?turn\b', r'\bspun? (?:around|round)\b',
               r'\brotat\w+\b', r'\bpivot\w*\b', r'\bwhirl\w*\b',
               r'\bswing\w* (?:his|her) (?:body|hips|shoulders)\b',
               u'转了四分之一圈', u'转身', u'旋转', u'打转']
MOVE = [r'\bwalk\w*\b', r'\bcircle\w*\b', r'\bstep\w*\b', r'\bdrag\w*\b', r'\bskid\w*\b',
        r'\blunge\w*\b', r'\broll\w*\b', r'\bslide\w*\b', r'\bturn\w*\b', r'\bmove\w*\b',
        r'\bhalf circle\b', u'绕', u'走', u'挪', u'滑', u'翻']
PROJECTILE = [r'\bchain\b', r'\bwhip\b', r'\bdart\b', r'\brope\b', r'\bcoin\b', r'\bblade\b',
              r'\bspear\b', r'\bstaff\b', u'链', u'鞭', u'镖', u'绳', u'刀', u'枪', u'剑']
# ⚠️ 不收 `cross*`／`arc*`：前者撞上"环带压过第一圈"(crosses the first)、后者撞上运镜词 Arc，
#    会把"没有东西在飞"的镜判成投射物飞行＝闸自己造噪声。
FLY = [r'\bfly\w*\b', r'\bflew\b', r'\bunroll\w*\b', r'\bsweep\w*\b', r'\bcross the (?:open )?ground\b',
       r'\barriv\w*\b', r'\blash\w*\b', r'\bshoot\w*\b', r'\bhurl\w*\b', r'\bwhip\b',
       u'飞', u'甩', u'扫', u'抽', u'横穿']
TOWARD = [r'\btoward(?:s)? (?:the )?(?:man|woman|girl|boy|him|her)\b', r'\baimed at\b',
          r'\bat (?:the )?(?:man|woman|girl|boy|him|her)\b',
          r'\bonto (?:him|her)\b', r'\bin her direction\b', r'\bat his (?:chest|face|head)\b',
          u'朝', u'向他', u'向她', u'扑']
LINEAXIS = [r'\bstraight\b', r'\balong the line\b', r'\bbetween (?:the )?(?:two|them)\b',
            r'\btaut\b', r'\blow and straight\b', r'\bthe open ground between\b',
            u'直线', u'绷直', u'两人之间', u'空地']


def _shot_blocks(prompt):
    """按**行首**的 [Shot N] 切镜。
    ⚠️ 必须锚行首：官方 I2VA 首行里 `(from [Shot 1])` 也含 `[Shot 1]`，
       不锚就会多切出一段假"镜1"（实测多出一块、把 18f 的初始侧别记错）。
       取不到行首 [Shot N]（十块/散文稿）⇒ 整篇当一镜，编号 None。"""
    hits = list(re.finditer(r'(?m)^[ \t]*\[Shot\s*(\d+)\]', prompt))
    if not hits:
        return [(None, prompt)]
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(prompt)
        out.append((int(m.group(1)), prompt[m.start():end]))
    return out


def _parties(prompt):
    """认主体：候选词按词边界数出现次数，≥2 次算在场。认不出两个就整条 R18 降级为判不了。"""
    cnt = {}
    low = prompt.lower()
    for w in PARTY_CAND:
        c = len(re.findall(r'\b%s\b' % w, low))
        if c >= 2:
            cnt[w] = c
    return [w for w, _ in sorted(cnt.items(), key=lambda kv: -kv[1])][:2]


def _hit(pats, text):
    """中英混表：含 ASCII 的按正则（忽略大小写），纯中文的按字面 in。"""
    return any((re.search(p, text, re.I) if any(c.isascii() and c.isalpha() for c in p)
                else p in text) for p in pats)


def check_space(prompt):
    """H3R18 空间一致性（敌我轴线／朝向／相机在哪一侧）。返回 [(规则号, [chk,...])]。"""
    ps = _parties(prompt)
    if len(ps) < 2:
        return [('H3R18', [chk('轴线', 'info',
                  '判不了：稿子里认不出两个稳定主体（候选词命中 %s）'
                  '⇒ 单人镜本来就不需要轴线句，别把这条当缺陷' % (ps or '无'))])]
    rows, drift_prev = [], {}
    for num, blk in _shot_blocks(prompt):
        tag = '镜%s' % num if num else '全篇'
        both = all(re.search(r'\b%s\b' % p, blk, re.I) for p in ps)
        has_facing = _hit(FACING, blk)
        has_back = _hit(BACK, blk)
        # "down his back"（灰尘落在他背上）是**材质描述**，不是机位；只有和取景词同句的背向词才算背面机位。
        # 不分开的话，段1 那条已验收的稿子会被自己的词表判成 error（实测踩过）。
        VIEW = [r'top[- ]down', r'back view', r'\bfrom behind\b', r'over[- ]the[- ]shoulder',
                r'\bseen\b', r'\bviewed\b', r'\bview\b', r'close[- ]up', r'\bshot of\b',
                r'\bcamera\b', r'\bfills? the frame\b', r'\bin the frame\b']
        back_view = any(_hit(BACK, sen) and _hit(VIEW, sen) for sen in re.split(r'(?<=[.。])\s+', blk))
        back_mat = has_back and not back_view
        has_rot = _hit(ROTATE_AWAY, blk)
        has_axis = _hit(AXIS_SIDE, blk)
        has_transfer = _hit(FLY, blk) or _hit(
            [r'\bhit\w*\b', r'\bstrik\w*\b', r'\bwrap\w*\b', r'\bpull\w*\b',
             r'\bdrag\w*\b', r'\bpin\w*\b'], blk)
        if not has_axis:
            anchored = ('<Picture' in blk) or re.search(r'\bopening frame\b', blk, re.I)
            if anchored:
                rows.append(chk('18a 相机侧', 'info',
                          '%s 没写相机侧，但本镜由首帧锚钉几何（<Picture>／the opening frame）'
                          '⇒ 侧别在像素里，不算缺陷' % tag))
            else:
                rows.append(chk('18a 相机侧', 'warn',
                            '%s 没声明相机在敌我轴线的哪一侧（front／behind X／over shoulder／'
                            'top-down／side…）⇒ 模型自己选边，实测常选成背面' % tag))
        if both and has_transfer and not has_facing:
            rows.append(chk('18b 面对', 'warn',
                            '%s 双方同框且有交接动作，却没有"面对／朝向对方"的词'
                            '⇒ 轴线靠模型自己补' % tag))
        if back_view and not has_facing:
            rows.append(chk('18c 背面机位', 'error',
                            '%s 取景句里写了背向词（his back／后颈／from behind…）且同镜无"面对"词'
                            '⇒ 这一镜必然把对手拍成背对；改成正面或三四分之机位' % tag))
        elif back_mat:
            rows.append(chk('18c 背面机位', 'info',
                            '%s 的"背"落在材质/落点描述里（同句无取景词，如 dust down his back）'
                            '⇒ 不算机位，只登记' % tag))
        if has_rot and not has_facing:
            rows.append(chk('18d 转开', 'error',
                            '%s 有把人转开的旋转词（turned a quarter／spun around／转身…）'
                            '且同镜没有"转回面对"⇒ 每多一个这种词，他就离对手多转 90°' % tag))
        proj = _hit(PROJECTILE, blk)
        fly = _hit(FLY, blk)
        if proj and fly:
            tw = _hit(TOWARD, blk)
            ln = _hit(LINEAXIS, blk)
            if not (tw and ln):
                rows.append(chk('18e 链路', 'warn',
                          '%s 投射物在飞，缺%s⇒ 路径会画弧或斜出画外'
                          '（要"朝目标"＋"沿两人连线"两组词都在）'
                          % (tag, u'、'.join(x for x, ok in [(u'"朝目标"', tw), (u'"沿连线"', ln)]
                                             if not ok))))
        for p in ps:
            for side in ('left', 'right'):
                if re.search(r'\b%s\b[^.]{0,140}\bframe %s\b' % (p, side), blk, re.I) or \
                   re.search(r'\bframe %s\b[^.]{0,140}\b%s\b' % (side, p), blk, re.I):
                    if drift_prev.get(p) and drift_prev[p] != side and \
                       not any(re.search(m, blk, re.I) for m in MOVE):
                        rows.append(chk('18f 侧别漂移', 'warn',
                                  '%s：%s 从 frame %s 变成 frame %s，而本镜没有位移动词'
                                  '⇒ 没有移动交代的换边＝瞬移' % (tag, p, drift_prev[p], side)))
                    drift_prev[p] = side
                    break
    if not rows:
        rows = [chk('轴线', 'ok', '每镜都有相机侧声明，无背向机位、无"转开不转回"，投射物路径两组词齐全')]
    return [('H3R18', rows)]


# ---------------------------------------------------------------- H3R19 特写镜质感（2026-09-30 加）
# 出处：用户判段2 v3"前边真人实拍、后边变 CG"。逐镜量（脸占画面面积当景别代理，两条片各八镜 n=16）：
#   脸占 ≥1.5% 的镜 锐度均值 82／彩度均值 90；脸小的镜 锐度 169／彩度 82
#   （脸面积↔彩度 Pearson +0.56、↔锐度 −0.42）⇒ **画风漂移跟景别走、不跟时间走**。
#   段1 同病且更重：末镜脸占 25.6%、锐度 58.9 是十六镜最低。
# 判据口径与 R5 一致：**只有看得见的皮肤／镜头质感算数**，`realistic skin`／`hyperrealistic` 这类评价词不算。
CLOSEUP = [r'close[- ]up', r'extreme close', r'\btight on\b', r'\bmacro\b',
           r'\bclose\b[^.]{0,28}\b(?:view|shot|on|of)\b',
           r'fills? the (?:lower |upper |top |bottom )?(?:two )?(?:thirds|half)',
           r'\bin front of (?:his|her) (?:face|chest)\b', u'特写', u'大特写']
SKIN_SUBJECT = [r'\bface\b', r'\bcheek', r'\bjaw', r'\btemple', r'\bforehead', r'\bnose',
                r'\bmouth', r'\bteeth', r'\beye', r'\bskin\b', r'\bhands?\b', r'\bfingers?\b',
                r'\bknuckle', r'\bshoulders?\b', r'\bchest\b', r'\barms?\b',
                u'脸', u'皮肤', u'手', u'胸', u'肩']
SKIN_TEXTURE = [r'\bpores?\b', r'\bstubble\b', r'\bbeard\b', r'\bfine (?:hair|hairs)\b',
                r'\bsweat\b', r'\bdamp\b', r'\bwarmth showing\b', r'\bgrit stuck\b',
                r'\bdust stuck\b', r'\bchapped\b', r'\bscar tissue\b', r'\bblood vessel',
                r'\bindividual (?:hairs|hairs on)\b', r'\bskin texture\b', r'\bfilm grain\b',
                r'\bgrain\b', r'shallow depth of field', r'\bsoft circles\b', r'\bbokeh\b',
                r'\bsubsurface\b', r'\bfreckles\b', r'\bperspiration\b',
                u'毛孔', u'胡茬', u'汗珠', u'胶片颗粒', u'浅景深', u'焦外', u'皮下的红']
EVAL_ONLY = [r'\bhyper[- ]?realistic\b', r'\bphotorealistic\b', r'\brealistic skin\b',
             r'\bdetailed skin\b', r'\bultra[- ]?detailed\b', r'\b8k\b', r'\b4k\b']


def check_style(prompt):
    """H3R19：特写镜必须补可观察的皮肤／镜头质感，否则 H3 给磨皮高饱和＝CG 感。"""
    rows = []
    for num, blk in _shot_blocks(prompt):
        tag = '镜%s' % num if num else '全篇'
        if not _hit(CLOSEUP, blk) or not _hit(SKIN_SUBJECT, blk):
            continue
        got = [p for p in SKIN_TEXTURE if _hit([p], blk)]
        if len(got) >= 2:
            rows.append(chk('特写质感', 'ok',
                        '%s 有 %d 处可观察皮肤／镜头质感词' % (tag, len(got))))
            continue
        evalhit = [p for p in EVAL_ONLY if _hit([p], blk)]
        miss = '、'.join(x for x in ['pores/stubble', 'sweat/damp', 'grain', 'shallow depth of field']
                     if not any(x.split('/')[0] in g for g in got))
        rows.append(chk('特写质感', 'warn',
                    '%s 是特写镜（脸／手进框）但只有 %d 处皮肤质感词，缺 %s%s'
                    % (tag, len(got), miss,
                      '；且本镜出现了评价词 %s——按 R5 口径不计效' % ('、'.join(evalhit)) if evalhit else '')))
    if not rows:
        rows = [chk('特写质感', 'info', '本稿没有"脸／手进特写"的镜（或闸认不出），不判')]
    return [('H3R19', rows)]


# ---------------------------------------------------------------- H3R20 一击干脆（2026-09-30 加）
# 出处：用户判段2 v5——"链子缠身之后有拉扯的动作，这样反而会不好看。这种动作要干脆利落：
#   缠身马上收紧、男子随即痛苦倒地；或者缠上脖子提到半空、快窒息的时候松开、痛苦倒地。"
# 逐镜回查，两处病灶都是稿子自己写的双向受力：镜5「he drives forward … the pull **drags her toward**
# him … she plants both feet and **leans her weight back** until the coils stop her」、
# 镜7「She **hauls back** with her whole body」。⇒ 攻守变成拔河，观众看不到谁赢。
# 口径（两条）：
#   20a 一方把**另一方这个人**拖着走／后坐较力／明写僵持 ⇒ error。
#   20b 全篇一个"同拍完成"的时间词都没有 ⇒ warn（这一击会被演成慢慢来）。
# ⚠️ 词表纪律：**不收裸 pull／drag**。「the strand pulls taut」「drags a furrow through the dust」
#    是链子受力、链子拖灰，不是把人拖着走；收了会把已验收稿判成 error（与 R18c 同一次踩坑）。
TUG = [r'\bdrag(?:s|ged|ging)?\s+(?:her|him|them|the\s+(?:woman|man))\b',
       r'\bdragged\b', r'\bhaul(?:s|ed|ing)?\s+(?:back|on\s+(?:her|him|them))\b',
       r'\bheave(?:s|d|n)?\s+back\b', r'\bpull(?:s|ed|ing)?\s+(?:her|him|them|back)\b',
       r'\bpull\b[^.]{0,24}\bdrags?\b', r'\btug(?:s|ged|ging)?\b', r'\bwrestl\w*\b',
       r'\blean(?:s|ed|ing)?\s+(?:his|her)\s+weight\s+back\b', r'\bback\s+and\s+forth\b',
       r'\bneither\s+gives\b', r'\bstruggle[sd]?\b', r'\bstandoff\b',
       u'拉扯', u'拽住', u'拖着', u'僵持', u'拉锯', u'拔河', u'往回拉', u'角力']
INSTANT = [r'\bat once\b', r'\bin the same (?:motion|beat|instant)\b', r'\binstantly\b',
           r'\bin one (?:motion|beat|movement|unbroken motion)\b', r'\bon the same beat\b',
           r'\bsnap(?:s|ped)?\b', r'\bbefore\s+(?:he|she|him|her)\s+can\b', r'\bsuddenly\b',
           r'\bat\s+this\s+instant\b', r'\bstraight\s+off\b',
           u'立刻', u'随即', u'应声', u'瞬间', u'同一拍', u'一气呵成']


def _hits(pats, text):
    """取**命中的原文**（不是命中哪个模式）——报错时要让用户看见是哪几个字触发的。"""
    out = set()
    for p in pats:
        if any(c.isascii() and c.isalpha() for c in p):
            out |= {m.group(0).strip().lower() for m in re.finditer(p, text, re.I)}
        elif p in text:
            out.add(p)
    return sorted(out)


def check_decisive(prompt):
    """H3R20 一击干脆：禁双向拉扯／僵持，收招要有"同拍完成"的时间词。"""
    cut = prompt.find('overall_soundscape')
    body, snd = (prompt[:cut], prompt[cut:]) if cut >= 0 else (prompt, '')
    rows = []
    for num, blk in _shot_blocks(body):
        tag = '镜%s' % num if num else '全篇'
        hits = _hits(TUG, blk)
        if hits:
            rows.append(chk('20a 双向拉扯', 'error',
                        '%s 写了"把对方这个人拖着走／后坐较力"（命中 %s）'
                        '⇒ 攻守变拔河，观众看不到谁赢。改成一拍完成：收紧→当场出结果'
                        % (tag, u'、'.join(hits[:6]))))
    shits = _hits(TUG, snd)
    if shits:
        rows.append(chk('20a 双向拉扯', 'error',
                    '声音段写了较力的声音（命中 %s）⇒ 配音会把"僵住"再演一遍，删掉'
                    % u'、'.join(shits[:6])))
    inst = _hits(INSTANT, body)
    if not inst:
        rows.append(chk('20b 同拍完成', 'warn',
                    '全篇没有"at once／in the same motion／立刻／随即"这类同拍完成词'
                    '⇒ 收招容易被演成缓慢较力（R20 的另一半：不写拉扯，还要写明"马上"）'))
    if not rows:
        rows = [chk('一击干脆', 'ok',
                    '无双向拉扯词；同拍完成词 %d 处（%s）'
                    % (len(inst), u'、'.join(inst[:5]))) ]
    return [('H3R20', rows)]


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
     'B/C 各走自己脚本 ⇒ 用 other_lines_check.py 与本闸的 --dir/--files 文本稿模式补审计，只报不拦'),
    ('H3R19 特写镜质感（皮肤／镜头词 ≥2 处）', '仅**脸或手进特写**的镜；全景／无人脸镜不判',
     '判据与 R5 同口径：只数看得见的质感词，hyperrealistic／4K 这类评价词不算数。'
     '出片侧配套尺子＝`技能包转H3_SOP/工具/qc_style.py`（逐镜锐度＋彩度＋脸面积）'),
    ('H3R18 空间一致性（轴线／朝向／相机侧）', '仅**两方以上同场**的动作稿；单人镜不判',
     '认不出两个稳定主体时整条降级为 info，不当缺陷；18a 在挂首帧锚的镜降 info（侧别在像素里）；'
     '18c 只在**取景句**里查背向词，材质句（dust down his back）只登记——段1 已验收稿实测会被裸词表假报 error'),
    ('H3R20 一击干脆（禁双向拉扯／要同拍完成词）', '仅**两方对抗且有收招**的稿；单人演武、追逐镜不判',
     '词表只收"**把对方这个人**拖着走"（drags her／hauls back／leans her weight back／僵持），'
     '不收裸 pull／drag——「the strand pulls taut」「drags a furrow through the dust」是链子受力不是较力，'
     '收了会把已验收稿假报 error（与 R18c 的"材质句"同一次踩坑）。声音段单独查：较力的配音会把僵住再演一遍。'),
    ('格式契约（H3R0：骨架五条 / 十块五块 / 六段）', '按通道分治，互不套用',
     '2026-09-28 起：本地 H3 视频层＝官方 I2VA 骨架；中文十块只属云端 SD 通道。'
     '**混用是静默的**——十块喂 H3 会把元叙述念成台词，所以这一条必须机器判'),
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
    ('§九／§十一 的字面 vs 本管线永久"枪"硬闸 ——已落：2026-09-27 补 21 条词形 + 坏中文报错',
     '方案示例逐字用「长枪／枪杆／枪头／枪花一抖／端枪／白麻布裹严」；'
     '而 h3_shots.py 的硬闸是"视频提示词视觉描述区一个『枪』字都不许出现"（H07 把缠布长杆渲成子弹换来的）。'
     '曾经的病：DEGUN 只覆盖 10 条词形，枪花/枪尖/枪法/枪缨/枪柄/回马枪/一杆枪/舞花 走裸兜底 ⇒ '
     '产出「长杆花」「回马长杆」这种坏中文，而字面闸查不出来（"枪"确实没了）——**静默改坏中文比不改更糟，它骗过了自己的闸**。'
     '⇒ 现已两条都上：补到 21 条显式词形 ＋ `BAD_AFTER` 正则命中即 SystemExit。'
     '**残留风险**：方案第十一节招式表**仍不能逐字照抄**，必须过 DEGUN；'
     '而 C 线（三阶 previz）走的是另一条脚本、**不经本闸**，那 12 份正文里"长枪"是明写的（按 SCOPE 不算违规）。'),
    ('官方 I2VA 骨架 vs 项目法条 R1/R3/R5（2026-09-28 新登记，未裁）',
     '骨架示例正文里成串使用否定式与"不得/不要"（不得卡通化、画面不得出现任何文字、霓虹招牌上不得有文字），'
     '而方案 R5 v2.1 已判"排除句不计效"、prompt_lint 又把否定式当"点名"计入拦截。'
     '⇒ 风格/水印类否定句与招式类否定句**要不要一视同仁**，等裁。'
     '本闸现在的口径：招式/物体类否定句必须有正向替身；风格与水印类只登记不计效。'),
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


def _arg(name):
    """取 `--dir X` / `--dir=X` 形态的参数值；没有就返回 None。"""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(name + '='):
            return a.split('=', 1)[1]
    return None


def _tally(cnt, hit, vl=True):
    print('\n合计 ok=%d info=%d warn=%d error=%d' % (
        cnt['ok'], cnt['info'], cnt['warn'], cnt['error']))
    if hit:
        print('\n—— 触发次数排序（先修命中最多的那条轴）——')
        for r, v in sorted(hit.items(), key=lambda kv: -len(kv[1]))[:8]:
            print('  %-12s %2d 次：%s' % (r, len(v), v[0][:70]))
    else:
        print('\n无 warn/error 命中')


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
    for k in ('R16', 'R17', 'R18', 'R19', 'R20'):
        print('  真源含 %s：%s' % (k, '是' if re.search(r'^\| %s ' % k, d, re.M) else '否'))

    cnt = dict(ok=0, info=0, warn=0, error=0)
    hit = {}
    mode_dir = _arg('--dir')
    mode_files = [p for p in (_arg('--files') or '').split(',') if p.strip()]
    if mode_dir or mode_files:
        paths = mode_files or sorted(
            os.path.join(mode_dir, f) for f in os.listdir(mode_dir)
            if f.lower().endswith(('.txt', '.md')))
        print('\n【文本稿模式】审 %d 份（不经 h3_shots，按格式契约 + 可静态检条款跑）' % len(paths))
        for pth in paths:
            prompt = open(pth, encoding='utf8').read()
            s = synth_shot(prompt)
            rows = []
            for rid, chks in (check_format(prompt) + check_shot(H, s, prompt) + check_space(prompt) + check_style(prompt) + check_decisive(prompt)):
                for c in chks:
                    cnt[c['lvl']] += 1
                    if c['lvl'] in ('warn', 'error'):
                        hit.setdefault(rid, []).append('%s:%s' % (
                            os.path.basename(pth)[:12], c['msg'][:56]))
                        rows.append('%s %s' % (rid, c['msg'][:96]))
            print('%-30s %s' % (os.path.basename(pth)[:30],
                                '\n      '.join(rows) if rows else 'ok'))
        _tally(cnt, hit, vl=False)
        vl_plan(SH)
        if not same and '--sync' in sys.argv:
            import shutil
            shutil.copyfile(DOC, DESK)
            print('\n已把真源整份回写桌面快照：%s' % DESK)
        raise SystemExit(0)

    print('\n镜号  触发项（ok 不列）')
    for s in SH:
        pth = os.path.join(D, 'h3', '%s_video.txt' % s['id'])
        if not os.path.isfile(pth):
            print('%-5s 无已编译提示词，跳过（先跑 h3_shots.py）' % s['id'])
            continue
        prompt = open(pth, encoding='utf8').read()
        rows = []
        for rid, chks in check_format(prompt) + check_shot(H, s, prompt) + check_space(prompt) + check_style(prompt) + check_decisive(prompt):
            for c in chks:
                cnt[c['lvl']] += 1
                if c['lvl'] in ('warn', 'error'):
                    hit.setdefault(rid, []).append('%s:%s' % (s['id'], c['msg'][:56]))
                    rows.append('%s %s' % (rid, c['msg'][:78]))
        if rows:
            print('%-5s %s' % (s['id'], '\n      '.join(rows)))
    _tally(cnt, hit)

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
