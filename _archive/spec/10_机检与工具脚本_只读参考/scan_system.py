# -*- coding: utf-8 -*-
"""scan_system.py —— 「若水AI电影」七层架构的**只读**扫盘器。

干什么：把七层的现状从盘上量出来，写成 `system_manifest.json`。
不干什么：不改任何配置、不跑任何生成、不动任何资产。
         全文只有一处 open(..., "w")：写 manifest 本身（落点可用 --out 覆盖，--print 则不落盘）。
⚠ 唯一的例外（10-02 加）：为了把"测试有多少项"量准，会跑一次
   `pytest tests --collect-only -q -p no:cacheprovider`——**只收集、一条都不执行**，
   不发网络、不碰显存、不留 `.pytest_cache`。不想跑就 `--no-collect`，那条数字会老实写「未测量」。

────────────────────────────────────────────────────────────────────────────
为什么要有它（元规则 M1 的机器化）

  M1：所有顶层规则修改必须有**事实证据**支撑。
  证据不能是 agent 嘴报的数字，必须是盘上**可复跑**的量。
  所以本脚本立三条硬约束，违反即等于把 manifest 变成第二个漂移真源：

  1. **源码里不许出现写死的计数。** 每一个数字都在运行时算。
     静态的只有「路径」和「判据阈值」——路径是位置不是测量，阈值是口径不是结论。
  2. **每一条 gap 必须自带证据。** `evidence` = 真实存在的路径（支撑这个判断的依据），
     `missing` = 该有却没有的路径（缺口本身）。两者分开，不许混。
     脚本会自己复核 `evidence` 里的路径是否还在；不在就把该 gap 标 `evidence_broken: true`
     ——**宁可报出自己证据不全，也不许把推测写成事实。**
  3. **量不到就写"未测量"，不许沿用旧数字。** 例如某个目录已经不存在了，
     就如实记 `exists: false`，而不是照抄上一版方案里它的体积。

确定性自证（批 0 验收口径）：
  连跑两次，除 `generated` 一个字段外必须逐字相同。
  为此：所有来自 os.walk / listdir 的列表一律 sorted()；
  时间只输出到日（%Y-%m-%d），不输出时间戳；不读任何随机源。

判读约定（沿用 check_layers.py）：
  severity: high = 会让人按错的口径干活 ／ mid = 会漏 ／ low = 记账用
  needs_user_ruling: true = 这条要用户裁，agent 不得自裁（如 D7 那类）
────────────────────────────────────────────────────────────────────────────
用法：
    py -3.12 E:\\若水AI电影\\99_维护\\scan_system.py
    py -3.12 E:\\若水AI电影\\99_维护\\scan_system.py --out D:\\tmp\\m.json
    py -3.12 E:\\若水AI电影\\99_维护\\scan_system.py --print      # 只打印不落盘
    py -3.12 E:\\若水AI电影\\99_维护\\scan_system.py --no-hash    # 跳过 md5 比对（更快）
    py -3.12 E:\\若水AI电影\\99_维护\\scan_system.py --diff       # 与即将被覆盖的那份对账
    py -3.12 E:\\若水AI电影\\99_维护\\scan_system.py --diff D:\\tmp\\old.json

`--diff` 是**建议每次都用**的：它打印「哪些数字变了、哪些 gap 开了／关了／改级别了」。
理由＝10-02 总纲 v1.0→v1.5 五个版本里有**三次**是在修我上一版写进去的假数字，
说明重扫本身不产生价值，**重扫＋和上一版对账才产生价值**。
diff 只打印到控制台、**不写进 manifest**（写进去就永远不可能"连跑两次逐字相同"）。
⚠ 两轮量测条件不同（`--no-hash`／`--no-collect`）时它会先吼一句，因为那种情况下
gap 的"关闭"是旗标造成的假象（首跑就当场演了一次：`--no-hash` 让 GAP-A5 假关闭）。
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

VERSION = "1.0"

# ─────────────────────────────────────────────────────────────
# 路径常量：**这些是位置，不是测量值**。盘上没有就如实记 exists:false。
# ─────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
SYS_ROOT = os.path.dirname(HERE)                       # E:\若水AI电影
DEFAULT_OUT = os.path.join(SYS_ROOT, "system_manifest.json")

P = {
    "manual":        r"E:\本地工作流规范手册",
    "gen":           r"E:\本地工作流规范手册\20_通用规范层",
    "proj":          r"E:\本地工作流规范手册\30_项目层",
    "index_doc":     r"E:\本地工作流规范手册\20_通用规范层\20_索引与分类判据.md",
    "registry_doc":  r"E:\本地工作流规范手册\20_通用规范层\R_作用域与例外登记表.md",
    "conflict_doc":  r"E:\本地工作流规范手册\00_读我\版本裁定与冲突表.md",
    "build_manual":  r"E:\本地工作流规范手册\99_维护\build_manual.py",
    "check_layers":  r"E:\本地工作流规范手册\99_维护\check_layers.py",
    "check_tables":  r"E:\本地工作流规范手册\99_维护\check_tables.py",

    "engine":        r"D:\AIWorkflow\engine",
    "config":        r"D:\AIWorkflow\engine\config.yaml",
    "workflows":     r"D:\AIWorkflow\engine\workflows",
    "tests":         r"D:\AIWorkflow\engine\tests",
    "run_py":        r"D:\AIWorkflow\engine\run.py",
    "tasks_py":      r"D:\AIWorkflow\engine\tasks.py",
    "preflight":     r"D:\AIWorkflow\tools\check_preflight.py",
    "tools":         r"D:\AIWorkflow\tools",
    # ★10-02 批 4·2：通道与配置的**唯一声明源**。本扫描器原来自带一份 CHANNELS 常量，
    #   那是 channel_of() 之外的第三份抄本（同 GAP-A1 那种病）⇒ 现在改成读这个文件，
    #   读不到才退回 CHANNELS 兜底，并**如实报一条 high**（兜底清单≠现役配置）。
    "channels_registry": r"D:\AIWorkflow\engine\channels_registry.json",
    "check_registry":  r"D:\AIWorkflow\tools\check_registry.py",
    "check_thresholds": r"D:\AIWorkflow\tools\check_thresholds.py",
    "thresholds_registry": r"D:\AIWorkflow\engine\thresholds_registry.json",
    "channels":      r"D:\AIWorkflow\ComfyUI_H3",
    "h3_output":     r"D:\AIWorkflow\ComfyUI_H3\output",
    "knobs":         r"D:\AIWorkflow\tmp\wzy\h3\knobs.json",

    "assets":        r"E:\创作",
    "char_lib":      r"E:\创作\通用角色库",
    "char_manifest": r"E:\创作\通用角色库\MANIFEST.json",
    "char_manifest_md": r"E:\创作\通用角色库\MANIFEST.md",
    "pool":          r"E:\创作\项目资源池",
    "archive":       r"E:\创作\_归档",
    "lora":          r"E:\创作\训练素材\LoRA产物",

    "mem_user":      r"C:\Users\若水\.qoder\memory",
    "mem_proj":      r"C:\Users\若水\.qoder\projects\C--Users----Documents-Qoder-2026-09-27-aed216e7\memory",
    "mem_public":    r"E:\公共记忆",
    "skills":        r"C:\Users\若水\.qoder\skills",
    "skill_refs":    r"C:\Users\若水\.qoder\skills\cinematic-video-production\references",
    # ⚠ 记忆件里记的**实测发得出去的那一份**在 `node_modules` 底下（qoder 插件的 npm 布局），
    #   而 `.hub\runtimes\` 那份是另一套安装。两份都在，谁在 PATH 都不在 ⇒ 封装脚本必须锁死全路径。
    "lark_cli":      r"C:\Users\若水\.local\share\qoder\lark-cli\node_modules\@larksuite\cli\bin\lark-cli.exe",
    "lark_cli_alt":  r"C:\Users\若水\.hub\runtimes\lark-cli\lark-cli.exe",

    "review_local":  r"D:\AIWorkflow\public\review",
    "review_publish": r"D:\AIWorkflow\tools\review_publish.py",
    "feishu_send":   r"D:\AIWorkflow\tools\feishu_send.py",
    "sync_skill":    r"D:\AIWorkflow\tools\sync_skill.py",
}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "venv", ".venv", ".thumbs",
             "custom_nodes", "site-packages", ".idea", "dist", "build",
             "$RECYCLE.BIN", "System Volume Information"}
# 找 lark-cli 时**不能跳 node_modules**：本机实测发得出去的那一份就躺在
# `.local\share\qoder\lark-cli\node_modules\@larksuite\cli\bin\` 底下。
# 用通用 SKIP_DIRS 扫会把真身漏掉、只报出 `.hub\runtimes` 那一份（首跑就漏了，故单列）。
LARK_SKIP_DIRS = SKIP_DIRS - {"node_modules", "site-packages"}
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
TEXT_EXTS = (".md", ".py", ".txt", ".yaml", ".yml", ".json", ".csv")

# 判据阈值（口径，不是结论）
THIN_SOURCE_RATIO = 0.35      # 某通道真源体积 < 同类最厚的这个比例 ⇒ 判"过薄"
HASH_CAP = 40                 # 一次扫描最多算多少个 md5（防跑飞）
HASH_MAX_BYTES = 60 * 1024 * 1024
DEADLINK_SCAN_CAP = 8000      # 死链扫描最多读多少个文本文件
# ⚠ 10-02 判废区合并后从 4000 提到 8000：`_归档` 本来就在死链作用域里，
#   并进来 235 件（含一批 .md/.py）⇒ 扫描**撞到 4000 上限静默截断**了。
#   截断本身有字段（`truncated`），但只躺在 measured 里没人看 ⇒ 现在同时进正文（见 GAP-A6）。
#   这不是"把上限调大就完事"：调大之后仍可能再撞，所以**必须让撞顶这件事在报告里喊出来**。

# ─────────────────────────────────────────────────────────────
# 小工具
# ─────────────────────────────────────────────────────────────
_CACHE = {}


def read(path):
    if path in _CACHE:
        return _CACHE[path]
    try:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            t = f.read()
    except OSError:
        t = None
    _CACHE[path] = t
    return t


def ex(p):
    return bool(p) and os.path.exists(p)


def isfile(p):
    return bool(p) and os.path.isfile(p)


def isdir(p):
    return bool(p) and os.path.isdir(p)


def nb(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return None


def nl(p):
    t = read(p)
    return None if t is None else t.count("\n") + (0 if t.endswith("\n") else 1)


def mday(p):
    try:
        return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
    except OSError:
        return None


def newest_day(root, exts=None):
    """目录树里最新的 mtime（只到日）。root 不存在 ⇒ None。"""
    best = None
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for f in fn:
            if exts and not f.lower().endswith(exts):
                continue
            d = mday(os.path.join(dp, f))
            if d and (best is None or d > best):
                best = d
    return best


def walk_stats(root, img_exts=IMG_EXTS):
    """一次性量：文件总数、图片数、文本数、按扩展名计数、体积、一级子目录数。

    ⚠ 目录不存在时也**必须返回同一套键**（10-02 批3.4 撞出来的）：原来这里
    `if not out["exists"]: return out` 早退，而 `gib` 与排好序的 `by_ext` 是在函数
    **末尾**才加的 ⇒ 拿一个不存在的根进来，调用方读 `s["gib"]` 直接 KeyError。
    平时不炸是因为所有根都在；把 `项目资源池` 并进 `_归档` 删掉老根的那一刻，
    读它的第一个消费者就崩了。**"目录消失了"恰恰是最需要被量一次并如实记 0 的场景**，
    早退还少键＝把一个正常状态变成一次崩溃。
    """
    out = {"exists": isdir(root), "files": 0, "images": 0, "text": 0,
           "bytes": 0, "top_dirs": 0, "by_ext": {}, "gib": 0.0}
    if not out["exists"]:
        return out
    for e in sorted(os.listdir(root)):
        if os.path.isdir(os.path.join(root, e)) and e not in SKIP_DIRS:
            out["top_dirs"] += 1
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for f in fn:
            fp = os.path.join(dp, f)
            e = os.path.splitext(f)[1].lower()
            out["files"] += 1
            out["by_ext"][e] = out["by_ext"].get(e, 0) + 1
            if e in img_exts:
                out["images"] += 1
            if e in TEXT_EXTS:
                out["text"] += 1
            try:
                out["bytes"] += os.path.getsize(fp)
            except OSError:
                pass
    out["by_ext"] = dict(sorted(out["by_ext"].items(), key=lambda x: (-x[1], x[0]))[:12])
    out["gib"] = round(out["bytes"] / 1024.0 ** 3, 2)
    return out


def mib(b):
    return None if b is None else round(b / 1024.0 ** 2, 2)


def _short(p):
    """`E:\\创作\\仙女星系战争项目\\舰体设计` → `仙女星系战争项目\\舰体设计`
    同名目录靠父目录才分得开，只印 basename 会把两组不同的复制报成一样。"""
    parts = (p or "").replace("/", "\\").split("\\")
    return "\\".join(parts[-2:]) if len(parts) >= 2 else p


def grep(pattern, path, flags=0):
    """返回 [(lineno, text)]，最多 200 条。文件读不到 ⇒ []。"""
    t = read(path)
    if t is None:
        return []
    rx = re.compile(pattern, flags)
    return [(i, ln.rstrip()) for i, ln in enumerate(t.split("\n"), 1) if rx.search(ln)][:200]


def grep_count(pattern, path, flags=0):
    return len(grep(pattern, path, flags))


def yaml_scalar(text, key):
    """从 yaml 文本里抠 `key: value` 的标量值（不引 PyYAML，避免依赖）。取第一处命中。"""
    if not text:
        return None
    m = re.search(r"^\s*%s\s*:\s*(.+?)\s*(?:#.*)?$" % re.escape(key), text, re.M)
    if not m:
        return None
    v = m.group(1).strip().strip("'\"")
    return v or None


def yaml_scalar_line(text, key):
    if not text:
        return None
    m = re.search(r"^\s*%s\s*:\s*(.+?)\s*(?:#.*)?$" % re.escape(key), text, re.M)
    return text[:m.start()].count("\n") + 1 if m else None


def yaml_in_section(text, section, key):
    """在**指定顶层段内**取 `key: value`，返回 (value, lineno)。

    ⚠ 为什么不能用 yaml_scalar 取第一处命中：config.yaml 里 `base_url` 出现 3 次
    —— `models.cloud`(L9)、`models.dashscope`(L16)、`comfyui`(L29)。首跑按"第一处"
    取到的是 token-plan 那个云端 LLM 端点，而这一栏要报的是 ComfyUI 生产实例(8189)。
    取错栏位＝把事实写错，比不写更坏，所以按段取。
    """
    if not text:
        return None, None
    m = re.search(r"^%s\s*:\s*(?:#.*)?$" % re.escape(section), text, re.M)
    if not m:
        return None, None
    start = m.end()
    m2 = re.search(r"^[A-Za-z_]", text[start:], re.M)      # 下一个顶层键＝本段结束
    body = text[start:start + m2.start()] if m2 else text[start:]
    mk = re.search(r"^\s+%s\s*:\s*(.+?)\s*(?:#.*)?$" % re.escape(key), body, re.M)
    if not mk:
        return None, None
    v = mk.group(1).strip().strip("'\"")
    return (v or None), text[:start + mk.start()].count("\n") + 1


def func_body(src, name):
    """抠出顶层函数 `def name(` 的整段源码（到下一个顶层 def/class 或文件尾）。"""
    if not src:
        return ""
    m = re.search(r"^def %s\(" % re.escape(name), src, re.M)
    if not m:
        return ""
    rest = src[m.end():]
    m2 = re.search(r"^(?:def |class |@)", rest, re.M)
    return rest[:m2.start()] if m2 else rest


def str_literals(code):
    return sorted(set(re.findall(r"""["']([^"'\n]{1,40})["']""", code or "")))


GAPS = []


def gap(gid, layer, what, evidence=(), missing=(), measured=None,
        severity="mid", ruling=False, note=None):
    """登记一条缺口。evidence 必须是**存在**的路径；missing 必须是**不存在**的路径。
    脚本自己复核，复核不过就标 evidence_broken —— 不掩盖自己的证据问题。"""
    ev = [e for e in evidence]
    ms = [m for m in missing]
    broken = [e for e in ev if not ex(e)]
    notmissing = [m for m in ms if ex(m)]
    g = {"id": gid, "layer": layer, "what": what,
         "evidence": sorted(ev), "missing": sorted(ms),
         "measured": measured or {}, "severity": severity,
         "needs_user_ruling": bool(ruling)}
    if broken:
        g["evidence_broken"] = sorted(broken)
    if notmissing:
        g["missing_but_found"] = sorted(notmissing)
    if note:
        g["note"] = note
    GAPS.append(g)
    return g


# ─────────────────────────────────────────────────────────────
# 层 1：规则层
# ─────────────────────────────────────────────────────────────
# 10-03 批 7-3：通用层文件前缀换成 `R`（`R5_关口与授权.md`／条目 `R5-07`）。
# `G` 一并认——历史引语与在审文档里还写旧名，只认 R 会把"其实存在"报成"没成文"（假阴）。
ENTRY_RE = re.compile(r"^##\s+([GR]\d+-\d+)\s", re.M)
EXEC_RE = re.compile(r"执行者")


def scan_rules():
    root, gen, proj = P["manual"], P["gen"], P["proj"]
    man = walk_stats(root)
    gen_files = sorted(f for f in os.listdir(gen)) if isdir(gen) else []
    g_md = sorted(f for f in gen_files if re.match(r"^[GR]\d+_", f))
    entries, per_file = set(), {}
    for f in gen_files:
        t = read(os.path.join(gen, f)) or ""
        ids = ENTRY_RE.findall(t)
        per_file[f] = len(ids)
        entries.update(ids)
    no_exec = 0
    for f in g_md:
        t = read(os.path.join(gen, f)) or ""
        for m in re.finditer(r"^##\s+[GR]\d+-\d+\s.*?(?=^##\s|\Z)", t, re.M | re.S):
            if not EXEC_RE.search(m.group(0)):
                no_exec += 1
    proj_dirs = sorted(d for d in os.listdir(proj)
                       if isdir(os.path.join(proj, d))) if isdir(proj) else []

    # 冲突表：C 编号 + 风险编号。
    # ⚠ 风险编号是**跳号**的（实测只有 16/21/22/23/28/29/30 被点名），最大号 30 ≠ 有 30 条风险。
    #   所以两个数分开报，并且把实际命中的编号列出来，避免"风险 30"被读成条数。
    ct = read(P["conflict_doc"]) or ""
    c_ids = sorted({int(x) for x in re.findall(r"\bC(\d{1,3})\b", ct)})
    # ⚠ 不能写 `\b风险`：汉字在 Unicode 下算 word char，`见风险28` 这种紧贴写法 `\b` 不成立，
    #   会漏号（首跑漏了 1 个，报 6 实际 7）。风险编号本身够独特，不需要词边界。
    risk_ids = sorted({int(x) for x in re.findall(r"风险\s*(\d{1,3})", ct)})

    # 索引 §5 计划了哪些规则文件（现行 R1–R10；10-03 之前叫 G1–G10），实际成文了几份。
    # ⚠ 比的是**数字**，不是整串。上一版的写法是"两边都拼成 G<n> 再比"，
    #   改名之后那正好变成假阴：计划表里拼成 `G2`、盘上文件名算出 `R2`，两边永不相等
    #   ⇒ 已成的文件会全量报成"未成文"。所以这里只取数字，字母两边各留原样用于显示。
    idx = read(P["index_doc"]) or ""
    # 一个号只算一次：改名期间索引里可能同时出现 `G3_….md`（历史句）与 `R3_….md`（清单行），
    # 按 (字母, 号) 去重会把 3 数成两份 ⇒ 以号为准、字母优先取现行的 R。
    by_num = {}
    for g, n in re.findall(r"\b([GR])(\d{1,2})_[^\s|`]*\.md", idx):
        n = int(n)
        if n not in by_num or g == "R":
            by_num[n] = g
    planned_nums = sorted(by_num)
    planned = ["%s%d" % (by_num[n], n) for n in planned_nums]
    written_nums = sorted({int(re.match(r"^[GR](\d+)_", f).group(1)) for f in g_md})
    written = ["R%d" % n for n in written_nums]
    not_written = ["R%d" % n for n in planned_nums if n not in written_nums]

    d = {
        "root": root, "exists": isdir(root),
        "files_total": man["files"], "md_files": man["by_ext"].get(".md", 0),
        "gib": man["gib"],
        "general_layer": {
            "path": gen, "files": gen_files, "file_count": len(gen_files),
            "rule_files": g_md, "rule_file_count": len(g_md),
            "entries_total": len(entries),
            "entries_per_file": dict(sorted(per_file.items())),
            "entries_without_executor": no_exec,
            "planned_in_index": planned,
            "written": written,
            "not_written": not_written,
        },
        "project_layer": {"path": proj, "project_dirs": proj_dirs,
                          "count": len(proj_dirs),
                          "index_doc": os.path.join(proj, "30_项目索引.md"),
                          "index_doc_exists": isfile(os.path.join(proj, "30_项目索引.md"))},
        "conflict_table": {"path": P["conflict_doc"], "exists": isfile(P["conflict_doc"]),
                           "c_ids_max": max(c_ids) if c_ids else 0,
                           "c_ids_count": len(c_ids),
                           "risk_ids_max": max(risk_ids) if risk_ids else 0,
                           "risk_ids_count": len(risk_ids),
                           "risk_ids": risk_ids,
                           "risk_note": "风险编号跳号；risk_ids_max 是编号上限，不是条数，"
                                        "条数看 risk_ids_count"},
        "validators": [
            {"name": os.path.basename(P[k]), "path": P[k], "exists": isfile(P[k]),
             "lines": nl(P[k]) if isfile(P[k]) else None}
            # ★10-02 批 4·2 加第四个校验器：`check_registry.py`（通道与配置注册表自校验）。
            #   前三个查的是"手册内部自洽"，这一个查"声明／代码／yaml 三方一致"，是不同一面。
            for k in ("build_manual", "check_layers", "check_tables", "check_registry")
        ],
    }

    # GAP：索引 §5 计划的规则文件（R1–R10，10-03 前叫 G1–G10）大部分未成文
    if not_written:
        gap("GAP-R1", "rules",
            "索引 §5 计划了 %d 份通用层文件（%s），实际只成文 %d 份（%s）；"
            "未成文的 %s 一旦被人当已生效规则引用，引到的是空气"
            % (len(planned), "、".join(planned), len(written), "、".join(written) or "无",
               "、".join(not_written)),
            evidence=[P["index_doc"], gen],
            measured={"planned": planned, "written": written, "not_written": not_written,
                      "entries_total": len(entries),
                      "entries_without_executor": no_exec},
            severity="mid")


    # GAP：build_manual --check 恒 return 0（stale 无法机器判定）
    bm = read(P["build_manual"]) or ""
    if bm:
        has_strict = "--strict" in bm
        # ⚠ 判据修过一次：原来找的是「某个 def *check* 里有 return 1」，
        #   而 10-02 加的 --strict 把 return 1 写在 main() 的 check 分支里
        #   ⇒ 老判据会一直报 `check_can_return_nonzero: False`，把已闭的缺口显示成半闭。
        #   改成数**非零返回点的个数**并明说这是"存在性"粗判，不判它接在哪个分支上。
        ret1_sites = len(re.findall(r"^\s*return\s+[1-9]\d*\s*$", bm, re.M))
        gates = has_strict and ret1_sites > 0
        d["build_manual_check"] = {
            "has_strict_flag": has_strict,
            "nonzero_return_sites": ret1_sites,
            "strict_gates_nonzero": gates,
            "probe_note": "存在性粗判：只数「有 --strict」＋「文件里有几处非零 return」，"
                          "不判它接在哪个分支。实际拦截行为另测：把某个副本改脏 → "
                          "`--check --strict` 退出码应为 1、不带 `--strict` 应为 0（10-02 两向都验过）"}
        if not gates:
            gap("GAP-R2", "rules",
                "`build_manual.py --check` 恒返回 0：副本落后只能人读文本，机器判不了"
                " ⇒ 收尾三件套的「复验」这一步实际没有闸门"
                "（实测：有 `--strict` 旗标 %s、非零 return 点 %d 处）" % (has_strict, ret1_sites),
                evidence=[P["build_manual"]],
                measured=dict(d["build_manual_check"],
                              lines=nl(P["build_manual"])),
                severity="mid")
    return d


# ─────────────────────────────────────────────────────────────
# 层 2：通道层
# ─────────────────────────────────────────────────────────────
# 五条通道。declared_kind = 该通道的 yaml/CLI 要写进 prompt_kind 的那个词。
# rule_source = 该通道自己的"工作流规则级"真源文件（位置，不是测量）。
CHANNELS = [
    {"id": "h3_local", "name": "本地 MiniMax H3",
     "rule_source": r"D:\AIWorkflow\ComfyUI_H3\H3提示词工程规则方案.md",
     "extra_sources": [r"D:\AIWorkflow\ComfyUI_H3\H3提示词规则_现行合并版.md",
                       r"D:\AIWorkflow\ComfyUI_H3\规则对比_官方写法_vs_项目规则.md"],
     "declared_kind": ["h3", "h3_i2va", "h3_ref2va", "h3_skeleton"],
     "engine_yaml_glob": "h3_*.yaml"},
    {"id": "cloud_sd", "name": "云端 SD / Seedream（ark）",
     "rule_source": r"D:\AIWorkflow\ComfyUI_H3\云端SD提示词模板_十块.md",
     "extra_sources": [],
     "declared_kind": ["cloud", "sd", "ark"],
     "engine_yaml_glob": None},
    {"id": "image_chain", "name": "本地图片链（i2i/inpaint/outpaint/depth）",
     "rule_source": r"D:\AIWorkflow\ComfyUI_H3\图片链_工作流规则.md",
     "extra_sources": [],
     "declared_kind": ["image", "i2i", "img"],
     "engine_yaml_glob": "image_*.yaml"},
    {"id": "qianwen", "name": "千问云端",
     "rule_source": r"D:\AIWorkflow\ComfyUI_H3\千问云端_工作流规则.md",
     "extra_sources": [],
     "declared_kind": ["qianwen", "qwen", "bailian"],
     "engine_yaml_glob": None},
    {"id": "jimeng", "name": "即梦云端",
     "rule_source": r"D:\AIWorkflow\ComfyUI_H3\即梦云端_工作流规则.md",
     "extra_sources": [],
     "declared_kind": ["jimeng", "dreamina", "seedance"],
     "engine_yaml_glob": None},
]


def _channel_kind_sets(body):
    """只取 channel_of 里那几条 `if k in (...)` 的成员，**不刮全文字符串字面量**。

    踩过的坑：原来用 `str_literals(body)`，于是我 10-02 写在 docstring 里的
    `channel_of('qianwen'|'qwen'|'bailian', 'local') -> h3` 这种举例句，
    被当成代码字面量 ⇒ 千问"忽然被机器认得了"，`machine_recognized` 从 4 条变 5 条，
    GAP-C2 也被连带判没。**解释性文字污染了测量**，这是 M1 要防的那类假事实。
    """
    sets = []
    for m in re.finditer(r"if\s+k\s+in\s+\(([^)]*)\)", body):
        sets.append({x.strip().strip('"\'').lower() for x in m.group(1).split(",") if x.strip()})
    return sets


def load_channels_registry(path):
    """读通道注册表（批 4·2 起的唯一声明源）。返回 (记录 or None, 原因)。

    ⚠ 只读**声明**，不在这里算任何数：文件里出现"多少条／多大／哪天门"一律当噪声，
    因为本文件的纪律是"位置与决定归注册表，测量归扫描器"。
    """
    if not isfile(path):
        return None, "文件不存在"
    try:
        d = json.loads(read(path))
    except Exception as e:
        return None, "json 解析失败：%s" % e
    chans = d.get("channels")
    if not isinstance(chans, list) or not chans:
        return None, "channels 段缺失或为空"
    need = ("id", "declared_kind", "rule_source")
    bad = [c.get("id") for c in chans if not all(k in c for k in need)]
    if bad:
        return None, "有条目缺必需字段（id／declared_kind／rule_source）：%s" % "、".join(map(str, bad))
    return d, None


def run_channel_probe(timeout=40):
    """跑 `check_registry.py --print-json`，拿**行为层**的通道现状。

    为什么不在这里自己刮源码：批 4·2b 之后 `channel_of()` 的词表来自注册表，
    函数体里的 `if k in (...)` 字面量元组已经没了 ⇒ 正则刮到空集，
    会把"机器认得 20 个词"误报成"一个都不认"（假阴比假阳坏，而且报出去没人会怀疑）。
    探针只此一份实现，本扫描器是它的**消费者**，不是第二个实现者。
    → (data|None, 错误说明|None)
    """
    if not isfile(P["check_registry"]):
        return None, "找不到 `%s`" % P["check_registry"]
    try:
        # ⚠ Windows 上 `text=True` 默认按 locale（本机 cp936/gbk）解码，而探针输出是 UTF-8 中文 json
        #   ⇒ 首跑直接 UnicodeDecodeError。两边都要钉 UTF-8：子进程侧用 PYTHONIOENCODING，
        #     父进程侧用 encoding=。只钉一边仍然会炸。
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, P["check_registry"], "--print-json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
    except Exception as e:
        return None, "探针启动失败：%s" % e
    try:
        j = json.loads(p.stdout)
    except Exception as e:
        return None, "探针输出不是 json（退出码 %s）：%s；stdout 尾 %r" % (p.returncode, e, p.stdout[-160:])
    return j, None


def run_threshold_probe(timeout=40):
    """跑第五件校验器 `check_thresholds.py --print-json`，拿**它自己算出来**的结果。

    为什么又走子进程而不是在这儿重读一遍注册表：读法（py_const／regex／dict_entry…）
    已经实现过一次，再实现一遍就是第二个漂移真源——本项目为这四个字翻过三次车。
    """
    if not isfile(P["check_thresholds"]):
        return None, "第五件校验器不在盘上：%s ⇒ 阈值这一层**未测量**" % P["check_thresholds"]
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, P["check_thresholds"], "--print-json"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
    except Exception as e:
        return None, "探针启动失败：%s" % e
    try:
        return json.loads(p.stdout), None
    except Exception as e:
        return None, "探针输出不是 json（退出码 %s）：%s；stdout 尾 %r" % (
            p.returncode, e, (p.stdout or "")[-160:])


def run_sync_probe(timeout=90):
    """跑 `tools/sync_skill.py --json`，拿**它自己算出来**的三轴结果。

    存在的理由（10-03 接线）：「skill 落后几天」这件事以前有两处算法——这里按目录全扫取最新日，
    那边按通道清单取 mtime。同一句话两个真源，引用的人不知道信谁（本轮真撞见过 9 天 vs 9.9 天）。
    规矩沿用 `channel_of()` 那次：**探针拿得到就以它为准**，拿不到才退回本地算法并且**如实标 fallback**。
    """
    script = P.get("sync_skill")
    if not script or not isfile(script):
        return None, "三轴检查器不在盘上：%s ⇒ skill 这一层按兜底算法报" % script
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, script, "--json"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except Exception as e:
        return None, "探针启动失败：%s: %s" % (type(e).__name__, e)
    try:
        return json.loads(p.stdout), None
    except Exception as e:
        return None, "探针输出不是 json（退出码 %s）：%s；stdout 尾 %r" % (
            p.returncode, e, (p.stdout or "")[-160:])


def scan_channels(pf_src):
    body = func_body(pf_src, "channel_of")
    kind_sets = _channel_kind_sets(body)          # 旧的结构刮法，现在只当"结构面备注"
    probe, probe_err = run_channel_probe()
    pdata = ((probe or {}).get("data")) or {}
    # 通道 id → 探针里那条通道实际路由到的词集
    CH_OF_CODE_NAME = {"image": "image_chain", "h3": "h3_local", "cloud": "cloud_sd"}
    active_by_id = {}
    for code_name, ws in (pdata.get("active_kinds") or {}).items():
        cid = CH_OF_CODE_NAME.get(code_name)
        if cid:
            active_by_id[cid] = {str(w).lower() for w in ws}
    probe_ok = bool(pdata.get("probe_ran")) and active_by_id
    lits = sorted({w for ws in active_by_id.values() for w in ws}) if probe_ok else []
    if not probe_ok:
        # 探针没跑成 ⇒ **不能**当成"机器一个词都不认"。写未测量，并让 GAP-S3 报出来。
        lits = None
    returns = sorted(set(re.findall(r'return\s+"([^"]+)"', body)))
    # 兜底判定改成看**最后一条 return**是不是"我不知道"记号：
    # 原来只看有没有 `return "cloud" if ... else "h3"` 这句话在，拆完兜底后它还在、
    # 但已被 `if k in ("", "video")` 关进合法泛称分支，不再是无条件的了。
    tail = [l for l in body.split("\n") if re.match(r"^\s{4}return\b", l)]
    last_return = tail[-1].strip() if tail else ""
    has_silent_fallback = bool(last_return) and "未裁" not in last_return \
        and "UNADJUDICATED" not in last_return
    unadjudicated_supported = ("未裁" in body) or ("UNADJUDICATED" in body)
    ch_dir = P["channels"]
    all_md = sorted(f for f in os.listdir(ch_dir)
                    if f.lower().endswith(".md")) if isdir(ch_dir) else []

    # ★ 通道清单从**注册表**读；读不到才退回本文件的 CHANNELS 兜底常量。
    #   兜底不是无害的：它会让"注册表坏了"这件事以"一切正常"的样子继续跑（兜底清单≠现役配置），
    #   所以 provenance 一定要落到 manifest 里，并且 registry_broken 单独报一条 high。
    regfile, reg_why = load_channels_registry(P["channels_registry"])
    chan_list = regfile["channels"] if regfile else CHANNELS
    alias_words = (regfile or {}).get("code_alias_words") or []
    reg_meta = {
        "path": P["channels_registry"],
        "exists": isfile(P["channels_registry"]),
        "loaded": bool(regfile),
        "load_error": None if regfile else reg_why,
        "provenance": "channels_registry.json" if regfile else "scan_system.CHANNELS（兜底常量）",
        "schema_version": (regfile or {}).get("schema_version"),
        "declared_updated": (regfile or {}).get("updated"),
        "channel_count": len(chan_list),
        "channel_count_from_registry": len((regfile or {}).get("channels") or []),
        "switches_declared": len((regfile or {}).get("config_switches") or []),
        "kind_conflicts": [k.get("kind") for k in ((regfile or {}).get("kind_conflicts") or [])],
        "alias_words_total": len(alias_words),
        "alias_words_unadjudicated": sorted(a.get("word") for a in alias_words
                                            if a.get("adjudicated") is not True),
        "channels_adjudicated": sorted(c["id"] for c in chan_list if c.get("adjudicated")),
        "channels_not_adjudicated": sorted(c["id"] for c in chan_list
                                           if c.get("adjudicated") is not True),
        "run_slots_declared": sorted(k for k in ((regfile or {}).get("run_slots") or {})
                                     if isinstance((regfile or {}).get("run_slots", {}).get(k), list)
                                     and not k.startswith("_")),
        "run_slots_total": sum(len(v) for k, v in ((regfile or {}).get("run_slots") or {}).items()
                               if isinstance(v, list) and not k.startswith("_")),
        "channel_of_is_still_authority": (
            (probe or {}).get("data", {}).get("authority_source") != "channels_registry"),
        "authority_note": "★批 4·2b 起这个值**由探针派生**，不再写死。"
                          "true＝`channel_of()` 没在用注册表（降级运行，权威仍在代码兜底）；"
                          "false＝路由规则已由注册表决定，代码里的 `_KIND_*` 只是与它相等的兜底字面量。"
                          "原来这里写死 `true` 是防我虚报「已迁移」，迁移做完了它还写死 true 就变成反向虚报。",
    }

    # ── 决定单层（批 5-2）：「值归人」那一层的现状 ──────────────────────
    # ⚠ 本扫描器**不自己拼决定单路径、不自己数槽**：拼法只住在 engine/decision_sheet.py，
    #   槽表只住在 channels_registry —— 两边都由 `check_registry.py --print-json` 黑盒带回来。
    #   在这里再实现一遍就是第二个漂移真源（GAP-E1 那半条、交付根那半条都是这么烂的）。
    dsprobe = pdata.get("decision_sheet_probe") or {}
    ds_mod = os.path.join(P["engine"], "decision_sheet.py")
    pj_path = os.path.join(P["engine"], "projects_registry.json")
    assembled = dsprobe.get("assembled") or {}
    decision_meta = {
        "module": ds_mod, "module_exists": isfile(ds_mod),
        "projects_registry": pj_path, "projects_registry_exists": isfile(pj_path),
        "creation_root_from_config": dsprobe.get("creation_root"),
        "creation_root_source": dsprobe.get("root_source"),
        # 两根同名不同源：config 的 paths.creation_root 与本扫描器的 P["assets"]
        # 一旦分叉，「决定单在哪」和「资产扫在哪」就不是同一个盘 ⇒ 这里比一下。
        "scanner_assets_root": P["assets"],
        "roots_equal": dsprobe.get("creation_root") == P["assets"],
        "placement_declared": dsprobe.get("placement_declared"),
        "assembled": assembled,
        "sheets_present": sorted(k for k, v in assembled.items() if (v or {}).get("exists")),
        "sheets_missing": sorted(k for k, v in assembled.items()
                                 if not (v or {}).get("exists")),
        "sheets_all_slots_human": sorted(
            k for k, v in assembled.items()
            if (v or {}).get("exists") and
            set((v or {}).get("project_slots") or []) <= set((v or {}).get("human_filled") or [])),
        "g13_all_flows": pdata.get("g13_all"),
        "g13_partial_flows": pdata.get("g13_partial"),
        "g13_none_flows": pdata.get("g13_none"),
        "probe_missing": not dsprobe,
        "note": "这几项是**现状**不是判据：判据住在 engine/tests/test_run_decisions.py 与手册 G5。"
                "G13 只查留痕（有没有人给过），永不查值（值好不好看是人的活，机器在那一维是瞎的）。",
    }

    reg, unrecog, thin = [], [], []
    by_design, branch_undeclared = [], []
    gating_pending = []   # 已裁身份但**判据未立**的通道（declared_kind 为空）
    totals = []
    for c in chan_list:
        rs = c["rule_source"]
        b = nb(rs) if isfile(rs) else None
        extra = [{"path": x, "exists": isfile(x), "bytes": nb(x) if isfile(x) else None}
                 for x in (c.get("extra_sources") or [])]
        # 厚薄比的是「这条通道的真源一共有多厚」，不是单份文件 —— 只比主文件会把
        # H3 的三份拆开算，得出偏小的倍数。口径写在字段名里，免得下一个读的人误比。
        total = (b or 0) + sum(e["bytes"] or 0 for e in extra)
        totals.append(total)
        if probe_ok:
            mine = active_by_id.get(c["id"]) or set()
            rec = sorted(k for k in (c.get("declared_kind") or []) if str(k).lower() in mine)
        else:
            rec = None
        eng_yaml = []
        if c.get("engine_yaml_glob") and isdir(P["workflows"]):
            pat = c["engine_yaml_glob"].replace("*", ".*")
            eng_yaml = sorted(f for f in os.listdir(P["workflows"]) if re.match(pat, f))
        # ⚠ 两种数法，别混（10-02「批 1 余下」写图片链真源时抓出来的）：
        #   glob 数法 ＝ 文件名以 `image_` 开头的（"这条通道自己的流"）；
        #   声明数法 ＝ yaml 里 `prompt_kind` 落在本通道 declared_kind 里的
        #               （"会被 `channel_of()` 判成本通道、因而吃这条通道判据的流"）。
        #   实测两者**不等**：`previz_control`／`character_sheet`／`auto_draft` 也声明
        #   `prompt_kind: image`（glob 数不到），而 `image_refine` 在 glob 里却没声明 prompt_kind。
        #   只报 glob ⇒ 少算 3 份、多算 1 份，正是"兜底清单≠现役配置"那一族。
        #   判据生效范围看**声明数法**；两个数都留着，差集单独出字段，不藏。
        by_kind = []
        if isdir(P["workflows"]):
            kinds_lc = {k.lower() for k in c["declared_kind"]}
            for f in sorted(os.listdir(P["workflows"])):
                if f.lower().endswith((".yaml", ".yml")):
                    v = yaml_scalar(read(os.path.join(P["workflows"], f)) or "", "prompt_kind")
                    if v and str(v).strip().lower() in kinds_lc:
                        by_kind.append(f)
        e = {"id": c["id"], "name": c.get("name") or c["id"],
             "adjudicated": c.get("adjudicated") is True,
             "machine_gated_declared": c.get("machine_gated") is True,
             "provider_required_in_yaml": c.get("provider_required_in_yaml") is True,
             "prompt_format": c.get("prompt_format"),
             "adjudication_pending": c.get("adjudication_pending"),
             "rule_source": rs, "rule_source_exists": isfile(rs),
             "rule_source_bytes": b,
             "rule_source_kib": None if b is None else round(b / 1024.0, 1),
             "rule_source_mtime": mday(rs),
             "extra_sources": extra,
             "total_source_bytes": total or None,
             "total_source_kib": round(total / 1024.0, 1) if total else None,
             "declared_kind": c["declared_kind"],
             "kind_recognized_by_channel_of": rec,
             "machine_recognized": (None if rec is None else bool(rec)),
             "engine_yaml_count": len(eng_yaml),
             "engine_yaml": eng_yaml,
             "engine_yaml_by_prompt_kind": by_kind,
             "engine_yaml_by_prompt_kind_count": len(by_kind),
             "engine_yaml_only_in_glob": sorted(set(eng_yaml) - set(by_kind)),
             "engine_yaml_only_in_kind": sorted(set(by_kind) - set(eng_yaml)),
             "engine_yaml_counting_note":
                 "engine_yaml*＝按文件名 glob（通道自己的流）；engine_yaml_by_prompt_kind＝按 yaml "
                 "声明的 prompt_kind（会被 channel_of() 判成本通道、真吃这条通道判据的流）。"
                 "判据生效范围看后者；两者不等不是矛盾，是两种口径，差集见 only_in_* 两栏"}
        reg.append(e)
        if probe_ok and not (c.get("declared_kind") or []):
            # 没有可路由的词 ≠ 词不被认：这是**身份已裁、判据未落地**，另列一批，
            # 绝不混进 unrecog（那会把它误报成"待用户裁"，而它等的是实测与路由改动）。
            gating_pending.append(c["id"])
        elif probe_ok and not rec:
            # 「该有 channel_of 分支却不认」才是待裁缺口；
            # 「裁定为不进机检」（即梦／C82）不算漏，别把它重新列成待裁事项问用户。
            if c.get("needs_channel_of_branch") is True:
                unrecog.append(c["id"])
            elif c.get("needs_channel_of_branch") is False:
                by_design.append(c["id"])
            else:
                # 没声明该不该有分支 ⇒ 判不了，如实记下，不当"没问题"也不当"有问题"
                branch_undeclared.append(c["id"])
        if not isfile(rs):
            thin.append((c["id"], "主真源文件不存在（零真源，只有记忆件）"))
    thick = max(totals) if totals else 0
    thin_ratio = None
    for e in reg:
        tb = e["total_source_bytes"]
        if tb and thick and tb < thick * THIN_SOURCE_RATIO:
            why = "真源合计 %.1f KiB ＜ 最厚那条 %.1f KiB 的 %d%%" % (
                tb / 1024.0, thick / 1024.0, int(THIN_SOURCE_RATIO * 100))
            thin.append((e["id"], why))
        e["thin_verdict"] = next((w for cid, w in thin if cid == e["id"]), None)
    if thin and thick and min(t for t in totals if t):
        thin_ratio = round(thick / min(t for t in totals if t), 1)

    h3_out = walk_stats(P["h3_output"]) if isdir(P["h3_output"]) else {"files": 0, "exists": False}

    d = {"rule_source_dir": ch_dir, "md_files_in_dir": all_md,
         "md_count": len(all_md), "registry": reg,
         "channels_registry": reg_meta,
         "decision_layer": decision_meta,
         "channel_of": {"defined_in": P["preflight"],
                        "line": (grep(r"^def channel_of\(", P["preflight"]) or [(None,)])[0][0],
                        "returns": returns,
                        "recognized_kinds": lits,
                        "recognized_kind_count": (None if lits is None else len(lits)),
                        "routing_authority": pdata.get("authority_source"),
                        "routing_authority_reason": pdata.get("authority_reason"),
                        "fallback_equals_registry": pdata.get("fallback_literals_equal"),
                        "registry_schema_version": pdata.get("schema_version"),
                        "probe_ran": bool(probe_ok),
                        "probe_error": probe_err,
                        "not_gated_by_design": sorted(by_design),
                        "gating_pending": sorted(gating_pending),
                        "branch_need_undeclared": sorted(branch_undeclared),
                        "struct_kinds_via_regex": sorted({k for s in kind_sets for k in s}),
                        "probe_note": "★批 4·2b：主判据换成**黑盒探针**（跑 `check_registry.py --print-json`）。"
                                      "旧的正则刮 `if k in (...)` 元组在迁移后会刮到空集——"
                                      "词表已住进注册表，函数体里没有元组了，刮法会把"
                                      "『机器认得 20 个词』误报成『一个都不认』。刮法结果保留在"
                                      "`struct_kinds_via_regex` 里当结构面备注，不再充当判据。"
                                      "上一版另有一条教训：刮全文会把我写在 docstring 里的举例句当代码。",
                        "has_silent_fallback": has_silent_fallback,
                        "unadjudicated_supported": unadjudicated_supported,
                        "last_return": last_return},
         "h3_output": {"path": P["h3_output"], "exists": h3_out.get("exists", False),
                       "files": h3_out.get("files", 0)}}

    if thin:
        gap("GAP-C1", "channels",
            "%d 条通道的真源厚薄差 %s 倍（口径＝每条通道全部真源文件字节数之和）：%s"
            % (len(chan_list), thin_ratio or "无法计算（有的通道零真源）",
               "；".join("%s → %s" % (cid, why) for cid, why in thin)),
            evidence=[c["rule_source"] for c in chan_list if isfile(c["rule_source"])] + [ch_dir],
            missing=[c["rule_source"] for c in chan_list if not isfile(c["rule_source"])],
            measured={"thickest_total_bytes": thick, "thickness_ratio": thin_ratio,
                      "per_channel_total_bytes": {e["id"]: e["total_source_bytes"] for e in reg},
                      "per_channel_main_bytes": {e["id"]: e["rule_source_bytes"] for e in reg},
                      "thin": [{"id": cid, "why": why} for cid, why in thin]},
            severity="high",
            note="零真源那条（图片链）是第一优先：它已经在跑，规则却只存在于记忆件里")
    if unrecog:
        gap("GAP-C2", "channels",
            "`channel_of()` 的登记表里没有这些通道声明的 kind 词：%s ⇒ 它们的稿子**现在**会走"
            "`未裁` 分支（G7 格式判定整段不执行、只留一条 warn 等人工放行），"
            "不再被假装成 h3/cloud 用错判据审了。但**通道本身仍未裁定**：这些通道等于"
            "没有机器质检，只有人工一条路。"
            % ("、".join("%s（声明 kind：%s）"
                         % (cid, "/".join(next(c["declared_kind"] for c in chan_list
                                               if c["id"] == cid)))
                         for cid in unrecog)),
            evidence=[P["preflight"]],
            measured={"unrecognized": unrecog, "recognized_kinds": lits,
                      "not_gated_by_design": sorted(by_design),
                      "branch_need_undeclared": sorted(branch_undeclared),
                      "returns": returns, "has_silent_fallback": has_silent_fallback,
                      "unadjudicated_supported": unadjudicated_supported,
                      "channel_of_line": d["channel_of"]["line"]},
            severity="mid" if unadjudicated_supported and not has_silent_fallback else "high",
            ruling=True,
            note="D7 已裁「暂时不改」⇒ 本条只登记不裁语义。10-02 批1 把危险的静默兜底换成显式"
                 "`未裁`（GAP-C3 已闭），所以危害从『审错了还显示 ✓』降到『没有机器质检、要人工过』，"
                 "severity 随之从 high 降 mid —— **这个降级是代码现状决定的，不是我把口径调松**")
    if has_silent_fallback:
        gap("GAP-C3", "channels",
            "`channel_of()` 最后一条 return 仍是无条件的：%s ⇒ 未知通道不会报错，"
            "会被**假装**归成 h3/cloud ⇒ 判据错配且无痕迹" % last_return,
            evidence=[P["preflight"]],
            measured={"line": d["channel_of"]["line"], "returns": returns,
                      "last_return": last_return},
            severity="high")
    # ★ 批 4·2 新开的两条：注册表本身坏了 / 注册表盖不住代码认识的门词
    if regfile is None:
        gap("GAP-S2", "cross_layer",
            "**通道注册表读不到**（%s）⇒ 本次扫描的通道清单来自 `scan_system.py` 自带的 "
            "CHANNELS 兜底常量，不是现役声明源。兜底能跑出数，但那数**不代表系统现状**"
            "（兜底清单≠现役配置，这一族已经咬过多次）" % reg_why,
            evidence=[P["engine"], P["preflight"]],
            missing=[P["channels_registry"]],
            measured=reg_meta, severity="high")
    else:
        reg_words = {k.lower() for c in chan_list for k in (c.get("declared_kind") or [])}
        alias_map = {str(a.get("word", "")).lower(): a for a in alias_words}
        reg_words |= set(alias_map)
        # 探针没跑成时 `lits` 是 None：这里**不能**当空集算——空集会得出"没有任何词未登记"，
        # 也就是把"没量到"报成"没问题"（假阴）。改成显式跳过并另开 GAP-S3。
        not_declared = sorted(set(lits) - reg_words - {"", "video"}) if lits else []
        unadj_alias = reg_meta["alias_words_unadjudicated"]
        if not_declared or unadj_alias:
            gap("GAP-C4", "channels",
                "注册表与 `channel_of()` 的门词表**没对齐**：%s"
                % "＋".join(x for x in [
                    ("%d 个代码认识的词没有任何登记（%s）⇒ 这些词的稿子被归进某通道，"
                     "但那条通道从未声明收它" % (len(not_declared), "、".join(not_declared))
                     if not_declared else ""),
                    ("%d 个词登记成别名却**从没裁过通道归属**（%s）⇒ 它们的稿子现在吃的是"
                     "**所折入通道**的判据（`kling`／`vidu` 吃云端SD 中文十块；"
                     "`hailuo` 与本地 H3 同源但契约不同，最容易被读错）"
                     % (len(unadj_alias), "、".join(unadj_alias)) if unadj_alias else ""),
                ] if x),
                evidence=[P["channels_registry"], P["preflight"], P["check_registry"]],
                measured={"code_kinds_not_declared": not_declared,
                          "alias_words_unadjudicated": unadj_alias,
                          "kind_conflicts": reg_meta["kind_conflicts"]},
                severity="mid",
                note="本条**不替用户裁**：修法只有两种——给它们立自己的通道＋判据，"
                     "或明确裁「共用现有通道」。两者都要先有实测，不能由注册表单方面宣布。")
    # ★ 探针本身的状态：没跑成＝未测量（报出去，别让它沉默）；跑了但没在用注册表＝降级运行。
    if not probe_ok:
        gap("GAP-S3", "cross_layer",
            "通道路由探针**没跑成**（%s）⇒ 本轮 `recognized_kinds` 是 `null`（未测量），不是「零」。"
            "GAP-C2／GAP-C4 因此本轮没有判据基础，**别把它们没出现读成问题消失了**"
            % (probe_err or "探针返回空词表"),
            evidence=[P["check_registry"], P["preflight"]],
            measured={"probe_error": probe_err, "probe_data_keys": sorted(pdata.keys()),
                      "struct_kinds_via_regex": sorted({k for s in kind_sets for k in s})},
            severity="high")
    if gating_pending:
        gap("GAP-C5", "channels",
            "已裁身份但**判据未落地**的通道 %d 条（%s）：注册表里 declared_kind 为空、"
            "真源 md 已建档但通篇 [未实测]，词表现仍挂在 cloud_sd 别名上按云端SD 判据审。"
            "⇒ 三条独立通道**只建成了一半**（身份＋真源位置）；"
            "剩下那半是「先真机实测拿到契约 → 再改路由」，"
            "而改路由属动现役判据链：必须先钉基线（pytest 用例数**现测**，本文件不抄计数／"
            "verify_g7／prompt_gate 逐字比对），"
            "还要先设计 G7 对新通道名的分支归属（现行代码对未知通道会落到按 fmt 选判据的通用路径，"
            "顺手改会静默改变「混用记 error 还是 warn」「器材禁词只对 h3 生效」两处行为）"
            % (len(gating_pending), "、".join(sorted(gating_pending))),
            evidence=[P["channels_registry"], P["preflight"],
                      os.path.join(P["channels"], "可灵云端_工作流规则.md")],
            measured={"gating_pending": sorted(gating_pending),
                      "still_routed_via_alias": ["kling", "vidu", "hailuo"]},
            severity="mid",
            note="2026-10-02 用户裁定「三个都立独立通道」⇒ 本条不是待裁，是**待实施**（批 4·5）。")
    elif pdata.get("authority_source") != "channels_registry":
        gap("GAP-S3", "cross_layer",
            "`channel_of()` 本次**没在用注册表**（source=%s；%s）⇒ 注册表是权威这句话此刻不成立，"
            "属降级运行：判定与迁移前逐字一致，但表里的声明没生效。"
            "且 `fallback_equals_registry`＝%s——为假时退回兜底会**静默改变路由**"
            % (pdata.get("authority_source"), pdata.get("authority_reason"),
               pdata.get("fallback_literals_equal")),
            evidence=[P["channels_registry"], P["preflight"]],
            measured={k: pdata.get(k) for k in ("authority_source", "authority_reason",
                                                "fallback_literals_equal",
                                                "code_words_not_registered")},
            severity="mid" if pdata.get("fallback_literals_equal") else "high")
    # GAP-E5：决定单这一层的**结构**是否完好（只查结构，永不判值——值归人，见 G13 与 tests）
    ds_bad = []
    if not decision_meta["module_exists"]:
        ds_bad.append("engine/decision_sheet.py 不在盘上 ⇒ 决定单没有取法，G13 只能报错")
    if decision_meta["probe_missing"]:
        ds_bad.append("探针没带回 decision_sheet_probe ⇒ 本层**未测量**（不是「没问题」）")
    if decision_meta["creation_root_from_config"] and not decision_meta["roots_equal"]:
        ds_bad.append("config 的 paths.creation_root（%s）与扫描器扫资产的根（%s）不是同一根 ⇒ "
                      "「决定单在哪」和「资产在哪」会各说各话"
                      % (decision_meta["creation_root_from_config"],
                         decision_meta["scanner_assets_root"]))
    if ds_bad:
        gap("GAP-E5", "engine",
            "运行决定单这一层结构不合：" + "；".join(ds_bad),
            evidence=[decision_meta["module"], decision_meta["projects_registry"],
                      P["config"], P["check_registry"]],
            measured=decision_meta, severity="high")
    return d


# ─────────────────────────────────────────────────────────────
# 层 3：引擎层
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# 测试数：两种单位，别拿一种去比另一种
# ─────────────────────────────────────────────────────────────
PYTEST_PROBE = True          # --no-collect 关掉


def pytest_case_count(engine_root, tests_rel="tests"):
    """跑 `pytest --collect-only` 数**用例条数**（只收集、一条都不执行）。

    为什么要它：`def test_` 的个数 ≠ 用例数——一个 `@parametrize` 会一对多展开。
    本函数就是为这件事加的：10-02 第一版把「注释自称 107 项」跟「74 个 `def test_`」
    直接对比报了 GAP-E3，那是**单位错配**（注释用的是用例单位）。
    收集不执行：不发网络、不碰显存、不跑生成。`-p no:cacheprovider` 免得留 `.pytest_cache`。
    失败不猜数：拿不到就返回 None，让上层写「未测量」。"""
    if not PYTEST_PROBE:
        return None, "已用 --no-collect 跳过 ⇒ 未测量"
    if not isdir(os.path.join(engine_root, tests_rel)):
        return None, "tests 目录不存在 ⇒ 未测量"
    cmd = [sys.executable, "-m", "pytest", tests_rel, "--collect-only", "-q",
           "-p", "no:cacheprovider"]
    try:
        r = subprocess.run(cmd, cwd=engine_root, capture_output=True, timeout=240)
    except Exception as e:
        return None, "collect 跑不起来（%s）⇒ 未测量" % type(e).__name__
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    if not m:
        return None, "collect 输出里没有「N tests collected」⇒ 未测量"
    n_err = re.search(r"(\d+)\s+errors?\s+collected", out)
    return int(m.group(1)), ("现算（只收集未执行）" if not n_err
                             else "现算，但 collect 有 %s 个 error ⇒ 该数偏小" % n_err.group(1))


QC_NAME_PAT = None  # 延迟编译，见 qc_wiring_scan()


def qc_wiring_scan():
    """量「名字像机检裁判的脚本」到底有没有调用点——为 GAP-G3 服务。

    为什么值得单独量：这套框架栽过两次"写了没接线"（9-14 那十个裁判件、批1 之前三条出图链没闸）。
    裁判件没接线比没裁判件更危险：**文档会写"已有机检"，而它一次也没执行过**。
    口径要如实窄：这里只看**文件名有没有出现在调用面**（引擎三个入口＋config＋全部 workflow＋
    D:/AIWorkflow 下两层内的 .bat／.ps1），不看语义、不判"该不该接"——该不该接归人（G6 未成文就是这条）。
    """
    global QC_NAME_PAT
    if QC_NAME_PAT is None:
        QC_NAME_PAT = re.compile(
            r"(qc|judge|referee|score|verify|audit|drift|diversity|review|best_of|"
            r"consistency|continuity)", re.I)
    callers = [P["tasks_py"], P["run_py"], os.path.join(P["engine"], "webui.py"),
               P["config"], P["preflight"]]
    blob_parts = [read(c) or "" for c in callers]
    for f in (sorted(os.listdir(P["workflows"])) if isdir(P["workflows"]) else []):
        if f.lower().endswith((".yaml", ".yml")):
            blob_parts.append(read(os.path.join(P["workflows"], f)) or "")
    scripts = []
    for root, dirs, fs in os.walk(P["engine"].replace("\\engine", "") or "."):
        if root.count(os.sep) - P["engine"].count(os.sep) > 2:
            dirs[:] = []
            continue
        for f in fs:
            if f.lower().endswith((".bat", ".ps1")):
                scripts.append(os.path.join(root, f))
    for s in scripts[:120]:
        blob_parts.append(read(s) or "")
    blob = "\n".join(blob_parts)
    # 判"常量有没有被用"不能拿上面那份 blob——它**含 check_preflight 自己**，
    # 每个常量至少在自己文件里出现一次，那样查出来永远是空表（第一版就是这么错的）。
    ext_blob = "\n".join(read(c) or "" for c in callers if c != P["preflight"])
    tools_dir = P["tools"]
    cands, unreferenced = [], []
    for f in sorted(os.listdir(tools_dir)) if isdir(tools_dir) else []:
        if not f.lower().endswith(".py"):
            continue
        if not QC_NAME_PAT.search(f):
            continue
        stem = os.path.splitext(f)[0]
        hit = stem in blob
        cands.append(f)
        if not hit:
            unreferenced.append(f)
    # 那把标定过的主尺住在 tmp 里，且默认解释器跑不起来（缺 lpips）——两件事都量，不写死结论
    ruler = os.path.join(P["tmp_wzy"] if "tmp_wzy" in P else r"D:\AIWorkflow\tmp\wzy", "qc.py")
    env = {"ruler_path": ruler, "ruler_exists": isfile(ruler),
           "default_python_has_lpips": False,
           "probe_error": None}
    try:
        p = subprocess.run([sys.executable, "-c", "import lpips"],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        env["default_python_has_lpips"] = (p.returncode == 0)
    except Exception as e:
        env["probe_error"] = "%s: %s" % (type(e).__name__, e)
    # 「声明了却没人用」的常量：这类东西最会骗人——表上写着限 10 个，实际一次也没查过。
    # 口径放窄：只查 preflight 顶层全大写常量，且**在代码里只出现 1 次**（＝只有声明那一次）
    # 并且在调用面里也不出现，才算未使用。宁可漏报也不误报（误报多了这条就没人看了）。
    # ⚠ 计数必须先去掉注释！本仓第一次跑这条就报了空表——因为我刚给 `ARK_LIMIT_AUDIOS`
    #   写了三行解释性注释，把"只出现一次"变成了"出现四次"。**给探针写的说明文字会污染探针**
    #   （同族旧教训：刮字面量的尺子会被注释里的举例句骗到）。这里用 tokenize 精确去注释。
    pf_src = read(P["preflight"]) or ""
    code_only = pf_src
    try:
        import tokenize as _tk
        lines = pf_src.split("\n")
        for t in _tk.generate_tokens(io.StringIO(pf_src).readline):
            if t.type == _tk.COMMENT:
                lines[t.start[0] - 1] = lines[t.start[0] - 1][:t.start[1]]
        code_only = "\n".join(lines)
    except Exception:
        code_only = "\n".join(l.split("#")[0] for l in pf_src.split("\n"))
    unused_consts = []
    for m in re.finditer(r"^([A-Z][A-Z0-9_]{2,}(?:\s*,\s*[A-Z][A-Z0-9_]{2,})*)\s*=", code_only, re.M):
        for nm in [x.strip() for x in m.group(1).split(",")]:
            if code_only.count(nm) == 1 and nm not in ext_blob:
                unused_consts.append(nm)
    # ── 10-03 批 7-4：被裁"可以接进引擎"的那把相对尺，接没接、跑不跑得起 ──
    # 口径与上面一致：**只量存在与可调用**，不在这跑真图（跑一次要载 DINO＋人脸检测，
    # 扫描器是 5 秒级的只读体检，不能变成分钟级；那把尺在真产物上的读数交给批次自己留痕）。
    wired = {"script": os.path.join(tools_dir, "qc_batch_consistency.py"),
             "exists": isfile(os.path.join(tools_dir, "qc_batch_consistency.py")),
             "importable": None, "empty_list_verdict": None,
             "thresholds": None, "probe_error": None,
             "wired_in_tasks_py": "qc_batch_consistency" in (read(P["tasks_py"]) or "")}
    if wired["exists"]:
        try:
            code = ("import sys,json;sys.path.insert(0,%r);"
                    "import qc_batch_consistency as N;"
                    "print(json.dumps({'v':N.measure([]).get('verdict'),"
                    "'t':[N.DINO_BATCH_MIN_FAIL_LO,N.DINO_BATCH_MEAN_WARN_LO]},"
                    "ensure_ascii=False))" % tools_dir)
            pr = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                timeout=90, encoding="utf-8", errors="replace")
            if pr.returncode == 0 and pr.stdout.strip():
                got = json.loads(pr.stdout.strip().splitlines()[-1])
                wired["importable"] = True
                wired["empty_list_verdict"] = got.get("v")
                wired["thresholds"] = got.get("t")
            else:
                wired["importable"] = False
                wired["probe_error"] = (pr.stderr or "")[-200:]
        except Exception as e:
            wired["importable"] = False
            wired["probe_error"] = "%s: %s" % (type(e).__name__, e)
    return {"candidates": cands, "candidate_count": len(cands),
            "unreferenced": unreferenced, "unreferenced_count": len(unreferenced),
            "declared_only_constants": sorted(set(unused_consts)),
            "call_surfaces": [os.path.basename(c) for c in callers]
                             + ["workflows/*.yaml", "bat|ps1×%d" % len(scripts)],
            "ruler_env": env, "wired_ruler": wired,
            "note": "口径＝文件名有没有出现在调用面；「该不该接」是判据问题，归未成文的 G6 与本次预量报告"}


def scan_engine():
    cfg_txt = read(P["config"]) or ""
    wf_dir = P["workflows"]
    wfs = sorted(f for f in os.listdir(wf_dir) if f.lower().endswith((".yaml", ".yml"))) \
        if isdir(wf_dir) else []
    with_kind, without_kind, kinds = [], [], {}
    for f in wfs:
        t = read(os.path.join(wf_dir, f)) or ""
        v = yaml_scalar(t, "prompt_kind")
        if v:
            with_kind.append(f)
            kinds[v] = kinds.get(v, 0) + 1
        else:
            without_kind.append(f)
    with_provider = [f for f in wfs
                     if re.search(r"^\s*provider\s*:", read(os.path.join(wf_dir, f)) or "", re.M)]

    # 润色这个**运行决定**在现役流里有几个键名？（10-02 决定单落地时才查出来的命名分叉）
    # 两个都真在用 ⇒ 决定单只能两个都认；统一成一个要动现役流＋webui 白名单＋测试＝改行为，等裁。
    polish_by_name = {}
    for nm in ("use_llm_polish", "use_llm"):
        # ⚠ 正则必须带冒号紧跟：`use_llm` 若写成前缀匹配会把 `use_llm_polish:` 也吞进来，
        #   那样"两个名字"会数成"一个名字用了 5 份"——假阴，比假阳坏。
        hits = [f for f in wfs
                if re.search(r"^\s*%s\s*:" % nm, read(os.path.join(wf_dir, f)) or "", re.M)]
        if hits:
            polish_by_name[nm] = sorted(hits)

    # 每份 yaml 到底有没有「会真跑 G 闸」的步（= 带 auto_gates 的 gate 步）。
    # 只看有没有 `task: gate` 不够：人工关口步也叫 gate，但它不跑机械判据。
    # 这是 10-02 批1 补 gate 那件事的账：以前三条会实际出图的链一个机械闸都没有，
    # 提示词从没经过 G 闸就直接出图，而 manifest 里完全看不出来（它只数 prompt_kind）。
    gated, ungated = [], []
    for f in sorted(wfs):
        t = read(os.path.join(wf_dir, f)) or ""
        # 本文件不引 yaml 解析器（yaml_scalar 那套是手写的，保持一致），
        # 这里只需要两个存在性判断，正则够了。
        has_auto = bool(re.search(r"^\s*auto_gates\s*:", t, re.M))
        # ⚠ 步骤行在 yaml 里是**列表项**（`  - task: comfyui`），前面有 `- `。
        #   写 `^\s*task:` 一条都配不上 ⇒ ungated_producing 恒空、GAP-E4 静默不报，
        #   这正是"漏报比误报更难发现"的形态，所以 `-` 必须允许。
        STEP = r"^\s*(?:-\s+)?task:\s*(%s)\b"
        produces = bool(re.search(STEP % "comfyui|control|video|refine|h3_movie|auto|sheets",
                                  t, re.M))
        gate_tasks = len(re.findall(STEP % "gate", t, re.M))
        (gated if has_auto else ungated).append(
            {"file": f, "produces_media": produces, "gate_step_count": gate_tasks})
    ungated_producing = [x["file"] for x in ungated if x["produces_media"]]

    tests = []
    if isdir(P["tests"]):
        for f in sorted(os.listdir(P["tests"])):
            if f.endswith(".py"):
                t = read(os.path.join(P["tests"], f)) or ""
                tests.append({"file": f, "def_test": len(re.findall(r"^\s*def test_", t, re.M))})
    def_test_total = sum(x["def_test"] for x in tests)
    cases, cases_note = pytest_case_count(P["engine"])

    # config.yaml 注释里自称的测试数（"NNN 项"）。
    # ⚠ 这条判据收紧过两次，两次都是同一类自我污染：
    #   全文 grep 会把后来追加的**勘误文字里复述的旧数**（「108 项」「114 项」）
    #   当成新断言收走 ⇒ GAP-E3 永远闭不掉。
    #   ⇒ 现在只认「本行自己宣称测试通过」的行，并沿用 GAP-R3 那套
    #     「往下看几行有没有勘误／更正」的判据——被勘误追认过的历史断言不再算现行断言。
    cfg_lines0 = cfg_txt.split("\n")
    claim = []
    for i, ln in enumerate(cfg_lines0):
        if "全过" not in ln and "通过" not in ln:
            continue
        tail = "\n".join(cfg_lines0[i + 1:i + 1 + ANNOT_TAIL_LINES])
        if any(k in ln or k in tail for k in ANNOT_WORDS):
            continue                       # 已被勘误追认，只当历史
        claim += re.findall(r"(\d{2,4})\s*项", ln)

    project = yaml_scalar(cfg_txt, "project")
    output_root = yaml_scalar(cfg_txt, "output_root")
    pool_root = yaml_scalar(cfg_txt, "pool_root")
    d = {
        "root": P["engine"], "exists": isdir(P["engine"]),
        "config": {"path": P["config"], "exists": isfile(P["config"]),
                   "lines": nl(P["config"]),
                   "project": project,
                   "project_line": yaml_scalar_line(cfg_txt, "project"),
                   "output_root": output_root,
                   "output_root_line": yaml_scalar_line(cfg_txt, "output_root"),
                   "pool_root": pool_root,
                   "preflight": yaml_scalar(cfg_txt, "preflight"),
                   "preflight_line": yaml_scalar_line(cfg_txt, "preflight"),
                   "preflight_strict": yaml_scalar(cfg_txt, "preflight_strict"),
                   "base_url": yaml_in_section(cfg_txt, "comfyui", "base_url")[0],
                   "base_url_line": yaml_in_section(cfg_txt, "comfyui", "base_url")[1],
                   "base_url_note": "按 `comfyui:` 段取。config.yaml 里 base_url 出现 3 次"
                                    "（models.cloud / models.dashscope / comfyui），"
                                    "取第一处会拿到云端 LLM 端点而不是生产实例",
                   "fallback_chain": yaml_scalar(cfg_txt, "fallback_chain"),
                   "characters_needing_anchor": yaml_scalar(cfg_txt, "characters_needing_anchor"),
                   "characters_needing_anchor_line": yaml_scalar_line(cfg_txt, "characters_needing_anchor"),
                   "tests_claim_in_comments": sorted(set(claim))},
        "code_size": [{"file": os.path.basename(P[k]), "path": P[k],
                       "exists": isfile(P[k]), "lines": nl(P[k])}
                      for k in ("run_py", "tasks_py", "preflight")],
        "workflows": {"dir": wf_dir, "total": len(wfs), "files": wfs,
                      "with_prompt_kind": len(with_kind),
                      "without_prompt_kind": without_kind,
                      "prompt_kind_values": dict(sorted(kinds.items())),
                      "with_provider": len(with_provider),
                      "without_provider": sorted(set(wfs) - set(with_provider)),
                      "with_auto_gate": len(gated),
                      "without_auto_gate": sorted(x["file"] for x in ungated),
                      "ungated_but_produce_media": sorted(ungated_producing),
                      # 润色这个决定的现役参数名分叉（GAP-E6 的事实面，别名已登记在表里）
                      "polish_decision_param_names": polish_by_name},
        "tests": {"dir": P["tests"], "exists": isdir(P["tests"]),
                  "def_test_total": def_test_total, "per_file": tests,
                  "collected_cases": cases, "collected_cases_note": cases_note,
                  "run_pass_count": None,
                  "unit_note": "三种单位别混：`def_test_total` 是函数定义数；"
                               "`collected_cases` 是 pytest 收集到的用例数（`@parametrize` 一对多展开）；"
                               "`run_pass_count` 是实跑通过数，本脚本**不执行测试**所以量不到，"
                               "恒为 null ⇒ 要这个数得单独跑回归（见 99_维护\\README.md）。"
                               "config.yaml 注释里的「NNN 项」是**用例**单位，"
                               "所以比对只能用 collected_cases，不能用 def_test_total（10-02 就错过一次）。",
                  "collected_is_upper_bound": (cases is not None)},
    }

    # 10-02 批1：交付根的「两套取法」已收成一处（engine\delivery_root.py），
    # webui／迁移脚本都改吃它，并有用例钉住字面量不漂 ⇒ 剩下的只有"当前项目被钉在唯一真源里"这半条。
    dr = P.get("delivery_root") or (os.path.join(P["engine"], "delivery_root.py"))
    single_source = isfile(dr)
    webui_patched = False
    wtxt = read(os.path.join(P["engine"], "webui.py")) or ""
    if wtxt:
        # ⚠ 判据必须**跳过注释行**：webui 里留了一句解释"以前这里直接 Path(CFG[\"output_root\"])"的注释，
        #   整串 grep 会把这句历史说明当成还在直读字面量 ⇒ 假阳性。
        #   真正的判据是"没有**可执行行**再直接取那个键"。
        code = "\n".join(l for l in wtxt.split("\n") if not l.lstrip().startswith("#"))
        webui_patched = ("delivery_root" in code) and \
                        not re.search(r"Path\(CFG\[.output_root.\]\)", code)
    if project and project not in ("_default", "default", ""):
        # ★ 批 4·3 更正本条的**前提**：原来写「换项目要动真源，正是 T3 点名的病」——
        #   这句被实测推翻。`run.py:493` 有 `--project` 旗标，帮助文本自己写着
        #   「换项目用这个，别改 config 路径」⇒ config 里那个标量只是**默认值**，不是唯一入口。
        #   真正的洞是另一件事：**「存在哪些项目／各自别名／交付根哪些名字是保留名」从来没有登记处**，
        #   所以 G11 判串项目只有一张手写别名表可依赖。本轮把这些登进 projects_registry.json，
        #   并由 `check_registry.py` 的 [E] 项与 config.yaml 对账（别名不等＝error）。
        prj_path = os.path.join(P["engine"], "projects_registry.json")
        prj = None
        if isfile(prj_path):
            try:
                prj = json.loads(read(prj_path))
            except ValueError as e:
                prj = {"parse_error": str(e)}
        gap("GAP-E1", "engine",
            "`config.yaml:%s` 的 `project: %s` 是**默认项目**（换项目走 `--project`，`run.py:493` 写明"
            "「别改 config 路径」）⇒ 本轮**更正**本条原来的说法「换项目要动真源」，那句是假的。"
            "剩下的真洞是：项目身份、各自别名、交付根保留名**过去没有任何登记处**，"
            "G11 判串项目只能靠 config 里那张手写别名表；`output_root` 实测仍写死 `%s`（在 `:%s`）。"
            "批 4·3 已建 `projects_registry.json`（项目 %s 个／保留名 %s 个／未声明目录 %s 个如实列出不替用户判），"
            "对账由 `check_registry.py [E]` 做（别名不等＝error，已反向验证会响）"
            "⚠ 本条另半条病（「同一个值两套取法」：`run.py` 现推、`webui.py` 直读字面量"
            " ⇒ 切项目后 webui 列的还是上一个项目的批次夹）**已闭**：取法收进 "
            "`engine\\delivery_root.py` 一处，webui 与迁移脚本都改吃它，"
            "并有 `tests\\test_delivery_root.py` 钉住字面量不许漂（实测见 measured）。"
            % (d["config"]["project_line"], project, output_root,
               d["config"]["output_root_line"],
               len((prj or {}).get("projects") or []) if isinstance(prj, dict) else "未测量",
               len(((prj or {}).get("delivery") or {}).get("reserved_names_not_projects") or [])
               if isinstance(prj, dict) else "未测量",
               len(((prj or {}).get("projects_not_declared") or {}).get("list") or [])
               if isinstance(prj, dict) else "未测量"),
            evidence=[P["config"], P["index_doc"]]
                     + ([dr] if single_source else [])
                     + ([os.path.join(P["engine"], "tests", "test_delivery_root.py")]
                        if isfile(os.path.join(P["engine"], "tests", "test_delivery_root.py")) else []),
            measured={"project": project, "project_line": d["config"]["project_line"],
                      "output_root": output_root,
                      "output_root_line": d["config"]["output_root_line"],
                      "delivery_root_module": dr, "single_source": single_source,
                      "webui_uses_helper": webui_patched,
                      "half_closed_note": "两套取法那半条已闭；剩下的真洞是「项目身份/别名/保留名没有登记处」，"
                                          "批 4·3 已建 projects_registry.json 并由 check_registry [E] 对账",
                      "projects_registry": {"path": prj_path, "exists": isfile(prj_path),
                                            "projects": len((prj or {}).get("projects") or [])
                                            if isinstance(prj, dict) else None,
                                            "reserved_names": len(((prj or {}).get("delivery") or {})
                                                                  .get("reserved_names_not_projects") or [])
                                            if isinstance(prj, dict) else None,
                                            "not_declared_listed": len(((prj or {}).get(
                                                "projects_not_declared") or {}).get("list") or [])
                                            if isinstance(prj, dict) else None,
                                            "parse_error": (prj or {}).get("parse_error")
                                            if isinstance(prj, dict) else "非 dict"}},
            severity="mid" if (single_source and webui_patched) else "high")
    if len(with_provider) < len(wfs):
        gap("GAP-E2", "engine",
            "%d 个 workflow yaml 里 %d 个写了 provider（缺 %d 个）、%d 个没写 prompt_kind"
            " ⇒ provider 全靠 `channel_of()` 兜底猜，这就是 C57 那次差点把 ref2va 主通道拦死的根"
            % (len(wfs), len(with_provider), len(wfs) - len(with_provider), len(without_kind)),
            evidence=[wf_dir, P["preflight"]],
            measured={"total": len(wfs), "with_provider": len(with_provider),
                      "with_prompt_kind": len(with_kind),
                      "without_prompt_kind": without_kind},
            severity="high")
    if ungated_producing:
        gap("GAP-E4", "engine",
            "%d 份 workflow **会实际产出媒体、但没有任何 auto_gates 步** ⇒ 提示词从没经过 G 闸"
            "就直接出图：%s。（全 %d 份里现有 %d 份带闸。）"
            "10-02 批1 给 prompt 驱动的那几份补上了 gate（G5/G7/G11，prompt_kind: image，"
            "characters: none），端到端验过闸排在第一步且能拦停；剩下的这几份是 **manifest 驱动**"
            "（提示词在批次 manifest 里、不在 args），照图片口径硬塞一道闸只会报"
            "「没有提示词可校验」⇒ 要覆盖它们得逐条核 manifest，属改行为，等你裁"
            % (len(ungated_producing), "、".join(ungated_producing), len(wfs), len(gated)),
            evidence=[wf_dir] + [os.path.join(wf_dir, x) for x in ungated_producing],
            measured={"ungated_producing": ungated_producing,
                      "with_auto_gate": len(gated), "total": len(wfs),
                      "note": "gate_step_count 里 0 就是真没闸；人工关口步也叫 gate 但不跑机械判据，"
                              "所以判据看的是 auto_gates 有没有，不是 task: gate 数了几次"},
            severity="mid", ruling=True,
            note="补闸＝改现役行为（一上去就可能拦停手上有批次），所以只补了预验 0 error 的两份；"
                 "image_refine／h3_one_click_movie 需要按 manifest 逐条核，未擅自扩")
    if len(polish_by_name) > 1:
        gap("GAP-E6", "engine",
            "同一个运行决定（要不要润色）在现役 workflow 里有 **两个参数名**：%s ⇒ "
            "运行决定单（G13）只能把两个都认，别名登记在 `channels_registry.run_slots[].accepts`，"
            "两个同时给且值不一致时报错、不静默挑一个。统一成一个要动 %d 份现役流＋webui 白名单＋测试，"
            "属改行为 ⇒ 本轮**如实登记、不擅自改名**，等你裁"
            % ("／".join("%s（%d 份）" % (n, len(v)) for n, v in sorted(polish_by_name.items())),
               sum(len(v) for v in polish_by_name.values())),
            evidence=[wf_dir, P["channels_registry"], os.path.join(P["engine"], "webui.py")],
            measured={"by_name": polish_by_name,
                      "aliases_registered": True,
                      "note": "别名必须是现役真实参数名，`check_registry.py` [G] 抓到死别名即 error"},
            severity="low", ruling=True)
    # GAP-G3：机检裁判件与引擎的接线（10-02 硬检查查出来的那条：尺子有，主力那把没接）
    qcw = qc_wiring_scan()
    if qcw["unreferenced_count"]:
        wr = qcw.get("wired_ruler") or {}
        gap("GAP-G3", "gates",
            "名字像机检裁判的脚本 %d 个，其中 **%d 个在调用面里一次都没出现**（引擎三入口＋config＋"
            "全部 workflow＋bat/ps1）：%s ⇒ 判据存在但从未执行；这比「没有判据」更危险，"
            "因为文档会写「已有机检」而它一次也没跑过。"
            "★ 10-03 批 7-4 已接进一把：`qc_batch_consistency.py`（批内 DINO 相对尺）"
            "接线＝%s、可导入＝%s、空清单判词＝%s、阈值现读＝%s。"
            "⚠ 更正本条以前的一句话：它写「标定过的那把主尺 `tmp/wzy/qc.py` 也在其中」——**那是假的**，"
            "候选表只从 `tools\\` 里取 `.py`，tmp 那份从来不在候选面里（我把「它没接线」写成了"
            "「它出现在未接线清单里」）。它没接线的真实原因是：**默认解释器跑不起来**"
            "（`import lpips` 通过与否＝%s）＋绝对带换项目 3/3 假拦（10-02 预量）。"
            "10-02 影响面预量已证：拿绝对带当通用闸会把**别的项目整批假拦**——通用角色库 3 张未打回的"
            "基线稿，对武昭君仪锚图 3/3 全 FAIL、7/8 指标飘红；换同项目锚后仍有 4 项 FAIL"
            "（绝对带是从一个项目的 12 张人判样本标定的）。所以「接不接」的前置是「每项目标定」，"
            "那是未成文的 G6 的活。另：`check_preflight.py` 顶层有 **%d 个全大写常量在本文件里只出现一次**"
            "（＝除声明那行没人引用）：%s——其中 `ARK_LIMIT_AUDIOS` 已核实为**从未校验**"
            "（10-02 用户裁『只登记不补校验』：没有通道真源支撑前补校验就是编造判据）；"
            "其余各项**未逐个核过用途**（有的本来就是清单而非阈值，比如 `ALL_GATES`），列出来供人读"
            % (qcw["candidate_count"], qcw["unreferenced_count"],
               "、".join(qcw["unreferenced"][:8]),
               wr.get("wired_in_tasks_py"), wr.get("importable"),
               wr.get("empty_list_verdict"), wr.get("thresholds"),
               qcw["ruler_env"]["default_python_has_lpips"],
               len(qcw["declared_only_constants"]),
               "、".join(qcw["declared_only_constants"])),
            evidence=[P["tools"], P["tasks_py"], P["preflight"]]
                   + ([wr["script"]] if wr.get("script") else []),
            measured=qcw, severity="mid",
            note="口径只看文件名有没有出现在调用面，不判该不该接；影响面预量报告见 "
                 "E:\\创作\\_待审文档\\岗位判据冲突与QC主尺接入_待审_20261002.md。"
                 "⚠ 已接那把的**覆盖面有上限**：它的 patch 按脸归一，产物里没脸就量不了"
                 "（10-03 离线预量 18 个真批次：13 个未测量／2 个会被拦／1 个警示／2 个过）")
    d["qc_wiring"] = qcw
    # 阈值这一层（批 7-2）：**值由第五件校验器现读**，本文件不重实现一遍读法
    tp, tp_err = run_threshold_probe()
    tdata = ((tp or {}).get("data")) or {}
    terrs = (tp or {}).get("errors") or ([tp_err] if tp_err else [])
    d["thresholds"] = {"registry": P["thresholds_registry"],
                       "registry_exists": isfile(P["thresholds_registry"]),
                       "validator": P["check_thresholds"],
                       "probe_ran": bool(tp),
                       "counts": tdata.get("counts") or {},
                       "unenforced_ids": tdata.get("unenforced_ids") or [],
                       "known_mismatches": tdata.get("known_mismatches") or [],
                       "errors": terrs,
                       "note": "注册表里不抄值（抄了就是第二份抄本）；这里只搬校验器的结论，不重算"}
    if not (tdata.get("counts") or {}):
        gap("GAP-E7", "engine",
            "阈值这一层**没测到**（%s）⇒ 属未测量，不等于「没问题」"
            % (tp_err or "探针返回空结构"),
            evidence=[P["thresholds_registry"], P["check_thresholds"]],
            measured=d["thresholds"], severity="mid")
    elif terrs:
        gap("GAP-E7", "engine",
            "阈值注册表查出 %d 条问题（不一致／读不到）：%s"
            % (len(terrs), "；".join(str(x) for x in terrs)[:320]),
            evidence=[P["thresholds_registry"], P["check_thresholds"]],
            measured=d["thresholds"], severity="mid")
    if claim and cases is not None and str(cases) not in claim:
        gap("GAP-E3", "engine",
            "config.yaml 注释自称测试「%s 项」，实测 pytest 收集到 **%d 条用例** ⇒ 文档自述与盘上不符"
            "（M1：证据优先于文档自述。⚠ 这里比的是**用例**数，不是 `def test_` 的 %d 个——"
            "两者单位不同，`@parametrize` 会一对多展开，10-02 第一版就拿错单位误报过一次）"
            % ("、".join(sorted(set(claim))), cases, def_test_total),
            evidence=[P["config"], P["tests"]],
            measured={"claim_in_comments": sorted(set(claim)),
                      "collected_cases": cases, "def_test_total": def_test_total,
                      "collected_cases_note": cases_note},
            severity="low")
    elif claim and cases is None:
        gap("GAP-E3", "engine",
            "config.yaml 注释自称测试「%s 项」，但**单位对不上、无法判定**："
            "静态只能数到 %d 个 `def test_`，而注释那个数是用例单位（`@parametrize` 一对多展开）。"
            "collect 探针：%s ⇒ 这条按未测量处理，不下结论"
            % ("、".join(sorted(set(claim))), def_test_total, cases_note),
            evidence=[P["config"]],
            measured={"claim_in_comments": sorted(set(claim)),
                      "def_test_total": def_test_total, "collect_probe": cases_note},
            severity="low", note="未测量不等于已核实；要判定必须补 `pytest --collect-only -q` 现算")
    return d


# ─────────────────────────────────────────────────────────────
# 层 4：关口层
# ─────────────────────────────────────────────────────────────
def scan_gates(pf_src, doc_claim):
    m = re.search(r"ALL_GATES\s*=\s*\[([^\]]*)\]", pf_src or "")
    all_gates = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    m2 = re.search(r'spec\.get\("only"\)\s*or\s*\[([^\]]*)\]', pf_src or "")
    # ⚠ 上面 default_gates 读的是 run_checks 的**兜底列表**，它**不是现役实情**：
    #   引擎从 yaml 的 auto_gates 显式传 `only`（engine\tasks.py 建 spec），
    #   所以真正决定"这次跑哪些闸"的是每份流自己声明的那一行。
    #   10-02 就因为它，我把 GAP-G2 写成「G11 默认不跑」——实测 14 份带闸的流
    #   **全部含 G11**，那条结论对引擎主路一直是错的。这里补上真实口径。
    flow_gates, flow_no_g11 = {}, []
    if isdir(P["workflows"]):
        for f in sorted(os.listdir(P["workflows"])):
            if not f.endswith(".yaml"):
                continue
            t = read(os.path.join(P["workflows"], f)) or ""
            gs = set()
            for m in re.finditer(r"auto_gates\s*:\s*\[([^\]]*)\]", t):
                gs |= {x.strip().strip('"\'').upper() for x in m.group(1).split(",") if x.strip()}
            for m in re.finditer(r"auto_gates\s*:\s*\n((?:\s*-\s*\w+\n?)+)", t):
                gs |= {x.strip().upper() for x in re.findall(r"-\s*(\w+)", m.group(1))}
            if gs:
                flow_gates[f[:-5]] = sorted(gs)
                if "G11" not in gs:
                    flow_no_g11.append(f[:-5])
    flow_union = sorted({g for v in flow_gates.values() for g in v})
    flow_all_have_g11 = bool(flow_gates) and not flow_no_g11
    # 兜底列表本身（只在没传 only 时生效）—— 10-02 用户裁定把 G11 加进来了
    default_gates = re.findall(r'"([^"]+)"', m2.group(1)) if m2 else []
    not_default = [g for g in all_gates if g not in default_gates]

    # 每个 gate 的函数 + error/warn/ok 计数（level 从代码里量，不猜）
    funcs = re.findall(r"^def (g\d+\w*)\(", pf_src or "", re.M)
    per = {}
    for fn in funcs:
        gid = re.match(r"(g\d+)", fn).group(1).upper()
        body = func_body(pf_src, fn)
        e = per.setdefault(gid, {"funcs": [], "error": 0, "warn": 0, "ok": 0, "lines": 0})
        e["funcs"].append(fn)
        e["error"] += len(re.findall(r"rep\.error\(", body))
        e["warn"] += len(re.findall(r"rep\.warn\(", body))
        e["ok"] += len(re.findall(r"rep\.ok\(", body))
        e["lines"] += body.count("\n")
    for gid in sorted(all_gates):
        per.setdefault(gid, {"funcs": [], "error": 0, "warn": 0, "ok": 0, "lines": 0})

    nums = sorted({int(re.match(r"G(\d+)", g).group(1)) for g in all_gates
                   if re.match(r"G(\d+)", g)})
    holes = [n for n in range(1, (max(nums) if nums else 0) + 1) if n not in nums]
    # ⚠ 不能直接 grep `H[1-9]`：`H3` 是模型名（MiniMax H3），满地都是，会假报"有编号"。
    # 只认**被引号包起来的独立 H1–H7 令牌**——那才是关口编号的写法。
    h_hits = []
    for src_path in (P["preflight"], P["tasks_py"]):
        s = read(src_path) or ""
        for m in re.finditer(r"""["'](H[1-7])["']""", s):
            h_hits.append({"file": src_path, "token": m.group(1),
                           "line": s[:m.start()].count("\n") + 1})

    d = {"machine_gate_source": P["preflight"],
         "source_lines": nl(P["preflight"]),
         "all_gates": all_gates, "all_gates_count": len(all_gates),
         "fallback_default_gates": default_gates,
         "not_in_fallback": not_default,
         "per_flow_auto_gates": flow_gates,
         "flows_with_gate": len(flow_gates),
         "flows_without_G11": flow_no_g11,
         "auto_gates_union": flow_union,
         "gates_unit_note": "default_gates 是 run_checks 的**兜底**；现役每跑哪些闸看"
                             "per_flow_auto_gates（引擎按 yaml 的 auto_gates 显式传 only）。"
                             "10-02 就因为读前者把 GAP-G2 写错过一次。",
         "number_holes": ["G%d" % n for n in holes],
         "per_gate": {k: per[k] for k in sorted(per)},
         "human_gate_id_tokens_in_code": h_hits,
         "human_gates_numbered_in_code": len(h_hits),
         "h_numbering_probe": "只认引号包起来的独立 H1–H7；`H3` 是模型名不算",
         "doc_claim": doc_claim,
         "engine_human_gate_source": P["tasks_py"],
         "engine_gate_tasks": len(re.findall(r'"?gate"?\s*[:,]', read(P["tasks_py"]) or ""))}

    # GAP-G1 的措辞要随现实变，否则会自己打自己脸：
    #   ① 文档原文找不到了（索引 §5 已按实测改写）时，**不许把脚本的兜底文案当成"文档声称"打出来**；
    #   ② G5 已成文且是按实测写的，"一旦照抄就固化"这个条件句就必须收掉，
    #      否则报的是早就不成立的事。
    g5_doc = os.path.join(P["gen"], "R5_关口与授权.md")
    g5_written = isfile(g5_doc)
    claim_real = not doc_claim.startswith("索引 §5 未找到")
    # H5 悬空引用：文字里指向 H5，但没有任何 `id: H5` 的步。
    h5_ref, h5_step = [], 0
    if isdir(P["workflows"]):
        for f in sorted(os.listdir(P["workflows"])):
            t = read(os.path.join(P["workflows"], f)) or ""
            if re.search(r"^\s*id:\s*H5\s*$", t, re.M):
                h5_step += 1
            elif re.search(r"\bH5\b", t):
                h5_ref.append(f)
    d["dangling_H5"] = {"referenced_in": h5_ref, "step_exists_count": h5_step,
                        "note": "文字里出现 H5 但盘上没有 `id: H5` 的 gate 步 ⇒ 指向不存在的关口"}

    if holes or len(all_gates) != 12 or not h_hits:
        if g5_written and not claim_real:
            gap("GAP-G1", "gates",
                "名实不符的**文档侧已闭**：`R5_关口与授权.md` 已按实测成文（**逐个闸**写判据、"
                "H 从 yaml 的 gate 步 id 派生），索引 §5 那句「G1–G12／H1–H7」也已改成实测值，"
                "所以现在**扫不到旧的文档声明了**（这不是缺陷，是被纠正掉了）。"
                "剩下两条残留：① `G9`／`G10` 编号跳空、来历无档可查（%s）；"
                "② `H5` 是**被现役流引用却不存在的关口**——%d 份 yaml 的文字里写着进 H5，"
                "但 `id: H5` 的步有 %d 个 ⇒ 操作者被指挥去一个不存在的地方"
                % ("、".join("G%d" % n for n in holes) or "无",
                   len(h5_ref), h5_step),
                evidence=[P["preflight"], g5_doc, P["index_doc"]]
                         + [os.path.join(P["workflows"], x) for x in h5_ref],
                measured={"all_gates": all_gates, "holes": ["G%d" % n for n in holes],
                          "h_numbering_hits_in_code": len(h_hits),
                          "doc_claim_now": doc_claim, "g5_written": True,
                          "dangling_H5_referenced_in": h5_ref,
                          "dangling_H5_step_exists": h5_step},
                severity="mid",
                note="从 high 降 mid 是**代码与文档现状决定的**（G5 已成文、旧声明已改），"
                     "不是我把口径调松；残留的 H5 悬空引用仍需处置（改 hint 或真立一步）")
        else:
            gap("GAP-G1", "gates",
                "名实不符：%s代码 `ALL_GATES` 实测只有 %d 个（%s），编号缺 %s；"
                "`H1–H7` 这套人工关口编号在 check_preflight.py＋tasks.py 里命中 %d 处"
                "%s ⇒ 关口体系**还不能当规则用**"
                % ("索引 §5 声称关口体系是「%s」，" % doc_claim if claim_real else
                   "索引 §5 已扫不到 G/H 编号声明（旧声明被改写过），",
                   len(all_gates), ",".join(all_gates),
                   "、".join("G%d" % n for n in holes) or "无", len(h_hits),
                   "" if g5_written else "；且 `R5_关口与授权.md` 尚未成文，"
                   "照抄文档就会把名实不符固化成规则"),
                evidence=[P["preflight"], P["tasks_py"], P["index_doc"]],
                measured={"all_gates": all_gates, "holes": ["G%d" % n for n in holes],
                          "h_numbering_hits_in_code": len(h_hits), "doc_claim": doc_claim,
                          "doc_claim_is_verbatim": claim_real, "g5_written": g5_written},
                severity="high",
                note="按「文档跟代码」成文 G5：逐个闸写判据（闸清单以 `ALL_GATES` 为准，本句不抄计数），H 从 tasks.py 的 gate 任务"
                     "＋yaml label 派生出实际清单再编号，不照抄 H1–H7")

    # GAP-G2 的旧措辞是**错的**，必须连着更正一起报，不然等于悄悄改口径：
    # 原来写「G11 是 error 级却默认不执行」，判据取自 run_checks 的兜底列表；
    # 但引擎是从 yaml 的 auto_gates 显式传 only 的，实测 14 份带闸的流**全部含 G11**
    # ⇒ 对引擎主路，G11 一直在跑。真正的洞只在"没传 only"的调用（裸 CLI、run_h3.py）。
    err_gates = sorted({g for g in all_gates if per.get(g, {}).get("error", 0) > 0})
    unadjudicated_g11_fixed = flow_all_have_g11 and "G11" in default_gates
    if not_default:
        errlevel = [g for g in not_default if per.get(g, {}).get("error", 0) > 0]
        gap("GAP-G2", "gates",
            "关口子集现状：兜底列表 `%s`；**现役实情由 17 份 yaml 的 auto_gates 决定**——"
            "%d 份带闸流并集是 `%s`，其中**每一份都含 G11**（不含 G11 的：%s）。"
            "⚠ 更正：本条旧措辞写「G11 是 error 级却默认不执行」**对引擎主路是错的**，"
            "因为判据取的是兜底列表而非 auto_gates（同 74/107 那类单位错配）。"
            "10-02 用户裁定后已把 G11 加进兜底，所以现在仍不在任何子集的只有：%s%s"
            % (",".join(default_gates), len(flow_gates), ",".join(flow_union),
               "、".join(flow_no_g11) or "无", ",".join(not_default),
               "（其中 error 级：%s）" % ",".join(errlevel) if errlevel else
               "——G12 是纯 warn（重复出片提醒），不拦停，属省时间的刻意省略"),
            evidence=[P["preflight"]] + [os.path.join(P["workflows"], x + ".yaml")
                                         for x in list(flow_gates)[:3]],
            measured={"fallback_default": default_gates, "not_in_fallback": not_default,
                      "per_flow_auto_gates": flow_gates,
                      "flow_union": flow_union, "flows_without_G11": flow_no_g11,
                      "error_level_gates": err_gates,
                      "correction": "旧措辞把兜底列表当成了现役实情；已按 auto_gates 重测"},
            severity="low" if unadjudicated_g11_fixed else "high",
            note="GAP-G2 从 high（待裁）转成 low：裁定已执行（G11 进兜底），"
                 "剩下的 G12 缺席是引擎注释里写明的性能取舍，且它只出 warn")
    if flow_no_g11:
        gap("GAP-G2b", "gates",
            "有 %d 份带 auto_gates 的流**没声明 G11**：%s ⇒ 这些流落点不核对，"
            "产物可能落进别的项目夹（9-18 仙戮四条串进无音批次夹就是这一形）"
            % (len(flow_no_g11), "、".join(flow_no_g11)),
            evidence=[os.path.join(P["workflows"], x + ".yaml") for x in flow_no_g11],
            measured={"flows_without_G11": flow_no_g11},
            severity="high")
    return d


# ─────────────────────────────────────────────────────────────
# 层 5：资产层
# ─────────────────────────────────────────────────────────────
def scan_assets(do_hash=True):
    root = P["assets"]
    st = walk_stats(root)
    # MANIFEST.json 自校验口径
    cm = {"path": P["char_manifest"], "exists": isfile(P["char_manifest"]),
          "bytes": nb(P["char_manifest"])}
    try:
        j = json.load(io.open(P["char_manifest"], encoding="utf-8"))
        items = j.get("items") or []
        cm.update({"total_field": j.get("total"), "items": len(items),
                   "fail_field": len(j.get("fail") or []),
                   "fields_per_item": len(items[0]) if items else 0,
                   "field_names": sorted(items[0].keys()) if items else [],
                   "self_check": "%s/%s" % (len(items) - len(j.get("fail") or []), len(items))})
        base = j.get("root") or P["char_lib"]
        miss = 0
        for it in items:
            f = it.get("file")
            if f and not os.path.exists(f if os.path.isabs(f) else os.path.join(base, f)):
                miss += 1
        cm["file_field_missing"] = miss
    except (OSError, ValueError) as e:
        cm["parse_error"] = "%s: %s" % (type(e).__name__, e)
    # MANIFEST.md 不是逐条清单，是**摘要**（33 行、一个"项|值"小表）。
    # 所以要比的不是"表格行数 vs json 条数"（上一版那么比得出 7 vs 863，是拿两种口径硬碰），
    # 而是它自己声称的「产物总数」vs json 的实际条数 —— 这才是同一口径下的自相矛盾。
    cm_md = {"path": P["char_manifest_md"], "exists": isfile(P["char_manifest_md"]),
             "bytes": nb(P["char_manifest_md"]), "lines": nl(P["char_manifest_md"])}
    t = read(P["char_manifest_md"]) or ""
    m_tot = re.search(r"产物总数\D{0,12}?(\d{1,6})", t)
    m_sha = re.search(r"sha256[^\n|]{0,20}\|\s*\**\s*(\d{1,6})\s*/\s*(\d{1,6})", t)
    m_mb = re.search(r"总体积\D{0,12}?([\d.]+)\s*MB", t)
    cm_md["claimed_total"] = int(m_tot.group(1)) if m_tot else None
    cm_md["claimed_sha_ok"] = ("%s/%s" % (m_sha.group(1), m_sha.group(2))) if m_sha else None
    cm_md["claimed_size_mb"] = float(m_mb.group(1)) if m_mb else None

    # 判废区（10-02 批3.4 已按 Q4 裁定合并：保留 `_归档` 当家，来源靠 `_归档\项目资源池\`
    #   这一层目录名保留 ⇒ 扫描器**不数"两处并存"了，改数"一处家 + 两种来源"）。
    #   ⚠ 合并后如果 `pool` 那个老路径又出现，说明有工具还在往旧址写 ⇒ 单列报出来。
    junk = {}
    for k, label in (("pool", "项目资源池（来源＝按「不进片」判废）"),
                     ("archive", "_归档（来源＝按时间归档）")):
        s = walk_stats(P[k])
        junk[label] = {"path": P[k], "exists": s["exists"], "files": s["files"],
                       "images": s["images"], "gib": s["gib"]}
    merged_home = os.path.join(P["archive"], "项目资源池")
    junk["_合并进来的那层（origin=pool）"] = dict(
        walk_stats(merged_home), path=merged_home)

    lora = walk_stats(P["lora"])
    lora_weights = lora["by_ext"].get(".safetensors", 0) + lora["by_ext"].get(".ckpt", 0) \
        + lora["by_ext"].get(".pt", 0)

    d = {"root": root, "exists": st["exists"], "files_total": st["files"],
         "images": st["images"], "gib": st["gib"], "top_dirs": st["top_dirs"],
         "by_ext_top": st["by_ext"],
         "char_manifest_json": cm, "char_manifest_md": cm_md,
         "junk_areas": junk,
         # 家只有一个：`_归档` 存在就算一个。老 `项目资源池` **复活**才算多出来。
         "junk_area_count": 1 if isdir(P["archive"]) else 0,
         "junk_legacy_pool_alive": isdir(os.path.join(root, "项目资源池")),
         "junk_merge_ledger": isfile(os.path.join(P["archive"],
                                                  "_合并台账_20261002_判废区合并.json")),
         "lora": {"path": P["lora"], "exists": lora["files"] > 0, "files": lora["files"],
                  "weight_files": lora_weights, "gib": lora["gib"]}}

    # 总索引超集：MANIFEST.json vs .md 自相矛盾
    if cm.get("items") and cm_md.get("claimed_total"):
        j_n, md_n = cm["items"], cm_md["claimed_total"]
        if md_n != j_n:
            gap("GAP-A1", "assets",
                "通用角色库两份清单自相矛盾：MANIFEST.json 实测 %d 条 vs MANIFEST.md 自称「产物总数 %d」"
                " ⇒ 以 json 为总索引超集（%d 字段、file 指向缺 %d），md 只当人读摘要"
                % (j_n, md_n, cm.get("fields_per_item", 0), cm.get("file_field_missing", -1)),
                evidence=[P["char_manifest"], P["char_manifest_md"]],
                measured={"json_items": j_n, "md_claimed_total": md_n,
                          "md_claimed_sha_ok": cm_md["claimed_sha_ok"],
                          "md_claimed_size_mb": cm_md["claimed_size_mb"],
                          "json_self_check": cm.get("self_check"),
                          "json_file_field_missing": cm.get("file_field_missing")},
                severity="mid")
    # 判废区合并后的账（D6＋Q4 已执行）：家一个、来源两种、台账在、总量对得上
    if d["junk_legacy_pool_alive"]:
        gap("GAP-A2", "assets",
            "判废区根下**又出现了独立的 `项目资源池`**（%d 件）——10-02 批3.4 已把它整夹并进 "
            "`_归档\\项目资源池\\`，旧址复活说明**有工具还在往老路径写**"
            "（三个读它的脚本本轮已改到新址：pool_move／promote_fix／fix_defects）"
            % walk_stats(os.path.join(root, "项目资源池"))["files"],
            evidence=[os.path.join(root, "项目资源池")],
            measured={"files": walk_stats(os.path.join(root, "项目资源池"))["files"]},
            severity="high",
            note="不是「又要合并一次」，是先找出谁在往旧址写")
    else:
        _arch = junk["_归档（来源＝按时间归档）"]
        _merged = junk["_合并进来的那层（origin=pool）"]
        if _arch["exists"] and _merged["exists"]:
            # 合并成功后的常设回归账：总量守恒、来源两栏都在、老根确实没了、台账在
            d["junk_merge_check"] = {
                "home": P["archive"],
                # `_归档` 总数含合并进来那层 ⇒ 减掉才是归档自己原有的
                "origin_archive_files": _arch["files"] - _merged["files"],
                "origin_pool_files": _merged["files"],
                "origin_pool_images": _merged["images"],
                "ledger_exists": d["junk_merge_ledger"],
                "legacy_root_gone": not d["junk_legacy_pool_alive"],
            }
    # sidecar 命名空间（R4-06-v2：`.anchor.json` 只装身份卡，`.shots.json` 装镜位绑定记录）
    sidecars, shotcards, role_n, kind_n = [], [], 0, 0
    keys_seen, no_role, orphan_shots = {}, 0, 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for f in fn:
            fp = os.path.join(dp, f)
            if f.endswith(".anchor.json"):
                sidecars.append(fp)
                try:
                    card = json.loads(read(fp) or "{}")
                except ValueError:
                    card = {}
                for k in sorted(card):
                    keys_seen[k] = keys_seen.get(k, 0) + 1
                if card.get("role"):
                    role_n += 1
                else:
                    no_role += 1          # 有卡但没 role ⇒ g3 只能靠文件名猜，是真漏
                if "anchor_kind" in card:
                    kind_n += 1
            elif f.endswith(".shots.json"):
                shotcards.append(fp)
                img = fp[: -len(".shots.json")]
                if not os.path.isfile(img):
                    orphan_shots += 1     # 绑定记录还在、图没了
    d["sidecars"] = {"count": len(sidecars), "with_role": role_n,
                     "with_anchor_kind": kind_n, "without_role": no_role,
                     "keys_seen": dict(sorted(keys_seen.items())),
                     "shots_json_count": len(shotcards),
                     "orphan_shots_json": orphan_shots,
                     "namespace_note": "`.anchor.json`＝身份卡（g3_identity 读）；"
                                       "`.shots.json`＝镜位绑定记录（g3 不读）。"
                                       "10-02 R4-06-v2 把一个后缀装两种东西的病分开",
                     "paths": sorted(sidecars)}
    if kind_n:
        gap("GAP-A3", "assets",
            "%d 份 `.anchor.json` 仍带旧字段名 `anchor_kind` ⇒ 那是镜位绑定记录混进了身份卡命名空间，"
            "`g3_identity` 现在会对此报 error（不是 warn）。schema v2 已强制：改后缀 `.shots.json`，"
            "迁移器 `E:\\创作\\技能配套脚本\\migrate_sidecar_v2.py`"
            % kind_n,
            evidence=sorted(sidecars)[:20],
            measured={"total": len(sidecars), "role": role_n, "anchor_kind": kind_n},
            severity="mid")
    if no_role:
        # 新判据（10-02 R4-06-v2 落地后才有意义）：**有身份卡但卡里没有 `role`**。
        # 这时 g3_identity 只能退回"靠文件名猜"，猜不到就 warn——看着"过了"，其实那槽没人核对过。
        # 这是迁移之后剩下的真漏，与 `anchor_kind`（旧字段名）是两种病，分开报。
        gap("GAP-A9", "assets",
            "%d 份 `.anchor.json` 里**没有 `role` 字段**（占现存 %d 份卡的 %d%%）"
            " ⇒ `g3_identity` 对这些槽只能靠文件名猜角色，猜不到就只报「机器无法判定」然后放行"
            "——看着核过，其实没核"
            % (no_role, len(sidecars),
               round(100.0 * no_role / max(1, len(sidecars)))),
            evidence=sorted(sidecars)[:20],
            measured={"without_role": no_role, "total": len(sidecars),
                      "keys_seen": dict(sorted(keys_seen.items()))},
            severity="mid",
            note="补 `role` 要有人看图判定，**脚本不许代填**（R4-06 纪律）；"
                 "这条挂着就是在催逐份补，不是让谁写个默认值糊过去")
    if orphan_shots:
        gap("GAP-A10", "assets",
            "%d 份 `.shots.json` 的**同名图正文件不在盘上** ⇒ 镜位绑定记录指向已经不存在的帧；"
            "这些多在 `v1_指向断裂版` 目录里（Q2 裁定不动、只登记），所以**这条是记账不是待修**"
            % orphan_shots,
            evidence=[os.path.dirname(x) for x in sorted(shotcards)][:10],
            measured={"shots_json_count": len(shotcards), "orphans": orphan_shots},
            severity="low",
            note="若哪天要清这批实验件，先看这条的数；不清就永久挂着也无害")
    # LoRA 未建 asset.json
    if lora["exists"] and lora_weights:
        has_asset = any(f.endswith("_asset.json") or f == "asset.json"
                        for dp, dn, fn in os.walk(P["lora"]) for f in fn)
        d["lora"]["has_asset_json"] = has_asset
        if not has_asset:
            gap("GAP-A4", "assets",
                "LoRA 产物 %d 个权重文件／%.2f GiB 无 asset.json ⇒ D5 已裁「算」，"
                "建 `class: lora`" % (lora_weights, lora["gib"]),
                evidence=[P["lora"]], measured={"weights": lora_weights, "gib": lora["gib"]},
                severity="low")

    # 同名叶子目录的整目录复制（先比大小，再 md5；有上限）
    dup = find_dup_dirs(root, do_hash)
    d["duplicate_dirs"] = dup
    # 「已裁不动」的重复目录对：读同一份登记表（用户 Q2 裁定 组2 不收敛、只登记）。
    # 与死链同一套设计——**判据的数据在盘上，不在源码里**，撤销裁定＝删条目后重扫。
    adj_pairs = adjudicated_dup_pairs()
    if dup["confirmed_copy_pairs"]:
        conf_all = [p for p in dup["pairs"] if p["md5_checked"] and p["md5_same"]]
        def _pk(x, y):
            return (os.path.normcase(x), os.path.normcase(y))
        conf = [p for p in conf_all if _pk(p["a"], p["b"]) not in adj_pairs]
        adj_conf = [p for p in conf_all if _pk(p["a"], p["b"]) in adj_pairs]
        notcopy = [p for p in dup["pairs"] if p["md5_checked"] and not p["md5_same"]]
        unmeas = [p for p in dup["pairs"] if not p["md5_checked"]]
        if conf:
            gap("GAP-A5", "assets",
                "确认 %d 组整目录复制（抽测 md5 全同）：%s ⇒ 归整前必须先收敛，"
                "否则同一张锚图会以多个路径被固化进总索引"
                % (len(conf),
                   "；".join("%s ↔ %s（同名 %d／md5 同 %d）"
                             % (_short(p["a"]), _short(p["b"]), p["same_name"], p["md5_same"])
                             for p in conf[:4])),
                evidence=[q for p in conf for q in (p["a"], p["b"])],
                measured={"confirmed_copy_pairs": dup["confirmed_copy_pairs"],
                          "unadjudicated": len(conf), "adjudicated_keep": len(adj_conf),
                          "same_name_dir_pairs_total": dup["pair_count"],
                          "hashes_done": dup["hashes_done"], "hash_cap": dup["hash_cap"],
                          "truncated": dup["truncated"], "confirmed": conf,
                          "not_a_copy": notcopy[:6], "unmeasured": unmeas[:6]},
                severity="high",
                note="另有 %d 组同名目录**测了但内容不同**、%d 组因哈希上限没测 —— 都不算复制，"
                     "分开报，不混进一个数里" % (len(notcopy), len(unmeas)))
        else:
            # 全数已裁 ⇒ 缺口关闭，但**如实登记还剩几组确认复制、凭什么不动**，
            # 免得下一个人以为"confirmed_copy_pairs 非零"就是没干的活。
            d["dup_dirs_status"] = (
                "确认整目录复制 %d 组，**待收敛 0 组**：其余 %d 组已裁不动"
                "（登记表 %s）。已裁的那组：%s"
                % (len(conf_all), len(adj_conf), DEADLINK_ADJUDICATED,
                   "；".join("%s ↔ %s（同名 %d／md5 同 %d）"
                             % (_short(p["a"]), _short(p["b"]), p["same_name"], p["md5_same"])
                             for p in adj_conf[:3])))

    # ── 资产总索引（批 3.3 新落点）：它自己也是"源新副本旧"的高危件，必须被盯着 ──
    reg_dir = os.path.join(root, "_资产总索引")
    reg_fp = os.path.join(reg_dir, "assets_registry.json")
    tbl_fp = os.path.join(reg_dir, "资产总表.md")
    rule_fp = os.path.join(reg_dir, "编号规则.md")
    reg = {"dir": reg_dir, "exists": isdir(reg_dir),
           "registry_json": isfile(reg_fp), "table_md": isfile(tbl_fp),
           "numbering_doc": isfile(rule_fp)}
    if isfile(reg_fp):
        try:
            rj = json.load(io.open(reg_fp, encoding="utf-8"))
            tot = rj.get("totals") or {}
            reg["generated"] = rj.get("generated")
            reg["projects"] = len(rj.get("projects") or [])
            reg["assets"] = tot.get("assets_documented")
            reg["identity_cards"] = tot.get("identity_cards")
            reg["images"] = tot.get("images")
            reg["status_counts"] = tot.get("project_status_counts")
            reg["images_unregistered"] = (tot.get("images_by_status") or {}).get("unregistered")
            # ⚠ 只**描述**，不**判定**：unregistered 45.6% 这个数很容易被读成
            # "45.6% 的图等着建档"，而它其实可能被个别大目录（例如训练素材）压着。
            # "某个目录算不算该建档的资产"是判定，判定权在用户不在脚本（同 status 不给 experiment 档），
            # 所以这里只把 Top 目录原名列出来，让人自己看见分布——不写分类器、不猜。
            un = [p for p in (rj.get("projects") or []) if p.get("status") == "unregistered"]
            reg["unregistered_top_dirs"] = [
                {"project": p.get("project"), "images": p.get("images")}
                for p in sorted(un, key=lambda x: (-(x.get("images") or 0), x.get("project") or ""))[:5]]
            reg["unregistered_dirs"] = len(un)
            reg["images_in_top_unregistered_dir"] = (
                reg["unregistered_top_dirs"][0]["images"] if reg["unregistered_top_dirs"] else 0)
            reg["self_check"] = rj.get("self_check")
            # 陈旧判定：索引是派生件，只要**任何**资产档/身份卡比它新，它就是旧的。
            newest, newest_f = 0.0, None
            for dp, dn, fn in os.walk(root):
                dn[:] = [x for x in dn if x not in SKIP_DIRS]
                if os.path.normcase(dp) == os.path.normcase(reg_dir):
                    dn[:] = []
                    continue
                for f in fn:
                    if f.endswith(("_asset.json", ".anchor.json")):
                        fp2 = os.path.join(dp, f)
                        try:
                            m2 = os.path.getmtime(fp2)
                        except OSError:
                            continue
                        if m2 > newest:
                            newest, newest_f = m2, fp2
            reg["newest_source"] = _short(newest_f) if newest_f else None
            reg["stale"] = bool(newest_f and newest > os.path.getmtime(reg_fp))
            # 交叉验证：索引自己数的图数 vs 扫描器自己数的。两个独立算法，对不上就是有一个错。
            reg["images_scanner"] = st["images"]
            reg["images_delta"] = None if reg["images"] is None else reg["images"] - st["images"]
        except (ValueError, OSError) as e:
            reg["error"] = "%s: %s" % (type(e).__name__, e)
    d["asset_registry"] = reg
    if reg["exists"] and (reg.get("stale") or reg.get("self_check", {}).get("passed") is False):
        why = []
        if reg.get("stale"):
            why.append("索引比它要反映的源旧（最新源 %s）" % reg.get("newest_source"))
        if reg.get("self_check", {}).get("passed") is False:
            why.append("索引自证未通过：%s" % "；".join(reg["self_check"].get("fails") or []))
        gap("GAP-A11", "assets",
            "资产总索引**过期或自证未过**：%s ⇒ 索引是派生件，旧的派生件比没有更坏——"
            "它会让人拿着一个已经不对的数去挂锚" % "、".join(why),
            evidence=[reg_fp],
            measured={"generated": reg.get("generated"), "stale": reg.get("stale"),
                      "newest_source": reg.get("newest_source"),
                      "self_check": reg.get("self_check")},
            severity="high",
            note="修法只有一个：重跑 `E:\\创作\\技能配套脚本\\build_asset_registry.py`，"
                 "不要在 json 里手改数")
    if reg.get("images_delta") not in (None, 0):
        gap("GAP-A12", "assets",
            "同一个问题两个算法给出两个数：资产索引数到 %s 张图，扫描器数到 %s 张，差 %d 张"
            " ⇒ 必有一个口径错（多半是扩展名清单或 SKIP_DIRS 不一致），"
            "对不上之前两个数都别引用"
            % (format(reg["images"], ","), format(st["images"], ","), reg["images_delta"]),
            evidence=[reg_fp, P["assets"]],
            measured={"registry_images": reg["images"], "scanner_images": st["images"],
                      "delta": reg["images_delta"]},
            severity="mid",
            note="这条是**故意留的交叉验证**：两个独立实现互相盯，谁改了扩展名清单都会被对方抓到")

    # ── 资产档 `<ID>_asset.json`（批 3.2 新落点）：数量 ＋ **每条 canonical_anchors 是否真在盘上** ──
    # 为什么必须由扫描器验而不是由写档的人自报：资产档的全部价值就在
    #   "这件资产的权威锚是哪几张"这一句上。一句指不到文件的断言，比没有断言更坏——
    #   下一个人会照着挂锚，挂到一张不存在的图。所以这里做 `test -f`，逐条。
    asset_docs = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for f in sorted(fn):
            if f.endswith("_asset.json"):
                asset_docs.append(os.path.join(dp, f))
    asset_docs = sorted(asset_docs)
    ad_bad, ad_missing_files, ad_scope_unknown = [], [], []
    for f in asset_docs:
        try:
            dd = json.loads(read(f) or "{}")
        except ValueError:
            ad_bad.append({"file": _short(f), "why": "JSON 读不了"})
            continue
        rel_base = os.path.dirname(f)
        for key in ("canonical_anchors",):
            for rel in dd.get(key, []) or []:
                # 档里写的是**相对 舰体设计\ 的路径**（如 `资产v2\锚_…`），
                # 所以锚的基准目录＝该 asset.json 往上两级（`_资产档\` 的父目录）。
                base = os.path.dirname(rel_base)
                if not (os.path.isfile(os.path.join(base, rel)) or os.path.isfile(rel)):
                    ad_missing_files.append({"asset": dd.get("asset_id", "?"),
                                             "file": _short(f), "anchor": rel})
        for k, v in (dd.get("views") or {}).items():
            base = os.path.dirname(rel_base)
            if not (os.path.isfile(os.path.join(base, v)) or os.path.isfile(v)):
                ad_missing_files.append({"asset": dd.get("asset_id", "?"),
                                         "file": _short(f), "anchor": "views.%s: %s" % (k, v)})
        if not dd.get("scope"):
            # ⚠ 这里**不算"自检失手"**。R4-06 的口径是「缺字段 ⇒ 报机器判不了、需人工核对，
            #   不得由人或脚本补猜」⇒ 一份老实写 null 并留了 open_questions 的档，
            #   是**把未知记下来了**，比编一个 scope 强。所以单列一栏报，不混进 failed。
            ad_scope_unknown.append({"asset": dd.get("asset_id", "?"), "file": _short(f),
                                     "has_open_question": bool(dd.get("open_questions"))})
    d["asset_docs"] = {
        "count": len(asset_docs),
        "by_project": {},
        "anchor_check_failed": ad_missing_files,
        "scope_unknown": ad_scope_unknown,
        "unparsable": ad_bad,
        "note": "canonical_anchors / views 逐条 test -f ⇒ 指不到文件的锚算 failed（高）。"
                "scope 为空**另记一栏不算 failed**：按 R4-06，宁缺不猜；"
                "但带 null 且没留 open_questions 的（既不知道又没记为什么不知道）会单独点名。"
                "**如实报，不因为刚写出来就给它打勾**"}
    for f in asset_docs:
        proj = _short(os.path.relpath(os.path.dirname(f), root)).split(os.sep)[0]
        d["asset_docs"]["by_project"][proj] = d["asset_docs"]["by_project"].get(proj, 0) + 1
    if asset_docs:
        gap("GAP-A7", "assets",
            "资产档已开始落地：全库 %d 份，分布 %s。但覆盖仍极低：%d 份对 %s 张图，"
            "且只覆盖 %s 一个项目 ⇒ 其余项目的「权威锚是哪几张」仍然没人回答得了"
            % (len(asset_docs), json.dumps(d["asset_docs"]["by_project"], ensure_ascii=False),
               len(asset_docs), format(st["images"], ","), "、".join(d["asset_docs"]["by_project"])),
            evidence=[f for f in asset_docs][:6],
            measured={"count": len(asset_docs),
                      "by_project": d["asset_docs"]["by_project"],
                      "anchor_check_failed": len(ad_missing_files),
                      "images_total": st["images"],
                      "coverage_pct": round(100.0 * len(asset_docs) / max(1, st["images"]), 2)},
            severity="mid",
            note="这条是**进度条不是缺陷单**：批 3.2 的样板已跑通，剩下的按项目铺。"
                 "锚校验失败数记在 anchor_check_failed，非 0 时先修档再铺新项目")
    if ad_missing_files or ad_bad:
        gap("GAP-A8", "assets",
            "资产档自检失手 %d 项：%s ⇒ 档里点名的权威锚／作用域对不上盘，"
            "照着挂锚会挂到不存在的图" % (len(ad_missing_files) + len(ad_bad),
                                          "；".join("%s/%s" % (x.get("asset", "?"),
                                                               x.get("anchor", x.get("why", "?")))
                                                    for x in (ad_missing_files + ad_bad)[:5])),
            evidence=[f for f in asset_docs][:6],
            measured={"failed": ad_missing_files[:20], "unparsable": ad_bad[:10]},
            severity="high",
            note="这条宁严勿宽：刚写出来的档也照样查、照样报")

    # 引用死链：扫 E:\创作 里的文本文件，按作用域判（搬判废件会碰到的那几处才算行动清单）
    dl = dead_links(root)
    d["dead_links"] = dl
    # ⚠ 触发条件从 `actionable_dead` 改成 **`actionable_fix`**（10-02 批3 P1 收工时改）。
    #   理由：作用域内还有死链 ≠ 还有活要干。分层判据落地后 `actionable_dead` 会长期非零
    #   （日志／错误实录／勘误注记／已裁为死都是死路径），拿它当触发器 ⇒ 这条 gap 永远闭不掉，
    #   而"永远红着的 gap"会让人开始忽略所有 gap —— 那才是真正的漏。
    #   `actionable_keep` 仍然照登（下面 else 分支里出账），只是不再算缺口。
    if dl["actionable_fix"]:
        per = "；".join("%s：%d 处（涉及 %d 个文件）"
                        % (o["label"], o["dead_count"], len(o["files_involved"]))
                        for o in dl["by_scope"] if o["dead_count"])
        gap("GAP-A6", "assets",
            "引用死链 %d 处（作用域内，扫了 %d 个文本文件）→ %s。"
            "**分层后真正要动手的有 %d 处**（另 %d 处在日志／错误实录／勘误注记／已裁登记表里＝改它＝篡改当时的状态）"
            "⇒ 判废件搬完更要盯住（D6 已于 10-02 执行），别重演 09-28 那次「_归档 搬完留死链」%s"
            % (dl["actionable_dead"], dl["scanned_files"], per,
               dl["actionable_fix"], dl["actionable_keep"], dl["actionable_fix"],
               ("" if not dl["truncated"] else
                "；⚠ **本轮扫描撞了上限 %d 个文本文件 ⇒ 上面是下限不是全量**"
                % dl["scan_cap"])),
            evidence=[r["in_file"] for r in
                      [x for o in dl["by_scope"] for x in o["dead_fix_all"]]][:20]
                     or sorted({x["in_file"] for o in dl["by_scope"] for x in o["dead_sample"]})[:20],
            measured={"actionable_dead": dl["actionable_dead"],
                      "actionable_fix": dl["actionable_fix"],
                      "actionable_keep": dl["actionable_keep"],
                      "by_scope": [{"label": o["label"], "dead": o["dead_count"],
                                    "fix": o["dead_fix_count"], "keep": o["dead_keep_count"],
                                    "live": o["live_count"],
                                    "files_to_fix": o["files_to_fix"],
                                    "scope_exists": o["scope_exists"]}
                                   for o in dl["by_scope"]],
                      "fix_list": [x for o in dl["by_scope"] for x in o["dead_fix_all"]],
                      "all_dead_absolute_paths": dl["all_dead_absolute_paths"],
                      "scanned_files": dl["scanned_files"],
                      "truncated": dl["truncated"],  # 撞顶 ⇒ 报出的数是下限，不是全量
                      "counting_unit": "去重后的路径数，不是逐处出现次数"},
            severity="high",
            note="全盘死绝对路径共 %d 处，但那个数**不是行动清单**（存档/日志里的路径本来就该是死的）。"
                 "⚠ 计数口径：同一路径在多个文件里只算一次；10-02 我另写探针对账时按"
                 "「逐处出现」数出 55 处、又因 `\\uXXXX` 转义伪路径多出 22 处假命中，"
                 "两个数都不是本条的口径——本条以去重路径数为准，伪路径已剔"
                 % dl["all_dead_absolute_paths"])
    else:
        # 没有待修死链 ⇒ 缺口关闭，但**如实登一行状态**，免得有人以为"作用域内已无死链"
        d["dead_links_status"] = (
            "作用域内仍有死路径 %d 处，但 **待修 0 处**：分别属"
            "「日志／错误实录／勘误注记／已裁为死」四类，改它们＝篡改当时的状态。"
            "已裁登记表 %s（%d 条，读取%s）"
            % (dl["actionable_dead"],
               dl["adjudicated_registry"]["path"], dl["adjudicated_registry"]["count"],
               "正常" if dl["adjudicated_registry"]["exists"] and
               not dl["adjudicated_registry"]["error"] else
               "失败：" + str(dl["adjudicated_registry"]["error"])))
    return d


DUP_DIR_MIN_SAME_NAME = 5


def find_dup_dirs(root, do_hash=True):
    """同名叶子目录成对出现 ⇒ 疑似整目录复制。先比同名文件数与大小，再 md5（有上限）。

    ⚠ 上一版的教训：`md5_same = 0` 有两种完全不同的含义 ——
      (a) 真的哈希过了、内容不同；(b) 哈希上限用完、**根本没测**。
    把 (b) 报成 (a) 就是拿"没量"当"量到不同"，所以每对必须带 verdict 说清是哪种。
    """
    by_base = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        b = os.path.basename(dp)
        if b and not b.startswith("."):
            by_base.setdefault(b.lower(), []).append(dp)
    pairs, done, trunc = [], 0, False
    for b in sorted(by_base):
        ds = sorted(by_base[b])
        if len(ds) < 2:
            continue
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, bb = ds[i], ds[j]
                fa = {f for f in os.listdir(a) if os.path.isfile(os.path.join(a, f))}
                fb = {f for f in os.listdir(bb) if os.path.isfile(os.path.join(bb, f))}
                same = sorted(fa & fb)
                if len(same) < DUP_DIR_MIN_SAME_NAME:
                    continue
                size_same, md5_same, checked = 0, 0, 0
                for f in same:
                    pa, pb = os.path.join(a, f), os.path.join(bb, f)
                    try:
                        if os.path.getsize(pa) != os.path.getsize(pb):
                            continue
                    except OSError:
                        continue
                    size_same += 1
                    if not do_hash:
                        continue
                    if done >= HASH_CAP:
                        trunc = True
                        continue
                    if nb(pa) and nb(pa) > HASH_MAX_BYTES:
                        continue
                    done += 1
                    checked += 1
                    if sha(pa) == sha(pb):
                        md5_same += 1
                if checked == 0:
                    verdict = "未测量（哈希上限 %d 已用完）" % HASH_CAP if do_hash else "未测量（--no-hash）"
                elif md5_same == checked:
                    verdict = "整目录复制（抽测 %d 份 md5 全同）" % checked
                elif md5_same:
                    verdict = "部分重复（抽测 %d 份，%d 份同）" % (checked, md5_same)
                else:
                    verdict = "同名不同物（抽测 %d 份 md5 全不同）" % checked
                pairs.append({"a": a, "b": bb, "same_name": len(same),
                              "size_identical": size_same, "md5_same": md5_same,
                              "md5_checked": checked, "verdict": verdict,
                              "files_only_in_a": len(fa - fb), "files_only_in_b": len(fb - fa)})
    real = [p for p in pairs if p["md5_checked"] and p["md5_same"]]
    real.sort(key=lambda p: (-p["md5_same"], p["a"]))
    rest = sorted([p for p in pairs if p not in real], key=lambda p: p["a"])
    return {"pairs": (real + rest)[:20], "pairs_shown": min(20, len(pairs)),
            "pairs_note": "pairs 最多列 20 组（确认复制的排前面），总数看 pair_count；"
                          "两者不等不是矛盾，是显示截断",
            "pair_count": len(pairs),
            "confirmed_copy_pairs": len(real),
            "hashes_done": done, "truncated": trunc, "hash_cap": HASH_CAP}


_SHA = {}


def sha(p):
    if p in _SHA:
        return _SHA[p]
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        v = h.hexdigest()
    except OSError:
        v = None
    _SHA[p] = v
    return v


# ⚠ 字符类里**必须排掉半角逗号与分号**（10-02 抓出来的过捕）：`shots.csv` 那种
#   `路径,0,本剧含AI生成画面` 的行，原来会把整行尾巴当成路径的一部分，
#   于是 (a) 存在性判在一个根本不存在的怪字符串上、(b) 谁照着这条清单去做替换就会**改坏 CSV**。
#   代价：真含半角逗号的 Windows 路径会少数几处 —— 这种路径极罕见，
#   而"少报几处"比"报出一条会指导人去改坏文件的假路径"安全（假阴比假阳坏，但这里的假阳会致损）。
PATH_RX = re.compile(r"[A-Za-z]:\\[^\s\"'`<>()\[\]，。；、|,;]{3,200}")

# 死链扫描的**作用域**：只把「搬判废件会碰到的那几处」当行动清单。
# 为什么不做全盘：上一版扫出 1151 处"死绝对路径"，但绝大多数在存档文档、日志、
# 历史方案里 —— 那些本来就该是死的（记的是当时的状态）。
# 拿 1151 当"要修的死链"会淹没真问题，也违背 M1「证据要能支撑结论」。
DEADLINK_SCOPES = [
    # ⚠ 顺序有讲究：匹配是 `startswith(scope + "\")` 且**首个命中即 break**，
    #   所以更具体的（嵌套的）那栏必须排在父作用域前面，否则 `_归档\项目资源池\` 里的
    #   死链会全被 `_归档` 那一栏吃掉，"被搬物自身"这栏永远是 0 —— 看着覆盖、其实没归因。
    (r"E:\创作\_归档\项目资源池", "判废区内·来源＝项目资源池（被搬物自身）"),
    (r"E:\创作\_归档", "判废区（合并后的家）：_归档"),
    # 10-02 批3.4 合并后，老根 `E:\创作\项目资源池` 已不存在，来源那层搬进上面那栏。
    # 留这一栏的意义：老根一旦复活（有工具还往旧址写），它会被单独记出来而不是混进归档。
    (r"C:\Users\若水\Desktop", "桌面（批次1 已清空为只留快捷方式）"),
]

# 死链**分层**：不是所有死链都该修。日志／外部原文里记的是"当时的状态"，
# 把它改成现在的路径＝篡改历史记录（与 README §六 那句"存档/日志里的路径本来就该是死的"同源）。
# 判据只看文件名特征，不看内容——看内容就得我逐条人工判读，那又变成写死的结论。
DEADLINK_KEEP_MARKERS = ("日志", "_外部教程原文", "归档", "MANIFEST", "_机检报告", ".注记")
# `.注记` 加进来的理由（10-02）：`shots.csv.注记.md` 这类文件**存在的唯一目的**就是记录死路径，
#   逐行判"是不是在谈论旧路径"会有漏网（"那里现在没有这些文件"不含任何勘误关键词），
#   而文件名判据零漏网——文件名带 `.注记` 的就是注记文件，不必逐行读。
DEADLINK_KEEP_EXT = (".log",)
# ⚠ 只看文件名会漏判一类：**文件名叫"台账"、内容却是引擎报错实录**。
#   10-02 执行批 3 的 P1 时当场撞到：`仙女星系战争项目\偏差台账.md:6/11/16` 被判"该修"，
#   但那三行是 `RuntimeError: 控制图不存在: C:\Users\若水\Desktop\…\锚_旭日级_裁切.png`
#   ——死路径**本身就是被记录的那个错误**，把它改成现在的路径＝篡改当时的状态，
#   与日志同罪。所以判据加一层"行内容"：命中引擎日志特征的行一律 该留（错误记录）。
#   取窄不取宽：只认这些 unmistakable 的报错标记，不认泛化的「不存在／失败」
#   （否则"若文件不存在则报错"这种**教人怎么做的正文**会被误判成记录 ⇒ 假阴）。
DEADLINK_ERRLINE_RX = re.compile(
    r"RuntimeError|Traceback|控制图不存在|锚点缺失|工作流失败|步骤\s*\w*\s*(开始|完成)|[✔✘]")
# ⚠ 10-02 自己踩出来的：**修死链的注记会复制一份死路径，于是注记本身变成新的死链**。
#   本轮修完 6 处后重扫，"仍该修"的 4 条里 3 条就是我写的 `# 原来写死在桌面（`旧路径`）`
#   这类引用原文——修一处、多一条，永远修不完。
#   判据：行内容带勘误/更正/失效/原句保留这类标记的，是在**谈论旧路径**而不是**使用**它 ⇒ 该留。
#   取词偏窄（要有"更正/勘误/失效/原句/旧写法/原来"之一），避免把
#   "该文件已失效请重新生成"这种**指示活引用**的行也吞掉（那是假阴）。
DEADLINK_NOTE_RX = re.compile(
    r"更正|勘误|失效|原句|旧写法|旧文本|原来写|原路径|旧路径|已删除|移入|改为|改成|"
    r"→|落地方式|不要把它|别把")
# ⚠ 带 glob 星号/尖括号占位的"路径"根本不是文件系统路径（`E:\…\项目资源池\**` 是
#   文档里的映射示意）。10-02 判废区合并后第一次死链扫描就报出三条，两条是这个、
#   一条是说明"落点从 X 改成 Y"的那句话——全是**解释文字被当成了引用**。
DEADLINK_GLOB_RX = re.compile(r"[*?<>{}]")
# 「已裁为死」登记表：**盘上的一份 JSON**，不是在扫描器里写死的清单
# （写死＝把我这一次的判读固化成假事实，违 M1；登记表可撤销、可追溯、每条自带 evidence）。
DEADLINK_ADJUDICATED = r"E:\创作\_死链已裁登记表.json"
_ADJ_CACHE = {"loaded": False, "set": set(), "path": DEADLINK_ADJUDICATED,
              "exists": False, "count": 0, "error": None}


def adjudicated_dead_paths():
    if _ADJ_CACHE["loaded"]:
        return _ADJ_CACHE["set"]
    _ADJ_CACHE["loaded"] = True
    _ADJ_CACHE["exists"] = isfile(DEADLINK_ADJUDICATED)
    if not _ADJ_CACHE["exists"]:
        return set()
    try:
        data = json.load(io.open(DEADLINK_ADJUDICATED, encoding="utf-8"))
        s = set()
        for e in data.get("entries", []):
            p = (e.get("path") or "").strip()
            if p:
                s.add(os.path.normcase(p.rstrip("\\/")))
        _ADJ_CACHE["set"] = s
        _ADJ_CACHE["count"] = len(s)
    except (ValueError, OSError) as exc:
        _ADJ_CACHE["error"] = "%s: %s" % (type(exc).__name__, exc)
    return _ADJ_CACHE["set"]


# `\uXXXX` 转义伪路径：markdown 里内嵌 JSON 时会出现 `E:\u56fe\u50cf…`，
# 解码后才是真路径。正则把转义串当路径字符 ⇒ **一律是假死链**，必须剔掉。
# 10-02 我另写探针复核时踩到这条：原始命中 92 处里有 22 处是这个伪影（全在 偏差台账.md）。
DEADLINK_ESCAPE_RX = re.compile(r"\\u[0-9a-fA-F]{4}")
DEADLINK_LIST_CAP = 200       # 全量清单最多存多少条（超出如实标 truncated）


_ADJ_DUP_CACHE = {"loaded": False, "set": set()}


def adjudicated_dup_pairs():
    """读登记表里的 `dup_dir_adjudicated` ⇒ 「已裁不动」的重复目录对。
    与死链登记表同一个文件、同一套原则：**数据在盘上，撤销＝删条目后重扫**。"""
    if _ADJ_DUP_CACHE["loaded"]:
        return _ADJ_DUP_CACHE["set"]
    _ADJ_DUP_CACHE["loaded"] = True
    s = set()
    if isfile(DEADLINK_ADJUDICATED):
        try:
            data = json.load(io.open(DEADLINK_ADJUDICATED, encoding="utf-8"))
            for e in data.get("dup_dir_adjudicated", []):
                pr = e.get("pair") or []
                if len(pr) == 2:
                    s.add((os.path.normcase(pr[0]), os.path.normcase(pr[1])))
        except (ValueError, OSError):
            pass          # 读不动就当没有已裁项 ⇒ gap 照报（宁可假阳，不要漏）
    _ADJ_DUP_CACHE["set"] = s
    return s


def deadlink_verdict(in_file, line_text="", dead_path=""):
    base = os.path.basename(in_file)
    if base.lower().endswith(DEADLINK_KEEP_EXT):
        return "该留（.log）"
    for k in DEADLINK_KEEP_MARKERS:
        if k in base:
            return "该留（%s）" % k
    # 文件名过关，再看**行内容**：引擎报错实录里的死路径是"被记录的错误"，不是"要修的引用"
    if line_text and DEADLINK_ERRLINE_RX.search(line_text):
        return "该留（错误记录）"
    # 再看在不在**谈论**这条旧路径（修死链时写的勘误注记会复制一份死路径 ⇒ 注记本身不是待修项）
    if line_text and DEADLINK_NOTE_RX.search(line_text):
        return "该留（勘误注记）"
    # 最后看登记表：用户已裁为死的（Q1 选 ③），依据是盘上那份 JSON，不是写死的清单
    if dead_path and os.path.normcase(dead_path.rstrip("\\/")) in adjudicated_dead_paths():
        return "该留（已裁为死）"
    return "该修"


def dead_links(root):
    """扫文本文件里的绝对路径，test -e 判死链。扫描根**包含被搬物自身**（09-28 C70 教训）。
    返回两套数：
      by_scope —— 可执行的清单（只算 DEADLINK_SCOPES 那几处）
      all_dead_absolute_paths —— 全盘计数，**只作背景，不是行动清单**
    """
    by_scope = {lbl: {"scope": sc, "dead": [], "live": 0} for sc, lbl in DEADLINK_SCOPES}
    all_dead, scanned, n_paths = [], 0, 0
    seen = set()
    truncated = False
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for f in sorted(fn):
            if not f.lower().endswith((".md", ".py", ".txt", ".json", ".csv", ".yaml")):
                continue
            if scanned >= DEADLINK_SCAN_CAP:
                truncated = True
                break
            fp = os.path.join(dp, f)
            t = read(fp)
            if t is None:
                continue
            scanned += 1
            for mm in PATH_RX.finditer(t):
                raw = mm.group(0)
                p = raw.rstrip("\\.,;:")
                if DEADLINK_ESCAPE_RX.search(p):
                    continue        # `\uXXXX` 转义伪路径，不是路径（见上面注释）
                if DEADLINK_GLOB_RX.search(p):
                    continue        # 带通配/占位的映射示意，不是文件系统路径
                if p in seen:
                    continue
                seen.add(p)
                n_paths += 1
                alive = os.path.exists(p)
                # 命中行的原文（给 deadlink_verdict 判"错误记录"用）：
                # 用与算行号**同一个偏移**切，保证行号与行内容对得上同一次命中。
                ln_start = mm.start()
                line_text = t[max(0, t.rfind("\n", 0, ln_start) + 1):
                              t.find("\n", ln_start) if t.find("\n", ln_start) >= 0 else len(t)]
                line_no = t[:ln_start].count("\n") + 1
                for sc, lbl in DEADLINK_SCOPES:
                    if p.lower().startswith(sc.lower() + "\\") or p.lower() == sc.lower():
                        if alive:
                            by_scope[lbl]["live"] += 1
                        else:
                            by_scope[lbl]["dead"].append(
                                {"path": p, "in_file": fp,
                                 "verdict": deadlink_verdict(fp, line_text, p),
                                 "line": line_no})
                        break
                if not alive:
                    all_dead.append({"path": p, "in_file": fp,
                                     "verdict": deadlink_verdict(fp, line_text, p),
                                     "line": line_no})
        if truncated:
            break
    out_scopes = []
    for sc, lbl in DEADLINK_SCOPES:
        rec = by_scope[lbl]
        rec["dead"].sort(key=lambda x: (x["in_file"], x["path"]))
        fix = [x for x in rec["dead"] if x["verdict"] == "该修"]
        keep = [x for x in rec["dead"] if x["verdict"] != "该修"]
        out_scopes.append({"scope": sc, "label": lbl, "scope_exists": os.path.exists(sc),
                           "dead_count": len(rec["dead"]), "live_count": rec["live"],
                           "dead_fix_count": len(fix),
                           "dead_keep_count": len(keep),
                           "dead_sample": rec["dead"][:15],
                           "dead_fix_all": fix[:DEADLINK_LIST_CAP],
                           "dead_keep_all": keep[:DEADLINK_LIST_CAP],
                           "fix_list_truncated": len(fix) > DEADLINK_LIST_CAP,
                           "keep_list_truncated": len(keep) > DEADLINK_LIST_CAP,
                           "files_involved": sorted({x["in_file"] for x in rec["dead"]}),
                           "files_to_fix": sorted({x["in_file"] for x in fix}),
                           "files_to_keep": sorted({x["in_file"] for x in keep})})
    all_dead.sort(key=lambda x: (x["in_file"], x["path"]))
    return {"by_scope": out_scopes,
            "actionable_dead": sum(o["dead_count"] for o in out_scopes),
            "actionable_fix": sum(o["dead_fix_count"] for o in out_scopes),
            "actionable_keep": sum(o["dead_keep_count"] for o in out_scopes),
            "verdict_note": "actionable_dead ＝ 作用域内死链总数；其中 actionable_fix 才是要动手的，"
                            "actionable_keep 是日志／外部原文／归档里的历史记录，**改它＝篡改当时的状态**。"
                            "分层判据只看文件名特征（DEADLINK_KEEP_MARKERS），不逐条人工判读",
            "all_dead_absolute_paths": len(all_dead),
            "all_dead_sample": all_dead[:20],
            "all_dead_note": "全盘计数含存档文档/日志/历史方案里的路径，那些**本来就该是死的**"
                             "（记的是当时的状态）⇒ 不是行动清单，行动清单看 by_scope",
            "counting_note": "dead_count 按**去重后的路径**数（同一路径在多个文件里只算一次，"
                             "归到首次出现的那个文件）⇒ 与「逐处出现次数」不是一个单位，别混读",
            "scanned_files": scanned, "distinct_paths_seen": n_paths,
            "adjudicated_registry": {k: _ADJ_CACHE[k] for k in
                                     ("path", "exists", "count", "error")},
            "scan_cap": DEADLINK_SCAN_CAP, "truncated": truncated}


# ─────────────────────────────────────────────────────────────
# 层 6：交付层
# ─────────────────────────────────────────────────────────────
def scan_delivery():
    tools = P["tools"]
    tool_py = sorted(f for f in os.listdir(tools) if f.endswith(".py")) if isdir(tools) else []
    hexgen, upload = [], []
    for f in tool_py:
        t = read(os.path.join(tools, f)) or ""
        if re.search(r"token_hex|token_urlsafe|urandom", t):
            hexgen.append(f)
        if re.search(r"scp\s|paramiko|UserKnownHostsFile", t):
            upload.append(f)
    lark = {"path": P["lark_cli"], "exists": isfile(P["lark_cli"]), "bytes": nb(P["lark_cli"]),
            "alt_path": P["lark_cli_alt"], "alt_exists": isfile(P["lark_cli_alt"]),
            "alt_bytes": nb(P["lark_cli_alt"])}
    # 深度上限 9：真身在 `.local\share\qoder\lark-cli\node_modules\@larksuite\cli\bin\`（第 8 层），
    # 深度 5 扫不到。根只圈几个点目录＋AppData\Local，不扫全盘，实测 2s 内。
    # 上限本身写进输出，读者知道这个数是**在深度 9 以内**数出来的，不是全盘。
    LARK_DEPTH = 9
    LARK_ROOTS = [r"C:\Users\若水\.local", r"C:\Users\若水\.hub", r"C:\Users\若水\.trae",
                  r"C:\Users\若水\.trae-cn", r"C:\Users\若水\.qoder",
                  r"C:\Users\若水\AppData\Local"]
    raw = {}          # normcase → 原样路径（去重用 normcase，输出用原样，否则盘符和小写看着像另一个路径）
    for r in LARK_ROOTS:
        if not isdir(r):
            continue
        base_depth = r.rstrip("\\").count("\\")
        for dp, dn, fn in os.walk(r):
            if dp.rstrip("\\").count("\\") - base_depth >= LARK_DEPTH:
                dn[:] = []
            dn[:] = [x for x in dn if x not in LARK_SKIP_DIRS]
            if "lark-cli.exe" in fn:
                p = os.path.join(dp, "lark-cli.exe")
                raw.setdefault(os.path.normcase(p), p)
    # 分桶：裸报一个总数会骗人——Doubao 沙箱里那十几份是**沙箱快照**，不是用户装的 CLI；
    # .trae/.trae-cn 是**别的 agent 的插件副本**。混在一起数出来的"11 处"没有决策价值。
    prod, other_agent, sandbox = [], [], []
    known = {os.path.normcase(P["lark_cli"]), os.path.normcase(P["lark_cli_alt"])}
    for c in sorted(raw):
        p = raw[c]
        if c in known:
            prod.append(p)
        elif "sandbox_envs_dir" in c or "\\doubao\\" in c:
            sandbox.append(p)
        else:
            other_agent.append(p)
    # ⚠ 测量卫生（10-02 批 2 收尾时抓出来的）：`convention_source` 以前是**写死的结论**
    #   "仅记忆件（无代码）"。批 2 把 review_publish.py 落地之后，这一栏就变成了假的现状断言，
    #   而它照样打印进 manifest ⇒ 违反 README §四.1「源码里不许出现写死的计数／结论」。
    #   现在改成由盘上存在性派生：有代码就写代码在哪，没有才写"仅记忆件"。
    hexgen_ok = isfile(P["review_publish"])
    review_local_ok = isdir(P["review_local"])
    d = {"tools_dir": tools, "tool_py_count": len(tool_py),
         "review_area": {
             "convention_source": ("记忆件约定 ＋ 已落成代码（%s）" % _short(P["review_publish"])
                                   if hexgen_ok else "仅记忆件（无代码）"),
             "local_dir": P["review_local"], "local_dir_exists": review_local_ok,
             "hex_generator_script": P["review_publish"],
             "hex_generator_exists": hexgen_ok,
             "upload_script_exists": hexgen_ok,
             "scripts_with_hex_gen": hexgen, "scripts_with_scp": upload},
         "feishu": {"cli": lark,
                    "cli_production": prod,
                    "cli_other_agent_copies": other_agent,
                    "cli_sandbox_snapshots": sandbox,
                    "cli_copy_count_raw": len(raw),
                    "cli_copy_count_meaningful": len(prod) + len(other_agent),
                    "cli_search_depth": LARK_DEPTH,
                    "cli_search_roots": LARK_ROOTS,
                    "cli_note": "raw 含 Doubao 沙箱快照（非用户安装）；meaningful＝真安装＋别的 agent 插件副本",
                    "in_PATH": bool(_which("lark-cli.exe") or _which("lark-cli")),
                    "wrapper_script": P["feishu_send"],
                    "wrapper_exists": isfile(P["feishu_send"]),
                    "send_verified": True, "receive_verified": False,
                    "note": "发送侧此前实测可靠；接收侧未证实 ⇒ 不作为能力承诺"},
         "post": {"ffmpeg_copies": sorted(_ffmpeg()), "fx_light": None}}
    fx, fx_var = _find_fx_light()
    # 分层按**实测路径**算，不靠字符串前缀判事（以前 GAP-D3 的判据是「layer 开头是不是"资产层"」，
    # 那等于把一条机器判据挂在一句给人看的说明文字上——措辞一改判据就错，故改成路径集合）。
    fx_del = [p for p in fx if p.startswith(P["tools"])]
    fx_ast = [p for p in fx if p not in fx_del]
    d["post"]["fx_light_copies"] = fx
    d["post"]["fx_light_variants"] = fx_var
    d["post"]["fx_light"] = fx[0] if fx else None
    d["post"]["fx_light_exists"] = bool(fx)
    d["post"]["fx_light_delivery_copies"] = fx_del
    d["post"]["fx_light_asset_copies"] = fx_ast
    d["post"]["fx_light_in_delivery"] = bool(fx_del)
    d["post"]["fx_light_layer"] = (
        None if not fx else
        "交付层（%d 份，无资产层副本）" % len(fx_del) if fx_del and not fx_ast else
        "交付层 %d 份＋资产层 %d 份（归档/历史遗留）" % (len(fx_del), len(fx_ast)) if fx_del else
        "资产层（跟着项目目录走，交付层没有固定落点）")
    d["post"]["searched_roots"] = FX_ROOTS

    if not d["review_area"]["hex_generator_exists"]:
        gap("GAP-D1", "delivery",
            "审片区**只有约定没有代码**：本地无 `%s`、无 hex 生成脚本、无上传脚本"
            "（tools 下 %d 个 .py 里命中 hex 生成的 %d 个、命中 scp 的 %d 个）"
            " ⇒ 16 位 hex 防猜、faststart、压到 ≈1 Mbps 全写在记忆件里，一条都没落成代码"
            % (P["review_local"], len(tool_py), len(hexgen), len(upload)),
            evidence=[tools],
            missing=[P["review_local"], P["review_publish"], P["feishu_send"]],
            measured={"tool_py_count": len(tool_py), "hex_gen_scripts": hexgen,
                      "scp_scripts": upload,
                      "local_dir_exists": isdir(P["review_local"])},
            severity="high")
    if not d["feishu"]["in_PATH"]:
        # ⚠ 测量卫生（10-02 批 2 收尾）：本条的判据以前只看 in_PATH，不看封装脚本在不在。
        #   批 2 落地 feishu_send.py（把两处真安装的全路径写死在脚本里）之后，本条自己写的
        #   补救措施「封装脚本要把路径锁死」**已经做到了**，缺口却照旧报 mid ⇒ 假阳。
        #   假阳比假阴安全，但它会让人反复去修一件已经修好的事，所以这里按"补救已落地"降级，
        #   并把**残余风险**如实写出来（不是简单关掉）：
        #     · 直接敲 `lark-cli` 的旧命令、别的 agent 的插件副本，仍然会断；
        #     · 封装脚本自己成了唯一落点——它被搬走／改名，整条飞书通路就哑（GAP-D3 同形）。
        wrapped = d["feishu"]["wrapper_exists"]
        tail = ("封装脚本 `%s` 已把全路径锁死 ⇒ **走它的调用不再受 PATH 影响**；残余风险两条："
                "① 直接敲 `lark-cli` 的旧命令与别的 agent 插件副本仍会断；"
                "② 封装脚本自己成了唯一落点，它被搬走／改名整条飞书通路就哑（与 GAP-D3 同形）"
                % _short(P["feishu_send"])) if wrapped else \
               "⇒ 每次调用要人记全路径，换个会话就断，封装脚本要把路径锁死"
        gap("GAP-D2", "delivery",
            "`lark-cli.exe` 有 %d 处真安装（%s）＋ %d 处别的 agent 插件副本，另有 %d 份 Doubao "
            "沙箱快照不算安装；%d 处都不在 PATH。%s"
            % (len(prod), "／".join(os.path.basename(os.path.dirname(os.path.dirname(p)))
                                    for p in prod) or "无",
               len(other_agent), len(sandbox), len(prod) + len(other_agent), tail),
            evidence=(prod + other_agent) or [P["lark_cli"]],
            measured={"production": prod, "other_agent_copies": other_agent,
                      "sandbox_snapshots": len(sandbox),
                      "search_depth": LARK_DEPTH,
                      "in_PATH": d["feishu"]["in_PATH"],
                      "wrapper_exists": wrapped,
                      "wrapper_script": P["feishu_send"] if wrapped else None,
                      "receive_verified": False},
            severity="low" if wrapped else "mid")
    if fx and (fx_ast or fx_var or not fx_del):
        # 10-03 批 7-4：`fx_light.py` 已按用户裁定（落点＝`D:\AIWorkflow\tools\post\`）搬进交付层，
        #   但本条**不静默关掉**——按 GAP-D2 同样的处理法：补救落地后降severity，残余风险如实写。
        #   残余＝资产层仍有实测副本／版本变体，且历史文档里的相对路径没回改（改历史＝造假）。
        residual = []
        if fx_ast:
            residual.append("资产层仍有实测副本 %d 份（%s）"
                            % (len(fx_ast), "；".join(_short(p) for p in fx_ast[:2])))
        if fx_var:
            residual.append("版本变体 %d 份仍在项目目录（%s）"
                            % (len(fx_var), "；".join(os.path.basename(p) for p in fx_var[:2])))
        if not fx_del:
            residual.append("`D:\\AIWorkflow\\tools` 下**一份都没有** ⇒ 交付层仍然没有落点")
        closed = bool(fx_del)
        gap("GAP-D3", "delivery",
            ("已收拢但有尾巴：" if closed else "后期能力没有固定落点：")
            + "叠光管线 `fx_light.py` 实测 %d 份，交付层 %d 份（%s）。%s"
            % (len(fx), len(fx_del),
               "；".join(_short(p) for p in fx_del[:1]) or "无",
               "；".join(residual)),
            evidence=fx + fx_var,
            measured={"copies": fx, "variants": fx_var, "layer": d["post"]["fx_light_layer"],
                      "delivery_copies": fx_del, "asset_copies": fx_ast,
                      "searched_roots": FX_ROOTS},
            severity="low" if closed else "mid",
            note="搬动走的是 copy→逐份 sha256→引用回扫→全绿才删源；归档份按「搬文件只复制不删源」保留。"
                 "历史文档里的旧相对路径**只加指针不改写**（改历史＝造假）。"
                 "残余风险与 GAP-D2 同形：交付层这份现在成了唯一正身，它被搬走／改名，"
                 "叠光管线又回到「找不到」。")

    # ── GAP-D4：批 2 之后交付层**有代码了**，但那套约定仍然没有规则真源 ──
    # 判据全部可测，不靠我断言：
    #   ① 通用层 5 份 md 里「审片区」命中几处（0 ＝ 规则层根本没管这件事）；
    #   ② 索引 §5 那张计划表里，有没有哪一份的职责含「交付／审片」。
    # 为什么要单列：批 2 把约定写进了脚本 docstring，docstring 是好东西，但它**不过关口**——
    # 改脚本里的码率／token 长度／删除策略，没有任何校验器会发现，也没有人审。
    # 这正是《索引》§2 说的"第二个漂移真源"的另一种长法：不是两份文档打架，
    # 而是**唯一那份根本不是文档**。
    gen_hits = []
    if isdir(P["gen"]):
        for f in sorted(os.listdir(P["gen"])):
            if f.lower().endswith(".md"):
                n = (read(os.path.join(P["gen"], f)) or "").count("审片区")
                if n:
                    gen_hits.append({"file": f, "hits": n})
    idx_txt = read(P["index_doc"]) or ""
    idx_delivery_owners = [ln.strip() for ln in idx_txt.splitlines()
                           if ln.strip().startswith("|") and "`G" in ln
                           and ("交付" in ln or "审片" in ln)]
    d["review_area"]["rule_source_hits_in_general_layer"] = gen_hits
    d["review_area"]["index_planned_owners_for_delivery"] = idx_delivery_owners
    if (hexgen_ok or d["feishu"]["wrapper_exists"]) and not gen_hits:
        gap("GAP-D4", "delivery",
            "交付层**有代码但没有规则真源**：审片区／飞书三件套的约定（16 位 hex 防猜、无鉴权、"
            "审完删、faststart、≈1 Mbps、三条消息顺序）现在只活在 `%s` 的 docstring 与记忆件里；"
            "通用层 %d 份 md 里「审片区」命中 **0** 处，索引 §5 计划的 10 份里**没有一份**的职责含交付／审片"
            " ⇒ 改这些约定不过任何关口、不经人审。⚠ 补规则文件时会撞编号：机器闸已占用 G1–G8／G11／G12，"
            "规则文件已占用 G1–G10，新增交付规则要么用别的字母前缀，要么先裁编号空间"
            % ("、".join(_short(x) for x in (P["review_publish"], P["feishu_send"]) if isfile(x)),
               len([f for f in os.listdir(P["gen"]) if f.lower().endswith(".md")])
               if isdir(P["gen"]) else 0),
            evidence=[p for p in (P["review_publish"], P["feishu_send"], P["gen"]) if os.path.exists(p)],
            missing=[os.path.join(P["gen"], "G?_交付与审片区.md")],
            measured={"general_layer_files_with_审片区": gen_hits,
                      "index_planned_owners_for_delivery": idx_delivery_owners,
                      "delivery_code_exists": True},
            severity="mid",
            note="写这份规则文件属于**顶层规则新增**，按元规则 M1 要用户点头；"
                 "本条只登记洞，不代裁编号方案")
    return d


def _which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def _ffmpeg():
    # ⚠ 用 normcase 去重：`D:\AIWorkflow\tools` 是 `D:\AIWorkflow` 的子目录，
    #   两个根都走一遍会把同一份 ffmpeg.exe 报两次（首跑就报了两次）。
    out = {}
    for r in (P["tools"], r"D:\AIWorkflow"):
        if isdir(r):
            for dp, dn, fn in os.walk(r):
                dn[:] = [x for x in dn if x not in SKIP_DIRS]
                for f in fn:
                    if f.lower() == "ffmpeg.exe":
                        p = os.path.join(dp, f)
                        out.setdefault(os.path.normcase(p), p)
    return [out[k] for k in sorted(out)]


# 后期工具（叠光管线）实际落点。首跑只在 `D:\AIWorkflow\tools` 找，报"不存在"——
# 实际它在**资产层的项目目录**里（`E:\创作\特效打斗练习件_20260930\工具\`）。
# 这本身就是一条架构事实：交付层的后期能力没有固定落点，跟着项目走。
FX_ROOTS = [r"D:\AIWorkflow\tools", P["assets"]]


def _find_fx_light():
    hits, variants = [], []
    for r in FX_ROOTS:
        if not isdir(r):
            continue
        for dp, dn, fn in os.walk(r):
            dn[:] = [x for x in dn if x not in SKIP_DIRS]
            for f in sorted(fn):
                p = os.path.join(dp, f)
                if f == "fx_light.py":
                    hits.append(p)
                elif f.startswith("fx_light") and f.endswith(".py"):
                    variants.append(p)      # 版本变体（v9b／pre_v10 之类），单列不混进正身计数
    return sorted(set(hits)), sorted(set(variants))


# ─────────────────────────────────────────────────────────────
# 层 7：记忆与技能层
# ─────────────────────────────────────────────────────────────
def _enum_project_memory_roots():
    """枚举 `.qoder\\projects\\*\\memory`——项目级记忆根**不是一个，是每个会话一个**。

    为什么要它（10-02 批 2 收尾抓出来的假阴）：原来 `P["mem_proj"]` 写死了
    `…projects\\C--Users----Documents-Qoder-2026-09-27-aed216e7\\memory` 一个路径，
    于是"项目级记忆根"这一栏永远只报那一个会话，**当前会话的那个根本不在账上**。
    写死路径 ＋ 路径背后的东西会随会话轮换 ⇒ 典型的"兜底清单≠现役配置"。
    这里改成枚举：目录名 sorted，只收真含 `memory` 子目录的，数字全部现算。"""
    parent = os.path.dirname(os.path.dirname(P["mem_proj"]))
    out = []
    if not isdir(parent):
        return parent, out
    for d in sorted(os.listdir(parent)):
        p = os.path.join(parent, d, "memory")
        if isdir(p):
            md = sorted(f for dp, dn, fn in os.walk(p) for f in fn
                        if f.lower().endswith(".md"))
            out.append({"session_dir": d, "path": p, "md_count": len(md),
                        "newest_md": newest_day(p, (".md",))})
    return parent, out


def scan_memory():
    roots = []
    for k, label in (("mem_user", "用户级 .qoder\\memory"),
                     ("mem_public", "E:\\公共记忆")):
        p = P[k]
        md = sorted(f for dp, dn, fn in os.walk(p) for f in fn
                    if f.lower().endswith(".md")) if isdir(p) else []
        idx = [os.path.join(dp, f) for dp, dn, fn in os.walk(p)
               for f in fn if f.upper() in ("MEMORY.MD", "INDEX.JSON")] if isdir(p) else []
        roots.append({"label": label, "path": p, "exists": isdir(p),
                      "md_count": len(md), "index_files": sorted(idx),
                      "newest_md": newest_day(p, (".md",))})
    proj_parent, proj_roots = _enum_project_memory_roots()
    proj_nonempty = [r for r in proj_roots if r["md_count"] > 0]
    proj_md_total = sum(r["md_count"] for r in proj_roots)
    proj_newest = max((r["newest_md"] for r in proj_roots if r["newest_md"]), default=None)
    hardcoded = P["mem_proj"]
    roots.insert(1, {"label": "项目级 memory（**按会话散落，共 %d 处**）" % len(proj_roots),
                     "path": proj_parent, "exists": isdir(proj_parent),
                     "md_count": proj_md_total,
                     "index_files": sorted(os.path.join(r["path"], "MEMORY.md")
                                           for r in proj_roots
                                           if isfile(os.path.join(r["path"], "MEMORY.md"))),
                     "newest_md": proj_newest})
    sk = P["skills"]
    sk_dirs = sorted(d for d in os.listdir(sk)
                     if isdir(os.path.join(sk, d))) if isdir(sk) else []
    refs = P["skill_refs"]
    ref_files = sorted(f for f in os.listdir(refs)) if isdir(refs) else []
    ref_new = newest_day(refs)
    ch_new = newest_day(P["channels"], (".md",))
    lag = None
    if ref_new and ch_new:
        try:
            lag = (datetime.strptime(ch_new, "%Y-%m-%d")
                   - datetime.strptime(ref_new, "%Y-%m-%d")).days
        except ValueError:
            lag = None
    # ── 10-03 接线：`sync_skill.py --json` 是这件事的**唯一实现**，本扫描器改成消费者 ──
    # 为什么算"接线"而不是"再加一个数"：以前"落后几天"有两处算法（这里按目录全扫取最新日，
    # 那边按通道清单取 mtime），两处都可以被引用 ⇒ 同一件事两个真源，迟早互相打脸
    # （本轮就撞见过：一边 9 天、一边 9.9 天——分母不同，都不是错，但引用者不知道信谁）。
    # 规矩沿用 `channel_of()` 那次：**探针拿得到就以它为准；拿不到退回本地算法并如实标 fallback**。
    probe, probe_err = run_sync_probe()
    authoritative = "sync_skill.py --json"
    probe_max_lag = None
    if probe:
        lags = [x for x in (probe.get("upstream_lag_days") or []) if isinstance(x, (int, float))]
        probe_max_lag = max(lags) if lags else None
    else:
        authoritative = "本扫描器（兜底算法，探针没跑起来）"
    if probe_max_lag is not None:
        lag_reported = probe_max_lag
    else:
        lag_reported = lag
    d = {"roots": roots,
         "project_memory": {
             "parent": proj_parent,
             "root_count": len(proj_roots),
             "nonempty_count": len(proj_nonempty),
             "md_total": proj_md_total,
             "newest_md": proj_newest,
             "roots": proj_roots,
             "hardcoded_path_in_P": hardcoded,
             "hardcoded_exists": isdir(hardcoded),
             "hardcoded_is_current": bool(proj_roots) and
                 proj_roots[-1]["path"] == hardcoded,
             "note": "项目级记忆**按会话隔离**：每开一个新工作目录就多一个根，跨会话不共享。"
                     "长期的只有用户级与 E:\\公共记忆 两处；这里如实把 %d 处全列出来，"
                     "不再只盯写死的那一个。" % len(proj_roots)},
         "skills": {"path": sk, "exists": isdir(sk), "dir_count": len(sk_dirs),
                    "dirs": sk_dirs},
         "skill_refs": {"path": refs, "exists": isdir(refs),
                        "file_count": len(ref_files), "files": ref_files,
                        "newest_day": ref_new,
                        "channel_docs_newest_day": ch_new,
                        # ↓ 三个字段是**兜底算法**的结果，只有探针没跑起来时才当数看
                        "lag_days_vs_channel_docs": lag,
                        "lag_days_reported": lag_reported,
                        "lag_authority": authoritative,
                        "sync_probe": probe, "sync_probe_error": probe_err,
                        "probe_mirror": (probe or {}).get("mirror"),
                        "probe_residual": {k: (probe or {}).get(k) for k in
                                           ("residual_hits", "residual_labels")}},
         "sync_script": {"path": P["sync_skill"], "exists": isfile(P["sync_skill"])}}

    if probe_err:
        gap("GAP-M1b", "memory_skill",
            "三轴检查器 `sync_skill.py --json` **没跑起来**（%s）⇒ 现在报的落后天数来自扫描器的"
            "兜底算法，与检查器那份**不是同一把尺**（两边分母不同：一个按通道清单取 mtime，"
            "一个按目录全扫取最新日）。这属**未测量**，不等于「没问题」。" % probe_err,
            evidence=[P["sync_skill"], refs], measured={"probe_error": probe_err,
                                                       "fallback_lag_days": lag},
            severity="mid")
    mm = (probe or {}).get("mirror") or {}
    if probe and (mm.get("stale") or mm.get("missing") or mm.get("errors")):
        gap("GAP-M1c", "memory_skill",
            "skill 镜像副本与事实源不一致：落后 %d 份、缺失 %d 份、读失败 %d 份（探针 %s）"
            " ⇒ 事实源改了但分发出去的那份还是旧的，引用者会读到旧口径"
            % (len(mm.get("stale") or []), len(mm.get("missing") or []),
               len(mm.get("errors") or []), "sync_skill.py --json"),
            evidence=[P["sync_skill"]], measured=mm, severity="mid")
    # ⚠ 探针挂了也**照样报 GAP-M1**（用兜底算法那个数），旁边再挂一条 GAP-M1b 说清数是从哪来的。
    #   原来我写成 `and not probe_err`，那等于"探针一坏信号就消失"——假阴比假阳坏，正是本项目翻过三次车的那类。
    if lag_reported:
        gap("GAP-M1", "memory_skill",
            "skill 事实源 `references\\` %d 篇最新只到 %s，而通道真源已到 %s ⇒ "
            "落后 **%s 天**（数值取自 `%s`，扫描器不再是第二处算法）"
            " ⇒ 两份副本之间没有同步器，skill 里的通道口径是旧的"
            % (len(ref_files), ref_new, ch_new, lag_reported, authoritative),
            evidence=[refs, P["channels"]],
            missing=[] if isfile(P["sync_skill"]) else [P["sync_skill"]],
            measured={"ref_files": len(ref_files), "ref_newest": ref_new,
                      "channel_newest": ch_new, "lag_days": lag_reported,
                      "lag_authority": authoritative,
                      "fallback_lag_days_local": lag,
                      "probe_max_lag_days": probe_max_lag,
                      "sync_script_exists": isfile(P["sync_skill"])},
            severity="mid")
    # GAP-M2：项目级记忆**按会话隔离**这件事本身是设计，不是 bug；
    # 但它有一个会漏的后果——上一次会话写进项目级的东西，这一次读不到。
    # 判据用测量值：非空根 > 1 就说明内容确实散在多个会话里。
    if len(proj_nonempty) > 1:
        gap("GAP-M2", "memory_skill",
            "项目级记忆**按会话隔离**：实测 %d 个根（%d 个非空、共 %d 份 md，最新 %s），"
            "而跨会话能读到的只有用户级（%d 份）与 `E:\\公共记忆`（%d 份）两处。"
            "⇒ 上一次会话写进项目级的结论，这一次**读不到**；架构类知识若落在项目级就等于半衰期一个会话。"
            "建议口径：本项目（若水AI电影）的架构结论落用户级记忆或 `E:\\公共记忆`，"
            "项目级只放当次会话的临时状态"
            % (len(proj_roots), len(proj_nonempty), proj_md_total, proj_newest or "未测量",
               roots[0]["md_count"], roots[-1]["md_count"]),
            evidence=[proj_parent, P["mem_user"], P["mem_public"]],
            measured={"project_root_count": len(proj_roots),
                      "project_nonempty": len(proj_nonempty),
                      "project_md_total": proj_md_total,
                      "user_md": roots[0]["md_count"],
                      "public_md": roots[-1]["md_count"],
                      "hardcoded_path_still_in_P": hardcoded},
            severity="mid",
            note="这条不是要求搬记忆，是要求**写记忆时选对层**；判据是枚举实测，"
                 "不再依赖 P 里那个写死的会话路径")
    return d


# ─────────────────────────────────────────────────────────────
# 开关矩阵（"没有单一真源"这条缺口的证据）
# ─────────────────────────────────────────────────────────────
def scan_switches(cfg_txt):
    """开关矩阵。★批 4·2：**清单从注册表读**，本函数只负责按声明的 `reader` 现取值。

    原来这五处的"名字＋读法"写死在本函数里，那是继 `channel_of()`／通道真源 md／CHANNELS 常量
    之后的**第四份抄本**。现在：注册表声明"有哪些开关、住在哪、怎么读"，
    扫描器只读值；读不到注册表才退回兜底清单，并在 manifest 里写明 provenance（＋GAP-S2 由 §通道层报）。
    """
    knobs = None
    t = read(P["knobs"])
    if t:
        try:
            knobs = json.loads(t)
        except ValueError:
            knobs = {"parse_error": True}
    fallback = [
        {"name": "preflight", "kind": "跑前自审总开关", "file": P["config"],
         "key": "preflight", "reader": "yaml", "single_source": True},
        {"name": "preflight_strict", "kind": "warn 是否升级为拦", "file": P["config"],
         "key": "preflight_strict", "reader": "yaml", "single_source": True},
        {"name": "knobs.on", "kind": "H3 法条临时开关", "file": P["knobs"],
         "key": "on", "reader": "json", "single_source": False},
        {"name": "prompt_kind", "kind": "每个 workflow 自己的格式声明",
         "file": P["workflows"], "key": "prompt_kind", "reader": "dir", "single_source": False},
        {"name": "channel_of() 兜底", "kind": "通道归属的最终裁决",
         "file": P["preflight"], "key": "channel_of", "reader": "code", "single_source": False},
    ]
    regfile, _why = load_channels_registry(P["channels_registry"])
    declared = (regfile or {}).get("config_switches")
    src = "channels_registry.json" if regfile else "scan_system.兜底清单"
    if not declared:
        declared = fallback
        src = "scan_system.兜底清单（注册表里没有 config_switches 段）"

    sw = []
    for s in declared:
        name, key, reader, f = s.get("name"), s.get("key"), s.get("reader"), s.get("file")
        line = value = None
        if reader == "yaml":
            line, value = yaml_scalar_line(cfg_txt, key), yaml_scalar(cfg_txt, key)
        elif reader == "json":
            value = (knobs or {}).get(key) if isinstance(knobs, dict) else None
            if s.get("derived"):
                # 🔴 2026-10-19 用户裁定：knobs.json 是**派生账本**，不是配置。
                #   以前这里把 `on: []` 当"当前开关状态"报，而那份快照实测是 22 天前
                #   某次 `h3_shots.py` 重出提示词表时留下的 ⇒ 报出来的"现在的配置"是旧的。
                #   改成如实说：这是谁写的、多久没更新、要看真状态该去问谁。
                age = None
                try:
                    age = int((time.time() - os.path.getmtime(f)) / 86400)
                except Exception:
                    pass
                value = ("派生账本，不是配置：由 `tools/h3_shots.py` 每次重出提示词表时写；"
                         "本次快照 %s 天前，`on`=%s ⇒ 要问「现在开着哪几条」应读 h3_shots 的 "
                         "KNOBS 源码而不是这个文件"
                         % ("%d" % age if age is not None else "年龄未知",
                            (knobs or {}).get("on") if isinstance(knobs, dict) else "读不到"))
        elif reader == "dir":
            value = "逐 yaml"
        elif reader == "code":
            line = (grep(r"^def channel_of\(", P["preflight"]) or [(None,)])[0][0]
            value = "代码常量"
        else:
            value = "未测量（注册表没声明 reader＝扫描器不知道怎么读，不猜）"
        sw.append({"name": name, "kind": s.get("kind"), "file": f, "key": key,
                   "reader": reader, "line": line, "value": value,
                   "single_source": bool(s.get("single_source")),
                   "derived": bool(s.get("derived")),     # 派生账本≠配置（10-19 裁定）
                   "authority": s.get("authority")})
    n_single = sum(1 for x in sw if x["single_source"])
    if n_single < len(sw):
        gap("GAP-S1", "cross_layer",
            "想知道「系统现在的配置」要读 %d 处（%s），其中只有 %d 处是单一真源"
            " ⇒ 清单本身已收进注册表（本轮），但**值仍散在 4 个地方**（config.yaml／tmp 里的 knobs.json／"
            "逐 yaml／一段代码），一处改完不会通知其他处"
            % (len(sw), "、".join(str(x["name"]) for x in sw), n_single),
            evidence=[x["file"] for x in sw if x["file"] and ex(x["file"])],
            measured={"switch_count": len(sw), "single_source": n_single,
                      "switches": [x["name"] for x in sw],
                      "list_provenance": src},
            severity="high")
    return {"switches": sw, "count": len(sw), "single_source_count": n_single,
            "list_provenance": src,
            "knobs_file": {"path": P["knobs"], "exists": isfile(P["knobs"]),
                           "content_keys": sorted(knobs.keys()) if isinstance(knobs, dict) else None}}


# ─────────────────────────────────────────────────────────────
# 端口占用（跨层：引擎／工具／启动脚本各说各的）
# ─────────────────────────────────────────────────────────────
# label 是**人工注记**不是测量值：脚本量的是"这个端口在哪些文件里被声明"，
# 至于它是什么服务，得由读过代码的人写一句。注记来源单列，免得被当成实测结论。
PORT_LABELS = {
    8189: ("ComfyUI 唯一生产实例（H3 那套，0.30.2；引擎 config 指向它）", "人工注记"),
    8188: ("ComfyUI 旧便携包（0.29.2）——引擎已不指向，但 tools 下的脚本仍写死", "人工注记"),
    8787: ("引擎自带 webui（start-webui.bat / webui.py）", "人工注记"),
    7890: ("HTTP 代理端口（不是本机服务；记忆件记三处代理全关）", "人工注记"),
    11500: ("Ollama 改用的端口（默认 11434 与档1冲突，engine\\README.md:121 记的绕法）",
            "人工注记"),
}
PORT_SCAN_EXTS = (".py", ".yaml", ".yml", ".bat", ".md", ".json")
PORT_RX = re.compile(r"(?:127\.0\.0\.1|localhost):(\d{4,5})\b|--port[=\s]+(\d{4,5})\b")


def scan_ports(cfg_txt):
    """量：每个端口在哪些**声明类**文件里出现（.log 不算声明，单列）。

    为什么要单列这一节：GAP-S1 说"配置没有单一真源"，端口是这条最具体的证据——
    引擎 config 指 8189，而 tools 下一批 LoRA 测试脚本仍写死 8188。
    只报"有几个端口"没有决策价值，报"谁在哪个文件里声明了它"才有。
    """
    roots = [P["engine"], P["tools"]]
    top_files = [os.path.join(P["channels"], f) for f in sorted(os.listdir(P["channels"]))] \
        if isdir(P["channels"]) else []
    top_files = [f for f in top_files
                 if os.path.isfile(f) and f.lower().endswith(PORT_SCAN_EXTS)]
    decl, logs = {}, {}
    for r in roots:
        if not isdir(r):
            continue
        for dp, dn, fn in os.walk(r):
            dn[:] = [x for x in dn if x not in SKIP_DIRS]
            for f in sorted(fn):
                p = os.path.join(dp, f)
                low = f.lower()
                if low.endswith(".log"):
                    tgt = logs
                elif low.endswith(PORT_SCAN_EXTS):
                    tgt = decl
                else:
                    continue
                t = read(p)
                if not t:
                    continue
                for mm in PORT_RX.finditer(t):
                    port = int(mm.group(1) or mm.group(2))
                    tgt.setdefault(port, []).append(
                        "%s:%d" % (p, t[:mm.start()].count("\n") + 1))
    prod_port = None
    bu = yaml_in_section(cfg_txt, "comfyui", "base_url")[0] or ""
    mb = re.search(r":(\d{4,5})", bu)
    if mb:
        prod_port = int(mb.group(1))
    out = []
    for port in sorted(set(decl) | set(logs)):
        lab, src = PORT_LABELS.get(port, (None, None))
        out.append({"port": port,
                    "service": lab, "label_source": src,
                    "is_engine_production": port == prod_port,
                    "declared_in_count": len(decl.get(port, [])),
                    "declared_in": sorted(decl.get(port, []))[:12],
                    "in_logs_only": not decl.get(port) and bool(logs.get(port)),
                    "log_hits": len(logs.get(port, []))})
    # 缺口：非生产端口仍被**声明类**文件写死
    stray = [o for o in out if not o["is_engine_production"] and o["declared_in_count"]
             and o["port"] != 7890]
    if stray:
        gap("GAP-P1", "cross_layer",
            "引擎生产实例是 %s 端口，但另有 %d 个端口仍被声明类文件写死：%s"
            " ⇒ 端口这件事也没有单一真源（与 GAP-S1 同族，但这条是可执行的具体证据）"
            % (prod_port, len(stray),
               "；".join("%s（%d 处，如 %s）" % (o["port"], o["declared_in_count"],
                                               o["declared_in"][0]) for o in stray)),
            # ⚠ 必须 rsplit 不是 split：Windows 路径自带盘符冒号（`D:\...py:88`），
            #   split(":")[0] 会得到 "D"，证据自检当场就把这条标成失效（首跑就是这么抓出来的）。
            evidence=sorted({x.rsplit(":", 1)[0] for o in stray for x in o["declared_in"][:3]}),
            measured={"production_port": prod_port,
                      "stray_ports": [{"port": o["port"], "count": o["declared_in_count"],
                                       "service": o["service"]} for o in stray]},
            severity="mid",
            note="⚠ 10-02 实测纠正（免得下一轮把它当技术债\"修好\"）：8188 那 20 处全是 "
                 "09-05／09-11 的 LoRA 试跑脚本（`compare_epochs_realistic.py` 等），"
                 "**没有任何别处引用**，且指向的是仍然存在的旧实例 0.29.2 —— 所以它们不是"
                 "跑不通，是历史件。把它们改到 8189 是**错的**：那会让 SDXL/FLUX 的测试脚本"
                 "去打 H3 的生产实例。真要收拾，办法是归档或标注，不是改端口。")
    return {"production_port": prod_port,
            "production_source": "%s（comfyui.base_url）" % P["config"],
            "ports": out,
            "scanned_roots": roots + [P["channels"] + "（仅顶层文件）"],
            "note": ".log 命中不算声明（记的是当时跑过什么），单列 log_hits；"
                    "service 字段是人工注记，label_source 已标明"}


# ─────────────────────────────────────────────────────────────
# 未纳管的外部资产位置（明确不碰，但要登记）
# ─────────────────────────────────────────────────────────────
EXTERNAL_ASSET_ROOTS = [
    r"E:\LocalAI", r"E:\FLUX_Workflow", r"E:\hailluoai",
    r"E:\6a8b0dd1b3ead574d77ceda3",
    r"C:\Users\若水\Documents\Qoder\2026-08-27\4543d0f4",
    r"E:\图像影音资源池", r"E:\_统一备份", r"E:\归档区", r"E:\BaiduNetdiskDownload",
]


def scan_external_assets():
    out = []
    for r in EXTERNAL_ASSET_ROOTS:
        e = {"path": r, "exists": isdir(r)}
        if isdir(r):
            s = walk_stats(r)
            e.update({"files": s["files"], "images": s["images"], "gib": s["gib"]})
        out.append(e)
    present = [x for x in out if x["exists"]]
    absent = [x["path"] for x in out if not x["exists"]]
    # ── 用户 2026-10-02 裁定：GAP-X1 取 **(a) 只纳入架构口径** ──
    # (a) 的原话是「升成资产层正式成员、算总量、进去重与死链扫描」；(b)「纳入生产可达」未裁。
    # 本轮**做到的**：总量口径纳入（下面 architecture_scope 那组字段）＋ 成员身份声明。
    # 本轮**没做到的**：去重与死链扫描的**实际覆盖**——外部 8 处共约 4.4 万文件，
    #   现有 HASH_CAP=40 与死链扫描的作用域都是按 `E:\创作` 一个根设计的，直接放开会把
    #   4 秒的扫盘拖到分钟级、且哈希上限一触顶就大面积"未测量"⇒ **先如实标 not_yet_scanned**，
    #   不谎称已覆盖（假阴比假阳坏，但假阳会让人以为洞已经堵上）。
    ext_files = sum(x.get("files", 0) for x in present)
    ext_images = sum(x.get("images", 0) for x in present)
    ext_gib = round(sum(x.get("gib", 0.0) for x in present), 2)
    if present:
        gap("GAP-X1", "assets",
            "`E:\\创作` 之外这 %d 处资产位置**已按用户 10-02 裁定 (a) 升为资产层正式成员**（算进总量）：%s%s。"
            "**但 (a) 的第二半还没做**：去重与死链扫描的实际覆盖仍是 `E:\\创作` 一个根"
            "（外部 8 处共 %s 文件未进去重、未进死链扫描 ⇒ 标 `not_yet_scanned`）。"
            "(b)「纳入生产可达」**未裁也未做**：不改那 76 个硬编码 `E:\\创作` 的脚本、"
            "不让工作流直接引用这些位置"
            % (len(present),
               "、".join("%s(%.1f GiB)" % (x["path"], x["gib"]) for x in present[:6]),
               "；已不存在的 %d 处：%s" % (len(absent), "、".join(absent)) if absent else "",
               format(ext_files, ",")),
            evidence=[x["path"] for x in present],
            measured={"present": present, "absent": absent,
                      "external_files": ext_files, "external_images": ext_images,
                      "external_gib": ext_gib,
                      "ruling": "(a) 只纳入架构口径（2026-10-02 用户裁）",
                      "done": "总量口径纳入 ＋ 成员身份声明",
                      "not_yet_scanned": True,
                      "not_done": "去重与死链扫描的实际覆盖；(b) 生产可达（未裁）"},
            severity="mid", ruling=False,
            note="裁定已下 ⇒ 不再是待裁项；留着这条 gap 是因为**裁定只执行了一半**。"
                 "其中已不存在的那些说明旧方案里的体积数字已过期")
    return {"roots": out, "present_count": len(present), "absent": absent,
            "architecture_scope": {
                "ruling": "(a) 只纳入架构口径（2026-10-02 用户裁）",
                "member_root_count": 1 + len(present),
                "external_files": ext_files, "external_images": ext_images,
                "external_gib": ext_gib,
                "dedup_and_deadlink_covered": False,
                "note": "外部根自此是资产层**正式成员**（总量口径）；去重与死链的实际扫描范围"
                        "仍只有 `E:\\创作`，放开前要先定哈希上限与作用域，否则 4 秒的扫盘会变分钟级"}}


# ─────────────────────────────────────────────────────────────
# 规则层过期红警报（本轮新查出，校验器抓不到）
# ─────────────────────────────────────────────────────────────
# 语义分类的词表。**判据全部取自行内可见特征**（删除线奇偶、现场窗口里的现状词／更正词／
# 条件词），不写死文件名或行号——写死就等于把我这一次的人工判读固化成假事实（M1）。
# 分类顺序是有意的：先看这处现场是不是已经被更正/是条件句/是过程记录，再看它是不是现状断言。
ASSERT_WORDS = ("现状", "当前", "现在", "目前")
FIXED_WORDS = ("已裁", "闸已开", "已开闸", "已修", "已恢复", "已开", "现为")
PROCESS_WORDS = ("改口", "一律注明", "加注", "晨查出", "当时")
COND_PAIRS = (("不受", "影响"), ("可临时", "关掉"), ("若要", "清空"), ("确要", "改成"))
CLAIM_WINDOW = 60          # 现场窗口半径（字符）
PF_RX = re.compile(r"preflight", re.I)
OFF_RX = re.compile(r"off|关闭|关着|关掉", re.I)
CITE_RX = re.compile(r"config\.yaml\s*[:：]\s*(\d{1,4})")


def _off_scenes(ln, tail=""):
    """把一行里每个「preflight … off/关闭」的现场拆出来，逐个分类。
    返回 [(类别, 理由)]，类别 ∈ asserts/asserts_fixed/fixed/cond/process/plain。
    只看窗口，不看整行：同一行里既有过期红标、又有 09-28 的更正结论是常态，
    按整行判会把两种现场混成一种（上一版就是这么把 2 处报成 5 处的）。
    ⚠ 类别必须是**枚举**，下游只许看枚举、不许在理由串里做子串匹配——
      理由串自己就含「更正」二字，拿它判会把「窗口内无更正」误读成「已更正」。"""
    out = []
    for m in PF_RX.finditer(ln):
        i = m.start()
        w = ln[max(0, i - CLAIM_WINDOW): i + CLAIM_WINDOW]
        # 表格行是一整行一个逻辑单元：登记表的 C10 那行几百字，🔴「当前关闭」在第二格、
        # ✅「09-28 已裁＝开闸」在最后一格。拿 ±60 字符去看，同一行里的更正永远"看不见"
        # ⇒ 会把已更正的行报成未更正。所以**只有"本行有没有更正"这一项**放宽到整行。
        # ⚠ 反过来，"是不是现状断言""是不是条件句""有没有 off 这个字面"**必须留在局部窗口**——
        #   否则会像上一版那样：C10 行里别处有个「可临时…关掉」，就把第二格那句真·现在时
        #   断言整个吞成条件句 ⇒ 从假阳变成**假阴**（把过期说成没问题），那比假阳更坏。
        is_row = ln.lstrip().startswith("|")
        w_fix = ln if is_row else w
        fix_scope = "整行（表格行）" if is_row else "±%d 窗口" % CLAIM_WINDOW
        if not OFF_RX.search(w):
            continue                      # 这个现场说的是 on，不算
        # 删除线：match 之前的 `~~` 个数为奇 ⇒ 这处现场被划掉了
        if ln[:i].count("~~") % 2 == 1:
            out.append(("fixed", "原文带删除线（已划掉）"))
            continue
        if any(a in w and b in w for a, b in COND_PAIRS):
            out.append(("cond", "条件句（说的是「若要／可临时／不受…影响」，不是断言开关状态）"))
            continue
        if any(k in w for k in PROCESS_WORDS):
            out.append(("process", "过程记录（记的是那次怎么改文档，不是现在什么状态）"))
            continue
        has_fix = [k for k in FIXED_WORDS if k in w_fix]
        has_assert = [k for k in ASSERT_WORDS if k in w]
        # 勘误块常常写在**下一行**（markdown 的 `> **10-02 勘误**：…` 是惯例），
        # 只看本行就会把"已经按规矩追加了勘误"的句子当成没更正的过期断言。
        # 所以补一个 tail：只认明确的勘误字样，不认泛化的"已裁"，免得隔壁不相干的行替它背书。
        has_annot = [k for k in ANNOT_WORDS if k in (tail or "")]
        if has_assert and has_annot and not has_fix:
            out.append(("annotated", "现状断言词 %s，本行无更正，但**下面紧跟勘误块**（%s）"
                        % ("／".join(has_assert), "／".join(has_annot))))
        elif has_assert and has_fix:
            out.append(("asserts_fixed", "现状断言词 %s ＋ 更正词 %s 写在%s"
                        % ("／".join(has_assert), "／".join(has_fix), fix_scope)))
        elif has_assert:
            out.append(("asserts", "现状断言词 %s，窗口内无更正词" % "／".join(has_assert)))
        elif has_fix:
            out.append(("fixed", "同窗口已有更正词 %s" % "／".join(has_fix)))
        else:
            out.append(("plain", "只提到 off，无现状断言词也无更正词"))
    return out


ASSERT_KINDS = ("asserts", "asserts_fixed", "annotated")
FIXED_KINDS = ("fixed", "asserts_fixed", "annotated")
# tail（本行之后几行）里只认这几个"确系勘误"的字样；比行内的 FIXED_WORDS 严，
# 因为隔壁一行写"已裁"未必是在说本行这句。
ANNOT_WORDS = ("勘误", "更正：", "更正＝", "10-02 更正", "现状已过期", "已按规矩追加", "已过期勿引")
ANNOT_TAIL_LINES = 4         # 往下看几行找勘误块


def _line_verdict(scenes):
    """一行里多个现场汇总成一行结论（只看枚举，不读理由串）。
    有现状断言 ＋ 同行也有更正 ⇒ half（事实记对了，🔴 与现在时措辞没降级）；
    有现状断言 ＋ 更正只写在下面 ⇒ annotated（追加过勘误，但本行时态没改）；
    只有现状断言、上下都没有更正 ⇒ asserts（真过期，要动手）；
    其余 ⇒ mention（不算过期，列出来只为留痕）。"""
    if not scenes:
        return "none", "行内无 preflight+off 现场"
    kinds = {k for k, _ in scenes}
    why = "；".join(sorted({r for _, r in scenes}))
    a = bool(kinds & set(ASSERT_KINDS))
    if not a:
        return "mention", why
    if kinds & {"asserts"}:
        return "asserts", why
    if "asserts_fixed" in kinds:
        return "half", why
    return "annotated", why


def _cite_check(ln, cfg_lines):
    """断言行里引的 `config.yaml:NN` 到底指没指到 preflight 那一行。
    行号锚漂没漂是 check_layers.py 的活；**引到的行内容对不对**只有这里查得出来。"""
    out = []
    for m in CITE_RX.finditer(ln):
        n = int(m.group(1))
        got = cfg_lines[n - 1].strip() if 1 <= n <= len(cfg_lines) else None
        out.append({"cite_line": n, "line_exists": got is not None,
                    "holds_preflight_key": bool(got) and "preflight" in got.lower(),
                    "actual_text": (got or "")[:80]})
    return out


def scan_stale_alerts(cfg_txt):
    """通用层里写死的状态断言 vs 盘上真值。
    现在只查一条：preflight。判据是**语义**的，check_layers.py 的行号锚查不出来
    （行号没漂、锚句还在，只是内容过期了）。"""
    real = (yaml_scalar(cfg_txt, "preflight") or "").lower()
    real_line = yaml_scalar_line(cfg_txt, "preflight")
    cfg_lines = cfg_txt.split("\n")
    hits, asserts, half, annotated, mention, unclear = [], [], [], [], [], []
    for p in sorted(os.listdir(P["gen"])) if isdir(P["gen"]) else []:
        fp = os.path.join(P["gen"], p)
        t = read(fp)
        if not t:
            continue
        all_lines = t.split("\n")
        for i, ln in enumerate(all_lines, 1):
            if "preflight" not in ln.lower():
                continue
            tail = "\n".join(all_lines[i:i + ANNOT_TAIL_LINES])
            scenes = _off_scenes(ln, tail)
            if not scenes:
                continue
            verdict, why = _line_verdict(scenes)
            h = {"file": fp, "line": i, "verdict": verdict, "why": why,
                 "scenes": [{"kind": k, "why": r} for k, r in scenes],
                 "text": ln.strip()[:200]}
            cites = _cite_check(ln, cfg_lines)
            if cites:
                h["cites"] = cites
                h["cite_wrong"] = [c["cite_line"] for c in cites
                                   if not c["holds_preflight_key"]]
            hits.append(h)
            {"asserts": asserts, "half": half, "annotated": annotated,
             "mention": mention}.get(verdict, unclear).append(h)
    # stale ＝ 会误导读者的那些。annotated（本行还是现在时，但下面紧跟了勘误块）
    # **不算未更正**：按 §2 的规矩勘误就是追加在后面的。它只算"🔴 与时态没降级"，
    # 记低级别、不记 high。
    stale = (asserts + half) if real == "on" else []
    # 引到的行号对不对，**只对真在断言 preflight 状态的那些行判**。
    # 只是提及的行可能引的是别的键——登记表:81(R3) 引 `config.yaml:61` 指的是
    # `characters_needing_anchor`，对 R3 说的那件事引号是**对的**；拿 preflight 的行号去判它
    # 就是把对的报成错的（M1：不许把推理写成事实）⇒ 这类不判，单列出来留痕。
    drift = [{"file": h["file"], "line": h["line"], "verdict": h["verdict"],
              "wrong": h["cite_wrong"], "real_line": real_line}
             for h in (asserts + half + annotated) if h.get("cite_wrong")]
    not_judged = [{"file": h["file"], "line": h["line"], "verdict": h["verdict"],
                   "cites": h["cites"],
                   "why_not_judged": "该行不是现状断言（判为 %s），引的可能是别的键" % h["verdict"]}
                  for h in (mention + unclear) if h.get("cites")]
    d = {"real_value": real, "real_line": real_line, "real_source": P["config"],
         "note": "verdict 分五档：asserts＝真过期断言、上下都没有更正（要动手）／"
                 "half＝同一行已写了更正结论但 🔴 与现在时措辞没降级／"
                 "annotated＝本行仍是现在时，但**下面紧跟了勘误块**（按索引 §2 步骤 4 的规矩这就算更正到位，"
                 "只是 🔴／时态没降级）／mention＝已更正或条件句或过程记录（不算过期）／"
                 "unclear＝判不了（不计数，留给人读）",
         "annot_tail_lines": ANNOT_TAIL_LINES,
         "claims_found": hits,
         "asserts_count": len(asserts), "asserts": asserts,
         "half_count": len(half), "half": half,
         "annotated_count": len(annotated), "annotated": annotated,
         "mention_count": len(mention), "mention": mention,
         "unclear_count": len(unclear), "unclear": unclear,
         "stale_count": len(stale), "stale": stale,
         "cite_drift": drift, "cites_not_judged": not_judged}
    located = lambda hs: "、".join("%s:%d" % (os.path.basename(h["file"]), h["line"]) for h in hs) or "无"
    if asserts:
        gap("GAP-R3", "rules",
            "通用层有 %d 处**断言现在 preflight 是 off、且上下都没有更正**（%s），"
            "而 `%s:%s` 实测是 `%s` ⇒ 读规则层的人会以为闸门全关。"
            "另有 同行已更正 %d 处、下面追了勘误块 %d 处、只是提到 %d 处、判不了 %d 处，这四类不算未更正。"
            "%s行号锚没漂、锚句也在，所以 check_layers.py 查不出来，只能靠这条语义比对"
            % (len(asserts), located(asserts),
               os.path.basename(P["config"]), real_line, real,
               len(half), len(annotated), len(mention), len(unclear),
               ("其中 %d 处引的行号实测不含 `preflight` 键（%s；真值在 `:%s`）。"
                % (len(drift),
                   "、".join("%s:%d 引 `:%d`" % (os.path.basename(x["file"]), x["line"], w)
                             for x in drift for w in x["wrong"]), real_line)) if drift else ""),
            evidence=[h["file"] for h in asserts] + [P["config"]],
            measured={"real": real, "real_line": real_line, "asserts": asserts,
                      "half": half, "annotated": annotated,
                      "mention": [{"file": h["file"], "line": h["line"], "why": h["why"]}
                                  for h in mention],
                      "unclear": [{"file": h["file"], "line": h["line"], "text": h["text"][:120]}
                                  for h in unclear],
                      "cite_drift": drift, "cites_not_judged": not_judged},
            severity="high",
            note="修法是**追加勘误注记**（写在原句下面即可，本探针会往下看 %d 行认它），"
                 "不是删掉原句——原句是当时的真状态，属出处证据" % ANNOT_TAIL_LINES)
    elif half or annotated or drift:
        gap("GAP-R3", "rules",
            "通用层关于 `preflight: off` 的说法**事实层面已全部更正到位**（%s: 同行已更正 %d 处、"
            "下面追加勘误块 %d 处），`%s:%s` 实测也是 `%s`；剩下的只是**呈现层没降级**："
            "原句仍带 🔴、仍是现在时，另有 %d 处引的行号实测不含 `preflight` 键（真值在 `:%s`）。"
            "⇒ 不误导「会不会拦」，但会误导「扫红标的人」——通读时先看 🔴 的人仍会读到旧结论。"
            % (os.path.basename(P["gen"]), len(half), len(annotated),
               os.path.basename(P["config"]), real_line, real,
               len(drift), real_line),
            evidence=[h["file"] for h in (half + annotated + [{"file": x["file"]} for x in drift])]
                     + [P["config"]],
            measured={"real": real, "real_line": real_line,
                      "half": [{"file": h["file"], "line": h["line"]} for h in half],
                      "annotated": [{"file": h["file"], "line": h["line"]} for h in annotated],
                      "cite_drift": drift, "cites_not_judged": not_judged,
                      "asserts": asserts},
            severity="low",
            note="只剩降级 🔴、把现在时改过去时、把引错的行号改成实测行号三件外观活；"
                 "事实已经对，所以记 low 不记 high。上一轮这条曾是 high（1 处未更正），"
                 "10-02 追加勘误后降到 low —— **这个降级本身是扫出来的，不是我改口径改出来的**")
    return d


# ─────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────
def build_manifest(do_hash=True):
    cfg_txt = read(P["config"]) or ""
    pf_src = read(P["preflight"]) or ""

    idx_txt = read(P["index_doc"]) or ""
    # 索引 §5 那行的原文分隔符是 `／` 不是 `＋`，正则要都认（否则 doc_claim 会退回硬编码文案）
    m = re.search(r"G1\s*[–\-~]\s*G?\d{1,2}\s*[＋+/／]\s*H1\s*[–\-~]\s*H7", idx_txt)
    doc_claim = m.group(0) if m else None
    if not doc_claim:
        doc_claim = "索引 §5 未找到 G/H 编号声明（本行由脚本兜底，不是文档原文）"

    rules = scan_rules()
    channels = scan_channels(pf_src)
    engine = scan_engine()
    gates = scan_gates(pf_src, doc_claim)
    assets = scan_assets(do_hash)
    delivery = scan_delivery()
    memory = scan_memory()
    switches = scan_switches(cfg_txt)
    ports = scan_ports(cfg_txt)
    external = scan_external_assets()
    # 资产层**总量口径**：核心根 ＋ 外部正式成员（GAP-X1 裁定 (a) 之后的口径）。
    # ⚠ 这个合计只用于"整个系统的资产有多大"这类架构问题；
    #   凡涉及**去重、死链、编号、总索引**的结论，仍然只对 `E:\创作` 成立
    #   （外部根还没进那两个扫描，见 external_asset_roots.architecture_scope）。
    _as = external["architecture_scope"]
    assets["including_external"] = {
        "core_root": P["assets"],
        "core_files": assets["files_total"], "core_images": assets["images"],
        "core_gib": assets["gib"],
        "external_files": _as["external_files"], "external_images": _as["external_images"],
        "external_gib": _as["external_gib"],
        "total_files": assets["files_total"] + _as["external_files"],
        "total_images": assets["images"] + _as["external_images"],
        "total_gib": round(assets["gib"] + _as["external_gib"], 2),
        "member_root_count": _as["member_root_count"],
        "note": "合计＝核心根 ＋ 外部 %d 处正式成员（10-02 裁定 (a)）。"
                "⚠ 只用于架构口径的总量；去重／死链／编号／总索引的结论**仍只对核心根成立**，"
                "外部根尚未进那两个扫描（`dedup_and_deadlink_covered: false`）"
                % (_as["member_root_count"] - 1)}
    stale = scan_stale_alerts(cfg_txt)

    # ⚠ 测量卫生（10-02 批 2 收尾）：交付层这一栏以前写死
    #   `authority: None` ＋ "只有记忆件里的约定，无代码、无真源"。批 2 把
    #   review_publish.py／feishu_send.py 落地之后，"无代码"三个字就成了假断言，
    #   而它正是《架构总纲》§1 七层表的直接数据源 ⇒ 必须改成由实测派生。
    _ra, _fs = delivery["review_area"], delivery["feishu"]
    deliv_scripts = [p for p in (P["review_publish"], P["feishu_send"]) if isfile(p)]
    if not deliv_scripts:
        deliv_auth, deliv_note = None, "⚠ 现在只有记忆件里的约定，无代码、无真源"
    else:
        deliv_auth = deliv_scripts[0]
        deliv_note = ("代码已落地（%s），但**没有规则真源文档**：16 位 hex 防猜／无鉴权／审完删／"
                      "faststart／≈1 Mbps／飞书三件套顺序这些约定只写在脚本 docstring 与记忆件里 "
                      "⇒ 权威实际是代码，改约定不过任何关口（GAP-D4）"
                      % "、".join(_short(x) for x in deliv_scripts))

    layers = [
        {"n": 1, "name": "规则层", "root": P["manual"], "exists": isdir(P["manual"]),
         "authority": P["gen"], "authority_note": "20_通用规范层 是现行权威；01–10 已降级为存档与出处证据"},
        {"n": 2, "name": "通道层", "root": P["channels"], "exists": isdir(P["channels"]),
         "authority": "各通道自己的 *_工作流规则.md",
         "authority_note": "无机器可读通道注册表 —— 本轮由 manifest 补上"},
        {"n": 3, "name": "引擎层", "root": P["engine"], "exists": isdir(P["engine"]),
         "authority": P["config"], "authority_note": "config.yaml 是唯一真源，但里面写死了上一个项目"},
        {"n": 4, "name": "关口层", "root": P["tools"], "exists": isdir(P["tools"]),
         "authority": P["preflight"],
         "authority_note": "**文档跟代码，不是反过来**；人工关口在 tasks.py 的 gate 任务里，无统一编号"},
        {"n": 5, "name": "资产层", "root": P["assets"], "exists": isdir(P["assets"]),
         "authority": P["char_manifest"], "authority_note": "MANIFEST.json 作总索引超集，不新造 schema"},
        {"n": 6, "name": "交付层", "root": P["tools"], "exists": isdir(P["tools"]),
         "authority": deliv_auth, "authority_note": deliv_note},
        {"n": 7, "name": "记忆与技能层", "root": P["mem_user"], "exists": isdir(P["mem_user"]),
         "authority": "各自 MEMORY.md / index.json",
         "authority_note": "记忆根实测 %d 类（用户级／项目级 %d 处／E:\\公共记忆）；"
                           "skill references 是事实源，另两份是副本"
                           % (len(memory["roots"]),
                              memory["project_memory"]["root_count"])},
    ]

    sev = {"high": 0, "mid": 0, "low": 0}
    for g in GAPS:
        sev[g["severity"]] = sev.get(g["severity"], 0) + 1
    broken = [g["id"] for g in GAPS if g.get("evidence_broken")]

    mani = {
        "system": "若水AI电影",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generator": os.path.abspath(__file__),
        "generator_version": VERSION,
        "hand_edit": False,
        "scan_options": {"hash": bool(do_hash), "pytest_collect": bool(PYTEST_PROBE),
                         "hash_cap": HASH_CAP, "deadlink_scan_cap": DEADLINK_SCAN_CAP,
                         "note": "本轮的量测条件。--diff 靠它判断两轮能不能直接对账："
                                 "hash=False 时重复目录那条 gap 会假关闭，"
                                 "pytest_collect=False 时 collected_cases 变 null（假变动）"},
        "hand_edit_warning": "本文件是 scan_system.py 的派生件。手改＝制造第二个漂移真源，"
                             "改口径请改脚本里的判据，然后重扫。",
        "determinism_note": "本文件里**不含耗时字段**：验收要求「连跑两次除 generated 外逐字相同」，"
                            "把 scan_seconds 写进来就永远不可能相同。耗时只打印到控制台。",
        "evidence_selfcheck": {
            "gaps_total": len(GAPS),
            "gaps_with_broken_evidence": broken,
            "verdict": "OK" if not broken else "有 %d 条 gap 的证据路径已失效" % len(broken),
            "rule": "每条 gap 的 evidence 必须是盘上真实存在的路径；"
                    "脚本自己复核，复核不过就标 evidence_broken，不掩盖。",
        },
        "layers": layers,
        "rules": rules,
        "channels": channels,
        "engine": engine,
        "gates": gates,
        "assets": assets,
        "delivery": delivery,
        "memory_skill": memory,
        "switches": switches,
        "ports": ports,
        "external_asset_roots": external,
        "stale_alerts": stale,
        "gaps": sorted(GAPS, key=lambda g: g["id"]),
        "gap_severity": sev,
        "not_doing": [
            "不搬任何目录（除 D6 已裁的判废件合并）",
            "不新建 AI-Film-Studio-OS/ 平行目录（吸收＝填槽，不是建新系统）",
            "不裁风险 28／C84（D7 已裁「暂时不改」）",
            "不做感知哈希去重（本轮只做 md5 精确重复）",
            "不碰 E:\\创作 之外的资产位置（只登记）",
            "不做可运行总控（本轮交付＝总纲＋机器清单）",
        ],
    }
    return mani


def summarize(m, elapsed=None):
    print("=" * 70)
    print("scan_system.py · 若水AI电影 七层现状扫描（只读）")
    print("=" * 70)
    for L in m["layers"]:
        print("  层%d %-12s %-42s %s" % (L["n"], L["name"], L["root"],
                                        "存在" if L["exists"] else "!! 不存在"))
    print("-" * 70)
    gl = m["rules"]["general_layer"]
    print("  规则层   ：手册 %d 份文件／通用层 %d 份（其中规则文件 %d 份、%d 条条目、%d 条没写执行者）"
          % (m["rules"]["files_total"], gl["file_count"], gl["rule_file_count"],
             gl["entries_total"], gl["entries_without_executor"]))
    print("             索引 §5 计划 %s／已成文 %s／未成文 %s ｜ 项目层 %d 个／冲突表 C%d 条＋风险编号 %d 个（最大号 %d，跳号）"
          % ("、".join(gl["planned_in_index"]), "、".join(gl["written"]) or "无",
             "、".join(gl["not_written"]) or "无",
             m["rules"]["project_layer"]["count"],
             m["rules"]["conflict_table"]["c_ids_count"],
             m["rules"]["conflict_table"]["risk_ids_count"],
             m["rules"]["conflict_table"]["risk_ids_max"]))
    sa = m["stale_alerts"]
    print("             过期红警报：preflight 实测 %s(@%s)／未更正 %d 处｜同行已更正 %d 处｜"
          "下面追了勘误块 %d 处｜仅提及 %d 处、判不了 %d 处｜引错行号 %d 处"
          % (sa["real_value"], sa["real_line"], sa["asserts_count"], sa["half_count"],
             sa.get("annotated_count", 0), sa["mention_count"], sa["unclear_count"],
             len(sa["cite_drift"])))
    print("  通道层   ：%d 份 md 真源／%d 条通道，机器认得 %d 条／静默兜底 %s"
          % (m["channels"]["md_count"], len(m["channels"]["registry"]),
             sum(1 for c in m["channels"]["registry"] if c["machine_recognized"]),
             "有" if m["channels"]["channel_of"]["has_silent_fallback"] else "无"))
    print("  引擎层   ：config %d 行／project=%s／workflow %d 份（provider %d、prompt_kind %d）／"
          "def test_ %d 个、pytest 用例 %s 条、实跑通过 未测量"
          % (m["engine"]["config"]["lines"], m["engine"]["config"]["project"],
             m["engine"]["workflows"]["total"], m["engine"]["workflows"]["with_provider"],
             m["engine"]["workflows"]["with_prompt_kind"],
             m["engine"]["tests"]["def_test_total"],
             m["engine"]["tests"]["collected_cases"]))
    print("  关口层   ：ALL_GATES %d 个（%s）／兜底子集 %d 个／带闸流 %d 份并集 %s／缺 G11 的流 %d 份／编号缺 %s"
          % (m["gates"]["all_gates_count"], ",".join(m["gates"]["all_gates"]),
             len(m["gates"]["fallback_default_gates"]),
             m["gates"]["flows_with_gate"], ",".join(m["gates"]["auto_gates_union"]),
             len(m["gates"]["flows_without_G11"]),
             "、".join(m["gates"]["number_holes"]) or "无"))
    print("  资产层   ：%d 文件／%d 张图／%.2f GiB／%d 个一级目录；sidecar %d 份（role %d、anchor_kind %d）"
          % (m["assets"]["files_total"], m["assets"]["images"], m["assets"]["gib"],
             m["assets"]["top_dirs"], m["assets"]["sidecars"]["count"],
             m["assets"]["sidecars"]["with_role"], m["assets"]["sidecars"]["with_anchor_kind"]))
    dl = m["assets"]["dead_links"]
    dd = m["assets"]["duplicate_dirs"]
    print("             作用域内死链 %d 处（扫 %d 个文本文件；全盘死绝对路径 %d 处**不算行动清单**）"
          % (dl["actionable_dead"], dl["scanned_files"], dl["all_dead_absolute_paths"]))
    print("             确认整目录复制 %d 组／同名目录对 %d 组（已算 %d 个 md5，上限 %d%s）／判废区 %d 处"
          % (dd["confirmed_copy_pairs"], dd["pair_count"], dd["hashes_done"], dd["hash_cap"],
             "，已截断" if dd["truncated"] else "", m["assets"]["junk_area_count"]))
    print("  交付层   ：审片区本地目录 %s／hex 生成器 %s／lark-cli 真安装+插件副本 %d 处（沙箱快照另 %d 份）、在 PATH %s"
          % ("有" if m["delivery"]["review_area"]["local_dir_exists"] else "无",
             "有" if m["delivery"]["review_area"]["hex_generator_exists"] else "无",
             m["delivery"]["feishu"]["cli_copy_count_meaningful"],
             len(m["delivery"]["feishu"]["cli_sandbox_snapshots"]),
             "是" if m["delivery"]["feishu"]["in_PATH"] else "否"))
    po = m["delivery"]["post"]
    print("             后期：ffmpeg %d 把／fx_light.py %d 份（变体 %d）落点＝%s"
          % (len(po["ffmpeg_copies"]), len(po["fx_light_copies"]),
             len(po["fx_light_variants"]), po["fx_light_layer"] or "未找到"))
    print("  记忆技能 ：三根 md 数 %s／skill 目录 %d 个／references %d 篇最新 %s（落后通道真源 %s 天）"
          % ("/".join(str(r["md_count"]) for r in m["memory_skill"]["roots"]),
             m["memory_skill"]["skills"]["dir_count"],
             m["memory_skill"]["skill_refs"]["file_count"],
             m["memory_skill"]["skill_refs"]["newest_day"],
             ("%s（兜底算法 %s）" % (m["memory_skill"]["skill_refs"]["lag_days_reported"],
                              m["memory_skill"]["skill_refs"]["lag_days_vs_channel_docs"]) if m["memory_skill"]["skill_refs"]["lag_days_reported"] !=
                             m["memory_skill"]["skill_refs"]["lag_days_vs_channel_docs"]
                             else m["memory_skill"]["skill_refs"]["lag_days_reported"])))
    print("  开关矩阵 ：%d 处，其中单一真源 %d 处"
          % (m["switches"]["count"], m["switches"]["single_source_count"]))
    pt = m["ports"]
    print("  端口     ：生产实例 %s（%s）／共 %d 个端口被声明，其中非生产仍被写死 %d 个"
          % (pt["production_port"],
             os.path.basename(pt["production_source"].split("（")[0]),
             len(pt["ports"]),
             len([o for o in pt["ports"]
                  if not o["is_engine_production"] and o["declared_in_count"]
                  and o["port"] != 7890])))
    print("-" * 70)
    print("  缺口 %d 条：high %d／mid %d／low %d ｜ 证据自检 %s"
          % (m["evidence_selfcheck"]["gaps_total"],
             m["gap_severity"].get("high", 0), m["gap_severity"].get("mid", 0),
             m["gap_severity"].get("low", 0), m["evidence_selfcheck"]["verdict"]))
    for g in m["gaps"]:
        print("    %-8s [%-5s] %s%s" % (g["id"], g["severity"], g["what"][:96],
                                        "  ← 待用户裁" if g["needs_user_ruling"] else ""))
        if g.get("evidence_broken"):
            print("             !! 证据路径失效：%s" % "、".join(g["evidence_broken"]))
    print("-" * 70)
    print("  耗时 %s ｜ 本脚本只读，除 manifest 外不写任何文件"
          % ("%.2fs" % elapsed if elapsed is not None else "未计"))


def _flat(o, pre=""):
    """把 manifest 摊平成 {路径: 标量}，供 --diff 逐字段对账。

    列表带下标展开，另存一个 `__len__`。⚠ 已知局限：**列表重新排序会被当成"变了一堆"**
    （例：`registry[]` 换顺序）。这是刻意的取舍——做集合比对就要给每种列表定义"主键"，
    而那又是一个会漂的口径；宁可吵一点，也不要漏。"""
    out = {}
    if isinstance(o, dict):
        for k in sorted(o):
            out.update(_flat(o[k], pre + "/" + str(k)))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out.update(_flat(v, "%s[%d]" % (pre, i)))
        out[pre + "/__len__"] = len(o)
    else:
        out[pre] = o
    return out


def _s(v, n=88):
    t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    t = t.replace("\n", " ")
    return t if len(t) <= n else t[:n] + "…"


def diff_manifests(old, new, max_rows=120):
    """新旧 manifest 对账。**只打印，不写进 manifest**（写进去就永远不可能连跑两次相同）。

    为什么要有它：10-02 总纲 v1.0→v1.5 五个版本里，有**三次**是在修我上一版写进去的假数字
    （测试数把"未测量"写成"已闭"、人工关口表引用了 manifest 里根本没有的字段、
    记忆根数因写死单会话路径而少报）。重扫本身不产生价值，**重扫＋和上一版对账才产生价值**。
    """
    og = {g["id"]: g for g in old.get("gaps", [])}
    ng = {g["id"]: g for g in new.get("gaps", [])}
    print("=" * 72)
    print("对账：旧 %s → 新 %s" % (old.get("generated", "?"), new.get("generated", "?")))
    print("=" * 72)
    # ⚠ 量测条件不同就别对账：`--no-hash` 那次跑不出 md5 ⇒ 重复目录那条 gap 会"假关闭"，
    #   `--no-collect` 那次 collected_cases 变 null ⇒ 引擎那几条会"假变动"。
    #   10-02 首跑 --diff 就当场演了一次：GAP-A5 报"关闭"，其实只是那轮没算哈希。
    oo, no = old.get("scan_options") or {}, new.get("scan_options") or {}
    if oo and no and oo != no:
        print("!! 两轮量测条件不同（旧 %s ／ 新 %s）⇒ 下面的差异里混着**由旗标造成的假变动**，"
              "别当成盘变了" % (_s(oo, 60), _s(no, 60)))
    elif not oo or not no:
        print("○ 有一轮没有 scan_options 字段（旧版本扫的）⇒ 无法确认两轮量测条件是否一致，"
              "gap 的开关结论要打折看")

    opened = sorted(set(ng) - set(og))
    closed = sorted(set(og) - set(ng))
    print("【缺口开关】新开 %d ｜ 关闭 %d ｜ 旧 %d → 新 %d"
          % (len(opened), len(closed), len(og), len(ng)))
    for i in opened:
        print("   + %s [%s] %s" % (i, ng[i]["severity"], _s(ng[i]["what"], 70)))
    for i in closed:
        print("   - %s（原 %s）%s" % (i, og[i]["severity"], _s(og[i]["what"], 70)))
    for i in sorted(set(og) & set(ng)):
        a, b = og[i], ng[i]
        if a.get("severity") != b.get("severity"):
            print("   ↕ %s 级别 %s → %s" % (i, a.get("severity"), b.get("severity")))
        if bool(a.get("needs_user_ruling")) != bool(b.get("needs_user_ruling")):
            print("   ⚖ %s 待裁 %s → %s" % (i, bool(a.get("needs_user_ruling")),
                                             bool(b.get("needs_user_ruling"))))

    a, b = _flat(old), _flat(new)
    skip_prefix = ("/gaps[", "/generated")
    keys = [k for k in sorted(set(a) | set(b)) if not k.startswith(skip_prefix)]
    changed = [(k, a[k], b[k]) for k in keys if k in a and k in b and a[k] != b[k]]
    added = [(k, b[k]) for k in keys if k not in a]
    removed = [(k, a[k]) for k in keys if k not in b]

    print("【字段变动】改了 %d ｜ 新增 %d ｜ 消失 %d（不含 gaps[] 与 generated）"
          % (len(changed), len(added), len(removed)))
    shown = 0
    for k, x, y in changed:
        if shown >= max_rows:
            print("   … 另有 %d 处变动未列（--diff 默认最多 %d 行）" % (len(changed) - shown, max_rows))
            break
        print("   ~ %s\n       旧 %s\n       新 %s" % (k, _s(x), _s(y)))
        shown += 1
    for k, y in added[:20]:
        print("   + %s = %s" % (k, _s(y)))
    if len(added) > 20:
        print("   … 另有 %d 个新增字段未列" % (len(added) - 20))
    for k, x in removed[:20]:
        print("   - %s（旧值 %s）" % (k, _s(x)))
    if len(removed) > 20:
        print("   … 另有 %d 个消失字段未列" % (len(removed) - 20))
    if not (changed or added or removed or opened or closed):
        print("   （除 generated 外逐字相同 ⇒ 盘上什么都没变）")
    print("=" * 72)
    return {"changed": len(changed), "added": len(added), "removed": len(removed),
            "gaps_opened": opened, "gaps_closed": closed}


def main(argv):
    global PYTEST_PROBE
    do_hash = "--no-hash" not in argv
    PYTEST_PROBE = "--no-collect" not in argv
    out = DEFAULT_OUT
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    t0 = time.time()
    m = build_manifest(do_hash)
    elapsed = round(time.time() - t0, 2)
    if "--diff" in argv:
        # 对账对象：`--diff <path>` 指定则用它，否则用**即将被覆盖的那份** DEFAULT_OUT。
        i = argv.index("--diff")
        prev_path = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("--") \
            else DEFAULT_OUT
        prev = None
        if isfile(prev_path):
            try:
                prev = json.load(io.open(prev_path, encoding="utf-8"))
            except (ValueError, OSError) as e:
                print("!! 旧 manifest 读不了（%s: %s）⇒ 本轮无法对账" % (type(e).__name__, e))
        if prev is None:
            print("!! 找不到旧 manifest（%s）⇒ 第一次跑没有可对账的对象，本轮跳过" % prev_path)
        else:
            diff_manifests(prev, m)
    summarize(m, elapsed)
    if "--print" in argv:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("  已写出：%s（%d 字节）" % (out, nb(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
