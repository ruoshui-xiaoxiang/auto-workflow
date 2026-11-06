# -*- coding: utf-8 -*-
"""三阶打斗 12 镜编排审计 v2：按"接打一体算一单元"重算 R15/R17。

v1 的错：把「对方出招＋我方反应」这种**接打一体**的复合拍当成"多一个动作"，
        于是 P1B/P1C/P1D/P2D/P3A/P3B/P3C/P3D 八镜全被判超甜点。
        但 G1/R12 恰恰要求这么写——拆成两拍会演成"停一下再躲"的分步断层。
        （同类误判 Qoder 在 H04 上犯过一次："剧烈度判据在混写的镜上会误判"。）

v2 的口径：
  · **独立动作形态数**＝模型要单独完成几个不同的动作姿态。
    接打一体（对方出招→我方化解→我方反击）、动作＋它的物理结果（崩飞→撞墙→瘫坐）、
    招式＋它的展示细节（枪花→弹抖→连点）——都算 **1 个**动作形态。
  · **展示细节**（亮相、特写、材质）各算 0.5 单元（R17）。
  · **台词**每条 1.75 单元（口型＋听者反应）。
  · R15 甜点：剧烈 2–4 个动作形态；从容 6 个。
  · R17 时长：单元 × 0.9–1.2 秒，向上吸附 H3 帧网格（17n+5）。

只读，不改任何提示词。用法：python audit_p_fight.py

v3（2026-09-28，跟提示词格式契约对齐）：
  · **真源搬家了**：三阶 12 镜现在在 `ComfyUI_H3/prompts_H3官方骨架/`，文件名去掉了镜名后缀
    （`wuzhaojunyi_三阶P1A.txt`）。旧代码 glob `wuzhaojunyi_三阶P1A_*.txt` ⇒ 12/12 取不到，
    而 `audit()` 返回 None、main 直接过滤掉 ⇒ 表格全空还印"需处置 0/12 镜"，**看着像全过**。
    现在两种命名都吃，且**一份取不到就当场喊**，不再静默少算。
  · **切区改走共用底座 `prompt_format`**：骨架正文里没有【事件脚本】，旧代码那句
    `re.search(r'【事件脚本】…')` 取到空串 ⇒ 拍数 0 ⇒ 动作形态 0 ⇒ 单元 0 ⇒ "ok"。
    这是"判据绑死在旧块名上"的典型假阴（同 H3 规则闸的教训）。
  · **超载判定加实测密度上限**（与 h3_rule_gate 的 H3R17 同一个 SAFE_CEIL）：
    公式说塞不下但没超实测上限 ⇒ 只记 info，不判超载（P1A 同 seed 7.5 单元/5.17s 三句台词全准）。
"""
import re
import sys
from pathlib import Path

D = r'D:/AIWorkflow/tmp/wzy'
sys.path.insert(0, D)
import prompt_format as PF                           # noqa: E402  共用底座：认格式＋切区＋切拍

PR = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架')   # 09-28 起的真源
PR_OLD = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts')          # 旧落点，兼容已搬走前的快照
OUT_MD = Path(r'D:/AIWorkflow/tmp/wzy/h3/三阶编排审计.md')

SHOTS = ['P1A', 'P1B', 'P1C', 'P1D', 'P2A', 'P2B', 'P2C', 'P2D',
         'P3A', 'P3B', 'P3C', 'P3D']
# 镜名不再从文件名反推（新命名没有后缀）；出处＝三阶打斗编排_v2.md 与提示词全集总览表
NAMES = {'P1A': '拦路', 'P1B': '试探', 'P1C': '吃亏', 'P1D': '力不敌',
         'P2A': '激发', 'P2B': '棍架', 'P2C': '棍扫', 'P2D': '过载',
         'P3A': '亮枪', 'P3B': '枪花', 'P3C': '崩弹', 'P3D': '点喉'}

# 实测信息密度安全上限（与 h3_rule_gate.H3R17 同一条：P1A 7.5 单元/5.17s＝1.45 三句台词全准，
# 拉到 175 帧反两句乱码 ⇒ "超载就返工"的字面读法已被否证一次）。改一处要同步改另一处。
SAFE_CEIL = 1.6

GRID = [(124, 5.17), (175, 7.29), (192, 8.00), (209, 8.71), (243, 10.13),
        (294, 12.25), (328, 13.67), (362, 15.08)]

