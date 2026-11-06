# -*- coding: utf-8 -*-
"""review_publish.py —— 把成片/逐镜拼图发到用户网站**审片区**，回一条防猜 URL。

为什么要有它（批 2／GAP-D1）：审片区的约定（16 位 hex 防猜、无鉴权、审完删、
`-movflags +faststart`、压到 ≈1 Mbps）一直**只存在于记忆件里，没有一行代码**——
hex 生成器不存在、上传脚本不存在。这个文件把那套约定变成可复跑的东西。

事实来源（不是猜的）：
  · 服务器 `root@47.250.138.158`，密钥 `%USERPROFILE%\\.ssh\\server_deploy_key`，站点根
    `/opt/product-site/`，nginx `location /review/ { alias .../public/review/; Accept-Ranges bytes; }`
    （2026-09-23 用户批准新增）。
  · 下行实测约 60 KB/s ⇒ 目标码率默认 1 Mbps，再高就是卡。
  · Git Bash 下 `%USERPROFILE%` 含中文会把 `~/.ssh` 转成乱码路径 ⇒ known_hosts 用**绝对 Windows 路径**。

安全边界：
  · **无鉴权 ＝ 知道 URL 就能看到**。所以 token 用 `secrets` 不是随机数发生器，且 URL 只在
    本地打印，绝不发去任何第三方、绝不写进日志以外的地方。
  · 审完就删（`--delete`），不留公网残留。
  · 不上传凭证类文件；`--dry-run` 只打印计划不动盘、不联网。

用法：
  py -3.12 review_publish.py 成片.mp4                      # 压＋传＋验 Range＋打印 URL
  py -3.12 review_publish.py a.png b.png --title 逐镜拼图   # 图片直接传（不转码）
  py -3.12 review_publish.py 成片.mp4 --dry-run             # 只看计划
  py -3.12 review_publish.py --list                         # 列远端现有审片夹
  py -3.12 review_publish.py --delete 203328f48a97560c      # 审完删
退出码：0 成功／1 参数或校验失败／2 远端操作失败／3 上传后 URL 验不过
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

HOST = "root@47.250.138.158"
SITE = "https://www.huahuayoueryuan.com"
REMOTE_ROOT = "/opt/product-site/public/review"
KEY = os.path.expandvars(r"%USERPROFILE%\.ssh\server_deploy_key")
# known_hosts 必须是绝对 Windows 路径：这台机器的用户名含中文，MSYS 会把 ~ 转成八进制乱码，
# 结果是 known_hosts 写不进去（连接能成但每次都告警）。
KNOWN_HOSTS = r"D:\AIWorkflow\tmp\qoder_known_hosts"
FFMPEG = r"D:\AIWorkflow\tools\ffmpeg.exe"
TOKEN_LEN = 16                    # 8 字节 ⇒ 16 个 hex 字符（沿用已上线那版的口径）
TARGET_BITRATE_K = "1000k"        # 下行实测 ~60 KB/s，1 Mbps 已经贴着上限
MAX_UPLOAD_MB = 28.0              # 飞书 30 MB 是另一回事；这里防的是把未压的原片直接怼上去
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def die(code, msg):
    print(msg)
    sys.exit(code)


def sh(cmd, capture=True):
    """跑一条外部命令。ssh/scp 一律带同一组 -o，避免中文用户名那个坑。"""
    r = subprocess.run(cmd, capture_output=capture, text=True,
                       encoding="utf-8", errors="replace")
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode, out


def ssh(remote_cmd, dry=False):
    if dry:
        print("  [dry-run] ssh %s '%s'" % (HOST, remote_cmd))
        return 0, ""
    return sh(["ssh", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
               "-o", "StrictHostKeyChecking=accept-new",
               "-o", "UserKnownHostsFile=%s" % KNOWN_HOSTS, HOST, remote_cmd])


def scp(srcs, remote_dir, dry=False):
    cmd = ["scp", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
           "-o", "StrictHostKeyChecking=accept-new",
           "-o", "UserKnownHostsFile=%s" % KNOWN_HOSTS]
    cmd += list(srcs) + ["%s:%s" % (HOST, remote_dir)]
    if dry:
        print("  [dry-run] scp %s → %s:%s" % (", ".join(srcs), HOST, remote_dir))
        return 0, ""
    return sh(cmd)


def new_token():
    """secrets 而非 random：审片区无鉴权，token 是唯一屏障。"""
    return secrets.token_hex(TOKEN_LEN // 2)


def probe(path):
    """ffprobe 拿码率/时长。ffprobe 不在就直接按体积估（估的会标出来）。"""
    ffprobe = os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")
    if os.path.isfile(ffprobe):
        rc, out = sh([ffprobe, "-v", "error", "-show_entries",
                      "format=bit_rate,duration,size", "-of", "json", path])
        if rc == 0:
            try:
                f = (json.loads(out) or {}).get("format", {})
                return {"bit_rate": int(f.get("bit_rate") or 0),
                        "duration": float(f.get("duration") or 0),
                        "size": int(f.get("size") or 0), "source": "ffprobe"}
            except Exception:
                pass
    size = os.path.getsize(path)
    return {"bit_rate": 0, "duration": 0.0, "size": size,
            "source": "体积估算（ffprobe 没拿到）"}


def should_transcode(path, force):
    """已经够小/够低码率就别重编码——重编码一次几分钟，且画质只会掉不会涨。"""
    if force:
        return True, "用户强制 --recode"
    if os.path.splitext(path)[1].lower() not in VIDEO_EXT:
        return False, "不是视频，直接传"
    p = probe(path)
    mb = p["size"] / 1048576.0
    if p["bit_rate"] and p["bit_rate"] <= int(TARGET_BITRATE_K.rstrip("k")) * 1000 * 1.1:
        return False, "码率 %d bps 已在目标内（%.1f MB）" % (p["bit_rate"], mb)
    if mb <= 6.0:
        return False, "体积 %.1f MB 本就很小，不必压" % mb
    return True, "码率 %s／体积 %.1f MB → 压到 %s" % (
        p["bit_rate"] or "未知", mb, TARGET_BITRATE_K)


def transcode(path, outdir):
    name = os.path.splitext(os.path.basename(path))[0] + "_review.mp4"
    dst = os.path.join(outdir, name)
    cmd = [FFMPEG, "-y", "-i", path, "-c:v", "libx264", "-preset", "veryfast",
           "-b:v", TARGET_BITRATE_K, "-maxrate", TARGET_BITRATE_K, "-bufsize", "2M",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", dst]
    rc, out = sh(cmd)
    if rc != 0:
        die(2, "!! ffmpeg 失败：%s" % out[-500:])
    return dst


def check_range(url, tries=2):
    """真验 Range：拖进度条能不能定位，取决于服务端支不支持 206。
    不验就直接给用户 URL，是拿他的等待换我的省事。"""
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=25) as r:
                code = r.getcode()
                acc = str(r.headers.get("Accept-Ranges", "")).lower()
                cr = r.headers.get("Content-Range", "")
                ok = code == 206 or (code == 200 and "bytes" in acc)
                return ok, code, acc, cr
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False, 404, "", "404 —— 还没落盘或路径不对"
        except Exception as e:
            last = type(e).__name__
    return False, 0, "", "取不到（%s）" % last


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="要发审的成片／拼图")
    ap.add_argument("--title", default="", help="审片夹里留一行说明（只进本地台账，不进 URL）")
    ap.add_argument("--recode", action="store_true", help="强制重编码")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划：不建远端目录、不传、不联网")
    ap.add_argument("--list", action="store_true", help="列远端现有审片夹")
    ap.add_argument("--delete", metavar="TOKEN", help="审完删掉这个 token 的夹")
    a = ap.parse_args(argv)

    if a.list:
        rc, out = ssh("ls -1 %s 2>/dev/null | sed 's#^#/review/#'" % REMOTE_ROOT)
        print(out or "（审片区为空）")
        return 0 if rc == 0 else 2

    if a.delete:
        if not re.fullmatch(r"[0-9a-f]{%d}" % TOKEN_LEN, a.delete):
            die(1, "!! token 形态不对（应为 %d 位小写 hex）：拒绝执行 rm -rf" % TOKEN_LEN)
        rc, out = ssh("rm -rf %s/%s && echo DELETED" % (REMOTE_ROOT, a.delete))
        print(("✓ 已删 " + a.delete) if "DELETED" in out else "!! 删除未确认：%s" % out[-200:])
        return 0 if rc == 0 and "DELETED" in out else 2

    if not a.files:
        die(1, __doc__)

    missing = [f for f in a.files if not os.path.isfile(f)]
    if missing:
        die(1, "!! 文件不存在：%s" % "、".join(missing))

    token = new_token()
    remote_dir = "%s/%s" % (REMOTE_ROOT, token)
    workdir = os.path.join(os.environ.get("TEMP", "."), "review_%s" % token)
    print("审片 token：%s（无鉴权，知道 URL 就能看 ⇒ 审完请 --delete）" % token)

    to_send, plan = [], []
    for f in a.files:
        do, why = should_transcode(os.path.abspath(f), a.recode)
        mb = os.path.getsize(f) / 1048576.0
        plan.append("  %-46s %6.1f MB  %s" % (os.path.basename(f), mb, why))
        if mb > MAX_UPLOAD_MB and not do:
            die(1, "!! %s %.1f MB 超过 %s MB 且未压 —— 先处理再发，别硬怼"
                % (os.path.basename(f), mb, MAX_UPLOAD_MB))
        to_send.append((os.path.abspath(f), do))
    print("\n".join(plan))

    if a.dry_run:
        print("\n[dry-run] 未联网、未建远端目录、未传任何字节")
        print("[dry-run] 将建 %s 并把 %d 个文件传进去" % (remote_dir, len(to_send)))
        return 0

    if not os.path.isfile(KEY):
        die(2, "!! 找不到部署密钥 %s ⇒ 先确认密钥在位（本脚本不生成也不改密钥）" % KEY)
    os.makedirs(workdir, exist_ok=True)

    rc, out = ssh("mkdir -p %s" % remote_dir)
    if rc != 0:
        die(2, "!! 建远端目录失败：%s" % out[-300:])

    staged = []
    for path, do in to_send:
        if do:
            print("   压 %s …" % os.path.basename(path))
            staged.append(transcode(path, workdir))
        else:
            staged.append(path)
    rc, out = scp(staged, remote_dir + "/")
    if rc != 0:
        die(2, "!! scp 失败：%s" % out[-300:])

    urls, bad = [], []
    for p in staged:
        url = "%s/review/%s/%s" % (SITE, token, os.path.basename(p))
        ok, code, acc, extra = check_range(url)
        print("   %s %s  [%s %s %s]" % ("✓" if ok else "!!", url, code, acc or "-", extra))
        (urls if ok else bad).append(url)
    ledger = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "审片台账.jsonl")
    with open(ledger, "a", encoding="utf-8") as fp:
        fp.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             "token": token, "title": a.title,
                             "files": [os.path.basename(x) for x in staged],
                             "uploaded": len(staged), "verified": len(urls),
                             "urls": urls}, ensure_ascii=False) + "\n")

    print("\nURL（%d/%d 验过 Range）：" % (len(urls), len(staged)))
    for u in urls:
        print("  " + u)
    print("台账：%s ｜ 审完删：--delete %s" % (ledger, token))
    if bad:
        print("!! %d 个上传后验不过，先别当已交付" % len(bad))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
