# -*- coding: utf-8 -*-
"""check_h3_dialogue.py - official dialogue format + locked project rules.

Gates (D1–D10；W2 起分层判级):
  D1 dialogue only in integrated_multimodal_description via (Sx) says: <d>[Lang]…</d>
  D2 soundscape has zero dialogue
  D3 every <d> has speech lead-in; every speech colon has <d>
  D4 speaker IDs (Sx) present and STABLE across batch files
  D5 一镜一声：**按 Shot 计人**，同一 [Shot N] 内最多 1 个说话 ID（默认 warn）
  D6 lip lock phrase after each <d>
  D7 UNIQUENESS LOCK + SPATIAL ANCHOR + ENVIRONMENT present（无对白不要求；默认 warn）
  D8 eyeline lock phrase present（无对白不要求；默认 warn）
  D9 no banned negatives / camera gear（默认 warn）
  D10 official first line + fields once each（W2：首行/字段识别委托 h3_official_spec）

W2（2026-10-23）分层裁定：
  · 官方硬约束（D1/D2/D3/D4/D6/D10）仍是 error；
  · 房内专项（D5/D7/D8/D9）默认 **warn**，只有项目/题材显式开启才升 error：
        --house                  全部房内专项升 error
        --house-rules D5,D7      只升指定的几条
  · **无对白不强制 D7/D8**：稿子里没有 <d> 也没有说话引导句时，D7/D8 整条跳过。

Usage: python check_h3_dialogue.py a.txt b.txt ... [--mode i2va|fl2va|l2va|t2va|ref2va]
       python check_h3_dialogue.py --dir shots_folder [--house|--house-rules D5,D7] [--strict]
Exit: 0 = 无 error（warn 不算失败）；1 = 有 error；2 = 用法错。--strict 时 warn 也按失败。
"""
import importlib.util
import os
import re
import sys

SPEECH = re.compile(
    r"(says|said|exclaims|replies|answers|whispers|shouts|asks|mutters|calls|cries)\b[^:]{0,80}:",
    re.I,
)
D_TAG = re.compile(r"<d>\s*\[([^\]]+)\]\s*(.+?)\s*</d>", re.S)
SPEAKER = re.compile(r"\((S\d+(?:,S\d+)*)\)")
NEG = re.compile(r"\b(NO|NOT|Never|none)\b|禁止|不要|不得|不许|避免|严禁|切勿|\bwithout\b|\bavoid\b", re.I)
GEAR = re.compile(r"dolly|steadicam|tripod|gimbal|crane mount", re.I)
LIP = re.compile(
    r"(closes (her|his|its) lips|lips close|speech pulse stops|closes its speech|lip sync stops)",
    re.I,
)
EYELINE = re.compile(
    r"(three-quarter|profile|gaze|eyes (are )?fixed|looks toward|facing (left|right))",
    re.I,
)
QUOTED_CJK = re.compile(r"[\"“][^\"“”]{2,}[\"”]")
CJK = re.compile(u"[\u4e00-\u9fff]")

HOUSE_RULES = ("D5", "D7", "D8", "D9")
SKELETON_MODES = ("i2va", "fl2va", "l2va", "t2va")


# ---------------------------------------------------------------- 格式核心（唯一真源）
def _load_spec():
    """W2：D10 的首行/字段/模式判定只认 h3_official_spec，不再在本文件维护第二份表。"""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h3_official_spec.py")
        ld = importlib.util.spec_from_file_location("h3_official_spec", p)
        m = importlib.util.module_from_spec(ld)
        ld.loader.exec_module(m)
        return m, None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


SPEC, SPEC_ERR = _load_spec()


class Issue(str):
    """带级别的字符串：打印与旧调用方完全兼容，聚合时读 .sev。"""

    sev = "error"

    def __new__(cls, text, sev="error"):
        obj = str.__new__(cls, text)
        obj.sev = sev
        return obj


def _sev(issue):
    return getattr(issue, "sev", "error")


def _house_on(rule, house_rules):
    return bool(house_rules) and (house_rules is True or rule in house_rules)


def _sections(text):
    # ref2va uses detailed_description; fl2va/t2va/i2va use integrated_multimodal_description
    m_int = re.search(
        r"(?:integrated_multimodal_description|detailed_description):\s*(.*?)(?=overall_soundscape:|$)",
        text,
        re.S,
    )
    m_snd = re.search(
        r"overall_soundscape:\s*(.*?)(?=non_diegetic_music:|$)", text, re.S
    )
    return (m_int.group(1) if m_int else ""), (m_snd.group(1) if m_snd else ""), bool(m_int), bool(m_snd)


