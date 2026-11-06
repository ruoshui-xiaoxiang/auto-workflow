# -*- coding: utf-8 -*-
"""用 curl 过 Cloudflare 下载 civitai 文件，并对账官方 SHA256。

为什么不用 urllib：civitai 前置 Cloudflare，按客户端指纹拦非浏览器 UA（返回 403 / error code 1010）。
curl 能过 CF，但下载端点要登录态 ⇒ 带 Bearer key。

三条安全/正确性约定：
  1. key 不进 argv（进程表可见）、不落临时文件、不出现在 stdout/stderr——只经 stdin 交给 curl --config -。
  2. 第一跳带 Authorization 只为解析 302 Location；第二跳取 CDN 文件时**不带凭证**。
  3. 落盘后必须与 civitai 给的 SHA256 对上，不符就判废，不进步骤。
"""
import hashlib
import io
import os
import re
import subprocess
import sys
import time
import urllib.parse

TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{16,}")


def sanitize(s):
    """任何要打印的错误信息先过这里：把长字母数字串（可能是 key）抹掉。"""
    out = str(s)
    for m in set(TOKEN_RE.findall(out)):
        out = out.replace(m, "<已抹掉>")
    return out

KEY_FILE = r"E:\密钥文件\civitai.txt"
OUTDIR = r"D:\Models\ComfyUI\loras"
PROXY = "http://127.0.0.1:7890"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

JOBS = [
    ("ZIT_Midjourney_Luneva_Cinematic_v1_r128.safetensors",
     "https://civitai.com/api/download/models/2460437?fileId=2348879",
     "18401392AF09DBD3229E8107152996F18C69F6F4BF8F4DE9C4FCDFEEC93ADB21", 648.8),
    ("midj-z-1.safetensors",
     "https://civitai.com/api/download/models/2794215?fileId=2680247",
     "199126B1072A9CA507EECF46CDBF3AE4DA958C116EEE30B221BF4B3C4F9B9B3C", 162.2),
]


def get_key():
    raw = io.open(KEY_FILE, encoding="utf-8", errors="ignore").read().strip()
    m = re.search(r"[A-Za-z0-9_\-]{16,}", raw)
    if not m:
        raise SystemExit("密钥文件里没找到可用 token")
    return m.group(0)


def curl(cfg_lines):
    """把 curl 配置经 stdin 交进去，返回 (rc, stdout)。stdout 里不含 key。"""
    text = "\n".join(["silent", "show-error", 'user-agent = "%s"' % UA,
                      'proxy = "%s"' % PROXY, "max-time = 900"] + cfg_lines) + "\n"
    p = subprocess.run(["curl", "-K", "-"], input=text.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


class SoftFail(Exception):
    """瞬时故障（代理抖动／TLS 中断）⇒ 吃掉一轮重试，不打死整个循环。"""


def resolve(url, key):
    """第一跳：带 key 只为拿 Location。响应头打到 stdout 自己解。

    ⚠ 走代理时响应头里会先出现代理的 `HTTP/1.1 200 Connection established`，
    那不是源站状态——取**最后一条** HTTP/ 状态行，并跳过 CONNECT 那行。
    """
    rc, out, err = curl(['header = "Authorization: Bearer %s"' % key,
                         'url = "%s"' % url,
                         "max-redirs = 0", "output = NUL", "dump-header = -"])
    loc, code = "", "?"
    for line in out.splitlines():
        l = line.strip()
        if l.upper().startswith("HTTP/"):
            parts = l.split(None, 2)
            if len(parts) >= 3 and "connection established" in parts[2].lower():
                continue                     # 代理的 CONNECT 应答，不是源站状态
            code = parts[1] if len(parts) > 1 else "?"
        if l.lower().startswith("location:"):
            loc = l.split(":", 1)[1].strip()
    if code in ("301", "302", "303", "307", "308") and loc:
        print("  第一跳 %s → CDN 域 %s" % (code, urllib.parse.urlsplit(loc).netloc))
        return loc
    raise SoftFail("第一跳没拿到 Location：http=%s err=%s" % (code, err[:120]))


def fetch_once(url, tmp):
    """一跳取文件；已有 tmp 则断点续传。返回 (rc, 已落盘字节数, stderr)。"""
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    lines = ['url = "%s"' % url, "location", "output = \"%s\"" % tmp.replace("\\", "/"),
             'write-out = "http=%{http_code} bytes=%{size_download}"']
    if have:
        lines.append("continue-at = -")     # -C -：从已落盘处续
    else:
        lines.append("fail")
    rc, out, err = curl(lines)
    return rc, (os.path.getsize(tmp) if os.path.exists(tmp) else 0), err, out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            h.update(c)
    return h.hexdigest().upper()


def main():
    key = get_key()
    print("凭证：读到 %d 字符（全程不回显、不进 argv）" % len(key))
    os.makedirs(OUTDIR, exist_ok=True)
    bad = 0
    for name, url, want, mb in JOBS:
        dst = os.path.join(OUTDIR, name)
        tmp = dst + ".part"
        want_bytes = int(round(mb * 1024 * 1024))
        print("\n[%s] 约 %.1f MB" % (name, mb))
        if os.path.exists(dst) and sha256(dst) == want.upper():
            print("  盘上已有且哈希命中，跳过下载")
        else:
            if os.path.exists(dst):
                os.remove(dst)
            hit = False
            for attempt in range(1, 26):
                try:
                    loc = resolve(url, key)      # 每轮重取限时签名地址
                    rc, have, err, out = fetch_once(loc, tmp)
                    print("  第 %2d 轮：%s 累计 %d 字节（约需 %d）"
                          % (attempt, out.strip(), have, want_bytes))
                except SoftFail as e:
                    print("  第 %2d 轮：软失败（重试）%s" % (attempt, str(e)[:120]))
                    time.sleep(3)
                    continue
                except Exception as e:
                    print("  第 %2d 轮：异常（重试）%s" % (attempt, sanitize(str(e))[:120]))
                    time.sleep(3)
                    continue
                if os.path.exists(tmp) and sha256(tmp) == want.upper():
                    os.replace(tmp, dst)
                    hit = True
                    break
            if not hit:
                print("  🔴 25 轮仍未命中哈希，判废")
                bad += 1
        if not os.path.exists(dst):
            bad += 1
            continue
        got = os.path.getsize(dst)
        real = sha256(dst)
        ok = real == want.upper()
        print("  实得 %d 字节（%.1f MB）｜SHA256 %s… %s"
              % (got, got / 2**20, real[:16], "✅ 与 civitai 声明一致" if ok else "🔴 不符"))
        if not ok:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
