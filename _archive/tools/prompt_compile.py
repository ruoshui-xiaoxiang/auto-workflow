#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""prompt_compile.py · W2 英文编译的**离线纯函数**与提交前校验器

背景（计划 §3-W2 / 04 记录第 5 条）：
  · 所有模式（T2VA/I2VA/FL2VA/L2VA/Ref2VA）必须先产出**独立英文稿**；
  · 原稿按字节保存、哈希不变；编译稿落批次目录并由下游引用；**禁止回写原稿**；
  · 编译失败（截断、缺字段、漏台词、超长）必须停在提交前，不许静默缩写。

分工（重要）：
  · 本文件的 `compile_prompt()` 是**纯函数**：调用方注入 `translator(source, system) -> str`。
    真正调云端 LLM 的那半在引擎 `tasks.t_llm`（YAML 的 translate 步），本文件不联网、不读 key。
    ⇒ 离线测试用假 translator 就能覆盖"编译 + 校验"全链；联网部分只是换一个注入实现。
  · `snapshot` / `verify` 是落盘与证据：snapshot 在翻译前把原稿按字节复制并记 sha256；
    verify 在提交前重算原稿哈希、比对台词、复核官方格式/语言/长度。任一失败退出码 1。

用法（引擎 YAML 里由 shell 步调用；也可手工跑）：
  py prompt_compile.py snapshot --source 原稿.txt --out-dir 批次/prompt_compile --run-id 20261023_...
  py prompt_compile.py verify   --source 原稿.txt --state-dir 批次/prompt_compile \
                                --run-id 20261023_... --compiled 批次/prompt_compile/compiled_....txt
  py prompt_compile.py check    --source 原稿.txt --compiled 英文稿.txt [--mode i2va]