def _d10(text, mode=None, house_rules=()):
    """D10：官方首行/字段/槽位（W2 共用格式核心）。

    认不出 H3 格式、首行不对、字段重复/缺失/乱序、骨架与六段混用、Picture 越界都记 error；
    规则 ID 仍是 D10。显式 `mode` 与内容模式不一致也算 error。
    """
    if SPEC is None:
        return [Issue("D10: 格式核心 h3_official_spec 不可用（%s）⇒ 首行/字段判定不能执行"
                      % SPEC_ERR, "error")]
    issues = []
    a = SPEC.analyze(text)
    want = str(mode or "").strip().lower() or None
    if a["format"] == "h3_ref2va":
        if want and want != "ref2va":
            issues.append(Issue("D10: 内容是 Ref2VA 六段，但 --mode 声明 %s" % want.upper()))
        for f in a["fields"]:
            if a["counts"].get(f, 0) != 1:
                issues.append(Issue("D10: ref2va field count != 1: %s" % f))
        if not a["missing"] and a["order_ok"] is False:
            issues.append(Issue("D10: 六段顺序不对（subject_definitions → summary → "
                                "retention_analysis → detailed_description → overall_soundscape "
                                "→ non_diegetic_music）"))
        skel = [f for f in (SPEC.SKELETON_ONLY_FIELDS if hasattr(SPEC, "SKELETON_ONLY_FIELDS")
                            else ())
                if f in text]
        if skel:
            issues.append(Issue("D10: 六段里混进基础骨架字段 %s（两种模式互斥）" % skel))
        if not re.search(r"<(Picture|Subject|Video|Audio)\s*\d+>", text):
            issues.append(Issue("D10: ref2va without <Picture>/<Subject> labels"))
        return issues

    if a["format"] != "h3_skeleton":
        return [Issue("D10: 认不出 H3 格式（既不是官方三字段骨架，也不是 Ref2VA 六段）")]

    inferred = a["mode"]
    if inferred is None and want == "t2va" and text.lstrip(u"\ufeff").lstrip().startswith(
            (SPEC.BASE_FIELDS if hasattr(SPEC, "BASE_FIELDS") else ("integrated_multimodal_description:",))[0]):
        inferred = "t2va"
    if inferred is None:
        issues.append(Issue("D10: 缺官方首行指令/不是官方四形之一（I2VA/FL2VA/L2VA 逐字句式；"
                            "T2VA 无首行，须以 integrated_multimodal_description: 开头）"))
    elif want in SKELETON_MODES and want != inferred:
        issues.append(Issue("D10: 首行是 %s，但 --mode 声明 %s" % (inferred.upper(), want.upper())))
    elif inferred in ("i2va", "fl2va", "l2va"):
        rest = text.split("\n", 1)[1] if "\n" in text else ""
        if not rest.startswith("\n"):
            issues.append(Issue("D10: 官方首行指令后必须空一行再进三字段"))

    for f in a["fields"]:
        if a["counts"].get(f, 0) != 1:
            issues.append(Issue("D10: field count != 1: %s" % f))
    if not a["missing"] and a["order_ok"] is False:
        issues.append(Issue("D10: 三字段顺序不对（integrated → soundscape → music）"))
    if not a["missing"] and not a["duplicated"] and not a["body_start_ok"]:
        issues.append(Issue("D10: 正文没有以 [Shot 1] 开头"))

    pics = a["pictures"]
    if inferred in ("i2va", "l2va") and pics - {1}:
        issues.append(Issue("D10: %s 只挂 <Picture 1>，引用了其他槽 %s"
                            % (inferred.upper(), sorted(pics - {1}))))
    elif inferred == "fl2va" and pics - {1, 2}:
        issues.append(Issue("D10: FL2VA 只允许 <Picture 1>/<Picture 2>（首帧/末帧）"))
    elif inferred == "t2va" and pics:
        issues.append(Issue("D10: T2VA 官方无图，正文却引用了 <Picture N>"))

    six = [f for f in SPEC.REF2VA_ONLY_FIELDS if f in text]
    if six:
        issues.append(Issue("D10: 骨架里混进全参考六段字段 %s（两种模式互斥）" % six))
    return issues


