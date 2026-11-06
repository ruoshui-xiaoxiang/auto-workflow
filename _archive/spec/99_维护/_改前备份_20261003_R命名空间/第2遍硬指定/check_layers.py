# -*- coding: utf-8 -*-
"""两层规则体系的自校验器（**只读、只报不拦**）。

用法（一律用绝对路径；手册根以外也能跑）：
    py -3.12 "E:\\本地工作流规范手册\\99_维护\\check_layers.py"
    py -3.12 "E:\\本地工作流规范手册\\99_维护\\check_layers.py" --external
    py -3.12 "E:\\本地工作流规范手册\\99_维护\\check_layers.py" --strict

    --external  追加到 E:\\创作 与 D:\\AIWorkflow 里找指针（慢，但外部真源只有在
                这个模式下才可能解析到；不加时指向外部的指针会算「找不到」）
    --strict    有任何 ⚠/!! 时退出码 1。**默认退出码恒为 0**

退出码默认恒为 0 是规格要求（「全部只报不拦」，见
`00_读我\\重构方案_两层分离_待审.md` 批 4）。--strict 留给以后想把它接进闸门时用，
**现在不接**——接之前得先把下面第 4 项那条口径分歧裁掉。

本脚本**不写任何文件**：全文没有 open(..., "w")／shutil／os.remove／os.rename。

────────────────────────────────────────────────────────────────────────────
规格出处（四项，摘自 `00_读我\\重构方案_两层分离_待审.md` 批 4）：

  1. **指针有效性**：通用层每条 `出处:` 指向的文件+锚点是否还存在、是否被改名（防漂移）
  2. **名词剥离自检（T1 自动化）**：扫通用层文件，命中角色名/项目代号/具体道具名即报 ⚠
  3. **反向索引完备性**：项目层每条 `上位:` 指向的通用条是否存在；通用层
     `R_作用域与例外登记表` 是否登记了对应项目条（双向都缺就报）
  4. **冲突项清点**：`关系=冲突` 的条目列成待裁清单，数量必须等于登记表里的未裁项数

第 3 项存在的理由（`30_项目层\\P_武昭君仪\\规则.md` 原话）：
  「`check_layers.py` 会把『指向上位不存在』的条数报出来
    （**这项校验存在的全部理由就是防止占位编号被永久遗忘**）」

附加第 5 项（不在上述四项内，但 `20_索引与分类判据.md` §2 已有规则要求）：
  5. **执行者标记覆盖率**：「每条规则必须登记机器执行者」，
     且「没标执行者的条目视为 `[人]`，且视为现在没人管」。
  ⇒ 只报每条 `## G<n>-<nn>` 有没有执行者标记，不判对错。
────────────────────────────────────────────────────────────────────────────
判读约定（**避免把「报出来」当成「违规」**）：
  ✓ = 通过    ○ = 判不了/已跳过（不算问题，但要看得见）
  ⚠ = 需要人看（可能是真漂了，也可能是本脚本判据不够）
  !! = 大概率真错

三处刻意「不假装通过」的设计，读报告前先看：
  A. 第 1 项把**带扩展名却找不到文件**记 ⚠，把**简写/只到目录/带省略号**记 ○。
     理由：通用层里大量指针写成 `方案 §3.3`、`02\\H3提示词规则_现行合并版`（无扩展名）、
     `06\\`（只到目录）。这些**不是失效指针**，一律记 ⚠ 会让假告警淹死真告警。
     简写真身在 ALIASES 里登记；查不到就报 ○「简写未登记」，提示人去补表。
  B. 第 2 项**跳过 `R_作用域与例外登记表.md`**：那份文件的职责就是记录
     「某项目把某条通用规则收窄成什么具体值」，通篇项目名是**设计如此**，
     拿 T1 去扫它是范畴错误。
  C. 第 4 项的等式**大概率不成立**，脚本把三个数分开报并说明原因，**不凑数**。
     详见 check_4_conflicts() 里的判读文字（那是一条需要用户裁的口径分歧）。
"""
import io
import json
import os
import re
import sys
import time

ROOT = r"E:\本地工作流规范手册"
GEN_DIR = os.path.join(ROOT, "20_通用规范层")
PROJ_DIR = os.path.join(ROOT, "30_项目层")
REGISTRY = "R_作用域与例外登记表.md"

# --external 时才走这两个根；都是只读遍历，且跳过重目录
EXTERNAL_ROOTS = [r"E:\创作", r"D:\AIWorkflow"]
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "venv", ".venv", "models",
             "output", "outputs", "custom_nodes", ".thumbs", "checkpoints",
             "site-packages", ".idea", "dist", "build"}
EXTERNAL_MAX_FILES = 400000

EXTS = (".md", ".py", ".txt", ".yaml", ".yml", ".json", ".jsonl", ".csv",
        ".bat", ".ps1", ".sh", ".js", ".html", ".docx", ".xlsx", ".png", ".jpg")