"""
from __future__ import print_function

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import h3_official_spec as SPEC          # noqa: E402
import prompt_format as PF              # noqa: E402

# 编译步 `max_tokens`（engine/workflows/*.yaml 里 translate 步的预算）＝1500。
# 英文按 ~4 字符/token 粗估；超过就必须停，不许靠截断混过去。
DEFAULT_MAX_TOKENS = 1500
MAX_COMPILED_CHARS = 8000
# 源稿正文含中文而编译稿短于这个比例 ⇒ 视为"静默缩写"（中文→英文通常不缩水）。
MIN_EN_RATIO = 0.5
D_TAG_RE = SPEC.D_TAG
CJK_ANY = re.compile(u"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
BLOCK_CN_RE = re.compile(u"【([^】]{1,12})】")

COMPILE_SYSTEM = (
    "你是 MiniMax H3 官方提示词的英文编译器。输入是一份完整提示词，输出**同一份提示词的英文版**。"
    "硬性规则：\n"
    "1) 首行/图对齐行（如果有）逐字保留，不得改写、不得换序。\n"
    "2) 保留所有官方字段名与出现次数（基础三字段 integrated_multimodal_description / "
    "overall_soundscape / non_diegetic_music；Ref2VA 六段 subject_definitions / summary / "
    "retention_analysis / detailed_description / overall_soundscape / non_diegetic_music），"
    "字段顺序不变，每段只出现一次。\n"
    "3) 只把重写段落翻译成英文；`<d>…</d>` 内台词/歌词**逐字保留原语言**；"
    "英文双引号内画面可见文字也保留原文。\n"
    "4) 不得缩写、合并、删减信息，不得省略任何一段；输出必须完整到最后一个字段。\n"
    "5) 不要 markdown 代码块、不要解释、不要前后缀；只输出编译后的完整提示词。"
)


class CompileResult(object):
    def __init__(self, text, backend, issues=None):
        self.text = text
        self.backend = backend
        self.issues = issues or []      # [(code, msg)]

    @property
    def ok(self):
        return not self.issues


# ---------------------------------------------------------------- 纯函数
def needs_compile(text):
    """正文（扣除 <d> 台词）是否含非英文——与 engine/tasks.t_llm 的 skip_if_no_cjk 同口径。"""
    body = re.sub(r"<d>.*?</d>", "", (text or "").strip(), flags=re.S)
    return bool(CJK_ANY.search(body))


def dialogues(text):
    """[(语言, 台词原文)]，按出现顺序；台词逐字比对用。"""
    return [(m.group(1), m.group(2).strip()) for m in D_TAG_RE.finditer(text or "")]


def _last_field_value(text):
    hits = list(re.finditer(r"(?m)^(non_diegetic_music:)\s*", text or ""))
    if not hits:
        return None
    return (text[hits[-1].end():] or "").strip()


def _looks_truncated(text):
    """结构性截断判据（宁可停，不静默放行）。返回问题清单。"""
    out = []
    t = (text or "").rstrip()
    if not t:
        return ["empty"]
    if t.count("<d>") != t.count("</d>"):
        out.append("unclosed_dialogue_tag")
    tail = _last_field_value(t)
    if tail is None:
        out.append("missing_last_field")
    elif not tail:
        out.append("empty_last_field")
    elif tail.upper() not in ("N/A", "NA"):
        # 完整英文段落应以句末标点/引号/闭括号收尾；以逗号/冒号/破折号/单词中间收尾都算截断。
        if tail[-1] not in ".!?\"'”’)]}":
            out.append("last_field_not_terminated")
    if re.search(r"[,:;，：；—-]\s*$", t):
        out.append("ends_with_dangling_punctuation")
    return out


def validate_compiled(source_text, compiled_text, mode=None, max_tokens=DEFAULT_MAX_TOKENS):
    """编译稿的提交前校验。返回 [(code, msg)]；空表＝可提交。

    覆盖：空稿/BOM/格式或模式变化/官方字段缺失重复乱序/中文残留/漏台词或改台词/
    截断/十块混入/超长/静默缩写。
    """
    issues = []
    src = source_text or ""
    out = compiled_text or ""
    if not out.strip():
        return [("empty", "编译稿为空")]
    if out.startswith(u"\ufeff"):
        issues.append(("bom", "编译稿带 UTF-8 BOM（官方样例无 BOM）"))

    src_fmt, out_fmt = SPEC.detect_format(src), SPEC.detect_format(out)
    src_mode, out_mode = SPEC.detect_mode(src), SPEC.detect_mode(out)
    if src_fmt and out_fmt != src_fmt:
        issues.append(("format_changed", "编译稿格式从 %s 变成 %s" % (src_fmt, out_fmt)))
    if mode:
        if out_mode != mode:
            issues.append(("mode_changed", "编译稿模式是 %s，期望 %s"
                           % (out_mode or "认不出", mode)))
    elif src_mode and out_mode != src_mode:
        issues.append(("mode_changed", "编译稿模式从 %s 变成 %s"
                       % (src_mode, out_mode or "认不出")))

    # 官方契约：首行、字段各一次、顺序、[Shot N]/切点、正文英文（F2）
    rp = SPEC.validate(out, mode=mode or out_mode)
    for r in rp.rows:
        if r["sev"] == "error":
            issues.append(("official_%s" % r["id"], r["msg"]))

    # 台词逐字（漏台词/改台词/多出台词）
    sd, od = dialogues(src), dialogues(out)
    if sd != od:
        if len(od) < len(sd):
            issues.append(("dialogue_missing", "源稿 %d 句台词，编译稿只有 %d 句"
                           % (len(sd), len(od))))
        elif len(od) > len(sd):
            issues.append(("dialogue_added", "源稿 %d 句台词，编译稿多出 %d 句"
                           % (len(sd), len(od))))
        for i, (a, b) in enumerate(zip(sd, od)):
            if a != b:
                issues.append(("dialogue_changed", "第 %d 句台词不是逐字保留：%r → %r"
                               % (i + 1, a[1][:40], b[1][:40])))
                break

    # 正文语言（官方豁免之外的任何中文）
    zh = PF.non_english_spans(out)
    if zh:
        issues.append(("non_english", "编译稿仍有 %d 处非英文（第 %d 行：%s）"
                       % (len(zh), zh[0][0], zh[0][1][:40])))

    # 中文十块混入（H3 上会被当台词念）
    blocks = BLOCK_CN_RE.findall(out)
    if blocks:
        issues.append(("tenblock", "编译稿混入中文块名：%s" % "、".join(blocks[:6])))

    # 截断
    for code in _looks_truncated(out):
        issues.append(("truncated_%s" % code, "编译稿疑似截断：%s" % code))

    # 超长（按 translate 步的 max_tokens 预算估）
    est = int(len(out) / 4) + 1
    if est > int(max_tokens):
        issues.append(("too_long", "编译稿约 %d tokens > 预算 %d（len=%d）"
                       % (est, int(max_tokens), len(out))))
    if len(out) > MAX_COMPILED_CHARS:
        issues.append(("too_long_chars", "编译稿 %d 字符 > %d 上限"
                       % (len(out), MAX_COMPILED_CHARS)))

    # 静默缩写（仅当源稿确实需要编译时）
    if needs_compile(src) and len(out) < len(src) * MIN_EN_RATIO:
        issues.append(("abbreviated", "编译稿 %d 字符 < 源稿 %d 字符的 %.0f%% ⇒ 疑似静默缩写"
                       % (len(out), len(src), MIN_EN_RATIO * 100)))
    return issues


def compile_prompt(source_text, translator, mode=None, max_tokens=DEFAULT_MAX_TOKENS):
    """纯函数编译：英译由注入的 translator 完成，本函数只做判定与返回。

    translator(source_text, system_prompt) -> str。传 None 表示"没有联网实现"：
    仅当源稿本来就不需要编译（正文无中文）时走 identity；否则返回错误，不静默放行。
    """
    src = source_text or ""
    if src.startswith(u"\ufeff"):
        src = src.lstrip(u"\ufeff")
    if not needs_compile(src):
        return CompileResult(src, "identity", validate_compiled(src, src, mode, max_tokens))
    if translator is None:
        return CompileResult("", "none", [("no_translator",
                                           "源稿正文含中文，需要编译，但未注入 translator（联网部分）")])
    try:
        out = translator(src, COMPILE_SYSTEM)
    except Exception as e:
        return CompileResult("", "error", [("translator_error", "%s: %s" % (type(e).__name__, e))])
    return CompileResult(out, "translator", validate_compiled(src, out, mode, max_tokens))


# ---------------------------------------------------------------- 落盘：快照与证据
def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _eol_kind(b):
    crlf = b.count(b"\r\n")
    lf = b.count(b"\n") - crlf
    if crlf and not lf:
        return "CRLF"
    if lf and not crlf:
        return "LF"
    return "mixed" if crlf or lf else "none"


def snapshot_source(source_path, out_dir, run_id):
    """翻译前：原稿按字节复制 + 记 sha256/mtime/EOL；纯英文稿同时生成 identity 编译稿。

    返回 (state_path, compiled_path|None, state dict)。不修改原稿。
    """
    src = os.path.abspath(source_path)
    b = open(src, "rb").read()
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    base = "source_%s.txt" % run_id
    snap = os.path.join(out_dir, base)
    with open(snap, "wb") as f:
        f.write(b)                       # 逐字节，不做换行/编码转换
    text = b.decode("utf-8", "replace")
    state = {
        "run_id": run_id,
        "source": src,
        "snapshot": snap,
        "sha256": _sha256_bytes(b),
        "size": len(b),
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                               time.localtime(os.path.getmtime(src))),
        "eol": _eol_kind(b),
        "needs_compile": needs_compile(text),
    }
    compiled = None
    if not state["needs_compile"]:
        compiled = os.path.join(out_dir, "compiled_%s.txt" % run_id)
        with open(compiled, "wb") as f:
            f.write(b)                   # identity：英文稿就是原稿的字节副本
        state["identity"] = True
    state_path = os.path.join(out_dir, "source_%s.json" % run_id)
    with io.open(state_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=2))
    return state_path, compiled, state


def verify_compiled(source_path, state_dir, run_id, compiled_path,
                    mode=None, max_tokens=DEFAULT_MAX_TOKENS):
    """提交前：原稿哈希不变 + 编译稿通过全部校验。返回 (issues, state)。

    issues 为空才可提交；原稿被回写/改一个字节都会在这里红。
    """
    issues = []
    state_path = os.path.join(os.path.abspath(state_dir), "source_%s.json" % run_id)
    if not os.path.isfile(state_path):
        return [("missing_state", "找不到快照 %s —— 无法证明原稿未被回写" % state_path)], {}
    state = json.loads(io.open(state_path, encoding="utf-8").read())
    src = os.path.abspath(source_path)
    if os.path.abspath(str(state.get("source"))) != src:
        issues.append(("source_mismatch", "快照记录的原稿是 %s，本次传入 %s"
                       % (state.get("source"), src)))
    b = open(src, "rb").read() if os.path.isfile(src) else b""
    if _sha256_bytes(b) != state.get("sha256"):
        issues.append(("original_changed", "原稿 sha256 与快照不一致 ⇒ 原稿被改写/回写，禁止提交"))
    if os.path.abspath(compiled_path) == src:
        issues.append(("writeback", "编译稿路径就是原稿路径 ⇒ 编译结果会回写原稿，禁止提交"))
    if not os.path.isfile(compiled_path):
        issues.append(("missing_compiled", "编译稿不存在：%s" % compiled_path))
        return issues, state
    cb = open(compiled_path, "rb").read()
    out = cb.decode("utf-8", "replace")
    if out.startswith(u"\ufeff"):
        issues.append(("bom", "编译稿带 UTF-8 BOM"))
    src_text = b.decode("utf-8", "replace")
    issues.extend(validate_compiled(src_text, out, mode=mode, max_tokens=max_tokens))
    # 去重（哈希/结构问题可能和 validate 的重叠）
    seen, uniq = set(), []
    for code, msg in issues:
        if (code, msg) in seen:
            continue
        seen.add((code, msg))
        uniq.append((code, msg))
    return uniq, state


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="W2 英文编译：快照/校验（离线，不联网）")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("snapshot", help="翻译前把原稿按字节快照并记 sha256")
    s.add_argument("--source", required=True)
    s.add_argument("--out-dir", required=True)
    s.add_argument("--run-id", required=True)
    v = sub.add_parser("verify", help="提交前校验：原稿哈希不变 + 编译稿合规")
    v.add_argument("--source", required=True)
    v.add_argument("--state-dir", required=True)
    v.add_argument("--run-id", required=True)
    v.add_argument("--compiled", required=True)
    v.add_argument("--mode", default=None,
                   choices=list(SPEC.MODES))
    v.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    c = sub.add_parser("check", help="离线比对一份源稿与编译稿（无快照）")
    c.add_argument("--source", required=True)
    c.add_argument("--compiled", required=True)
    c.add_argument("--mode", default=None, choices=list(SPEC.MODES))
    c.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    a = ap.parse_args(argv)

    if a.cmd == "snapshot":
        state_path, compiled, state = snapshot_source(a.source, a.out_dir, a.run_id)
        print("[snapshot] 原稿 %s → %s" % (a.source, state_path))
        print("           sha256=%s size=%d eol=%s needs_compile=%s"
              % (state["sha256"], state["size"], state["eol"], state["needs_compile"]))
        if compiled:
            print("[snapshot] 正文无中文 ⇒ 已生成 identity 编译稿 %s" % compiled)
        return 0

    if a.cmd == "verify":
        issues, state = verify_compiled(a.source, a.state_dir, a.run_id, a.compiled,
                                        mode=a.mode, max_tokens=a.max_tokens)
        if issues:
            print("[verify] FAIL：编译稿不可提交（%d 条）" % len(issues))
            for code, msg in issues:
                print("  ✗ %-24s %s" % (code, msg))
            return 1
        print("[verify] PASS：原稿哈希未变（%s），编译稿通过格式/台词/语言/长度校验"
              % state.get("sha256", "")[:12])
        return 0

    if a.cmd == "check":
        src = io.open(a.source, encoding="utf-8", errors="replace").read()
        out = io.open(a.compiled, encoding="utf-8", errors="replace").read()
        issues = validate_compiled(src, out, mode=a.mode, max_tokens=a.max_tokens)
        if issues:
            print("[check] FAIL：%d 条" % len(issues))
            for code, msg in issues:
                print("  ✗ %-24s %s" % (code, msg))
            return 1
        print("[check] PASS：格式/台词/语言/长度均通过")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