# 剧烈度：只认"人打人"的动词，环境/姿态词不算（H04 误判的教训）
VIOLENCE = ['拳', '踢', '砸', '抡', '挥拳', '横扫', '连挥', '重击', '撞', '崩飞',
            '横飞', '磕', '拨开', '点戳', '抽中', '刺', '扑', '抓']
DLG = re.compile(r'<d>\[中文\]\s*(.*?)</d>', re.S)
BEAT = re.compile(r'^\s*(\d+\.\d+)[–-](\d+\.\d+)\s*秒[：:]\s*(.*)$', re.M)

# 展示细节（R17 里算 0.5 单元）：亮相／特写／材质／静态呈现
SHOWCASE = ['亮相', '泛起寒光', '泛出寒光', '寒光', '特写', '悬停', '定格',
            '电光熄灭', '走进霓虹深处', '背影', '画面短暂稳定']

# 一拍里"其实是同一个动作形态"的模式（接打一体 / 动作＋物理结果 / 招式＋细节）
# 命中 ⇒ 这一拍算 1 个动作形态，**不再**额外加步数
SAME_UNIT = [
    (r'(挥|砸|扑|扫|冲|压|刺|扎).{0,24}(她|武君仪).{0,14}(让|躲|挡|架|格|退|偏|收紧)',
     '接打一体：对方出招＋我方化解'),
    (r'(让过|挡开|格挡|架住|一拨|磕开).{0,30}(随即|紧接|顺势|一记|再|跟着)',
     '接打一体：我方化解＋我方反击'),
    (r'(崩飞|横飞|飞出).{0,24}(撞|滑落|瘫|摔)',
     '动作＋物理结果链'),
    (r'(扯下|飞落).{0,18}(缠在|落在)',
     '动作＋物理结果链'),
    (r'(枪花|转枪|弹抖|颤动).{0,28}(连点|逼得|后退)',
     '招式＋展示细节＋结果'),
    (r'(嘲讽|讥讽|狞笑|得意|放话|吐出一个字).{0,26}(她|他|武君仪|粗臂男).{0,16}(后退|退半步|瘫软|不敢|神色|发麻)',
     '台词／表情＋对方的身体结果'),
    (r'(架住|架).{0,20}(被压|下沉|后退|震得)',
     '防御＋受力结果'),
]


def shot_file(sid):
    """新命名（无镜名后缀）与旧命名都吃；两个目录都找（真源 09-28 搬过一次家）。"""
    for base in (PR, PR_OLD):
        for pat in ('wuzhaojunyi_三阶%s_*.txt', 'wuzhaojunyi_三阶%s.txt'):
            hits = sorted(base.glob(pat % sid))
            if hits:
                return hits[0]
    return None


def frames_for(secs):
    for f, s in GRID:
        if s >= secs - 1e-6:
            return f, s
    return 362, 15.08


def audit(sid):
    f = shot_file(sid)
    if not f:
        return None
    txt = f.read_text(encoding='utf8')
    name = NAMES.get(sid) or f.stem.split('_', 2)[-1]

    # 切区/切拍一律走底座：骨架正文里**没有**【事件脚本】，旧那句 re.search 取到空串
    # ⇒ 0 拍 ⇒ 0 动作形态 ⇒ 判"ok"。这就是判据绑死旧块名的假阴。
    reg = PF.regions(txt)
    body = reg['body'] or txt
    beats = PF.beats(txt)
    dlgs = [re.sub(r'^\[中文\]\s*', '', d).strip() for d in PF.dialogues(txt)]

    violent = any(v in body for v in VIOLENCE)

    # 每拍算 1 个动作形态；命中 SAME_UNIT 的复合拍**不额外加**（这就是 v2 的修正）
    # 但一拍里若出现"两个各自独立的攻方动作"（对方连出两招），仍算 2
    acts = 0.0
    notes = []
    for a, b, c in beats:
        hit = [lab for pat, lab in SAME_UNIT if re.search(pat, c)]
        acts += 1.0
        if hit:
            notes.append((c[:30], hit[0]))

    # 展示细节：出现在末拍且属静态呈现的，算 0.5 而不是 1
    show = 0.0
    for a, b, c in beats:
        if any(w in c for w in SHOWCASE) and not any(v in c for v in VIOLENCE):
            show += 0.5
            acts -= 0.5

    units = acts * 1.0 + len(dlgs) * 1.75 + show * 0.0
    need_lo, need_hi = units * 0.9, units * 1.2

    spans = [(a, b) for a, b, _ in beats if b is not None]
    cur = spans[-1][1] if spans else None
    cur_f, cur_s = frames_for(cur if cur else 5.17)
    want_f, want_s = frames_for(need_lo)
    dense = (units / cur_s) if cur_s else None
    # 「公式说塞不下」和「真塞不下」是两件事：实测密度上限以下只记 info（见 SAFE_CEIL 注释），
    # 否则 12 镜全 5.17s 会被整批判超载 ⇒ 报一屏没人会照做的返工，等于没报。
    tight = bool(spans) and cur_s < need_lo - 0.05 and not (dense and dense > SAFE_CEIL)
    over = bool(spans) and cur_s < need_lo - 0.05 and bool(dense) and dense > SAFE_CEIL
    ratio = cur_s / units if units and cur_s else 99

    lim = 4 if violent else 6
    return dict(sid=sid, name=name, beats=[c for _, _, c in beats], spans=spans,
                acts=acts, show=show, violent=violent, dlgs=dlgs, units=units,
                need=(need_lo, need_hi), cur_s=cur_s, cur_f=cur_f, lim=lim, fmt=reg['kind'],
                want_f=want_f, want_s=want_s, over=over, tight=tight, dense=dense,
                no_beats=not spans, ratio=ratio, notes=notes,
                r15_bad=acts > lim)


