#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""check_fight_storyboard.py · 打戏分镜三必填静态扫（只报不拦）

2026-10-08 用户裁定 P0。扫分镜 md/表格，找三列关键词是否出现：
  本场作用 / 优势易手 / 终结
缺列或列内容过短 → warn/error。机器判不了「写得好不好」，只判「填没填」。

用法：
  py check_fight_storyboard.py <分镜.md> [--strict]
"""
from __future__ import print_function
import argparse
import os
import re
import sys

COLS = [
    ("本场作用", r"本场作用|场景作用|这场戏|作用"),
    ("优势易手点", r"优势易手|易手|主动权|优势反转|力量关系"),
    ("终结如何被看见", r"终结|收势|结果.*看见|收尾定格|结束画面"),
]


def scan_text(text):
    hits = []
    for name, pat in COLS:
        m = re.search(pat, text)
        hits.append((name, bool(m)))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        print("NOT FOUND", args.path)
        return 1
    with open(args.path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    hits = scan_text(text)
    missing = [n for n, ok in hits if not ok]
    for n, ok in hits:
        print(("OK  " if ok else "MISS") + "  " + n)
    if missing:
        print("WARN 缺列：", " / ".join(missing))
        if args.strict:
            return 1
    else:
        print("PASS 三必填关键词均出现（内容质量仍须人审）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
