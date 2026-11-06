# -*- coding: utf-8 -*-
"""把三阶 12 镜提示词合成一份可直接读的文档。

读 D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架/wuzhaojunyi_三阶P*.txt 原文，
附总览表（时长/帧数/运镜/首帧来源/状态）与已知问题。

2026-09-28 命名变更：真源从 `prompts/` 搬进 `prompts_H3官方骨架/`，文件名**去掉了镜名后缀**
（`wuzhaojunyi_三阶P1A_拦路.txt` → `wuzhaojunyi_三阶P1A.txt`）。glob 因此改成"后缀可有可无"，
镜名改由下面 NAMES 承担（出处＝本文件"三阶段结构"表）——别再靠文件名反推。
用法：python pack_p_prompts.py
"""
import io
import io
import re
import sys
import time
from pathlib import Path

PR = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架')
OUT = Path(r'E:/创作/武昭君仪/三阶打斗_提示词全集.md')

ORDER = ['P1A', 'P1B', 'P1C', 'P1D', 'P2A', 'P2B', 'P2C', 'P2D',
         'P3A', 'P3B', 'P3C', 'P3D']
NAMES = {'P1A': '拦路', 'P1B': '试探', 'P1C': '吃亏', 'P1D': '力不敌',
         'P2A': '激发', 'P2B': '棍架', 'P2C': '棍扫', 'P2D': '过载',
         'P3A': '亮枪', 'P3B': '枪花', 'P3C': '崩弹', 'P3D': '点喉'}


def shot_file(sid):
    """找某一镜的真源；新旧命名都能吃到。取不到就返回 None（调用方必须报缺文件，别静默跳过）。"""
    for pat in ('wuzhaojunyi_三阶%s_*.txt', 'wuzhaojunyi_三阶%s.txt'):
        hits = sorted(PR.glob(pat % sid))
        if hits:
            return hits[0]
    return None


# ── 运镜刮取：中英两种形都读，解析成同一个三元组再比 ────────────────────
_TYPES = r"(Push In|Pull Out|Truck|Pan|Tilt|Arc(?: Shot)?|Tracking(?: Shot)?|Static(?: Shot)?|Shake(?: Slightly| Strongly)?|Roll(?: Clockwise| Counterclockwise)?|POV|Zoom In|Zoom Out)"
CN_CAM = re.compile(u"(小幅度|中幅度|大幅度)\\s*(慢速|快速|极速)\\s*" + _TYPES)
EN_AMP = re.compile(r"with\s+(small|large)\s+amplitude", re.I)
EN_SPD = re.compile(r"at\s+(slow|fast)\s+speed", re.I)
_AMP_CN = {u"小幅度": "small", u"中幅度": "medium", u"大幅度": "large"}
_SPD_CN = {u"慢速": "slow", u"快速": "fast", u"极速": "fast"}
_AMP_EN = {"small": "small", "large": "large", None: "medium"}
_SPD_EN = {"slow": "slow", "fast": "fast", None: "normal"}


def cam_measured(txt):
    """从真源正文里读运镜实测值，返回（展示串, 三元组）。读不到返回 (None, None)。"""
    for m in CN_CAM.finditer(txt):
        return (m.group(0).strip(), (m.group(3), _AMP_CN[m.group(1)], _SPD_CN[m.group(2)]))
    # 英文形：官方写法是「类型 ＋ with … amplitude ＋ at … speed」，也可能倒装。
    # ⚠ 类型词**只能按官方的大写形匹配**：早先用 re.I，结果 "rolling off" 里的 roll
    #   被判成 `Roll`，12 镜全报「声明≠正文」⇒ 受控词表是大小写敏感的字面量。
    best = None
    for sent in re.split(r"(?<=[.。])\s+", txt):
        ty = re.search(r"\b(?:" + _TYPES + r")\b", sent)
        am = EN_AMP.search(sent)
        sp = EN_SPD.search(sent)
        if not ty or not (am or sp):
            continue
        best = (sent, ty, am, sp)
        break
    if best:
        sent, ty, am, sp = best
        disp = sent.strip()
        disp = disp[:disp.find(".", 12)] if "." in disp[12:] else disp
        return (disp[:64], (ty.group(1), _AMP_EN[am.group(1).lower()] if am else "medium",
                            _SPD_EN[sp.group(1).lower()] if sp else "normal"))
    return (None, None)


