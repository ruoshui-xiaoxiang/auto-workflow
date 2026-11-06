# -*- coding: utf-8 -*-
r"""运动质检（留痕期，只报警不拦批）。

2026-10-19 从 tmp/scene_20261004/motion_qc.py 上移为正式工具（真源不许住在 tmp）。
原处已留路障桩指向本文件。上移时做了三处修正，见下方「2026-10-19 修正」。

两把尺成对用，缺一不可（2026-10-07 实测教训）：
  · 速度 = 逐帧平均位移，口径照抄 motion_ab.py：736×416 强制拉伸 + Farneback(0.5,3,15,3,5,1.2,0)
  · 幅值 = lag 12 帧（约 0.5 秒）的平均位移，同一网格同一算法
逐帧单尺量的是"速度"：说话、缓缓抬头这类慢速连续运动逐帧只有 0.03~0.15 px，
会被 <0.35 判成"冻结"，而我们 32 镜里这样被误判的有 15 条、真静止只有 1 条。
⇒ 判定：两把尺都低 = 真静止；速度低幅值够 = 慢速连续；幅值高 = 明显运动。

2026-10-19 修正（三条，都是复核时抓出来的）：
  ① **常量拆分**。原来只有一个 `FROZEN = 0.35`，speed 与 amplitude 共用它，而
     thresholds_registry 记的 2026-10-07 标定是两个不同的数（speed_max=0.05 /
     amplitude_max=0.35，decided_by:「第1集32镜实测标定（n=32；真静止仅G10 speed=0.038）」）。
     真相是：**0.35 是"三档分类"阈值，0.05 是"真静止报警"阈值，两个不同的量共用了同一个变量名**。
     若粗暴把 speed 侧改成 0.05，那 15 条「speed<0.35 但幅值 0.43~3.8」的镜头会从
     "慢速连续"变成"明显运动"＝误分类回归。所以拆成三个具名常量：
       MOTION_DEAD_SPEED_MAX     = 0.05  ← registry motion_dead_speed_max 的 authority
       MOTION_DEAD_AMPLITUDE_MAX = 0.35  ← registry motion_dead_amplitude_max 的 authority
       MOTION_KIND_SLOW_MAX      = 0.35  ← 三档分类用，不是报警阈值
     在 32 镜标定样本上，verdict 与 speed_frozen_pct / amplitude_frozen_pct 三个输出
     **与改前逐值相同**（G10 speed=0.038<0.05 且 amplitude=0.308<0.35 仍是唯一真静止；
     那 15 条 amplitude≥0.43 不满足报警的 AND 条件，仍落"慢速连续"）。
  ② **去掉对 tmp 的隐式依赖**。原来 `--kind` 模式写死 `from ep1_shots import SHOTS`
     并 `sys.path.insert(0, 本文件所在目录)`——搬到 tools\ 后那个目录里就没有 ep1_shots 了。
     改成显式 `--shots <路径>`，找不到就明确报错，**不静默回落到 tmp**。
  ③ 本文件无任何代码调用者（唯一引用是 thresholds_registry 的两条 places 指针），
     所以这次改动的影响面是零；enforced=alarm_only，不拦批。

用法：
  python motion_qc.py <mp4目录>                       # 写 motion_profile.json 并打印分档
  python motion_qc.py <mp4目录> --shots <镜头表.py>    # 同时按镜头表补 motion_kind 字段
       （镜头表需暴露 SHOTS，每项形如 (sid, ?, action, lines)；旧写法 --kind 已废）
"""
import json
import os
import re
import sys

import cv2
import numpy as np

GRID = (736, 416)
LAG = 12

# --- 报警阈值（thresholds_registry 的 authority，enforced=alarm_only）---
# 两者必须**同时**低于上限才判"真静止"。单用 speed 会误杀慢速连续运动。
MOTION_DEAD_SPEED_MAX = 0.05        # px/帧 @736x416
MOTION_DEAD_AMPLITUDE_MAX = 0.35    # px/0.5s @736x416

# --- 三档分类阈值（不是报警阈值，别混用）---
# 低于它的 speed 才算"慢"，配合 amplitude 决定落"慢速连续"还是"明显运动"。
MOTION_KIND_SLOW_MAX = 0.35


