#!/usr/bin/env python
# -*- coding: utf-8 -*-
# OFFICIAL-PATH-TOMBSTONE v1  ← 这行是机器可检的签名，别删、别改字。
#                               tools/check_official_path.py 的 [P3] 靠它认桩。
#
# 【路障桩模板】把废弃/上移的脚本换成这个壳，留在**原路径**上。
#
# 为什么不能直接删或搬走了事（2026-10-19 治理批的立论）：
#   静默归档比留着更糟。调用方（尤其是 agent）拿到 FileNotFoundError 之后
#   不会停下来问，它会**自己去猜替代方案**——那就是「每个 agent 用法都不一样」
#   这条病的起点。桩的作用是：把"这条路封了"和"该走哪条"一次性说清楚，
#   并且用一个**可区分的退出码**让调用方知道这是配置问题不是脚本崩了。
#
# 用法：
#   1. 复制本文件到被废弃脚本的原路径（覆盖它），文件名保持不变。
#   2. 把下面三处 TODO 换成实际内容。
#   3. 在 D:/AIWorkflow/官方路径.json 的 deprecated 段登记这一项
#      （path / reason / use_instead / since / 状态）。
#   4. 跑 py D:/AIWorkflow/tools/check_official_path.py --run-stubs 验退出码。
#
# ⚠ 桩里**只许用正斜杠路径**。Windows 下 r"D:\AIWorkflow" 在普通字符串里会触发
#   SyntaxWarning: invalid escape sequence '\A'，而 raw 字符串又不解释 \n —— 两边都是坑。
#   统一写 D:/AIWorkflow/... 最省事（本项目已为此翻过一次车）。
# ⚠ 桩**不许 import 任何本项目模块**。它要在依赖已经被搬走/删掉的情况下还能跑起来，
#   否则报的是 ImportError 而不是"这条路封了"。
import sys

# TODO(1): 一句话说清这个文件原来是什么、什么时候被封的。
WHAT = "TODO: 原脚本名与用途"
SINCE = "TODO: YYYY-MM-DD"

# TODO(2): 确切可复制粘贴的替代命令。别写"见文档"——要写能直接跑的那一行。
USE_INSTEAD = "cd D:/AIWorkflow/engine && python run.py <workflow>"

# TODO(3): 如果有"旧的某个开关废了、换成什么"这类坑，写在这里；没有就删掉这段。
GOTCHA = ""

sys.stderr.write(
    "[已封] %s 于 %s 停止使用。\n" % (WHAT, SINCE)
    + "改走：%s\n" % USE_INSTEAD
    + (GOTCHA + "\n" if GOTCHA else "")
    + "全部官方入口见 D:/AIWorkflow/官方路径.json\n"
)
sys.exit(78)   # EX_CONFIG：与"脚本自己跑失败"(1) 和"参数用错"(2) 区分开，便于 tripwire 统计
