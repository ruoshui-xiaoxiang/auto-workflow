# -*- coding: utf-8 -*-
"""W0 子进程隔离守卫。仅当环境变量 AW_ISOLATED=1 时生效，否则零行为。

激活机制：conftest.py 把本目录前置进子进程 PYTHONPATH ⇒ Python 启动时自动
import 本模块（sitecustomize 协议）。父进程（pytest）不经过这里，父进程的
守卫在 _isolation.install()。

生效后：
  · sys.dont_write_bytecode = True（pycache 不写源树）
  · 封锁 socket.connect / connect_ex / create_connection（含 127.0.0.1）
  · 拦 subprocess.Popen：白名单仅 sys.executable 与 shell=True 的 echo 哨兵
    （selftest_gates 的 after 步是 `echo …` 哨兵，e2e 靠它证明续跑走下去了；
     powershell 气泡、lark-cli、ComfyUI 拉起、ffmpeg 等一律拦）
每次拦截/放行追加一行 JSONL 到 AW_ISOLATED_LOG 指向的文件，父进程聚合作证据。
"""
import json
import os
import sys

if os.environ.get("AW_ISOLATED") == "1":
    sys.dont_write_bytecode = True
    import socket
    import subprocess

    _LOG = os.environ.get("AW_ISOLATED_LOG")

    def _rec(kind, detail):
        if not _LOG:
            return
        try:
            with open(_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "kind": kind,
                                    "detail": str(detail)[:200]},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass

    class _NetBork(OSError):
        """子进程隔离：真实网络连接一律拦（OSError 子类，宽捕获安全）。"""

    def _bork(*a, **kw):
        _rec("net", a)
        raise _NetBork(f"子进程隔离：禁止真实网络 {str(a)[:120]}")

    socket.socket.connect = _bork
    socket.socket.connect_ex = _bork
    socket.create_connection = _bork

    _RealPopen = subprocess.Popen

    def _allowed(args, kw):
        exe = args[0] if isinstance(args, (list, tuple)) else args
        try:
            if os.path.normcase(str(exe)) == os.path.normcase(sys.executable):
                return True
        except Exception:
            pass
        return (bool(kw.get("shell")) and isinstance(args, str)
                and args.lstrip().lower().startswith("echo "))

    def _guarded(args, *a, **kw):
        if _allowed(args, kw):
            _rec("popen_allow", args)
            return _RealPopen(args, *a, **kw)
        _rec("popen_block", args)
        raise RuntimeError(f"子进程隔离：白名单外子进程被拦 {str(args)[:160]}")

    subprocess.Popen = _guarded
