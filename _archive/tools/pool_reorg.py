#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pool_reorg.py — 把散落的无音项目视频/图片/音频，按 **AGENTS.md 第一节的类别规范**
收集进 E:\\图像影音资源池\\<项目>\\{视频,图像,素材,音频}。

为什么不用"按来源"两层结构：用户裁定 —— 两层多占一份内存，没必要。
所以类别口径完全沿用现有规范：
    视频 = 成品/交付片        图像 = 出图最终成品
    素材 = 抽帧·参考·QC·中间稿·测试片·冷数据
    音频 = 配音/BGM/音效

规矩：
  - **只复制，不删源**（第三方 App 自有目录如 output_files 尤其要保源）
  - 保留相对路径落位（避免 frame_0000.png 之类同名互撞、保住出处）
  - 输出双向 MANIFEST（源↔目标）+ sha256，落在 池内 _归档_MANIFEST\\<日期>\\
  - **dry-run 默认**：只打印+出清单，不复制

用法:
  py pool_reorg.py scan        # 只读：各来源数量 + 分类预览
  py pool_reorg.py dry-run     # 出完整「源→目标」清单 CSV（不复制）
  py pool_reorg.py ingest      # 真正复制（带 sha256 校验）
  py pool_reorg.py purge --root <目录> [--root ...]
                               # 删源。删前逐文件 sha256 复核池内副本，
                               # 副本缺失/不符的一律不删（保守）。只删文件，
                               # 再清掉变空的子目录；根目录本身保留。
