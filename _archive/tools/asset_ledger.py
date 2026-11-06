#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""asset_ledger.py · 项目资产台账（治理批新功能②，2026-10-19）

解决什么
--------
用户痛点 #3「一致性很难保证，一换题材就又要重新测试」有一半是**资产层面**的：
同一批镜头里的角色造型、场景陈设、关键道具、空间站位必须前后一致，但盘上只有
`E:\\创作\\<项目>\\assets\\{cast,movie-set,props,构图}\\<名字>\\<文件>` 这么一棵裸目录树——
**没有任何一处能回答**「这个角色定妆定了吗、这张是沿用的还是新出的、道具缺不缺、
第 7 镜该用哪张站位图」。于是每次开批都要人肉翻目录，翻漏了就是接戏崩。

漫剧老李 V7.4.20 的「三清单」（角色／道具／场景分离）对应的就是这件事。核实后我们与它
**互补的缺口只有两块**：① 道具没被当资产登记（盘上有 `props\\` 目录但没有台账）
② 机位格（G）这一类根本还没有目录。其余（cast / movie-set / 构图·站位）盘上已有结构，
所以本工具**不另起平行结构**，直接长在既有目录树上。

台账形态（用户 2026-10-19 裁定 D13：**资产默认不跨项目复用 ⇒ 每项目一份**，不做全局统一库）
    E:\\创作\\<项目 asset_dir>\\assets\\ledger.csv
    schema ＝ `E:\\创作\\人物角色库\\_meta\\characters.csv` 的既有 10 列 ＋ 3 列：
        编号,名称,主题,画幅,通道,模型,分辨率,提示词,文件路径,日期,
        状态,交叉索引,首次出现
    编号前缀：C=角色 P=道具 S=场景 G=机位格 B=站位

`状态` 只许这四个值（**禁止自造**，自造＝第二套口径）：
    ⏳待生成 / 🔄沿用已有 / ✅已生成 / ❌待确认

用法
----
    py asset_ledger.py --project 武昭君仪 --init      # 建空台账（只写表头）
    py asset_ledger.py --project 武昭君仪 --scan      # 扫目录树，把没登记的文件补成 ❌待确认
    py asset_ledger.py --project 武昭君仪 --check     # 校验（默认动作）
    py asset_ledger.py --project 武昭君仪 --xlsx      # 导出 xlsx（主表 + 标签反查）
    py asset_ledger.py --list-projects                # 列出有 assets 目录的项目

