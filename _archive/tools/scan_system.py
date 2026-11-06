#!/usr/bin/env python
# -*- coding: utf-8 -*-
# OFFICIAL-PATH-TOMBSTONE v1
"""tools/scan_system.py —— 这里原来是第二份 scan_system.py 副本，2026-10-19 归档。

正身在 E:/若水AI电影/99_维护/scan_system.py（它扫那棵树、产物 system_manifest.json 落那儿，
且引用它的文档就是那项目自己的 00_架构总纲.md 与 99_维护/README.md）。
本副本没有任何代码 import 它，也没有生产代码按绝对路径调它 —— 纯多一份抄本，
而两份同字节＝早晚漂（2026-10-19 为 knobs 打补丁时就得同步改两边，那正是漂移的前兆）。
"""
import sys

WHAT = "D:/AIWorkflow/tools/scan_system.py（scan_system.py 的第二份副本）"
SINCE = "2026-10-19"
USE_INSTEAD = ("python E:/若水AI电影/99_维护/scan_system.py"
               "        # 正身；产物写 E:/若水AI电影/system_manifest.json")
GOTCHA = ("⚠ 别再往 D:/AIWorkflow/tools/ 放第二份：要跨项目用就在调用处写全路径，"
          "或者把它登记成 engine/channels_registry.json 的外部工具而不是复制文件。")

sys.stderr.write(
    "[已封] %s 于 %s 停止使用。\n" % (WHAT, SINCE)
    + "改走：%s\n" % USE_INSTEAD
    + (GOTCHA + "\n" if GOTCHA else "")
    + "全部官方入口见 D:/AIWorkflow/官方路径.json\n"
)
sys.exit(78)   # EX_CONFIG
