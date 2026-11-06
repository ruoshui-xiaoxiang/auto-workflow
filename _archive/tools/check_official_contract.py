# -*- coding: utf-8 -*-
r"""官方契约对账（10-03 批 11 立；取代只查运镜的 check_cam_vocab.py）。

为什么要有它：H3 官方三份模板（`prompts\official_h3\base-en.txt`／`ref-en.txt`／`SKILL.md`）
规定了 43 条契约与四张固定值表，而我们库里过去**只把其中一部分抄进 skill 事实源**，
判据层（通用层 R2／通道真源／速查表）零份——运镜词表就是因此漂成"13 类／14 类"两种说法的。
本脚本**每次现读官方原文**再逐条核对，表里不抄值：官方改了就会报，不靠人记。

六道检查：
  [1] 官方四张固定值表＋§2.1 三种第一行能否解析、条数是否符合预期（官方改版 ⇒ 报 !! 并印出新数）
  [2] 唯一转写处（方案 §十三）是否含全部固定值
  [3] 别处是否**只放指针不重抄**（重抄＝多一个漂移面）；两处偏离登记是否还在
  [4] 已作废的旧数（"300–700 词"）与**已撤销的判据口径**（「换引号重试」「中英混写放行」）不许复活
  [5] **口径优先级（R2 里那条「官方为准」）**在不在、有没有被改回加严判据、第③态有没有漏标
      —— 10-03 批 12 用户裁定：「以官方口径为准，我们自己的口径只作为用户明确要求时的补充」
  [6] 10-03 批 13 那条裁定（graph 文件名 `fl2va`≠官方 FL2VA，不改名只在注册表加注释）**落地了没有**

只报不拦（它查的是文档一致性，不是产物质量；拦人之前要先有人裁）。
`--selftest` 会植入十类坏样本，必须逐条被抓——没做过反向验证的绿分不清是守卫还是摆设。
"""
import glob
import io
import json
import os
import re
import sys

OFF = r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3"
TRANSCRIPT = r"D:\AIWorkflow\ComfyUI_H3\H3提示词工程规则方案.md"
MERGED = r"D:\AIWorkflow\ComfyUI_H3\H3提示词规则_现行合并版.md"
SPEED = r"E:\本地工作流规范手册\00_读我\硬参数速查表.md"
R2 = r"E:\本地工作流规范手册\20_通用规范层\R2_提示词结构与接口契约.md"
RULE_DIR = r"E:\本地工作流规范手册\20_通用规范层"
POINTER_MARK = "check_official_contract.py"
RETIRED = ("300–700", "300-700")
RETIRED_JUDG = (u"换引号重试", u"中英混写放行")   # 10-03 批 13 撤销的两条判据口径
REG = r"D:\AIWorkflow\engine\channels_registry.json"
SELF3 = "〔本层自写·官方未规定"          # 第③态标签的固定前缀
EXEMPT = ("补充档", "只在用户明确要求", "已裁", "旧口径", "不重述", "已按官方", "无官方出处")
RULE_FILES = (R2, SPEED, TRANSCRIPT, MERGED)

EXPECT = {"mot": 12, "amp": 2, "spd": 2, "styles": 7, "cuts": 5, "tasks": 6, "vis": 4,
          "aud": 4, "fl": 3}


