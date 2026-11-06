# -*- coding: utf-8 -*-
"""H3 产线（ComfyUI 端口 8189）停摆监测 —— 旁路只读看门狗。

只做四件事：看产出、看 API/队列、看进程、看 GPU。全程只读：
不提交任务、不清队列、不重启服务、不碰 output 目录里的文件。

分层判定（不是「没新片就喊」）：
  DOWN          进程不存在                         -> 告警
  UNRESPONSIVE  进程在但 /system_stats 连不上      -> 告警（典型 OOM 后假死）
  HUNG          队列有任务 + 超时无产出 + GPU 长期 0 -> 告警（真卡住）
  IDLE_STALL    队列空 + 超时无产出                 -> 告警（没人喂任务，今天就是这种）
  SLOW          队列有任务 + 超时无产出 + GPU 在动  -> 只记录，不告警
  RUNNING/IDLE_OK  阈值内有新产出                    -> 正常

同一段停摆只告警一次，恢复（出现新产出 / 队列重新运转）自动复位。
状态写 watch_status.json，历史追加进 watch_status.log。

用法：
  python h3_watchdog.py                     # 计划任务每 5 分钟调这个
  python h3_watchdog.py --threshold 20      # 改停摆阈值（分钟）
  python h3_watchdog.py --test-notify       # 只测桌面通知通道
  python h3_watchdog.py --no-notify         # 只判定不弹窗
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_OUTPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"
DEFAULT_URL = "http://127.0.0.1:8189"
DEFAULT_PORT = 8189
DEFAULT_STATUS = r"D:\AIWorkflow\tools\watch_status.json"
DEFAULT_LOG = r"D:\AIWorkflow\tools\watch_status.log"
DEFAULT_COMFY_LOG_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\user"
DEFAULT_THRESHOLD_MIN = 20.0
DEFAULT_EXT = ".mp4,.mov,.webm"
GPU_IDLE_PCT = 5
GPU_SAMPLES = 4          # 每 5 分钟一采，4 次 ≈ 20 分钟
LOG_MAX_BYTES = 2 * 1024 * 1024

ALERT_STATES = {"DOWN", "UNRESPONSIVE", "HUNG", "IDLE_STALL"}
STATE_CN = {
    "DOWN": "进程不在",
    "UNRESPONSIVE": "服务无响应",
    "HUNG": "队列卡死",
    "IDLE_STALL": "空转停摆",
    "SLOW": "渲染中但慢",
    "RUNNING": "正在渲染",
    "IDLE_OK": "空闲但正常",
    "NO_OUTPUT": "尚无产出",
}


def now_str(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def fmt_age(minutes: float | None) -> str:
    if minutes is None:
        return "-"
    if minutes < 60:
        return "%.1f 分钟" % minutes
    return "%.1f 小时" % (minutes / 60.0)


def fmt_ts(ts: float | None) -> str:
    return "-" if not ts else datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def scan_outputs(root: Path, exts: tuple[str, ...]) -> tuple[str | None, float | None, int]:
    """返回 (最新产出文件, 其 mtime, 产出文件总数)。只 stat，不打开。"""
    latest_file = None
    latest_mtime = None
    count = 0
    if not root.is_dir():
        return None, None, 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(exts):
                continue
            count += 1
            p = os.path.join(dirpath, fn)
            try:
                m = os.stat(p).st_mtime
            except OSError:
                continue
            if latest_mtime is None or m > latest_mtime:
                latest_file, latest_mtime = p, m
    return latest_file, latest_mtime, count


def http_json(base: str, path: str, timeout: float):
    req = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def probe_api(base: str, timeout: float) -> dict:
    res = {
        "ok": False, "latency_ms": None, "error": None, "version": None,
        "queue_running": None, "queue_pending": None,
    }
    t0 = time.perf_counter()
    try:
        stats = http_json(base, "/system_stats", timeout)
        res["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        res["version"] = (stats.get("system") or {}).get("comfyui_version")
        res["ok"] = True
    except Exception as exc:  # 连不上/超时/返回非 JSON 都算无响应
        res["error"] = "%s: %s" % (type(exc).__name__, exc)
        return res
    try:
        q = http_json(base, "/queue", timeout)
        res["queue_running"] = len(q.get("queue_running") or [])
        res["queue_pending"] = len(q.get("queue_pending") or [])
    except Exception as exc:
        res["queue_error"] = "%s: %s" % (type(exc).__name__, exc)
    return res


def find_process(port: int) -> dict | None:
    """优先 psutil（对照 main.py + 端口命令行），退化到 WMI。"""
    try:
        import psutil  # 本机已装；没有就走 WMI 分支
    except ImportError:
        psutil = None

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmd = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            # 必须是 python 本体 + main.py + 端口，排除父级 pwsh（它的命令行里也带着这些字样）
            if not name.startswith("python"):
                continue
            if "main.py" in cmd and str(port) in cmd:
                try:
                    started = proc.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    started = None
                return {"pid": proc.info["pid"], "cmdline": cmd, "started_at": started}
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if (conn.laddr and conn.laddr.port == port
                        and conn.status == psutil.CONN_LISTEN and conn.pid):
                    return {"pid": conn.pid, "cmdline": "", "started_at": None}
        except (psutil.AccessDenied, OSError):
            pass
        return None

    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*main.py*' -and $_.CommandLine -like '*%d*' } | "
          "Select-Object -First 1 ProcessId,CommandLine,CreationDate | ConvertTo-Json -Compress") % port
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        if not out:
            return None
        info = json.loads(out)
        started = None
        raw = info.get("CreationDate")
        if isinstance(raw, str):
            started = datetime.strptime(raw[:14], "%Y%m%d%H%M%S").timestamp()
        return {"pid": info.get("ProcessId"), "cmdline": info.get("CommandLine") or "", "started_at": started}
    except Exception:
        return None


def gpu_util() -> int | None:
    exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    if not os.path.exists(exe):
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    nums = [int(x) for x in re.findall(r"\d+", out)]
    return nums[0] if nums else None


def last_log_timestamp(log_dir: Path) -> float | None:
    """读最新 comfyui_*.log 的尾部，取最后一条「真在干活」的时间戳。

    优先匹配 got prompt / Prompt executed / 模型载入标记，避免把客户端断连
    的 _ProactorBasePipeTransport 噪声当成产线活动。
    """
    if not log_dir.is_dir():
        return None
    candidates = sorted(
        (p for p in log_dir.glob("comfyui_*.log") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    path = candidates[0]
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 16384))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return path.stat().st_mtime
    pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d{3}\]")
    work = re.compile(r"got prompt|Prompt executed|Requested to load|seeder.scan_completed")
    work_stamp = None
    any_stamp = None
    for line in tail.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        any_stamp = m.group(1)
        if work.search(line):
            work_stamp = m.group(1)
    for stamp in (work_stamp, any_stamp):
        if stamp:
            try:
                return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
    return path.stat().st_mtime


TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
$title = $env:H3WD_TITLE
$body = $env:H3WD_BODY
function Show-Toast {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null
    $esc = [System.Security.SecurityElement]::Escape($body)
    $escT = [System.Security.SecurityElement]::Escape($title)
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast duration='long'><visual><binding template='ToastGeneric'><text>$escT</text><text>$esc</text></binding></visual><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
}
function Show-Balloon {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $ni = New-Object System.Windows.Forms.NotifyIcon
    $ni.Icon = [System.Drawing.SystemIcons]::Warning
    $ni.Visible = $true
    $ni.ShowBalloonTip(10000, $title, $body, [System.Windows.Forms.ToolTipIcon]::Warning)
    Start-Sleep -Milliseconds 4000
    $ni.Dispose()
}
try { Show-Toast; Write-Output 'OK:toast' ; exit 0 } catch { }
try { Show-Balloon; Write-Output 'OK:balloon'; exit 0 } catch { Write-Output ('FAIL:' + $_.Exception.Message); exit 1 }
"""


