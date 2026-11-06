# -*- coding: utf-8 -*-
"""W0 测试隔离设施：计数桩 + 隔离 config（计划 §3-W0 的父进程那半）。

目标：
  · 真实网络 0、真实生成提交 0、飞书发送 0、ComfyUI 启动 0 —— 用计数桩证明；
  · config.yaml 的 status/审批/落点/自测根/ComfyUI 出入目录 全部指到 tmp；
  · feishu.push_gates 显式 off（不靠环境变量 dry）；
  · 禁真实子进程（白名单：sys.executable；shell=True 的 echo 哨兵——
    selftest_gates 的 after 步是 `echo …`，e2e 靠它证明续跑走下去了）；
  · 子进程那半在 sitecustomize_iso/sitecustomize.py（PYTHONPATH 自动激活）。

计数语义：只记「被拦/被桩的次数」；放行的只有白名单进程，另计 popen_allowed。
验收口径（V0-2）：跑完全部测试后 net/submit/feishu/comfy_launch/popen_blocked
里的「成功真实调用」恒为 0 —— 这些计数器记录的全部是「拦截」。
"""
import copy
import os
import socket
import subprocess
import sys
from pathlib import Path

import yaml

ENGINE = Path(__file__).resolve().parent.parent


class IsolatedNetworkError(OSError):
    """测试隔离：任何真实网络连接（含 127.0.0.1）一律拦。OSError 子类，
    requests/urllib3 与 tasks.http_ok 的宽捕获都能安全接住。"""


class IsolatedProcessError(RuntimeError):
    """测试隔离：白名单外的子进程不许起。"""


class Counters:
    """隔离计数。全部为「拦截次数」——验收时任何一项增长都代表
    有代码试图越界并被按住；不存在「成功真实调用」这个维度。"""

    def __init__(self):
        self.net_blocked = 0     # socket 层拦下的连接尝试
        self.submit_calls = 0    # 其中打到 ComfyUI /prompt（生成提交）的
        self.popen_blocked = 0   # 白名单外被拦的子进程
        self.popen_allowed = 0   # 白名单内放行的（sys.executable / echo 哨兵）
        self.feishu_calls = 0    # 打到 send_media_to_feishu 的（全拦）
        self.comfy_launch = 0    # 打到 ensure_comfyui 的（全拦）

    def snapshot(self):
        return dict(vars(self))


COUNTERS = Counters()


# ---------------------------------------------------------------- 网络桩
def _net_bork(*a, **kw):
    COUNTERS.net_blocked += 1
    raise IsolatedNetworkError(f"测试隔离：禁止真实网络连接 {str(a)[:120]}")


class _DeadSession:
    """替换 tasks.SESSION：get/post/request 计数即抛。
    tasks.http_ok 宽捕获 Exception ⇒ 探活恒 False；提交生成必被拦。
    monkeypatch 兼容：test_gates_phase3 打 SESSION.get、test_quality_gates
    patch SESSION.post、test_no_size_fallback 整体换 SESSION —— 三种现役写法
    打在实例/模块属性上，与本桩互不冲突。"""

    trust_env = False

    def get(self, url, *a, **kw):
        COUNTERS.net_blocked += 1
        raise IsolatedNetworkError(f"测试隔离：SESSION.get 被拦 {url}")

    def post(self, url, *a, **kw):
        COUNTERS.net_blocked += 1
        if "/prompt" in str(url):
            COUNTERS.submit_calls += 1
        raise IsolatedNetworkError(f"测试隔离：SESSION.post 被拦 {url}")

    def request(self, method, url, *a, **kw):
        COUNTERS.net_blocked += 1
        raise IsolatedNetworkError(f"测试隔离：SESSION.request({method}) 被拦 {url}")


# ---------------------------------------------------------------- 子进程桩
_RealPopen = subprocess.Popen


def _is_python_exe(args):
    exe = args[0] if isinstance(args, (list, tuple)) else args
    try:
        return os.path.normcase(str(exe)) == os.path.normcase(sys.executable)
    except Exception:
        return False


def _is_echo_shell(args, kw):
    """唯一的非 python 放行：shell=True 且命令体是 echo 哨兵。
    t_shell 以 subprocess.run('echo …', shell=True) 跑 selftest_gates 的 after 步，
    e2e 要靠它证明续跑真的走下去了；除此之外的 shell 命令一律拦。"""
    return (bool(kw.get("shell")) and isinstance(args, str)
            and args.lstrip().lower().startswith("echo "))


