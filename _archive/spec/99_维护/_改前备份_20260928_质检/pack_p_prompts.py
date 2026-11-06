# -*- coding: utf-8 -*-
"""把三阶 12 镜提示词合成一份可直接读的文档。

读 D:/AIWorkflow/ComfyUI_H3/prompts/wuzhaojunyi_三阶P*.txt 原文，
附总览表（时长/帧数/运镜/首帧来源/状态）与已知问题。
用法：python pack_p_prompts.py
"""
import io
import re
import time
from pathlib import Path

PR = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架')
OUT = Path(r'C:/Users/若水/Desktop/武昭君仪/三阶打斗_提示词全集.md')

ORDER = ['P1A', 'P1B', 'P1C', 'P1D', 'P2A', 'P2B', 'P2C', 'P2D',
         'P3A', 'P3B', 'P3C', 'P3D']
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
        f = list(PR.glob('wuzhaojunyi_三阶%s_*.txt' % sid))
        name = f[0].stem.split('_')[-1] if f else '?'
        lines.append('| %s | %s | %s | 124帧/5.17s | %s | %s | %s |' % (
            sid[:2], sid, name, CAM[sid], FIRST[sid], STATUS[sid]))
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
        f = list(PR.glob('wuzhaojunyi_三阶%s_*.txt' % sid))
        if not f:
            lines.append('> ⚠ 缺文件：%s' % sid)
            continue
        txt = f[0].read_text(encoding='utf8').strip()
        name = f[0].stem.split('_')[-1]
        lines.append('#### %s · %s ｜ %s ｜ 124帧 / 5.17s' % (sid, name, CAM[sid]))
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
    OUT.write_text('\n'.join(lines), encoding='utf8')
    print('已写', OUT, '（%d 行）' % len(lines))


if __name__ == '__main__':
    main()