def check_text(text, mode=None, house_rules=()):
    """纯函数版检查（不读盘，便于离线测试）。返回 (issues, speakers)。"""
    issues = []
    body, snd, has_int, has_snd = _sections(text)

    if not has_int:
        issues.append(Issue("D1: missing integrated_multimodal_description/detailed_description"))
    if not has_snd:
        issues.append(Issue("D2: missing overall_soundscape"))

    # D1 speech → <d>
    for m in SPEECH.finditer(body):
        tail = body[m.end(): m.end() + 140]
        if "<d>" not in tail:
            issues.append(Issue("D1: speech without <d>: %r" % m.group(0)))

    has_ref2va = "subject_definitions:" in text
    for m in D_TAG.finditer(body):
        prev = body[max(0, m.start() - 120): m.start()]
        if not re.search(
            r"(says|said|exclaims|replies|answers|whispers|shouts|asks|mutters|calls|cries|voice)\b",
            prev,
            re.I,
        ):
            issues.append(Issue("D3: <d> without speech lead-in near: ...%r" % prev[-50:]))
        if has_ref2va and not re.search(r"<Subject\s*\d+>\s*\(\s*S\d+", prev):
            issues.append(Issue(
                "D3: ref2va <d> must bind <Subject N> (Sx) before says: ...%r" % prev[-60:]))
        after = body[m.end(): m.end() + 100]
        if not LIP.search(after):
            issues.append(Issue("D6: no lip lock after <d>: <d>...%r then %r"
                                % (m.group(2)[:20], after[:40])))

    # D2 soundscape clean
    if "<d>" in snd or "</d>" in snd:
        issues.append(Issue("D2: soundscape contains <d>"))
    if SPEECH.search(snd):
        issues.append(Issue("D2: soundscape contains speech verbs"))
    for q in QUOTED_CJK.findall(snd):
        if CJK.search(q):
            issues.append(Issue("D2: soundscape quoted Chinese (dialogue leak): %r" % q[:30]))

    # D4 speaker IDs
    speakers = set()
    for m in SPEAKER.finditer(body):
        for s in m.group(1).split(","):
            speakers.add(s)
    if D_TAG.search(body) and not speakers:
        issues.append(Issue("D4: dialogue without (Sx) speaker ID"))

    # D5 一镜一声（W2：按 Shot 分块计人，不再全篇累加；默认 warn）
    blocks = SPEC.shot_blocks(body) if SPEC is not None else [(None, body)]
    d5_sev = "error" if _house_on("D5", house_rules) else "warn"
    for shot_no, blk in blocks:
        speaking = set()
        for m in re.finditer(r"\((S\d+(?:,S\d+)*)\)[^<]{0,80}<d>", blk):
            for s in m.group(1).split(","):
                speaking.add(s)
        if len(speaking) > 1:
            issues.append(Issue("D5: %s 有 %d 个说话 ID（一镜一声，最多 1 个）：%s"
                                % ("镜%s" % shot_no if shot_no else "同一镜", len(speaking),
                                   sorted(speaking)), d5_sev))

    # D7/D8：无对白不强制（W2 裁定）。有对白时才检查；默认 warn。
    has_dialogue = bool(D_TAG.search(body)) or bool(SPEECH.search(body))
    if has_dialogue:
        d7_sev = "error" if _house_on("D7", house_rules) else "warn"
        if not re.search(r"UNIQUENESS LOCK|exactly one", text, re.I):
            issues.append(Issue("D7: missing UNIQUENESS LOCK", d7_sev))
        if not re.search(r"SPATIAL ANCHOR", text, re.I):
            issues.append(Issue("D7: missing SPATIAL ANCHOR", d7_sev))
        if not re.search(r"ENVIRONMENT", text, re.I):
            issues.append(Issue("D7: missing ENVIRONMENT", d7_sev))
        d8_sev = "error" if _house_on("D8", house_rules) else "warn"
        if not EYELINE.search(body):
            issues.append(Issue("D8: missing eyeline / three-quarter / gaze phrase", d8_sev))

    # D9 banned（默认 warn，项目显式开启才 error）
    d9_sev = "error" if _house_on("D9", house_rules) else "warn"
    if NEG.search(text):
        issues.append(Issue("D9: banned negative: %r" % NEG.search(text).group(0), d9_sev))
    if GEAR.search(text):
        issues.append(Issue("D9: camera gear: %r" % GEAR.search(text).group(0), d9_sev))

    # D10 官方格式（共用格式核心）
    issues.extend(_d10(text, mode=mode, house_rules=house_rules))
    return issues, speakers