def _gray(fs):
    return [cv2.cvtColor(cv2.resize(f, GRID, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
            for f in fs]


def _flow(g, lag):
    out = []
    for i in range(len(g) - lag):
        f = cv2.calcOpticalFlowFarneback(g[i], g[i + lag], None, 0.5, 3, 15, 3, 5, 1.2, 0)
        out.append(float(np.mean(np.sqrt(f[..., 0] ** 2 + f[..., 1] ** 2))))
    return np.array(out)


def profile(path):
    c = cv2.VideoCapture(path)
    fs = []
    while True:
        ok, f = c.read()
        if not ok:
            break
        fs.append(f)
    c.release()
    if len(fs) < LAG + 2:
        return None
    g = _gray(fs)
    sp = _flow(g, 1)
    am = _flow(g, LAG)
    # 真静止 = 两把尺同时低于报警上限（registry 的两个 authority 常量）
    if sp.mean() < MOTION_DEAD_SPEED_MAX and am.mean() < MOTION_DEAD_AMPLITUDE_MAX:
        kind = "真静止"
    elif sp.mean() < MOTION_KIND_SLOW_MAX:
        kind = "慢速连续"
    else:
        kind = "明显运动"
    # 两个 frozen_pct 沿用分类阈值 0.35（与 2026-10-07 那批标定输出的口径一致，
    # 改成报警阈值会让历史数字对不上，所以刻意保留）
    return dict(speed=round(float(sp.mean()), 3),
                speed_frozen_pct=round(float((sp < MOTION_KIND_SLOW_MAX).mean()) * 100, 1),
                amplitude=round(float(am.mean()), 3), amplitude_min=round(float(am.min()), 3),
                amplitude_frozen_pct=round(float((am < MOTION_KIND_SLOW_MAX).mean()) * 100, 1),
                verdict=kind, frames=len(fs),
                thresholds=dict(speed_max=MOTION_DEAD_SPEED_MAX,
                                amplitude_max=MOTION_DEAD_AMPLITUDE_MAX,
                                kind_slow_max=MOTION_KIND_SLOW_MAX),
                ruler="736x416拉伸+Farneback(0.5,3,15,3,5,1.2,0)；lag1=速度，lag12=幅值")


def motion_kind(sid, action, lines):
    if lines:
        return "dialogue"
    if re.search(r"走|跑|跳|挥|打|追|扑|摔|爬|搬|拉|推(?!头)", action):
        return "action"
    if re.search(r"仰拍|俯拍|过肩|跟拍|推近|拉远|摇|环绕", action):
        return "camera"
    return "still"


def _load_shots(path):
    """从镜头表 .py 里取 SHOTS。显式路径，不静默回落。"""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        sys.exit("[ERROR] --shots 指向的文件不存在：%s\n"
                 "        旧版本写死 from ep1_shots import SHOTS 并从自身目录找，"
                 "上移到 tools\\ 后已改为显式传路径。\n"
                 "        第1集那份在 D:\\AIWorkflow\\tmp\\scene_20261004\\ep1_shots.py" % path)
    d = os.path.dirname(path)
    if d not in sys.path:
        sys.path.insert(0, d)
    mod = os.path.splitext(os.path.basename(path))[0]
    SHOTS = getattr(__import__(mod), "SHOTS", None)
    if SHOTS is None:
        sys.exit("[ERROR] %s 里没有 SHOTS" % path)
    return {s[0]: (s[2], s[3]) for s in SHOTS}


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if "--kind" in argv:
        sys.exit("[ERROR] --kind 已废（2026-10-19）：它原来写死从本文件所在目录 import ep1_shots，\n"
                 "        上移到 tools\\ 后那个目录里没有 ep1_shots。改用 --shots <镜头表.py>。")
    shots = None
    if "--shots" in argv:
        i = argv.index("--shots")
        if i + 1 >= len(argv):
            sys.exit("[ERROR] --shots 需要一个路径参数")
        shots = _load_shots(argv[i + 1])
        del argv[i:i + 2]
    d = argv[0]
    out = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".mp4") or f.startswith(("_head", "_tail")):
            continue
        p = profile(os.path.join(d, f))
        if not p:
            print("%s 帧数不足，跳过" % f[:-4])
            continue
        sid = f[:-4]
        if shots:
            p["motion_kind"] = motion_kind(sid, *shots.get(sid, ("", [])))
        out[sid] = p
        print("%-5s 速度%.3f(冻%5.1f%%) 幅值%.3f(冻%5.1f%%) → %s%s" % (
            sid, p["speed"], p["speed_frozen_pct"], p["amplitude"], p["amplitude_frozen_pct"],
            p["verdict"], "  kind=" + p.get("motion_kind", "") if p.get("motion_kind") else ""), flush=True)
    json.dump(out, open(os.path.join(d, "motion_profile.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    n = len(out)
    dead = [k for k, v in out.items() if v["verdict"] == "真静止"]
    print("\n共 %d 镜：真静止 %d 条%s ｜ 慢速连续 %d ｜ 明显运动 %d" % (
        n, len(dead), "：" + " ".join(dead) if dead else "",
        sum(1 for v in out.values() if v["verdict"] == "慢速连续"),
        sum(1 for v in out.values() if v["verdict"] == "明显运动")))
    print("已写 %s" % os.path.join(d, "motion_profile.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
