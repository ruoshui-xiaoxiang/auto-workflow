# -*- coding: utf-8 -*-
"""备份工具（09-28 磁盘整理时定稿，住在 tools 家）：`E:\\_统一备份` 成为唯一的备份树，并给出可重复执行的增量备份工具。

规矩：
  · 一份源在原地，一份备份在 E:\\_统一备份\\<类目>\\<时间戳>\\
  · 每次备份都写一个**全新的时间戳目录**（全量拷贝当前状态），类目内最多留 KEEP 份、旧的自动清
    ⇒ 备份模式下不存在"跳过"，`--check` 才是唯一能回答"备份是否落后于活区"的手段
  · `--check` 报两类问题：**缺**（备份里根本没这份）与**陈旧**（备份里有、但内容不等于活区）
    ★ 09-28 修：旧版 `--check` 只数"缺"，"陈旧"被静默丢掉 ⇒ 活区在备份之后改过，`--check` 照样报 0
      （实测：快照里 99,607 B / `6d8d41…` vs 活区 100,194 B / `16ca6c…`，旧版报「新 0」）。
      验收口径从今往后是**「缺 0 且 陈旧 0」**，不是只看那一个数。
  · 只备份**能重建一切的那部分**：规则手册、记忆、引擎配置与工作流、自产脚本、盘面对照表
  · 不复制 `E:\\密钥文件`——明文凭证多一份就多一次泄露面，只在清单里登记"位置"
  · 保留策略：每个类目最多留 KEEP 份，最旧的自动清（只清本工具自己建的目录，不碰别处）
"""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(r"E:\_统一备份")
KEEP = 5
CHUNK = 1 << 20

SETS = [
    # (类目, 源, 跳过子串, 允许的扩展名)
    ("手册", [r"E:\本地工作流规范手册"],
     ["\\_改前备份", "\\99_来源清单\\manifest.json"], None),
    ("记忆", [r"C:\Users\若水\.qoder\memory", r"C:\Users\若水\.qoder\projects"],
     ["\\sessions", "\\cache", "\\logs", "\\tmp", "\\node_modules", "\\_改前备份", "\\只读参考"],
     {".md"}),      # 用户记忆＋各项目记忆都是 .md，量很小；别用 "\\projects\\" 当排除词，那会把整类清空
    ("引擎配置", [r"D:\AIWorkflow\engine"],
     ["\\runs", "\\logs", "\\__pycache__", "\\批次", "\\_backup"],
     {".py", ".yaml", ".yml", ".json", ".md", ".bat", ".txt"}),
    ("自产脚本", [r"D:\AIWorkflow\tmp\wzy", r"D:\AIWorkflow\tools"],
     ["\\h3", "\\anchors", "\\dingzhuang", "\\__pycache__", "\\frames", "\\staging",
      "\\output", "\\logs", "\\node_modules", "\\prompts",
      "\\qcenv", "\\venv", "\\.venv", "\\site-packages", "\\python_embeded", "\\Lib"],
     {".py", ".bat"}),      # 只备份**自产代码**；虚拟环境/产物/日志/提示词正文各有自己的真源与归档
]

ONLY_EXT = {".py", ".yaml", ".yml", ".json", ".md", ".bat", ".txt", ".cfg", ".ini"}


def sha256(p):
    h = hashlib.sha256()
    with open(str(p), "rb") as f:
        for blk in iter(lambda: f.read(CHUNK), b""):
            h.update(blk)
    return h.hexdigest()


def latest(cat):
    ds = sorted([d for d in (ROOT / cat).iterdir() if d.is_dir()]) if (ROOT / cat).is_dir() else []
    return ds[-1] if ds else None


def run(set_filter="", check=False):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    total_new = 0
    report = {}
    for cat, srcs, skips, exts in SETS:
        exts = exts or ONLY_EXT
        if set_filter and set_filter != cat:
            continue
        prev = latest(cat)
        dst_root = ROOT / cat / (stamp if not check else (prev.name if prev else stamp))
        new, skipped, failed, stale = 0, 0, 0, 0
        rows = []
        for s in srcs:
            src = Path(s)
            if not src.is_dir():
                continue
            for cur, ds, fs in os.walk(str(src)):
                if any(k.strip("\\") in os.path.normpath(cur).replace("/", "\\") for k in skips):
                    ds[:] = []
                    continue
                for fn in sorted(fs):
                    if os.path.splitext(fn)[1].lower() not in exts:
                        continue
                    p = Path(cur) / fn
                    rel = p.relative_to(src)
                    try:
                        h = sha256(p)
                    except OSError:
                        failed += 1
                        continue
                    target = dst_root / src.name / rel
                    if target.is_file() and sha256(target) == h:
                        skipped += 1
                        continue
                    if check:
                        # ★09-28 修：旧版这里只数"备份里缺的"，文件在但内容≠活区（＝备份落后）
                        # 既不落 skipped 也不落 new，被静默丢掉 ⇒ --check 报 0 而最新快照其实是旧件。
                        # 而备份模式每次都写**全新的时间戳目录**（全量拷贝），所以"检测活区是否比快照新"
                        # 恰恰是 --check 唯一的本职工作，漏掉它等于把验收依据作废。
                        if not target.is_file():
                            new += 1      # 缺：备份里根本没有这份
                        elif sha256(target) != h:
                            stale += 1    # 陈旧：备份里有，但不是现行内容
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(str(p), str(target))
                        new += 1
                    except OSError as ex:
                        print("!! %s：%s" % (p, ex))
                        failed += 1
                        continue
                    rows.append([str(p), str(target), p.stat().st_size, h])
        if not check:
            dst_root.mkdir(parents=True, exist_ok=True)
            with open(dst_root / "manifest.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["src", "dst", "size", "sha256"])
                w.writerows(rows)
            (dst_root / "README.txt").write_text(
                "%s 类目 %s\n源：%s\n新备份 %d 个 / 已存在跳过 %d 个 / 失败 %d 个\n"
                "排除：%s\n恢复方法：按 manifest.csv 的 src 把 dst 文件复制回去即可。\n"
                % (time.strftime("%F %T"), cat, "、".join(srcs), new, skipped, failed,
                   "、".join(skips)), encoding="utf-8")
            # 保留策略：只清本工具建的、名字是 14 位数字的目录
            dirs = sorted([d for d in (ROOT / cat).iterdir()
                           if d.is_dir() and d.name.replace("_", "").isdigit()])
            for old in dirs[:-KEEP] if len(dirs) > KEEP else []:
                shutil.rmtree(str(old))
                print("  清掉过期的 %s\\%s（保留最近 %d 份）" % (cat, old.name, KEEP))
        report[cat] = dict(new=new, stale=stale, skipped=skipped, failed=failed, at=str(dst_root))
        print("%-6s %s %5d ｜陈旧 %5d ｜跳过 %6d ｜失败 %d ｜落点 %s"
              % (cat, "缺" if check else "新", new, stale, skipped, failed, dst_root))
        total_new += new + stale
    (ROOT / "last_run.json").write_text(json.dumps(
        {"at": time.strftime("%F %T"), "mode": "check" if check else "backup",
         "report": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n%s：%d 个文件需要处理" % ("检查" if check else "备份", total_new))
    return 0 if total_new == 0 or not check else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只报备份里缺什么，不写")
    ap.add_argument("--only", default="", help="只做某一个类目")
    a = ap.parse_args()
    ROOT.mkdir(exist_ok=True)
    sys.exit(run(a.only, a.check))


if __name__ == "__main__":
    main()