def cam_of(sid, txt):
    """运镜从真源正文里**现读**，表里那份只当声明；两边都解析成三元组再比。

    ⚠ 实测读不到就**报错且不写文件**——原来空着照样出表，那份合订本看着完整、运镜列其实是空的。
    """
    disp, got = cam_measured(txt or "")
    if got is None:
        return (None, u"✗ 正文里读不到运镜（中英两种形都没匹配上）⇒ 不出表")
    want = CAM[sid]
    wm = CN_CAM.search(want)
    want_t = (wm.group(3), _AMP_CN[wm.group(1)], _SPD_CN[wm.group(2)]) if wm else (want, "", "")
    def canon(t):
        return re.sub(r"\s*shot$", "", (t or "").strip().lower())
    if canon(got[0]) != canon(want_t[0]) or got[1] != want_t[1] or got[2] != want_t[2]:
        return (disp, u"✗ 声明「%s」≠ 正文「%s」" % (want, disp))
    return (disp, "ok")

STAGE = {'P1': '阶段一 · 空手八极（她力量吃亏）',
         'P2': '阶段二 · 裹布棍法（对机械义体，均势转上风）',
         'P3': '阶段三 · 解布枪法（裸枪，碾压）'}
CAM = {'P1A': '中幅度慢速 Push In', 'P1B': '小幅度慢速 Truck', 'P1C': '中幅度慢速 Push In',
       'P1D': '中幅度慢速 Arc', 'P2A': '中幅度慢速 Push In', 'P2B': '小幅度慢速 Truck',
       'P2C': '中幅度慢速 Arc', 'P2D': '中幅度慢速 Push In', 'P3A': '中幅度慢速 Arc',
       'P3B': '中幅度慢速 Push In', 'P3C': '大幅度慢速 Truck', 'P3D': '中幅度慢速 Pull Out'}
FRAMES = {s: 124 for s in ORDER}
FIRST = {s: '接力（抽上一镜成片末帧）' for s in ORDER}
FIRST['P1A'] = '线稿机位首帧（可灵，唯一服装正确的锚）'
STATUS = {s: '细化版待渲待审' for s in ORDER}
STATUS['P1B'] = '**已过审（v7）**'
NOTE = {
    'P2B': '首帧接力自 P2A 末帧（机械臂特写、没带到混混全身）⇒ 混混被重新想象成短发黑T，待修',
    'P3C': '混混裤子漂成绿色；招牌有可读汉字',
    'P3A': '招牌有可读汉字（P3A–P3D 同）',
    'P3B': '招牌有可读汉字',
    'P3D': '招牌有可读汉字；线稿首帧右上原有「武君仪」字样，已本地 inpaint 抹除',
}


problems = []


