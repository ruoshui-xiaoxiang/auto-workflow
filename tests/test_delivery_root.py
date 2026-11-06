# -*- coding: utf-8 -*-
"""交付根只有一个取法（批1 GAP-E1 的守门用例）。

动因：`config.yaml` 里 `output_root` 是**绝对路径字面量**，而 `run.py` 另按
`pool_root/<project>/批次` 现推一遍。同一个值两套取法的结果是
`webui.py` 直接读字面量 ⇒ 切了项目以后面板列的还是上一个项目的批次夹。
现在三处都走 `delivery_root()`，本文件钉住两件事：
  ① 字面量不许悄悄漂（漂了就红，附两侧值）；
  ② 不许再出现"绕过 delivery_root 自己拼交付根"的新代码。
"""
import re
from pathlib import Path

import yaml

from delivery_root import config_literal_is_fresh, delivery_root

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def test_config_literal_output_root_has_not_drifted_from_project():
    """config 那行字面量必须等于按当前 project 派生的值。

    这条**不是**在要求谁去手改那行字面量——它是在要求：改 `project` 时必须同批改它，
    否则任何直接读字面量的代码会拿到上一个项目的落点（9-18 仙戮四条串进无音批次夹就是这个形状）。
    """
    ok, derived, literal = config_literal_is_fresh(CFG)
    assert ok, ("config.yaml 的 output_root 字面量已漂：\n"
                "  按 project=%r 派生 = %s\n"
                "  字面量          = %s\n"
                "改法：把字面量改成派生值，或删掉那行并接受走 delivery_root()。"
                % (CFG.get("project"), derived, literal))


def test_derived_root_keeps_project_segment():
    """派生值的项目段必须就是 project —— G11 的判据在 run.py 里靠这个前提才成立。"""
    r = delivery_root(CFG)
    assert CFG["project"] in Path(r).parts, r


def test_changing_project_moves_the_root():
    """换 project 必须换落点，且不依赖那行字面量。"""
    other = "仙戮"
    assert other != CFG["project"], "测试要挑一个跟当前 project 不同的代号"
    r = delivery_root(CFG, project=other)
    assert other in Path(r).parts and r != delivery_root(CFG), r


def test_cli_override_wins_and_selftest_isolates():
    """优先级：命令行 > selftest 独立落点 > 派生 > 字面量兜底。"""
    assert delivery_root(CFG, cli_override=r"Z:\显式给的根") == r"Z:\显式给的根"
    assert delivery_root(CFG, is_selftest=True) == str(CFG["selftest_output_root"])
    # 没 pool_root 也没 project 时才退回字面量
    assert delivery_root({"output_root": r"E:\只有字面量"}) == r"E:\只有字面量"


def test_delivery_root_is_pure():
    """helper 不许有副作用：不建目录、不写文件。"""
    before = {p for p in Path(CFG["pool_root"]).iterdir()} if Path(CFG["pool_root"]).is_dir() else set()
    delivery_root(CFG)
    delivery_root(CFG, project="一个不存在的项目代号XYZ")
    after = {p for p in Path(CFG["pool_root"]).iterdir()} if Path(CFG["pool_root"]).is_dir() else set()
    assert before == after, "delivery_root() 创建了目录 ⇒ 有副作用"


def test_no_caller_recomputes_the_root_by_hand():
    """源码级守门：除 delivery_root.py 自己，不许再有人手拼 pool_root/<project>/batch_subdir。

    判式是"文本里出现 `pool_root'] / ` 这种拼接"，粗，但本仓库的既有测试也这么守
    （见 test_stage_d.py 直接 assert 源码字符串），风格一致。
    """
    pat = re.compile(r"pool_root.{0,4}\}\s*/|cfg\[.pool_root.\]\s*/")
    offenders = []
    for f in sorted(ROOT.glob("*.py")) + sorted((ROOT / "tools").glob("*.py")):
        if f.name == "delivery_root.py":
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        for i, ln in enumerate(src.split("\n"), 1):
            if pat.search(ln) and "import" not in ln:
                offenders.append("%s:%d  %s" % (f.name, i, ln.strip()[:90]))
    assert not offenders, "这些地方绕过 delivery_root 自己拼交付根：\n  " + "\n  ".join(offenders)
