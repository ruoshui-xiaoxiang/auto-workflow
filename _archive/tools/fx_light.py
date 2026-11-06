# -*- coding: utf-8 -*-
"""fx_light.py — 招式光／起亮点／命中闪白 的后期叠光器（H3 特效打戏用）

为什么要有它：国漫"放技能"的观感＝**特效与动作帧级同步**，而这一层必须从模型手里拿回来。
实测依据（09-22 单变量）：模型把光当**缓慢移动的物体**而不是一次事件——速度、起止时刻、闪白落在哪一帧
只能后期精确到帧；且**同帧里只要同时有兵器与光，两者必被焊成"一把发光的兵器"并指向同框的人**
（[[feedback-combat-shot-grammar]] §三）。所以生成层负责"粗动作＋介质飞溅＋接触点爆亮"，
**方向性招式光一律由本脚本叠**。

三层 + 一个开关：
  core   起亮点／掌心光核：径向渐变，时域包络＝渐强→峰值→衰减（峰值帧由你指定）
  beam   光轨／光柱：从 origin 沿 dir 画线，带宽度与长度包络（出射方向＝兵器/手掌朝向的延长线）
  flash  命中闪白／冲击帧：整幅过曝 + 接触点白核（默认 60px，**别做大圆**，大圆读成"贴了个白球"）+ 放射线
  --flash auto|on|off   ⚠️ **命中点的过曝只该有一层负责**：生成侧自己炸出介质光 ⇒ 用 off，
                        生成侧没有 ⇒ 用 on。两层一起上就是"贴了个太阳"（09-28 用户裁定）。

用法：
  python fx_light.py <输入.mp4> <事件.json> -o <输出.mp4> [--flash auto] [--sheet 接触表.jpg] [--dry]
事件文件见同目录示例；坐标一律**归一化 0–1**（左下为原点，y 向上），这样换分辨率不用改事件。

⚠️ 两个本机既有坑已内置处理：① cv2 打不开中文路径 ⇒ 先拷进 ASCII 中转目录（`C:/Temp/fxlight/`）；
② 滤镜/混合写在中文路径上会炸 ⇒ 编码也在 ASCII 目录做完再拷回。
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

TMP = r'C:/Temp/fxlight'
FFMPEG = r'D:/AIWorkflow/tools/ffmpeg.exe'      # 与 reference-ffmpeg-location 一致：拼片/切点用这把


# ---------------------------------------------------------------- 几何原语

def _radial(h, w, xy, radius, softness=0.45):
    """归一化坐标的径向渐变，返回 float32 0–1。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = xy[0] * w, (1.0 - xy[1]) * h          # y 轴向上 → 转回像素坐标
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inner = radius * (1.0 - softness)
    m = np.clip((radius - d) / max(radius - inner, 1e-3), 0.0, 1.0)
    return (m * m * (3 - 2 * m)).astype(np.float32)  # smoothstep


