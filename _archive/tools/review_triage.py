#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""review_triage.py · 出片终审的**三分类**裁定与落库（治理批新功能③，2026-10-19）

用户 2026-10-19 定的机制
----------------------
出片要求最终审核时做**三个分类**存储：
    ✅ 通过   —— 可以当**标准样片**
    🔧 瑕疵   —— 还要重修
    🔴 废片   —— 问题重大，修复价值不大
另外三条配套裁定：
    · **审片先发飞书**（`feishu_send.py --review` 的三件套），**审片站不做终审**
      （`review_site.py` / `review_publish.py` 是协作面，不是裁定面）。
    · 第一镜出来后也必须发飞书（不必等目审，但第一镜要发）。
    · **超过 30 分钟没有回复就先继续流程，直到批次完成** ⇒ 本工具不阻塞、不轮询，
      只把"到期未裁"如实标出来。

🔴 为什么裁定只能从 CLI 进来（这是硬约束不是设计偏好）
----------------------------------------------------
飞书**出向可用、入向被拒**：应用只有 `im:message.p2p_msg:readonly`，读群历史返回 **230027**
（`feishu_send.py` 自己的 docstring 与 `tools/review_site.py` 的既有结论都记着这条）。
⇒ **本工具不会去轮询飞书拿你的回复**，因为拿不到。假装能拿＝制造一个永远静默失败的环节。
裁定入口只有两个：① 本 CLI 的 `--verdict`；② Qoder 会话里让我代为落库（我调本 CLI）。
你远程／手机端看到飞书那条之后，回话给我或自己敲一行 CLI 都行。

台账形态（**不复制成片**）
------------------------
    E:\\图像影音资源池\\<项目>\\审片\\台账.csv      一批一行，可按分类筛
    <批次目录>\\审片单.json                       与该批次同生共死（批次是自包含的）
为什么不把成片拷进 通过/瑕疵/废片 三个目录：一条 H3 成片几百 MB，三分类是**对批次的裁定**，
不是三份新资产。拷一遍＝三份会漂的副本＋白占几十 GB。台账里存**指向批次的路径**就够，
"标准样片"靠 `分类=通过` 筛出来，不靠文件搬家。

用法
----
    py review_triage.py --project 武昭君仪 --batch <批次目录> --send [--name 段2v5]
    py review_triage.py --project 武昭君仪 --batch <批次目录> --verdict 通过 --note "可当标准样片"
    py review_triage.py --project 武昭君仪 --pending          # 列出到期未裁的
    py review_triage.py --project 武昭君仪 --list             # 看台账
    py review_triage.py --first-shot <mp4> --cover <png>      # 第一镜必发（不等目审）

