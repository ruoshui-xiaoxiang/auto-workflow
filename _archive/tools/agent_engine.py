#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""agent_engine.py · 通道3「agent出片引擎」的**非交互**调用入口（给 agent / 脚本 / 其它软件用）

为什么要有它：`E:\\LocalAI\\LocalAI.ps1` 是给人用的交互菜单（`Clear-Host` + `Read-Host` + `while($true)`），
agent 一调就卡住；`gateway\\start-desktop.bat` 里有 `pause` 和 `timeout /t`，在非交互 shell 下会失败，
而且它最后会前台阻塞跑 `desktop.py`（工作台 GUI）。本脚本把通道3 拆成可编程的四个动作，
**只用现有官方入口脚本，不新起端口、不改四通道分工**。

端口（照 E:\\LocalAI\\CHANNELS.md，不新增）：
  8080 网关（OpenAI 兼容 /v1）  8081 qwen3-14b 后端  8082/8083/8084 agent 档后端
  11434 Ollama  1234 LM Studio  8189 统一 ComfyUI（通道4 娱乐流只起这一个）
  8787 / 8790 已废门面端口 —— 本脚本只在 status 表里**显示**它们有没有人占着，
             不会去起、也不会去调；端口号留着是为了让 status 表形状不变、
             万一有残留进程还能一眼看见。

用法：
  py agent_engine.py up      [--model qwen3-14b|agent] [--tier 1|2|3] [--json] [--timeout 900]
  py agent_engine.py status  [--json]
  py agent_engine.py models  [--json]
  py agent_engine.py chat    "一句话" [--model qwen3-14b] [--json] [--max-tokens 512] [--temp 0.3]
  py agent_engine.py down    [--gateway] [--json]        # 默认只停 8081-8084 后端腾显存，网关留着

