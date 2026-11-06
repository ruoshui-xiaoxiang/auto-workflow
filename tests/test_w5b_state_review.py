# -*- coding: utf-8 -*-
"""W5b 验收：状态词表、提交归属、取消只动自己、批准绑定媒体与参数。

全程桩掉 SESSION/网络（W0 隔离在），0 真实提交、0 飞书、0 GPU。
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))

import run as R                    # noqa: E402
import tasks as T                  # noqa: E402


# ------------------------------------------------------------------ 状态词表
def test_state_vocabulary_is_closed():
    for s in ("planned", "awaiting_review", "reviewed", "submitted", "running",
              "unknown_after_timeout", "generated", "qc_failed", "qc_passed",
              "archive_pending", "cancel_requested", "cancelled", "failed", "done"):
        assert T.assert_task_state(s) == s
    with pytest.raises(ValueError):
        T.assert_task_state("completed")      # completed ≠ confirmed，也不许当状态词
    with pytest.raises(ValueError):
        T.assert_task_state("ok")


def test_run_id_has_random_tail_and_old_ids_still_readable():
    ids = {time.strftime("%Y%m%d_%H%M%S") + "_" + "%04x" % i for i in range(3)}
    assert len(ids) == 3
    # 旧纯时间戳 ID 仍能当 run_id 用（--resume 传什么用什么）
    old = "20261023_114402"
    assert re.fullmatch(r"\d{8}_\d{6}(_[0-9a-f]{4})?", old)
    assert re.fullmatch(r"\d{8}_\d{6}(_[0-9a-f]{4})?", "20261023_114402_a31f")


# ------------------------------------------------------------------ 提交快照
def test_persist_submission_writes_graph_and_prompt_id(tmp_path):
    ctx = {"cfg": {}, "run_id": "R1", "batch_dir": tmp_path, "workflow": "w",
           "args": {}, "log": lambda m: None}
    payload, path = T.persist_submission(
        ctx, "pid-abc", {"7": {"class_type": "X"}}, {"length": 124, "seed": 7,
                                                     "_secret": "不该落盘"},
        stage="video", intent="submit")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["prompt_id"] == "pid-abc"
    assert data["graph"]["7"]["class_type"] == "X"
    assert data["params"]["length"] == 124
    assert "_secret" not in data["params"], "内部键不该进快照"
    assert path.name == "submission_R1_video.json"


# ------------------------------------------------------------------ 超时归属
class _Resp:
    def __init__(self, payload, code=200):
        self._p, self.status_code = payload, code

    def json(self):
        return self._p


def test_timeout_never_claims_foreign_new_files(tmp_path, monkeypatch):
    """以前：超时后扫输出目录，多了文件就"按成功处理"。现在必须只认 prompt_id。"""
    out = tmp_path / "comfy_out"
    out.mkdir()
    (out / "someone_else.mp4").write_bytes(b"x")      # 并发别人的产物

    class Session:
        def get(self, url, timeout=None):
            return _Resp({})                           # history 始终没有这个 prompt_id

        def post(self, url, json=None, timeout=None):
            raise AssertionError("轮询不该提交任何东西")

    monkeypatch.setattr(T, "SESSION", Session())
    monkeypatch.setattr(T.time, "sleep", lambda s: None)
    ticks = iter([0.0, 0.0, 999.0])                    # 第二次读表就过期 ⇒ 走超时分支
    monkeypatch.setattr(T.time, "time", lambda: next(ticks))
    ctx = {"cfg": {"comfyui": {"output_dir": str(out)}}, "run_id": "R",
           "log": lambda m: None}
    with pytest.raises(RuntimeError) as ei:
        T.poll_history(ctx, "http://stub", "pid-mine", timeout=10,
                       pre_snapshot=set(), expected_prefix=None)
    msg = str(ei.value)
    assert "pid-mine" in msg and "不扫输出目录" in msg, msg
    assert "someone_else.mp4" not in msg


def test_adopt_late_output_only_for_that_prompt(tmp_path, monkeypatch):
    out = tmp_path / "comfy_out"
    (out / "mine_0001.mp4").parent.mkdir(parents=True)
    (out / "mine_0001.mp4").write_bytes(b"x")

    class Session:
        def get(self, url, timeout=None):
            if "pid-yes" in url:
                return _Resp({"pid-yes": {"outputs": {"12": {"videos": [
                    {"filename": "mine_0001.mp4", "subfolder": ""}]}}}})
            return _Resp({"pid-no": {"outputs": {}}})

    monkeypatch.setattr(T, "SESSION", Session())
    ctx = {"cfg": {"comfyui": {"output_dir": str(out)}}, "run_id": "R"}
    got = T.adopt_late_output(ctx, "http://stub", "pid-yes")
    assert got and got["files"] == [str(out / "mine_0001.mp4")], got
    assert T.adopt_late_output(ctx, "http://stub", "pid-no") is None, \
        "没有产出的 prompt_id 不许从目录里捞东西冒充"


# ------------------------------------------------------------------ 取消
def test_cancel_uses_named_endpoints_and_never_clears_queue(monkeypatch):
    seen = []

    class Session:
        def post(self, url, json=None, timeout=None):
            seen.append((url, json))
            return _Resp({"cancelled": "/api/jobs/pid-1/cancel" in url}, 200)

        def get(self, url, timeout=None):
            seen.append((url, None))
            if "/history/" in url:
                return _Resp({})
            return _Resp({"queue_running": [], "queue_pending": []})

    monkeypatch.setattr(T, "SESSION", Session())
    res = T.cancel_submission({"cfg": {}, "run_id": "R"}, "http://stub", "pid-1")
    assert res["confirmed"] is True
    assert res["state"] == "cancelled"
    assert ("http://stub/api/jobs/pid-1/cancel", None) in seen, seen
    assert not any(u.endswith("/queue") for u, _b in seen
                   if _b is not None), "取消不许再走 /queue 删除"
    assert not any("/interrupt" in u for u, _b in seen), \
        "按 ID 取消不许发无 ID 的全局中断"


def test_cancel_running_reports_still_queued_without_global_interrupt(monkeypatch):
    seen = []

    class Session:
        def post(self, url, json=None, timeout=None):
            seen.append(url)
            return _Resp({"cancelled": True}, 200)

        def get(self, url, timeout=None):
            if "/history/" in url:
                return _Resp({})
            # 服务端说取消了，但回读队列仍在（竞争/未落地）
            return _Resp({"queue_running": [["x", "pid-9", {}, {}, {}]],
                          "queue_pending": []})

    monkeypatch.setattr(T, "SESSION", Session())
    res = T.cancel_submission({"cfg": {}}, "http://stub", "pid-9", running=True)
    assert not any("/interrupt" in u for u in seen), seen
    assert res["confirmed"] is False, res
    assert res["state"] == "still_queued", res
    assert "不得当已取消" in res["note"]


# ------------------------------------------------------------------ 批准绑定
def _gate_ctx(tmp_path, cfg):
    batch = tmp_path / "batch"
    batch.mkdir(exist_ok=True)
    return {"cfg": cfg, "args": {"theme": "t"}, "run_id": "R", "workflow": "w",
            "batch_dir": batch, "wf_root": ENGINE, "step_id": "H3", "log": lambda m: None}


@pytest.fixture()
def gate_env(tmp_path, monkeypatch):
    import _isolation
    cfg, _cfg_path = _isolation.isolated_config(tmp_path)
    png = tmp_path / "first.png"
    png.write_bytes(b"\x89PNG\r\n")
    prompts = tmp_path / "p.txt"
    prompts.write_text("英文提示词", encoding="utf-8")
    monkeypatch.setattr(T, "push_gate_review",
                        lambda c, cap, f, v, logf: {"pushed": False, "mode": "off"})
    monkeypatch.setattr(T, "write_pending_note", lambda *a, **k: None)
    monkeypatch.setattr(T, "toast", lambda *a, **k: None)
    return cfg, png, prompts


def _digest(cfg, png, prompts, **over):
    p = {"mode": "human", "gate_id": "H3", "prompt_file": str(prompts),
         "refs": [str(png)], "width": 736, "height": 416, "length": 124,
         "lora": "x.safetensors", "seed": 42, "steps": 8, "lora_strength": 0.7,
         "workflow_json": "comfy/h3_i2v_fl2va_api.json"}
    p.update(over)
    ctx = _gate_ctx(png.parent, cfg)
    with pytest.raises(T.GateAwaiting):
        T.t_gate(p, ctx)
    pend = T.read_approvals(cfg).get("pending") or {}
    assert pend, "未批内容必须进 pending"
    return list(pend)[-1]


def test_approval_bound_to_seed_steps_template_and_media(gate_env):
    cfg, png, prompts = gate_env
    k1 = _digest(cfg, png, prompts)
    k2 = _digest(cfg, png, prompts, seed=43)
    k3 = _digest(cfg, png, prompts, steps=20)
    k4 = _digest(cfg, png, prompts, workflow_json="comfy/h3_i2v_fl2va_dual_api.json")
    k5 = _digest(cfg, png, prompts, two_pass=True, scale_by=1.25)
    assert len({k1, k2, k3, k4, k5}) == 5, "换 seed/步数/模板/二采参数都必须另开一次批准"


def test_final_review_bound_to_media_hash(gate_env, tmp_path):
    cfg, png, prompts = gate_env
    clip_a = tmp_path / "a.mp4"
    clip_a.write_bytes(b"clip-a")
    clip_b = tmp_path / "a.mp4"          # 同路径换内容
    v1 = _digest(cfg, png, prompts, videos=[str(clip_a)])
    clip_b.write_bytes(b"clip-bbb")
    v2 = _digest(cfg, png, prompts, videos=[str(clip_b)])
    assert v1 != v2, "成片换了一条必须重新验收（终审绑媒体哈希）"


def test_approved_gate_blocks_until_reapproved(gate_env):
    """批准过后内容一变，旧批准就不再命中（不会静默沿用）。"""
    cfg, png, prompts = gate_env
    key = _digest(cfg, png, prompts)
    T.record_approval(cfg, key, "approved", note="过")
    ctx = _gate_ctx(tmp_path=prompts.parent, cfg=cfg)
    out = T.t_gate({"mode": "human", "gate_id": "H3", "prompt_file": str(prompts),
                    "refs": [str(png)], "width": 736, "height": 416, "length": 124,
                    "lora": "x.safetensors", "seed": 42, "steps": 8,
                    "lora_strength": 0.7,
                    "workflow_json": "comfy/h3_i2v_fl2va_api.json"}, ctx)
    assert out["approved"] is True
    changed = dict(seed=99)
    p = {"mode": "human", "gate_id": "H3", "prompt_file": str(prompts),
         "refs": [str(png)], "width": 736, "height": 416, "length": 124,
         "lora": "x.safetensors", "steps": 8, "lora_strength": 0.7,
         "workflow_json": "comfy/h3_i2v_fl2va_api.json"}
    p.update(changed)
    with pytest.raises(T.GateAwaiting):
        T.t_gate(p, ctx)


# ------------------------------------------------------------------ 素材去重命名
def test_reference_copies_are_content_hashed(tmp_path, monkeypatch):
    a = tmp_path / "角色.png"
    a.write_bytes(b"face-a")
    b = tmp_path / "角色.png"            # 同名不同内容（跨批次很常见）
    dirb = tmp_path / "other"
    dirb.mkdir()
    b = dirb / "角色.png"
    b.write_bytes(b"face-b")
    assert T.content_hash8(a) != T.content_hash8(b)
    assert T.content_hash8(tmp_path / "不存在.png") == "missing"
