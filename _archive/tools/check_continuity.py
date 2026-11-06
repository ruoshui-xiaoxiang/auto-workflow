#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_continuity.py — 事件线一致性校验（跨镜断链自动标红）

校验项
  E1 必填字段           每镜必须有 id/scene/cast/props/emotion/goal/handoff/duration_s
  E2 承接链             除首镜外 handoff 不得为空；有产出却未挂状态锚 → 警告
  E3 角色凭空出现       新增出场主体必须在 goal/props/handoff/note 里被点名
  E4 道具交接链          state_ledger.prop_chain 里 holder 变化必须在该镜 props 里有交代
  E5 道具链方向反转      同一道具在链上出现"反向交接"（A→B 后又 B→A）→ 需人工确认
  E6 提示词真源          prompt_src 为空或指向不存在的文件
  E7 成片未入交付层      status 含"已出片"但 output 落在 素材/ 而不是 视频/
  E8 变更意向未落地      shots.yaml 的 change_request 仍是待改状态
  E9 目标总长未定        无 target_total_s 时给出当前累计值（阻断节奏决策）

用法:
  py -3.12 check_continuity.py            # 人读报告
  py -3.12 check_continuity.py --json     # 机器读
退出码: 有 🔴 错误 → 1；只有 🟡 警告 → 0
"""

import os, sys, json, argparse

import yaml

EVENT_DIR = r"E:\创作\无音项目\事件线"
SHOTS = os.path.join(EVENT_DIR, "shots.yaml")
LEDGER = os.path.join(EVENT_DIR, "state_ledger.yaml")
POOL = r"E:\图像影音资源池\无音"
DRIVES = ("C:", "D:", "E:")
POOL_SUBDIRS = ("素材", "视频", "图像", "音频", "批次")
REQUIRED = ("id", "scene", "cast", "props", "emotion", "goal", "handoff", "duration_s")


def resolve(ref):
    if not ref:
        return None
    ref = str(ref).strip()
    if ref[:2].upper() in DRIVES:
        return ref.replace("/", os.sep)
    first = ref.replace("\\", "/").split("/")[0]
    if first in POOL_SUBDIRS:
        return os.path.join(POOL, ref.replace("/", os.sep))
    return os.path.join(r"C:\Users\若水\Desktop",
                        os.path.basename(ref.split("§")[0].strip()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with open(SHOTS, encoding="utf-8") as f:
        S = yaml.safe_load(f)
    shots = S["shots"]
    with open(LEDGER, encoding="utf-8") as f:
        L = yaml.safe_load(f)
    led_by_id = {x["id"]: x for x in (L.get("ledger") or [])}

    err, warn, info = [], [], []

    def add(L_, code, where, msg):
        L_.append({"code": code, "where": where, "msg": msg})

    # E1 必填字段
    for s in shots:
        miss = [k for k in REQUIRED if s.get(k) in (None, "", [])]
        if miss:
            add(err, "E1", s.get("id", "?"), f"缺必填字段：{', '.join(miss)}")

    # E2 承接链 + E7 交付层
    prev_led = None
    for i, s in enumerate(shots):
        if i > 0 and not s.get("handoff"):
            add(err, "E2", s["id"], "非首镜但 handoff 为空 —— 跨镜承接断链")
        prev_blind = prev_led is not None and any(
            k in str(prev_led.get("wuyin", "")) for k in ("全黑", "不可见"))
        if i > 0 and not s.get("state_anchor") and not prev_blind:
            add(warn, "E2", s["id"],
                "未挂状态锚（上一镜收尾帧）—— 本镜【开始时】的空间关系没有锁")
        out = s.get("output") or ""
        if "已出片" in str(s.get("status", "")) and "/素材/" in out:
            add(warn, "E7", s["id"],
                "状态是「已出片」但成片仍落在 素材/ 未入交付层 视频/")
        prev_led = led_by_id.get(s["id"])

    # E3 角色凭空出现（可用 introduces 显式声明引入）
    def norm(x):
        return str(x).split("（")[0].split("(")[0].strip()
    known = set()
    for i, s in enumerate(shots):
        cur = set(s.get("cast") or [])
        blob = " ".join(str(s.get(k, "")) for k in
                        ("scene", "goal", "props", "handoff", "note"))
        intro = {norm(x.get("entity")) for x in (s.get("introduces") or [])
                 if isinstance(x, dict)} if isinstance(s.get("introduces"), list) else set()
        for c in cur - known:
            if i == 0:
                continue                      # 首镜没有"上一镜"，不算凭空出现
            if norm(c) in blob or norm(c) in intro:
                continue
            add(warn, "E3", s["id"],
                f"出场主体「{c}」在上一镜未出现，且本镜既没交代引入、也没有 introduces 声明")
        known |= cur

    # E4 / E5 道具交接链
    pc = (L.get("prop_chain") or {})
    chain = pc.get("chain") or []
    by_id = {s["id"]: s for s in shots}
    prev_holder, seen_pairs = None, []
    for c in chain:
        sh, holder = c.get("shot"), c.get("holder")
        s = by_id.get(sh)
        if s is not None and prev_holder != holder and prev_holder is not None:
            p = str(s.get("props", ""))
            if (holder or "空") not in p and (prev_holder or "空") not in p:
                add(err, "E4", sh,
                    f"道具「{pc.get('prop')}」持有者 {prev_holder} → {holder}，但本镜 props 里没写这次交接")
        if prev_holder and holder and prev_holder != holder:
            seen_pairs.append((prev_holder, holder))
        prev_holder = holder
    for (a_, b_) in seen_pairs:
        if (b_, a_) in seen_pairs:
            add(warn, "E5", pc.get("prop", "?"),
                f"链上出现方向相反的两次交接（{a_}→{b_} 与 {b_}→{a_}）—— 确认是否有意设计")
            break

    # E6 提示词真源
    for s in shots:
        src = s.get("prompt_src")
        if not src:
            add(err, "E6", s["id"], "提示词真源缺失 —— 无法复现，也无法过「提示词先审」这道闸门")
        else:
            p = resolve(src)
            if p and not os.path.isfile(p):
                add(err, "E6", s["id"], f"提示词真源指向的文件不存在：{src}")

    # E10 提示词正文 ↔ yaml 锚点一致性（"人工写、机器查"——把两副本漂移降级成可查）
    ANCHOR_KW = {
        "沈无音": ["沈无音"],
        "小Q": ["小Q"],
        "交领汉服": ["交领汉服"],
        "米色小布袋": ["米色小布袋"],
        "哑女不出声": ["不出声", "不张嘴"],
        "破伞": ["伞"],
    }
    for s in shots:
        src = s.get("prompt_src")
        if not src:
            continue
        p = resolve(src)
        # 只对真正的 .txt 运行真源做正文一致性（桌面定稿文档是 §引用，跳过）
        if not p or not os.path.isfile(p) or not p.lower().endswith(".txt"):
            continue
        try:
            txt = open(p, encoding="utf-8").read()
        except Exception:
            continue
        checks = dict(ANCHOR_KW)
        if "伞" not in str(s.get("props", "")) and "遮阳伞" not in str(s.get("props", "")):
            checks.pop("破伞", None)
        missing = [name for name, kws in checks.items() if not any(k in txt for k in kws)]
        if missing:
            add(warn, "E10", s["id"], f"提示词正文缺少 yaml 里的锚点：{'、'.join(missing)}")

    # E8 变更意向未落地
    for s in shots:
        if s.get("change_request"):
            add(warn, "E8", s["id"], f"变更意向未落地：{s['change_request']}")
    shot_ids = {s["id"] for s in shots}
    for k, v in (S.get("变更意向") or {}).items():
        if k in shot_ids:
            continue          # 已按镜报过，不重复
        add(warn, "E8", k, f"顶层变更意向未落地：{v}")

    # E9 目标总长
    total = sum((s.get("duration_s") or 0) for s in shots)
    tgt = S.get("target_total_s")
    if not tgt:
        add(info, "E9", "全片", f"目标总长未定；当前累计 {total:.2f}s（{len(shots)} 镜）")
    else:
        add(info, "E9", "全片", f"累计 {total:.2f}s / 目标 {tgt}s（{total/tgt*100:.1f}%）")

    if a.json:
        print(json.dumps({"errors": err, "warnings": warn, "info": info},
                         ensure_ascii=False, indent=2))
    else:
        print(f"事件线校验：{SHOTS}")
        print(f"镜数 {len(shots)}　累计 {total:.2f}s\n")
        for L_, tag in ((err, "🔴 错误"), (warn, "🟡 警告"), (info, "ℹ️ 信息")):
            if not L_:
                continue
            print(f"--- {tag} ({len(L_)})")
            for x in L_:
                print(f"  [{x['code']}] {x['where']}：{x['msg']}")
            print()
        print(f"结论：{len(err)} 错误 / {len(warn)} 警告 / {len(info)} 信息")
    sys.exit(1 if err else 0)


if __name__ == "__main__":
    main()
