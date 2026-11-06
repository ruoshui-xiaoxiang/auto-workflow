#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 〔为什么没人调用但保留 · 2026-10-19 治理批〕
#   即梦技能包 **真源 → 镜像** 的同步器（2026-10-08 用户裁定）：
#   真源 `E:\创作\即梦技能包\skills`，镜像 `.qoder\skills`；**只 copy、不删多余**。
#   为什么没有调用方：它是人手动跑的基础设施脚本——改技能只改真源，改完跑它一次。
#   🔴 规矩：绝不在镜像里直接改（下次同步会被真源覆盖，改动静默丢失）。
r"""sync_jimeng_skills.py · 即梦技能包 -> .qoder 镜像（2026-10-08 用户裁定）

真源 = E:\创作\即梦技能包\skills
镜像 = C:\Users\若水\.qoder\skills
只 copy 不删多余；改技能只改真源后跑本脚本。
"""
import os, sys, hashlib, shutil

SRC = r"E:\创作\即梦技能包\skills"
MIRROR = r"C:\Users\若水\.qoder\skills"

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

def main():
    if not os.path.isdir(SRC):
        print("SRC missing", SRC); return 1
    os.makedirs(MIRROR, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(SRC)):
        sroot = os.path.join(SRC, name)
        if not os.path.isdir(sroot):
            continue
        for dp, dn, fn in os.walk(sroot):
            dn[:] = [x for x in dn if x not in ("__pycache__", ".git")]
            rel_dir = os.path.relpath(dp, sroot)
            for f in fn:
                sp = os.path.join(dp, f)
                tp = os.path.join(MIRROR, name, rel_dir, f) if rel_dir != "." else os.path.join(MIRROR, name, f)
                os.makedirs(os.path.dirname(tp), exist_ok=True)
                if not os.path.isfile(tp) or sha(sp) != sha(tp):
                    shutil.copy2(sp, tp)
                    print("SYNC", name, os.path.relpath(sp, sroot))
                    n += 1
    print("updated", n)
    return 0

if __name__ == "__main__":
    sys.exit(main())