def main():
    lines = []
    lines.append('# 三阶打斗 · 12 镜提示词全集')
    lines.append('')
    lines.append('> 真源目录：`D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架/`（2026-09-28 起：H3 视频层用**官方 I2VA 骨架**，十块已剥离到云端 SD 通道）')
    lines.append('> 快照时间：%s ｜ 规格：736×416 / 24fps / 124 帧 = 5.17s / 8 步 turbo + Bunny 武器战斗 LoRA'
                 % time.strftime('%Y-%m-%d %H:%M'))
    lines.append('> 定位：武打设计稿（previz），不进第一章成片；编排依据见 `三阶打斗编排_v2.md`')
    lines.append('')
    lines.append('## 总览')
    lines.append('')
    lines.append('| 阶段 | 镜 | 名 | 时长 | 运镜 | 首帧来源 | 状态 |')
    lines.append('|---|---|---|---|---|---|---|')
    for sid in ORDER:
        f = shot_file(sid)
        name = NAMES.get(sid) or (f.stem.split('_')[-1] if f else '?')
        txt = f.read_text(encoding='utf8') if f else ''
        cam, flag = cam_of(sid, txt) if txt else (CAM[sid], '✗ 没读到真源')
        if flag != 'ok':
            problems.append('%s %s' % (sid, flag))
            print('!! %s 运镜对不上：%s' % (sid, flag))
            cam = cam or '（读不到）'
        lines.append('| %s | %s | %s | %d帧/%.2fs | %s | %s | %s |' % (
            sid[:2], sid, name, FRAMES[sid], FRAMES[sid] / 24.0, cam, FIRST[sid], STATUS[sid]))
    lines.append('')
    lines.append('## 三阶段结构')
    lines.append('')
    lines.append('| 阶段 | 武学 | 力量关系 | 镜 |')
    lines.append('|---|---|---|---|')
    lines.append('| P1 空手八极 | 挂耳格挡、撑锤 | 她**吃亏**（力量破不开蛮力） | P1A 拦路 / P1B 试探 / P1C 吃亏 / P1D 力不敌 |')
    lines.append('| P2 裹布棍法 | 一架一拨、连拨带扫、棍头点戳 | 均势 → 她占上风 | P2A 激发 / P2B 棍架 / P2C 棍扫 / P2D 过载 |')
    lines.append('| P3 解布枪法 | 拦拿、单掌五花枪弹抖、压杆崩弹 | 她**碾压** | P3A 亮枪 / P3B 枪花 / P3C 崩弹 / P3D 点喉 |')
    lines.append('')
    lines.append('## 逐镜提示词全文')
    lines.append('')

    cur_stage = None
    for sid in ORDER:
        st = sid[:2]
        if st != cur_stage:
            cur_stage = st
            lines.append('### %s' % STAGE[st])
            lines.append('')
        f = shot_file(sid)
        if not f:
            lines.append('> ✗ **缺真源**：`%s/wuzhaojunyi_三阶%s*.txt` 不存在 ⇒ 这一镜没并进本文档，'
                         '先确认文件是否被改名/搬走，别当它已经写好了' % (PR, sid))
            print('!! 缺真源：三阶%s' % sid)
            continue
        txt = f.read_text(encoding='utf8').strip()
        name = NAMES.get(sid) or f.stem.split('_')[-1]
        cam = cam_of(sid, txt)[0]
        lines.append('#### %s · %s ｜ %s ｜ %d帧 / %.2fs' % (
            sid, name, cam, FRAMES[sid], FRAMES[sid] / 24.0))
        lines.append('')
        if sid in NOTE:
            lines.append('> ⚠ 已知问题：%s' % NOTE[sid])
            lines.append('')
        lines.append('```')
        lines.append(txt)
        lines.append('```')
        lines.append('')

    lines.append('## 附：本轮迭代中固化的写法经验')
    lines.append('')
    lines.append('1. **别写"前栽／收不住／背对"**——H3 会把"前冲惯性"一律演成"上身前弯"（塌下去）；要给一个稳定终点："撑住／站定／侧身"。')
    lines.append('2. **"掌根轻贴"容易演成抓握**——必须明写"手指张开、不抓不握、触一下就松"。')
    lines.append('3. **横向位移 H3 做不出来**——想要"错身而过"，只能靠运镜（Truck 跟着走）或改设计。')
    lines.append('4. **每拍写全四件**：哪个肢体、从哪到哪、接触点、对方身体反应（受力证据）。')
    lines.append('5. **底线句写死**：涉及脸/头的镜一律带"拳头绝对没有碰到她的脸和皮肤"。')
    lines.append('')
    txt = '\n'.join(lines)
    if problems:
        sys.exit(u"!! 有 %d 镜运镜对不上／读不到 ⇒ 合订本**不写**：%s" % (len(problems), problems))
    OUT.write_text(txt, encoding='utf8')
    # 行数按**成品实际换行数**报，不要报 len(lines)——条目里含多行全文，两者差近一倍（09-28 实测：
    # 成品 212 行、列表 129 条）。报错的数一旦进文档就成了假基线。
    print('已写 %s（%d 行 / %d 字，%d 个条目）'
          % (OUT, txt.count('\n') + 1, len(txt), len(lines)))


if __name__ == '__main__':
    main()
