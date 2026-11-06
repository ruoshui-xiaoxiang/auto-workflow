# -*- coding: utf-8 -*-
"""W0 隔离自身的验证（计划 §3-W0 的 V0 主体）：桩必须有牙、隔离 config 必须
指 tmp、子进程守卫必须生效、错输入在隔离下照旧被闸拦。

断言口径：
  · 计数桩记录的全是「拦截次数」—— 每个故障注入用例断言必抛 + 计数 +1；
  · 白名单只有 sys.executable 与子进程 echo 哨兵，两者各有一条放行用例；
  · isolated_config 的全部落盘键都在 tmp 下，feishu.push_gates 显式 "off"；
  · 子进程守卫用真子进程证明：触网/起白名单外进程 ⇒ 非零退出 + JSONL 有记录。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
TOOLS = ENGINE.parent / "tools"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TOOLS))

import tasks as T                      # noqa: E402
import _isolation                      # noqa: E402
from check_preflight import run_checks  # noqa: E402


# ---- 桩已就位 ----
def test_guards_are_installed():
    assert T.SESSION.__class__.__name__ == "_DeadSession"
    assert T.ensure_comfyui is _isolation._stub_ensure_comfyui
    assert T.send_media_to_feishu is _isolation._stub_send_media_to_feishu
    assert os.environ.get("AW_ISOLATED") == "1"
    assert os.environ.get("AW_CONFIG_PATH")


# ---- 故障注入：必抛 + 计数 +1 ----
def test_session_get_blocked_and_counted(iso):
    with pytest.raises(OSError):
        T.SESSION.get("http://127.0.0.1:8189/system_stats")
    assert (_isolation.COUNTERS.net_blocked
            == iso["before"]["net_blocked"] + 1)


def test_submit_to_prompt_blocked_and_counted(iso):
    with pytest.raises(OSError):
        T.SESSION.post("http://127.0.0.1:8189/prompt", json={})
    assert (_isolation.COUNTERS.submit_calls
            == iso["before"]["submit_calls"] + 1)


def test_popen_non_whitelist_blocked(iso):
    with pytest.raises(_isolation.IsolatedProcessError):
        subprocess.Popen(["cmd", "/c", "dir"])
    assert (_isolation.COUNTERS.popen_blocked
            == iso["before"]["popen_blocked"] + 1)


def test_popen_python_allowed(iso):
    r = subprocess.run([sys.executable, "-c", "print('ok')"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0 and "ok" in r.stdout
    assert (_isolation.COUNTERS.popen_allowed
            >= iso["before"]["popen_allowed"] + 1)


def test_feishu_send_blocked_and_counted(iso):
    with pytest.raises(OSError):
        T.send_media_to_feishu(iso["cfg"], [], [], "t", lambda m: None)
    assert (_isolation.COUNTERS.feishu_calls
            == iso["before"]["feishu_calls"] + 1)


def test_ensure_comfyui_blocked_and_counted(iso):
    with pytest.raises(_isolation.IsolatedProcessError):
        T.ensure_comfyui({"cfg": iso["cfg"]})
    assert (_isolation.COUNTERS.comfy_launch
            == iso["before"]["comfy_launch"] + 1)


def test_http_ok_returns_false_without_network(iso):
    """探活在隔离下恒 False，且不许真触网（SESSION 死桩兜底）。"""
    assert T.http_ok("http://127.0.0.1:8189/system_stats") is False


# ---- 隔离 config ----
def test_isolated_config_points_into_tmp(iso):
    cfg, tmp = iso["cfg"], iso["tmp"]
    for key in ("status_file", "log_dir", "output_root", "pool_root",
                "selftest_output_root", "play_output_root"):
        assert Path(cfg[key]).is_relative_to(tmp), f"{key} 没指进 tmp：{cfg[key]}"
    assert Path(cfg["paths"]["creation_root"]).is_relative_to(tmp)
    for key in ("output_dir", "input_dir", "log"):
        assert Path(cfg["comfyui"][key]).is_relative_to(tmp), \
            f"comfyui.{key} 没指进 tmp：{cfg['comfyui'][key]}"
    assert cfg["feishu"]["push_gates"] == "off"
    # 写出给子进程的副本与返回值同内容，且 AW_CONFIG_PATH 正指着它
    on_disk = yaml.safe_load(iso["cfg_path"].read_text(encoding="utf-8"))
    assert on_disk["status_file"] == cfg["status_file"]
    assert Path(os.environ["AW_CONFIG_PATH"]).resolve() == iso["cfg_path"].resolve()


# ---- 错输入：闸在隔离下照旧拦，且全程 0 网络 0 提交 ----
def test_wrong_input_blocked_by_preflight(iso):
    spec = {"refs": [], "prompt": "x", "prompt_kind": "h3_ref2va",
            "w": 864, "h": 1536, "length": 60, "provider": "local",
            "only": ["G6"], "output_root": str(iso["tmp"]), "project": "无音",
            "project_aliases": {"无音": ["wuyin", "无音"]}}
    rep = run_checks(spec)
    assert any(g == "G6" for _, g, _ in rep.errors), rep.render()
    cur = _isolation.COUNTERS.snapshot()
    assert cur["submit_calls"] == iso["before"]["submit_calls"]
    assert cur["feishu_calls"] == iso["before"]["feishu_calls"]


# ---- 子进程守卫（sitecustomize_iso 经 PYTHONPATH 自动激活）----
def _child_jsonl_delta(before):
    log = Path(os.environ["AW_ISOLATED_LOG"])
    after = log.read_text(encoding="utf8") if log.exists() else ""
    return [json.loads(x) for x in after[len(before):].splitlines() if x.strip()]


def _log_now():
    log = Path(os.environ["AW_ISOLATED_LOG"])
    return log.read_text(encoding="utf8") if log.exists() else ""


def test_child_guard_blocks_network(iso):
    before = _log_now()
    code = ("import urllib.request;"
            "urllib.request.urlopen('http://127.0.0.1:8189/', timeout=2)")
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode != 0, f"子进程触网竟成功：{r.stdout[-200:]}"
    assert any(rec.get("kind") == "net" for rec in _child_jsonl_delta(before)), \
        "子进程触网被拦但 JSONL 无记录"


def test_child_guard_blocks_foreign_popen(iso):
    before = _log_now()
    code = ("import subprocess;"
            "subprocess.Popen(['cmd', '/c', 'dir'])")
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode != 0, f"子进程起了白名单外进程：{r.stdout[-200:]}"
    assert any(rec.get("kind") == "popen_block"
               for rec in _child_jsonl_delta(before))


def test_child_echo_sentinel_allowed(iso):
    """selftest_gates 的 after 步（t_shell 跑 echo）在子进程里必须能走。"""
    before = _log_now()
    code = ("import subprocess;"
            "r = subprocess.run('echo sentinel_ok', shell=True,"
            "                   capture_output=True, text=True,"
            "                   encoding='utf-8', errors='replace');"
            "assert r.returncode == 0 and 'sentinel_ok' in r.stdout")
    r = subprocess.run([sys.executable, "-c", code],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"echo 哨兵在子进程被误拦：{r.stderr[-300:]}"
    assert any(rec.get("kind") == "popen_allow"
               for rec in _child_jsonl_delta(before))