免终端：双击同目录下的 素材入库.bat
"""

import os, sys, csv, shutil, hashlib, argparse
from datetime import datetime

POOL = r"E:\图像影音资源池"          # 交付层根
DEFAULT_PROJECT = "无音"

# ---------------------------------------------------------------- 来源表
# img/vid = 该来源下 图片/视频 各自默认归到哪一类
# flat    = 只看目录第一层（不递归），用于桌面这种"混放"的目录
# vid_root_only = 视频只有在来源根目录才算出片（renders 里成品永远导出到根，
#                 子目录里的 .mp4 都是迭代草稿 → 素材）
SOURCES = [
    dict(root=r"E:\hailluoai\MiniMax Design\current Data\Projects\无音_virtual_production\renders",
         project="无音", img="素材", vid="视频", vid_root_only=True,
         tag="虚拟制作工作区（成品导出到根，子目录皆迭代稿）"),
    dict(root=r"E:\hailluoai\MiniMax Design\current Data\output_files",
         project="无音", img="素材", vid="视频",
         tag="海螺导出（定妆图/封面=参考，mp4=导出片）"),
    dict(root=r"D:\AIWorkflow\ComfyUI_H3\output",
         project="无音", img="素材", vid="素材",
         tag="H3 引擎暂存（已交付的由引擎搬进批次，剩下的是测试/迭代）"),
    dict(root=r"D:\AIWorkflow\tmp\staging",
         project="无音", img="素材", vid="素材",
         tag="引擎暂存（临时中间产物）"),
    dict(root=r"D:\AIWorkflow\tmp\frames",
         project="无音", img="素材", vid="素材",
         tag="抽帧"),
    dict(root=r"E:\创作\仙戮双生",
         project="无音", img="素材", vid="视频",
         tag="成品交片（镜1/2/4/5/6 + 合并成片 + bgm 试听）"),
    dict(root=r"E:\创作\_待审文档",
         project="无音", img="素材", vid="视频", flat=True,
         tag="桌面散落（仅第一层，找到啥算啥）"),
]

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}

# 视频里判为「素材」（灰模/previz/QC/测试）的名字特征
VID_SUCAI_PAT = ("gray_", "previz", "contact", "compare", "aud_guided", "_test",
                 "dreamina_test", "temp", "preview")
# 图片里判为「成品图」的名字特征。
# 注：这 7 个来源里没有"出图最终成品"（成品图都在 批次\\ 与 E:\\创作\\无音项目\\图\\），
# 所以留空 → 图片一律按来源的 img 口径走（本批全部 = 素材）。
IMG_FINAL_PAT = ()

# 直接跳过的目录/文件（第三方缓存、日志、非图文）
SKIP_DIR = {".hilo", "__pycache__", ".git", "__manager", ".cache", "node_modules"}
SKIP_EXT = {".txt", ".csv", ".json", ".log", ".py", ".js", ".md", ".bat", ".ps1",
            ".exe", ".dll", ".lnk", ".ini", ".yaml", ".yml", ".toml", ".cfg"}


def category_of(src, rel, name, s):
    ext = os.path.splitext(name)[1].lower()
    low = rel.lower().replace("\\", "/")
    if ext in VIDEO_EXTS:
        if any(p in low for p in VID_SUCAI_PAT):
            return "素材"
        if s.get("vid_root_only") and ("/" in low):
            return "素材"
        return s["vid"]
    if ext in IMAGE_EXTS:
        if any(p in low for p in IMG_FINAL_PAT):
            return "图像"
        return s["img"]
    if ext in AUDIO_EXTS:
        return "音频"
    return None


def iter_files(root, flat=False):
    if flat:
        try:
            for fn in os.listdir(root):
                p = os.path.join(root, fn)
                if os.path.isfile(p):
                    yield p, fn
        except OSError:
            return
        return
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIR]
        for fn in fns:
            yield os.path.join(dp, fn), fn


def sha256_of(p, buf=1 << 16):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_dst(dst):
    if not os.path.exists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    i = 1
    while os.path.exists(f"{stem}__{i}{ext}"):
        i += 1
    return f"{stem}__{i}{ext}"


def newest_manifest():
    base = os.path.join(POOL, "_归档_MANIFEST")
    subs = [d for d in (os.path.join(base, x) for x in os.listdir(base))
            if os.path.isdir(d)]
    return sorted(subs)[-1]


def under(path, root):
    p = os.path.normcase(os.path.abspath(path)) + os.sep
    r = os.path.normcase(os.path.abspath(root)) + os.sep
    return p.startswith(r)


def cmd_purge(roots):
    if not roots:
        print("purge 需要至少一个 --root <来源目录>")
        return
    man = newest_manifest()
    csv_path = os.path.join(man, "pool_reorg_map.csv")
    if not os.path.isfile(csv_path):
        print(f"找不到清单: {csv_path}")
        return
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig"))
            if any(under(r["src"], rt) for rt in roots)]
    print(f"清单 {man}；命中删除范围 {len(rows)} 个文件\n")

    deleted, kept, freed = 0, [], 0
    touched = set()
    for r in rows:
        src, dst = r["src"], r["dst"]
        if not os.path.isfile(src):
            kept.append((src, "源已不在"))
            continue
        if not os.path.isfile(dst) or os.path.getsize(dst) != int(r["bytes"]):
            kept.append((src, "池内副本缺失/大小不符"))
            continue
        if sha256_of(dst) != sha256_of(src):
            kept.append((src, "sha256 不符"))
            continue
        try:
            os.remove(src)
            deleted += 1
            freed += os.path.getsize(dst)
            touched.add(os.path.dirname(src))
        except Exception as e:
            kept.append((src, str(e)))

    print(f"[purge] 已删 {deleted} 个（约 {freed/1024**3:.2f} GB）；保留 {len(kept)} 个")
    for s_, why in kept[:15]:
        print(f"   ! 未删 {s_} :: {why}")

    # 只清理被删文件所在的那几层空目录（自下而上），绝不动无关空目录
    def is_root(p):
        return any(os.path.normcase(os.path.abspath(p)) ==
                   os.path.normcase(os.path.abspath(rt)) for rt in roots)
    for dp in sorted(touched, key=len, reverse=True):
        cur = dp
        while os.path.isdir(cur) and not is_root(cur):
            try:
                if os.listdir(cur):
                    break
                parent = os.path.dirname(cur)
                os.rmdir(cur)
                cur = parent
            except OSError:
                break
    print("[purge] 空目录已清理；根目录保留。MANIFEST 仍在: " + man)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "dry-run", "ingest", "purge"])
    ap.add_argument("--root", action="append", default=[],
                    help="purge: 只删该来源目录下的源文件，可重复")
    a = ap.parse_args()
    if a.cmd == "purge":
        cmd_purge(a.root)
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    man_dir = os.path.join(POOL, "_归档_MANIFEST", stamp)
    rows, per, skipped = [], {}, []

    for s in SOURCES:
        root, proj = s["root"], s["project"]
        if not os.path.isdir(root):
            print(f"[skip] 不存在: {root}")
            continue
        n = 0
        for src, fn in iter_files(root, s.get("flat", False)):
            cat = category_of(src, os.path.relpath(src, root), fn, s)
            ext = os.path.splitext(fn)[1].lower()
            if cat is None:
                if ext and ext not in SKIP_EXT and ext not in (".db", ".tmp", ".part"):
                    skipped.append(src)
                continue
            rel = os.path.relpath(src, root)
            dst = os.path.join(POOL, proj, cat, rel)   # 保相对路径，防同名互撞
            rows.append({"project": proj, "category": cat, "src": src, "dst": dst,
                         "bytes": os.path.getsize(src), "source_root": root,
                         "rule": f'{s["tag"]}'})
            per.setdefault((proj, cat), []).append(src)
            n += 1
        print(f'[scan] {os.path.basename(root)[:36]:38s} → {proj}  {n:5d} 个  ({s["tag"]})')

    print("\n=== 分类统计 ===")
    for (proj, cat), v in sorted(per.items()):
        tot = sum(os.path.getsize(x) for x in v) / 1024**3
        print(f"  {proj} / {cat:4s} {len(v):5d} 个  {tot:6.2f} GB")
    if skipped:
        print(f"  （另有 {len(skipped)} 个非图文扩展名文件，跳过不收集）")

    tiny = [r for r in rows
            if os.path.splitext(r["src"])[1].lower() in (VIDEO_EXTS | AUDIO_EXTS)
            and r["bytes"] < 20 * 1024]
    if tiny:
        print(f"\n⚠ 可疑小文件（视频/音频 <20KB，可能是坏渲染，建议跳过）共 {len(tiny)} 个：")
        for r in tiny:
            print(f"   {r['bytes']:7d} B  {r['src']}")

    if a.cmd == "scan":
        return

    os.makedirs(man_dir, exist_ok=True)
    csv_path = os.path.join(man_dir, "pool_reorg_map.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n[清单] {csv_path}（{len(rows)} 行）")

    if a.cmd == "dry-run":
        print("[dry-run] 未复制任何文件。确认清单后再跑 ingest。")
        for (proj, cat), v in sorted(per.items()):
            ex = ", ".join(os.path.basename(x) for x in v[:3])
            print(f"  {proj}/{cat} 例: {ex}")
        return

    done, fail = 0, []
    for r in rows:
        os.makedirs(os.path.dirname(r["dst"]), exist_ok=True)
        dst = unique_dst(r["dst"])
        try:
            shutil.copy2(r["src"], dst)
            if os.path.getsize(dst) != r["bytes"] or sha256_of(dst) != sha256_of(r["src"]):
                fail.append((r["src"], "校验不符"))
                continue
            done += 1
        except Exception as e:
            fail.append((r["src"], str(e)))
    print(f"\n[ingest] 复制 {done}/{len(rows)} 个；失败 {len(fail)}")
    for s_, why in fail[:10]:
        print(f"   ! {s_} :: {why}")
    print(f"[ingest] 源文件全部保留未动。MANIFEST: {man_dir}")


if __name__ == "__main__":
    main()
