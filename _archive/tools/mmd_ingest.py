#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mmd_ingest.py — MiniMax Design 参考图入库（只复制，不删源文件）

把 MiniMax Design 导出到 output_files\\ 的图，复制进《无音》规范参考图目录并登记版本。
源文件一律保留不动（用户要求：搬=复制，别把源文件移走）。

用法（命令行）:
  py mmd_ingest.py scan                   # 只读：列出 output_files 里有哪些图、哪些已入库
  py mmd_ingest.py ingest                 # 把新图复制到 定妆\\minimax_design\\ 并登记
  py mmd_ingest.py ingest --role 场景     # 复制到 场景\\minimax_design\\
  py mmd_ingest.py ingest --dry-run       # 预演：只打印会做什么，不真正复制
  py mmd_ingest.py ingest --match "wasteland*"  # 只处理文件名匹配的图
  py mmd_ingest.py report                 # 打印已入库历史

免终端：双击同目录下的 参考图入库.bat。
"""

import os
import sys
import json
import shutil
import hashlib
import argparse
import fnmatch
from datetime import datetime

SOURCE = r"E:\hailluoai\MiniMax Design\current Data\output_files"
DEST_ROOT = r"E:\创作\无音项目\图"
MANIFEST = os.path.join(DEST_ROOT, "minimax_design_manifest.json")
IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ROLES = {"定妆", "场景", "道具"}


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"[warn] MANIFEST 损坏，重新初始化: {MANIFEST}")
    return {"version": 1, "entries": []}


def save_manifest(m):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def source_images():
    if not os.path.isdir(SOURCE):
        print(f"[error] 源目录不存在: {SOURCE}")
        sys.exit(1)
    items = []
    for name in sorted(os.listdir(SOURCE)):
        p = os.path.join(SOURCE, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in IMG_EXTS:
            items.append((name, p))
    return items


def cmd_scan(manifest):
    ingested_hashes = {e["sha256"] for e in manifest["entries"]}
    rows = []
    for name, p in source_images():
        h = sha256_of(p)
        state = "已入库" if h in ingested_hashes else "新"
        rows.append((name, os.path.getsize(p), h[:12], state))
    if not rows:
        print("output_files 里没有图片文件。")
        return
    print(f"{'状态':<5}{'大小':>10}   sha256(前12)      文件名")
    for name, size, h12, state in rows:
        print(f"{state:<5}{size:>10,}   {h12}  {name}")
    new_n = sum(1 for r in rows if r[3] == "新")
    print(f"\n共 {len(rows)} 张图，其中新图 {new_n} 张。")


def unique_dest(dest_dir, name):
    base, ext = os.path.splitext(name)
    candidate = name
    i = 2
    while os.path.exists(os.path.join(dest_dir, candidate)):
        candidate = f"{base}_{i}{ext}"
        i += 1
    return candidate


def cmd_ingest(manifest, role, dry_run, match):
    if role not in ROLES:
        print(f"[error] 未知角色目录: {role}（可选: {' / '.join(sorted(ROLES))}）")
        sys.exit(1)
    ingested_hashes = {e["sha256"] for e in manifest["entries"]}
    plan = []  # (src_path, dest_path, size, sha256, src_name)
    for name, p in source_images():
        if match and not fnmatch.fnmatch(name.lower(), match.lower()):
            continue
        h = sha256_of(p)
        if h in ingested_hashes:
            continue
        dest_dir = os.path.join(DEST_ROOT, role, "minimax_design")
        dest_name = unique_dest(dest_dir, name)
        plan.append((p, os.path.join(dest_dir, dest_name), os.path.getsize(p), h, name))

    if not plan:
        print("没有需要入库的新图（都已登记，或没有匹配 --match 的文件）。")
        return

    print(f"将入库 {len(plan)} 张 → 角色目录「{role}」:")
    for src, dst, size, h, name in plan:
        print(f"  {name}  ({size:,} B)  →  {dst}")

    if dry_run:
        print("\n[dry-run] 未做任何修改。")
        return

    for src, dst, size, h, name in plan:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)  # 只复制，不动源文件
        manifest["entries"].append({
            "source": name,
            "dest": dst,
            "role": role,
            "size": size,
            "sha256": h,
            "ingested_at": datetime.now().isoformat(timespec="seconds"),
        })
        print(f"  已复制: {os.path.basename(dst)}")
    save_manifest(manifest)
    print(f"\n完成。源文件保留在 output_files，未删除。")


def cmd_report(manifest):
    entries = manifest["entries"]
    if not entries:
        print("MANIFEST 为空（还没入库过任何图）。")
        return
    for e in entries:
        print(f"[{e.get('role', '?')}] {e.get('source')}  →  {e.get('dest')}  ({e.get('ingested_at', '')})")


def main():
    ap = argparse.ArgumentParser(description="MiniMax Design 参考图入库")
    ap.add_argument("cmd", choices=["scan", "ingest", "report"])
    ap.add_argument("--role", default="定妆", help="目标角色目录（定妆/场景/道具），默认定妆")
    ap.add_argument("--match", default="", help="文件名 glob 过滤（如 wasteland*）")
    ap.add_argument("--dry-run", action="store_true", help="只预演不真正复制")
    args = ap.parse_args()

    manifest = load_manifest()
    if args.cmd == "scan":
        cmd_scan(manifest)
    elif args.cmd == "ingest":
        cmd_ingest(manifest, args.role, args.dry_run, args.match)
    elif args.cmd == "report":
        cmd_report(manifest)


if __name__ == "__main__":
    main()