只读默认：`--check` 不写任何文件。`--scan` 会写 ledger.csv，写前留 `.bak-<日期>`。
"""
import argparse
import csv
import io
import os
import re
import sys
from datetime import date

CREATION_ROOT = r"E:/创作"
GLOBAL_CHARACTERS = r"E:/创作/人物角色库/_meta/characters.csv"
PROJECTS_REGISTRY = r"D:/AIWorkflow/engine/projects_registry.json"
LEDGER_NAME = "ledger.csv"

COLUMNS = ["编号", "名称", "主题", "画幅", "通道", "模型", "分辨率", "提示词",
           "文件路径", "日期", "状态", "交叉索引", "首次出现"]

# 编号前缀 ↔ assets 下的子目录。盘上已有的三类照抄现名，不为了"整齐"去改目录。
PREFIX_OF_DIR = {
    "cast": "C",         # 角色（定妆／造型）
    "props": "P",        # 道具
    "movie-set": "S",    # 场景（无人母版）
    "构图": "B",          # 站位／构图（有人）
    "机位格": "G",        # 机位格 —— 🔴 盘上还没有这个目录，是核实的两块缺口之一
}
DIR_OF_PREFIX = {v: k for k, v in PREFIX_OF_DIR.items()}
PREFIX_MEANING = {"C": "角色", "P": "道具", "S": "场景", "G": "机位格", "B": "站位"}

STATUSES = ("⏳待生成", "🔄沿用已有", "✅已生成", "❌待确认")

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
TODAY = date.today().isoformat()


def rd(p):
    try:
        return io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def load_projects():
    """{id: asset_dir}。asset_dir 为 None 的项目（如 抖音人物）没有 E:/创作 落点。"""
    import json
    try:
        d = json.loads(rd(PROJECTS_REGISTRY))
    except Exception as e:
        return {}, "projects_registry.json 读不了：%s" % e
    out = {}
    for p in (d.get("projects") or []):
        if isinstance(p, dict) and p.get("id"):
            out[p["id"]] = p.get("asset_dir")
    return out, None


def assets_dir(project):
    projs, why = load_projects()
    if why:
        return None, why
    if project not in projs:
        return None, ("项目 `%s` 没在 projects_registry.json 里声明（那份表是项目声明的唯一真源）。"
                      "在册的有：%s" % (project, "、".join(sorted(projs))))
    ad = projs[project]
    if not ad:
        return None, ("项目 `%s` 的 asset_dir 是 null ⇒ E:/创作 下没有对应目录，台账无处可落。"
                      "先在 projects_registry.json 里补 asset_dir。" % project)
    d = os.path.join(CREATION_ROOT, ad, "assets")
    if not os.path.isdir(d):
        return None, "assets 目录不在盘上：%s（先 --init 或手动建）" % d
    return d, None


def read_ledger(path):
    if not os.path.isfile(path):
        return [], None
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        rows = [dict(x) for x in r]
        return rows, (r.fieldnames or [])


def write_ledger(path, rows):
    if os.path.isfile(path):
        bak = path + ".bak-" + TODAY.replace("-", "")
        if not os.path.exists(bak):
            io.open(bak, "w", encoding="utf-8", newline="").write(rd(path))
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    os.replace(tmp, path)          # 原子写：中途崩了不会留下半份 csv


def scan_tree(adir):
    """扫 assets 目录树，产出 (前缀, 名字, 相对路径, 绝对路径, 字节)。

    盘上既有约定是 `<类别目录>\\<名字>\\<文件>`（实测武昭君仪：cast\\君仪\\portrait1.png、
    props\\木椅-左端\\prop1.jpg、构图\\小Q位置\\q-地上.jpg）。**照它读，不改它。**
    """
    out = []
    for sub, pre in sorted(PREFIX_OF_DIR.items()):
        base = os.path.join(adir, sub)
        if not os.path.isdir(base):
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = [x for x in dns if x != "__pycache__"]
            for f in sorted(fns):
                if not f.lower().endswith(IMG_EXT):
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, adir).replace("\\", "/")
                parts = rel.split("/")
                name = parts[1] if len(parts) >= 3 else os.path.splitext(f)[0]
                out.append((pre, name, rel, p, os.path.getsize(p)))
    return out


def next_id(rows, prefix):
    n = 0
    for r in rows:
        m = re.match(r"^%s(\d+)$" % prefix, str(r.get("编号", "")).strip())
        if m:
            n = max(n, int(m.group(1)))
    return "%s%03d" % (prefix, n + 1)


def do_init(path, force=False):
    if os.path.isfile(path) and not force:
        print("=  台账已存在，不覆盖：%s（要重建加 --force，会先留 .bak）" % path)
        return 0
    write_ledger(path, [])
    print("+  已建空台账：%s" % path)
    print("   %d 列：%s" % (len(COLUMNS), "、".join(COLUMNS)))
    return 0


def do_scan(adir, path):
    rows, _ = read_ledger(path)
    if rows is None:
        rows = []
    have = {str(r.get("文件路径", "")).strip().replace("\\", "/") for r in rows}
    disk = scan_tree(adir)
    added = 0
    for pre, name, rel, ap, sz in disk:
        if rel in have or ap.replace("\\", "/") in have:
            continue
        rows.append({
            "编号": next_id(rows, pre),
            "名称": name,
            "主题": "",
            "画幅": "",
            "通道": "",
            "模型": "",
            "分辨率": "",
            "提示词": "",
            "文件路径": ap,
            "日期": TODAY,
            # 🔴 一律标 ❌待确认，**不自动标 ✅已生成**。
            # 文件在盘上 ≠ 它是被选定的那一张：定妆要人眼过（记忆库「关键帧必须人工目审闸」），
            # 而且同目录下常有 portrait1/portrait2 多版，机器不知道哪版是准的。
            "状态": "❌待确认",
            "交叉索引": "",
            "首次出现": TODAY,
        })
        added += 1
    if added:
        write_ledger(path, rows)
    print("扫 %s：盘上 %d 个图文件／台账原有 %d 行 ⇒ 新增 %d 行（全部标 ❌待确认）"
          % (adir, len(disk), len(rows) - added, added))
    miss_dir = [d for d in PREFIX_OF_DIR if not os.path.isdir(os.path.join(adir, d))]
    if miss_dir:
        print("⚠ assets 下缺这些类别目录：%s" % "、".join(miss_dir))
        if "机位格" in miss_dir:
            print("   🔴 `机位格\\`（G）是核实的两块真缺口之一 —— 盘上从来没建过。"
                  "老李的三清单里也没有对应物，是我们自己需要的（锁机位与画框）。")
    return 0


def do_check(adir, path):
    rows, fields = read_ledger(path)
    if not os.path.isfile(path):
        print("!! 台账不存在：%s ⇒ 先 --init" % path)
        return 1
    errs, warns = [], []
    if fields and list(fields) != COLUMNS:
        miss = [c for c in COLUMNS if c not in (fields or [])]
        extra = [c for c in (fields or []) if c not in COLUMNS]
        errs.append("表头与契约不符：缺 %s／多 %s（契约 13 列＝characters.csv 的 10 列＋状态/交叉索引/首次出现）"
                    % (miss or "无", extra or "无"))
    ids = {}
    for i, r in enumerate(rows, 2):       # 第 1 行是表头
        no = str(r.get("编号", "")).strip()
        if not no:
            errs.append("第 %d 行：编号为空" % i)
            continue
        m = re.match(r"^([CPSGB])\d+$", no)
        if not m:
            errs.append("第 %d 行：编号 `%s` 不合前缀规则（只许 C=角色 P=道具 S=场景 G=机位格 B=站位 ＋ 数字）"
                        % (i, no))
        else:
            pre = m.group(1)
            fp = str(r.get("文件路径", "")).strip()
            if fp:
                low = fp.replace("\\", "/").lower()
                d = None
                for k, v in PREFIX_OF_DIR.items():
                    if ("/%s/" % k) in low:
                        d = v
                        break
                if d and d != pre:
                    errs.append("第 %d 行：编号前缀 `%s`(%s) 与文件路径所在目录 `%s`(%s) **对不上**"
                                % (i, pre, PREFIX_MEANING[pre], d, PREFIX_MEANING[d]))
        if no in ids:
            errs.append("编号重复：`%s` 出现在第 %d 行与第 %d 行 ⇒ 交叉索引会指错" % (no, ids[no], i))
        ids[no] = i
        st = str(r.get("状态", "")).strip()
        if st not in STATUSES:
            errs.append("第 %d 行（%s）：状态 `%s` **不在允许集**里（只许 %s）—— 自造状态＝第二套口径"
                        % (i, no, st, " / ".join(STATUSES)))
        fp = str(r.get("文件路径", "")).strip()
        if st == "✅已生成" and fp and not os.path.isfile(fp):
            errs.append("第 %d 行（%s）：状态是 ✅已生成 但文件不在盘上：%s ⇒ **虚报**" % (i, no, fp))
        if st == "⏳待生成" and fp and os.path.isfile(fp):
            warns.append("第 %d 行（%s）：状态是 ⏳待生成 但文件已在盘上 ⇒ 状态陈旧：%s" % (i, no, fp))
        fo = str(r.get("首次出现", "")).strip()
        if fo and not re.match(r"^\d{4}-\d{2}-\d{2}$", fo):
            warns.append("第 %d 行（%s）：首次出现 `%s` 不是 YYYY-MM-DD" % (i, no, fo))
        if not str(r.get("名称", "")).strip():
            warns.append("第 %d 行（%s）：名称为空" % (i, no))
    # 盘上有、台账没有的（漏登记）
    listed = {str(r.get("文件路径", "")).strip().replace("\\", "/") for r in rows}
    for pre, name, rel, ap, sz in scan_tree(adir):
        if rel not in listed and ap.replace("\\", "/") not in listed:
            warns.append("盘上有、台账没登记：%s（跑 --scan 补）" % rel)
    # 分布统计
    from collections import Counter
    by_pre = Counter(str(r.get("编号", ""))[:1] for r in rows if r.get("编号"))
    by_st = Counter(str(r.get("状态", "")).strip() for r in rows)
    print("=" * 78)
    print("asset_ledger --check · %s" % path)
    print("=" * 78)
    print("台账 %d 行｜按类别：%s｜按状态：%s"
          % (len(rows),
             "、".join("%s(%s) %d" % (k, PREFIX_MEANING.get(k, "?"), v) for k, v in sorted(by_pre.items())) or "空",
             "、".join("%s %d" % (k or "(空)", v) for k, v in sorted(by_st.items())) or "空"))
    for m in warns:
        print("  ⚠ %s" % m)
    for m in errs:
        print("  !! %s" % m)
    print("-" * 78)
    print("error %d｜warn %d" % (len(errs), len(warns)))
    return 1 if errs else 0


def do_xlsx(adir, path):
    rows, _ = read_ledger(path)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception as e:
        print("!! 需要 openpyxl（画风库那套是 `py -3.12` 跑的）：%s" % e)
        return 2
    out = os.path.join(os.path.dirname(path), "ledger.xlsx")
    HF = PatternFill("solid", fgColor="1F3864")
    BOLD = Font(bold=True, color="FFFFFF")
    TOP = Alignment(vertical="top", wrap_text=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "资产台账"
    ws.append(COLUMNS)
    for c in range(1, len(COLUMNS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill, cell.font, cell.alignment = HF, BOLD, TOP
    widths = [8, 20, 16, 8, 10, 20, 14, 60, 52, 12, 12, 20, 12]
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    for r in rows:
        ws.append([r.get(k, "") for k in COLUMNS])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = TOP
    ws.freeze_panes = "A2"
    # 标签反查：状态 / 类别 → 编号
    ws2 = wb.create_sheet("标签反查")
    ws2.append(["标签类型", "标签", "编号", "名称", "文件路径"])
    for c in range(1, 6):
        cell = ws2.cell(row=1, column=c)
        cell.fill, cell.font = HF, BOLD
    for c, w in enumerate([12, 16, 10, 22, 60], 1):
        ws2.column_dimensions[get_column_letter(c)].width = w
    for r in rows:
        no = str(r.get("编号", ""))
        ws2.append(["状态", r.get("状态", ""), no, r.get("名称", ""), r.get("文件路径", "")])
        ws2.append(["类别", PREFIX_MEANING.get(no[:1], "?"), no, r.get("名称", ""), r.get("文件路径", "")])
        xi = str(r.get("交叉索引", "")).strip()
        for t in [x for x in re.split(r"[,，;；/、]", xi) if x.strip()]:
            ws2.append(["交叉索引", t.strip(), no, r.get("名称", ""), r.get("文件路径", "")])
    ws2.freeze_panes = "A2"
    wb.save(out)
    print("+  已导出：%s（主表 %d 行 ＋ 标签反查）" % (out, len(rows)))
    return 0


def main():
    ap = argparse.ArgumentParser(description="项目资产台账（每项目一份，不跨项目复用）")
    ap.add_argument("--project", help="projects_registry.json 里的项目 id，如 武昭君仪")
    ap.add_argument("--list-projects", action="store_true")
    ap.add_argument("--init", action="store_true", help="建空台账（只写 13 列表头）")
    ap.add_argument("--scan", action="store_true", help="扫 assets 目录树，未登记的补成 ❌待确认")
    ap.add_argument("--check", action="store_true", help="校验（默认动作）")
    ap.add_argument("--xlsx", action="store_true", help="导出 ledger.xlsx（主表＋标签反查）")
    ap.add_argument("--force", action="store_true", help="--init 时允许覆盖既有台账（会先留 .bak）")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if a.list_projects:
        projs, why = load_projects()
        if why:
            print("!! %s" % why)
            return 1
        print("%-14s %-24s %s" % ("项目 id", "asset_dir", "assets 目录"))
        for pid, ad in sorted(projs.items()):
            if not ad:
                print("%-14s %-24s %s" % (pid, "(null)", "— 无 E:/创作 落点"))
                continue
            d = os.path.join(CREATION_ROOT, ad, "assets")
            led = os.path.join(d, LEDGER_NAME)
            print("%-14s %-24s %s%s" % (pid, ad,
                                        "在" if os.path.isdir(d) else "🔴 不在",
                                        "｜台账 %s" % ("有" if os.path.isfile(led) else "无")
                                        if os.path.isdir(d) else ""))
        return 0

    if not a.project:
        print("!! 要给 --project（或 --list-projects 看在册项目）")
        return 2
    adir, why = assets_dir(a.project)
    if not adir:
        print("!! %s" % why)
        return 1
    path = os.path.join(adir, LEDGER_NAME)
    if a.init:
        return do_init(path, force=a.force)
    if a.scan:
        if not os.path.isfile(path):
            do_init(path)
        return do_scan(adir, path)
    if a.xlsx:
        return do_xlsx(adir, path)
    return do_check(adir, path)


if __name__ == "__main__":
    sys.exit(main())