# ── 简写表 ────────────────────────────────────────────────────────────────
# 通用层「出处」里的指针经常只写短名（`方案 §3.3`）或省掉扩展名
# （`02\H3提示词规则_现行合并版`）。按文件名硬解析会 100% 落空 ⇒ 假告警。
# 所以先过这张表。表里的每一条都在 2026-10-02 用 `test -e` 核实过存在。
# 维护约定：报告里出现 ○「简写未登记」时，把真身补进来（**要人核实路径再加**）。
ALIASES = {
    "方案": r"E:\本地工作流规范手册\02_H3提示词规则\H3提示词工程规则方案_真源.md",
    "现行合并版": r"E:\本地工作流规范手册\02_H3提示词规则\H3提示词规则_现行合并版.md",
    "使用规范": r"E:\本地工作流规范手册\03_使用规范与关口流程",
    "官方规范_h3": r"E:\本地工作流规范手册\02_H3提示词规则\官方规范_MiniMax-H3_h3-prompt-writing_SKILL.md",
    "h3规则方案_v2.1": r"E:\本地工作流规范手册\02_H3提示词规则\H3提示词工程规则方案_真源.md",
    "h3规则方案": r"E:\本地工作流规范手册\02_H3提示词规则\H3提示词工程规则方案_真源.md",
    "手册": r"E:\本地工作流规范手册\01_总手册",
    "关口化实施说明": r"E:\本地工作流规范手册\03_使用规范与关口流程",
    # 外部真源（不在手册副本集里，或副本改了名）
    "v1.md": r"E:\创作\武昭君仪\武昭君仪_剧本与资产盘点_v1.md",
    "ref-en.txt": r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\ref-en.txt",
    "skills/h3-prompt-writing": r"E:\本地工作流规范手册\02_H3提示词规则\官方规范_MiniMax-H3_h3-prompt-writing_SKILL.md",
    "h3-prompt-writing": r"E:\本地工作流规范手册\02_H3提示词规则\官方规范_MiniMax-H3_h3-prompt-writing_SKILL.md",
}

# T1 名词剥离：命中在这些上下文里＝合法引用/样例/证据，记 ○ 不记 ⚠
# 判据原则（2026-10-02 定）：**证据句可以点名具体物件，规则句不可以。**
# 「实测」入表就是因为 G*_.md 每条的结构是 规则 → 机制 → 出处 → 实测，
# 最后那段本来就要写清"在哪个具体案例上量出来的"，写具体名词是它的职责。
INFO_CTX = ("出处", "来源", "样例", "填法", "例如", "例：", "反例", "项目层",
            "登记", "真源", "冲突", "已裁", "未裁", "作废", "旧法条", "坑",
            "索引", "本项目", "镜像", "实测", "WZJY-", "P_武")
INFO_LOOKBACK = 2          # 上一/上上一个非空行里有 INFO_CTX 也算（列表续行）

# 行号锚所在行若自带这些话，说明**文档自己已经登记了这个锚是死的**（如登记表 C8 行
# 就是在举证「prompt_rules.py 引 v1.md:86 … 现为空行」）。这种记 ○ 不记 !!，
# 否则它会永远红着，红久了人就学会不看报告了。
DEAD_ACK = ("现为空行", "已漂", "内容已换", "已改写", "旧记的", "整体移动")

# T1 显式词表：角色名 / 具体道具名 / 画风代号 / 项目代号。
# 项目代号一部分从 30_项目层\P_* 目录名自动派生；**没有 P_ 目录的项目**只能写死在这。
# ⚠ 这张表要人维护：新角色/新道具/新项目进项目层时顺手加进来，否则 T1 查不到它。
T1_NAMES = [
    # 角色
    "武君仪", "武昭君", "沈无音", "萧烬言", "小金焰", "薇拉", "白玖璃",
    "亚瑟王", "圣女", "saintess", "今田美樱", "祝绪丹", "金高银",
    # 具体道具 / 服装件
    "沉铁长枪", "白麻布", "金簪", "携行布带", "义体腿", "云肩", "披膊", "补子",
    "矛头", "长枪", "BJD",
    # 具体载具 / 舰级
    "旭日级", "矩尺级", "仙后级", "战星",
    # 项目代号（无 P_ 目录，派生不到）
    "无音", "仙女星系", "烬骨辞", "太空战",
]

ENTRY_RE = re.compile(r"^##\s+(G\d+-\d+)\s")
EXEC_RE = re.compile(r"执行者")
SRC_LINE_RE = re.compile(r"出处")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
ANGLE_RE = re.compile(r"「([^」\n]{2,40})」")
LINE_ANCHOR_RE = re.compile(r"^(.*?):(\d+)(?:[-–](\d+))?$")
# 全表扫行号锚：`xxx.md:826` 这种，不限「出处」行（C8 那个病就长在表格单元里）
ANY_LINE_ANCHOR_RE = re.compile(
    r"([A-Za-z0-9_\-\u4e00-\u9fff\\/\.]{2,80}?\.(?:md|py|txt|yaml|json|csv)):(\d{1,5})\b")
UPPER_RE = re.compile(r"\bG(\d+)(?:-(\d+))?\b")
PLACEHOLDER_RE = re.compile(r"拟\s*G\d+-x+")
REL_CONFLICT = "冲突"
UNRESOLVED = ("未裁", "未修", "未验")

_CACHE = {}


def read(path):
    if path not in _CACHE:
        try:
            with io.open(path, encoding="utf-8", errors="replace") as f:
                _CACHE[path] = f.read()
        except OSError as e:
            _CACHE[path] = ""
            print("      （读不了 %s：%s）" % (path, e))
    return _CACHE[path]


def files_in(d, exts=(".md",)):
    out = []
    if not os.path.isdir(d):
        return out
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(exts):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def manual_index():
    """→ (文件名小写→[相对路径], 目录数字前缀→[相对路径], 数字前缀→目录名)"""
    by_base, by_prefix, dirs = {}, {}, {}
    for top in sorted(os.listdir(ROOT)):
        m = re.match(r"^(\d+[a-z]?)_", top)
        if m and os.path.isdir(os.path.join(ROOT, top)):
            dirs[m.group(1)] = top
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [x for x in dirnames if x not in ("__pycache__",)]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
            by_base.setdefault(fn.lower(), []).append(rel)
            head = rel.split(os.sep)[0]
            m = re.match(r"^(\d+[a-z]?)", head)
            if m:
                by_prefix.setdefault(m.group(1), []).append(rel)
    return by_base, by_prefix, dirs


