# -*- coding: utf-8 -*-
"""把分散在 D/E 盘的工作流文本内容镜像进 engine/_archive，供单一公开仓存档。

只收文本（代码 / 文档 / 配置 / 规则），不收二进制、媒体、缓存、日志。
源目录不动，镜像可随时重建；镜像里源侧已删除的文件会被同步删除。
"""
import os
import shutil
import sys
from pathlib import Path

REPO = Path(r"D:\AIWorkflow\engine")
MIRROR = REPO / "_archive"

TEXT_EXT = {
    ".py", ".md", ".json", ".jsonl", ".txt", ".bat", ".cmd", ".ps1", ".sh",
    ".yaml", ".yml", ".html", ".htm", ".js", ".mjs", ".css", ".csv", ".tsv",
    ".ini", ".cfg", ".toml", ".xml", ".iss", ".spec", ".pbtxt", ".sql",
    ".gitignore", ".gitattributes", ".orig", ".bak", ".conf", ".properties",
    ".jinja", ".j2", ".vue", ".ts", ".srt", ".ass",
}
KEEP_NAME = {".gitignore", ".gitattributes", "README", "LICENSE", "AGENTS.md"}
SKIP_NAME_SUFFIX = (".log", ".pyc", ".pyo")
MAX_SIZE = 4 * 1024 * 1024  # 单文件 4MB 上限：超出的基本是数据/日志，不是规则

SOURCES = [
    {
        "dest": "tools",
        "src": Path(r"D:\AIWorkflow\tools"),
        "dirs": None,  # None = 整棵子树
        "skip": {"__pycache__", ".pytest_cache", "debug_images", "models", ".git", "node_modules"},
    },
    {
        "dest": "spec",
        "src": Path(r"E:\本地工作流规范手册"),
        "dirs": None,
        "skip": {"__pycache__", ".git", "08_Qoder记忆_现行约定"},
    },
    {
        "dest": "wzy_rules",
        "src": Path(r"D:\AIWorkflow\tmp\wzy"),
        "dirs": [
            "",  # 仅根层文件，不递归
            "h3",
            "txt",
            "_b16",
            "正文归档_20260925_费管事改费主管",
            "正文归档_20260925_夹层改弱电井",
            "正文归档_20260925_身份术语改智能终端身份ID",
            "正文归档_20260925_语言时代纪律",
        ],
        "skip": {"__pycache__", ".git"},
    },
    {
        "dest": "h3",
        "src": Path(r"D:\AIWorkflow\ComfyUI_H3"),
        "dirs": [
            "",  # 仅根层文件
            "prompts",
            "prompts_官方三段式",
            "prompts_H3官方骨架",
            "advanced",
            "ab_taokan_20261015",
            r"ComfyUI\user\default\workflows",
            r"ComfyUI\user\default\workflows_archive",
        ],
        "skip": {"__pycache__", ".git"},
    },
    {
        "dest": "root",
        "src": Path(r"D:\AIWorkflow"),
        "files": ["AGENTS.md", "README.md", "官方路径.json"],
    },
]


def is_text(p: Path) -> bool:
    name = p.name.lower()
    if name.endswith(SKIP_NAME_SUFFIX):
        return False
    if p.name in KEEP_NAME:
        return True
    return p.suffix.lower() in TEXT_EXT


def iter_entries(entry):
    src = entry["src"]
    if not src.is_dir():
        return
    if "files" in entry:
        for rel in entry["files"]:
            p = src / rel
            if p.is_file():
                yield p, Path(rel)
        return
    skip = entry.get("skip", set())
    dirs = entry.get("dirs")
    if dirs is None:
        for dp, dn, fn in os.walk(src):
            dn[:] = [d for d in dn if d not in skip and not d.startswith(".git")]
            for f in fn:
                p = Path(dp) / f
                yield p, p.relative_to(src)
        return
    for rel in dirs:
        base = src / rel if rel else src
        if not base.is_dir():
            continue
        if not rel:
            for p in base.iterdir():
                if p.is_file():
                    yield p, Path(p.name)
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in skip and not d.startswith(".git")]
            for f in fn:
                p = Path(dp) / f
                yield p, p.relative_to(src)


def main():
    wanted = {}  # dest -> set(relative paths)
    copied = skipped = 0
    for entry in SOURCES:
        dest_root = entry["dest"]
        wanted[dest_root] = set()
        for p, rel in iter_entries(entry):
            if not is_text(p):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > MAX_SIZE:
                skipped += 1
                continue
            dst = MIRROR / dest_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            wanted[dest_root].add(rel.as_posix())
            copied += 1

    # 删除源侧已不存在的镜像文件
    removed = 0
    for dest_root, keep in wanted.items():
        root = MIRROR / dest_root
        if not root.is_dir():
            continue
        for dp, dn, fn in os.walk(root, topdown=False):
            for f in fn:
                p = Path(dp) / f
                rel = p.relative_to(root).as_posix()
                if rel not in keep:
                    p.unlink()
                    removed += 1
            if not os.listdir(dp):
                os.rmdir(dp)

    total = sum(len(v) for v in wanted.values())
    print("mirrored=%d removed=%d skipped_oversize=%d total_in_mirror=%d" % (copied, removed, skipped, total))
    for dest_root, keep in wanted.items():
        print("  %-10s %d" % (dest_root, len(keep)))


if __name__ == "__main__":
    sys.exit(main())
