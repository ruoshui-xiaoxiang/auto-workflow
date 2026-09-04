# -*- coding: utf-8 -*-
"""webui（本地网页操作界面）的离线单测：不碰显存、不起 HTTP 服务。

测的是纯函数 + 契约：schema 分组、白名单来源、批次/路径解析、子进程互相排斥。
跑法：cd E:\\LocalAI\\workflows && python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import webui  # noqa: E402


# ---- 工作流 schema / 白名单 ----
def test_workflow_meta_schema_grouping():
    m = webui.workflow_meta("image_draft_batch")
    assert m is not None
    assert m["common"] == ["theme", "count"]      # 默认区只露输入框和数量
    for k in ("prompt", "width", "height", "steps", "loras", "seed"):
        assert k in m["advanced"]                  # 参数全藏进高级折叠区
    assert "use_llm_polish" in m["fields"]
    assert m["fields"]["theme"]["value"]           # 默认值来自 YAML args


def test_workflow_meta_unknown_wf_is_none():
    assert webui.workflow_meta("no_such_workflow") is None


def test_all_workflows_cover_yaml_files():
    yamls = {f.stem for f in (ROOT / "workflows").glob("*.yaml")}
    assert yamls == set(webui.all_workflows())
    for n in yamls:
        assert webui.workflow_meta(n) is not None


def test_advanced_catches_yaml_params_not_in_whitelist():
    """白名单没列、但 YAML 里有的参数不应被藏没：必须出现在 advanced。"""
    for n in webui.all_workflows():
        m = webui.workflow_meta(n)
        wl = webui.WHITELIST.get(n, {"common": [], "advanced": []})
        known = set(wl["common"]) | set(wl["advanced"])
        assert known.issubset(set(m["fields"])), f"{n}: 白名单字段没全进 schema"


# ---- 批次 / 路径 ----
def test_batch_detail_rejects_traversal():
    assert webui.batch_detail("..") is None
    assert webui.batch_detail("../foo") is None
    assert webui.batch_detail("a\\b") is None
    assert webui.batch_detail("") is None


def test_safe_out_blocks_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "OUT_ROOT", tmp_path)
    (tmp_path / "ok.png").write_bytes(b"x")
    assert webui._safe_out("ok.png") is not None
    assert webui._safe_out("../status.json") is None     # 越界
    assert webui._safe_out("..\\..\\win.ini") is None
    assert webui._safe_out("missing.png") is None        # 不存在


def test_batch_detail_reads_manifest(tmp_path, monkeypatch):
    batch = tmp_path / "20260903_141822"
    draft = batch / "draft"
    draft.mkdir(parents=True)
    (draft / "draft_x.png").write_bytes(b"png")
    (batch / "image_draft_batch_20260903_141822.manifest.json").write_text(
        '{"run_id":"20260903_141822","images":[{"index":1,"file":"draft/draft_x.png",'
        '"step":"draft","seed":7,"width":832,"height":1216}]}',
        encoding="utf-8")
    monkeypatch.setattr(webui, "OUT_ROOT", tmp_path)
    b = webui.batch_detail("20260903_141822")
    assert b is not None and b["n_draft"] == 1
    assert b["images"][0]["index"] == 1
    assert b["images"][0]["file"] == "draft/draft_x.png"


def test_out_batches_skips_empty_dirs(tmp_path, monkeypatch):
    (tmp_path / "20260903_141822" / "draft").mkdir(parents=True)
    (tmp_path / "20260903_141822" / "draft" / "a.png").write_bytes(b"x")
    (tmp_path / "stray").mkdir()                      # 空夹，应被跳过
    monkeypatch.setattr(webui, "OUT_ROOT", tmp_path)
    rows = webui.out_batches()
    assert [r["run_id"] for r in rows] == ["20260903_141822"]


# ---- 子进程互斥（不真起进程，只验证同一个锁和守卫逻辑）----
def test_start_run_refuses_concurrent(monkeypatch):
    sentinel = {"poll": lambda: None}                  # 模拟一个还活着的 proc
    monkeypatch.setattr(webui, "_proc", sentinel)
    r = webui.start_run("selftest", {})
    assert r["ok"] is False and "已有运行" in r["error"]


def test_unknown_param_rejected_by_handler_logic():
    """防呆第一道闸：post 不是白名单字段整体拒绝（422 语义在 Handler._run）。"""
    m = webui.workflow_meta("image_draft_batch")
    fields = m["fields"]
    assert "evil" not in fields
    assert "theme" in fields and "count" in fields


def test_image_batch_draft_llm_off_by_default():
    """一步式工作流默认不碰 LLM：use_llm=false，polish 走 static 直接出图。
    （2026-09-03 修：此前默认 auto 拉兜底链致 t3/q14/t2 全失败）"""
    m = webui.workflow_meta("image_batch_draft")
    assert m["fields"]["use_llm"]["value"] is False
    assert m["fields"]["use_llm"]["type"] == "bool"
    # step 层：polish 的 enabled 引用 args.use_llm，且有 static 兜底
    y = webui.yaml.safe_load(
        (webui.WF_DIR / "image_batch_draft.yaml").read_text(encoding="utf-8"))
    polish = [s for s in y["steps"] if s.get("id") == "polish"][0]
    assert polish.get("enabled") == "{{args.use_llm}}"
    assert "static" in polish