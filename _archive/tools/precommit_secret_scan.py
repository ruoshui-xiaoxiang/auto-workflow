# -*- coding: utf-8 -*-
"""pre-commit 钩子：扫描暂存区内容。

阻断：凭证类（私钥/token/sk-/AK/Slack/JWT/URL 带凭据/DB 连接串/赋值型 secret/Bearer）、
      身份证号、明显二进制大件（safetensors/mp4/exe/zip/wav 等）、单文件 >5MB。
告警（不阻断）：手机号/邮箱/私网 IP —— 需人工判断是否真实 PII。
"""
import re
import subprocess
import sys

BLOCK_EXT = (
    ".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".bin", ".gguf",
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".wav", ".mp3", ".flac",
    ".exe", ".dll", ".pyd", ".so", ".zip", ".7z", ".rar", ".gz", ".tar",
    ".pyc", ".pyo",
)
MAX_SIZE = 5 * 1024 * 1024

BLOCK_PATTERNS = [
    ("私钥", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("sk- 密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("AWS AK", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("URL 带凭据", re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]{1,64}:[^/\s@]{1,64}@")),
    ("DB 连接串", re.compile(r"(mysql|postgres(?:ql)?|mongodb|redis|mssql|oracle)://[^\s\"']{4,}:[^\s\"']{4,}@", re.I)),
    ("Bearer", re.compile(r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+([A-Za-z0-9_\-\.=]{16,})")),
    ("身份证", re.compile(r"(?<![0-9])[1-9][0-9]{5}(19|20)[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[0-9]{3}[0-9Xx](?![0-9])")),
]

WARN_PATTERNS = [
    ("手机号", re.compile(r"(?<![0-9])1[3-9][0-9]{9}(?![0-9])")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("私网 IP", re.compile(r"\b(?:10\.[0-9]{1,3}|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}\b")),
]


def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout


def main():
    files = [f for f in git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines() if f]
    blocked, warned = [], []
    for f in files:
        low = f.lower()
        if low.endswith(BLOCK_EXT):
            blocked.append((f, "二进制/媒体扩展名被禁止入库"))
            continue
        try:
            size = len(git("show", ":" + f).encode("utf-8"))
        except Exception:
            continue
        if size > MAX_SIZE:
            blocked.append((f, "单文件 %.1f MB 超过 5 MB" % (size / 1048576.0)))
            continue
        content = git("show", ":" + f)
        for name, rx in BLOCK_PATTERNS:
            m = rx.search(content)
            if m:
                line = content[:m.start()].count("\n") + 1
                blocked.append((f, "%s（第 %d 行）" % (name, line)))
        for name, rx in WARN_PATTERNS:
            m = rx.search(content)
            if m:
                line = content[:m.start()].count("\n") + 1
                warned.append((f, "%s（第 %d 行）" % (name, line)))

    if warned:
        print("[pre-commit] 告警（不阻断，请确认不是真实 PII）：")
        for f, why in warned:
            print("  - %s : %s" % (f, why))
    if blocked:
        print("[pre-commit] 已阻断，以下内容不得进入公开仓：")
        for f, why in blocked:
            print("  - %s : %s" % (f, why))
        return 1
    print("[pre-commit] 通过，%d 个文件" % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