def external_index():
    by_base = {}
    n, trunc = 0, False
    for r in EXTERNAL_ROOTS:
        if not os.path.isdir(r):
            continue
        for dirpath, dirnames, filenames in os.walk(r):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
            for fn in filenames:
                by_base.setdefault(fn.lower(), []).append(os.path.join(dirpath, fn))
                n += 1
                if n > EXTERNAL_MAX_FILES:
                    return by_base, n, True
    return by_base, n, trunc


def table_rows(text):
    """→ [(表头单元, 表头行号, [(行号, 单元...)...]) ...]"""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j, block = i, []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                block.append((j + 1, lines[j]))
                j += 1
            if len(block) >= 2:
                hdr = [c.strip() for c in block[0][1].strip().strip("|").split("|")]
                rows = []
                for ln, raw in block[2:]:
                    cells = [c.strip() for c in raw.strip().strip("|").split("|")]
                    if len(cells) == len(hdr):
                        rows.append((ln, cells, raw))
                out.append((hdr, block[0][0], rows))
            i = j
        else:
            i += 1
    return out


def col_of(hdr, *names):
    for k, h in enumerate(hdr):
        for n in names:
            if n in h:
                return k
    return None


# ─────────────────────────────────────────────────────────────
# 1. 指针有效性
# ─────────────────────────────────────────────────────────────
def split_anchor(tok):
    """`a\\b.md:123` → ('a\\b.md', 123)；`X §3` → ('X', None)"""
    t = tok.strip().strip("，,；;。、")
    m = LINE_ANCHOR_RE.match(t)
    if m and (m.group(1).lower().endswith(EXTS) or "\\" in m.group(1)
              or "/" in m.group(1) or m.group(1) in ALIASES):
        return m.group(1), int(m.group(2))
    return re.split(r"\s+§", t)[0].strip(), None


def tail_score(ptr_parts, cand):
    """指针路径的**尾部**与候选路径尾部能对上几段。

    为什么需要：`engine\\config.yaml` 这种指针，盘上同名的 config.yaml 有 5 个
    （E:\\创作\\_归档 两个 40 行的旧备份、两个 LoRA 训练 config、以及真身
    D:\\AIWorkflow\\engine\\config.yaml 90 行）。取 hits[0] 会挑到 40 行的备份，
    然后把一条**正确的**行号锚报成「超出行数」——假告警比漏报更坏。
    按尾部匹配段数排序，`engine\\config.yaml` 就会优先命中 `...\\engine\\config.yaml`。
    """
    cp = [x.lower() for x in re.split(r"[\\/]", cand.replace("/", "\\")) if x]
    n = 0
    for a, b in zip(reversed(ptr_parts), reversed(cp)):
        if a.lower() == b or b == a.lower() + ".md":
            n += 1
        else:
            break
    return n


def resolve(tok, idx):
    """→ (状态, 命中路径列表, 行号 or None)

    状态：file_manual / file_alias / file_external   → ✓
          dir_only / abbrev / shorthand             → ○
          missing                                   → ⚠
          skip                                      → 不计
    """
    mbase, mprefix, mdirs, ext_idx = idx
    t = tok.strip()
    if not t or len(t) < 3:
        return "skip", [], None
    if "…" in t or "..." in t or "*" in t:
        return "abbrev", [], None
    # 带空格的是散文/公式（如 `单元/秒 ＞ SAFE_CEIL(=1.6)`），不是路径。
    # 手册里的指针一律无空格；真有带空格的路径请写进 ALIASES。
    if " " in t:
        return "skip", [], None
    # 只有「含分隔符 / 带已知扩展名 / 登记在 ALIASES」才算路径候选。
    # 否则它是代码标识符（`SPEAR_LOCK`）、批次号（`jm_9862`）之类，
    # 按文件名去解析必然落空 ⇒ 记 skip，不制造假告警。
    low = t.lower()
    if ("\\" not in t and "/" not in t and not low.endswith(EXTS)
            and low not in ALIASES
            and re.sub(r"\.\w+$", "", low) not in ALIASES
            and os.path.basename(low.replace("/", "\\")) not in ALIASES):
        return "skip", [], None
    path, lineno = split_anchor(t)
    base = os.path.basename(path.replace("\\", "/")).lower()
    cands = [base] + [base + e for e in EXTS] + [re.sub(r"\.\w+$", "", base)]

    # 1) 简写表（整串 与 纯文件名 两种键都试）
    for k in (t.lower(), path.lower().replace("\\", "/"), base,
              re.sub(r"\.\w+$", "", base)):
        if k in ALIASES:
            return "file_alias", [ALIASES[k]], lineno

    # 1.5) **绝对路径**直接判存在性。规则层里允许引外部真源（如 `E:\若水AI电影\00_架构总纲.md`），
    #      这类指针既不在手册索引里、也不在 --external 那两个根的索引里
    #      ⇒ 不特判就永远报 ⚠，等于校验器自己制造假告警（会把真漂移淹掉，见 C8 的教训）。
    if os.path.isabs(path):
        ap = os.path.normpath(path.replace("/", "\\"))
        if os.path.isfile(ap):
            return "file_abs", [ap], lineno
        if os.path.isdir(ap):
            return "dir_only", [ap], lineno
        return "missing", [], lineno

    # 2) 手册内：目录前缀 + 文件名（含补扩展名）
    head = path.replace("/", "\\").split("\\")[0]
    mh = re.match(r"^(\d+[a-z]?)$", head)
    hits = []
    if mh:
        for c in cands:
            for rel in mprefix.get(mh.group(1), []):
                if os.path.basename(rel).lower() == c and rel not in hits:
                    hits.append(rel)
    if not hits:
        for c in cands:
            for rel in mbase.get(c, []):
                if rel not in hits:
                    hits.append(rel)
    ptr_parts = [x for x in re.split(r"[\\/]", path) if x]
    if hits:
        hits.sort(key=lambda c: -tail_score(ptr_parts, c))
        return "file_manual", hits, lineno

    # 3) 外部两根（只有 --external 时）
    if ext_idx is not None:
        eh = []
        for c in cands:
            eh += [x for x in ext_idx.get(c, []) if x not in eh]
        if eh:
            eh.sort(key=lambda c: -tail_score(ptr_parts, c))
            return "file_external", eh, lineno

    # 4) 只解析到目录：`06\` / `03\使用规范` / `05\comfy模板`
    if mh and mh.group(1) in mdirs:
        return "dir_only", [os.path.join(ROOT, mdirs[mh.group(1)])], lineno
    if path.replace("/", "\\").rstrip("\\") in [v for v in ALIASES.values()]:
        return "dir_only", [path], lineno
    if os.path.isdir(os.path.join(ROOT, path.replace("/", "\\"))):
        return "dir_only", [os.path.join(ROOT, path.replace("/", "\\"))], lineno

    # 5) 带扩展名却哪儿都找不到 ⇒ 真漂了
    if base.endswith(EXTS):
        return "missing", [], lineno
    return "shorthand", [], lineno


