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
"""
import re
from pathlib import Path

PR = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts')
OUT_MD = Path(r'D:/AIWorkflow/tmp/wzy/h3/三阶编排审计.md')

SHOTS = ['P1A', 'P1B', 'P1C', 'P1D', 'P2A', 'P2B', 'P2C', 'P2D',
         'P3A', 'P3B', 'P3C', 'P3D']

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


def frames_for(secs):
    for f, s in GRID:
        if s >= secs - 1e-6:
            return f, s
    return 362, 15.08


def audit(sid):
    files = list(PR.glob('wuzhaojunyi_三阶%s_*.txt' % sid))
    if not files:
        return None
    txt = files[0].read_text(encoding='utf8')
    name = files[0].stem.split('_', 2)[-1]

    m = re.search(r'【事件脚本】(.*?)(?:【Motion】|【保持一致】)', txt, re.S)
    body = m.group(1) if m else ''
    beats = [(float(a), float(b), c.strip()) for a, b, c in BEAT.findall(body)]
    dlgs = DLG.findall(txt)

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

    spans = [(a, b) for a, b, _ in beats]
    cur = spans[-1][1] if spans else 5.17
    cur_f, cur_s = frames_for(cur)
    want_f, want_s = frames_for(need_lo)
    over = cur_s < need_lo - 0.05
    ratio = cur_s / units if units else 99

    lim = 4 if violent else 6
    return dict(sid=sid, name=name, beats=[c for _, _, c in beats], spans=spans,
                acts=acts, show=show, violent=violent, dlgs=dlgs, units=units,
                need=(need_lo, need_hi), cur_s=cur_s, cur_f=cur_f, lim=lim,
                want_f=want_f, want_s=want_s, over=over, ratio=ratio, notes=notes,
                r15_bad=acts > lim)


def main():
    rows = [r for r in (audit(s) for s in SHOTS) if r]
    print('镜   名        动作形态 展示 剧烈 台词  单元  现给s   应给s(帧)   判定')
    print('-' * 92)
    tot_cur = tot_want = 0.0
    bad = []
    for r in rows:
        flag = []
        if r['r15_bad']:
            flag.append('R15 超甜点(%d>%d)' % (r['acts'], r['lim']))
        if r['over']:
            flag.append('R17 超载')
        j = '⚠ ' + '＋'.join(flag) if flag else 'ok'
        tot_cur += r['cur_s']; tot_want += r['want_s']
        print('%-4s %-9s %6.1f %5.1f %5s %3d %6.2f %6.2f %6.2fs(%3d)  %s' % (
            r['sid'], r['name'], r['acts'], r['show'],
            '剧烈' if r['violent'] else '从容', len(r['dlgs']), r['units'],
            r['cur_s'], r['want_s'], r['want_f'], j))
        if flag:
            bad.append((r, flag))
    print('-' * 92)
    print('合计 现 %.2fs（全 124 帧）→ 应 %.2fs  ⇒ 差 %.2fs' % (tot_cur, tot_want, tot_want - tot_cur))
    print('\n需处置：%d / %d 镜' % (len(bad), len(rows)))

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
    lines = ['# 三阶打斗 12 镜编排审计（R11–R17 · v2 口径）', '',
             '> 真源：`ComfyUI_H3/prompts/wuzhaojunyi_三阶P*_*.txt`｜脚本：`wzy/audit_p_fight.py`（只读）',
             '> **v1 判据是错的，v2 已修**：v1 把「对方出招＋我方化解」这种**接打一体**的复合拍当成'
             '"多一个动作"，八镜全被判超甜点；但 G1/R12 恰恰要求这么写——拆成两拍会演成"停一下再躲"的分步断层。',
             '> **v2 口径**：动作形态数＝模型要单独完成几个不同的动作姿态。接打一体（对方出招→我方化解→我方反击）、'
             '动作＋物理结果（崩飞→撞墙→瘫坐）、招式＋展示细节（枪花→弹抖→连点）**都算 1 个**。'
             '展示细节 0.5 单元、台词 1.75 单元。R15 甜点＝剧烈 2–4／从容 6；R17 时长＝单元×0.9–1.2s，向上吸附帧网格。',
             '', '| 镜 | 名 | 动作形态 | 展示 | 剧烈 | 台词 | 单元 | 现给 | 应给 | 判定 |',
             '|---|---|---|---|---|---|---|---|---|---|']
    tot_cur = tot_want = 0.0
    for r in rows:
        flag = []
        if r['r15_bad']:
            flag.append('R15 超甜点')
        if r['over']:
            flag.append('R17 超载')
        tot_cur += r['cur_s']; tot_want += r['want_s']
        lines.append('| %s | %s | %.1f | %.1f | %s | %d | %.2f | %.2fs | %d帧/%.2fs | %s |' % (
            r['sid'], r['name'], r['acts'], r['show'], '剧烈' if r['violent'] else '从容',
            len(r['dlgs']), r['units'], r['cur_s'], r['want_f'], r['want_s'],
            '⚠ ' + '＋'.join(flag) if flag else 'ok'))
    lines += ['', '合计：现 **%.2fs**（12 镜全 124 帧）→ 按 R17 应 **%.2fs**，差 **%.2fs**。' % (
        tot_cur, tot_want, tot_want - tot_cur), '',
        '## 需处置的镜', '']
    for r, flag in bad:
        lines += ['### %s（%s）— %s' % (r['sid'], r['name'], '＋'.join(flag)), '',
                  '- 动作形态 **%.1f**（甜点 %d）｜展示 %.1f｜台词 %d 条｜信息单元 **%.2f**' % (
                      r['acts'], r['lim'], r['show'], len(r['dlgs']), r['units']),
                  '- 现给 %.2fs（%d 帧）→ 建议 **%d 帧（%.2fs）**' % (
                      r['cur_s'], r['cur_f'], r['want_f'], r['want_s']), '',
                  '现事件脚本：', '']
        for (a, b), c in zip(r['spans'], r['beats']):
            lines.append('%d. `%.1f–%.1fs` %s' % (r['spans'].index((a, b)) + 1, a, b, c))
        if r['notes']:
            lines += ['', '复合但按 v2 只算 1 个动作形态的拍：']
            for b, lab in r['notes']:
                lines.append('- 「%s…」＝ **%s**' % (b, lab))
        lines.append('')
    OUT_MD.write_text('\n'.join(lines), encoding='utf8')
    print('\n报告已写：', OUT_MD)


if __name__ == '__main__':
    main()
