# -*- coding: utf-8 -*-
"""端到端：人工关口停住 → 本地待批清单 → 一键批准 → 续跑，全程不许污染交付根。

用 subprocess 真跑引擎（selftest_gates 不碰显存、不调模型、不出图），
因为"自测落点"这类 bug 只有在真走 main() 的参数解析顺序时才会暴露
（2026-09-20 就真出过：一键批准改了 a.workflow 却没重算 is_selftest，
 自测续跑的报告写进了 E:\\图像影音资源池\\无音\\批次）。
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import yaml

ENGINE = Path(r"D:\AIWorkflow\engine")
ROOT = ENGINE
# W0 隔离：conftest 已把 AW_CONFIG_PATH 指到 session tmp 的隔离 config（status/审批/
# 落点全在 tmp，feishu.push_gates=off），本文件不再直接读真 config.yaml——真跑
# run.py 的子进程也经 _load_cfg() 读这同一个隔离副本，全链路不碰真台账。
CFG = yaml.safe_load(Path(os.environ["AW_CONFIG_PATH"]).read_text(encoding="utf8"))
STATUS = Path(CFG["status_file"])
NOTE = Path(CFG["log_dir"]) / "待批关口.txt"
SELF_ROOT = Path(CFG["selftest_output_root"])
APPROVALS = Path(CFG["log_dir"]) / "gate_approvals.json"


def _run(*args):
    return subprocess.run([sys.executable, "run.py", *args], cwd=str(ENGINE),
                          capture_output=True, text=True, encoding="utf8",
                          errors="replace", timeout=240)


def _pngs(tmp_path, n=4):
    import cv2
    import numpy as np
    out = []
    for i in range(n):
        p = tmp_path / f"anchor_{i}.png"
        ok, buf = cv2.imencode(".png", np.full((64, 48, 3), i * 30, dtype=np.uint8))
        assert ok
        p.write_bytes(buf.tobytes())
        out.append(str(p))
    return out


def test_gate_stop_and_one_click_resume(tmp_path):
    theme = f"自测 {uuid.uuid4().hex[:8]}"
    refs = ",".join(_pngs(tmp_path))
    started = time.time()

    r1 = _run("selftest_gates", "--set", f"theme={theme}", "--set", f"refs={refs}",
              "--set", f"shot_png={tmp_path / 'anchor_0.png'}")
    assert r1.returncode == 3, f"应停在人工关口（退出码 3），实得 {r1.returncode}：{r1.stdout[-400:]}"

    entry = json.loads(STATUS.read_text(encoding="utf8"))["last_run"]
    assert entry["status"] == "awaiting_human", entry
    assert entry["workflow"] == "selftest_gates"
    assert Path(entry["report"]).is_relative_to(SELF_ROOT), \
        f"自测报告写到了交付根：{entry['report']}"
    assert any(s["id"] == "H3" and s["status"] == "awaiting_human" for s in entry["steps"])
    assert NOTE.is_file() and theme in NOTE.read_text(encoding="utf8"), "待批清单没落地"

    data = json.loads(APPROVALS.read_text(encoding="utf8"))
    pend = [k for k, m in data["pending"].items()
            if m.get("run_id") == entry["run_id"]]
    assert len(pend) == 1, f"待批记录异常：{pend}"

    r2 = _run("--approve-and-resume")
    assert r2.returncode == 0, f"一键批准续跑失败：{r2.stdout[-400:]}{r2.stderr[-300:]}"
    assert "已批准" in r2.stdout

    entry2 = json.loads(STATUS.read_text(encoding="utf8"))["last_run"]
    assert entry2["run_id"] == entry["run_id"], "续跑必须回到同一次运行"
    assert entry2["status"] == "success", entry2
    assert Path(entry2["report"]).is_relative_to(SELF_ROOT), entry2["report"]
    st = {s["id"]: s["status"] for s in entry2["steps"]}
    restored = {s["id"]: s.get("restored") for s in entry2["steps"]}
    # 计划 W5a：--resume 已成功步骤不再标 skipped，而是 done + restored=true
    # status.json steps 每条显式带 restored 布尔（run.py status_extra）
    assert st["pre"] == "done", f"已完成的步骤续跑后应显式 done（restored），不该重跑也不该伪装 skipped：{st}"
    assert restored["pre"] is True, f"pre 步骤续跑后 restored 应为 True：{restored}"
    assert st["H3"] == "done" and st["after"] == "done", st
    assert restored["H3"] is False and restored["after"] is False, restored

    data2 = json.loads(APPROVALS.read_text(encoding="utf8"))
    assert not [k for k, m in data2["pending"].items()
                if m.get("run_id") == entry["run_id"]], "批准后 pending 必须清掉"
    assert any(m.get("run_id") == entry["run_id"] for m in data2["approved"].values())
    assert time.time() - started < 200, "自测不该变慢"