def anchor_lines(text):
    """「出处」所在的行号 ＋ 表头含「出处」的表格的所有行号"""
    out, lines = set(), text.split("\n")
    for i, ln in enumerate(lines, 1):
        if SRC_LINE_RE.search(ln):
            out.add(i)
    for hdr, hln, rows in table_rows(text):
        if any("出处" in h for h in hdr):
            out.add(hln)
            for ln, _cells, _raw in rows:
                out.add(ln)
    return out


CORE_SEPS = ("——", "（", "(", " + ", "＋", "／", "/", "、", "，", ",", "：",
             ":", "；", ";", "。", " ", "　", "·", "→")


def norm(s):
    """只留中日韩汉字与字母数字：比对关键词锚时先把标点/空格/引号全抹掉"""
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)


def anchor_core(a):
    """取「」锚句的**前导核心**（最早出现的分隔符之前那一段）。

    为什么要这个：通用层的「」锚句写的是**话题标签**，不是逐字引文。
    实测四例（2026-10-02）全部"话题在、字面不同"：
      引 `~300px 是启发式`            → 真身写 `⚠️ ~300px 这条线是启发式`
      引 `锚点身份写进 sidecar`        → 真身写 `锚点身份可以写进 sidecar 卡`
      引 `画风漂了不一定是锚链二手——…` → 真身写 `"画风漂了"不一定是锚链二手——…`
      引 `双锚拆分（2026-09-15 …）`    → 真身写 `★双锚拆分＝造型全自由的正确做法（…）`
    逐字比会全判失效 ⇒ 假告警。改成"核心词必须能在目标里 grep 到"，
    仍然满足登记表 §四.6 的目的（行号漂了还能靠关键词定位），
    同时目标真被改名/重写时会照样报出来。
    """
    best = len(a)
    for sep in CORE_SEPS:
        i = a.find(sep)
        if 4 <= i < best:
            best = i
    return a[:best]


def note_anchor(bad, ack, rel, i, tok, ln, fulls, line_text):
    """行号锚是否失效。**所有同名候选都对不上**才算失效（有一个对上就通过）。

    若该行自己已声明这锚是死的（DEAD_ACK）⇒ 记 ○ 不记 !!，否则它会永远红着，
    红久了人就学会不看报告了。
    """
    tried = []
    for full in fulls:
        if not os.path.isfile(full):
            continue
        body = read(full).split("\n")
        if ln <= len(body) and body[ln - 1].strip():
            return False
        tried.append((full, len(body), "超出行数" if ln > len(body) else "该行是空行"))
    if not tried:
        return False
    full, n, why = tried[0]
    if len(tried) > 1:
        why += "（另有 %d 个同名候选也都不对）" % (len(tried) - 1)
    rec = (rel, i, tok, ln, n, why)
    (ack if any(k in line_text for k in DEAD_ACK) else bad).append(rec)
    return True


def fulls_of(hits):
    return [h if os.path.isabs(h) else os.path.join(ROOT, h) for h in hits]