def _line(h, w, origin, direction, length, width, taper=1.0, widen=1.0):
    """从 origin 沿 direction 的一条有宽度的线，返回 float32 0–1 与"沿线进度"数组（给长度包络用）。

    widen>1 ⇒ 线**越远越宽**（空气透视：光柱射远时被尘散开，远端是宽的、糊的，不是等宽的棍子）。
    ⚠️ direction 是**像素空间**方向（y 向下）。xy 是归一化 y 向上——"向右上射"要写负 dy。
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ox, oy = origin[0] * w, (1.0 - origin[1]) * h
    dx, dy = direction
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    px, py = xx - ox, yy - oy
    t = (px * dx + py * dy) / (length * w)           # 沿线进度 0–1
    perp = np.abs(-px * dy + py * dx)                # 垂距（像素）
    prof = np.clip(1.0 - t, 0.0, 1.0) ** taper       # 尾端渐细
    tc = np.clip(t, 0.0, 1.0)
    wt = width * (1.0 + (widen - 1.0) * tc)          # 沿线变宽
    band = np.exp(-(perp ** 2) / (2.0 * (wt / 2.0) ** 2))
    # 起点后方不再硬切：t<0 时在 origin_soft 段内线性淡出。
    # 原来写 (t >= 0.0) 是把 440px 宽的雾晕沿一条竖直线直接掐掉 ⇒ 锚点右侧整片被抬亮、
    # 左缘一根"玻璃板"竖直硬边（09-30 独立复跑实测：最大竖直台阶恰好落在锚点 x 上）。
    soft = float(width) / (2.0 * w) * 1.5 + 0.02
    m = band * prof * np.clip(t / soft, 0.0, 1.0) * (t <= 1.0)
    return m.astype(np.float32), np.clip(t, 0.0, 1.0)


def _sigil(h, w, xy, radius, points=6, phase=0.0, thickness=3, ring=True, glow=0.85):
    """法阵：N 角星的**程序化**图形（六芒星＝两个正三角叠加），可旋转。

    为什么程序画：法阵是**有精确几何的图形**，交给模型画会漂位置/漂角数；
    放在后期可以控制它出现的那一帧、半径、转速——这正是"特效与动作帧级同步"要的东西。
    glow＝再加一层大半径模糊（09-30 晚补：只有细线时读起来像"画上去的白线框"，
    加一层辉光才像发光体）。"""
    m = np.zeros((h, w), np.float32)
    cx, cy = xy[0] * w, (1.0 - xy[1]) * h
    r = radius * min(w, h)
    for k in range(2):                                   # 两个叠加的正多边形 ⇒ 2N 角星
        idx = [k + i * 2 for i in range(points // 2)]
        pts = []
        for i in idx:
            a = phase + 2 * math.pi * i / points - math.pi / 2
            pts.append([int(cx + r * math.cos(a)), int(cy + r * math.sin(a))])
        cv2.polylines(m, [np.array(pts, np.int32)], True, 1.0, thickness, cv2.LINE_AA)
    if ring:
        cv2.circle(m, (int(cx), int(cy)), int(r * 1.12), 1.0, max(1, thickness - 1), cv2.LINE_AA)
        cv2.circle(m, (int(cx), int(cy)), int(r * 1.26), 1.0, 1, cv2.LINE_AA)
    m = cv2.GaussianBlur(m, (0, 0), 1.8)
    if glow > 0:
        m = m + cv2.GaussianBlur(m, (0, 0), 9.0) * float(glow)
    return m


def _spokes(h, w, xy, radius, count=12, phase=0.0):
    """冲击帧的放射线。"""
    acc = np.zeros((h, w), np.float32)
    for i in range(count):
        ang = phase + 2 * math.pi * i / count
        m, _ = _line(h, w, xy, (math.cos(ang), math.sin(ang)), radius / w, 3.0)
        acc = np.maximum(acc, m)
    return acc


# ---------------------------------------------------------------- 时域包络

def _xy_t(t, e):
    """事件的挂点可以**在画面里走**：给了 xy0 就按时间从 xy0 线性插到 xy（到 xy_t1 为止）。

    为什么必须有它（09-30 晚踩到）：镜头一横移，主体在画面里的位置就变了——
    镜6 一个 1.5s 的镜头里她从左 0.19 走到右 0.35。锚点只量一个时刻 ⇒ 法阵飘在沙面上、
    根本不在她手上。**"逐镜各一条"还不够，移动镜头还要"逐帧跟着走"。**
    """
    x0 = e.get('xy0')
    if not x0:
        return e['xy']
    t0 = e['t0']
    t1 = float(e.get('xy_t1', e.get('t_hold', e.get('t_end', t0))))
    u = 0.0 if t1 <= t0 else min(1.0, max(0.0, (t - t0) / (t1 - t0)))
    return [x0[0] + (e['xy'][0] - x0[0]) * u, x0[1] + (e['xy'][1] - x0[1]) * u]


def _env(t, spec):
    """一个事件的时域包络：<t0 为 0，峰在 t_peak，可维持到 t_hold，之后按 decay 指数衰减到 t_end。

    t_hold 是 09-30 加"光柱射到天边"这一拍时补的：`光柱先急速延伸到天边，然后维持`——
    没有 hold 的话包络过峰即衰，"维持"这一段就写不出来，光柱会一边伸长一边变暗。
    """
    t0, tp = spec.get('t0'), spec.get('t_peak', spec.get('t0'))
    th = spec.get('t_hold', tp)
    te, decay = spec.get('t_end', th), spec.get('decay', 0.25)
    if t < t0 or t > te:
        return 0.0
    if spec.get('ease') == 'step':                    # 闪白：来就满、走就断
        return 1.0
    if t <= tp:
        u = (t - t0) / max(tp - t0, 1e-3)
        return u * u                                        # 渐强（慢起、末尾陡）
    if t <= th:
        return 1.0                                          # 维持段
    return math.exp(-(t - th) / max(decay, 1e-3))            # 衰减


# ---------------------------------------------------------------- 叠加

def _screen(base, layer):
    """screen 混合：out = 255 - (255-a)(255-b)/255。逐通道做，BGR/RGB 皆同式。"""
    return 255.0 - (255.0 - base) * (255.0 - layer) / 255.0


def render(in_mp4, events, out_mp4, flash_mode='auto', sheet=None, dry=False, max_frames=None, intra=False):
    cap = cv2.VideoCapture(in_mp4)
    if not cap.isOpened():
        sys.exit('打不开输入：%s' % in_mp4)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # flash 的最终开关：auto = 事件表里没有 diag_light=true 时才叠
    if flash_mode == 'auto':
        flash_on = not events.get('diegetic_flash', False)
    else:
        flash_on = (flash_mode == 'on')

    evs = []
    for e in events.get('events', []):
        e = dict(e)
        if e['type'] == 'flash' and not flash_on:
            continue
        evs.append(e)

    if dry:
        print('输入 %dx%d @%.3ffps' % (w, h, fps))
        print('闪白层：%s（diegetic_flash=%s）⇒ %s'
              % (flash_mode, events.get('diegetic_flash', False), '叠' if flash_on else '不叠'))
        for e in evs:
            print('  %-6s t=%.3f→%.3f 峰=%.3f %s' % (e['type'], e['t0'], e.get('t_end', e['t0']),
                                                     e.get('t_peak', e['t0']),
                                                     e.get('note', '')))
        if sheet:
            print('（--dry 不写片；接触表要真跑才有）')
        return {'frames': None, 'flash_on': flash_on}

    os.makedirs(TMP, exist_ok=True)
    raw = os.path.join(TMP, 'composed.avi')
    vw = cv2.VideoWriter(raw, cv2.VideoWriter_fourcc(*'FFV1'), fps, (w, h))
    if not vw.isOpened():
        vw = cv2.VideoWriter(raw, cv2.VideoWriter_fourcc(*'MJPG'), fps, (w, h))

    i, energy, picks = 0, [], []
    # 接触表取样＝**全片均匀 12 帧**（不是每 fps/3 一帧——那样只采到片头，事件帧进不了表）
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if max_frames:
        n_total = min(n_total, max_frames) if n_total else max_frames
    pick_set = set(int(round(x)) for x in np.linspace(0, n_total - 1, 12)) if (sheet and n_total) else set()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if max_frames and i >= max_frames:
            break
        t = i / fps
        ov = np.zeros((h, w, 3), np.float32)     # 空气里那道光本身（emissive，最终 screen 上去）
        ill = np.zeros((h, w, 3), np.float32)    # ★光**照到场景上**的那一份（乘法，09-30 晚补）
        tints = []              # ★全屏淹没／余晖 (颜色BGR, 强度, 亮部偏置) —— 最后**加**上去
        lum = (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0)
        hzcache = {}
        for e in evs:
            a = _env(t, e)
            if a <= 0.0:
                continue
            col = np.array(e.get('color', [150, 235, 255]), np.float32)[::-1]  # 事件写 RGB，内部 BGR
            gain = float(e.get('gain', 1.0)) * a
            if e['type'] == 'core':
                m = _radial(h, w, _xy_t(t, e), float(e.get('radius', 30)),
                            float(e.get('softness', 0.45)))
                ov = np.maximum(ov, m[..., None] * col[None, None, :] * gain)
                # ★星芒（10-01 用眼睛补）：远处一个**撞在天边的爆点**应该是一个刺眼的小核＋放射星芒；
                #   只给一个大半径高斯 ⇒ 读成"画面右上角糊了个焦外光斑"（v9 镜4 落点实测就是这个样）。
                sk = int(e.get('spikes', 0))
                if sk > 0:
                    sp = _spokes(h, w, _xy_t(t, e), float(e.get('spike_len', 0.12)) * w,
                                 sk, float(e.get('spike_phase', 0.0)))
                    ov = np.maximum(ov, (sp * float(e.get('spike_gain', 0.85)) * gain)[..., None]
                                    * col[None, None, :])
                lg = float(e.get('lit', 0.0))
                if lg > 0:                                   # 起亮点也照亮它周围
                    ill += (m[..., None] * col[None, None, :] / 255.0) * (gain * lg) \
                           * (lum[..., None] ** float(e.get('lit_exp', 0.85)))
            elif e['type'] == 'beam':
                # 光柱的**长度也随包络走**：grow = 起始长度占比。
                #   grow 0.0 → 从 0 射出去（"急速延伸到天边"）；grow 0.25 → 边淡边收（"慢慢消失"）；1.0 → 不伸缩
                grow = float(e.get('grow', 1.0))
                L = float(e.get('length', 1.0)) * (grow + (1.0 - grow) * a)
                W = float(e.get('width', 8))
                tap, wid = float(e.get('taper', 1.0)), float(e.get('widen', 1.0))
                # ★ 一条光柱＝三层同心：细芯（亮的丝）＋雾晕（等宽的那圈光）＋大晕（空气里的辉）
                #   只画一层等宽的线 ⇒ 读成"贴了一条白棍子"（09-30 晚用户判：和视频不在一个图层）
                cc = np.array(e.get('color_core', e.get('color', [232, 248, 255])), np.float32)[::-1]
                ch = np.array(e.get('color_haze', e.get('color', [200, 235, 255])), np.float32)[::-1]
                xy = _xy_t(t, e)
                mc, _ = _line(h, w, xy, e['dir'], L, max(1.2, W * float(e.get('core_mul', 0.34))), tap, wid)
                mh, _ = _line(h, w, xy, e['dir'], L, W, tap, wid)
                mw, _ = _line(h, w, xy, e['dir'], L, W * float(e.get('halo_mul', 5.0)), tap, wid)
                # ★沿线的亮度**跟着它穿过的介质走**：亮尘/沙处更亮、清空处更暗。
                #   没有这一项，光柱沿全长一个值、边界一个样 ⇒ 读成"贴上去的矢量棍"（09-30 晚用户判）。
                vary = float(e.get('vary', 0.0))
                if vary > 0:
                    sg = float(e.get('vary_sigma', 11.0))
                    if sg not in hzcache:
                        hzcache[sg] = np.clip((cv2.GaussianBlur(lum, (0, 0), sg) - 0.10) / 0.55, 0.0, 1.0)
                    modv = ((1.0 - vary) + 2.0 * vary * hzcache[sg])[..., None]
                else:
                    modv = 1.0
                # ★本层的贡献先攒进 ov_b（别直接写 ov）：闪烁只该作用于这条光柱自己，
                #   不能把之前叠好的掌心核／法阵一起闪（09-30 晚踩过一次才改的）。
                #   ★芯与雾是**同心的高斯**：相加会在中心堆到裁白（参考片芯是橙金 252,149,94，不是白）⇒ 取 max
                ov_b = np.maximum(mc[..., None] * modv * cc[None, None, :] * (gain * float(e.get('core_boost', 1.0))),
                                  mh[..., None] * modv * ch[None, None, :] * (gain * float(e.get('haze', 0.50))))
                ov_b += mw[..., None] * modv * ch[None, None, :] * (gain * float(e.get('halo', 0.10)))
                # ★多丝结构（09-30 晚按参考片补）：光柱内部是一束丝（十几条细光丝绕主线），不是一根棍
                ns = int(e.get('strands', 0))
                if ns > 0:
                    rs = np.random.RandomState(int(round(e['t0'] * 1000)) % (2 ** 31))
                    # ★散布必须按**柱宽**算，不能按画面宽算（10-01 用眼睛查出来的）：
                    #   原来写 off = uniform(-1,1)*W*0.5 ⇒ 镜4 七条丝的法向偏移实测 431/447/496px
                    #   ＝画面高(576)的 0.86 倍，而光柱自身半宽只有 44px ⇒ "丝束"根本不在柱里，
                    #   是七条独立光带随机甩到天空和地面里，把夜空拉出竖纹。
                    spread = float(e.get('strand_spread', 0.85))     # 相对柱宽的倍数，<1 才在柱内
                    swid = float(e.get('strand_width', 0.14))        # 丝的宽度＝柱宽的 14%
                    for _ in range(ns):
                        off = rs.uniform(-1.0, 1.0) * W * spread     # 横向散布（像素）
                        ja = rs.uniform(-0.014, 0.014)               # 角度抖动（弧度）
                        lj = rs.uniform(0.86, 1.0)                   # 长度抖动
                        ddx, ddy = e['dir']
                        n2 = math.hypot(ddx, ddy) or 1.0
                        ddx, ddy = ddx / n2, ddy / n2
                        ddx, ddy = ddx * math.cos(ja) - ddy * math.sin(ja), \
                                   ddx * math.sin(ja) + ddy * math.cos(ja)
                        # 垂直偏移（像素 off → 归一化）：Δx=−off·ddy/w，Δy=−off·ddx/h
                        so = [xy[0] - off * ddy / w, xy[1] - off * ddx / h]
                        ms, _ = _line(h, w, so, [ddx, ddy], L * lj, max(1.0, W * swid), tap, wid)
                        ms *= np.clip(1.0 - np.abs(off) / (W * spread * 1.25), 0.0, 1.0)   # 越靠边的丝越暗
                        ov_b += ms[..., None] * ch[None, None, :] * (gain * float(e.get('strand_gain', 0.5)))
                fl = float(e.get('flick', 0.0))
                if fl > 0:
                    fk = np.clip(1.0 + fl * (math.sin(t * 6.1) + math.sin(t * 12.7 + 1.7)) * 0.5, 0.3, 1.7)
                    ov_b *= fk
                # ★涌动（参考片的"光往上涌"）：一个亮点沿光柱循环扫过
                if e.get('surge'):
                    per = float(e.get('surge_period', 0.85))
                    u = ((t - e['t0']) / per) % 1.0
                    su = [xy[0] + u * L * e['dir'][0],
                          xy[1] - u * L * e['dir'][1] * w / h]    # 像素方向 → 归一化（×w/h）
                    ms = _radial(h, w, su, W * 0.42, 0.6)
                    ov_b = np.maximum(ov_b, ms[..., None] * cc[None, None, :]
                                      * (gain * float(e.get('surge_gain', 0.8))))
                ov += ov_b
                lg = float(e.get('lit', 0.0))
                if lg > 0:                                   # ★照亮被它扫过的沙、被它穿过的尘
                    prof = 0.55 * mh + 0.45 * mw
                    ill += (prof[..., None] * ch[None, None, :] / 255.0) * (gain * lg) \
                           * (lum[..., None] ** float(e.get('lit_exp', 0.85)))
                # ★轮廓光（10-01 用眼睛补）：她整个人是纯黑剪影，站在一道 255 级亮度的光柱起点上
                #   却**没有任何边光** ⇒ 像一张人形贴纸压在光上。
                #   为什么 lit 给不了它：lit 走的是 ill（乘性、∝lum^0.85＝反照率），黑衣服反照率≈0
                #   ⇒ 物理上"黑布不反光"没错，但**掠射角的边缘光不吃反照率**（菲涅尔），
                #   所以这一项必须走 emissive(ov) 加法，不能走 ill 乘法。
                rg = float(e.get('rim', 0.0))
                if rg > 0:
                    if ('rimband', round(float(e.get('rim_dark', 0.34)), 3)) not in hzcache:
                        dk = np.clip((float(e.get('rim_dark', 0.34)) - lum) / float(e.get('rim_dark', 0.34)), 0.0, 1.0)
                        hzcache[('rimband', round(float(e.get('rim_dark', 0.34)), 3))] = \
                            np.clip(cv2.GaussianBlur(dk, (0, 0), 1.6)
                                    - cv2.GaussianBlur(dk, (0, 0), 7.0), 0.0, 1.0)
                    near = np.clip(mh * 2.2 + mw * 1.1, 0.0, 1.0)      # 只有朝光柱那一侧的轮廓吃光
                    ov += (hzcache[('rimband', round(float(e.get('rim_dark', 0.34)), 3))] * near)[..., None] \
                          * cc[None, None, :] * (gain * rg)
            elif e['type'] == 'sigil':
                # 法阵：可选自转（spin 度/秒），半径也随包络走（radius0 → radius）＝"成形"/"收阵"
                spin = float(e.get('spin', 0.0)) * max(0.0, t - e['t0'])
                r0 = float(e.get('radius0', e.get('radius', 0.30)))
                r1 = float(e.get('radius', 0.30))
                m = _sigil(h, w, _xy_t(t, e), r0 + (r1 - r0) * a, int(e.get('points', 6)),
                           math.radians(float(e.get('phase0', 0.0)) + spin),
                           int(e.get('thickness', 3)), bool(e.get('ring', True)),
                           float(e.get('glow', 0.85)))
                ov = np.maximum(ov, m[..., None] * col[None, None, :] * min(1.0, gain) * 1.35)
                lg = float(e.get('lit', 0.0))
                if lg > 0:                                   # 法阵也照亮她胸前那片衣料
                    ill += (m[..., None] * col[None, None, :] / 255.0) * (min(1.0, gain) * lg) \
                           * (lum[..., None] ** float(e.get('lit_exp', 0.85)))
            elif e['type'] == 'flood':
                # 全屏淹没：peak 决定"淹没"到什么程度（1.0＝纯白丢结构，0.7＝过曝但留住尘埃与轮廓）
                ov += (255.0 - ov) * min(1.0, gain * float(e.get('peak', 1.0)))
            elif e['type'] == 'tint':
                # ★全屏淹没／金色余晖（10-01 一天里换了两次算子）：
                #   v9 lerp：out += (gold − out)·α ⇒ 全图对比度乘 (1−α)，α=0.8 时只剩 20%
                #      → 实测峰值帧成了一片米黄牛皮纸（7.80s 肉眼判）。
                #   v10 add：out += gold·α ⇒ 不压对比，但 R/G 先撞 255、B 后撞
                #      → 过曝区褪成**白**，实测 R−B 从 +104 掉到 +39（参考片是 +107）。
                #   v11 huelight（只给"淹没"那 0.36s 用）：把画面**重新打上一盏金色的灯**——
                #      亮度走"抬起来的原亮度"（结构在），色相整幅锁死成金的（暖度在）。
                #      这正是单色强光主导一帧时物理上发生的事：不是加白，是换光源。
                #   mode='add' 留给余晖：强度小，加法保结构，不至于把夜的色相也抹掉。
                at = min(1.0, float(e.get('alpha', 1.0)) * a)
                if at > 0:
                    tints.append((col.copy(), at, {k: float(e.get(k, d)) for k, d in
                                                   (('bias', 0.35), ('usm', 0.0),
                                                    ('dark', 0.0), ('dark_knee', 45.0))},
                                  e.get('mode', 'add')))
            elif e['type'] == 'flash':
                g = gain
                ov += (255.0 - ov) * (g * float(e.get('frame_gain', 0.65)))       # 整幅过曝
                core = _radial(h, w, e['xy'], float(e.get('radius', 60)), 0.55)
                ov = np.maximum(ov, core[..., None] * np.array([225, 245, 255], np.float32)[None, None, :])
                sp = _spokes(h, w, e['xy'], float(e.get('spoke_len', 0.16)),
                             int(e.get('spokes', 12)), float(e.get('spoke_phase', 0.0)))
                ov = np.maximum(ov, (sp * 0.7 * g)[..., None] * col[None, None, :])
        energy.append(float(ov.mean()))
        base = frame.astype(np.float32)
        if ill.any():
            base = (base * (1.0 + ill)).clip(0, 255)     # ★先把光"打"回场景，再把空气里那道光 screen 上去
        out = _screen(base, ov)
        for col_t, at_t, pp, mode in tints:
            if at_t <= 0:
                continue
            if mode == 'huelight':
                # ★淹没＝"换一盏金色的灯"，不是"加一层白"（10-01 v11）：
                #   亮度＝抬起来的原亮度（结构还在，只是被压到顶端 20% 里），色相＝整幅锁成金的。
                #   这样才同时拿到参考片那两个数：全屏均值 218（够亮）**且** R−B +107（够暖）。
                #   纯加法（v10）会先让 R/G 撞 255、B 后撞 ⇒ 过曝区褪成白，实测 R−B 掉到 +39。
                g = lum * 255.0
                lift = g + (255.0 - g) * at_t
                # ★找回被"抬平"抹掉的那 1%：底板在 7.8s 有 1% 分位=13（飞石/尘的深阴影），
                #   纯线性抬平后它变成 203 ⇒ 全片 100% 亮，比参考片的 91% 更"糊"（10-01 逐层对账量出来的）。
                #   usm：把原图的细节差分加回去（飞石的边缘重新硬起来）；
                #   dark：把最深的像素单独压回去（留住剪影，同时让"亮且暖占比"落回参考片区间）。
                # ⚠️ 参数一律走 pp 字典，不要在合成处写 e.get(...)：这里已经没有 e 了，
                #    写下去会拿到事件循环**泄漏**的最后一个事件（v12 首渲 usm/dark 全 0 就是这么来的）。
                if pp['usm']:
                    lift = lift + pp['usm'] * (g - cv2.GaussianBlur(g, (0, 0), 2.5))
                if pp['dark']:
                    lift = lift - pp['dark'] * np.clip(1.0 - g / pp['dark_knee'], 0.0, 1.0)
                lift = np.clip(lift, 0.0, 255.0)[..., None]
                hv = col_t / float(col_t.mean())              # 色相单位向量：只改三通道配比，不改明度
                out = lift * hv[None, None, :]
            else:
                out = out + col_t[None, None, :] * (at_t * ((1.0 - pp['bias']) + 2.0 * pp['bias'] * lum[..., None]))
        out = out.clip(0, 255).astype(np.uint8)
        if sheet and ((i in pick_set) if pick_set else (i % max(1, int(fps // 3)) == 0)):
            picks.append((i, out.copy()))
        vw.write(out)
        i += 1
    cap.release()
    vw.release()

    # 合音轨（别用 -shortest：本机实测会截掉尾音）；沿用原音轨，视频重编码
    if intra:
        # 全帧内（FFV1 无损）：用于**自证**——比较两次叠加时，帧间预测会把"闪光那几帧"的差异
        # 传染给邻近帧（B 帧可引用未来帧），量出来像"层漏出去了"，其实只是编码器做账。
        res = subprocess.run([FFMPEG, '-y', '-i', raw, '-i', in_mp4,
                              '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'copy',
                              '-c:a', 'aac', out_mp4], capture_output=True, text=True)
        if res.returncode != 0:
            subprocess.run([FFMPEG, '-y', '-i', raw, '-c:v', 'copy', out_mp4], check=True)
    else:
        res = subprocess.run([FFMPEG, '-y', '-i', raw, '-i', in_mp4,
                              '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'libx264', '-crf', '18',
                              '-pix_fmt', 'yuv420p', '-c:a', 'aac', out_mp4],
                             capture_output=True, text=True)
        if res.returncode != 0:
            subprocess.run([FFMPEG, '-y', '-i', raw, '-c:v', 'libx264', '-crf', '18',
                            '-pix_fmt', 'yuv420p', out_mp4], check=True)

    if sheet and picks:
        rows, cols = 4, 3
        picks = picks[:rows * cols]
        th = [cv2.resize(p[1], (w // 3, h // 3)) for p in picks]
        while len(th) < rows * cols:
            th.append(np.zeros_like(th[0]))
        grid = np.vstack([np.hstack(th[r * cols:(r + 1) * cols]) for r in range(rows)])
        cv2.imencode('.jpg', grid)[1].tofile(sheet)      # 中文路径用 imencode（本机老坑）

    return {'frames': i, 'flash_on': flash_on,
            'energy_mean': float(np.mean(energy)) if energy else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('events')
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--flash', default='auto', choices=['auto', 'on', 'off'])
    ap.add_argument('--sheet')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--max-frames', type=int, default=None)
    ap.add_argument('--intra', action='store_true', help='全帧内无损输出（自证用，排除帧间预测传染）')
    a = ap.parse_args()

    events = json.load(open(a.events, encoding='utf-8'))
    src, dst = a.input, a.out
    os.makedirs(TMP, exist_ok=True)
    if any(ord(c) > 127 for c in src):                   # 中文路径 → ASCII 中转
        tmp_in = os.path.join(TMP, 'in.mp4')
        shutil.copyfile(src, tmp_in)
        src = tmp_in
    tmp_out = os.path.join(TMP, 'out.mp4')
    st = render(src, events, tmp_out if any(ord(c) > 127 for c in dst) else dst,
                a.flash, a.sheet, a.dry, a.max_frames, a.intra)
    if any(ord(c) > 127 for c in dst) and not a.dry:
        shutil.copyfile(tmp_out, dst)
    print(json.dumps({'out': dst, **st}, ensure_ascii=False))


if __name__ == '__main__':
    main()
