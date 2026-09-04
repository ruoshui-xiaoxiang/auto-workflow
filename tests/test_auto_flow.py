# -*- coding: utf-8 -*-
"""auto（闭环自动出图）任务的离线单测：不碰 GPU / 不调云端。

用 monkeypatch 假 t_llm / t_comfyui / vl_score_image 驱动 t_auto 的循环逻辑：
阈值短路、带反馈改写、轮尽返回最优、判分失败降级。
跑法：cd E:\\LocalAI\\workflows && python -m pytest tests -q
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tasks  # noqa: E402

# 保存原始 vl_score_image，避免被 _fake_backend 污染
_original_vl_score_image = tasks.vl_score_image


def _ctx():
    return {"cfg": {"log_dir": str(ROOT / "logs" / "workflows")}, "run_id": "x",
            "args": {}, "log": lambda m: None, "wf_root": str(ROOT)}


def _fake_backend(call_log, scores_by_round, prompt_for_round):
    """构造假后端：t_llm 返回设定提示词；t_comfyui 产出假文件；vl 按轮返回分数。

    scores_by_round: {round_no: [score,...]} 决定每轮分数。
    """
    import tasks as T

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        def __call__(self, p, ctx):
            self.calls += 1
            rnd = self.calls
            call_log.append(("llm", rnd, str(p.get("prompt", ""))[:40]))
            return {"text": prompt_for_round.get(rnd, f"prompt-{rnd}"), "backend": "cloud"}

    fake_llm = FakeLLM()

    def fake_comfyui(p, ctx):
        n = int(p.get("count", 1))
        files = [str(ROOT / "tmp" / f"img_r{p.get('seed','0')}_{i}.png") for i in range(n)]
        return {"files": files, "count": n}

    fake_vl = FakeVL(scores_by_round)

    T.t_llm = fake_llm
    T.t_comfyui = fake_comfyui
    T.vl_score_image = fake_vl.call
    return fake_llm, fake_vl


class FakeVL:
    """按调用次数（=轮次）返回分数。scores 耗尽后重复最后一个。"""

    def __init__(self, scores_by_round):
        self.scores_by_round = scores_by_round
        self.calls = 0

    def call(self, path):
        self.calls += 1
        arr = self.scores_by_round.get(self.calls, [60])
        s = arr[0]
        return {"score": s, "dims": {"face": s // 4, "compose": s // 4,
                                     "quality": s // 4, "mood": s // 4},
                "reasons": [f"round{self.calls}-issue"], "suggestion": "fix"}


def _rewire(scores_by_round, prompt_for_round=None):
    call_log = []
    fake_llm, fake_vl = _fake_backend(call_log, scores_by_round,
                                      prompt_for_round or {})
    params = {"theme": "古风御姐", "prompt": "", "count": 1, "width": 832,
              "height": 1216, "steps": 12, "workflow": "comfy/draft_flux_api.json",
              "threshold": 78, "max_tries": 3, "backend": "cloud"}
    out = tasks.t_auto(params, _ctx())
    return out, call_log, fake_llm, fake_vl


def test_auto_first_round_hits_threshold_short_circuits():
    """第 1 轮 85 分 >= 78 → 只跑 1 轮、直接接收。"""
    out, log, llm, vl = _rewire({1: [85]})
    assert out["scores"] == [85]
    assert len(out["rounds"]) == 1
    assert llm.calls == 1 and vl.calls == 1


def test_auto_retries_on_low_score_with_feedback():
    """第 1 轮 65（低）→ 第 2 轮 90（达标）：应跑 2 轮，
    且第 2 轮 prompt 的构造包含上轮理由（带反馈改写）。"""
    prompts = {1: "init-prompt", 2: "rewritten-prompt"}
    out, log, llm, vl = _rewire({1: [65], 2: [90]}, prompts)
    assert len(out["rounds"]) == 2
    assert out["rounds"][1]["score"] == 90
    assert out["scores"] == [90]
    # 第 2 轮的 LLM 输入必须带上轮判分理由（反馈回路）
    llm_prompt2 = log[1][2]
    assert "round1-issue" in llm_prompt2 or "扣分" in llm_prompt2


def test_auto_exhausts_tries_returns_best_round():
    """三轮全低分（65/70/72）→ 轮尽结束，返回最高分那轮产物。"""
    out, log, llm, vl = _rewire({1: [65], 2: [70], 3: [72]})
    assert len(out["rounds"]) == 3
    assert out["scores"] == [72]          # 取最好轮
    assert llm.calls == 3


def test_auto_keeps_user_prompt_without_llm_when_given():
    """给了 prompt 时第 1 轮不调 LLM（直接用用户提示词）；第 2 轮低分才改写。"""
    params = {"theme": "x", "prompt": "my english prompt", "count": 1,
              "threshold": 78, "max_tries": 2, "backend": "cloud"}
    call_log = []
    llm, vl = _fake_backend(call_log, {1: [60], 2: [90]}, {1: "rewrite"})
    out = tasks.t_auto(params, _ctx())
    # 第 1 轮 prompt 给定 → 不调 LLM；第 2 轮低分 → 调了 1 次
    assert llm.calls == 1
    assert out["rounds"][0]["prompt"] == "my english prompt"
    assert out["rounds"][1]["prompt"] == "rewrite"


def test_vl_missing_key_fails_loud(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, "VL_KEY_FILE", tmp_path / "no_such_keyfile.txt")
    monkeypatch.delenv("AW_VL_API_KEY", raising=False)
    fake_img = tmp_path / "fake.png"
    fake_img.write_bytes(b"fake")
    with pytest.raises(RuntimeError, match="多模态"):
        _original_vl_score_image(str(fake_img))


def test_vl_missing_file_fails_loud():
    with pytest.raises(RuntimeError, match="不存在"):
        _original_vl_score_image("/no/such/image.png")


def test_auto_vl_mode_rewrites_directly(monkeypatch):
    """rewrite_mode=vl：第2轮 VL 看图+读提示词直接改写（不调文本 LLM）。"""
    import tasks as T

    llm_calls = {"n": 0}
    vl_log = []

    def fake_llm(p, ctx):
        llm_calls["n"] += 1
        return {"text": "init-by-llm", "backend": "cloud"}

    def fake_comfyui(p, ctx):
        return {"files": [f"C:/fake/img_{llm_calls['n']}_{len(vl_log)}.png"], "count": 1}

    def fake_vl(path, **kw):
        vl_log.append((path, kw.get("rewrite_prompt")))
        if len(vl_log) == 1:      # 第1轮纯判分：低分触发重试
            return {"score": 60, "reasons": ["hands blurry"]}
        return {"score": 90, "reasons": [], "new_prompt": "fixed-prompt"}  # 第2轮带改写

    monkeypatch.setattr(T, "t_llm", fake_llm)
    monkeypatch.setattr(T, "t_comfyui", fake_comfyui)
    monkeypatch.setattr(T, "vl_score_image", fake_vl)

    params = {"theme": "古风御姐", "prompt": "", "count": 1, "width": 832,
              "height": 1216, "steps": 12, "workflow": "comfy/draft_flux_api.json",
              "threshold": 78, "max_tries": 3, "backend": "cloud",
              "rewrite_mode": "vl"}
    out = tasks.t_auto(params, _ctx())

    assert len(out["rounds"]) == 2
    # 第1轮 prompt 由文本 LLM 生成；第2轮由 VL 直改，不再调文本 LLM
    assert llm_calls["n"] == 1
    assert out["rounds"][1]["prompt"] == "fixed-prompt"
    # 第2轮的 VL 调用确实带上了 rewrite_prompt（看图+当前提示词）
    assert vl_log[1][1] is not None