def check_1_pointers(gen_files, idx, ext_used):
    gfiles_written = sorted(set(
        m.group(1) for m in (re.match(r"^(G\d+)_", os.path.basename(p))
                             for p in gen_files) if m))
    print("\n【1】指针有效性（通用层「出处」指向的文件／行号锚／关键词锚 是否还在）")
    print("    解析范围：%s" % ("手册内 ＋ 外部两根（--external）" if ext_used
                             else "**仅手册内**（外部真源必然落空，要判请补 --external 复跑）"))
    print("    扫描范围：含「出处」的行 ＋ 表头含「出处」的表格全部行（%d 份通用层文件）"
          % len(gen_files))
    stat = {}
    miss, planned, alias_unreg, dir_only = [], [], [], []
    line_bad, anchor_bad, dead_ack = [], [], []
    n_alias = n_anch = n_abs = 0
    for p in gen_files:
        rel = os.path.relpath(p, ROOT)
        text = read(p)
        lines = text.split("\n")
        for i in sorted(anchor_lines(text)):
            line = lines[i - 1]
            for tok in BACKTICK_RE.findall(line):
                st, hits, ln = resolve(tok, idx)
                stat[st] = stat.get(st, 0) + 1
                if st == "missing":
                    # `G<n>_xxx.md` 是本层清单里**计划要出但还没出**的文件
                    # （索引 §5 那张表列了 G1–G10，实际只出了 G2/G4）。
                    # 这不是漂移，是欠账 ⇒ 记 ○ 并单独计数，别混进 ⚠。
                    if re.match(r"^G\d+_", os.path.basename(tok.strip())):
                        planned.append((rel, i, tok))
                    else:
                        miss.append((rel, i, tok))
                elif st == "shorthand":
                    alias_unreg.append((rel, i, tok))
                elif st == "dir_only":
                    dir_only.append((rel, i, tok))
                elif st == "file_alias":
                    n_alias += 1
                elif st == "file_abs":
                    n_abs += 1
                if st.startswith("file") and hits and ln:
                    note_anchor(line_bad, dead_ack, rel, i, tok, ln,
                                fulls_of(hits), line)
            for a in ANGLE_RE.findall(line):
                key = norm(anchor_core(a))
                if len(key) < 4:
                    continue
                for tok in BACKTICK_RE.findall(line):
                    st, hits, _ = resolve(tok, idx)
                    if st != "file_manual" or len(hits) != 1:
                        continue
                    body = norm(read(os.path.join(ROOT, hits[0])))
                    n_anch += 1
                    if key not in body:
                        anchor_bad.append((rel, i, a, key, hits[0]))
                    break
    # 全表扫行号锚（不限「出处」行）——C8「机器层行号锚全漂」就长在表格单元里
    extra_bad, n_scan = [], 0
    for p in gen_files:
        rel = os.path.relpath(p, ROOT)
        for i, line in enumerate(read(p).split("\n"), 1):
            for fn, ln in ANY_LINE_ANCHOR_RE.findall(line):
                st, hits, _ = resolve(fn, idx)
                if not st.startswith("file") or not hits:
                    continue
                n_scan += 1
                note_anchor(extra_bad, dead_ack, rel, i,
                            "%s:%s" % (fn, ln), int(ln), fulls_of(hits), line)
    print("    统计：✓ 手册内命中 %d ｜ ✓ 外部命中 %d ｜ ✓ 绝对路径命中 %d ｜ ✓ 经 ALIASES 命中 %d"
          % (stat.get("file_manual", 0), stat.get("file_external", 0), n_abs, n_alias))
    print("          ○ 只到目录 %d ｜ ○ 待成文的 G 文件 %d ｜ ○ 简写未登记 %d"
          " ｜ ○ 省略号/通配 %d ｜ ⚠ 找不到 %d"
          % (len(dir_only), len(planned), len(alias_unreg),
             stat.get("abbrev", 0), len(miss)))
    if planned:
        print("  ○ 本层清单里列了、但还没成文的 G 文件 %d 份（索引 §5 计划 G1–G10，"
              "实际已出 %d 份）：" % (len(planned), len(gfiles_written)))
        for rel, i, tok in planned:
            print("      %s:%d  `%s`" % (rel, i, tok))
    if miss:
        print("  ⚠ 带扩展名却找不到文件的指针 %d 处（这才是真漂了）：" % len(miss))
        for rel, i, tok in miss[:25]:
            print("      %s:%d  `%s`" % (rel, i, tok))
        if len(miss) > 25:
            print("      … 其余 %d 处省略" % (len(miss) - 25))
    else:
        print("  ✓ 所有带扩展名的指针都解析到了文件")
    if alias_unreg:
        seen = sorted(set(t for _r, _i, t in alias_unreg))
        print("  ○ 简写未登记 %d 处（%d 种）——不是失效，是 ALIASES 表没收录：" % (len(alias_unreg), len(seen)))
        for t in seen[:20]:
            print("      `%s`" % t)
        print("      补表位置：本脚本 ALIASES（**加之前先 test -e 核实真身**）")
    if dir_only:
        seen = sorted(set(t for _r, _i, t in dir_only))
        print("  ○ 只解析到目录、未匹配到具体文件 %d 处（%d 种，多为节级指针）：%s"
              % (len(dir_only), len(seen), "、".join("`%s`" % x for x in seen[:12])))
    bad_all = line_bad + extra_bad
    if bad_all:
        print("  !! 行号锚失效 %d 处（「出处」行内 %d ＋ 全表扫 %d）——这就是冲突表 C8 那个病："
              % (len(bad_all), len(line_bad), len(extra_bad)))
        for rel, i, tok, ln, n, why in bad_all[:20]:
            print("      %s:%d  `%s` → 第 %d 行（目标共 %d 行，%s）" % (rel, i, tok, ln, n, why))
        if len(bad_all) > 20:
            print("      … 其余 %d 处省略" % (len(bad_all) - 20))
        print("      修法（登记表 §四.6）：行号属易碎指针，一律配一个「关键词锚」，别只留行号。")
    else:
        print("  ✓ 行号锚全部落在有内容的行上（全表扫共解析到 %d 个可查锚）" % n_scan)
    if dead_ack:
        print("  ○ 已登记的死锚 %d 处（所在行自己写明了「现为空行／已漂／已改写」，"
              "属举证不属缺陷）：" % len(dead_ack))
        for rel, i, tok, ln, n, why in dead_ack[:10]:
            print("      %s:%d  `%s` → 第 %d 行（%s）" % (rel, i, tok, ln, why))
    if anchor_bad:
        seen, uniq = set(), []
        for rec in anchor_bad:
            k = (rec[0], rec[2])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(rec)
        print("  ⚠ 「」关键词锚的核心词在目标文件里 grep 不到 %d 处（共查 %d 处）："
              % (len(uniq), n_anch))
        print("      判据＝取锚句的前导核心（第一个分隔符之前）去标点空格后做子串匹配；")
        print("      命中即算可定位。报出来说明目标那节**被改名或整段重写**了，要人工重新指。")
        for rel, i, a, key, tgt in uniq[:20]:
            print("      %s:%d  「%s」 核心=%s → 未在 %s 命中" % (rel, i, a, key, tgt))
    else:
        print("  ✓ 「」关键词锚全部可定位（共查 %d 处；判据＝前导核心词能 grep 到）" % n_anch)
    return len(miss) + len(bad_all), len(anchor_bad) + len(alias_unreg)