def notify(title: str, body: str) -> dict:
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="h3wd_")
    os.close(fd)
    try:
        Path(path).write_text(TOAST_PS, encoding="utf-8-sig")
        ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        if not os.path.exists(ps):
            ps = "powershell.exe"
        env = dict(os.environ)
        env["H3WD_TITLE"] = title
        env["H3WD_BODY"] = body.replace("\r", "")
        cp = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True, text=True, timeout=45, env=env,
        )
        out = (cp.stdout or "").strip()
        if out.startswith("OK:"):
            return {"sent": True, "method": out.split(":", 1)[1], "at": now_str()}
        err = (cp.stderr or out or "unknown").strip().splitlines()
        return {"sent": False, "method": "none", "at": now_str(),
                "error": (err[0] if err else "unknown")[:300]}
    except Exception as exc:
        return {"sent": False, "method": "none", "at": now_str(),
                "error": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def load_status(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_status(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def rotate_log(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def append_log(path: Path, line: str) -> None:
    rotate_log(path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line.rstrip("\n") + "\n")


def assess(args, prev: dict) -> dict:
    out_root = Path(args.output_dir)
    exts = tuple(x.strip().lower() for x in args.ext.split(",") if x.strip())
    last_file, last_mtime, total = scan_outputs(out_root, exts)
    api = probe_api(args.url, args.timeout)
    proc = find_process(args.port)
    util = gpu_util()
    log_ts = last_log_timestamp(Path(args.comfy_log_dir))

    threshold = args.threshold
    now = time.time()
    out_age = (now - last_mtime) / 60.0 if last_mtime else None
    activity_ts = max([t for t in (last_mtime, log_ts) if t], default=None)
    activity_age = (now - activity_ts) / 60.0 if activity_ts else None

    queue_busy = bool((api.get("queue_running") or 0) + (api.get("queue_pending") or 0))

    samples = list(prev.get("gpu", {}).get("samples") or [])
    if util is not None:
        samples.append(int(util))
    samples = samples[-GPU_SAMPLES:]
    gpu_idle_long = len(samples) >= 3 and all(v <= GPU_IDLE_PCT for v in samples)

    # --- 分层判定 ---
    reason = ""
    if proc is None:
        state = "DOWN"
        reason = "端口 %d 上没有 ComfyUI 进程（main.py 不在）" % args.port
    elif not api["ok"]:
        state = "UNRESPONSIVE"
        reason = "进程 %s 还在，但 /system_stats 连不上（%s）" % (proc.get("pid"), api.get("error"))
    elif out_age is None:
        state = "NO_OUTPUT"
        reason = "产出目录里还没有任何成片，无法计时"
    elif out_age < threshold:
        state = "RUNNING" if queue_busy else "IDLE_OK"
        reason = "%.1f 分钟前有新产出（阈值 %.0f 分钟）" % (out_age, threshold)
    else:
        if queue_busy and (gpu_idle_long or out_age >= threshold * 2):
            state = "HUNG"
            reason = ("队列里有 %d 个任务，但已 %s 无新产出，GPU 近 %d 次采样 ≤%d%%"
                      % ((api.get("queue_running") or 0) + (api.get("queue_pending") or 0),
                         fmt_age(out_age), len(samples), GPU_IDLE_PCT))
            if not gpu_idle_long:
                reason += "；已超过 2 倍阈值，按卡死处理"
        elif queue_busy:
            state = "SLOW"
            reason = ("队列里还有 %d 个任务，%s 没出新片，但 GPU=%s%% 仍在动 → 视为慢，不告警"
                      % ((api.get("queue_running") or 0) + (api.get("queue_pending") or 0),
                         fmt_age(out_age), util if util is not None else "?"))
        else:
            state = "IDLE_STALL"
            reason = ("队列空、无人提交任务，已 %s 没有新成片（阈值 %.0f 分钟）"
                      % (fmt_age(out_age), threshold))

    # --- 单次告警 / 恢复复位 ---
    episode = dict(prev.get("episode") or {})
    alert_now = False
    recovered = False
    if state in ALERT_STATES:
        if not episode.get("active") or episode.get("state") != state:
            episode = {"active": True, "state": state, "since": now_str(),
                       "since_ts": now, "alerted": False}
            alert_now = True
    else:
        if episode.get("active"):
            recovered = True
            episode = {"active": False, "state": None, "since": None, "since_ts": None,
                       "alerted": False, "recovered_at": now_str()}

    counters = dict(prev.get("counters") or {"total_checks": 0, "alerts": 0})
    counters["total_checks"] = int(counters.get("total_checks") or 0) + 1

    result = {
        "updated_at": now_str(),
        "state": state,
        "state_cn": STATE_CN.get(state, state),
        "severity": "alert" if state in ALERT_STATES else ("info" if state == "SLOW" else "ok"),
        "reason": reason,
        "alert_now": alert_now,
        "recovered": recovered,
        "last_output_file": last_file,
        "last_output_time": fmt_ts(last_mtime),
        "last_output_age_min": round(out_age, 1) if out_age is not None else None,
        "last_activity_time": fmt_ts(activity_ts),
        "last_activity_age_min": round(activity_age, 1) if activity_age is not None else None,
        "last_log_time": fmt_ts(log_ts),
        "output_total_files": total,
        "threshold_min": threshold,
        "comfy": {
            "url": args.url,
            "api_ok": api["ok"],
            "latency_ms": api["latency_ms"],
            "version": api["version"],
            "queue_running": api.get("queue_running"),
            "queue_pending": api.get("queue_pending"),
            "queue_busy": queue_busy,
            "process_alive": proc is not None,
            "pid": proc.get("pid") if proc else None,
            "api_error": api.get("error"),
        },
        "gpu": {"util_pct": util, "samples": samples, "idle_long": gpu_idle_long},
        "episode": episode,
        "counters": counters,
    }
    return result


def notify_text(result: dict, status_path: str) -> tuple[str, str]:
    stem = Path(result["last_output_file"]).name if result["last_output_file"] else "无"
    tail = "最后产出：%s @ %s（%s前）\n状态文件：%s" % (
        stem, result["last_output_time"],
        fmt_age(result["last_output_age_min"]), status_path,
    )
    state = result["state"]
    if state == "IDLE_STALL":
        title = "H3 产线停摆：队列空转"
        body = ("已 %s 没有新成片（阈值 %.0f 分钟）。ComfyUI 进程 %s 正常响应，GPU=%s%%，"
                "是没人喂任务/驱动没续提交，不是渲染卡死。\n%s"
                % (fmt_age(result["last_output_age_min"]), result["threshold_min"],
                   result["comfy"]["pid"], result["gpu"]["util_pct"], tail))
    elif state == "HUNG":
        title = "H3 产线卡住：队列不动"
        body = ("%s。进程 %s 还在，建议看 ComfyUI 控制台是否有 OOM/Traceback。\n%s"
                % (result["reason"], result["comfy"]["pid"], tail))
    elif state == "UNRESPONSIVE":
        title = "H3 产线假死：API 无响应"
        body = ("%s。历史上 OOM 后就是这个症状（队列清不掉），通常需要重启服务。\n%s"
                % (result["reason"], tail))
    else:
        title = "H3 产线进程不在了"
        body = ("%s。\n%s" % (result["reason"], tail))
    return title, body


def main() -> int:
    ap = argparse.ArgumentParser(description="H3 产线停摆监测（只读）")
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_MIN,
                    help="停摆阈值（分钟），默认 20")
    ap.add_argument("--ext", default=DEFAULT_EXT, help="算作产出的扩展名，逗号分隔")
    ap.add_argument("--status-file", default=DEFAULT_STATUS)
    ap.add_argument("--log-file", default=DEFAULT_LOG)
    ap.add_argument("--comfy-log-dir", default=DEFAULT_COMFY_LOG_DIR)
    ap.add_argument("--timeout", type=float, default=4.0, help="HTTP 超时（秒）")
    ap.add_argument("--no-notify", action="store_true", help="只判定不弹窗")
    ap.add_argument("--test-notify", action="store_true", help="只测试通知通道")
    ap.add_argument("--quiet", action="store_true", help="不打印到控制台（计划任务用）")
    args = ap.parse_args()

    if args.test_notify:
        res = notify("H3 停摆监测：通知通道测试",
                     "这是一条测试通知。能弹出来说明告警通道可用。\n"
                     "计划任务：H3_ComfyUI_Watchdog（每 5 分钟）")
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("sent") else 3

    status_path = Path(args.status_file)
    log_path = Path(args.log_file)
    prev = load_status(status_path)
    result = assess(args, prev)

    if args.no_notify:
        result["notify"] = {"sent": False, "method": "disabled", "at": now_str()}
    elif result["alert_now"]:
        title, body = notify_text(result, str(status_path))
        result["notify"] = notify(title, body)
        if result["notify"].get("sent"):
            result["counters"]["alerts"] = int(result["counters"].get("alerts") or 0) + 1
            result["episode"]["alerted"] = True
            result["episode"]["alerted_at"] = result["notify"]["at"]
    else:
        result["notify"] = {"sent": False, "method": "skip", "at": now_str()}

    write_status(status_path, result)

    flag = result["state"]
    if result["alert_now"]:
        flag = "ALERT:" + flag
    elif result["recovered"]:
        flag = "RECOVER"
    line = ("[{ts}] [{flag}] {cn} | {reason} | 产出={f} @{fo} | api={api}"
            " | proc={pid} | 队列={r}/{p} | gpu={gpu}% | notify={nt}"
            ).format(
        ts=result["updated_at"], flag=flag, cn=result["state_cn"], reason=result["reason"],
        f=Path(result["last_output_file"]).name if result["last_output_file"] else "-",
        fo=result["last_output_time"], api="ok" if result["comfy"]["api_ok"] else "无响应",
        pid=result["comfy"]["pid"], r=result["comfy"]["queue_running"],
        p=result["comfy"]["queue_pending"],
        gpu=result["gpu"]["util_pct"],
        nt=result["notify"]["method"],
    )
    append_log(log_path, line)
    if not args.quiet:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
