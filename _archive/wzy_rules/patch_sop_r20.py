# -*- coding: utf-8 -*-
"""一次性补丁：把 R20（一击干脆）与 v5 画风复测结论写进《技能包转H3》SOP。可重复跑（幂等：已打过就跳过）。"""
import io
import sys

P = r'E:/创作/技能包转H3_SOP/README_SOP.md'
s = io.open(P, encoding='utf-8').read()
n = 0

R20_ROW = (u'| 🔴 分镜表里的「收招／控制」：缠住→拽倒／举起→砸地 | '
           u'**不写"把对方这个人拖着走"**：`drags her`／`hauls back`／`leans her weight back`／'
           u'`back and forth`／`struggle`／僵持 全删，受力对象只能写成**物**（链子绷直、链子拖过灰）。'
           u'改成**一拍完成**：动作与结果写同一句，并带同拍词（at once／in the same motion／in one unbroken beat／snaps／随即）。'
           u'要"腾空／砸地"这类高结果，同镜必须写**凭什么受力**（手臂从肩到拳锁直、重心沉进髋＝桩），否则模型降成推搡 | '
           u'段2 v5 人审："链子缠身之后有拉扯的动作，这样反而会不好看……这种动作要干脆利落"。'
           u'回查两处都是稿子自己写的双向受力（镜5 `the pull drags her toward him`＋`leans her weight back`、镜7 `She hauls back`）。已立 **R20**，见 §6 ★★ |')

anchor1 = u'| 🔴 分镜表里的「机位：顶视角俯拍／过肩／背面」'
if R20_ROW[:24] not in s:
    lines = s.split('\n')
    for i, ln in enumerate(lines):
        if ln.startswith(anchor1):
            lines.insert(i + 1, R20_ROW)
            n += 1
            break
    else:
        sys.exit('找不到 R18 编译行')
    s = '\n'.join(lines)

old = u'看 `H3R18` 的 **error 必须为 0**'
new = u'看 `H3R18`／`H3R19`／`H3R20` 的 **error 必须为 0**'
if new not in s and old in s:
    s = s.replace(old, new, 1); n += 1

old2 = u'这把尺子的分辨力就是这么量出来的。'
new2 = (old2 + u'\n  R20 用同一方法量分辨力：段2 v5 → **error 3**（镜5 命中三处、镜7 一处、声音段一处）'
        u'→ v6 → error 0；段1 已验收稿 error 0。')
if 'R20 用同一方法量分辨力' not in s and old2 in s:
    s = s.replace(old2, new2, 1); n += 1

old3 = u'⚠️ 锐度会被**密集纹理物**污染（一屏铜钱能到 240+，那不是实拍感）；脸被画面边缘裁掉时脸面积报 0。'
new3 = (old3 + u'\n    🔴 **09-30 v5 复测把"加词治磨皮"判死了**：同锚同 seed 只在三处特写加皮肤质感词，'
        u'镜8 整帧锐度 71.5→**55.0**、彩度 105.4→**106.7**（预登记要 >100／<95，两项全未达），'
        u'而最大脸占比 9.2%→14.5% ⇒ **加质感词换来的是"镜头怼得更近"**，同一份细节铺到更大面积＝更糊。'
        u'换"脸内锐度"这把尺再量，方向对（23.4→32.1），但**完全没改动的镜2 从 160.8 摆到 263.5**，'
        u'批内噪声大于效应量 ⇒ 这把尺子**不许用于 A/B 归因**。'
        u'⇒ 判**模型层**：特写磨皮措辞层抬不动，实拍感交给**后期一层胶片颗粒**（§8）；'
        u'段1（已发抖音那条）同病更重，同判同治，不重生成。')
if '09-30 v5 复测把' not in s and old3 in s:
    s = s.replace(old3, new3, 1); n += 1

old4 = u'大肌群＋位移的拍（链子横穿空地、人被拽得滑、撞进柱身）全中；'
new4 = u'大肌群＋位移的拍（链子横穿空地、人撞进柱身）全中；'
if old4 in s:
    s = s.replace(old4, new4, 1); n += 1

old5 = u'同理，**一镜只放一个事件**：'
new5 = (u'★★ **收招一击干脆，禁双向拉扯**（R20，09-30 用户点名）：'
        u'「他往前冲、这一拽把她拖过去、她钉住脚后坐」在画面上＝两个人互相抵消，观众读不到谁赢，'
        u'节拍还被演成站着较力。改法只有用户给的两条路：'
        u'**① 缠身马上收紧→随即痛苦倒地**；**② 绞上脖子提到半空→快窒息时松手→砸地**。'
        u'共同点：**动作与结果同句、中间不许有来回**，且高结果要写明受力凭什么。'
        u'"删掉拉扯"还不够——**同拍词要显式写**（at once／in the same motion／随即），否则模型自己把它放慢。'
        u'⚠️ 别用否定句治它：写 "no pulling, no struggle" 等于把这两个概念喂给模型（与 R5 禁令句同判）。'
        u'声音段一起查：`boots skidding`／`she is dragged` 会把僵持再演一遍。'
        u'\n' + old5)
if '收招一击干脆' not in s and old5 in s:
    s = s.replace(old5, new5, 1); n += 1

io.open(P, 'w', encoding='utf-8').write(s)
print('patched %d places' % n)