# ─────────────────────────────────────────────────────────────
# 2. T1 名词剥离
# ─────────────────────────────────────────────────────────────
def project_codenames():
    out = []
    if not os.path.isdir(PROJ_DIR):
        return out
    for d in sorted(os.listdir(PROJ_DIR)):
        full = os.path.join(PROJ_DIR, d)
        if os.path.isdir(full) and d.startswith("P_"):
            out.append(d[2:])
    return out


def example_rows(text):
    """表头含「例／样例」的表格，其数据行行号 → 这些行里的项目名是举例，记 ○"""
    out = set()
    for hdr, _hln, rows in table_rows(text):
        if any(("例" in h) or ("样例" in h) for h in hdr):
            for ln, _c, _r in rows:
                out.add(ln)
    return out


def check_2_t1(gen_files, codenames):
    print("\n【2】名词剥离自检（T1：通用层里不该出现只有看过那片的人才懂的词）")
    lex = [w for w in (list(T1_NAMES) + list(codenames)) if w]
    lex = sorted(set(lex), key=len, reverse=True)
    print("    词表 %d 词＝显式 %d ＋ 从 30_项目层\\P_* 自动派生 %d 个（%s）"
          % (len(set(lex)), len(set(T1_NAMES)), len(codenames),
             "、".join(codenames) or "无"))
    skip = [os.path.basename(p) for p in gen_files if os.path.basename(p) == REGISTRY]
    if skip:
        print("    ○ 跳过 %s：这份文件的职责就是记录「某项目把某条通用规则收窄成什么具体值」，"
              % "、".join(skip))
        print("      通篇项目名是设计如此，拿 T1 扫它属范畴错误。")
    warn, info = [], []
    for p in gen_files:
        if os.path.basename(p) == REGISTRY:
            continue
        rel = os.path.relpath(p, ROOT)
        text = read(p)
        lines = text.split("\n")
        exrows = example_rows(text)
        for i, line in enumerate(lines, 1):
            hit = [w for w in lex if w in line]
            if not hit:
                continue
            rec = (rel, i, "、".join(sorted(set(hit))), line.strip()[:70])
            ctx = line
            k = i - 2
            while k >= 0 and len([c for c in INFO_CTX if c in ctx]) == 0 and k > i - 2 - INFO_LOOKBACK:
                if lines[k].strip():
                    ctx = lines[k] + " " + ctx
                k -= 1
            if any(c in ctx for c in INFO_CTX) or i in exrows:
                info.append(rec)
            else:
                warn.append(rec)
    print("    命中合计 %d 行：⚠ 规则正文里出现 %d 行 ｜ ○ 有出处/样例/举例列/登记上下文 %d 行"
          % (len(warn) + len(info), len(warn), len(info)))
    if warn:
        print("  ⚠ 需要人判的 %d 行（要么挪去项目层、要么补一句『它是槽的样例』、"
              "要么确认属 §1 两条边界之一）：" % len(warn))
        for rel, i, w, frag in warn[:30]:
            print("      %s:%d  [%s]  %s" % (rel, i, w, frag))
        if len(warn) > 30:
            print("      … 其余 %d 行省略" % (len(warn) - 30))
    else:
        print("  ✓ 通用层规则正文里干净")
    # T1 命中永远是「要人判」，不算硬错：§1 那两条边界（参考机条件、审美口味）
    # 本来就允许通用层出现具体名词，机器分不出来。
    return 0, len(warn)


# ─────────────────────────────────────────────────────────────
# 3. 反向索引完备性
# ─────────────────────────────────────────────────────────────
def gen_entries(gen_files):
    """→ (通用层现有条号集合 {'R4-06',...}, 现有 G 文件号集合 {'G2','G4',...})"""
    entries, files = set(), set()
    for p in gen_files:
        m = re.match(r"^(G\d+)_", os.path.basename(p))
        if m:
            files.add(m.group(1))
        for line in read(p).split("\n"):
            mm = ENTRY_RE.match(line)
            if mm:
                entries.add(mm.group(1))
                files.add(mm.group(1).split("-")[0])
    return entries, files