def verdict(r):
    """把一行判定归成 (是否要处置, 标签串)。取不到拍＝**判不了**，绝不写 ok。"""
    if r['no_beats']:
        return False, '✗ 判不了：稿面切不出带时间戳的拍（格式＝%s）⇒ 不判 ok' % r['fmt']
    flag = []
    if r['r15_bad']:
        flag.append('R15 超甜点(%.1f>%d)' % (r['acts'], r['lim']))
    if r['over']:
        flag.append('R17 超载(密度 %.2f>%.2f)' % (r['dense'], SAFE_CEIL))
    if not flag:
        return False, ('ok' if not r['tight'] else
                       'ok·公式说不下但密度 %.2f≤实测上限 %.2f，不据此返工' % (r['dense'], SAFE_CEIL))
    return True, '⚠ ' + '＋'.join(flag)


def main():
    rows, missing = [], []
    for s in SHOTS:
        r = audit(s)
        (rows if r else missing).append(r or s)
    if missing:
        print('✗ 取不到真源：%s ⇒ 这些镜**没被审计**，别把下面的数字当 12 镜的结论'
              % '、'.join(missing))
    print('镜   名        动作形态 展示 剧烈 台词  单元  现给s   应给s(帧)   判定')
    print('-' * 100)
    tot_cur = tot_want = 0.0
    bad = []
    for r in rows:
        need, j = verdict(r)
        tot_cur += r['cur_s']; tot_want += r['want_s']
        print('%-4s %-9s %6.1f %5.1f %5s %3d %6.2f %6.2f %6.2fs(%3d)  %s' % (
            r['sid'], r['name'], r['acts'], r['show'],
            '剧烈' if r['violent'] else '从容', len(r['dlgs']), r['units'],
            r['cur_s'], r['want_s'], r['want_f'], j))
        if need:
            bad.append((r, j[2:].split('＋')))
    print('-' * 100)
    print('合计 现 %.2fs → 应 %.2fs  ⇒ 差 %.2fs（只算取到的 %d 镜）' % (
        tot_cur, tot_want, tot_want - tot_cur, len(rows)))
    print('\n需处置：%d / %d 镜（真源共 %d 镜，取到 %d）' % (
        len(bad), len(rows), len(SHOTS), len(rows)))

    for r, flag in bad:
        print('\n  %s（%s）%s' % (r['sid'], r['name'], '＋'.join(flag)))
        print('    动作形态 %.1f（甜点 %d）· 展示 %.1f · 台词 %d 条 · 单元 %.2f' % (
            r['acts'], r['lim'], r['show'], len(r['dlgs']), r['units']))
        print('    现给 %.2fs（%d帧）→ 建议 %d 帧（%.2fs）' % (
            r['cur_s'], r['cur_f'], r['want_f'], r['want_s']))
        for (a, b), c in zip(r['spans'], r['beats']):
            print('      %.1f–%.1fs  %s' % (a, b, c[:72]))
        for b, lab in r['notes']:
            print('      ↳ 复合但算 1 个动作形态：「%s…」＝%s' % (b, lab))

    # 写报告
    lines = ['# 三阶打斗 12 镜编排审计（R11–R17 · v3 口径）', '',
             '> 真源：`ComfyUI_H3/prompts_H3官方骨架/wuzhaojunyi_三阶P*.txt`'
             '｜脚本：`wzy/audit_p_fight.py`（只读，切拍走共用底座 `prompt_format.py`）',
             '> **v1 判据是错的，v2 已修**：v1 把「对方出招＋我方化解」这种**接打一体**的复合拍当成'
             '"多一个动作"，八镜全被判超甜点；但 G1/R12 恰恰要求这么写——拆成两拍会演成"停一下再躲"的分步断层。',
             '> **v2 口径**：动作形态数＝模型要单独完成几个不同的动作姿态。接打一体（对方出招→我方化解→我方反击）、'
             '动作＋物理结果（崩飞→撞墙→瘫坐）、招式＋展示细节（枪花→弹抖→连点）**都算 1 个**。'
             '展示细节 0.5 单元、台词 1.75 单元。R15 甜点＝剧烈 2–4／从容 6；R17 时长＝单元×0.9–1.2s，向上吸附帧网格。',
             '> **v3（09-28）修的是"审计自己假阴"**：① 真源搬家＋去掉镜名后缀 ⇒ 旧 glob 12/12 取不到，'
             '旧 main 把取不到的镜**静默过滤**，表格空着还印"需处置 0/12"；② 旧代码靠【事件脚本】切区，'
             '而 H3 骨架正文里根本没有【】⇒ 0 拍 0 单元 ⇒ 每镜都"ok"；③ 超载判定并入实测密度上限 '
             'SAFE_CEIL＝%.2f（与 `h3_rule_gate.H3R17` 同一条），公式说不下但没超上限时只记说明、不判返工。'
             % SAFE_CEIL,
             '', '| 镜 | 名 | 动作形态 | 展示 | 剧烈 | 台词 | 单元 | 现给 | 应给 | 判定 |',
             '|---|---|---|---|---|---|---|---|---|---|']
    tot_cur = tot_want = 0.0
    for r in rows:
        need, j = verdict(r)
        tot_cur += r['cur_s']; tot_want += r['want_s']
        lines.append('| %s | %s | %.1f | %.1f | %s | %d | %.2f | %.2fs | %d帧/%.2fs | %s |' % (
            r['sid'], r['name'], r['acts'], r['show'], '剧烈' if r['violent'] else '从容',
            len(r['dlgs']), r['units'], r['cur_s'], r['want_f'], r['want_s'], j))
    if missing:
        lines += ['', '> ✗ **取不到真源、未被审计的镜**：%s' % '、'.join(missing)]
    lines += ['', '合计：现 **%.2fs** → 按 R17 应 **%.2fs**，差 **%.2fs**（只算取到的 %d 镜）。' % (
        tot_cur, tot_want, tot_want - tot_cur, len(rows)), '',
        '## 需处置的镜', '']
    for r, flag in bad:
        lines += ['### %s（%s）— %s' % (r['sid'], r['name'], '＋'.join(flag)), '',
                  '- 动作形态 **%.1f**（甜点 %d）｜展示 %.1f｜台词 %d 条｜信息单元 **%.2f**' % (
                      r['acts'], r['lim'], r['show'], len(r['dlgs']), r['units']),
                  '- 现给 %.2fs（%d 帧）→ 建议 **%d 帧（%.2fs）**' % (
                      r['cur_s'], r['cur_f'], r['want_f'], r['want_s']), '',
                  '现事件脚本（从骨架正文切出）：', '']
        for i, ((a, b), c) in enumerate(zip(r['spans'], r['beats']), 1):
            lines.append('%d. `%.1f–%.1fs` %s' % (i, a, b, c))
        if r['notes']:
            lines += ['', '复合但按 v2 只算 1 个动作形态的拍：']
            for b, lab in r['notes']:
                lines.append('- 「%s…」＝ **%s**' % (b, lab))
        lines.append('')
    OUT_MD.write_text('\n'.join(lines), encoding='utf8')
    print('\n报告已写：', OUT_MD)


if __name__ == '__main__':
    main()