退出码：0 成功／1 参数或状态不合格／2 外部命令（feishu_send）失败／3 到期未裁（--pending 时有）
"""
import argparse
import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

POOL_ROOT = r"E:/图像影音资源池"
PROJECTS_REGISTRY = r"D:/AIWorkflow/engine/projects_registry.json"
FEISHU_SEND = r"D:/AIWorkflow/tools/feishu_send.py"
LEDGER_DIR_NAME = "审片"
LEDGER_NAME = "台账.csv"
SHEET_NAME = "审片单.json"
WAIT_MINUTES = 30          # 用户裁定：超过 30 分钟没回复就先继续流程

VERDICTS = {
    "通过": ("✅", "可以当标准样片"),
    "瑕疵": ("🔧", "还要重修"),
    "废片": ("🔴", "问题重大，修复价值不大"),
}
LEDGER_COLUMNS = ["批次", "项目", "分类", "裁定时间", "裁定人", "理由",
                  "成片路径", "飞书已发", "发出时间", "到期时间", "标准样片"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rd(p):
    try:
        return io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def project_pool_dir(project):
    try:
        d = json.loads(rd(PROJECTS_REGISTRY))
    except Exception as e:
        return None, "projects_registry.json 读不了：%s" % e
    for p in (d.get("projects") or []):
        if isinstance(p, dict) and p.get("id") == project:
            root = os.path.join(POOL_ROOT, project)
            if not os.path.isdir(root):
                return None, ("资源池里没有项目目录 `%s`（projects_registry 声明的 id 是它，"
                              "但盘上没建）⇒ 先建目录，别让我猜" % root)
            return root, None
    return None, ("项目 `%s` 没在 projects_registry.json 里声明（那份表是项目声明的唯一真源）"
                  % project)


def ledger_path(pool_dir):
    return os.path.join(pool_dir, LEDGER_DIR_NAME, LEDGER_NAME)


def read_ledger(path):
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(x) for x in csv.DictReader(f)]


def write_ledger(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        bak = path + ".bak-" + datetime.now().strftime("%Y%m%d")
        if not os.path.exists(bak):
            io.open(bak, "w", encoding="utf-8", newline="").write(rd(path))
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LEDGER_COLUMNS})
    os.replace(tmp, path)


def upsert_ledger(path, batch, fields):
    rows = read_ledger(path)
    hit = None
    for r in rows:
        if r.get("批次") == batch:
            hit = r
            break
    if hit is None:
        hit = {"批次": batch}
        rows.append(hit)
    hit.update(fields)
    write_ledger(path, rows)
    return hit


def sheet_path(batch_dir):
    return os.path.join(batch_dir, SHEET_NAME)


def load_sheet(batch_dir):
    p = sheet_path(batch_dir)
    if not os.path.isfile(p):
        return {}, p
    try:
        return json.loads(rd(p)), p
    except Exception as e:
        return {"_parse_error": str(e)}, p


def save_sheet(batch_dir, d):
    p = sheet_path(batch_dir)
    os.makedirs(batch_dir, exist_ok=True)
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8", newline="").write(
        json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, p)
    return p


def find_film(batch_dir):
    """在批次目录里找成片。找不到就返回 None，**不猜、不拿别的文件顶替**。

    优先级（2026-10-19 实测批次结构定的）：
      ① `final\\*.mp4` —— 实测 `批次\\20261015_172854\\final\\relay_e2e_ep1v2_final.mp4`
         是拼好的成片，同目录还有 `*_封面.jpg`。有 final 就用它，这是**约定俗成的落点**。
      ② 名字里带 final / 成片 / concat 的
      ③ 最大的那个 mp4
    ⚠ 第一版只有 ③（取最大），在 20261015_172854 上**碰巧**选对了 final 那条。
      碰巧对不等于对：换一批里某个单镜归一化产物比成片还大，就会把单镜当成片发出去。
    """
    cands = []
    for dp, dns, fns in os.walk(batch_dir):
        dns[:] = [x for x in dns if x not in ("__pycache__",)]
        for f in fns:
            if f.lower().endswith((".mp4", ".mov", ".webm")):
                p = os.path.join(dp, f)
                cands.append(p)
    if not cands:
        return None
    final_dir = [p for p in cands
                 if os.path.basename(os.path.dirname(p)).lower() == "final"]
    if final_dir:
        final_dir.sort(key=lambda p: -os.path.getsize(p))
        return final_dir[0]
    named = [p for p in cands if re.search(r"(?i)final|成片|concat", os.path.basename(p))]
    if named:
        named.sort(key=lambda p: -os.path.getsize(p))
        return named[0]
    cands.sort(key=lambda p: -os.path.getsize(p))
    return cands[0]


def find_cover(film):
    """成片封面：同目录里同名的 png/jpg，否则目录里第一张 png。

    ⚠ `--video` **必须**配 `--video-cover`（lark-cli 的硬约束，feishu_send.py:121 会直接退出），
      所以找不到封面就不能发视频 —— 这时候如实报，不硬发。
    """
    d = os.path.dirname(film)
    stem = os.path.splitext(os.path.basename(film))[0]
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = os.path.join(d, stem + ext)
        if os.path.isfile(p):
            return p
    for f in sorted(os.listdir(d)):
        if f.lower().endswith((".png", ".jpg", ".jpeg")):
            return os.path.join(d, f)
    return None


def do_send(project, batch_dir, name, dry, yes, first_shot=None, cover=None):
    pool, why = project_pool_dir(project)
    if not pool:
        print("!! %s" % why)
        return 1
    if not os.path.isdir(batch_dir) and not first_shot:
        print("!! 批次目录不在盘上：%s" % batch_dir)
        return 1
    film = first_shot or find_film(batch_dir)
    if not film:
        print("!! 在 %s 里找不到成片（.mp4/.mov/.webm）⇒ 不发。" % batch_dir)
        print("   🔴 不猜、不拿别的文件顶替。要么先出片，要么用 --first-shot 显式给。")
        return 1
    cov = cover or find_cover(film)
    if not cov:
        print("!! 找不到封面：%s 同目录没有同名 png/jpg，也没有任何 png。" % film)
        print("   🔴 lark-cli 硬约束：`--video` 必须配 `--video-cover`，缺了发不出去。")
        print("   ⇒ 用 --cover 显式给一张（通常就是首帧）。")
        return 1
    sz = os.path.getsize(film) / 1048576.0
    if sz > 30:
        print("⚠ 成片 %.1f MB **超过飞书 30MB 上限** ⇒ 发不出去。" % sz)
        print("   按 feishu_send.py 的既定处置：改发审片区链接（review_publish.py），"
              "**不要压到失真硬塞**。")
        return 1
    cmd = [sys.executable, FEISHU_SEND, "--review",
           "--text", "【%s】%s 待终审（三分类：通过/瑕疵/废片）" % (project, name or os.path.basename(batch_dir)),
           "--film", os.path.basename(film), "--cover", os.path.basename(cov)]
    if not yes:
        cmd.append("--dry-run")
    print("=" * 78)
    print("发飞书审片三件套%s" % ("（--dry-run，不真发）" if not yes else ""))
    print("  成片：%s（%.1f MB）" % (film, sz))
    print("  封面：%s" % cov)
    print("  ⚠ feishu_send.py 的硬约束：媒体旗标**只收 cwd 相对路径** ⇒ 必须在成片所在目录里跑")
    cwd = os.path.dirname(film)
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        print("!! feishu_send.py 退出码 %d" % r.returncode)
        return 2
    sheet, sp = load_sheet(batch_dir) if batch_dir and os.path.isdir(batch_dir) else ({}, None)
    # 🔴 `飞书已发` 只有在**真发**（--yes）时才记 True。
    #   第一版无条件写 True，于是 --dry-run 也会在台账里留下"已发"——**记一件没发生的事**，
    #   比不记更坏：下次 --pending 会以为发过了、不再提醒，你就永远收不到那条审片。
    sheet.update({
        "项目": project,
        "批次": name or (os.path.basename(batch_dir) if batch_dir else os.path.basename(film)),
        "成片": film,
        "封面": cov,
        "飞书已发": bool(yes),
        "试发": (not yes),
        "发出时间": now() if yes else "",
        "到期时间": ((datetime.now() + timedelta(minutes=WAIT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
                     if yes else ""),
        "等待分钟": WAIT_MINUTES,
        "分类": sheet.get("分类", ""),
        "🔴裁定只能从CLI进": "飞书入向被拒 230027（应用只有 im:message.p2p_msg:readonly）⇒ 本工具不轮询飞书。"
                          "回话给 Qoder 会话，或自己敲 --verdict。",
    })
    if sp:
        save_sheet(batch_dir, sheet)
        print("+  审片单：%s%s" % (sp, "" if yes else "　（⚠ 试发，未真发 ⇒ 不记发出时间、不进到期计时）"))
        lp = ledger_path(pool)
        upsert_ledger(lp, sheet["批次"], {
            "项目": project, "成片路径": film, "飞书已发": "是" if yes else "否（试发）",
            "发出时间": sheet["发出时间"], "到期时间": sheet["到期时间"],
        })
        print("+  台账：%s" % lp)
    return 0


def do_verdict(project, batch_dir, batch_name, verdict, note, who):
    pool, why = project_pool_dir(project)
    if not pool:
        print("!! %s" % why)
        return 1
    if verdict not in VERDICTS:
        print("!! 分类只许三个：%s（你给的是 `%s`）" % ("／".join(VERDICTS), verdict))
        print("   🔴 不许自造第四类 —— 三分类是用户 2026-10-19 定的，加一类就等于换了机制。")
        return 1
    sheet = {}
    if batch_dir and os.path.isdir(batch_dir):
        sheet, sp = load_sheet(batch_dir)
    name = batch_name or sheet.get("批次") or (os.path.basename(batch_dir) if batch_dir else "")
    if not name:
        print("!! 要给 --batch <批次目录> 或 --name <批次名>，否则台账里认不出是哪一批")
        return 1
    mark, meaning = VERDICTS[verdict]
    film = sheet.get("成片") or (find_film(batch_dir) if batch_dir and os.path.isdir(batch_dir) else None) or ""
    row = upsert_ledger(ledger_path(pool), name, {
        "项目": project, "分类": verdict, "裁定时间": now(), "裁定人": who or "用户",
        "理由": note, "成片路径": film,
        "飞书已发": "是" if sheet.get("飞书已发") else "否",
        "发出时间": sheet.get("发出时间", ""), "到期时间": sheet.get("到期时间", ""),
        "标准样片": "是" if verdict == "通过" else "",
    })
    if sheet is not None and batch_dir and os.path.isdir(batch_dir):
        sheet.update({"分类": verdict, "裁定时间": row["裁定时间"], "裁定人": row["裁定人"],
                      "理由": note, "标准样片": row["标准样片"]})
        save_sheet(batch_dir, sheet)
    print("=" * 78)
    print("%s 分类＝%s（%s）" % (mark, verdict, meaning))
    print("  批次：%s｜项目：%s｜裁定人：%s" % (name, project, row["裁定人"]))
    if note:
        print("  理由：%s" % note)
    if verdict == "通过":
        print("  ★ 已标 `标准样片=是` ⇒ 后续 `--list --verdict 通过` 就能筛出全部标准样片")
    if verdict == "瑕疵":
        print("  ⚠ 瑕疵＝还要重修。修完重发一轮：--send 再 --verdict。")
    if verdict == "废片":
        print("  🔴 废片＝问题重大、修复价值不大。**别删**（记忆库纪律：资产全留，失败样本也收进库），"
              "台账留着才能回答「当初为什么废」。")
    print("  台账：%s" % ledger_path(pool))
    return 0


def do_pending(project):
    pool, why = project_pool_dir(project)
    if not pool:
        print("!! %s" % why)
        return 1
    rows = read_ledger(ledger_path(pool))
    late, waiting, done = [], [], []
    t = datetime.now()
    for r in rows:
        if r.get("分类"):
            done.append(r)
            continue
        dl = r.get("到期时间", "")
        try:
            d = datetime.strptime(dl, "%Y-%m-%d %H:%M:%S")
        except Exception:
            waiting.append((r, None))
            continue
        (late if t > d else waiting).append((r, d))
    print("=" * 78)
    print("待裁 %d（其中**已过 %d 分钟到期线** %d）｜已裁 %d" % (len(late) + len(waiting), WAIT_MINUTES, len(late), len(done)))
    for r, d in late:
        print("  🔴 到期未裁：%s（到期 %s，已超 %d 分钟）"
              % (r.get("批次"), r.get("到期时间"), int((t - d).total_seconds() // 60)))
    for r, d in waiting:
        print("  ⏳ 等待中：%s（到期 %s）" % (r.get("批次"), r.get("到期时间") or "未记录"))
    if late:
        print("-" * 78)
        print("按用户 2026-10-19 的裁定：**超过 %d 分钟没有回复就先继续流程，直到批次完成**。" % WAIT_MINUTES)
        print("⇒ 上面这些到期未裁的**不拦出片**，台账如实标着就行，等你有空再补 --verdict。")
        return 3
    return 0


def do_list(project, verdict):
    pool, why = project_pool_dir(project)
    if not pool:
        print("!! %s" % why)
        return 1
    rows = read_ledger(ledger_path(pool))
    if verdict:
        rows = [r for r in rows if r.get("分类") == verdict]
    print("=" * 78)
    print("%s（%d 行%s）" % (ledger_path(pool), len(rows), "｜筛 分类=%s" % verdict if verdict else ""))
    print("%-26s %-6s %-19s %-8s %s" % ("批次", "分类", "裁定时间", "标准样片", "理由"))
    for r in rows:
        print("%-26s %-6s %-19s %-8s %s"
              % (str(r.get("批次", ""))[:26], r.get("分类") or "未裁",
                 r.get("裁定时间", ""), r.get("标准样片", ""), str(r.get("理由", ""))[:40]))
    from collections import Counter
    c = Counter(r.get("分类") or "未裁" for r in read_ledger(ledger_path(pool)))
    print("-" * 78)
    print("全台账分布：%s" % "、".join("%s %d" % (k, v) for k, v in sorted(c.items())))
    return 0


def main():
    ap = argparse.ArgumentParser(description="出片终审三分类（通过/瑕疵/废片）")
    ap.add_argument("--project", help="projects_registry.json 里的项目 id")
    ap.add_argument("--batch", help="批次目录（资源池 <项目>\\批次\\<时间戳>）")
    ap.add_argument("--name", help="批次名（不给就从 --batch 目录名推）")
    ap.add_argument("--send", action="store_true", help="发飞书审片三件套")
    ap.add_argument("--first-shot", help="第一镜成片路径（第一镜必发，不等目审）")
    ap.add_argument("--cover", help="封面（--first-shot 时建议显式给，通常就是首帧）")
    ap.add_argument("--verdict", help="裁定：通过 / 瑕疵 / 废片")
    ap.add_argument("--note", default="", help="裁定理由（进台账）")
    ap.add_argument("--who", default="用户", help="裁定人")
    ap.add_argument("--pending", action="store_true", help="列出待裁与到期未裁")
    ap.add_argument("--list", action="store_true", help="看台账")
    ap.add_argument("--yes", action="store_true", help="真发飞书（不带就 --dry-run）")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not a.project:
        print("!! 要给 --project")
        return 1
    if a.send or a.first_shot:
        return do_send(a.project, a.batch, a.name, False, a.yes,
                       first_shot=a.first_shot, cover=a.cover)
    if a.verdict:
        return do_verdict(a.project, a.batch, a.name, a.verdict, a.note, a.who)
    if a.pending:
        return do_pending(a.project)
    if a.list:
        return do_list(a.project, None)
    print("!! 要一个动作：--send / --verdict / --pending / --list")
    return 1


if __name__ == "__main__":
    sys.exit(main())