def check_3_reverse(proj_files, entries, gfiles, registry_text):
    print("\n【3】反向索引完备性（项目层 `上位` ↔ 通用层条号 ↔ 登记表，双向都查）")
    bad_upper, pending, placeholder, unpaired, orphan_reg = [], [], [], [], []
    proj_ids, need_pair = set(), []

    for p in proj_files:
        rel = os.path.relpath(p, ROOT)
        for hdr, _hln, rows in table_rows(read(p)):
            ci, cu, cr = col_of(hdr, "id"), col_of(hdr, "上位"), col_of(hdr, "关系")
            if ci is None:
                continue
            for ln, cells, _raw in rows:
                pid = cells[ci].strip("`* ")
                if pid:
                    proj_ids.add(pid)
                up = cells[cu] if cu is not None and cu < len(cells) else ""
                rl = cells[cr] if cr is not None and cr < len(cells) else ""
                if PLACEHOLDER_RE.search(up):
                    placeholder.append((rel, ln, pid, up[:44]))
                for g, num in UPPER_RE.findall(up):
                    tag = "G%s-%s" % (g, num) if num else "G%s" % g
                    if num:
                        if tag in entries:
                            continue
                        # 整份 G 文件还没成文 ⇒ 是「等出」（索引 §5 批2 清单里已列），
                        # 不是「漂了」。真错是：文件在、条号却不在。
                        if "G%s" % g in gfiles:
                            bad_upper.append((rel, ln, pid, tag))
                        else:
                            pending.append((rel, ln, pid, tag + "（整份 G%s 未成文）" % g))
                    elif tag not in gfiles:
                        pending.append((rel, ln, pid, tag + "（整份文件未成文）"))
                if any(k in rl for k in ("收窄", "例外", REL_CONFLICT)):
                    need_pair.append((rel, ln, pid, rl[:20]))
                    if pid and pid not in registry_text:
                        unpaired.append((rel, ln, pid, rl[:20]))
    for m in re.finditer(r"`?(WZJY-[A-Z0-9]+)`?", registry_text):
        if m.group(1) not in proj_ids:
            orphan_reg.append(m.group(1))

    print("    通用层现有条号 %d 条（%s）；现有 G 文件 %d 份（%s）"
          % (len(entries),
             "、".join(sorted(entries)[:6]) + ("…" if len(entries) > 6 else ""),
             len(gfiles), "、".join(sorted(gfiles))))
    print("    项目层条数 %d ；其中声明了 收窄/例外/冲突 的 %d 条"
          % (len(proj_ids), len(need_pair)))

    if bad_upper:
        print("  !! 上位指向的通用条**在已成文的文件里查不到** %d 处（这才是真漂了）："
              % len(bad_upper))
        for rel, ln, pid, tag in bad_upper[:20]:
            print("      %s:%d  %s → %s" % (rel, ln, pid, tag))
    else:
        print("  ✓ 项目层每条 `上位` 指到的条号，在已成文的 G 文件里都存在")
    if pending:
        print("  ⚠ 上位指向**尚未成文**的通用条 %d 处（不是错，是欠账；**这项校验存在的"
              "全部理由就是防止它被永久遗忘**）：" % len(pending))
        for rel, ln, pid, tag in pending[:20]:
            print("      %s:%d  %s → %s" % (rel, ln, pid, tag))
    if placeholder:
        print("  ⚠ 占位编号（`拟 Gx-xx`）未回填 %d 处：" % len(placeholder))
        for rel, ln, pid, up in placeholder[:15]:
            print("      %s:%d  %s → %s" % (rel, ln, pid, up))
    else:
        print("  ✓ 无占位编号残留")
    if unpaired:
        print("  ⚠ 声明了收窄/例外/冲突但登记表里查不到该项目条 %d 处（登记表 §四.1 要求成对）："
              % len(unpaired))
        for rel, ln, pid, rl in unpaired[:20]:
            print("      %s:%d  %s（关系=%s）" % (rel, ln, pid, rl))
    else:
        print("  ✓ 收窄/例外/冲突 全部在登记表里成对出现")
    orph = sorted(set(orphan_reg))
    if orph:
        print("  ⚠ 登记表点名、但项目层已无此条 %d 个：%s" % (len(orph), "、".join(orph[:15])))
    else:
        print("  ✓ 登记表点名的项目条在项目层都存在")
    return len(bad_upper) + len(unpaired), len(pending) + len(placeholder) + len(orph)


