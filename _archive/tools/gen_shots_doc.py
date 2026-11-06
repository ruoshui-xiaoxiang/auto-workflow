#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_shots_doc.py — 事件线真源 → 桌面人读文档（单向生成）

真源分工（重要，别搞混）：
    E:\\创作\\无音项目\\事件线\\shots.yaml        结构/状态/承接/道具/时长  ← 意图
    E:\\创作\\无音项目\\事件线\\state_ledger.yaml  每镜定稿后的实际状态     ← 事实
    D:\\AIWorkflow\\ComfyUI_H3\\prompts\\*.txt     提示词正文（长散文）
本脚本把上面三样渲染成**一份只读的桌面文档**；文档里出现的一切不要手改，
改素材后重跑本脚本即可。这样"改脚本忘改文档"的老问题在机制上消失。

用法:
    py -3.12 gen_shots_doc.py            # 渲染
    py -3.12 gen_shots_doc.py -o 别的路径.md
免终端：双击同目录下的 事件线_生成文档.bat
"""

import os, sys, argparse
from datetime import datetime

import yaml

EVENT_DIR = r"E:\创作\无音项目\事件线"
SHOTS = os.path.join(EVENT_DIR, "shots.yaml")
LEDGER = os.path.join(EVENT_DIR, "state_ledger.yaml")
DEFAULT_OUT = r"E:\图像影音资源池\无音_镜1镜2_对照\无音_分镜表与状态台账.md"

DRIVES = ("C:", "D:", "E:")
POOL = r"E:\图像影音资源池\无音"
POOL_SUBDIRS = ("素材", "视频", "图像", "音频", "批次")
# 相对引用的兜底搜索根（按顺序，第一个命中即返回）。
# 10-02 加：桌面在整理批次 1 已被清成只剩快捷方式，原来只查桌面 ⇒ 兜底分支一律假阴。
REF_FALLBACK_ROOTS = (
    r"E:\创作\无音项目",                       # 本项目活区（最可能）
    r"E:\创作",                                 # 跨项目
    r"E:\图像影音资源池",                        # 交付落点
    r"C:\Users\若水\Desktop",                    # 兼容旧写法，放最后
)


def resolve_ref(ref):
    """把 shots.yaml 里的引用解析成 (显示文本, 是否存在?)

    支持三种写法：
      1) 绝对路径      E:/图像影音资源池/无音/视频/xxx.mp4
      2) 池内相对路径   素材/shot04_prop/prev_end.png  （相对 无音/）
      3) 桌面文档节引用 桌面/无音_提示词定稿.md §镜1
    """
    if not ref:
        return "—", None
    ref = str(ref).strip()
    if ref[:2].upper() in DRIVES:
        p = ref.replace("/", os.sep)
        return ref, os.path.isfile(p)
    first = ref.replace("\\", "/").split("/")[0]
    if first in POOL_SUBDIRS:
        p = os.path.join(POOL, ref.replace("/", os.sep))
        return f"{POOL}\\{ref}".replace("\\", "/"), os.path.isfile(p)
    head = ref.split("§")[0].strip()
    base = os.path.basename(head)
    # ⚠ 10-02 修：这里原来**只查桌面**（`os.path.join(r"C:\Users\若水\Desktop", basename)`）。
    #   桌面在"整理批次 1"里已被清成只剩快捷方式 ⇒ 凡是走到这条兜底分支的相对引用
    #   一律被判 ❌ 不存在，**产出的台账里那些 ❌ 就是这么来的假阴**（文件其实在 E 盘）。
    #   改成按根顺序找，先活区后备份区，桌面留最后一名只为兼容旧写法。
    for root in REF_FALLBACK_ROOTS:
        p = os.path.join(root, base)
        if os.path.isfile(p):
            return p.replace(os.sep, "/"), True
    p = os.path.join(REF_FALLBACK_ROOTS[0], base)
    return p.replace(os.sep, "/"), os.path.isfile(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    with open(SHOTS, encoding="utf-8") as f:
        S = yaml.safe_load(f)
    L = {}
    if os.path.isfile(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            L = yaml.safe_load(f)
    led = {x["id"]: x for x in (L.get("ledger") or [])}

    total = sum((s.get("duration_s") or 0) for s in S["shots"])
    L_ = []
    w = L_.append

    w(f"# {S['project']} · 分镜表与状态台账")
    w("")
    w(f"> **本文件由 `gen_shots_doc.py` 从事件线真源生成，禁止手改。**")
    w(f"> 真源：`{SHOTS}`（意图）＋ `{LEDGER}`（事实）＋ `prompts/*.txt`（提示词正文）")
    w(f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M} ｜ 事件线更新：{S.get('updated','?')}")
    w("")
    w(f"**全片已定稿镜数 {len(S['shots'])}，成片时长合计 {total:.2f} 秒。**")
    w("")

    # 总表
    w("## 一、总表")
    w("")
    w("| 生产编号 | 分镜表编号 | 幕 | 时长 | 道具关键变化 | 状态 |")
    w("|---|---|---|---|---|---|")
    for s in S["shots"]:
        prop = (s.get("props") or "").replace("\n", " ")
        if len(prop) > 44:
            prop = prop[:44] + "…"
        st = s.get("status", "")
        if s.get("change_request"):
            st += " ⚠️待改"
        w(f"| {s['id']} | {s.get('board_no','—')} | {s.get('act','—')} | "
          f"{s.get('duration_s','—')}s | {prop} | {st} |")
    w("")

    # 逐镜
    w("## 二、逐镜")
    for s in S["shots"]:
        w("")
        w(f"### {s['id']} · {s.get('goal','')}")
        w("")
        w(f"- **分镜表编号**：{s.get('board_no','—')}　**文件前缀**：{s.get('file_prefix','—')}")
        w(f"- **场景**：{s.get('scene','—')}")
        w(f"- **出场**：{'、'.join(s.get('cast') or [])}")
        w(f"- **道具状态**：{s.get('props','—')}")
        w(f"- **情绪**：{s.get('emotion','—')}")
        w(f"- **承接**：{s.get('handoff','—')}")
        w(f"- **时长**：{s.get('duration_s','—')}s")
        ref_txt, ref_ok = resolve_ref(s.get("state_anchor"))
        if ref_ok is True:
            w(f"- **状态锚**：`{ref_txt}` ✅")
        elif ref_ok is False:
            w(f"- **状态锚**：`{ref_txt}` ❌ 文件不存在")
        else:
            w(f"- **状态锚**：—")
        pr_txt, pr_ok = resolve_ref(s.get("prompt_src"))
        if pr_ok is True:
            w(f"- **提示词真源**：`{pr_txt}` ✅")
        elif pr_ok is False:
            w(f"- **提示词真源**：`{pr_txt}` ❌ 未找到")
        else:
            w("- **提示词真源**：🔴 **缺失**")
        out_txt, out_ok = resolve_ref(s.get("output"))
        w(f"- **成片**：`{out_txt}`" + (" ✅" if out_ok else (" ❌ 不存在" if out_ok is False else "")))
        w(f"- **状态**：{s.get('status','—')}")
        if s.get("note"):
            w(f"- **备注**：{s['note']}")
        if s.get("change_request"):
            w(f"- ⚠️ **变更意向**：{s['change_request']}")
        e = led.get(s["id"])
        if e:
            w("")
            w(f"<details><summary>{s['id']} 结束时的状态（来自台账）</summary>")
            w("")
            w(f"- **沈无音**：{e.get('wuyin','—')}")
            w(f"- **小Q**：{e.get('xiaoq','—')}")
            for k, v in (e.get("props") or {}).items():
                w(f"- **{k}**：{v}")
            for k, v in (e.get("knows") or {}).items():
                w(f"- **{k} 知道**：{v}")
            for r in (e.get("risks") or []):
                w(f"- ⚠️ 风险：{r}")
            w("")
            w("</details>")

    # 道具交接链
    pc = L.get("prop_chain")
    if pc:
        w("")
        w("## 三、道具交接链")
        w("")
        w(f"**{pc['prop']}**")
        w("")
        w("| 镜 | 持有者 | 姿态 |")
        w("|---|---|---|")
        for c in pc["chain"]:
            w(f"| {c['shot']} | {c.get('holder') or '—'} | {c.get('pose','—')} |")

    # 待补 / 变更意向 / 基线
    if S.get("待补"):
        w("")
        w("## 四、待补")
        w("")
        for x in S["待补"]:
            w(f"- {x}")
    if S.get("变更意向"):
        w("")
        w("## 五、变更意向（未落地）")
        w("")
        for k, v in S["变更意向"].items():
            w(f"- **{k}**：{v}")
    b = S.get("baseline") or {}
    if b:
        w("")
        w("## 六、全片统一基线（每条提示词逐字带上）")
        w("")
        w(f"- **画风**：{b.get('画风','—')}")
        w("- **角色锚（逐字全带，不许缩写）**")
        for k, v in (b.get("角色锚") or {}).items():
            w(f"  - **{k}**：{v}")
        w("- **铁律**")
        for x in (b.get("铁律") or []):
            w(f"  - {x}")

    out = a.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L_) + "\n")
    print(f"[gen] 已生成 {out}（{len(L_)} 行，{len(S['shots'])} 镜，合计 {total:.2f}s）")


if __name__ == "__main__":
    main()