退出码：0 成功 / 2 服务没起且没让我起 / 3 起了但失败 / 4 参数或环境错
所有命令都可加 --json 拿机器可读结果；不加就是人读的一行行文本。
"""
from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LOCALAI = Path(r"E:\LocalAI")
GATEWAY_DIR = LOCALAI / "gateway"
GATEWAY_PY = GATEWAY_DIR / "gateway.py"
LAUNCHERS = LOCALAI / "launchers"
QWEN_PS1 = LAUNCHERS / "start-qwen1234.ps1"      # 8081，已是幂等/无交互
AGENT_PS1 = LAUNCHERS / "agent-launch.ps1"       # 8082-8084，带 -Tier/-Status/-Stop
LOGDIR = LOCALAI / "logs"

GW = "http://127.0.0.1:8080"
PORTS = {8080: "agent出片引擎网关", 8081: "qwen3-14b 后端", 8082: "agent档后端(tier1)",
         8083: "agent档后端(tier2)", 8084: "agent档后端(tier3)",
         11434: "Ollama", 1234: "LM Studio",
         8189: "统一 ComfyUI（现役）",
         8787: "已废：脚本化出片 WebUI（仅显示占用，不起不调）",
         8790: "已废：说话出片 UI（仅显示占用，不起不调）"}

DETACHED = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS|NEW_PROCESS_GROUP|NO_WINDOW


def out(obj, as_json, human):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        for line in human:
            print(line, flush=True)


def http(base, path, method="GET", payload=None, timeout=30):
    """唯一外呼出口：只允许 127.0.0.1（零联网）。"""
    if not base.startswith("http://127.0.0.1"):
        raise RuntimeError("拒绝非本机端点：%s%s" % (base, path))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def proc_info(pid):
    """PID → 进程名/启动时间/命令行。查不到返回 None，不抛。

    为什么要记：2026-10-19 实测 8790 曾 `LISTEN pid=37940`，十几分钟后进程没了，
    status 表只留了个号 ⇒ 事后问「那是哪个程序在听」只能靠推断。名字＋启动时间＋命令行
    一起记，一眼可查；这也是把「已废门面还开着」变成可处置事实的前提。
    """
    if not pid:
        return None
    cmd = ["powershell", "-NoProfile", "-Command",
           "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%d' -ErrorAction SilentlyContinue;"
           "if($p){$p.Name+'|'+[string]$p.CreationDate+'|'+$p.CommandLine}" % int(pid)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=40)
        s = (r.stdout or b"").decode("utf-8", "replace").strip()
        if not s:
            return None
        name, created, cmdline = (s.split("|", 2) + ["", ""])[:3]
        return {"pid": int(pid), "name": name, "created": created,
                "cmd": (cmdline or "").strip()[:400]}
    except Exception:
        return None


def listening(port):
    """端口是否在听（用 PowerShell 的 Get-NetTCPConnection，不引第三方库）。"""
    cmd = ["powershell", "-NoProfile", "-Command",
           "$c=Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue;"
           "if($c){($c|Select-Object -First 1).OwningProcess}else{''}" % port]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=40)
        s = (r.stdout or b"").decode("utf-8", "replace").strip()
        return int(s) if s.isdigit() else None
    except Exception:
        return None


def gw_health():
    try:
        return http(GW, "/health", timeout=6)
    except Exception:
        return None


def gw_models():
    try:
        d = http(GW, "/v1/models", timeout=8)
        return [m.get("id") for m in (d.get("data") or []) if isinstance(m, dict)]
    except Exception:
        return []


def vram():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free",
                            "--format=csv,noheader,nounits"], capture_output=True, timeout=30)
        u, t, f = (r.stdout or b"").decode("utf-8", "replace").strip().split(",")[:3]
        return {"used_mib": int(u.strip()), "total_mib": int(t.strip()), "free_mib": int(f.strip())}
    except Exception:
        return {}


# 后端权重装载所需净显存（MiB）。agent 档的数字直接取自 launchers\agent-launch.ps1 的
# $TIER_DESC（他自己实测的净显存）：1=11957 / 2=2354 / 3=4780。
# 不够就**拒绝启动**而不是硬起——2026-10-13 撞过一次：ComfyUI 占着 14.6GB 时起 14B，
# llama-server 绑了端口但卡在 "Loading model" 十几分钟不动，网关一直回 503。
NEED_MIB = {"qwen3-14b": 9800, "agent": {1: 12200, 2: 2600, 3: 5100}}


def need_mib(model, tier):
    v = NEED_MIB.get(model, 9800)
    return v.get(tier, 12200) if isinstance(v, dict) else v


# ------------------------------------------------------------------ up
def start_gateway(timeout=180, verbose=True):
    h = gw_health()
    if h:
        if verbose:
            print("· 网关 8080 已在跑：%s" % json.dumps(h, ensure_ascii=False), flush=True)
        return True
    if not GATEWAY_PY.is_file():
        print("🔴 找不到 %s" % GATEWAY_PY)
        return False
    LOGDIR.mkdir(exist_ok=True)
    log = open(LOGDIR / "gateway_agent.log", "ab", buffering=0)
    env = dict(os.environ, LOCALAI_GATEWAY_CONFIG=str(GATEWAY_DIR / "config.json"),
               PYTHONIOENCODING="utf-8")
    # DETACHED：不随调用方的 shell 退出而死（这是之前 agent 起完就掉的原因）
    subprocess.Popen([sys.executable, str(GATEWAY_PY)], cwd=str(GATEWAY_DIR),
                     stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     creationflags=DETACHED, env=env)
    if verbose:
        print("· 起网关 8080（detached，日志 %s）…" % (LOGDIR / "gateway_agent.log"), flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if gw_health():
            if verbose:
                print("· 网关就绪，用时 %ds" % round(time.time() - t0), flush=True)
            return True
        time.sleep(2)
    print("🔴 网关 %ds 未就绪，看日志 %s" % (timeout, LOGDIR / "gateway_agent.log"))
    return False


def start_backend(model="qwen3-14b", tier=1, timeout=900, verbose=True):
    if model == "none":
        if verbose:
            print("· --model none：只起网关，不起任何后端（不占显存）", flush=True)
        return None
    if model == "agent":
        ps1, args, port = AGENT_PS1, ["-Tier", str(tier)], 8082
    else:
        ps1, args, port = QWEN_PS1, [], 8081
    if not ps1.is_file():
        print("🔴 找不到启动器 %s" % ps1)
        return False
    if listening(port):
        if verbose:
            print("· 后端 :%d 已在跑，复用" % port, flush=True)
        return True
    free = vram().get("free_mib")
    need = need_mib(model, tier)
    if free is not None and free < need:
        print("🔴 显存不够：净空 %d MiB < %s 需要的 %d MiB。" % (free, model, need))
        print("   14B/20B 后端与 ComfyUI(8189, H3/FLUX) **不能同时驻留**——LocalAI 菜单的")
        print("   「agent出片流水线」也是先停 8081-8084 再出片。二选一：")
        print("     · 要写稿：先停 ComfyUI（8189），再 py agent_engine.py up")
        print("     · 要出片：py agent_engine.py up --model none（只要网关，不占显存）")
        return False
    if verbose:
        print("· 起后端 :%d（%s，冷加载 8.38GB 权重要几分钟；净空显存 %s MiB）…"
              % (port, ps1.name, free), flush=True)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)] + args
    r = None
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        txt = b"".join([r.stdout or b"", r.stderr or b""]).decode("utf-8", "replace").strip()
        if verbose and txt:
            print("  " + txt.replace("\n", "\n  ")[:600], flush=True)
    except subprocess.TimeoutExpired:
        print("🔴 后端启动超时 %ds" % timeout)
        return False
    ok = listening(port) is not None
    if not ok:
        print("🔴 后端 :%d 没起来（rc=%s）" % (port, r.returncode if r else "?"))
    return ok


def cmd_up(a):
    res = {"gateway": False, "backend": False, "models": [], "vram": vram()}
    res["gateway"] = start_gateway(timeout=min(a.timeout, 300), verbose=not a.json)
    if res["gateway"]:
        res["backend"] = start_backend(a.model, a.tier, timeout=a.timeout, verbose=not a.json)
        res["models"] = gw_models()
    res["ok"] = bool(res["gateway"] and (res["backend"] or a.model == "none"))
    human = ["网关 8080：%s" % ("OK" if res["gateway"] else "失败"),
             "后端 %s：%s" % (a.model, "OK" if res["backend"] else "失败/未起"),
             "网关可见模型：%s" % (", ".join(res["models"]) or "（空）"),
             "显存：%s" % (res["vram"] or "?"),
             "调用方式：POST http://127.0.0.1:8080/v1/chat/completions"]
    out(res, a.json, human)
    return 0 if res["ok"] else 3


# ------------------------------------------------------------------ status / models / chat
def cmd_status(a):
    rows = []
    for p, name in sorted(PORTS.items()):
        pid = listening(p)
        row = {"port": p, "name": name, "listening": pid is not None, "pid": pid,
               "proc": proc_info(pid) if pid else None}
        rows.append(row)
    st = {"ports": rows, "gateway_health": gw_health(), "gateway_models": gw_models(),
          "vram": vram()}
    st["channels"] = {
        "1_LM": next(r["listening"] for r in rows if r["port"] == 1234),
        "2_OLL": next(r["listening"] for r in rows if r["port"] == 11434),
        "3_agent_engine": next(r["listening"] for r in rows if r["port"] == 8080),
        "4_pipeline": next(r["listening"] for r in rows if r["port"] == 8189),
    }
    human = ["端口  状态        通道角色                            进程（谁在听）"]
    for r in sorted(rows, key=lambda x: x["port"]):
        who = ""
        if r["proc"]:
            who = "  ← %s @ %s" % (r["proc"]["name"], r["proc"]["created"])
        human.append("%-6d %-11s %s%s" % (r["port"],
                                          ("LISTEN pid=%s" % r["pid"]) if r["listening"] else "idle",
                                          r["name"], who))
    for r in rows:
        if r["proc"] and r["proc"].get("cmd"):
            human.append("      pid %d cmd: %s" % (r["proc"]["pid"], r["proc"]["cmd"]))
    human.append("网关 /health：%s" % json.dumps(st["gateway_health"], ensure_ascii=False))
    human.append("网关模型：%s" % (", ".join(st["gateway_models"]) or "（空）"))
    human.append("显存：%s" % (st["vram"] or "?"))
    human.append("四通道：%s" % json.dumps(st["channels"], ensure_ascii=False))
    out(st, a.json, human)
    return 0


def cmd_models(a):
    ids = gw_models()
    out({"models": ids, "gateway_up": bool(ids)}, a.json,
        ["网关模型：%s" % (", ".join(ids) or "（空——网关没起或后端没挂）")])
    return 0 if ids else 2


def cmd_chat(a):
    ids = gw_models()
    if not ids:
        print("🔴 网关 8080 没起或没模型。先跑：py agent_engine.py up")
        return 2
    model = a.model or next((i for i in ids if "14b" in i or "qwen3" in i), ids[0])
    payload = {"model": model,
               "messages": [{"role": "system", "content": a.system} if a.system else None,
                            {"role": "user", "content": a.text}],
               "temperature": a.temp, "max_tokens": a.max_tokens}
    if getattr(a, "no_think", False):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    payload["messages"] = [m for m in payload["messages"] if m]
    t0 = time.time()
    try:
        d = http(GW, "/v1/chat/completions", "POST", payload, timeout=a.timeout)
    except urllib.error.HTTPError as e:
        print("🔴 网关返回 %s：%s" % (e.code, e.read().decode("utf-8", "replace")[:400]))
        return 3
    except Exception as e:
        print("🔴 调用失败：%s" % str(e)[:200])
        return 3
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    txt = (msg.get("content") or ch.get("text") or "").strip()
    reason = (msg.get("reasoning_content") or "").strip()
    fin = ch.get("finish_reason")
    res = {"model": model, "secs": round(time.time() - t0, 1), "content": txt,
           "finish_reason": fin, "reasoning_chars": len(reason), "usage": d.get("usage")}

    # 🔴 2026-10-19 端到端验证查实的静默失败：qwen3-14b 是**思考模型**，回答前会先吐
    #   `reasoning_content`，`content` 要等它想完才有字。默认 max_tokens=512 时
    #   实测「用八个字形容雪夜古城」这条**思考就吃掉 848 token** ⇒ content 空、
    #   finish_reason=length，旧代码打一行空串、rc=3，看着像"网关坏了"。
    #   实测三条出路：抬到 1024 → 20.3s 出「雪掩苍城，月寂灯寒。」；
    #   chat_template_kwargs.enable_thinking=false → 2.1s 直接出字；reasoning_effort=none 同样生效。
    if not txt and reason:
        res["why_empty"] = ("content 为空但 reasoning_content 有 %d 字 ⇒ 思考把 token 预算吃光了，"
                            "不是网关坏了" % len(reason))
        if not a.no_think and not a.no_retry and fin == "length":
            back = min(max(a.max_tokens * 3, 2048), 8192)
            payload["max_tokens"] = back
            t1 = time.time()
            try:
                d2 = http(GW, "/v1/chat/completions", "POST", payload, timeout=a.timeout)
                ch2 = (d2.get("choices") or [{}])[0]
                txt = ((ch2.get("message") or {}).get("content") or "").strip()
                res.update({"retried_with": back, "retry_secs": round(time.time() - t1, 1),
                            "content": txt, "finish_reason": ch2.get("finish_reason"),
                            "usage": d2.get("usage")})
            except Exception as e:
                res["retry_error"] = str(e)[:200]
    lines = ["[%s｜%.1fs] %s" % (model, res["secs"], txt or "（content 为空）")]
    if not txt:
        lines.append("   🔴 %s" % res.get("why_empty", "没拿到正文"))
        if res.get("retried_with"):
            lines.append("   已按 max_tokens=%d 重试，用时 %.1fs，仍为空 ⇒ 见 reason 字段"
                         % (res["retried_with"], res.get("retry_secs", 0.0)))
        lines.append("   要快、不要思考过程：加 --no-think（实测 2.1s 出字）；"
                     "要思考质量：加 --max-tokens 2048 以上")
        if reason:
            lines.append("   思考片段：%s…" % reason[:120].replace("\n", " "))
    out(res, a.json, lines)
    return 0 if txt else 3


# ------------------------------------------------------------------ down
def cmd_down(a):
    killed = []
    ports = [8080] if a.gateway else []
    ports += [8081, 8082, 8083, 8084]
    for p in ports:
        pid = listening(p)
        if not pid:
            continue
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Stop-Process -Id %d -Force -ErrorAction SilentlyContinue" % pid],
                       capture_output=True, timeout=60)
        killed.append({"port": p, "pid": pid})
        print("· 已停 :%d (pid %d)" % (p, pid), flush=True)
        time.sleep(1)
    if not a.gateway:
        print("· 网关 8080 保留（要一起停加 --gateway）")
    if not killed:
        print("· 没有在跑的后端。Ollama / LM Studio 未动。")
    out({"stopped": killed, "vram": vram()}, a.json,
        ["显存：%s" % (vram() or "?")])
    return 0


def main():
    ap = argparse.ArgumentParser(description="通道3 agent出片引擎的非交互入口（零联网，只用现有官方启动器）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("up", help="起网关 8080 + 后端（默认 qwen3-14b@8081）")
    p.add_argument("--model", default="qwen3-14b", choices=["qwen3-14b", "agent", "none"])
    p.add_argument("--tier", type=int, default=1, choices=[1, 2, 3], help="agent 档：1 全显存/2 卸载/3 7B")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_up)
    for name, fn, helpt in (("status", cmd_status, "端口/健康/模型/显存/四通道现状"),
                            ("models", cmd_models, "网关可见模型清单"),
                            ("down", cmd_down, "停后端腾显存（--gateway 连网关一起停）")):
        s = sub.add_parser(name, help=helpt)
        s.add_argument("--json", action="store_true")
        if name == "down":
            s.add_argument("--gateway", action="store_true")
        s.set_defaults(func=fn)
    c = sub.add_parser("chat", help="经网关跑一次对话（验证契约用）")
    c.add_argument("text")
    c.add_argument("--system", default=None)
    c.add_argument("--model", default=None)
    c.add_argument("--temp", type=float, default=0.3)
    c.add_argument("--max-tokens", dest="max_tokens", type=int, default=512)
    # qwen3-14b 是思考模型：默认会先吐 reasoning 再吐正文，512 token 常被思考吃光。
    # --no-think 走 llama-server 的 chat_template_kwargs（实测 2.1s 直接出字）；
    # --no-retry 关掉"空回答自动抬 3× token 重试"（默认开，为了不把空串当成功）。
    c.add_argument("--no-think", dest="no_think", action="store_true",
                   help="关掉思考（chat_template_kwargs.enable_thinking=false），快但少了推理过程")
    c.add_argument("--no-retry", dest="no_retry", action="store_true",
                   help="content 为空时不要自动抬 max_tokens 重试")
    c.add_argument("--timeout", type=int, default=600)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_chat)
    a = ap.parse_args()
    for f in (GATEWAY_PY, QWEN_PS1):
        if not f.is_file():
            print("🔴 通道3 文件缺失：%s" % f)
            return 4
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
