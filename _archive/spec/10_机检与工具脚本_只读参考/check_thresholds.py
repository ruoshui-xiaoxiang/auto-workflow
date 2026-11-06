# -*- coding: utf-8 -*-
"""阈值注册表自校验（第五件校验器，只读）。2026-10-03 批 7-2。

    py tools/check_thresholds.py [--strict] [--print-json] [-v]

为什么要有这件：10-02 硬检查查出**阈值散在 5 处**（关口常量区、引擎默认参、tmp 里那把主尺、
各项目 qc_*、手册正文），而且代码与注释/记忆两处已经不一致过（crf16 vs crf18、−16 vs −17）。
散着的数不会有"谁说了算"，改一处其余照旧——这正是本项目反复翻车的那类事。

本表**不抄值**：每条只登记「这个数住在哪几处、用什么读法取、谁定的、有没有真在生效」，
值全部现读。注册表里写值就是制造第二份抄本。

三种 role：
  authority        说了算的那处
  mirror           必须与 authority 相等的复刻（不同 ⇒ error）
  reference_only   旁证（实测带、记忆经验值），**不参与相等比对**，只印出来给人读
"""
import argparse
import io
import json
import os
import re
import sys

REG = r"D:\AIWorkflow\engine\thresholds_registry.json"


def _read(path):
    try:
        return io.open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return None


def _num(s):
    t = str(s).strip().replace("−", "-").replace("＿", "_")
    try:
        return float(t)
    except Exception:
        return t


def read_value(place, src_cache):
    """按注册表给的读法取值。取不到返回 (None, 原因)——**绝不返回 0 或空串冒充"读到"**。"""
    kind = str(place.get("kind") or "")
    path = str(place.get("file") or "").replace("/", os.sep)
    if not os.path.isfile(path):
        return None, "文件不在：%s" % path
    src = src_cache.get(path)
    if src is None:
        src = _read(path) or ""
        src_cache[path] = src
    if kind == "py_const":
        name = str(place.get("name") or "")
        m = re.search(r"^(?:%s)\s*=\s*([^\n#]+)" % re.escape(name), src, re.M)
        if not m:
            # 元组赋值（A, B, C = 1, 2, 3）里找第 n 个名字
            m2 = re.search(r"^([A-Z0-9_,\s]+)=([^\n#]+)", src, re.M)
            found = None
            for mm in re.finditer(r"^([A-Z][A-Z0-9_]*(?:\s*,\s*[A-Z][A-Z0-9_]*)+)\s*=\s*([^\n#]+)",
                                  src, re.M):
                names = [x.strip() for x in mm.group(1).split(",")]
                if name in names:
                    vals = [x.strip() for x in mm.group(2).split(",")]
                    if len(vals) == len(names):
                        found = vals[names.index(name)]
                    break
            if found is None:
                return None, "常量 %s 没读到（文件里既没有单行赋值也没有元组赋值）" % name
            return _num(found), None
        return _num(m.group(1)), None
    if kind == "py_default_kw":
        func, name = str(place.get("func")), str(place.get("name"))
        m = re.search(r"def %s\(([^)]*)\)" % re.escape(func), src, re.S)
        if not m:
            return None, "找不到函数 %s 的签名" % func
        m2 = re.search(r"%s\s*=\s*([-0-9.]+)" % re.escape(name), m.group(1))
        if not m2:
            return None, "函数 %s 的参数 %s 没有数值默认值" % (func, name)
        return _num(m2.group(1)), None
    if kind == "regex":
        m = re.search(str(place.get("pattern")), src)
        if not m:
            return None, "正则没匹配到（读法过期或值被改写法）"
        raw = m.group(int(place.get("group") or 0)) if place.get("group") else m.group(0)
        v = _num(raw)
        if isinstance(v, (int, float)):
            if place.get("scale_by"):
                v = v * float(place["scale_by"])
            if place.get("sign") and v > 0:
                v = v * float(place["sign"])
        return v, None
    if kind == "dict_entry":
        key, field = str(place.get("key")), str(place.get("field"))
        m = re.search(r"'%s'\s*:\s*\{([^}]*)\}" % re.escape(key), src, re.S)
        if not m:
            return None, "字典里没有键 %s" % key
        m2 = re.search(r"'%s'\s*:\s*([-0-9.]+)" % re.escape(field), m.group(1))
        if not m2:
            return None, "键 %s 下没有字段 %s" % (key, field)
        return _num(m2.group(1)), None
    return None, "未知读法 kind=%s（注册表写错了）" % kind


