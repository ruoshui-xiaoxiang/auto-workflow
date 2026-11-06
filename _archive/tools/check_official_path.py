#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_official_path.py · 「声明壳」的自校验（默认只报不拦，--strict 才返回 1）。

为什么要有它（2026-10-19 治理批 Phase 3）
----------------------------------------
`D:\\AIWorkflow\\官方路径.json` 是本机出片流水线的唯一机器可读真源清单。但一份清单如果
没人校，它就是第 12 份会漂移的抄本——本项目已经用 11 份互相矛盾的契约文件证明了这件事。
所以清单落地的同时必须配一把尺，把「登记的东西真的在盘上吗」「废弃的东西真的留桩了吗」
「有没有真源又住回 tmp/ 了」变成机器可检。

十一项校验（分开报数、不凑数、不互相掩盖）
  [P1] 入口数＝2（用户 2026-10-19 硬裁定：门面只留娱乐流 + agent，多一个少一个都算漂移），
       且每条入口都写了可执行命令／地址。
  [P2] `truth_sources` 逐个 stat：把 declared 与 runtime_loaded_from 里的绝对路径全刮出来
       挨个 exists()。**刮不出路径**单独报一类（假阴比假阳坏——解析器失效不能算通过）。
  [P3] `deprecated` 每一项 ＋ `truth_sources` 里带『原处桩』的每一项：要么原身还在（未归档），
       要么原处有路障桩。「文件没了且没桩」＝违反『废弃不许静默消失』，报 error。
       后者覆盖的是**上移**（真源从 tmp/ 搬进 tools/，老命令不能只报 FileNotFoundError）。
       桩的判定是静态签名（OFFICIAL-PATH-TOMBSTONE + sys.exit(78)）；
       加 --run-stubs 才真去执行桩验退出码（默认不执行，避免检查器自己跑出副作用）。
  [P4] 孤儿脚本扫描：tools/*.py 与 engine/*.py 里，**在现役语料中零引用**的列出来。
       降两级不算孤儿：① 已登记在官方路径.json ② 自带 Usage/用法 说明（人手调用的 CLI）。
       ⚠ 语料**故意不含 logs/**——历史日志里出现过不等于现在还有人调。
  [P5] tmp/ 落点禁令：官方路径.json 的 truth_sources 里不许出现 tmp/ 路径；
       三个 registry（thresholds / channels / projects）的原文里也不许出现。
       这条现在是**红的**，红得对：规则底座 runtime 仍住在 tmp\\wzy（Phase 4 上移）。
  [P6] 汇总 check_registry.py --print-json 的 error 数（不重实现，直接问它）。
  [P7] AGENTS.md 快照对账：AGENTS.md 是 agent 自动加载的那份契约，它**必须**内联入口与禁令
       （不点链接的 agent 什么都看不到），内联就有第二份抄本、抄本就会漂。解法不是别抄，
       是抄了但**双向逐字对账**：两段用 SNAPSHOT 标记包起来，与 json 互查（缺一条、多一条都报）。
  [P8] 声明牌存在性：json 的 `plates.dirs`（11 处）逐个查 `_官方路径声明.md` 在不在。
       牌子自己也是文件 ⇒ 会被误删、被清理脚本扫走、被 git clean 吃掉。没人校的告示牌等于没有。
  [P9] 否定词表不许漂：`tools/ban_words.py`（纯数据副本）↔ `tmp/wzy/prompt_lint.py` 的 NEG
       逐个比对。这张表是 G7 认「禁令句」的判据，漂了不报错、只会让闸悄悄变松或变紧。
       ⚠ 比对在**子进程**里做：prompt_lint 一 import 就 os.chdir 到 tmp/wzy，别污染本进程 CWD。
  [P10] 题材分层登记自洽：`engine/genres_registry.json` 的落点存在性、项目键与
       projects_registry 是否逐字相等、画风档与 prompt_lint 的 RENDER_TOXIC_BY_PROFILE
       **实读**是否相等、以及🔴**有没有把标定值抄进来**（本表纪律是只管键与元数据）。

最后还有一层「已登记例外」（`accepted_red`）：一把**恒红**的尺子等于没有尺子，所以允许把
已知项降级成 warn——但降级有代价：必须写 reason ＋ review_by，过期自动升回 error，
`expect_count` 与实际命中数不符就报错，一条都没命中的登记会被点名要求删掉（防僵尸豁免）。

实施方案里的第⑤项原写「接进 check_convergence.py」——**那个文件盘上不存在**（2026-10-19
find 全仓无命中），是方案文档里的一处前提错误。这里改成 [P6] 直接 subprocess 问
check_registry.py，效果等价（一条命令证明声明壳完整）且不新增第二份聚合实现。
[P7] 是实施方案之外**新增**的一项：Phase 3 查实上一版 AGENTS.md 正文一半是乱码（见该文件第 7 节），
重写它时顺带把"薄壳内联抄本会漂"这件事变成机器可检。

只读：本脚本不写任何文件（除 --json 明确指定路径时）。默认退出码 0，与三件套同风格。

Usage: py D:\\AIWorkflow\\tools\\check_official_path.py [-v] [--strict] [--run-stubs] [--json PATH]
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys

ROOT = r"D:\AIWorkflow"
MANIFEST = os.path.join(ROOT, "官方路径.json")
CHECK_REGISTRY = os.path.join(ROOT, "tools", "check_registry.py")
REGISTRIES = [
    os.path.join(ROOT, "engine", "thresholds_registry.json"),
    os.path.join(ROOT, "engine", "channels_registry.json"),
    os.path.join(ROOT, "engine", "projects_registry.json"),
]
TOMBSTONE_MARK = "OFFICIAL-PATH-TOMBSTONE"
EXIT_CONFIG = 78          # EX_CONFIG：与"脚本自己跑失败"区分开

# 路径刮取的终止符：空白 + 全角标点 + 本项目爱用的几个符号。
# ⚠ 不含 ASCII `.` `-` `_`，否则会截断 h3_official_spec.py / flux_i2i_api.json 这类名字。
_STOP = set(" \t\r\n，、。；：（）【】「」《》“”‘’·⇒⚠🔴＋=＝|｜*＊?？!！~～…→←"
            "\"'`<>")


def _try_utf8(stdout):
    """Windows 控制台/管道下把 stdout 拧成 utf-8，否则中文与 emoji 会变成 cp936 问号。"""
    for s in (stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def rd(p):
    try:
        return io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def load_manifest(path=MANIFEST):
    if not os.path.isfile(path):
        return None, "文件不存在：%s" % path
    try:
        d = json.loads(rd(path))
    except Exception as e:
        return None, "json 解析失败：%s" % e
    for k in ("entries", "truth_sources", "deprecated"):
        if not isinstance(d.get(k), dict):
            return None, "`%s` 段缺失或不是对象" % k
    return d, None


def extract_paths(text):
    """从一段（可能夹着中文说明的）文本里刮出所有带盘符的绝对路径。

    返回去重且保序的列表。刮不到就返回 []——调用方必须把 [] 当**一种结果**报出来，
    不能静默当"没问题"（同 check_registry 的 [E] 假阴纪律）。
    """
    if not isinstance(text, str) or not text:
        return []
    out, seen = [], set()
    for m in re.finditer(r"[A-Za-z]:[\\/][^\s]*", text):
        raw = m.group(0)
        # 逐字符截到第一个终止符
        buf = []
        for ch in raw:
            if ch in _STOP:
                break
            buf.append(ch)
        p = "".join(buf).rstrip(".,;:、")
        if len(p) >= 4 and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def norm(p):
    return p.replace("/", "\\").rstrip("\\")


def is_tmp(p):
    n = norm(p).lower()
    return "\\tmp\\" in n or n.endswith("\\tmp")


def _walk_strings(node, prefix=""):
    """递归产出 (json 指针, 字符串值)。

    用指针而不是行号：行号会随文件编辑漂（改一条 note 就能让所有下游指针错位），
    而 `thresholds[12].places[1].file` 这种指针只要结构不改就稳定 ⇒ accepted_red 的
    match 也才能写稳定子串。
    """
    if isinstance(node, dict):
        for k, v in node.items():
            for x in _walk_strings(v, "%s.%s" % (prefix or "$", k)):
                yield x
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for x in _walk_strings(v, "%s[%d]" % (prefix or "$", i)):
                yield x
    elif isinstance(node, str):
        yield (prefix or "$", node)


def _walk_numbers(node, prefix=""):
    """同 _walk_strings，但只产出 int/float（bool 除外——True/False 是判断不是标定值）。"""
    if isinstance(node, dict):
        for k, v in node.items():
            for x in _walk_numbers(v, "%s.%s" % (prefix or "$", k)):
                yield x
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for x in _walk_numbers(v, "%s[%d]" % (prefix or "$", i)):
                yield x
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield (prefix or "$", node)


# ---------------------------------------------------------------- [P1] 入口数
def p1_entries(d, errs, warns, infos, data):
    ents = {k: v for k, v in d["entries"].items() if k != "_note"}
    data["entries"] = sorted(ents)
    if len(ents) != 2:
        errs.append("[P1] 入口数 = %d，应为 2（用户 2026-10-19 硬裁定：门面只留娱乐流 + agent）"
                    "⇒ 实际登记：%s" % (len(ents), "、".join(sorted(ents)) or "（空）"))
    else:
        infos.append("[P1] 入口数 = 2：%s" % "、".join(sorted(ents)))
    for name, e in sorted(ents.items()):
        if not isinstance(e, dict):
            errs.append("[P1] 入口 `%s` 不是对象" % name)
            continue
        cmd = e.get("命令") or e.get("入口")
        if not cmd:
            errs.append("[P1] 入口 `%s` 既没有『命令』也没有『入口』字段 ⇒ agent 读到也不知道怎么起" % name)
        st = e.get("状态", "")
        if "待建" in st:
            warns.append("[P1] 入口 `%s` 状态＝%s（声明的目标态尚未落地，不算通过也不算失败）" % (name, st))
        data.setdefault("entry_status", {})[name] = st


# ------------------------------------------------------- [P2] truth_sources stat
def p2_truth_sources(d, errs, warns, infos, data):
    ts = {k: v for k, v in d["truth_sources"].items() if k != "_note"}
    data["truth_sources_total"] = len(ts)
    n_ok = n_missing = n_nopath = 0
    missing, nopath = [], []
    for name, e in sorted(ts.items()):
        if not isinstance(e, dict):
            errs.append("[P2] 真源 `%s` 不是对象" % name)
            continue
        pending = "待建" in str(e.get("状态", ""))
        paths = extract_paths(e.get("declared")) + extract_paths(e.get("runtime_loaded_from"))
        if not paths:
            n_nopath += 1
            nopath.append(name)
            if pending:
                infos.append("[P2] 真源 `%s` 无可校的绝对路径（declared 是模板/占位），且状态＝待建" % name)
            else:
                warns.append("[P2] 真源 `%s` **刮不出任何绝对路径** ⇒ 这条登记无法被机器校验"
                             "（不是通过，是尺子够不着）。declared=%r" % (name, e.get("declared")))
            continue
        bad = [p for p in paths if not os.path.exists(norm(p))]
        if bad:
            n_missing += 1
            missing.append((name, bad))
            for p in bad:
                msg = "[P2] 真源 `%s` 登记的路径不在盘上：%s" % (name, p)
                if pending:
                    warns.append(msg + "（状态＝待建，属声明的目标态）")
                else:
                    errs.append(msg + " ⇒ 清单在说谎")
        else:
            n_ok += 1
            infos.append("[P2] 真源 `%s` 全部命中（%d 条路径）" % (name, len(paths)))
    data["truth_sources_stat"] = {"ok": n_ok, "missing": n_missing, "no_path": n_nopath}
    data["truth_sources_missing"] = [{"name": n, "paths": b} for n, b in missing]
    data["truth_sources_no_path"] = nopath
    if n_ok + n_missing + n_nopath != len(ts):
        errs.append("[P2] 分类计数 %d+%d+%d != 真源总数 %d ⇒ **本项校验自身有漏**，不能算通过"
                    % (n_ok, n_missing, n_nopath, len(ts)))


# ------------------------------------------------------- [P3] deprecated 桩
def _looks_like_tombstone(text):
    return TOMBSTONE_MARK in text or ("sys.exit(%d)" % EXIT_CONFIG in text
                                     and ("已上移" in text or "已归档" in text or "已废" in text))


def _stub_needs_exit_code(path):
    """`.py` 桩必须以 exit 78 退出（调用方靠退出码区分"路封了"和"脚本崩了"）；
    `.md` 路标没有退出码这回事，只认签名。2026-10-19 Phase 5：ComfyUI/AGENTS.md 改成路标后，
    原来的判定会把它当"原身仍在"，等于看不出那份 25KB 上游指南已经被换掉了。
    """
    return path.lower().endswith(".py")


def _stub_targets(d):
    """收集所有「应该有桩」的位置：deprecated[].path ＋ truth_sources[].原处桩。

    后者覆盖的是**上移**（不是废弃）：真源从 tmp/ 搬进 tools/ 之后，原处要留桩，
    否则老命令报 FileNotFoundError，调用方照样会去猜。2026-10-19 motion_qc.py 就是这一类。
    """
    out = []
    for name, e in sorted({k: v for k, v in d["deprecated"].items() if k != "_note"}.items()):
        if isinstance(e, dict):
            out.append(("deprecated", name, e.get("path", ""), e))
    ts = {k: v for k, v in d["truth_sources"].items() if k != "_note"}
    for name, e in sorted(ts.items()):
        if isinstance(e, dict) and e.get("原处桩"):
            out.append(("上移", name, e["原处桩"], e))
    return out


def p3_deprecated(d, errs, warns, infos, data, run_stubs=False):
    dep = {k: v for k, v in d["deprecated"].items() if k != "_note"}
    targets = _stub_targets(d)
    data["deprecated_total"] = len(dep)
    data["stub_targets_total"] = len(targets)
    live, stubbed, vanished = [], [], []
    for kind, name, raw, e in targets:
        tag = "[P3]" if kind == "deprecated" else "[P3/上移]"
        paths = extract_paths(raw)
        if not paths:
            warns.append("%s %s项 `%s` 的路径刮不出绝对路径：%r" % (tag, kind, name, raw))
            continue
        for p in paths:
            np = norm(p)
            if not os.path.exists(np):
                vanished.append((name, p))
                errs.append("%s %s项 `%s` 的原身已不在盘上且**原处没有桩**：%s "
                            "⇒ 违反『废弃不许静默消失』（调用方拿到 FileNotFoundError 会自己去猜替代方案）"
                            % (tag, kind, name, p))
                continue
            txt = rd(np)
            if _looks_like_tombstone(txt):
                if _stub_needs_exit_code(np) and "sys.exit(%d)" % EXIT_CONFIG not in txt:
                    errs.append("%s `%s` 有桩标记但缺 sys.exit(%d)：%s" % (tag, name, EXIT_CONFIG, p))
                    continue
                if TOMBSTONE_MARK not in txt:
                    warns.append("%s `%s` 的桩退出码对但缺 `%s` 签名 ⇒ 只能靠中文措辞认，"
                                 "换个写法就认不出来了：%s" % (tag, name, TOMBSTONE_MARK, p))
                stubbed.append((name, p))
                infos.append("%s %s项 `%s` 已立桩：%s" % (tag, kind, name, p))
                if run_stubs and not _stub_needs_exit_code(np):
                    infos.append("%s   ↳ `%s` 是文档路标不是可执行桩，跳过实跑"
                                 % (tag, os.path.basename(np)))
                elif run_stubs:
                    try:
                        r = subprocess.run([sys.executable, np], capture_output=True, timeout=30,
                                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                        if r.returncode == EXIT_CONFIG:
                            infos.append("%s   ↳ 实跑桩 %s ⇒ 退出码 %d ✔"
                                         % (tag, os.path.basename(np), r.returncode))
                        else:
                            errs.append("%s   ↳ 实跑桩 %s ⇒ 退出码 %d，应为 %d（EX_CONFIG）"
                                        % (tag, os.path.basename(np), r.returncode, EXIT_CONFIG))
                    except Exception as ex:
                        errs.append("%s   ↳ 实跑桩 %s 失败：%s" % (tag, os.path.basename(np), ex))
            else:
                live.append((name, p))
                st = str(e.get("状态", ""))
                infos.append("%s %s项 `%s` 原身仍在（%s）：%s" % (tag, kind, name, st or "未标状态", p))
                if kind == "deprecated" and not st:
                    warns.append("%s 废弃项 `%s` 没有『状态』字段 ⇒ 分不清是"
                                 "『还没归档』还是『忘了归档』" % (tag, name))
    data["deprecated_stat"] = {"live": len(live), "stubbed": len(stubbed), "vanished": len(vanished)}
    data["deprecated_stubbed"] = [p for _, p in stubbed]
    # 反向也校：`archived` 段登记的东西必须**真的不在原位了**。
    # 不校的话，有人把它拷回去（或归档根本没做成）清单照样绿着 —— 那就成了第二份说谎的清单。
    arch = (d.get("archived") or {}).get("items") or []
    n_gone = n_back = 0
    for it in arch:
        if not isinstance(it, dict):
            continue
        p = it.get("path")
        if not p:
            continue
        np = norm(p) if os.path.isabs(p) else os.path.join(ROOT, p)
        if os.path.exists(np):
            n_back += 1
            errs.append("[P3] `archived` 段登记的 `%s` **又在原位出现了** ⇒ 要么归档被撤销了、"
                        "要么有人拷了回去。清单与盘面不一致，请二选一：改清单或再归档" % p)
        else:
            n_gone += 1
    data["archived_stat"] = {"declared": len(arch), "gone": n_gone, "back_in_place": n_back}
    if arch and n_back == 0:
        infos.append("[P3] archived 段 %d 项全部确认已离开原位 ✔" % len(arch))


# ------------------------------------------------------- [P4] 孤儿脚本
def _corpus_files():
    """现役语料。**故意不含 logs/ 与 tmp/**：历史日志里出现过 ≠ 现在还有人调。"""
    out = []
    top = ["AGENTS.md", "README.md", "官方路径.json"]
    for t in top:
        p = os.path.join(ROOT, t)
        if os.path.isfile(p):
            out.append(p)
    for sub, depth in (("engine", 3), ("tools", 1)):
        base = os.path.join(ROOT, sub)
        for dp, dns, fns in os.walk(base):
            rel = os.path.relpath(dp, base)
            if rel != "." and len(rel.split(os.sep)) >= depth:
                dns[:] = []
                continue
            dns[:] = [x for x in dns if x not in ("__pycache__", "logs", "output", ".git")]
            for f in fns:
                if f.endswith((".py", ".yaml", ".yml", ".json", ".md", ".bat", ".ps1")):
                    # 🔴 排除 `_` 前缀的 .md：那是**治理路标**（_孤儿脚本已打包_*.md 之类），
                    #   它只是"谈论"那些脚本、不是调用它们。第一版没排，结果我 2026-10-19
                    #   写的那块路标把留下的 9 个孤儿全"洗白"成了非孤儿，[P4] 从 9 掉到 4 ——
                    #   尺子被自己的产出污染了。约定与 `_官方路径声明.md`／`_路障桩模板.py` 一致。
                    if f.startswith("_") and f.endswith(".md"):
                        continue
                    out.append(os.path.join(dp, f))
    for dp, dns, fns in os.walk(r"E:\LocalAI"):
        if os.path.relpath(dp, r"E:\LocalAI").count(os.sep) >= 2:
            dns[:] = []
            continue
        dns[:] = [x for x in dns if x not in ("__pycache__", ".git", "node_modules", "models")]
        for f in fns:
            if f.endswith((".md", ".bat", ".ps1", ".py", ".json", ".yaml")):
                out.append(os.path.join(dp, f))
    return out


def _self_documents(path):
    """自带用法说明的人手 CLI ⇒ 零引用是正常的，不算孤儿。"""
    head = "".join(rd(path).splitlines(True)[:40])
    return bool(re.search(r"(?im)^\s*(Usage|用法|使用|运行|示例)\s*[:：]", head)) or "Usage:" in head


def p4_orphans(d, errs, warns, infos, data):
    """孤儿脚本扫描。

    ⚠ 语料**必须含 tools/*.py 自己**——tool 调 tool 是最常见的一种引用
      （check_h3_all.py 就是这么调 check_h3_prompt.py / check_h3_dialogue.py 的）。
      第一版把候选脚本从语料里剔了（本意是排自引用），结果把 tool→tool 的边全抹掉，
      51 个"孤儿"里一大片是假阳。正确做法：语料收全，计数时只跳过**它自己那一份**。
    """
    manifest_txt = rd(MANIFEST)
    cands = []
    for sub in ("tools", "engine"):
        base = os.path.join(ROOT, sub)
        if not os.path.isdir(base):
            continue
        for f in sorted(os.listdir(base)):
            if not f.endswith(".py") or f.startswith("_") or ".bak" in f:
                continue
            if f == os.path.basename(__file__):
                continue
            cands.append(os.path.join(base, f))
    cand_set = set(os.path.abspath(c) for c in cands)
    corpus = _corpus_files()
    blob = {}
    for p in corpus:
        t = rd(p)
        if t:
            blob[os.path.abspath(p)] = t
    data["orphan_scan"] = {"candidates": len(cands), "corpus_files": len(blob),
                           "corpus_contains_candidates": len(cand_set & set(blob))}
    orphans, handcli, registered = [], [], []
    for c in cands:
        name = os.path.basename(c)
        ap = os.path.abspath(c)
        hits = [p for p, t in blob.items() if name in t and p != ap]
        if hits:
            continue
        if name in manifest_txt:
            registered.append(name)
            infos.append("[P4] `%s` 现役语料零引用，但已登记在官方路径.json ⇒ 不算孤儿" % name)
        elif _self_documents(c):
            handcli.append(name)
            infos.append("[P4] `%s` 零引用但自带 Usage 说明 ⇒ 人手调用的 CLI，不算孤儿" % name)
        else:
            orphans.append(name)
    # 一条 warn 报全名单，不是一条一行 —— 51 行 warn 会把 [P5] 那 5 条真 error 淹掉，
    # 而淹掉之后人就只看 warn 了，尺子就白装了。明细在 --json / --print-json 里。
    if orphans:
        warns.append("[P4] 孤儿候选 %d 个（在 %d 份现役语料中零引用、未登记官方路径.json、"
                     "也无 Usage 说明）⇒ 需人判是死码还是漏登记。本项**只报不删**，"
                     "完整名单见 --print-json 的 data.orphans：\n      %s"
                     % (len(orphans), len(blob), "\n      ".join(
                         "、".join(orphans[i:i + 6]) for i in range(0, len(orphans), 6))))
    data["orphans"] = orphans
    data["orphans_handcli"] = handcli
    data["orphans_registered"] = registered
    infos.append("[P4] 扫 %d 个脚本／%d 份语料 ⇒ 有引用 %d、登记豁免 %d、CLI 豁免 %d、孤儿候选 %d"
                 % (len(cands), len(blob), len(cands) - len(orphans) - len(handcli) - len(registered),
                    len(registered), len(handcli), len(orphans)))
    # 探测器自检：语料里必须真的含候选脚本，否则 tool→tool 的边看不见，
    # 报出来的"孤儿"全是假阳（第一版就栽在这儿）。假阴比假阳坏，假阳比没报更坏——
    # 因为它会让人去删活代码。
    if cands and data["orphan_scan"]["corpus_contains_candidates"] == 0:
        errs.append("[P4] 语料里一个候选脚本都没含进来 ⇒ tool→tool 引用不可见，"
                    "上面那批『孤儿候选』**全是假阳，不许据此删任何东西**")
    if not blob:
        errs.append("[P4] 语料一份都没读到 ⇒ 本项等于没跑，不是通过")


# ------------------------------------------------------- [P5] tmp 落点禁令
def p5_no_tmp(d, errs, warns, infos, data):
    """tmp/ 落点禁令。

    ⚠ 只校 declared 与 runtime_loaded_from，**不校 `原处桩`**：上移类真源的老位置就在 tmp 下，
      桩本来就该立在那儿。禁令的立论是「真源不许住 tmp」（清 tmp 会让闸门静默落到兜底词表），
      不是「tmp 里不许有我们的文件」。把桩也算进来会让这条尺永远红，红久了就没人看了。
    """
    hits = []
    ts = {k: v for k, v in d["truth_sources"].items() if k != "_note"}
    for name, e in sorted(ts.items()):
        if not isinstance(e, dict):
            continue
        for field in ("declared", "runtime_loaded_from"):
            for p in extract_paths(e.get(field)):
                if is_tmp(p):
                    hits.append("官方路径.json truth_sources[%s].%s" % (name, field))
                    errs.append("[P5] 真源 `%s` 的 %s 住在 tmp 下：%s "
                                "⇒ tmp 是实验区不是落点（清 tmp 会让闸门静默落到兜底词表）"
                                % (name, field, p))
    reg_hits = []
    for reg in REGISTRIES:
        if not os.path.isfile(reg):
            warns.append("[P5] registry 不在盘上，未能校：%s" % reg)
            continue
        base = os.path.basename(reg)
        try:
            doc = json.loads(rd(reg))
        except Exception as e:
            # 解析不了 ⇒ **退回逐行扫**，并大声说出来。绝不能因为解析失败就当"没问题"
            # （假阴比假阳坏）。逐行扫会连散文里提到的路径一起报，宁可假阳。
            warns.append("[P5] `%s` json 解析失败（%s）⇒ 退回逐行扫，**可能误报散文里提到的路径**"
                         % (base, e))
            for i, line in enumerate(rd(reg).splitlines(), 1):
                for m in re.finditer(r"[A-Za-z]:[\\/][^\"]*?[\\/]tmp[\\/][^\"]*", line):
                    reg_hits.append("%s:%d" % (base, i))
                    errs.append("[P5] `%s:%d` 仍指向 tmp 下：%s"
                                % (base, i, m.group(0)[:120]))
            continue
        # 结构化扫：只认**整个字符串就是一个 tmp 路径**的值。
        # 为什么不逐行扫：2026-10-19 第一版逐行扫，把 thresholds_registry 里一条
        # 解释性 note（内容正好写着"原指 D:/AIWorkflow/tmp/wzy/qc.py"）也当成违规报了，
        # expect_count 2 变 3 当场露馅。一把分不清「指针」和「谈论指针的句子」的尺子不好用。
        for ptr, v in _walk_strings(doc):
            if not isinstance(v, str):
                continue
            s = v.strip()
            if not re.match(r"^[A-Za-z]:[\\/]\S+$", s):
                continue
            if is_tmp(s):
                reg_hits.append("%s → %s" % (base, ptr))
                errs.append("[P5] `%s → %s` 仍指向 tmp 下：%s" % (base, ptr, s[:120]))
    # 附加扫描：清单**其它字段**（说明／处置／⚠仍未解决…）里提到的 tmp 路径。
    # 这些不是"真源住在 tmp"，是"某处仍依赖 tmp 里的数据"⇒ 报 warn 不报 error。
    # 为什么非扫不可：不扫的话，把违规从 runtime_loaded_from 挪进说明字段就能让 [P5] 转绿——
    # 那等于给尺子留了一个自己把自己关掉的开关。
    other = set()
    skip_fields = ("declared", "runtime_loaded_from", "原处桩")
    for name, e in sorted(ts.items()):
        if not isinstance(e, dict):
            continue
        for k, v in e.items():
            if k in skip_fields or not isinstance(v, str):
                continue
            if any(is_tmp(p) for p in extract_paths(v)):
                other.add("truth_sources[%s].%s" % (name, k))
    for sect in ("frozen", "known_broken", "deprecated"):
        items = d.get(sect)
        pairs = list(items.items()) if isinstance(items, dict) else list(enumerate(items or []))
        for i, item in pairs:
            if not isinstance(item, dict):
                continue
            for kk, vv in item.items():
                if isinstance(vv, str) and any(is_tmp(p) for p in extract_paths(vv)):
                    other.add("%s[%s].%s" % (sect, i, kk))
    for o in sorted(other):
        warns.append("[P5] 清单 `%s` 字段里提到 tmp 路径 ⇒ 不是真源落点，但**仍有依赖**，"
                     "别以为 [P5] 绿了就与 tmp 无关" % o)
    data["tmp_hits"] = hits + reg_hits
    data["tmp_mentions_other_fields"] = sorted(other)
    if not hits and not reg_hits:
        infos.append("[P5] 三个 registry 与官方路径.json 的真源字段中均无 tmp/ 落点 ✔")


# ------------------------------------------------------- [P6] 汇总 check_registry
def p6_aggregate(errs, warns, infos, data):
    if not os.path.isfile(CHECK_REGISTRY):
        warns.append("[P6] check_registry.py 不在盘上 ⇒ 本项未跑（不是通过）：%s" % CHECK_REGISTRY)
        data["check_registry"] = {"ran": False}
        return
    try:
        r = subprocess.run([sys.executable, CHECK_REGISTRY, "--print-json"],
                           capture_output=True, timeout=120,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = (r.stdout or b"").decode("utf-8", "replace")
        j = json.loads(out)
    except Exception as e:
        warns.append("[P6] check_registry.py 跑不起来或输出不可解析 ⇒ 本项未跑（不是通过）：%s" % e)
        data["check_registry"] = {"ran": False, "why": str(e)}
        return
    ne, nw = len(j.get("errors") or []), len(j.get("warns") or [])
    data["check_registry"] = {"ran": True, "errors": ne, "warns": nw}
    for e in (j.get("errors") or []):
        errs.append("[P6] check_registry: %s" % e)
    infos.append("[P6] check_registry.py ⇒ error %d／warn %d" % (ne, nw))
    if ne == 0 and nw:
        warns.append("[P6] check_registry.py 有 %d 条 warn（明细见它自己的输出）" % nw)


# ------------------------------------------------- [P7] AGENTS.md 快照对账
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")
_SNAP_RE = re.compile(r"<!--\s*SNAPSHOT:(\w+)\s+BEGIN.*?-->(.*?)<!--\s*SNAPSHOT:\1\s+END\s*-->",
                      re.S)


def _snapshots(text):
    return {k: v for k, v in _SNAP_RE.findall(text)}


def p7_agents_snapshot(d, errs, warns, infos, data):
    """AGENTS.md 是 agent 自动加载的那一份，所以它**必须**内联最要命的两段（入口 + 禁令），
    否则不点链接的 agent 什么都看不到。内联就意味着有第二份抄本，抄本就会漂。
    解法不是"别抄"，是**抄了但机器对账**：两段都用 SNAPSHOT 标记包起来，逐字比 json。
    """
    n_err_before = len(errs)          # 本项自己的错误数要单独算：errs 是全节共享的累加器，
                                      # 用 `not errs` 判会被前面几节的红淹掉（假绿）。
    if not os.path.isfile(AGENTS_MD):
        errs.append("[P7] %s 不在盘上 ⇒ agent 自动加载的契约壳没了" % AGENTS_MD)
        data["agents_snapshot"] = {"ran": False}
        return
    txt = rd(AGENTS_MD)
    snaps = _snapshots(txt)
    data["agents_snapshot"] = {"ran": True, "blocks": sorted(snaps)}
    for need in ("entries", "forbidden"):
        if need not in snaps:
            errs.append("[P7] AGENTS.md 缺 `SNAPSHOT:%s` 标记块 ⇒ 要么壳被删了，"
                        "要么标记被改坏了（对账失效＝抄本随便漂）" % need)
    if "官方路径.json" not in txt:
        errs.append("[P7] AGENTS.md 里没有指向 官方路径.json 的指针 ⇒ 薄壳失去了唯一真源入口")

    # 正向：json 里的每条都必须在快照里逐字出现
    ents = {k: v for k, v in d["entries"].items() if k != "_note"}
    eb = snaps.get("entries", "")
    n_e = 0
    for name, e in sorted(ents.items()):
        if not isinstance(e, dict):
            continue
        for field in ("命令", "入口"):
            s = e.get(field)
            if isinstance(s, str) and s.strip():
                n_e += 1
                if s in eb:
                    infos.append("[P7] 入口 `%s` 的『%s』在 AGENTS.md 快照中逐字命中" % (name, field))
                else:
                    errs.append("[P7] 入口 `%s` 的『%s』在 AGENTS.md 快照中**找不到逐字副本** "
                                "⇒ 抄本已漂（agent 读到的命令与真源不同）：%s" % (name, field, s[:90]))
    data["agents_snapshot"]["entries_checked"] = n_e

    fb = snaps.get("forbidden", "")
    want = [str(x) for x in (d.get("forbidden") or [])]
    got = [m.group(1).strip() for m in re.finditer(r"(?m)^\s*\d+\.\s*(.+?)\s*$", fb)]
    data["agents_snapshot"]["forbidden_json"] = len(want)
    data["agents_snapshot"]["forbidden_md"] = len(got)
    for s in want:
        if s not in fb:
            errs.append("[P7] 禁令在 AGENTS.md 快照中找不到逐字副本 ⇒ 抄本已漂：%s" % s[:90])
    # 反向：快照里多出来的条目 ＝ 只手改了 md 没改 json
    for g in got:
        if g not in want:
            errs.append("[P7] AGENTS.md 快照里有 json 没有的禁令 ⇒ **只手改了 md**，"
                        "真源没跟上（这正是在制造第二份漂移真源）：%s" % g[:90])
    n_p7_err = len(errs) - n_err_before
    if len(want) != len(got):
        errs.append("[P7] 禁令条数不等：json %d 条 ／ AGENTS.md 快照 %d 条" % (len(want), len(got)))
        n_p7_err += 1
    elif want and n_p7_err == 0:
        infos.append("[P7] 禁令 %d 条双向逐字一致 ✔" % len(want))
    data["agents_snapshot"]["errors"] = n_p7_err


# ------------------------------------------------------- [P8] 声明牌在不在
PLATE_NAME = "_官方路径声明.md"


def p8_plates(d, errs, warns, infos, data):
    """声明牌存在性。牌子是"一 cd 进来就知道该走哪"的那一层，
    但它自己是文件 ⇒ 会被误删、会被清理脚本扫走、会被 git clean 吃掉。
    没人校的告示牌等于没有告示牌。名单登记在 json 的 plates.dirs（不在本脚本里抄一份）。
    """
    pl = d.get("plates") or {}
    dirs = pl.get("dirs") or []
    data["plates"] = {"declared": len(dirs)}
    if not dirs:
        warns.append("[P8] json 里没有 plates.dirs ⇒ 本项没跑（不是通过）。"
                     "声明牌这一层没有机器校验。")
        return
    gen = pl.get("generator")
    if gen and not os.path.isfile(norm(gen)):
        errs.append("[P8] 声明牌生成器不在盘上：%s ⇒ 牌子被删了也没法按同一格式重铺" % gen)
    ok = gone = nodir = 0
    for p in dirs:
        np = norm(p)
        if not os.path.isdir(np):
            nodir += 1
            warns.append("[P8] 声明牌登记的目录不在盘上（目录本身没了，不是牌子没了）：%s" % p)
            continue
        f = os.path.join(np, PLATE_NAME)
        if os.path.isfile(f):
            ok += 1
            infos.append("[P8] 牌子在：%s" % f)
            # 牌子存在不等于牌子能读：生成器里有几十条夹着 Windows 路径的中文字符串，
            # 哪条忘了加 r"" 就会被 `\b`/`\f` **吃掉下一个字母**（2026-10-19 端到端验证
            # 实测：tmp\wzy 那张牌上是 `toolsan_words.py` 与 `ace_anchors`，都读不出问题）。
            try:
                body = io.open(f, encoding="utf-8-sig", errors="replace").read()
                ctrl = sorted({hex(ord(c)) for c in body
                               if ord(c) < 32 and c not in "\n\r\t"})
                if ctrl:
                    errs.append("[P8] **牌文里有控制字符** %s：%s ⇒ 生成器某条字符串漏了 r\"\"，"
                                "牌上的路径/文件名已被吃掉字母，读的人照着做会撞空 "
                                "（重铺前先修 %s）" % (",".join(ctrl), f, gen or "<生成器未登记>"))
            except Exception as e:
                warns.append("[P8] 牌子读不出来：%s（%s）" % (f, e))
        else:
            gone += 1
            errs.append("[P8] **声明牌缺失**：%s ⇒ 这个目录现在是"
                        "『agent 一进来什么提示都没有』的状态（重铺：py %s）"
                        % (f, gen or "<生成器未登记>"))
    data["plates"].update({"ok": ok, "missing": gone, "dir_gone": nodir})



# ------------------------------- [P11] 画布夹的 6 份 API 副本不许与 engine 版漂
CANVAS_API_DIR = os.path.join("ComfyUI_H3", "ComfyUI", "user", "default",
                              "workflows", "娱乐流", "API格式_非画布_先看这个说明")
CANVAS_API_PAIRS = ("h3_i2v_fl2va_api.json", "h3_i2v_fl2va_dual_api.json",
                    "h3_i2v_fl2va_dual_lora.json", "h3_i2v_fl2va_dual_nolora_api.json",
                    "h3_i2v_fl2va_nolora_api.json", "h3_i2v_ref2va_api.json")


def _md5_file(p):
    try:
        return hashlib.md5(io.open(p, "rb").read()).hexdigest()[:8]
    except Exception:
        return None


def p11_canvas_api_copies(errs, warns, infos, data):
    """画布夹那 6 份是 engine 模板的**排障副本**（README 写明），不归档但必须逐字节相等。

    为什么是 error 不是 warn：两边不一致时**没人会知道**——出片走 engine 版，
    而人打开画布看到的是另一份，于是"照画布理解引擎"会理解错。
    这正是本项目反复强调的那类"静默失败"，所以直接拦。
    """
    data["canvas_api_copies"] = {"checked": 0, "same": 0, "drifted": [], "missing": []}
    cdir = os.path.join(ROOT, CANVAS_API_DIR)
    edir = os.path.join(ROOT, "engine", "comfy")
    if not os.path.isdir(cdir):
        errs.append("[P11] 画布副本目录不在盘上：%s ⇒ 要么被移走（那 engine 版就是唯一真源，"
                    "本项应改为不再需要），要么路径漂了。先查清再删这条检查。"
                    % CANVAS_API_DIR)
        return
    for name in CANVAS_API_PAIRS:
        a = os.path.join(cdir, name)
        b = os.path.join(edir, name)
        ma, mb = _md5_file(a), _md5_file(b)
        if ma is None or mb is None:
            data["canvas_api_copies"]["missing"].append(name)
            errs.append("[P11] 副本对不上（有一边不在）：%s 画布侧=%s engine 侧=%s"
                        % (name, "在" if ma else "缺", "在" if mb else "缺"))
            continue
        data["canvas_api_copies"]["checked"] += 1
        if ma == mb:
            data["canvas_api_copies"]["same"] += 1
            infos.append("[P11] 逐字节相等：%s（%s）" % (name, ma))
        else:
            data["canvas_api_copies"]["drifted"].append(name)
            errs.append("[P11] 🔴 **副本已漂**：%s 画布侧 md5=%s ≠ engine 侧 md5=%s ⇒ "
                        "出片走的是 engine 版，画布那份现在会误导人。要么把画布侧重新拷成 engine 版，"
                        "要么删掉画布侧并改 README 指向 engine 版。" % (name, ma, mb))

# ------------------------------------------- [P9] ban_words 与 prompt_lint 不许漂
def p9_ban_words_no_drift(errs, warns, infos, data):
    """`tools/ban_words.py` 是 `prompt_lint.NEG` 的纯数据副本（为断开 tmp 依赖而建）。
    副本就有漂移风险，而这张表是 G7 认「禁令句」的判据 ⇒ 漂了不报错，只会让闸悄悄变松或变紧。
    prompt_lint.py 里那句「本表升为唯一词源」现在由**这条**守着，不由记性守着。

    ⚠ 加载 prompt_lint 会 `os.chdir('D:/AIWorkflow/tmp/wzy')`（它自己 :19 干的，实测）
      ⇒ 比对在**子进程**里做，别污染 check_official_path 自己的 CWD。
    """
    bw = os.path.join(ROOT, "tools", "ban_words.py")
    pl = os.path.join(ROOT, "tmp", "wzy", "prompt_lint.py")
    data["ban_words"] = {"ran": False}
    if not os.path.isfile(bw):
        warns.append("[P9] tools/ban_words.py 不在盘上 ⇒ check_preflight 会退回 import prompt_lint，"
                     "那条路仍会 chdir 到 tmp/wzy。本项未跑（不是通过）")
        return
    if not os.path.isfile(pl):
        warns.append("[P9] tmp/wzy/prompt_lint.py 不在盘上 ⇒ 无法对账。"
                     "**这不代表没问题**：ban_words 从此没有对照物，改词表没人拦。"
                     "（tmp/wzy 归档后本项应改成与归档副本对账，别直接把这条检查删掉）")
        return
    probe = "\n".join([
        "import importlib.util, json, os, sys",
        "def L(p, n):",
        "    s = importlib.util.spec_from_file_location(n, p)",
        "    m = importlib.util.module_from_spec(s)",
        "    s.loader.exec_module(m)",
        "    return m",
        "out = {}",
        "try:",
        "    out['bw'] = list(L(sys.argv[1], 'bw').NEG)",
        "except Exception as e:",
        "    out['bw_err'] = repr(e)",
        "cwd0 = os.getcwd()",
        "try:",
        "    out['pl'] = list(L(sys.argv[2], 'pl').NEG)",
        "except Exception as e:",
        "    out['pl_err'] = repr(e)",
        "out['chdir'] = os.getcwd() != cwd0",
        "sys.stdout.write(json.dumps(out, ensure_ascii=False))",
    ])
    try:
        r = subprocess.run([sys.executable, "-c", probe, bw, pl], capture_output=True, timeout=60,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        j = json.loads((r.stdout or b"").decode("utf-8", "replace"))
    except Exception as e:
        warns.append("[P9] 对账探针跑不起来 ⇒ 本项未跑（不是通过）：%s" % e)
        return
    data["ban_words"] = {"ran": True, "bw": len(j.get("bw") or []), "pl": len(j.get("pl") or []),
                         "pl_chdirs": j.get("chdir")}
    for k, lbl in (("bw_err", "ban_words"), ("pl_err", "prompt_lint")):
        if j.get(k):
            errs.append("[P9] 加载 %s 失败：%s ⇒ 对账没跑成，不是通过" % (lbl, j[k]))
    if j.get("bw_err") or j.get("pl_err"):
        return
    a, b = j["bw"], j["pl"]
    if a == b:
        infos.append("[P9] ban_words.NEG 与 prompt_lint.NEG **逐字同序** ✔（%d 条）" % len(a))
    elif set(a) == set(b):
        warns.append("[P9] 两边集合相同但**顺序不同**（%d 条）。今天无害——消费点 "
                     "check_preflight.py:572 是 any(b in seg ...) 纯成员判定；"
                     "但顺序差说明有人只改了一边，请对齐" % len(a))
    else:
        errs.append("[P9] 否定词表**已漂**：ban_words %d 条 ／ prompt_lint %d 条；"
                    "只在 ban_words：%s；只在 prompt_lint：%s "
                    "⇒ G7 认禁令句的判据与词表闸不一致（正是 09-28 那条漂移的病）。"
                    "改词表必须两边一起改。"
                    % (len(a), len(b), [x for x in a if x not in b], [x for x in b if x not in a]))
    if j.get("chdir"):
        infos.append("[P9] 已确认 prompt_lint 导入会 chdir（探针在子进程里跑，未污染本进程 CWD）")


# ------------------------------------- 已登记例外（带到期日，过期自动升回 error）
def apply_accepted_red(d, errs, warns, infos, data):
    """把「已知、已登记、有理由、有到期日」的 error 降成 warn。

    为什么需要它：一把**恒红**的尺子等于没有尺子——人看到红就跳过，真出问题时也一起被跳过。
    但降级必须有代价，否则例外区会变成垃圾场。所以四重约束：
      ① 每条必须写 `reason`（为什么可以暂时红着）；缺 reason ⇒ 不予降级。
      ② 必须写 `review_by`；过期 ⇒ 自动升回 error，并加一条"例外已过期"。
      ③ `expect_count` 与实际命中数不符 ⇒ 报 error（修好了该删登记、又长新的该重新裁）。
      ④ 一条都没命中的例外 ⇒ warn「登记已失效」，防止僵尸条目永久豁免将来的同类问题。
    """
    ar = (d.get("accepted_red") or {}).get("items") or []
    data["accepted_red"] = {"declared": len(ar)}
    if not ar:
        return
    import datetime
    today = datetime.date.today().isoformat()
    kept, downgraded, expired, used = [], [], [], set()
    for e in errs:
        m = re.match(r"\[(P\d+)", e)
        tag = m.group(1) if m else None
        hit = None
        for i, it in enumerate(ar):
            if not isinstance(it, dict):
                continue
            if it.get("check") and it.get("check") != tag:
                continue
            if str(it.get("match", "")) and str(it["match"]) in e:
                hit = (i, it)
                break
        if not hit:
            kept.append(e)
            continue
        i, it = hit
        used.add(i)
        rb = str(it.get("review_by", ""))
        why = str(it.get("reason", ""))
        if not why:
            kept.append(e)
            kept.append("[例外] accepted_red[%d] 没有 reason ⇒ 不合格，不予降级" % i)
            continue
        if not rb:
            kept.append(e)
            kept.append("[例外] accepted_red[%d] 没有 review_by ⇒ 无到期日的例外＝永久豁免，不合格" % i)
            continue
        if rb < today:
            kept.append(e)
            expired.append(i)
            warns.append("[例外] accepted_red[%d] 的 review_by=%s **已过期**（今天 %s）⇒ 该重新面对了。理由：%s"
                         % (i, rb, today, why))
            continue
        downgraded.append((e, i))
        warns.append("[已登记例外→%s] %s\n        理由：%s" % (rb, e, why))
    for i, it in enumerate(ar):
        if not isinstance(it, dict):
            continue
        n = sum(1 for _, idx in downgraded if idx == i)
        exp = it.get("expect_count")
        if exp is not None and n != int(exp):
            kept.append("[例外] accepted_red[%d]（match=%r）登记 expect_count=%s 但实际命中 %d 条 ⇒ "
                        "修好了就该把这条登记删掉、又长新的就该重新裁，别让它挂着"
                        % (i, it.get("match"), exp, n))
        if i not in used:
            warns.append("[例外] accepted_red[%d] 一条都没命中（match=%r）⇒ 登记已失效，请删掉，"
                         "否则它会永久豁免将来同类的问题" % (i, it.get("match")))
    data["accepted_red"].update({"downgraded": len(downgraded), "expired": len(expired),
                                 "kept_errors": len(kept)})
    errs[:] = kept


def p10_genres_registry(errs, warns, infos, data):
    """`engine/genres_registry.json` 的自洽校验（治理批新功能①）。

    校四件事：
      ① 每个 `values_live_in` / `规则真源` / `维护脚本` 指的文件**在盘上**（登记了一个不存在的
         落点，比不登记更坏——调用方会照着去找，找不到就自己猜）。
      ② `projects` 的键集合与 `engine/projects_registry.json` 的 `projects[].id` **逐字相等**。
         那份表是项目声明的唯一真源，这边多一个少一个都是漂。
      ③ `prompt_vocab.已有档位` 与 `tools/prompt_lint.py` 里 `RENDER_TOXIC_BY_PROFILE`
         的**实际键**相等（实读源码，不信登记）。
      ④ 🔴 **不许抄值**：本表纪律是"只管键与元数据"，所以任何看起来像标定值的数字字段
         （value / fail_hi / warn_lo / 阈值 …）都不该出现。这条纪律如果没人守，
         它就会变成第 N 份会漂的抄本——`thresholds_registry.json` 当年就是这么红的。
    """
    GEN = os.path.join(ROOT, "engine", "genres_registry.json")
    data["genres_registry"] = {"ran": False}
    if not os.path.isfile(GEN):
        warns.append("[P10] engine/genres_registry.json 不在盘上 ⇒ 题材分层这件事没有登记处，"
                     "本项未跑（不是通过）。换题材时无法判断哪些判据可复用、哪些必须重标。")
        return
    try:
        g = json.loads(rd(GEN))
    except Exception as e:
        errs.append("[P10] genres_registry.json 解析失败：%s" % e)
        return
    data["genres_registry"] = {"ran": True, "genres": len(g.get("genres") or {}) - (1 if "_note" in (g.get("genres") or {}) else 0),
                               "projects": len(g.get("projects") or {}) - (1 if "_note" in (g.get("projects") or {}) else 0)}

    # ① 落点存在性
    # ⚠ 用 extract_paths()（能从"路径＋中文说明"里把路径刮出来），不用 [P5] 那套
    #   "整串必须就是一个路径"的严判。第一版用了严判，结果 values_live_in 的值是
    #   `D:/.../prompt_lint.py 的 RENDER_TOXIC_BY_PROFILE（字典…）` 这种带说明的串 ⇒
    #   **一个都没匹配上，却打印出「落点 0 个全在 ✔」**。校到 0 个而报通过＝假阴，
    #   比不校更坏（它会让人以为落点都验过了）。
    n_path = n_miss = 0
    for ptr, v in _walk_strings(g):
        if not isinstance(v, str):
            continue
        # 只校**该装路径的字段**，跳过 `_` 前缀的说明字段（_readme / _note）。
        # 第一版全字段扫，结果 projects._note 里那句「资源池(E:/图像影音资源池)下的目录名」
        # 被当成路径报了 2 条假阳——ASCII `)` 不在 extract_paths 的终止符集里。
        # 修法不是往终止符里加 `)`（会误伤真含右括号的 Windows 路径），是**别去扫散文**。
        leaf = ptr.rsplit(".", 1)[-1].split("[")[0]
        if leaf.startswith("_") or "._note" in ptr or "._readme" in ptr:
            continue
        for s in extract_paths(v):
            loc = s
            if re.search(r"[:：]", loc.split("/", 3)[-1]):   # 剥掉 §四-补二十二 这类定位后缀
                loc = re.split(r"[:：]", loc)[0]
            n_path += 1
            if not os.path.exists(norm(loc)):
                n_miss += 1
                errs.append("[P10] genres_registry `%s` 指的落点不在盘上：%s ⇒ 登记了一个不存在的地址，"
                            "调用方照着找会找不到然后自己猜" % (ptr, loc))
    data["genres_registry"]["paths_checked"] = n_path
    if n_path == 0:
        errs.append("[P10] genres_registry 里**一个落点路径都没刮出来** ⇒ 本项①等于没跑，"
                    "不是通过（解析器失效或表里根本没写绝对路径）")
    elif not n_miss:
        infos.append("[P10] genres_registry 的 %d 个落点全部在盘上 ✔" % n_path)

    # ② 项目键集合对账
    PR = os.path.join(ROOT, "engine", "projects_registry.json")
    if os.path.isfile(PR):
        try:
            pr = json.loads(rd(PR))
            want = {p["id"] for p in (pr.get("projects") or []) if isinstance(p, dict) and p.get("id")}
            got = {k for k in (g.get("projects") or {}) if k != "_note"}
            data["genres_registry"]["projects_match"] = (want == got)
            if want == got:
                infos.append("[P10] 项目键与 projects_registry **逐字相等** ✔（%d 个）" % len(want))
            else:
                for x in sorted(want - got):
                    errs.append("[P10] projects_registry 有、genres_registry 没有的项目：`%s` "
                                "⇒ 这个项目的题材标定状态无处登记" % x)
                for x in sorted(got - want):
                    errs.append("[P10] genres_registry 有、projects_registry 没有的项目：`%s` "
                                "⇒ 又长出一份项目清单抄本（projects_registry 才是唯一声明源）" % x)
        except Exception as e:
            warns.append("[P10] projects_registry 读不了 ⇒ 项目键对账未跑（不是通过）：%s" % e)
    else:
        warns.append("[P10] projects_registry.json 不在盘上 ⇒ 项目键对账未跑（不是通过）")

    # ③ 画风档实读对账
    dims = g.get("dimensions") or {}
    pv = dims.get("prompt_vocab") or {}
    declared = set(pv.get("已有档位") or [])
    pl = os.path.join(ROOT, "tools", "prompt_lint.py")
    if declared and os.path.isfile(pl):
        t = rd(pl)
        m = re.search(r"RENDER_TOXIC_BY_PROFILE\s*=\s*\{", t)
        real = set()
        if m:
            # 只取该字典**顶层**的键：形如 `'guoman_3d': [`。
            # 不做花括号配平（那是 node_class_collision_audit.py 的活），因为这里的值全是
            # 一维字符串列表，`键: [` 这个形状在顶层唯一；嵌套里不会再出现同样形状。
            seg = t[m.end():]
            stop = re.search(r"\n\}", seg)
            if stop:
                seg = seg[:stop.start()]
            real = set(re.findall(r"['\"]([A-Za-z_][\w]*)['\"]\s*:\s*\[", seg))
        data["genres_registry"]["profiles"] = {"declared": sorted(declared), "real": sorted(real)}
        if declared == real:
            infos.append("[P10] 画风档与 prompt_lint 实际键相等 ✔（%s）" % "、".join(sorted(real)))
        else:
            for x in sorted(declared - real):
                errs.append("[P10] genres_registry 登记了画风档 `%s`，但 prompt_lint 的 "
                            "RENDER_TOXIC_BY_PROFILE 里**没有** ⇒ 用这个档会命中 :289 那条"
                            "「没有毒词表 ⇒ 会拿别的档的表来判它」" % x)
            for x in sorted(real - declared):
                errs.append("[P10] prompt_lint 里有画风档 `%s`，genres_registry **没登记** "
                            "⇒ 登记漏了，换题材的人不知道有这一档" % x)
    elif declared:
        warns.append("[P10] tools/prompt_lint.py 不在盘上 ⇒ 画风档对账未跑（不是通过）")

    # ④ 不许抄值
    BAD_KEYS = ("value", "fail_hi", "fail_lo", "warn_hi", "warn_lo", "threshold", "阈值", "标定值")
    copied = []
    for ptr, v in _walk_numbers(g):
        leaf = ptr.rsplit(".", 1)[-1].split("[")[0]
        if leaf in BAD_KEYS:
            errs.append("[P10] genres_registry `%s` = %s ⇒ **抄了标定值**。本表纪律是只管键与元数据，"
                        "值要住在 values_live_in 指的那个文件里；抄进来就是第二个会漂的真源"
                        "（thresholds_registry 当年带 value 字段就是这么红过 3 条测试的）" % (ptr, v))
            copied.append(ptr)
    data["genres_registry"]["copied_values"] = copied
    if not copied:
        infos.append("[P10] 无任何标定值被抄进本表 ✔（不抄值纪律成立）")


def main():
    _try_utf8(sys.stdout)
    ap = argparse.ArgumentParser(description="官方路径.json 声明壳自校验（默认只报不拦）")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--strict", action="store_true",
                    help="有 error 级问题时返回 1（默认恒 0＝只报不拦，与三件套同风格）")
    ap.add_argument("--run-stubs", action="store_true",
                    help="真去执行路障桩并验退出码 78（默认只做静态签名判定，避免检查器产生副作用）")
    ap.add_argument("--json", metavar="PATH", help="额外把结果写成 json（默认不落盘）")
    ap.add_argument("--print-json", action="store_true", help="只把结构化结果打到 stdout")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    d, why = load_manifest(a.manifest)
    if not a.print_json:
        print("=" * 72)
        print("check_official_path.py · 声明壳自校验（只读）")
        print("清单：%s" % a.manifest)
        print("=" * 72)
    if d is None:
        # 读不到清单时 --print-json 也要给**结构**，否则调用方拿到空 stdout 会当成"没问题"。
        if a.print_json:
            json.dump({"errors": ["官方路径.json 读不到：%s ⇒ 十一项一项都没跑" % why],
                       "warns": [], "data": {"probe_ran": False}},
                      sys.stdout, ensure_ascii=False, indent=1)
            sys.stdout.write("\n")
            return 1 if a.strict else 0
        print("!! 官方路径.json 读不到：%s ⇒ **十一项校验一项都没跑，这不是通过**" % why)
        return 1 if a.strict else 0

    errs, warns, infos, data = [], [], [], {"manifest": a.manifest}
    p1_entries(d, errs, warns, infos, data)
    p2_truth_sources(d, errs, warns, infos, data)
    p3_deprecated(d, errs, warns, infos, data, run_stubs=a.run_stubs)
    p4_orphans(d, errs, warns, infos, data)
    p5_no_tmp(d, errs, warns, infos, data)
    p6_aggregate(errs, warns, infos, data)
    p7_agents_snapshot(d, errs, warns, infos, data)
    p8_plates(d, errs, warns, infos, data)
    p9_ban_words_no_drift(errs, warns, infos, data)
    p10_genres_registry(errs, warns, infos, data)
    p11_canvas_api_copies(errs, warns, infos, data)
    n_err_raw = len(errs)
    # 例外降级放在**最后**：它要看到全部 error 才能正确计数（expect_count 靠命中数对账）。
    apply_accepted_red(d, errs, warns, infos, data)
    data["error_count_raw"] = n_err_raw
    data["error_count"] = len(errs)
    data["warn_count"] = len(warns)

    if a.print_json:
        json.dump({"errors": errs, "warns": warns, "data": data},
                  sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 1 if (a.strict and errs) else 0

    if a.verbose:
        for m in infos:
            print("   · %s" % m)
    for m in warns:
        print("  ⚠ %s" % m)
    for m in errs:
        print("  !! %s" % m)
    print("-" * 72)
    st = data.get("truth_sources_stat", {})
    dp = data.get("deprecated_stat", {})
    os_ = data.get("orphan_scan", {})
    ar2 = data.get("archived_stat", {})
    print("真源 %d 条（命中 %d／缺件 %d／尺子够不着 %d）｜废弃 %d 项（原身在 %d／已立桩 %d／静默消失 %d）"
          "｜已归档 %d 项（确认离开原位 %d／又回来了 %d）"
          % (data.get("truth_sources_total", 0), st.get("ok", 0), st.get("missing", 0),
             st.get("no_path", 0), data.get("deprecated_total", 0),
             dp.get("live", 0), dp.get("stubbed", 0), dp.get("vanished", 0),
             ar2.get("declared", 0), ar2.get("gone", 0), ar2.get("back_in_place", 0)))
    pl = data.get("plates", {})
    ag = data.get("agents_snapshot", {})
    print("孤儿扫描：候选 %d／语料 %d ⇒ 孤儿候选 %d｜tmp 落点命中 %d"
          % (os_.get("candidates", 0), os_.get("corpus_files", 0), len(data.get("orphans", [])),
             len(data.get("tmp_hits", []))))
    print("AGENTS.md 快照：入口 %d 条／禁令 json %d ↔ md %d，本节 error %d｜声明牌 %d 处（在 %d／缺 %d／目录没了 %d）"
          % (ag.get("entries_checked", 0), ag.get("forbidden_json", 0), ag.get("forbidden_md", 0),
             ag.get("errors", 0), pl.get("declared", 0), pl.get("ok", 0),
             pl.get("missing", 0), pl.get("dir_gone", 0)))
    ar = data.get("accepted_red", {})
    bw = data.get("ban_words", {})
    print("词表对账[P9]：ban_words %s 条 ↔ prompt_lint %s 条（prompt_lint 会 chdir：%s）"
          % (bw.get("bw", "-"), bw.get("pl", "-"), bw.get("pl_chdirs", "未跑")))
    gr = data.get("genres_registry", {})
    if gr.get("ran"):
        print("题材分层[P10]：题材档 %s／项目 %s（与 projects_registry 逐字相等：%s）｜落点刮出 %s 个%s｜画风档对账：%s｜抄值 %s 处"
              % (gr.get("genres"), gr.get("projects"), gr.get("projects_match"),
                 gr.get("paths_checked"),
                 "（🔴 0 个＝没校到，不是通过）" if not gr.get("paths_checked") else " 全在",
                 "相等" if gr.get("profiles", {}).get("declared") == gr.get("profiles", {}).get("real") else "🔴不等",
                 len(gr.get("copied_values") or [])))
    else:
        print("题材分层[P10]：未跑（genres_registry.json 不在盘上）")
    print("合计：error %d（降级前 %d）｜warn %d｜已登记例外 %d 条（降级 %d／过期 %d）"
          % (len(errs), data.get("error_count_raw", len(errs)), len(warns),
             ar.get("declared", 0), ar.get("downgraded", 0), ar.get("expired", 0)))
    if a.json:
        json.dump({"manifest": a.manifest, "errors": errs, "warns": warns,
                   "infos": infos, "data": data},
                  io.open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写出：%s" % a.json)
    if a.strict and errs:
        print("!! --strict：有 error ⇒ 退出码 1")
        return 1
    if errs:
        print("本脚本只报不拦：退出码 0（要看拦截效果加 --strict）")
    else:
        print("十一项全过：退出码 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
