#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_registry.py · 通道与配置注册表的自校验（默认只报不拦，--strict 才返回 1）。

为什么要有它（10-02 批 4·2）：以前"系统有几条通道、每条的 kind 词是什么、谁归机器管"这件事
**没有一处能一次回答**——通道归属的实际裁决是 `check_preflight.py` 里 `channel_of()` 的三行元组，
声明散在 17 份 yaml 与五份通道真源 md 里，而 `E:\\若水AI电影\\99_维护\\scan_system.py` 的
`CHANNELS` 常量是**第三份抄本**。三份抄本正是 GAP-A1／索引 §5 手抄计数那一种病。
⇒ 现在 `D:\\AIWorkflow\\engine\\channels_registry.json` 是唯一的**声明**源，
   扫描器改读它（读不到才退回自带常量并**如实报一条 high**），
   本脚本负责在跑任何东西之前证明：**声明、代码、yaml 三方说的是同一件事**。

四项校验（分开报数，不凑数、不互相掩盖）：
  [A] 注册表自洽：id 唯一／kind 词跨通道不重复（重复必须在 kind_conflicts 里显式登记）／
      未裁的通道不许标机检／不变式字段齐全。
  [B] 注册表 vs 代码：用 **AST** 从 `channel_of()` 抽出「哪个 kind 词进哪个通道」，
      与注册表 `declared_kind` 对账。⚠ 这里**故意**用与扫描器（正则刮字面量）**不同的第二种实现**——
      两边必须给同一个答案，不一样就是其中一边读错了源码（同 GAP-A12 的立论）。
  [C] 注册表 vs 真源：每条通道的 `rule_source`／`extra_sources` 文件必须在盘上；
      `config_switches[].file` 同理。
  [D] 17 份 workflow yaml 是否合规：`prompt_kind` 有没有声明、声明的词属不属于某条通道、
      该带 `provider` 的通道有没有带。