def _guarded_popen(args, *a, **kw):
    if _is_python_exe(args) or _is_echo_shell(args, kw):
        COUNTERS.popen_allowed += 1
        return _RealPopen(args, *a, **kw)
    COUNTERS.popen_blocked += 1
    raise IsolatedProcessError(f"测试隔离：白名单外子进程被拦 {str(args)[:160]}")


# ---------------------------------------------------------------- tasks 桩
def _stub_ensure_comfyui(ctx, relay=False):
    COUNTERS.comfy_launch += 1
    raise IsolatedProcessError("测试隔离：禁止探活/拉起 ComfyUI（ensure_comfyui 被桩）")


def _stub_send_media_to_feishu(cfg, files, videos, caption, log, **kw):
    COUNTERS.feishu_calls += 1
    raise IsolatedNetworkError("测试隔离：禁止飞书发送（send_media_to_feishu 被桩）")


# ---------------------------------------------------------------- 隔离 config
def isolated_config(tmp_root):
    """深拷贝真 config.yaml，把所有会落盘的键指到 tmp_root，飞书推送显式 off。

    output_root 仍按 pool\\<project>\\<batch_subdir> 的形状派生：delivery_root /
    G11 会校验落点含当前 project，拍平成 tmp\\output 会被判串项目。

    返回 (cfg_dict, yaml_path)。yaml_path 是写出的隔离副本，给子进程
    AW_CONFIG_PATH 用（run.py 的 _load_cfg 读它）。
    """
    tmp_root = Path(tmp_root)
    cfg = yaml.safe_load((ENGINE / "config.yaml").read_text(encoding="utf-8"))
    cfg = copy.deepcopy(cfg)
    logs = tmp_root / "logs"
    cfg["status_file"] = str(tmp_root / "status.json")
    cfg["log_dir"] = str(logs)
    cfg["pool_root"] = str(tmp_root / "pool")
    cfg["output_root"] = str(tmp_root / "pool" / cfg.get("project", "无音")
                            / cfg.get("batch_subdir", "批次"))
    cfg["selftest_output_root"] = str(tmp_root / "selftest")
    cfg.setdefault("paths", {})["creation_root"] = str(tmp_root / "creation")
    # 10-24 补的洞：`--tier play` 的落点走 `play_output_root`（run.py 里取不到就硬拼
    #   ComfyUI_H3\output\娱乐流），以前本函数**没设这个键** ⇒ 隔离跑的预览批会写进真输出树。
    #   今天用 run.py 跑负例时真的在 D:\...\output\娱乐流\无音\ 下建了两个批次夹。
    cfg["play_output_root"] = str(tmp_root / "comfy_play")
    comfy = cfg.setdefault("comfyui", {})
    comfy["output_dir"] = str(tmp_root / "comfy_out")
    comfy["input_dir"] = str(tmp_root / "comfy_in")
    comfy["log"] = str(logs / "comfyui_h3.log")
    feishu = cfg.setdefault("feishu", {})
    feishu["push_gates"] = "off"          # 显式 off，不依赖环境变量 dry
    logs.mkdir(parents=True, exist_ok=True)
    yaml_path = tmp_root / "config.isolated.yaml"
    yaml_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
    return cfg, yaml_path


# ---------------------------------------------------------------- 安装
_INSTALLED = []


def install():
    """会话级安装全部守卫（幂等）。返回计数对象。

    socket 三层（connect/connect_ex/create_connection）+ subprocess.Popen +
    tasks.SESSION + tasks.ensure_comfyui + tasks.send_media_to_feishu。
    """
    if _INSTALLED:
        return COUNTERS
    socket.socket.connect = _net_bork
    socket.socket.connect_ex = _net_bork
    socket.create_connection = _net_bork
    subprocess.Popen = _guarded_popen
    import tasks as T                       # engine/ 已在 sys.path（conftest 保证）
    T.SESSION = _DeadSession()
    T.ensure_comfyui = _stub_ensure_comfyui
    T.send_media_to_feishu = _stub_send_media_to_feishu
    _INSTALLED.append(True)
    return COUNTERS