# ─────────────────────────────────────────────────────────────
# 4. 冲突项清点
# ─────────────────────────────────────────────────────────────
def check_4_conflicts(proj_files, registry_text):
    print("\n【4】冲突项清点（索引 §4：`关系=冲突` 的条数必须等于登记表里的未裁项数）")
    n_proj_conf, proj_conf = 0, []
    for p in proj_files:
        rel = os.path.relpath(p, ROOT)
        for hdr, _hln, rows in table_rows(read(p)):
            ci, cr = col_of(hdr, "id"), col_of(hdr, "关系")
            if ci is None or cr is None:
                continue
            for ln, cells, _raw in rows:
                if REL_CONFLICT in cells[cr]:
                    n_proj_conf += 1
                    proj_conf.append((rel, ln, cells[ci].strip("`* ")))
    reg_conf = len(re.findall(r"\|\s*\*{0,2}冲突", registry_text))
    sec2 = ""
    if "## 二、" in registry_text:
        sec2 = registry_text.split("## 二、")[1].split("## 三、")[0]
    unresolved = []
    for hdr, _hln, rows in table_rows(sec2):
        cnum, cst = col_of(hdr, "#"), col_of(hdr, "状态")
        if cnum is None or cst is None:
            continue
        for ln, cells, _raw in rows:
            if any(k in cells[cst] for k in UNRESOLVED):
                unresolved.append((cells[cnum].strip("*` "), cells[cst][:30]))
    print("    项目层 `关系=冲突` 条数             = %d %s"
          % (n_proj_conf,
             ("（%s）" % "、".join(x[2] for x in proj_conf)) if proj_conf else ""))
    print("    登记表 §一 关系列含「冲突」的行数     = %d" % reg_conf)
    print("    登记表 §二 状态为 未裁/未修/未验 的行  = %d" % len(unresolved))
    for num, st in unresolved:
        print("        %-8s %s" % (num, st))
    lhs = n_proj_conf + reg_conf
    if lhs == len(unresolved):
        print("  ✓ 两侧数量相等（%d == %d）" % (lhs, len(unresolved)))
        return 0, 0
    print("  ⚠ 两侧不等：%d（项目层＋登记表§一 的 关系=冲突） vs %d（§二 未决行）"
          % (lhs, len(unresolved)))
    print("     判读：**不一定是错，本脚本不凑数也不假装通过。**")
    print("     §二 队列比「冲突」宽——它还收 `未验`（等实测）与 `未修`（文档自相矛盾），")
    print("     这两类在项目层的 `关系` 列不写「冲突」。索引 §4 那句等式成立的前提是")
    print("     「只有冲突才进队列」，与登记表 §二 现行口径不一致")
    print("     ⇒ **这是一条需要用户裁的口径分歧（裁之前 --strict 会一直红）。**")
    return 1, 0


# ─────────────────────────────────────────────────────────────
# 5. 执行者标记覆盖率（附加项）
# ─────────────────────────────────────────────────────────────
def check_5_executor(gen_files):
    print("\n【5】执行者标记覆盖率（附加项；索引 §2「没标执行者＝视为 [人]＝现在没人管」）")
    total, noexec = 0, []
    for p in gen_files:
        if not re.match(r"^G\d+_", os.path.basename(p)):
            continue
        rel = os.path.relpath(p, ROOT)
        lines = read(p).split("\n")
        cur, start, blocks = None, 0, []
        for i, line in enumerate(lines):
            m = ENTRY_RE.match(line)
            if m:
                if cur:
                    blocks.append((cur, start, i))
                cur, start = m.group(1), i
        if cur:
            blocks.append((cur, start, len(lines)))
        for tag, a, b in blocks:
            total += 1
            if not EXEC_RE.search("\n".join(lines[a:b])):
                noexec.append((rel, tag))
    print("    通用层条目 %d 条，其中整段没出现「执行者」三字 %d 条" % (total, len(noexec)))
    if noexec:
        for rel, tag in noexec:
            print("      ⚠ %s  %s" % (rel, tag))
    else:
        print("  ✓ 每条都写了执行者")
    return 0, len(noexec)


def main(argv):
    strict = "--strict" in argv
    ext_used = "--external" in argv
    as_json = None
    if "--json" in argv:
        as_json = argv[argv.index("--json") + 1]
    t0 = time.time()
    print("=" * 72)
    print("check_layers.py · 两层规则体系自校验（只读、只报不拦）")
    print("手册根：%s" % ROOT)
    print("=" * 72)

    if not os.path.isdir(GEN_DIR):
        print("!! 通用层目录不存在：%s" % GEN_DIR)
        return 1
    gen_files = files_in(GEN_DIR)
    proj_files = files_in(PROJ_DIR)
    print("通用层 %d 份 ｜ 项目层 %d 份 ｜ ALIASES 简写 %d 条"
          % (len(gen_files), len(proj_files), len(ALIASES)))

    mbase, mprefix, mdirs = manual_index()
    ext_idx, ext_n = None, 0
    if ext_used:
        ext_idx, ext_n, trunc = external_index()
        print("外部索引：%d 个文件%s" % (ext_n, "（已截断）" if trunc else ""))
    idx = (mbase, mprefix, mdirs, ext_idx)

    reg_path = os.path.join(GEN_DIR, REGISTRY)
    registry_text = read(reg_path) if os.path.isfile(reg_path) else ""
    if not registry_text:
        print("!! 找不到 %s，第 3/4 项会失真" % REGISTRY)

    entries, gfiles = gen_entries(gen_files)
    codenames = project_codenames()

    res, h, w = {}, 0, 0
    for key, fn in (("1_pointers", lambda: check_1_pointers(gen_files, idx, ext_used)),
                    ("2_t1", lambda: check_2_t1(gen_files, codenames)),
                    ("3_reverse", lambda: check_3_reverse(proj_files, entries, gfiles,
                                                          registry_text)),
                    ("4_conflicts", lambda: check_4_conflicts(proj_files, registry_text)),
                    ("5_executor", lambda: check_5_executor(gen_files))):
        a, b = fn()
        res[key] = {"hard": a, "human": b}
        h += a
        w += b

    res.update({"gen_files": len(gen_files), "proj_files": len(proj_files),
                "entries": len(entries), "gfiles": sorted(gfiles),
                "aliases": len(ALIASES), "external": ext_used,
                "seconds": round(time.time() - t0, 1)})
    print("\n" + "=" * 72)
    print("合计：!!/⚠ 硬项 %d 处 ｜ 待人判 %d 处 ｜ 耗时 %.1fs" % (h, w, time.time() - t0))
    code = 0 if not strict else (1 if (h or w) else 0)
    print("本脚本只报不拦：退出码 %d%s" % (code, "" if not strict else "（--strict）"))
    print("=" * 72)
    if as_json:
        with io.open(as_json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("（--json 是唯一的写盘动作，且只写你指定的这个路径：%s）" % as_json)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