只读：本脚本不写任何文件（除 `--json` 明确指定路径时）。
"""
import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys

REG = r"D:\AIWorkflow\engine\channels_registry.json"
PROJ_REG = r"D:\AIWorkflow\engine\projects_registry.json"
CONFIG = r"D:\AIWorkflow\engine\config.yaml"
PREFLIGHT = r"D:\AIWorkflow\tools\check_preflight.py"
WF_DIR = r"D:\AIWorkflow\engine\workflows"


def rd(p):
    try:
        return io.open(p, encoding="utf-8").read()
    except Exception:
        return ""


def load_registry(path, need_key="channels"):
    """注册表读法。返回 (记录 or None, 原因)。

    `need_key` 让两份表共用同一个读法（项目表的主段叫 `projects`）——
    一个算法两份实现＝第二个漂移真源，本仓库已为此翻过两次车。
    """
    if not os.path.isfile(path):
        return None, "文件不存在"
    try:
        d = json.loads(rd(path))
    except Exception as e:
        return None, "json 解析失败：%s" % e
    if not isinstance(d.get(need_key), list) or not d[need_key]:
        return None, "%s 段缺失或为空" % need_key
    return d, None


def probe_channel_of(preflight_path, words, timeout=25):
    """**黑盒探针**：真的 import `check_preflight` 并对每个词调 `channel_of(w,'local')`。

    为什么换掉 AST 抽元组：批 4·2b 之后词表来自注册表，函数体里已经没有
    `if k in ("image","img",…)` 这种字面量了 ⇒ 静态刮法会刮到 0 个词，
    把"机器认得"误报成"什么都不认得"（假阴）。探针问的是**行为**，不受代码形状影响。
    顺带取回 `CHANNEL_REGISTRY_STATUS`，这样"权威在表还是在兜底"也是量出来的不是声明的。

    返回 ({词: 通道}, status, 错误信息或 None)。
    """
    d = os.path.dirname(preflight_path)
    payload = ("import sys,json\n"
               "sys.path.insert(0, r'%s')\n"
               "import check_preflight as C\n"
               "out = {}\n"
               "out['k'] = {w: C.channel_of(w, 'local') for w in %r}\n"
               "out['active'] = {c: sorted(ws) for c, ws in C._ACTIVE_KINDS.items()}\n"
               "out['literal'] = {c: sorted(getattr(C, '_KIND_' + c.upper(), []))\n"
               "                  for c in ('image', 'h3', 'cloud')}\n"
               "out['status'] = getattr(C, 'CHANNEL_REGISTRY_STATUS', None)\n"
               "print(json.dumps(out))\n"
               % (d, sorted(words)))
    try:
        # ⚠ 同 Windows 坑：子进程输出是 UTF-8 中文，`text=True` 默认按 cp936 解 ⇒ 必须两边钉 UTF-8。
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, "-c", payload], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except Exception as e:
        return None, "探针没跑成（启动失败）：%s" % e
    if p.returncode != 0:
        return None, "探针退出码 %s：%s" % (p.returncode, (p.stderr or "")[-300:])
    try:
        got = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        return None, "探针输出解析失败：%s（stdout 尾：%r）" % (e, p.stdout[-200:])
    return got, None


def probe_decision_sheet(timeout=25):
    """**黑盒探针**：真的跑 `engine/decision_sheet.py paths`，取回引擎自己拼出来的落点。

    为什么不在这里自己拼路径：那就是「一个算法两份实现」——GAP-E1 那半条、
    交付根那半条都是这么漂的。探针问的是**行为**，代码改取法这里立刻跟着变。
    返回 (dict | None, 错误信息 | None)。
    """
    ds = os.path.join(os.path.dirname(REG), "decision_sheet.py")
    if not os.path.isfile(ds):
        return None, "决定单模块不存在：%s" % ds
    try:
        # ⚠ Windows 老坑：子进程输出是 UTF-8 中文，text=True 默认按 cp936 解 ⇒ 两边都钉 UTF-8
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, ds, "paths"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, cwd=os.path.dirname(ds))
    except Exception as e:
        return None, "探针没跑成（启动失败）：%s" % e
    out = (p.stdout or "").strip()
    if p.returncode != 0 and not out.startswith("{"):
        return None, "探针退出码 %s：%s" % (p.returncode, (p.stderr or out or "")[-300:])
    i = out.find("{")
    if i < 0:
        return None, "探针输出里没有 JSON（stdout 尾：%r，stderr 尾：%r）" % (
            out[-160:], (p.stderr or "")[-160:])
    try:
        return json.loads(out[i:]), None
    except Exception as e:
        return None, "探针输出解析失败：%s（stdout 尾：%r）" % (e, out[-160:])


def kinds_from_code(src):
    """AST 抽 `channel_of()` 里的 `if k in (...) : return "<通道>"`。

    返回 {通道: [kind 词…]}。⚠ 只认**元组/列表字面量里的字符串常量**，
    不刮全文字符串——扫描器原来刮全文，被我写在 docstring 里的示例词污染过（同族教训⑫）。
    """
    out = {}
    try:
        tree = ast.parse(src)
    except Exception as e:
        return None
    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "channel_of":
            fn = node
            break
    if fn is None:
        return None
    for stmt in ast.walk(fn):
        if not isinstance(stmt, ast.If):
            continue
        test = stmt.test
        if not (isinstance(test, ast.Compare) and
                isinstance(test.left, ast.Name) and test.left.id == "k" and
                isinstance(test.comparators[0], (ast.Tuple, ast.List))):
            continue
        words = [e.value for e in test.comparators[0].elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        chans = []
        for sub in stmt.body:
            if isinstance(sub, ast.Return):
                v = sub.value
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    chans.append(v.value)
                elif isinstance(v, ast.IfExp):          # 三元：`cloud if … else h3`
                    for piece in (v.body, v.orelse):
                        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                            chans.append(piece.value)
        for c in chans:
            out.setdefault(c, [])
            for w in words:
                if w not in out[c] and w not in ("", "video"):
                    out[c].append(w)
    return out


def check(reg, pref_src, wf_dir, verbose=False):
    """→ (errs, warns, infos, data)。

    `data` 是给机器读的**结构化**结果（扫描器 `scan_system.py` 直接拿它当通道权威现状），
     prose 那三条给人看。有了 data，扫描器不必自己再实现一遍探针——
    一个算法两份实现＝第二个漂移真源（本仓库为此翻过两次车）。
    """
    errs, warns, infos = [], [], []
    data = {"probe_ran": False}
    chans = reg["channels"]

    # ── [A] 自洽 ──────────────────────────────────────────────
    ids = [c.get("id") for c in chans]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        errs.append("[A] 通道 id 重复：%s" % "、".join(sorted(map(str, dup))))
    conflicts = {k.get("kind"): k for k in (reg.get("kind_conflicts") or [])}
    seen = {}
    for c in chans:
        for w in c.get("declared_kind") or []:
            seen.setdefault(w.lower(), []).append(c["id"])
    for w, owners in sorted(seen.items()):
        if len(owners) > 1:
            rec = conflicts.get(w)
            if not rec or rec.get("disputed") is not True:
                errs.append("[A] kind 词 `%s` 被 %s 同时声明，却没在 kind_conflicts 里登记 disputed"
                            % (w, "／".join(owners)))
            else:
                infos.append("[A] 已登记的 kind 冲突：%s → %s（%s，未裁）"
                             % (w, "／".join(owners), rec.get("conflict_id") or "无冲突号"))
    for c in chans:
        if c.get("adjudicated") is False and c.get("machine_gated") is True:
            errs.append("[A] `%s` 未裁却标了 machine_gated＝虚报机检" % c["id"])
        if c.get("adjudicated") is not True and c.get("adjudicated") is not False:
            errs.append("[A] `%s` 的 adjudicated 不是布尔（必须明确 true/false，不许留空）" % c["id"])
        if "rule_source" not in c:
            errs.append("[A] `%s` 缺 rule_source（通道没有真源出处）" % c["id"])

    # ── [C] 真源在不在盘上（先做，[B] 的结论要引用它）──────────
    # ⚠ 首跑踩过：`for p in c["rule_source"]` 对**字符串**是按字符迭代，
    #   于是把一条正常路径报成 192 条"文件不在盘上"的假阳。⇒ 一律先归一成列表，
    #   并且 rule_source 为空/null **要报**（通道没真源是 high），不能被 `or []` 悄悄吃掉。
    for c in chans:
        rs = c.get("rule_source")
        if not (isinstance(rs, str) and rs.strip()):
            errs.append("[C] `%s` 的 rule_source 为空 ⇒ 这条通道没有真源出处" % c.get("id"))
        else:
            if not os.path.isfile(rs):
                errs.append("[C] `%s`(rule_source) 的真源文件不在盘上：%s" % (c["id"], rs))
        ex = c.get("extra_sources")
        if ex is None:
            ex = []
        if not isinstance(ex, list):
            errs.append("[C] `%s` 的 extra_sources 不是列表（%r）" % (c["id"], type(ex).__name__))
            ex = []
        for p in ex:
            if not (isinstance(p, str) and p.strip()):
                errs.append("[C] `%s` 的 extra_sources 里有空项" % c["id"])
            elif not os.path.isfile(p):
                errs.append("[C] `%s`(extra_sources) 的真源文件不在盘上：%s" % (c["id"], p))
    for s in reg.get("config_switches") or []:
        f = s.get("file")
        if f and not os.path.exists(f):
            errs.append("[C] 开关 `%s` 指向的位置不存在：%s" % (s.get("name"), f))

    # ── [B] 注册表 vs 代码 ────────────────────────────────────
    # declared／registered 在 [B] 之前建好：[D] 判 yaml 的 kind 归属也要用，
    # 不能放进 `else` 里——那样代码解析失败时 [D] 会 NameError（**查不了却装作查了**的一种）。
    declared = {}
    for c in chans:
        for w in c.get("declared_kind") or []:
            declared[w.lower()] = c["id"]
    alias = {}
    for a in reg.get("code_alias_words") or []:
        w = (a.get("word") or "").lower()
        if w:
            alias[w] = a
    registered = dict(declared)
    for w, a in alias.items():
        registered.setdefault(w, a.get("channel"))

    # ★ [B] 主探针改**黑盒**：批 4·2b 之后 `channel_of()` 的词表来自注册表，函数体里不再有字面量元组，
    #   AST 刮法会刮到空集 ⇒ 会把"机器认得 20 个词"误报成"一个都不认"（假阴）。
    #   探针直接问行为，并顺带量出"权威此刻在表里还是在代码兜底里"——不是声明出来的。
    probe, perr = probe_channel_of(PREFLIGHT, sorted(set(registered) | {"", "video"}))
    code = kinds_from_code(pref_src)
    if probe is None:
        errs.append("[B] 黑盒探针没跑成：%s ⇒ **这项没跑，不算通过**" % perr)
    elif code is None:
        errs.append("[B] 没能从 `%s` 里 AST 解析出 channel_of()（结构面这项没跑）" % PREFLIGHT)
    else:
        active = {ch: {str(w).lower() for w in ws} for ch, ws in (probe.get("active") or {}).items()}
        status = probe.get("status") or {}
        literal = {ch: {str(w).lower() for w in ws}
                   for ch, ws in (probe.get("literal") or {}).items()}
        in_code = {w: ch for ch, ws in active.items() for w in ws}
        if status.get("source") != "channels_registry":
            warns.append("[B] `channel_of()` 本次**没在用注册表**（source=%s；%s）"
                         " ⇒ 『注册表是通道权威』这句话此刻不成立，属降级运行："
                         "判定仍与迁移前一致，但表上写的没生效。差异=%s"
                         % (status.get("source"), status.get("reason"),
                            status.get("diff") or "无"))
        else:
            infos.append("[B] `channel_of()` 的词表**确实来自注册表**（schema v%s）；未裁但仍按现状路由的别名：%s"
                         % (status.get("schema_version"),
                            "、".join(status.get("alias_words_unadjudicated_routed_anyway") or []) or "无"))
        drift = {ch: {"only_active": sorted(active.get(ch, set()) - literal.get(ch, set())),
                      "only_literal": sorted(literal.get(ch, set()) - active.get(ch, set()))}
                 for ch in active if active.get(ch) != literal.get(ch)}
        if drift:
            warns.append("[B] 注册表推出的词表与代码里的**兜底字面量**不等：%s ⇒ 哪天表读不到退回兜底，"
                         "路由会静默变（这正是迁移设计要防的）" % drift)
        else:
            infos.append("[B] 兜底字面量与注册表集合相等 ⇒ 退表不改变任何一次判定")
        infos.append("[B·结构] AST 在函数体内刮到的字面量元组：%s"
                     % (json.dumps(code, ensure_ascii=False) if code else
                        "空（批 4·2b 之后属预期，故主判据已改黑盒）"))

        # 别名也算"已登记"，但**未裁的别名继续报 ⚠**——登记不等于裁定，
        # 让它变绿就是把洞藏起来（假阴比假阳坏）。
        # ⚠ `in_code` 用**探针**那份，绝不能再从 AST 的 `code` 重算：
        #   迁移后 `code` 是空集，重算会把 20 个词全报成"注册表声明了但机器不认"（假阳泛滥）。
        unadjudicated_alias = sorted(w for w, a in alias.items() if a.get("adjudicated") is not True)
        only_code = sorted(set(in_code) - set(registered))
        only_reg = sorted(set(declared) - set(in_code))
        mismatch = sorted(w for w in set(in_code) & set(registered)
                          if _canon(in_code[w]) != _canon(registered[w]))
        if unadjudicated_alias:
            warns.append("[B] %d 个别名词**登记了但通道归属从没裁过**：%s ⇒ 它们的稿子现在按所折入通道的判据审"
                         % (len(unadjudicated_alias), "、".join(unadjudicated_alias)))
        if only_code:
            warns.append("[B] 机器认但这些词**没登记进注册表** %d 个：%s"
                         % (len(only_code), "、".join(only_code)))
        if only_reg:
            warns.append("[B] 注册表声明了但机器不认 %d 个：%s ⇒ 这些 kind 词的稿子会走"
                         "`未裁`分支（没有机器质检，只有人工一条路）"
                         % (len(only_reg), "、".join(only_reg)))
        if mismatch:
            warns.append("[B] 两边都认但归的通道不同 %d 个：%s"
                         % (len(mismatch),
                            "、".join("%s(机器=%s/注册表=%s)" % (w, in_code[w], registered[w])
                                      for w in mismatch)))
        if not (only_code or only_reg or mismatch):
            infos.append("[B] 机器认的词**全部有登记**（声明或别名），且通道归属无冲突")
        data.update({
            "probe_ran": True,
            "authority_source": status.get("source"),
            "authority_reason": status.get("reason"),
            "schema_version": status.get("schema_version"),
            "active_kinds": {ch: sorted(ws) for ch, ws in active.items()},
            "words_recognized_total": len(in_code),
            "fallback_literals_equal": not drift,
            "code_words_not_registered": only_code,
            "registered_words_not_recognized": only_reg,
            "channel_mismatch_words": mismatch,
            "alias_unadjudicated": unadjudicated_alias,
            "unmapped_channels_not_routed": status.get("unmapped_channels_not_routed"),
        })

    # ── [D] workflow yaml ─────────────────────────────────────
    yamls = sorted(f for f in os.listdir(wf_dir)) if os.path.isdir(wf_dir) else []
    yamls = [f for f in yamls if f.endswith(".yaml")]
    if not yamls:
        errs.append("[D] `%s` 里没有 yaml（**这项没跑，不算通过**）" % wf_dir)
    else:
        no_kind, foreign, no_provider = [], [], []
        for f in yamls:
            t = rd(os.path.join(wf_dir, f))
            mk = re.search(r"^\s*prompt_kind:\s*([^\s#]+)?", t, re.M)
            kind = (mk.group(1) or "").strip().strip('"\'') if mk else None
            if mk is None:
                no_kind.append(f)
            elif kind == "":
                no_kind.append(f)
            elif kind not in registered and kind not in ("video",):
                foreign.append("%s(prompt_kind=%s)" % (f, kind))
            pv = re.search(r"^\s*provider:\s*([^\s#]+)?", t, re.M)
            if (pv is None or not (pv.group(1) or "").strip()):
                no_provider.append(f)
        if no_kind:
            warns.append("[D] %d／%d 份 yaml 没声明 prompt_kind：%s ⇒ 这些流的通道由兜底决定"
                         % (len(no_kind), len(yamls), "、".join(no_kind)))
        if foreign:
            errs.append("[D] %d 份 yaml 的 prompt_kind 不属于任何已登记通道：%s"
                        % (len(foreign), "、".join(foreign)))
        need = [c["id"] for c in chans if c.get("provider_required_in_yaml")]
        with_pv = len(yamls) - len(no_provider)
        if need and with_pv == 0:
            warns.append("[D] 注册表要求这些通道在 yaml 里带 provider（%s），"
                         "但实测 **%d／%d 份没写、0 份写了** ⇒ 该带的字段一个都不存在（GAP-E2）"
                         % ("、".join(need), len(no_provider), len(yamls)))
        elif no_provider:
            warns.append("[D] %d／%d 份 yaml 没写 provider：%s"
                         % (len(no_provider), len(yamls), "、".join(no_provider[:6])))
        infos.append("[D] 扫了 %d 份 yaml" % len(yamls))
        data.update({"probe_ran": data.get("probe_ran", False),
                     "yaml_total": len(yamls), "yaml_missing_prompt_kind": no_kind,
                     "yaml_foreign_prompt_kind": foreign,
                     "yaml_missing_provider": len(no_provider)})

    # ── [E] 项目与交付落点（批 4·3）─────────────────────────
    pj, pj_why = load_registry(PROJ_REG, "projects")
    cfg_txt = rd(CONFIG)
    m_pool = re.search(r"^pool_root:\s*(.+)$", cfg_txt, re.M)
    pool_declared = None
    if m_pool:
        pool_declared = m_pool.group(1).split("#")[0].strip().strip("'\"")
    if pj is None:
        errs.append("[E] 项目注册表读不到：%s ⇒ **本项没跑，不算通过**" % pj_why)
    else:
        e2, w2, i2, d2 = check_projects(pj, cfg_txt, pool_declared)
        errs += e2
        warns += w2
        infos += i2
        data["projects"] = d2

    # ── [F] run_slots：槽表里不许藏默认值（10-02 批 5-2 前半）──
    # 用户口径：值归人，规则只管「必须被显式决定并留痕」。
    # ⇒ 最可能的破口是我自己在槽表里顺手写个 suggested／default——那等于机器又替人定了，
    #   只是换个形式。这条属于「假阴比假阳坏」那一族：漏一个默认值比多报一次误报坏得多。
    rslots = reg.get("run_slots")
    if not isinstance(rslots, dict):
        warns.append("[F] 注册表没有 run_slots 段 ⇒ 运行期决定单尚未落地（值归人的机制还没建）")
    else:
        # ⚠ `_readme` 也是 list（字符串数组），要是当成槽组计数就会把说明句算成槽 ⇒ 排除下划线开头键
        groups = {k: v for k, v in rslots.items() if isinstance(v, list) and not k.startswith("_")}
        total = sum(len(v) for v in groups.values())
        if total == 0:
            errs.append("[F] run_slots 存在但一个槽都没有 ⇒ 空壳，不算已落地")
        forbidden = ("value", "default", "suggested", "recommend", "auto_fill",
                     "fallback_value", "预设值", "默认值", "建议值")
        offenders, no_why = [], []
        for gname, items in groups.items():
            for it in items:
                if not isinstance(it, dict):
                    continue
                hit = [k for k in it if any(f in str(k).lower() for f in forbidden)]
                if hit:
                    offenders.append("%s/%s → %s" % (gname, it.get("slot") or it.get("action"), hit))
                if not (it.get("why") or it.get("rule")):
                    no_why.append("%s/%s" % (gname, it.get("slot") or it.get("action")))
        if offenders:
            errs.append("[F] run_slots 里出现**取值类字段**（槽表只能声明「必须被人决定」，"
                        "不能写该选什么）：%s" % "；".join(offenders))
        if no_why:
            warns.append("[F] %d 个槽既没写 why 也没写 rule，日后没人知道它为什么必须问：%s"
                         % (len(no_why), "、".join(no_why[:6])))
        if not offenders and not no_why and total:
            infos.append("[F] run_slots 共 %d 个槽，全部只声明「必须人定＋留痕」，无一处藏默认值" % total)
        for gname in ("must_ask_every_run", "must_ask_every_project", "human_only_never_auto"):
            if gname in groups:
                infos.append("[F] %-24s %d 项" % (gname, len(groups[gname])))

    # ── [G] 决定单这一层（批 5-2）：两份声明不许各说各话，路径只许一处实现 ──
    # 为什么要单独一段：槽清单住在 channels_registry，分界原话住在 projects_registry，
    # 路径取法住在 engine/decision_sheet.py —— **三处**。任何一处改了另两处没跟，
    # G13 就会拿着一份没人认领的清单去拦人。这段只查「是不是同一件事」，不查值。
    ds = (pj or {}).get("decision_sheet") if isinstance(pj, dict) else None
    if pj is None:
        warns.append("[G] 项目注册表读不到 ⇒ 决定单对账**没跑**，不算通过（详见 [E]）")
    elif not isinstance(ds, dict):
        errs.append("[G] projects_registry 没有 decision_sheet 段 ⇒ 落点这条没有出处，"
                    "G13 拦人的依据找不到")
    else:
        tiers = ds.get("tiers") or {}
        decl = {"project": [str(x) for x in (tiers.get("project_level") or [])],
                "run": [str(x) for x in (tiers.get("run_level") or [])]}
        for tier, gname in (("project", "must_ask_every_project"),
                            ("run", "must_ask_every_run")):
            labels = []
            for e in ((rslots or {}).get(gname) or []):
                if not isinstance(e, dict):
                    continue
                if not e.get("label_cn"):
                    errs.append("[G] 槽 `%s` 没有 label_cn ⇒ 与 tiers 无从对账" % e.get("slot"))
                    continue
                labels.append(str(e["label_cn"]))
            a, b = sorted(decl[tier]), sorted(labels)
            if a != b:
                errs.append("[G] %s级槽标签两边不一致：tiers 说 %s，run_slots 说 %s"
                            " ⇒ 改了一处没改另一处（两边都改才算裁定落地）"
                            % ("项目" if tier == "project" else "运行", a, b))
            else:
                infos.append("[G] %s级 %d 个槽标签两边逐字一致"
                             % ("项目" if tier == "project" else "运行", len(a)))
        placement = str(ds.get("placement") or "").replace("\\\\", "\\").replace("/", "\\")
        probe, perr = probe_decision_sheet()
        if probe is None:
            errs.append("[G] 决定单路径探针没跑成：%s ⇒ **本项没跑，不算通过**" % perr)
        else:
            data["decision_sheet_probe"] = probe
            if probe.get("error"):
                errs.append("[G] 引擎拼不出决定单路径：%s" % probe["error"])
            # 落点声明里那个 `<项目>` 替换成什么，必须由代码自己说一遍：
            # 声明写 E:\创作\<项目>\_项目档案\…，代码却拼去别处＝两套取法（GAP-E1 那一族）。
            for pid, rec in sorted((probe.get("assembled") or {}).items()):
                if rec.get("error"):
                    errs.append("[G] 项目 `%s` 的决定单路径拼不出：%s" % (pid, rec["error"]))
                    continue
                want = placement.replace("<项目>", str(rec.get("asset_dir") or pid))
                got = str(rec.get("path", "")).replace("/", "\\")
                if got != want:
                    errs.append("[G] 项目 `%s` 实际拼出 %s，与注册表声明的落点 %s 不一致"
                                " ⇒ 声明与取法分叉了" % (pid, got, want))
                    continue
                filled = rec.get("human_filled") or []
                need = rec.get("project_slots") or []
                if not rec.get("exists"):
                    warns.append("[G] 项目 `%s` 还没有决定单（%s）⇒ 它下次出片会被 G13 拦；"
                                 "先建空白单再逐槽由人填" % (pid, rec.get("path")))
                elif len(filled) < len(need):
                    warns.append("[G] 项目 `%s` 的决定单只填了 %d／%d 个人给的槽，还缺：%s"
                                 " ⇒ 下一次跑这条项目会被 G13 拦（空槽不代填）"
                                 % (pid, len(filled), len(need),
                                    "、".join(sorted(set(need) - set(filled)))))
                else:
                    infos.append("[G] 项目 `%s` 决定单齐（%d 个槽都由人给过）" % (pid, len(filled)))
    # 别名必须真是现役参数名：登记了个没人用的别名＝把"名字分叉"藏进表里，
    # 将来人照着它填值反而填不动（这是 [C]「真源在不在盘上」的同一条思路搬到槽上）。
    wf_blob = "\n".join(rd(os.path.join(wf_dir, f))
                        for f in sorted(os.listdir(wf_dir)) if f.endswith(".yaml"))
    for e in ((rslots or {}).get("must_ask_every_run") or []):
        if not isinstance(e, dict):
            continue
        for alias in (e.get("accepts") or []):
            if re.search(r"^\s*%s\s*:" % re.escape(str(alias)), wf_blob, re.M):
                continue                          # 现役真在用的别名，合法
            if str(e.get("alias_compat_note") or "").strip():
                infos.append("[G] 槽 `%s` 的别名 `%s` 已不在任何 workflow 里用，但登记为**兼容别名**"
                             "（有退役条件才允许这样挂着）" % (e.get("slot"), alias))
                continue
            errs.append("[G] 槽 `%s` 登记的别名 `%s` 在任何 workflow 的 args 里都不存在，"
                        "也没写兼容别名退役条件 ⇒ 别名是死的（要么改名，要么删，要么补 alias_compat_note）"
                        % (e.get("slot"), alias))
    # G13 覆盖面：这里只报**事实**。「哪条流必须有 G13」是判据，钉在
    # engine/tests/test_run_decisions.py —— 校验器不当被告，也不当立法。
    yfiles = [f for f in sorted(os.listdir(wf_dir)) if f.endswith(".yaml")]
    both, only13, none13 = [], [], []
    for f in yfiles:
        lines = [m.group(0) for m in
                 re.finditer(r"^\s*auto_gates:[^\n]*", rd(os.path.join(wf_dir, f)), re.M)]
        if not lines:
            continue
        has = ["G13" in l for l in lines]
        (both if all(has) else (none13 if not any(has) else only13)).append(f)
    infos.append("[G] auto_gates 有 gate 步的流 %d 份：全带 G13 %d 份／部分带 %d 份／一条都没带 %d 份"
                 % (len(both) + len(only13) + len(none13), len(both), len(only13), len(none13)))
    for key, lst in (("g13_all", both), ("g13_partial", only13), ("g13_none", none13)):
        data[key] = lst
    data["yaml_total"] = len(yfiles)

    return errs, warns, infos, data


def _canon(ch):
    """把代码侧的通道名与注册表 id 对齐（代码返回 h3/cloud/image，id 是 h3_local/…）。"""
    m = {"h3": "h3_local", "cloud": "cloud_sd", "image": "image_chain"}
    return m.get(ch, ch)


def check_projects(pj, cfg_txt, pool_root_declared):
    """[E] 项目与交付落点：声明 vs `config.yaml` 的实际取法，两边不静默分叉。

    只查**测得出**的四件事，不替用户判"哪个目录算项目"（那是 status 的活，归资产索引）：
      1. 引擎当前项目（`config.yaml: project`）在本表登过没有；
      2. 别名表两边是否一致（config 的 `project_aliases` vs 本表 `projects[].aliases`）；
      3. 项目名有没有撞交付根的**保留名**（撞了 G11 的串项目判定就失效——9-18 那次真串过）；
      4. 声明的后期落点 `post_production.canonical_home` 与"现状"字段说的是不是一回事
         （写了 exists_now:true 而目录不存在＝虚报，直接 error）。
    """
    errs, warns, infos, data = [], [], [], {"probe_ran": True}
    if not isinstance(pj, dict) or not isinstance(pj.get("projects"), list):
        errs.append("[E] 项目注册表缺 projects 段 ⇒ 本项没跑，不算通过")
        data["probe_ran"] = False
        return errs, warns, infos, data
    chans = pj["projects"]
    ids = [c.get("id") for c in chans]
    if len(ids) != len(set(ids)):
        errs.append("[E] 项目 id 重复")
    # 别名唯一性：同一别名指向两个项目＝G11 判串项目时会自相矛盾
    seen = {}
    for c in chans:
        for a in c.get("aliases") or []:
            seen.setdefault(a, []).append(c["id"])
    for a, owners in sorted(seen.items()):
        if len(owners) > 1:
            errs.append("[E] 别名 `%s` 同时属于 %s ⇒ 串项目判定会失效" % (a, "／".join(owners)))

    def cfg_scalar(key):
        # ⚠ config.yaml 的值后面常跟**行内注释**（`project: '无音'   # 当前项目…`），
        #   用 `\s*$` 收尾的正则会**整行匹配失败** ⇒ 读出 None，
        #   再把"我正则写窄了"报成"config 里没读到 project"——那是假阴，比假阳坏。
        m = re.search(r"^%s:\s*(.+)$" % key, cfg_txt, re.M)
        if not m:
            return None
        v = m.group(1).split("#")[0]           # 去行内注释
        v = v.split("＃")[0]                     # 全角井号也去（中文注释里常见）
        return v.strip().strip("'\"").strip()
    cur = cfg_scalar("project")
    data["config_project"] = cur
    if cur is None:
        errs.append("[E] `config.yaml` 里没读到 project ⇒ 本项没跑，不算通过")
    elif cur not in ids:
        warns.append("[E] 引擎当前项目 `%s` **没登记在项目注册表** ⇒ 表盖不住现役默认值" % cur)
    else:
        infos.append("[E] 引擎当前项目 `%s` 已在表内登记" % cur)

    # config 的别名表 vs 表里的别名。⚠ 这块是**扁平的两空格条目**，
    # 不是"父键＋缩进子块"，用嵌套块正则去抓会只抓到第一行 ⇒ 后面全判成"注册表多出来"（假阳）。
    cfg_alias = {}
    lines = cfg_txt.splitlines()
    try:
        i0 = next(i for i, l in enumerate(lines) if re.match(r"^project_aliases:\s*$", l))
    except StopIteration:
        i0 = None
    if i0 is not None:
        for line in lines[i0 + 1:]:
            if line.strip() and not line.startswith("  "):
                break                        # 缩进结束＝块结束
            mm = re.match(r"^\s+(\S[^:\[]*):\s*\[(.*)\]", line)
            if mm:
                cfg_alias[mm.group(1).strip()] = [x.strip() for x in mm.group(2).split(",")
                                                  if x.strip()]
    data["config_aliases_parsed"] = len(cfg_alias)
    if cfg_txt and "project_aliases" in cfg_txt and not cfg_alias:
        errs.append("[E] `config.yaml` 有 project_aliases 但一条没解析出来 ⇒ **解析器失效**，"
                    "这项不能算通过（假阴比假阳坏）")
    for name, words in sorted(cfg_alias.items()):
        hit = [c for c in chans if c.get("id") == name]
        if not hit:
            warns.append("[E] `config.yaml` 别名表有项目 `%s`，注册表没有 ⇒ 又长出一份抄本" % name)
            continue
        reg_words = sorted(hit[0].get("aliases") or [])
        if reg_words != sorted(words):
            errs.append("[E] 项目 `%s` 两边别名不等：config=%s ／ 注册表=%s"
                        % (name, sorted(words), reg_words))
    for c in chans:
        if c.get("id") not in cfg_alias and c.get("id") != cur:
            infos.append("[E] 表里登记的项目 `%s` 在 config 别名表里没有（只声明身份，不代表引擎认识它）" % c["id"])

    dl = pj.get("delivery") or {}
    reserved = dl.get("reserved_names_not_projects") or []
    if len(reserved) != len(set(reserved)):
        errs.append("[E] 保留名清单自身有重复")
    clash = sorted(set(ids) & set(reserved))
    if clash:
        errs.append("[E] 项目名撞了交付根保留名：%s ⇒ G11 无法从路径唯一反推项目" % "、".join(clash))
    pr = dl.get("pool_root")
    data["pool_root"] = pr
    if pr and pool_root_declared and pr != pool_root_declared:
        errs.append("[E] 交付根两边不等：注册表 `%s` ／ config.yaml `%s`" % (pr, pool_root_declared))
    elif pr:
        infos.append("[E] 交付根声明与 config.yaml 一致：%s" % pr)
    if pr and not os.path.isdir(pr):
        errs.append("[E] 声明的交付根不在盘上：%s" % pr)

    pp = pj.get("post_production") or {}
    home = pp.get("canonical_home")
    exists_now = pp.get("exists_now")
    real = bool(home) and os.path.isdir(home)
    data["post_home"] = {"declared": home, "declared_exists_flag": exists_now, "really_exists": real}
    if exists_now is True and not real:
        errs.append("[E] `post_production.exists_now: true` 但目录不存在：%s ⇒ **虚报**" % home)
    elif exists_now is False and real:
        errs.append("[E] `post_production.exists_now: false` 但目录已在盘上：%s ⇒ 状态字段陈旧" % home)
    elif exists_now is False:
        warns.append("[E] 后期落点**尚未建立**（声明的目标态 %s 不存在）⇒ 属 GAP-D3 未闭，本项只是把它摆出来" % home)
    else:
        infos.append("[E] 后期落点已建立且与声明一致：%s" % home)
    nd = pj.get("projects_not_declared") or {}
    data["projects_not_declared_count"] = len(nd.get("list") or [])
    return errs, warns, infos, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=REG)
    ap.add_argument("--strict", action="store_true",
                    help="有 error 级问题时返回 1（默认恒 0＝只报不拦，与三件套同风格）")
    ap.add_argument("--json", metavar="PATH", help="额外把结果写成 json（默认不落盘）")
    ap.add_argument("--print-json", action="store_true",
                    help="只把结构化结果打到 stdout（`scan_system.py` 用它，避免两份探针实现）")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    reg, why = load_registry(a.registry)
    if not a.print_json:
        print("=" * 72)
        print("check_registry.py · 通道与配置注册表自校验（只读）")
        print("注册表：%s" % a.registry)
        print("=" * 72)
    if reg is None:
        # ⚠ 读不到表时 `--print-json` 也要给**结构**，否则调用方拿到空 stdout 会当成"没问题"——
        #   正则漏匹配＝静默不报那一族在这里同样成立。
        if a.print_json:
            json.dump({"errors": ["注册表读不到：%s ⇒ 四项一项都没跑" % why],
                       "warns": [], "data": {"probe_ran": False, "registry_load_error": why}},
                      sys.stdout, ensure_ascii=False, indent=1)
            sys.stdout.write("\n")
            return 1 if a.strict else 0
        print("!! 注册表读不到：%s ⇒ **四项校验一项都没跑，这不是通过**" % why)
        return 1 if a.strict else 0

    errs, warns, infos, data = check(reg, rd(PREFLIGHT), WF_DIR, a.verbose)
    if a.print_json:
        json.dump({"errors": errs, "warns": warns, "data": data},
                  sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 1 if (a.strict and errs) else 0
    for m in infos:
        if a.verbose:
            print("   · %s" % m)
    for m in warns:
        print("  ⚠ %s" % m)
    for m in errs:
        print("  !! %s" % m)
    print("-" * 72)
    print("通道 %d 条（已裁 %d／未裁 %d）｜error %d｜warn %d"
          % (len(reg["channels"]),
             sum(1 for c in reg["channels"] if c.get("adjudicated")),
             sum(1 for c in reg["channels"] if not c.get("adjudicated")),
             len(errs), len(warns)))
    if a.json:
        json.dump({"registry": a.registry, "errors": errs, "warns": warns, "infos": infos},
                  io.open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写出：%s" % a.json)
    if a.strict and errs:
        print("!! --strict：有 error ⇒ 退出码 1")
        return 1
    print("本脚本只报不拦：退出码 0" if not errs else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
