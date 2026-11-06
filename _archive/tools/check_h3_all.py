# -*- coding: utf-8 -*-
"""check_h3_all.py - single entry: run every H3 gate before GPU.

W2（2026-10-23）改派发：不再用 check_h3_prompt.py 的 I2VA-only 格式表当第二把尺，
而是**先由格式核心 h3_official_spec 认模式，再按模式派发**：
  · 官方契约 F*（h3_official_spec.validate：首行/字段/切点/语言/六段/Ref2VA 专项）
  · 房内格式 H3R0/H3R23（h3_rule_gate.check_format，与 G7 同判据）
  · 跑前闸 G7（check_preflight.g7_prompt_format：槽位/混用/器材词/FL2VA 多镜 warn）
  · 对白闸 D1–D10（check_h3_dialogue：D5 按 Shot 计人；D7/D8/D9 默认 warn）

分层裁定（W2）：
  · 无对白不强制 D7/D8；
  · D5（一镜一声）/D7/D8/D9 默认 **warn**，项目/题材显式开启才 error：
        --house               全部升 error
        --house-rules D5,D7   只升指定的几条
  · 官方硬约束（D1/D2/D3/D4/D6/D10、F*）仍是 error。

Usage: python check_h3_all.py <prompt.txt> [more...] [--mode M] [--frames 360]
       python check_h3_all.py --dir <folder> [--mode M] [--house|--house-rules ...] [--strict]
Exit 0 = 无 error（warn 不算失败；--strict 时 warn 也失败）。
Exit 1 = 闸门不合格。Exit 4 = 闸门过了但 --frames 判据没跑（帧数请用
        h3_official_spec.py check --frames N，本入口不把官方时长判据混进来）。Exit 2 = 用法错。
"""
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import h3_official_spec as SPEC          # noqa: E402
import h3_rule_gate as RULE              # noqa: E402
import check_h3_dialogue as DLG          # noqa: E402
import check_preflight as PRE            # noqa: E402

HOUSE_RULES = DLG.HOUSE_RULES


def _usage():
    print("usage: check_h3_all.py <files...> [--mode M] [--frames N] "
          "[--house|--house-rules D5,D7] [--strict] | --dir <folder>")


def _mode_kind(mode):
    return "h3_%s" % mode if mode in SPEC.MODES else "h3"


def check_one(text, mode=None, house_rules=()):
    """返回 (detected_mode, issues=[(sev, gate, msg)])。纯函数，不读盘。"""
    detected = SPEC.detect_mode(text)
    fmt = SPEC.detect_format(text)
    rows = []

    # 1) 官方契约 F*（模式由内容识别；显式 --mode 与内容不符时 F0 会报）
    rp = SPEC.validate(text, mode=mode if mode in SPEC.MODES else None, house=False)
    for r in rp.rows:
        if r["sev"] in ("error", "warn"):
            rows.append((r["sev"], "F%s" % r["id"].lstrip("F"), r["msg"]))

    # 2) 房内格式 H3R0/H3R23（格式核心同一判据，只报版）
    for rid, chks in RULE.check_format(text, channel="h3",
                                       expect=mode or detected):
        for c in chks:
            if c["lvl"] in ("error", "warn"):
                rows.append((c["lvl"], rid, "%s：%s" % (c["name"], c["msg"])))

    # 3) 跑前闸 G7（含 FL2VA 多镜缺切点 warn、器材词、槽位越界）
    rep = PRE.Report()
    PRE.g7_prompt_format(rep, text, PRE.TEN_BLOCKS, "local",
                         kind=_mode_kind(mode or detected), channel="h3")
    for lv, gate, msg in rep.items:
        if lv in ("error", "warn"):
            rows.append((lv, gate, msg))

    # 4) 对白闸 D1–D10（分层判级）
    dis, _speakers = DLG.check_text(text, mode=mode or detected,
                                    house_rules=house_rules)
    for i in dis:
        sev = DLG._sev(i)
        if sev in ("error", "warn"):
            rows.append((sev, "D", str(i)))

    # 同一模式被三个入口重复报同一句时只留一条（规则号不同＝不是重复，照留）
    seen, uniq = set(), []
    for r in rows:
        key = (r[0], r[2])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return detected, fmt, uniq


def _print_result(name, detected, fmt, rows):
    errs = [r for r in rows if r[0] == "error"]
    warns = [r for r in rows if r[0] == "warn"]
    print("===== %s ｜ 模式 %s ｜ 格式 %s ｜ error=%d warn=%d ====="
          % (name, detected or "认不出", fmt or "认不出", len(errs), len(warns)))
    for sev, gate, msg in errs:
        print("  ✗ [%s] %s" % (gate, msg))
    for sev, gate, msg in warns:
        print("  ~ [%s] %s" % (gate, msg))
    return len(errs)


def main():
    args = sys.argv[1:]
    frames = None
    if "--frames" in args:
        i = args.index("--frames")
        try:
            frames = int(args[i + 1])
        except (IndexError, ValueError):
            _usage()
            return 2
        del args[i: i + 2]
    mode = None
    for i, a in enumerate(args):
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1].lower()
        elif a.startswith("--mode="):
            mode = a.split("=", 1)[1].lower()
    if mode and mode not in SPEC.MODES:
        print("--mode 只认 %s，收到 %r" % ("/".join(SPEC.MODES), mode))
        return 2
    house_rules, bad = DLG._parse_house(args)
    if bad:
        print("--house-rules 只认 %s，收到 %s" % ("/".join(HOUSE_RULES), bad))
        return 2
    strict = "--strict" in args

    clean, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("--house", "--strict"):
            i += 1
        elif a in ("--mode", "--house-rules"):
            i += 2
        elif a.startswith("--mode=") or a.startswith("--house-rules="):
            i += 1
        elif a == "--frames":
            i += 2
        else:
            clean.append(a)
            i += 1
    if not clean:
        _usage()
        return 2
    if clean[0] == "--dir":
        if len(clean) < 2:
            _usage()
            return 2
        folder = clean[1]
        files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                 if f.endswith(".txt")]
    else:
        files = clean
    if not files:
        print("没有可审的 .txt")
        return 2

    ok = True
    any_warn = False
    for f in files:
        with open(f, "rb") as fp:
            text = fp.read().decode("utf-8", "replace")
        detected, fmt, rows = check_one(text, mode=mode, house_rules=house_rules)
        nerr = _print_result(os.path.basename(f), detected, fmt, rows)
        any_warn = any_warn or any(r[0] == "warn" for r in rows)
        if nerr:
            ok = False

    # 批级：说话人 ID 稳定性（D4）
    batch_rows = []
    for p, iss in DLG.check_batch(files, mode=mode, house_rules=house_rules):
        if p != "<batch>":
            continue
        for it in iss:
            if DLG._sev(it) == "error":
                batch_rows.append(str(it))
    print("\n===== BATCH =====")
    for m in batch_rows:
        print("  ✗ [D4] %s" % m)
    if batch_rows:
        ok = False
    else:
        print("说话人 ID 跨文件稳定（D4）")

    if not ok:
        print("ALL GATES FAIL")
        return 1
    if frames is not None:
        print("[WARN] --frames=%s 在本入口**未生效**：帧数/官方时长判据请改用 "
              "`py h3_official_spec.py check --dir <目录> --frames %s`。"
              % (frames, frames))
        print("ALL GATES PASS（但 --frames 判据未跑，见上方 WARN）")
        return 4
    if strict and any_warn:
        print("--strict：存在 warn，按失败处理")
        print("ALL GATES FAIL")
        return 1
    print("ALL GATES PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
