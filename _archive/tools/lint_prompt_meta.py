#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""lint_prompt_meta.py · 提示词元指令/结果描述扫描（只报不拦）2026-10-08 R3 §五

用法: py lint_prompt_meta.py <prompt.txt>
"""
import re, sys

PATS = [
    (r"must stay visible", "元指令：保持可见"),
    (r"zero dead air", "元指令：无空档"),
    (r"End pose is the next", "元指令：末帧=下镜"),
    (r"ALL established damage", "元指令：损伤账本"),
    (r"keep first-frame costumes", "元指令：保持服装"),
    (r"reframes hard on impacts", "结果式运镜描述"),
    (r"tracks large moves", "双运镜/结果描述风险"),
    (r"Camera tracks.*Camera ", "疑似双运镜"),
]

def main():
    if len(sys.argv) < 2:
        print("usage: lint_prompt_meta.py file"); return 1
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    hits = []
    for pat, why in PATS:
        for m in re.finditer(pat, text, re.I):
            hits.append((why, m.group(0)[:40]))
    if not hits:
        print("OK 未命中元指令清单")
        return 0
    for why, frag in hits:
        print("WARN", why, "|", frag)
    print("提示：元指令不产生画面，移到分镜备忘；正文只写本镜物理（R3 §五）")
    return 0

if __name__ == "__main__":
    sys.exit(main())
