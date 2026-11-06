# -*- coding: utf-8 -*-
r"""量「词表失明」v2：判据**消费点**级探针 ＋ 判定漂移，不是"词表级命中数"。

为什么重写成 v2（v1 的三个错都是它自己量出来的，不更正就照它下裁定＝拿坏尺子裁活）：
1. **只数中文条目** ⇒ 双语表（`FACING`／`BACK`／`SKIN_SUBJECT`…本来就配了英文正则形）
   在英文正文上"中文条目 0 命中"被判成失明，而**整表还在工作**——假告 12 张。
2. **只认模块级全大写表** ⇒ 写在判定代码里的散判据（`'音乐' in vis`、H3R7 末步风险词、
   函数级 `LOCK_*`／`UNWRAP`）**根本不在那 40 张里**——漏告（假阴比假阳坏）。
3. **不问"这张表吃哪个区"** ⇒ 吃 `s['beat']`（事件脚本，仍是中文）的表被算成被英译拿走，
   单位错配造出假缺口。
4. **配对表靠猜目录** ⇒ 15 份真源的路径拼错，静默只配上 1 份，整张表是在 1 份稿子上量的。

v2 的口径：
· [0] 清单：AST 取**所有**全大写词表（模块级＋函数级），按条目形态分「纯中文／中英双形／纯英文」——
  这是穷尽清单，不依赖"消费点认不认得出"；
· [1] 消费点：`x in 区`／`for w in 表: w in 区`／`_hit(表, 区)`／`表.rfind(w)` 四类写法都认，
  并区分**区的来源**（稿面 prompt 派生 vs 事件脚本 s[...]）；
· 匹配语义照抄闸：含正则元字符的条目 `re.search(…, re.I)`，纯词按子串（ASCII 条目大小写不敏感）；
· [2] 判定漂移：同一份稿子改前/改后各跑整套 `h3_rule_gate`，比 `(规则, 项, 级别)` 的重数——
  **只有这一节能区分"失明无害"和"失明有害"**，命中数只是线索。

用法：
    python h3_wordlist_blind.py            # [0]+[1]：清单与消费点（改前/改后命中）
    python h3_wordlist_blind.py --drift    # [2]：判定漂移
    python h3_wordlist_blind.py --json     # 机器可读

本工具**只测不拦**：不改判据、不写文件、退出码恒 0。
"""
import ast
import io
import json
import os
import re
import sys

WZY = r"D:\AIWorkflow\tmp\wzy"
BK = r"E:\本地工作流规范手册\99_维护\_改前备份_20261003_正文英译"
MANIFEST = os.path.join(WZY, "h3_rewrite_manifest.json")
MODS = ("h3_rule_gate.py", "prompt_lint.py")
if WZY not in sys.path:
    sys.path.insert(0, WZY)

CJK = re.compile(u"[\u4e00-\u9fff]")
META = re.compile(r"[\[\]{}()|*+?\\^$]")
# 区的来源分类：这些变量都是从**稿面**切出来的（会被英译拿走），
# 含 `s[`／`beat` 的是**事件脚本**（本层自留中文，不受正文语言影响）。
PROMPT_VARS = ("vis", "txt", "text", "vlo", "blk", "prompt", "line", "clause", "body",
               "snd", "cam", "seg", "tail", "low", "sen", "narr")


def _is_cn(s):
    return isinstance(s, str) and bool(CJK.search(s))


def kind_of(words):
    cn = sum(1 for w in words if _is_cn(w))
    if cn == len(words):
        return u"纯中文"
    return u"纯英文" if not cn else u"中英双形"


def region_kind(region):
    r = (region or "").strip()
    if r.startswith("s[") or "beat" in r or "main" in r and "s[" in r:
        return u"事件脚本"
    for v in PROMPT_VARS:
        if re.search(r"\b" + v + r"\b", r):
            return u"稿面"
    return u"未定"


# ── 1. 词表清单（穷尽）─────────────────────────────────────────────────────
def collect_tables(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                     if isinstance(node, ast.Assign)
                     else ([node.target.id] if isinstance(node.target, ast.Name) else []))
            for nm in names:
                if not nm.isupper():
                    continue
                val = node.value
                if isinstance(val, ast.Dict):
                    ents = [e.value for e in val.keys if isinstance(e, ast.Constant)]
                elif isinstance(val, (ast.List, ast.Tuple, ast.Set)):
                    ents = [e.value for e in val.elts if isinstance(e, ast.Constant)]
                else:
                    continue
                ents = [e for e in ents if isinstance(e, str) and e]
                if not ents:
                    continue
                prev = out.get(nm, (node.lineno, []))[1]
                out[nm] = (node.lineno, prev + [e for e in ents if e not in prev])
    return out


