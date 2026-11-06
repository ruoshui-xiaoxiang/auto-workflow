# -*- coding: utf-8 -*-
"""W0 会话级隔离（计划 §3-W0：先隔离后测试）。

本文件被 pytest 加载时**立即生效**，先于任何测试模块 import —— 这是硬要求：
test_gate_e2e 在模块 import 时就要读 AW_CONFIG_PATH，fixture 跑得再早也晚于
模块 import，所以隔离 config 与环境变量必须在 conftest 模块体内就备好。

做的事：
  · sys.dont_write_bytecode / PYTHONDONTWRITEBYTECODE：pycache 不写源树（父子同禁）
    【注：跑测试的推荐口径是 `py -3.12 -B -m pytest -p no:cacheprovider tests`，
      -B 连 conftest 自身的 pyc 也不写；本行保证万一忘了 -B，测试模块也不写。】
  · AW_ISOLATED=1 + PYTHONPATH 前置 sitecustomize_iso：子进程（run.py）自动带守卫
  · AW_ISOLATED_LOG：子进程拦截记录 JSONL（session tmp 下），父进程聚合作证据
  · AW_CONFIG_PATH：session tmp 里的隔离 config（status/审批/落点全在 tmp，
    feishu.push_gates 显式 off）；run.py 经 _load_cfg() 读它，真台账零接触
  · install()：父进程守卫——socket 三层、Popen 白名单、SESSION 死桩、
    ensure_comfyui / send_media_to_feishu 计数桩

fixture：
  · _session_isolation（session, autouse）：收尾把计数写 counters.json 并打印
  · iso（函数级）：每测试一个独立隔离 config（覆盖 AW_CONFIG_PATH）+ 计数基线
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True                      # 先于一切测试模块 import
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"         # 传子进程

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))                     # import tasks 用
sys.path.insert(0, str(TESTS_DIR))                  # import _isolation 用

os.environ["AW_ISOLATED"] = "1"
os.environ["PYTHONPATH"] = (str(TESTS_DIR / "sitecustomize_iso")
                            + os.pathsep + os.environ.get("PYTHONPATH", ""))

import pytest                                       # noqa: E402
import _isolation                                   # noqa: E402

# ---- 以下三步必须在模块体完成（见 docstring 顶部）----
_SESSION_TMP = Path(tempfile.mkdtemp(prefix="aw_iso_"))
os.environ["AW_ISOLATED_LOG"] = str(_SESSION_TMP / "child_guard.jsonl")
_SESSION_CFG, _SESSION_CFG_PATH = _isolation.isolated_config(_SESSION_TMP)
os.environ["AW_CONFIG_PATH"] = str(_SESSION_CFG_PATH)
COUNTERS = _isolation.install()


@pytest.fixture(scope="session", autouse=True)
def _session_isolation():
    yield {"cfg": _SESSION_CFG, "cfg_path": _SESSION_CFG_PATH,
           "counters": COUNTERS, "tmp": _SESSION_TMP}
    snap = COUNTERS.snapshot()
    (_SESSION_TMP / "counters.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[W0 隔离计数（全为拦截次数，放行仅白名单）] {snap}\n"
          f"[W0 证据目录] {_SESSION_TMP}")


@pytest.fixture()
def iso(tmp_path):
    """函数级：每测试独立隔离 config（AW_CONFIG_PATH 临时改指它，测完还原
    session 级）+ 计数基线快照（在 before 里，供断言增量）。"""
    cfg, yaml_path = _isolation.isolated_config(tmp_path)
    prev = os.environ["AW_CONFIG_PATH"]
    os.environ["AW_CONFIG_PATH"] = str(yaml_path)
    before = COUNTERS.snapshot()
    yield {"cfg": cfg, "cfg_path": yaml_path, "counters": COUNTERS,
           "before": before, "tmp": tmp_path}
    os.environ["AW_CONFIG_PATH"] = prev
