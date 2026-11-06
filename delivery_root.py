# -*- coding: utf-8 -*-
"""交付根（output_root）的**唯一推导处**。

为什么单独一个文件（2026-10-02，批1 GAP-E1）
------------------------------------------
`config.yaml` 的 `output_root` 写的是某个项目的**绝对路径字面量**，而引擎在
`run.py` 里又按 `pool_root/<project>/批次` 现推一遍。两条路并存的结果是：

  · `run.py` 这条路没事——它推完还会用 G11 校，不一致就 `sys.exit(2)`。
  · `webui.py` 直接 `Path(CFG["output_root"])` 读**原始字面量**，
    于是切了项目以后，webui 列的还是上一个项目的批次夹（`OUT_ROOT.iterdir()`）。
  · `engine/tools/migrate_stage_d.py` 同样读原始字面量。

⇒ 这不是"配置写死了上一个项目"那么简单，是**同一个值有两套取法**。
本模块把取法收成一处：谁要交付根，都调 `delivery_root()`，不许自己拼、
也不许直接信 config 里那行字面量。

config 里那行 `output_root` 仍然保留，因为它有两个既有用途：
  1. `tests/test_gates_phase1.py` 拿它当"字面量有没有跟着 project 走"的哨兵；
  2. 显式 `--output-root` 时它是被覆盖的对象。
保留 ≠ 权威：**权威是 `delivery_root(cfg)`**，字面量只是哨兵＋兜底。
"""
from __future__ import annotations

from pathlib import Path


def delivery_root(cfg, cli_override=None, project=None, is_selftest=False):
    """算出这次运行的交付根（返回 str）。

    优先级与 `run.py` 原有行为**逐字一致**，只是收成了一处：
      1. 命令行显式 `--output-root` → 原样用它（调用方负责自己确认落点）；
      2. selftest 流 → 用 `selftest_output_root`，绝不能往交付根写，否则自测造出假批次；
      3. 有 `pool_root` ＋ `project` → 派生 `pool_root/<project>/<batch_subdir>`；
      4. 以上都不成立 → 退回 config 里的 `output_root` 字面量（此时它才是真值）。
    """
    if cli_override:
        return str(cli_override)
    if is_selftest and cfg.get("selftest_output_root"):
        return str(cfg["selftest_output_root"])
    proj = str(project if project is not None else (cfg.get("project") or ""))
    pool = cfg.get("pool_root")
    if pool and proj:
        return str(Path(pool) / proj / str(cfg.get("batch_subdir") or "批次"))
    return str(cfg.get("output_root") or "")


def config_literal_is_fresh(cfg):
    """config 里那行 `output_root` 字面量，跟当前 project 派生出来的值对不对得上。

    对不上就意味着：走 `delivery_root()` 的调用方没事，但**任何直接读字面量的新代码
    会悄悄拿到上一个项目的落点**。这正是 9-18 仙戮四条串进无音批次夹的形状。
    返回 (ok, 派生值, 字面量)。"""
    derived = delivery_root(cfg)
    literal = str(cfg.get("output_root") or "")
    return (derived == literal), derived, literal
