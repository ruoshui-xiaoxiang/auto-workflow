# -*- coding: utf-8 -*-
"""阶段 D 存量迁移：把已散在暂存区/老归档点/log 区的产物归进 out\\<批次>\\。

一次性脚本，跑完留着备查。默认只打印计划，加 --apply 才动盘。
只 move 不删；目标重名则加 _1 序号（与 tasks.relocate 同规则）。

用法：
  python tools\\migrate_stage_d.py            # 看计划
  python tools\\migrate_stage_d.py --apply    # 真搬
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

# 10-02 批1 GAP-E1：交付根统一走 delivery_root()，别直接读 config 里那行字面量。
# （本脚本是一次性迁移件、已经跑过；但直接读字面量＝留一个"切项目后重跑会搬错地方"的雷，
#   顺手拆掉。行为今天不变，因为字面量当前仍是新鲜的，有 tests/test_delivery_root.py 钉着。）
sys.path.insert(0, str(ROOT))
from delivery_root import delivery_root  # noqa: E402

STAGING = Path(CFG["comfyui"]["output_dir"])   # ComfyUI_output（暂存）
LOGS = Path(CFG["log_dir"])                    # logs\workflows
OUT = Path(delivery_root(CFG))                 # out（交付根，按 project 派生）
AUTO_OUT = STAGING.parent / "auto_out"         # 一步式老归档点，一并收

IMG = re.compile(r"^(draft|refine|auto)_(\d{8}_\d{6})_")      # 产物文件名 -> (kind, run_id)
DOC = re.compile(r"^(image_draft_batch|image_refine|image_batch_draft)"
                 r"_(\d{8}_\d{6})\.(html|manifest\.json)$")   # 报告/manifest


def refine_parents():
    """从 status.json 读每次精修是被哪次草稿派生的，尽量把成品放回父批次夹。

    history 只留最近 30 条（run.py 的上限），更早的查不到 —— 那退化成用精修自己的
    run_id 建夹，并在 notes 里逐条说明这是退化，不假装准确。
    """
    sf = LOGS / "status.json"
    out = {}
    if sf.exists():
        try:
            hist = json.loads(sf.read_text(encoding="utf-8")).get("history") or []
        except Exception:
            hist = []
        for h in hist:
            if h.get("workflow") == "image_refine" and h.get("parent_run"):
                out[str(h["run_id"])] = str(h["parent_run"])
    return out


def target_for(name, parents, notes):
    """产物文件名 -> (批次号, 子目录)；查不到父草稿时如实记一条 note。"""
    m = IMG.match(name)
    kind, rid = m.group(1), m.group(2)
    if kind == "refine":
        if rid in parents:
            return parents[rid], "final"
        notes.append(f"{name}：status.json 里查不到父草稿，按精修自己的 run_id 建夹")
        return rid, "final"
    return rid, "draft" if kind == "draft" else "final"


def resolve_dst(src, dst_dir, notes):
    """算出目标路径，重名则加 _1 序号。返回 (源, 目标)，不建目录。"""
    to = dst_dir / src.name
    if to.exists():
        n = 1
        while (dst_dir / f"{src.stem}_{n}{src.suffix}").exists():
            n += 1
        to = dst_dir / f"{src.stem}_{n}{src.suffix}"
        notes.append(f"重名改名 {src.name} -> {to.name}")
    return src, to


def build_plan():
    parents = refine_parents()
    notes, moves = [], []

    for f in sorted(STAGING.iterdir()) if STAGING.is_dir() else []:
        if not (f.is_file() and IMG.match(f.name)):
            continue
        batch, stage = target_for(f.name, parents, notes)
        moves.append((f, OUT / batch / stage))
    if STAGING.is_dir():
        odd = [f.name for f in STAGING.iterdir() if f.is_file() and not IMG.match(f.name)]
        if odd:
            notes.append(f"暂存区有 {len(odd)} 个文件名不含 run_id、无法归批次，保持原位："
                         f"{odd[:5]}")

    for d in sorted(p for p in AUTO_OUT.iterdir() if p.is_dir()) if AUTO_OUT.is_dir() else []:
        for f in sorted(d.iterdir()):
            if f.is_file():
                moves.append((f, OUT / d.name / "final"))

    for f in sorted(LOGS.iterdir()) if LOGS.is_dir() else []:
        m = DOC.match(f.name) if f.is_file() else None
        if m:
            # 报告与 manifest 必须跟它的图进同一个夹：精修的图进父草稿夹，文件也进那里
            rid = parents.get(m.group(2), m.group(2)) if m.group(1) == "image_refine" else m.group(2)
            moves.append((f, OUT / rid))     # 报告与 manifest 进同一批次夹根

    plans, missing = [], []
    for src, dst_dir in moves:
        if not src.exists():
            missing.append(str(src))
            continue
        plans.append((src, dst_dir))
    return plans, notes, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真搬；不加只打印计划")
    a = ap.parse_args()
    plans, notes, missing = build_plan()
    for n in notes:
        print(f"[note] {n}")
    if missing:
        print(f"[FATAL] {len(missing)} 个源文件已不存在，中止：{missing[:3]}", file=sys.stderr)
        sys.exit(2)

    per_dir = {}
    for src, dst_dir in plans:
        key = str(dst_dir)
        per_dir[key] = per_dir.get(key, 0) + 1
    print(f"计划移动 {len(plans)} 个文件，落到 {len(per_dir)} 个目录")
    for k in sorted(per_dir):
        print(f"  {per_dir[k]:>4}  {k}")

    if not a.apply:
        print("dry-run 结束（未动盘）。确认无误后加 --apply")
        return

    def count_files():
        return sum(1 for p in OUT.rglob("*") if p.is_file()) if OUT.is_dir() else 0

    before = count_files()
    for src, dst_dir in plans:
        dst_dir.mkdir(parents=True, exist_ok=True)
        _, to = resolve_dst(src, dst_dir, notes)
        shutil.move(str(src), str(to))
    delta = count_files() - before
    print(f"完成：out\\ 内文件数增加 {delta}（计划移动 {len(plans)}）")
    if delta != len(plans):
        print("[FATAL] 数量不守恒，请检查", file=sys.stderr)
        sys.exit(3)
    left = [f.name for f in STAGING.iterdir()] if STAGING.is_dir() else []
    print(f"暂存区剩余 {len(left)} 项：{left[:5]}")


if __name__ == "__main__":
    main()