# ── 2. 判据消费点 ───────────────────────────────────────────────────────────
def _resolve(iterable, tables, src):
    if isinstance(iterable, ast.List):
        ents = [e.value for e in iterable.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return (ents, u"行内字面表") if ents else (None, None)
    seg = (ast.get_source_segment(src, iterable) or "").strip()
    if seg in tables:
        return tables[seg][1], seg
    for nm, (_ln, ents) in tables.items():      # `H.DEGUN` 之类按属性名兜一下
        if seg.endswith("." + nm):
            return ents, nm
    return None, None


def collect_sites(src, fname, tables):
    tree = ast.parse(src)
    sites = []
    seen = set()

    def note(lineno, words, region, how, matcher):
        if not words:
            return
        key = (lineno, tuple(words), region)
        if key in seen:
            return
        seen.add(key)
        sites.append(dict(line=lineno, words=list(words), region=region or "?",
                          how=how, matcher=matcher, mod=os.path.basename(fname)))

    for node in ast.walk(tree):
        # 2a. 左侧是字面量的成员测试：`'音乐' in vis`
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, ast.In) and isinstance(node.left, ast.Constant) \
                        and isinstance(node.left.value, str):
                    note(node.lineno, [node.left.value],
                         ast.get_source_segment(src, comp), u"单词判据", "in")
        # 2b. 推导式：`any(w in vis for w in FX_BAD)`（比较式在 elt/ifs，不在 gen 子树）
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            bind = {g.target.id: g for g in node.generators if isinstance(g.target, ast.Name)}
            for c in ast.walk(node):
                if not isinstance(c, ast.Compare):
                    continue
                for op, comp in zip(c.ops, c.comparators):
                    if isinstance(op, ast.In) and isinstance(c.left, ast.Name) \
                            and c.left.id in bind:
                        words, how = _resolve(bind[c.left.id].iter, tables, src)
                        note(c.lineno, words, ast.get_source_segment(src, comp), how, "in")
        # 2c. for 循环：`for w in ABSTRACT: if w in clause` ／ `for n in NEG: seg.rfind(n)`
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            tv = node.target.id
            words, how = _resolve(node.iter, tables, src)
            if not words:
                continue
            regs = set()
            for c in ast.walk(node):
                if isinstance(c, ast.Compare):
                    for op, comp in zip(c.ops, c.comparators):
                        if isinstance(op, ast.In) and isinstance(c.left, ast.Name) \
                                and c.left.id == tv:
                            regs.add((ast.get_source_segment(src, comp), "in"))
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) \
                        and c.func.attr in ("rfind", "find", "count", "index"):
                    rec = ast.get_source_segment(src, c.func.value)
                    if any(isinstance(a, ast.Name) and a.id == tv for a in c.args):
                        regs.add((rec, c.func.attr))
            if not regs:
                regs.add(("(未见显式取用)", "?"))
            for rg, mt in regs:
                note(node.lineno, words, rg, how, mt)
        # 2d. 函数式匹配：`_hit(TABLE, blk)` / `find_terms(txt, TABLE)`
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("_hit", "_hits", "find_terms", "_any"):
            args = list(node.args)
            tbl, reg = None, None
            for a in args:
                seg = (ast.get_source_segment(src, a) or "").strip()
                if seg in tables:
                    words, how = _resolve(a, tables, src)
                    if words:
                        tbl = (words, seg)
                else:
                    reg = reg or seg
            if tbl:
                note(node.lineno, tbl[0], reg, tbl[1], node.func.id)
    return sites


# ── 3. 匹配器（照抄闸的语义）───────────────────────────────────────────────
def count_hits(words, text):
    n = 0
    low = text.lower()
    for w in words:
        if not w:
            continue
        if not _is_cn(w) and META.search(w):
            try:
                n += len(re.findall(w, text, re.I))
            except re.error:
                n += len(re.findall(re.escape(w), low))
        elif _is_cn(w):
            n += text.count(w)
        else:
            n += low.count(w.lower())
    return n


# ── 4. 语料：改前备份 ↔ 现役稿（读批 15 改写清单，不猜目录）──────────────────
def pairs():
    out = []
    mf = json.load(io.open(MANIFEST, encoding="utf-8"))
    want = len(mf["files"])
    for f in mf["files"]:
        p = f["path"]
        b = os.path.join(BK, os.path.basename(os.path.dirname(p)) + u"__" + os.path.basename(p))
        if not (os.path.isfile(b) and os.path.isfile(p)):
            continue
        out.append((os.path.basename(p), io.open(b, encoding="utf-8").read(),
                    io.open(p, encoding="utf-8").read()))
    if len(out) != want:                     # 配不上必须当场说出来，别静默少样本跑完
        sys.stderr.write(u"⚠ 改写清单 %d 份、只配上 %d 份 ⇒ 下面的数是在少样本上量的\n"
                         % (want, len(out)))
    return out


def build():
    tables, sites = {}, []
    for fn in MODS:
        p = os.path.join(WZY, fn)
        src = io.open(p, encoding="utf-8").read()
        tb = collect_tables(ast.parse(src))
        tables[fn] = tb
        sites += collect_sites(src, p, tb)
    return tables, sites