def check(reg, verbose=False):
    errs, warns, infos = [], [], []
    data = {"thresholds": [], "counts": {}}
    src_cache = {}
    conflicts, unreadable, unenforced = [], [], []
    for th in reg.get("thresholds") or []:
        tid = str(th.get("id") or "(无名)")
        got = []
        for place in (th.get("places") or []):
            val, why = read_value(place, src_cache)
            role = str(place.get("role") or "authority")
            got.append({"role": role, "kind": place.get("kind"),
                        "where": str(place.get("file")).split("/")[-1]
                                 + (":" + str(place.get("name")) if place.get("name") else ""),
                        "value": val, "read_error": why})
            if why:
                unreadable.append("%s／%s（%s）" % (tid, role, why))
                errs.append("[阈值读不到] %s 的一处 %s：%s ⇒ 读法过期或文件搬走，"
                            "不当成「没问题」" % (tid, role, why))
        cmp_vals = [(g["role"], g["value"]) for g in got
                    if g["value"] is not None and g["role"] in ("authority", "mirror")]
        uniq = {v for _r, v in cmp_vals}
        if len(uniq) > 1:
            conflicts.append(tid)
            errs.append("[不一致] %s：%s ⇒ 同一个数在两处不一样，改一处其余照旧"
                        % (tid, "；".join("%s=%s" % (r, v) for r, v in cmp_vals)))
        if th.get("enforced") is False:
            unenforced.append(tid)
            warns.append("[挂着没生效] %s：%s ⇒ 有数没校验，别当已生效引用"
                         % (tid, str(th.get("含义") or "")[:38]))
        auth = [g for g in got if g["role"] == "authority"]
        rec = {"id": tid, "scope": th.get("scope"), "unit": th.get("unit"),
               "enforced": th.get("enforced"), "含义": th.get("含义"),
               "authority_value": (auth[0]["value"] if auth else None),
               "places": got}
        data["thresholds"].append(rec)
        if verbose:
            infos.append("[%-28s] %-10s authority=%s ｜ %s"
                         % (tid, str(th.get("scope") or "")[:10],
                            rec["authority_value"],
                            " ／ ".join("%s:%s" % (g["role"], g["value"] if g["value"] is not None
                                                   else "读不到") for g in got)))
    counts = {"thresholds": len(reg.get("thresholds") or []),
              "conflicts": len(conflicts), "unreadable": len(unreadable),
              "unenforced": len(unenforced)}
    data["counts"] = counts
    data["conflict_ids"] = conflicts
    data["unenforced_ids"] = unenforced
    data["known_mismatches"] = reg.get("known_mismatches") or []
    if not (reg.get("thresholds") or []):
        errs.append("[空表] 注册表里没有一条阈值 ⇒ 要么没写完、要么文件不对，"
                    "这不是「没有阈值」")
    return errs, warns, infos, data


def main():
    ap = argparse.ArgumentParser(description="阈值注册表自校验（只读、只报不拦；--strict 才有非零退出）")
    ap.add_argument("--registry", default=REG)
    ap.add_argument("--strict", action="store_true", help="有 error 级问题时返回 1（默认恒 0）")
    ap.add_argument("--print-json", action="store_true", help="只把结构化结果打到 stdout（扫描器吃这个）")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    try:
        reg = json.loads(io.open(a.registry, encoding="utf-8").read())
    except Exception as e:
        msg = "阈值注册表读不到（%s: %s）：%s" % (type(e).__name__, e, a.registry)
        if a.print_json:
            json.dump({"errors": [msg], "warns": [], "data": {"registry_load_error": str(e)}},
                      sys.stdout, ensure_ascii=False, indent=1)
            sys.stdout.write("\n")
        else:
            print("!! %s ⇒ **本项一项都没跑，这不是通过**" % msg)
        return 1 if a.strict else 0

    errs, warns, infos, data = check(reg, a.verbose)
    if a.print_json:
        json.dump({"errors": errs, "warns": warns, "data": data},
                  sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 1 if (a.strict and errs) else 0

    print("=" * 72)
    print("check_thresholds.py · 阈值注册表自校验（只读，值全部现读、表里不抄值）")
    print("注册表：%s" % a.registry)
    print("=" * 72)
    for line in infos:
        print("  " + line)
    for e in errs:
        print("  !! %s" % e)
    for w in warns:
        print("  ⚠ %s" % w)
    km = data.get("known_mismatches") or []
    for k in km:
        print("  ○ 已知不一致（登记不比对）%s：%s｜现状：%s"
              % (k.get("id"), " vs ".join(str(s.get("says")) for s in (k.get("sides") or [])),
                 k.get("status")))
    c = data.get("counts") or {}
    print("-" * 72)
    print("阈值 %d 条｜不一致 %d｜读不到 %d｜挂着没生效 %d"
          % (c.get("thresholds", 0), c.get("conflicts", 0),
             c.get("unreadable", 0), c.get("unenforced", 0)))
    print("本脚本默认只报不拦：退出码 %s" % (1 if (errs and a.strict) else 0))
    return 1 if (errs and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
