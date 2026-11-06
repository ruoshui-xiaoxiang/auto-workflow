# -*- coding: utf-8 -*-
"""审美判定这条线退役后的回归钉（2026-11-04 用户裁「所有带美学判定的都交给人来判，
机器只负责能实际判定的缺陷」）。

前身是 `tests/test_auto_flow.py`（auto 闭环的 7 条用例：阈值短路、带反馈改写、轮尽返回
最优、VL 直改提示词）。那条链整条退役了，旧用例不能"改成迁就新行为"留在盘上——
那等于用测试把已废的行为供起来。正身逐字节在
`backups/_治理_20261104/归档件/审美判定退役_20261104/test_auto_flow_py_退役前.py`。

本文件钉的是**退役本身**四件事：桩会说话、判分件不在模块里、事实型核查没被顺手带走、
现役链上没人再引这两个任务名。
"""
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tasks                             # noqa: E402
import run as engine_run                 # noqa: E402

WORKFLOWS = ROOT / "workflows"


# ──  桩必须会说话：调用方不许拿到裸 KeyError / ImportError 后自己去猜 ────────
def test_auto_task_is_a_tombstone_that_names_the_replacement():
    with pytest.raises(RuntimeError) as e:
        tasks.REGISTRY["auto"]({"theme": "x"}, {"log": lambda m: None, "args": {}})
    msg = str(e.value)
    assert "已退役" in msg, msg
    assert "image_draft_batch" in msg, "桩里必须写清替代命令，不能只说没了"
    assert "审美" in msg, msg


def test_vl_aesthetic_task_is_a_tombstone():
    with pytest.raises(RuntimeError) as e:
        tasks.REGISTRY["vl_aesthetic"]({"files": []},
                                       {"log": lambda m: None, "args": {}})
    msg = str(e.value)
    assert "已退役" in msg and "vl_qc" in msg, msg


def test_retired_chain_refuses_at_the_loader_and_prints_the_way_out(capsys):
    """`run.py auto_draft` 要停在桩上，并把原因／替代／恢复打全——
       而不是"工作流不存在"（那会逼人另找一条像的，正是这个项目记着的老病）。
       退出码必须是 **78（EX_CONFIG）**：调用方/脚本靠它区分"路封了"和"这次跑崩了"，
       这是本仓退役桩的硬约定（官方路径.json deprecated._note）。"""
    with pytest.raises(SystemExit) as e:
        engine_run.load_workflow(WORKFLOWS / "auto_draft.yaml")
    assert e.value.code == 78, "退役桩必须以 78 退出，不是 1／0"
    printed = capsys.readouterr().err
    for must in ("已退役", "image_draft_batch", "image_refine", "审美"):
        assert must in printed, (must, printed[:300])


# ── ② 判分本体真的不在了（不是只摘注册）────────────────────────────────────
def test_the_aesthetic_scorers_are_gone_from_the_module():
    src = io.open(ROOT / "tasks.py", encoding="utf-8-sig").read()
    for gone in ("def vl_score_image", "def _vl_score_frame", "_AESTHETIC_RUBRIC ="):
        assert gone not in src, "审美判分件还在模块里：%s" % gone
    for attr in ("vl_score_image", "_vl_score_frame", "_AESTHETIC_RUBRIC"):
        assert not hasattr(tasks, attr), "%s 仍可被直接调用" % attr


def test_the_factual_checkers_survived_the_cut():
    """反向自证：退役不许把**事实在场核查**一起带走。
       这条防的是"删干净"被理解成"删过头"——vl_qc 判的是谁在场／有没有瑕疵，不是好不好看。"""
    for keep in ("vl_content_check", "_vl_credentials", "_vl_ask", "_extract_frames"):
        assert hasattr(tasks, keep), "%s 被误删了" % keep
    assert "vl_qc" in tasks.REGISTRY, "事实型核查的任务入口没了"
    assert hasattr(tasks, "_batch_consistency_qc"), "批内身份尺不该跟着审美线一起走"


def test_no_live_workflow_uses_a_retired_task():
    """任何**还在跑**的链都不许引 auto／vl_aesthetic（桩只留给误用时报错）。

    ⚠ 按**结构**判，不扫字面量：`h3_i2va_video.yaml` 的 D20 退役注释里就写着
      `- task: vl_aesthetic`，扫文本会把它当成还在用（假阳）。同一个坑本仓记过
      （`test_batch_qc_wiring._code_only` 的注释里写着"刮字面量的尺子会被注释里的举例骗到"）。
    """
    import yaml

    for f in sorted(WORKFLOWS.glob("*.yaml")):
        if f.name == "auto_draft.yaml":
            continue                                   # 它自己就是桩
        d = yaml.safe_load(io.open(f, encoding="utf-8")) or {}
        kinds = {str(s.get("task")) for s in (d.get("steps") or []) if isinstance(s, dict)}
        assert "auto" not in kinds, "%s 还在跑已退役的 auto" % f.name
        assert "vl_aesthetic" not in kinds, "%s 还在跑已退役的 vl_aesthetic" % f.name


def test_webui_scoring_entry_fails_with_the_tombstone_not_import_error():
    """8787 面板的判分入口以前是 `from tasks import vl_score_image`——本体没了就会抛
       ImportError，看起来像"这个 UI 坏了"。桩要报的是"这条判分线被裁掉了＋替代是什么"。"""
    webui = pytest.importorskip("webui")
    with pytest.raises(RuntimeError) as e:
        webui.score_image("C:/不存在.png")
    assert "已退役" in str(e.value), str(e.value)
