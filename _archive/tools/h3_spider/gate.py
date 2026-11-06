# -*- coding: utf-8 -*-
"""跑前闸：证明 spider 批跑结果对得上当前项目；对不上就拒绝出片。"""
import hashlib
import json
import os
from typing import List, Optional, Tuple

from . import __version__ as SPIDER_VERSION
from .lexer import TOKENIZER_VERSION


def _sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_batch_gate(project: str, batch_dir: str,
                     shots: Optional[List[str]] = None) -> Tuple[bool, List[str], dict]:
    reasons = []
    vp = os.path.join(batch_dir, "batch_verdict.json")
    info = {"batch_dir": os.path.abspath(batch_dir), "version": SPIDER_VERSION}
    if not os.path.isfile(vp):
        return False, ["缺 batch_verdict.json：%s" % vp], info
    v = json.load(open(vp, encoding="utf-8"))
    info["overall"] = v.get("overall")
    if v.get("overall") != "PASS":
        reasons.append("spider 批跑判定为 %s" % v.get("overall"))

    ph = v.get("project_hashes") or {}
    if not ph:
        reasons.append("batch_verdict 没有 project_hashes，无法证明新鲜度")
        return False, reasons, info

    if ph.get("tokenizer") != TOKENIZER_VERSION:
        reasons.append("tokenizer 版本变了：%r -> %r"
                       % (ph.get("tokenizer"), TOKENIZER_VERSION))
    if ph.get("spider_version") != SPIDER_VERSION:
        reasons.append("spider 版本变了：%r -> %r"
                       % (ph.get("spider_version"), SPIDER_VERSION))

    for name, h in (ph.get("cards") or {}).items():
        p = os.path.join(project, name)
        if not os.path.isfile(p):
            reasons.append("卡文件不见了：%s" % name)
        elif _sha1_file(p) != h:
            reasons.append("卡文件在 spider 之后改过：%s" % name)

    check_shots = shots or sorted((v.get("shots") or {}).keys())
    info["checked_shots"] = check_shots
    for sid in check_shots:
        if sid not in (v.get("shots") or {}):
            reasons.append("%s 不在 spider 批跑结果里" % sid)
            continue
        expected = (ph.get("prompts") or {}).get(sid)
        p = os.path.join(project, "out", sid + ".txt")
        if expected is None:
            reasons.append("%s 没有记录 prompt 哈希" % sid)
        elif not os.path.isfile(p):
            reasons.append("%s 的渲染稿不见了" % sid)
        elif _sha1_file(p) != expected:
            reasons.append("%s 的渲染稿在 spider 之后改过" % sid)
        clean = os.path.join(batch_dir, sid, "clean.txt")
        if not os.path.isfile(clean):
            reasons.append("%s 缺 clean.txt（spider 影子稿）" % sid)
        elif os.path.isfile(p) and _sha1_file(clean) != _sha1_file(p):
            reasons.append("%s 的 clean.txt 与当前渲染稿不一致" % sid)

    for path, h in (ph.get("assets") or {}).items():
        if not os.path.isfile(path):
            reasons.append("资产在 spider 之后消失：%s" % path)
        elif _sha1_file(path) != h:
            reasons.append("资产在 spider 之后改过：%s" % path)

    return (not reasons), reasons, info