def check(path, mode=None, house_rules=()):
    with open(path, "rb") as f:
        raw = f.read()
    issues = []
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append(Issue("D9: BOM present",
                            "error" if _house_on("D9", house_rules) else "warn"))
    text = raw.decode("utf-8")
    got, speakers = check_text(text, mode=mode, house_rules=house_rules)
    return issues + got, speakers


def check_batch(paths, mode=None, house_rules=()):
    """Also verify speaker ID stability across files: same name → same ID."""
    all_issues = []
    id_map = {}  # speaker id -> set of identity phrases (first 8 words before (Sx))
    for p in paths:
        iss, speakers = check(p, mode=mode, house_rules=house_rules)
        text = open(p, encoding="utf-8").read()
        for m in SPEAKER.finditer(text):
            sid = m.group(1).split(",")[0]
            lead = text[max(0, m.start() - 80): m.start()].strip()[-60:]
            id_map.setdefault(sid, set()).add(lead)
        if iss:
            all_issues.append((p, iss))
    # stability: one ID used for wildly different leads is ok; flag if same lead uses 2 IDs
    lead_to_ids = {}
    for sid, leads in id_map.items():
        for lead in leads:
            key = re.sub(r"\s+", " ", lead)[-40:]
            lead_to_ids.setdefault(key, set()).add(sid)
    for lead, ids in lead_to_ids.items():
        if len(ids) > 1:
            all_issues.append(
                (
                    "<batch>",
                    [Issue("D4: identity lead maps to multiple IDs %s: ...%r"
                           % (sorted(ids), lead))],
                )
            )
    return all_issues


def _parse_house(args):
    """--house / --house-rules D5,D7 → frozenset。没给＝空集（全部默认 warn）。"""
    rules = set()
    if "--house" in args:
        rules |= set(HOUSE_RULES)
    for i, a in enumerate(args):
        if a == "--house-rules" and i + 1 < len(args):
            rules |= {x.strip().upper() for x in args[i + 1].split(",") if x.strip()}
        elif a.startswith("--house-rules="):
            rules |= {x.strip().upper() for x in a.split("=", 1)[1].split(",") if x.strip()}
    bad = sorted(rules - set(HOUSE_RULES))
    return frozenset(rules), bad


def main():
    args = [a for a in sys.argv[1:]]
    mode = None
    strict = "--strict" in args
    for i, a in enumerate(args):
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1].lower()
        elif a.startswith("--mode="):
            mode = a.split("=", 1)[1].lower()
    house_rules, bad = _parse_house(args)
    if bad:
        print("--house-rules 只认 %s，收到 %s" % ("/".join(HOUSE_RULES), bad))
        return 2
    clean = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--house", "--strict"):
            i += 1
            continue
        if a == "--mode":
            i += 2
            continue
        if a.startswith("--mode=") or a.startswith("--house-rules="):
            i += 1
            continue
        if a == "--house-rules":
            i += 2
            continue
        clean.append(a)
        i += 1
    if not clean:
        print("usage: check_h3_dialogue.py <files...> | --dir <folder> "
              "[--mode M] [--house|--house-rules D5,D7] [--strict]")
        return 2
    if clean[0] == "--dir":
        folder = clean[1]
        paths = []
        for f in sorted(os.listdir(folder)):
            if not (f.endswith(".txt") or f.endswith(".md")):
                continue
            p = os.path.join(folder, f)
            text = open(p, encoding="utf-8", errors="replace").read()
            # skip concat lists and non-prompt notes; accept every H3 official format
            fmt = SPEC.detect_format(text) if SPEC is not None else None
            if fmt is None and "integrated_multimodal_description" not in text \
                    and "For the target video" not in text:
                continue
            paths.append(p)
    else:
        paths = clean

    batch = check_batch(paths, mode=mode, house_rules=house_rules)
    any_error = False
    seen = set()
    for p, iss in batch:
        errs = [i for i in iss if _sev(i) == "error"]
        warns = [i for i in iss if _sev(i) == "warn"]
        if errs:
            any_error = True
        print(("[FAIL] " if errs else "[WARN] ") + p)
        for i in errs:
            print("  -", i)
        for i in warns:
            print("  ~", i)
        seen.add(p)
    for p in paths:
        if p not in seen:
            print("[PASS]", p)
    if strict and any(_sev(i) != "error" for _, iss in batch for i in iss):
        any_error = True
        print("--strict：存在 warn，按失败处理")
    if house_rules:
        print("房内专项升 error：%s" % ",".join(sorted(house_rules)))
    print("OVERALL", "FAIL" if any_error else "PASS")
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