def report_coverage():
    ps = pairs()
    tables, sites = build()
    print(u"[0] 词表清单（AST 穷尽，模块级＋函数级全大写表）｜%d 张"
          % sum(len(v) for v in tables.values()))
    print(u"%-18s %-16s %5s %6s %s" % (u"模块", u"表", u"行", u"条目", u"形态"))
    stat = {}
    for fn in MODS:
        for nm in sorted(tables[fn]):
            ln, ents = tables[fn][nm]
            k = kind_of(ents)
            stat[k] = stat.get(k, 0) + 1
            print(u"%-18s %-16s %5d %4d/%-4d %s" % (fn, nm, ln, len(ents), 0, k))
    print(u"  形态合计：%s" % u"／".join(u"%s %d" % (k, v) for k, v in sorted(stat.items())))

    print(u"\n[1] 判据消费点｜%d 个（对跑 %d 份）" % (len(sites), len(ps)))
    rows = []
    for st in sites:
        b = sum(count_hits(st["words"], old) for _n, old, _w in ps)
        a = sum(count_hits(st["words"], new) for _n, _o, new in ps)
        rk = region_kind(st["region"])
        k = kind_of(st["words"])
        if st["region"].startswith(u"(未见显式取用)") or rk == u"未定":
            # 探针认不出取用处 ≠ 这条判据在吃稿面。`DOMAIN_WORDS` 就是被这样误列过的：
            # 它是 degun 替换表的**覆盖自检**词表，压根不读提示词 ⇒ 拿它报"被英译拿走"是假告。
            v = u"取用处未定位（探针盲区，需人工判）"
        elif rk == u"事件脚本":
            v = u"吃事件脚本（不受正文语言影响）" if b else u"吃事件脚本，本来 0"
        elif k == u"纯中文" and b and not a:
            v = u"⚠ 被英译拿走（稿面 0 命中）"
        elif k == u"纯中文" and b and a:
            v = u"⚠ 被英译拿走（仅剩残留中文蹭到 %d）" % a
        elif not b and not a:
            v = u"本来 0"
        elif k != u"纯中文" and a:
            v = u"英文形仍在命中"
        else:
            v = u"待判（有英文形但改后 0：正文没写 or 词形不全）"
        rows.append((b, dict(mod=st["mod"], line=st["line"], how=st["how"],
                             region=st["region"], rkind=rk, kind=k, n=len(st["words"]),
                             before=b, after=a, verdict=v, matcher=st["matcher"],
                             sample=u"、".join(st["words"][:6])[:56])))
    print(u"%-16s %4s %-14s %-20s %6s %4s %5s %5s %-8s %s"
          % (u"模块", u"行", u"词表", u"扫的区", u"区源", u"条目", u"改前", u"改后", u"形态", u"结论"))
    for _b, r in sorted(rows, key=lambda x: (x[1]["verdict"][:2] != u"⚠", -x[0])):
        print(u"%-16s %4d %-14s %-20s %6s %4d %5d %5d %-8s %s" % (
            r["mod"][:16], r["line"], r["how"][:14], r["region"][:20], r["rkind"],
            r["n"], r["before"], r["after"], r["kind"], r["verdict"]))
    lost = [r for _b, r in rows if r["verdict"].startswith(u"⚠")]
    print(u"\n被英译拿走的稿面判据 %d 个，合计改前命中 %d"
          % (len(lost), sum(r["before"] for r in lost)))
    if "--json" in sys.argv:
        print(json.dumps([r for _b, r in rows], ensure_ascii=False, indent=1))
    return rows


# ── 5. 判定漂移：同一份稿子改前/改后各跑整套闸，比 (规则,项,级别) 重数 ──────────
def drift(ps=None):
    import contextlib
    import h3_rule_gate as HG
    ps = ps or pairs()
    tot = {}
    for name, old, new in ps:
        vs = []
        for txt in (old, new):
            cnt = {}
            s = HG.synth_shot(txt)
            with contextlib.redirect_stdout(io.StringIO()):
                rows = (HG.check_format(txt) + HG.check_shot(None, s, txt)
                        + HG.check_space(txt) + HG.check_style(txt) + HG.check_decisive(txt))
            for rid, chks in rows:
                for c in chks:
                    k = (rid, c["name"], c["lvl"])
                    cnt[k] = cnt.get(k, 0) + 1
            vs.append(cnt)
        a, b = vs
        for k in sorted(set(a) | set(b)):
            d = b.get(k, 0) - a.get(k, 0)
            if d:
                tot.setdefault(k, []).append((name, d))
    print(u"\n[2] 判定漂移（改后 − 改前；0 差不列）")
    if not tot:
        print(u"  无漂移：整套闸在英译稿上给出与中文稿完全相同的判定级别")
    for k in sorted(tot, key=lambda x: -sum(abs(d) for _n, d in tot[x])):
        print(u"  %-40s 净 %+3d（%d 份升 / %d 份降） 例：%s" % (
            u"%s｜%s｜%s" % k, sum(d for _n, d in tot[k]),
            sum(1 for _n, d in tot[k] if d > 0), sum(1 for _n, d in tot[k] if d < 0),
            tot[k][0][0][:28]))
    return tot


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--drift":
        drift()
        return
    rows = report_coverage()
    if "--full" in sys.argv:
        drift()
    return rows


if __name__ == "__main__":
    main()
