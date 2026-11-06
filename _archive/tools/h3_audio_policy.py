# -*- coding: utf-8 -*-
"""Ref2VA 音频上限「按哪种读法」的唯一真源（一个只读环境变量的小函数，谁要显示都调它）。

为什么要单独一个文件：这份口径此前**只活在注释里**——
· 官方 `README.zh-CN:85` 把音频写成**一类 ≤3 段**（同一段还写了每段 2–15 秒、总 ≤15 秒、不可单独输入、总文件 ≤12）；
· T8 节点 schema 拆成 `ref_video_audios ≤3` 与 `ref_audios ≤3`（合计可到 6）。
用户 2026-10-24 08:15 裁定：**默认按节点口径放行＋超限 warn**，官方逐字读法保留成开关
（`AW_H3_AUDIO_STRICT`）。裁定定了下来，但"这一批走的哪种读法"必须让人在计划里看见，
不然事后问"6 段音频怎么过的"只能翻代码——这正是监督方 10-24 终局点名的可见性缺口。

本文件刻意**零依赖**（不 import cv2 / yaml / 引擎模块），所以 ComfyUI 面板、`run_plan`、
`check_preflight` 三处都能安全引用它，不会把重依赖拖进面板进程。
"""
import os

SWITCH = "AW_H3_AUDIO_STRICT"
OFFICIAL_SOURCE = "README.zh-CN:85"
DECIDED_BY = "用户 2026-10-24 08:15 裁定：默认节点口径（每类各 ≤3）＋超限 warn；官方逐字读法留成开关"


def audio_reading_policy(environ=None):
    """返回本批音频读法的自述字典（**不判、不改行为**，只把"现在按哪种读法"说清楚）。"""
    env = os.environ if environ is None else environ
    raw = str(env.get(SWITCH) or "").strip()
    strict = bool(raw)
    return {
        "reading": "official_one_class_max3" if strict else "node_per_kind_max3",
        "strict": strict,
        "label_cn": ("官方逐字：音频**一类合计 ≤3**（严格档，超限 error）" if strict else
                     "节点口径：视频原声 ≤3 且独立音频 ≤3（默认档，合计可到 6，超限只 warn）"),
        "switch": SWITCH,
        "switch_value": raw or "(未设)",
        "decided_by": DECIDED_BY,
        "official_source": OFFICIAL_SOURCE,
        "applies_to": "provider=local 且 input_mode=ref2va（别的通道没有参考音频槽）",
    }


def summary_line(policy=None):
    """给人读的一行：摘要与 `--inspect` 用它，保证面板/CLI/闸看到的是同一句话。"""
    p = policy or audio_reading_policy()
    return ("音频读法 %s ｜开关 %s=%s ｜出处 %s ｜适用于 %s"
            % (p["label_cn"], p["switch"], p["switch_value"],
               p["official_source"], p["applies_to"]))