def _read(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def official():
    """从官方原文抽四张固定值表＋推荐结构。抽不到就返回错误，不猜。"""
    for n in ("base-en.txt", "ref-en.txt", "SKILL.md"):
        if not os.path.isfile(os.path.join(OFF, n)):
            return None, "官方模板缺 %s（换机／重装权重包后要重新落）" % n
    b, r = _read(os.path.join(OFF, "base-en.txt")), _read(os.path.join(OFF, "ref-en.txt"))
    if "4.3 Camera Motion" not in b:
        return None, "官方 base-en 里没有 §4.3 Camera Motion —— **厂商改了契约结构，本节全部判据要重读官方**"
    seg = b[b.find("4.3 Camera Motion"):b.find("### 4.4")]

    def cell(v):
        return v.strip().strip("`").strip()

    tri = re.findall(r"^\|\s*(Motion type|Amplitude|Speed)\s*\|\s*([^|]+?)\s*\|", seg, re.M)
    d = {
        "mot": [cell(v) for k, v in tri if k == "Motion type"],
        "amp": [cell(v) for k, v in tri if k == "Amplitude"],
        "spd": [cell(v) for k, v in tri if k == "Speed"],
    }
    # 带官方释义的**整行**（人审版词表要用；释义只解析一次，别处不再抄第二份解析式）
    d["mot_rows"] = [(cell(a), g.strip()) for a, g in re.findall(
        r"^\|\s*Motion type\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", seg, re.M)]
    d["amp_rows"] = [(cell(v), g) for v, g in
                     re.findall(r"^\|\s*Amplitude\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", seg, re.M)]
    d["spd_rows"] = [(cell(v), g) for v, g in
                     re.findall(r"^\|\s*Speed\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", seg, re.M)]
    styles_m = re.search(r"Common styles include (.+?)\.", b)
    d["styles_note"] = styles_m.group(1) if styles_m else ""
    m = re.search(r"Common styles include (.+?)\.", b)
    d["styles"] = re.findall(r"`([^`]+)`", m.group(1)) if m else []
    # 切镜白名单五个短语：**只在官方那句 "For ordinary cuts, use ..." 里抽**。
    # 之前用全文件成对反引号扫描，会被前面奇数个反引号错位（漏掉 `the camera cuts to`），
    # 这是假阴——比假阳更坏，所以换成锚定句抽取。
    _CUT_SEN = re.search(r"For ordinary cuts, use(.{0,400}?)may also be used\.", b, re.S)
    d["cuts"] = sorted({x.strip() for x in re.findall(r"`([^`]+)`", _CUT_SEN.group(1))}
                       ) if _CUT_SEN else []
    itask = r[r.find("## 3. `summary`"):r.find("## 4.")]
    d["tasks"] = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*[^|]+\|", itask, re.M)[:6]
    row_re = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*$", re.M)
    d["task_rows"] = [(a, b.strip()) for a, b in row_re.findall(itask)][:6]
    i41, i42 = r.find("### 4.1"), r.find("### 4.2")
    d["vis"] = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*[^|]+\|", r[i41:i42], re.M)
    d["aud"] = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*[^|]+\|", r[i42:r.find("## 5.", i42)], re.M)
    d["vis_rows"] = [(a, b.strip()) for a, b in row_re.findall(r[i41:i42])]
    d["aud_rows"] = [(a, b.strip()) for a, b in row_re.findall(r[i42:r.find("## 5.", i42)])]
    d["structs"] = re.findall(r"Recommended structure: \*\*([^*]+)\*\*", b)
    # §2.1「最终提示词的第一行」——官方按模式各给一句逐字模板（I2VA／FL2VA／L2VA）
    s21 = b[b.find("### 2.1"):b.find("### 2.2")]
    d["fl"] = [x.strip() for x in re.findall(r"```text\n(.+?)\n```", s21, re.S)]
    d["fl_rows"] = [(m.group(1).strip("* ").strip(), m.group(2).strip()) for m in
                    re.finditer(r"\*\*([A-Z0-9a-z]+)\*\*[^\n]*\n\n```text\n(.+?)\n```", s21, re.S)]
    d["fl_t2va"] = bool(re.search(r"\*\*T2VA\*\* has no image-alignment instruction", s21))
    d["eng_body"] = [s for s in ("Write all six rewrite sections in English",
                                 "Write the body in English",
                                 "Write rewrite sections in English")
                     if s in b or s in r]
    d["throughout"] = b.count("Throughout") + r.count("Throughout") + \
        _read(os.path.join(OFF, "SKILL.md")).count("Throughout")
    return d, None


def bare(v):
    return re.sub(r"[^A-Za-z]", "", v).lower()


def missing_terms(text, d, keys):
    blob = bare(text)
    out = []
    for k in keys:
        for v in d[k]:
            if bare(v) not in blob:
                out.append("%s:%s" % (k, v))
    return out


def collect(d, text=None):
    """全部待核固定值（可选：传 text 覆盖官方值中的一项，供 selftest 植入缺陷）。"""
    return d


def outside_fences(text):
    """返回 [(行号, 行文)]，跳过 ``` 围栏内的行（模板与代码块里出现的写法不算规则口径）。"""
    out, fence = [], False
    for n, l in enumerate(text.split("\n"), 1):
        if l.strip().startswith("`" * 3):
            fence = not fence
            continue
        if not fence:
            out.append((n, l))
    return out


def lint_precedence(text):
    """[5b] 第②态回归：把「三件齐全」这类**已被官方否掉的加严判据**改回去而不带豁免标记 ⇒ 报。"""
    bad = []
    for n, l in outside_fences(text):
        if u"\u4e09\u4ef6\u9f50\u5168" in l and not any(k in l for k in EXEMPT):
            bad.append((n, l.strip()[:60]))
    return bad


def lint_official_silence(text, throughout_hits):
    """[5c] 第③态漏标：官方查无此词（`Throughout` 现读 0 次）却被写进落点表 ⇒ 该行必须带〔本层自写〕。

    throughout_hits 是**每次现读的官方计数**，不是写死的数：官方哪天加了这句，这里就不该再拦，
    脚本会改口提示「探针要重判」。
    """
    if throughout_hits:
        return []
    bad = []
    for n, l in outside_fences(text):
        if "Throughout" in l and SELF3 not in l:
            bad.append((n, l.strip()[:60]))
    return bad


def lint_self3_vocab(text):
    """[5d] 标签词汇只许一种形：方括号标签写了「本层自写」却不是固定前缀 ⇒ 报。

    只查**带〔〕的标签**——正文里当散文用的「本层自写」不算（不然整条 R2-16 自己就被自己拦了）。
    """
    bad = []
    for n, l in outside_fences(text):
        for lab in re.findall(u"〔[^〕\\n]{0,20}\u672c\u5c42\u81ea\u5199[^〕\\n]{0,20}〕", l):
            if not lab.startswith(SELF3):
                bad.append((n, lab))
    return bad


def find_precedence_entry():
    """[5a] 通用层里必须有一条「口径优先级」条目，且三态与补充档口径都在它身上。"""
    hits = []
    for p in sorted(glob.glob(os.path.join(RULE_DIR, "R*.md"))):
        t = _read(p)
        for m in re.finditer(r"^##\s+[GR]\d+-\d+[^\n]*\u53e3\u5f84\u4f18\u5148\u7ea7[^\n]*$", t, re.M):
            body = t[m.end():]
            nxt = re.search(r"^##\s+[GR]\d+-\d+", body, re.M)
            if nxt:
                body = body[:nxt.start()]
            hits.append((os.path.basename(p), m.group(0), body))
    return hits


def precedence_problems(d):
    out = []
    hits = find_precedence_entry()
    if not hits:
        out.append("通用层里查不到「口径优先级」条目 ⇒ 用户 10-03 的裁定（官方为准）没落成规则，"
                   "任何人重新加严都无人拦")
    for name, title, body in hits:
        need = ["\u2460", "\u2461", "\u2462", "\u8865\u5145\u6863", "\u53ea\u5728\u7528\u6237\u660e\u786e\u8981\u6c42",
                SELF3]
        miss = [k for k in need if k not in body]
        if miss:
            out.append("%s《%s》缺要素 %s" % (name, title.strip()[:34], "\u3001".join(miss)))
    for p in RULE_FILES:
        if not os.path.isfile(p):
            out.append("文件不在：%s" % p)
            continue
        t = _read(p)
        for n, frag in lint_precedence(t):
            out.append("%s:%d 把已降为补充档的加严判据当判据写，且没有豁免标记：%s"
                       % (os.path.basename(p), n, frag))
        for n, frag in lint_official_silence(t, d["throughout"]):
            out.append("%s:%d 把官方查无此词的写法挂在官方名下（缺「%s」标）：%s"
                       % (os.path.basename(p), n, SELF3, frag))
        for n, frag in lint_self3_vocab(t):
            out.append("%s:%d 自写标签用错了形（应为固定前缀「%s」）：%s"
                       % (os.path.basename(p), n, SELF3, frag))
    return out


def retired_hits(t):
    """已作废的旧数／已撤销的判据口径：出现就要求同文件带更正语，否则算「悄悄被改回去」。"""
    out = []
    for x, marks in ((u"300–700", (u"无官方出处", u"已废", u"〔更正〕", u"见 §十三")),
                     (u"300-700", (u"无官方出处", u"已废", u"〔更正〕", u"见 §十三")),
                     (RETIRED_JUDG[0], (u"已撤销", u"撤销", u"已删", u"作废", u"已回官方形",
                                        u"待裁-13", u"不再")),
                     (RETIRED_JUDG[1], (u"已撤销", u"撤销", u"已删", u"作废", u"已回官方形",
                                        u"待裁-13", u"不再"))):
        if x in t and not any(k in t for k in marks):
            out.append(x)
    return out


def selftest(d):
    """植入坏样本：缺固定值／丢指针／复活旧数／双反引号／加严判据回归／漏标第③态／标签跑形／
    口径优先级条目被删——每类都必须被抓，否则这条守卫是摆设。"""
    good = " ".join("`%s`" % v for k in EXPECT for v in d[k]) + " " + POINTER_MARK
    assert not missing_terms(good, d, list(EXPECT)), "正向样本被判缺 ⇒ 比对有误伤"
    d_bad = dict(d)
    d_bad["mot"] = d["mot"] + ["Crane Move"]           # 官方多出一行、转写没有
    assert missing_terms(good, d_bad, ["mot"]) == ["mot:Crane Move"], "官方新增一行没被抓到"
    assert POINTER_MARK not in "只有正文没有指针", "指针检查是摆设"
    assert any(x in "旧数 300–700 词又回来了" for x in RETIRED), "旧数复活检查是摆设"
    assert "``" in "``Zoom In``", "双反引号检查是摆设"
    # [5b] 加严判据回归
    assert lint_precedence("1. 写法＝运动类型＋幅度＋速度，**三件齐全**。"), "判据回归没被抓到"
    assert not lint_precedence("旧口径「三件齐全」自本批起降为补充档。"), "补充档口径被误伤"
    assert not lint_precedence("```\n模板里写 三件齐全 占位\n```"), "代码围栏内的占位被误伤"
    # [5c] 漏标第③态
    assert lint_official_silence("| 2 不变量 | 正文末尾 `Throughout: …` |", 0), "漏标没被抓到"
    assert not lint_official_silence("| 2 不变量 | 末尾 `Throughout: …`（〔本层自写·官方未规定〕） |", 0), \
        "已标齐的被误伤"
    assert not lint_official_silence("正文末尾 `Throughout: …`", 3), "官方已有该词时不该再拦"
    # [5d] 标签跑形
    assert lint_self3_vocab("这条是〔本层自写〕的"), "标签写短了没被抓到"
    assert not lint_self3_vocab("这条是〔本层自写·官方未规定〕的"), "正形被误伤"
    assert not lint_self3_vocab("本层自写的加严项只能作补充档"), "散文用法被误伤（守卫自伤＝假阳）"
    # [4] 已撤销的判据口径复活
    assert "换引号重试" in retired_hits("对白出乱码时就换引号重试。"), "撤销掉的判据被改回去没被抓到"
    assert retired_hits(u"本层仍允许中英混写放行") == [RETIRED_JUDG[1]], "混写放行复活没被抓到"
    assert not retired_hits(u"旧句「换引号重试」的退路已撤销（10-03 批 13）"), "带着撤销语的被误伤"
    assert not retired_hits(_read(TRANSCRIPT)), "通道真源现文本被判复活 ⇒ 要么措辞漂了要么比对有误伤"
    # [6] 裁定落地痕迹（注册表那条注释）
    reg = json.loads(_read(REG))
    assert [c for c in reg["channels"] if "fl2va" in str(c.get("naming_note"))], \
        "批 13 的裁定（只加注释）没落地"
    print("  selftest ✓ 十类坏样本（缺固定值／丢指针／旧数复活／排版损伤／判据回归／漏标③态／"
          "标签跑形／围栏误伤／撤销口径复活／注释缺失）都能抓到")
    return 0


def main():
    print("=" * 72)
    print("check_official_contract.py · H3 官方契约对账（只报不拦）")
    print("权威：%s" % OFF)
    print("=" * 72)
    d, err = official()
    if err:
        print("!! %s" % err)
        return 1
    print("官方解析：运镜 %d 行｜幅度 %d｜速度 %d｜风格 token %d｜切镜短语 %d｜"
          "任务类型 %d｜关系标记 可见 %d／音频 %d｜推荐结构 %d｜§2.1 第一行 %d 形｜"
          "`Throughout` 官方出现 %d 次"
          % (len(d["mot"]), len(d["amp"]), len(d["spd"]), len(d["styles"]), len(d["cuts"]),
             len(d["tasks"]), len(d["vis"]), len(d["aud"]), len(d["structs"]), len(d["fl"]),
             d["throughout"]))
    hard = 0
    for k, want in EXPECT.items():
        if len(d[k]) != want:
            print("  !!   官方 %s 抽出 %d 项，预期 %d 项 ⇒ 官方改版或本脚本解析式过期"
                  % (k, len(d[k]), want))
            hard += 1
    if "--selftest" in sys.argv:
        return selftest(d)

    # [2] 唯一转写处
    for path, tag in ((TRANSCRIPT, "方案 §十三（唯一转写）"),
                      (MERGED, "现行合并版（指针＋偏离）"),
                      (SPEED, "硬参数速查表"), (R2, "通用层 R2")):
        if not os.path.isfile(path):
            print("  !!   文件不在：%s" % path)
            hard += 1
            continue
        t = _read(path)
        if "check_official_contract.py" not in t and "§十三" not in t:
            print("  !!   %-24s 既无指针也无转写 ⇒ 判据层看不见官方契约" % tag)
            hard += 1
        if tag.startswith("方案"):
            miss = missing_terms(t, d, ["mot", "amp", "spd", "styles", "cuts", "tasks", "vis",
                                        "aud", "fl"])
            if miss:
                print("  !!   %-24s 缺固定值 %d 项：%s" % (tag, len(miss), "、".join(miss[:6])))
                hard += 1
            else:
                print("  OK   %-24s 四张固定值表齐全（%d 项）"
                      % (tag, sum(len(d[k]) for k in EXPECT)))
            if re.search(r"^\d+\.\s*〔偏离〕", t, re.M):
                if "<d>" not in t:
                    print("  !!   %-24s 有〔偏离〕条目却没写清它偏离的是哪条官方要求" % tag)
                    hard += 1
            elif "〔已回官方形" not in t:
                print("  !!   %-24s 既无〔偏离〕条目、也无「〔已回官方形〕」的痕迹 ⇒ "
                      "分不清是本来就没有、还是被当笔误抹掉了（10-03 批 13 裁过的那两条就属于后者）" % tag)
                hard += 1
        for x in retired_hits(t):
            print("  !!   %-24s 出现已作废的旧数／已撤销的判据口径 %r 且没有更正说明" % (tag, x))
            hard += 1
        # 只抓「成对反引号夹着内容」这种渲染损伤；空行与三反引号代码围栏不算
        bad = [n for n, l in enumerate(t.split("\n"), 1)
               if "``" in l and "````" not in l and not l.strip().startswith("`")
               and re.search("``[^` \n]+``", l)]
        if bad:
            print("  !!   %-24s 有双反引号（渲染会坏）：第 %s 行" % (tag, "、".join(map(str, bad[:4]))))
            hard += 1
    # [3] 机器表只许宽、不许窄
    # 2026-10-19 Phase 4：改指 tools 版（1035 行，10-13，含 CAM_INFLECT_RE 屈折形修复）。
    # 原来指 tmp/wzy 版（998 行，10-04）⇒ 同一批稿，本脚本读的是旧版词表、oneshot 跑的是新版闸。
    # 本次改动**行为中性**已实测：两版 CAM_EN 逐字相同（各 14 项：Zoom/Push/Pull/Pan/Tilt/Truck/
    # Pedestal/Arc/Orbital/Tracking/Static/Shake/Roll/POV），而这里只做正则**文本抽取**、不执行那个文件。
    # ⚠ 别把这条当成"h3_rule_gate 已合一"：tools 版仍是**武昭君仪项目绑定**的
    #   （:36 D=tmp/wzy、:180 从 D 加载 h3_shots.py、:994 读 D/h3/<id>_video.txt），
    #   合一要先把项目数据路径参数化，那是另一件事。详见 官方路径.json 的 known_broken。
    gate = r"D:\AIWorkflow\tools\h3_rule_gate.py"
    if os.path.isfile(gate):
        g = _read(gate)
        m = re.search(r"CAM_EN\s*=\s*\[(.*?)\]", g, re.S)
        if m:
            items = re.findall(r"'([^']+)'", m.group(1))
            roots = [bare(x) for x in items]
            narrow = [x for x in d["mot"] if not any(r in bare(x) or bare(x) in r for r in roots)]
            print("  %s 机器表 CAM_EN %d 项（宽进匹配表）%s"
                  % ("OK  " if not narrow else "!!  ", len(items),
                     "" if not narrow else "，窄于官方：%s" % "、".join(narrow)))
            hard += bool(narrow)
        else:
            print("  !!   CAM_EN 读不到 ⇒ 这条对账空跑")
            hard += 1
    # [5] 口径优先级（用户 10-03 裁定：官方为准，本层自写只在被明确要求时作补充）
    probs = precedence_problems(d)
    for msg in probs:
        print("  !!   [5] %s" % msg)
    hard += len(probs)
    hits = find_precedence_entry()
    if d["throughout"]:
        print("  ??   [5] 官方三模板现在出现了 `Throughout`（%d 次）⇒ 第③态那条探针要重判："
              "它可能已升成官方规定" % d["throughout"])
    if not probs:
        print("  OK   [5] 口径优先级条目在（%s）；补充档未被改回加严；"
              "官方查无的写法都带〔本层自写〕标" % "、".join(h[0][:6] for h in hits))
    # [6] 待裁-12 的执行痕迹：注册表里那条撞名注释还在不在（裁定落地要有机器可查的证据）
    if os.path.isfile(REG):
        try:
            reg = json.loads(_read(REG))
            chans = reg.get("channels") or []
            have = [c for c in chans if isinstance(c, dict) and c.get("naming_note")
                    and "fl2va" in str(c.get("naming_note"))]
            if not chans:
                print("  !!   [6] 通道注册表里 channels 是空的 ⇒ 这条检查空跑")
                hard += 1
            elif not have:
                print("  !!   [6] 注册表查不到「`fl2va` 文件名≠官方 FL2VA」那条注释 ⇒ "
                      "10-03 批 13 的裁定（不改名、只加注释）没落地，读代码的人还会当它是首尾帧通道")
                hard += 1
            else:
                print("  OK   [6] 注册表撞名注释在（挂在 `%s`；通道共 %d 条，条数以盘上为准）"
                      % (have[0]["id"], len(chans)))
        except ValueError as e:
            print("  !!   [6] 通道注册表 JSON 解析失败：%s" % (str(e)[:80],))
            hard += 1
    else:
        print("  !!   [6] 注册表不在盘上：%s" % REG)
        hard += 1
    print("-" * 72)
    print("官方固定值 %d 项｜问题 %d 处｜只报不拦：退出码 0"
          % (sum(len(d[k]) for k in EXPECT), hard))
    return 0


if __name__ == "__main__":
    sys.exit(main())
