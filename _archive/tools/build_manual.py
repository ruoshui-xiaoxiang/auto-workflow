#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D 版 build_manual.py —— **薄委托**（S4，2026-10-24）。

唯一实现与唯一清单都在：
    E:/本地工作流规范手册/99_维护/build_manual.py
（`E:/本地工作流规范手册/刷新副本.bat` 调用的也是那一份。）

为什么保留这个文件：历史命令、登记与测试里还在引用这个路径；直接删掉会让
"文件不存在"变成一个假故障。现在它只把参数原样转给 E 版并透传退出码，**不再有
第二份清单**——以前两份同名脚本写同一个手册根、清单各有一套，谁最后跑手册就长成
谁的样子（RC-24）。

S4 合并前先只读比对过清单：D 独有的 6 条已全部并进 E 版（4 个启动器＋两个工具的真源
路径），E 版独有的 100 条保留；此文件改为委托后，两边的 `--check` 必然是同一结果。

用法与 E 版完全一致：
    py -3.12 build_manual.py            # 建目录 + 拷贝 + 出清单
    py -3.12 build_manual.py --check    # 只报告落后/缺源，不写文件
    py -3.12 build_manual.py --check --strict
"""
import runpy
import sys
from pathlib import Path

TARGET = Path(r"E:/本地工作流规范手册/99_维护/build_manual.py")

if not TARGET.is_file():
    print("D 版已改为薄委托，但真源不在：%s" % TARGET, file=sys.stderr)
    print("请恢复 E 维护版，或从 D:/AIWorkflow/backups/_优化_20261023/ 找回历史副本。",
          file=sys.stderr)
    sys.exit(2)

sys.argv = [str(TARGET)] + sys.argv[1:]
runpy.run_path(str(TARGET), run_name="__main__")
