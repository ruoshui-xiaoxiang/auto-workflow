# -*- coding: utf-8 -*-
"""workflow 阶段事件：给实时面板用的结构化输出。"""
import time

from fanxing.workflow import _event, _stage, _skipped


def test_stage_emits_start_end_fields():
    events = []
    _stage([], "precheck", "ok", _t0=time.time() - 0.05,
           summary="0 error", on_event=events.append)
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "stage"
    assert ev["stage"] == "precheck"
    assert ev["status"] == "ok"
    assert ev["summary"] == "0 error"
    assert ev["duration_s"] >= 0
    assert ev["at"]


def test_skipped_emits_reason():
    events = []
    _skipped([], "run", "未显式 --execute-run", on_event=events.append)
    assert events[0]["type"] == "stage"
    assert events[0]["status"] == "skipped"
    assert "execute-run" in events[0]["reason"]


def test_event_swallows_callback_errors():
    def boom(_ev):
        raise RuntimeError("ui died")

    # 回调故障不能把生产流程带崩
    _event(boom, type="stage", stage="qc", status="running")
