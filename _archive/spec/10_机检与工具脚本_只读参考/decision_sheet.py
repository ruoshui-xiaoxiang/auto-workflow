# -*- coding: utf-8 -*-
r"""运行决定单 · 「值」的落点（2026-10-02 裁定①②落地）

真源分工（一条东西只有一处实现，别处只引用）：
  · 有哪些槽、槽归哪一级        → `engine\channels_registry.json` 的 `run_slots`（唯一槽清单）
  · 单放哪、变更怎么留痕（原话） → `engine\projects_registry.json` 的 `decision_sheet`
  · 路径怎么拼                  → 本模块一处（`config.paths.creation_root` ＋ 注册表 `asset_dir`）
  · 值本体                      → 各项目 `E:\创作\<项目>\_项目档案\运行决定单.json`（**只有人能填**）

四条铁律（同时钉在 `tests\test_run_decisions.py` 里）：
  1. 本模块**永不填值、永不给默认**——缺槽如实报缺，交给 G13 拦。
  2. 值必须带 `set_by: human` 才算「人给过的」；来路不明（缺失／非 human）视同没给。
     这条是防「将来某人往这里加了个兜底默认」把整套留痕机制从内部掏空。
  3. **项目级槽不许按批传参覆盖**：某批要换画幅＝项目级变更，只能回来改单
     （10-02 你划的分界：常用画幅属项目级）。这里发现这类参数只报不用。
  4. **运行级槽即便在单里存了值也不采用**（每批必须重新给），本模块只报不借。

⚠ 本文件与 `tasks.py` 之间是单向引用（tasks 里延迟 import 本模块），
所以这里不 import tasks——原子写盘那 6 行是有意的小重复，避免循环导入。
"""
import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
CHANNELS_REGISTRY = ENGINE / "channels_registry.json"
PROJECTS_REGISTRY = ENGINE / "projects_registry.json"
SHEET_DIRNAME = "_项目档案"
SHEET_FILENAME = "运行决定单.json"
SCHEMA_VERSION = 1
TIER_PROJECT = "project"
TIER_RUN = "run"


def _read_json(path):
    """返回 (data, problem)。problem 非空时 data 一定不可信——不静默当空表。"""
    p = Path(str(path))
    if not p.is_file():
        return None, "文件不存在：%s" % p
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, "JSON 读坏（%s）：%s" % (type(e).__name__, p)


def _atomic_write(path, data):
    p = Path(str(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(str(tmp), str(p))


def _label(entry):
    """槽的中文标签：优先 label_cn，退回 slot 本身。"""
    if isinstance(entry, dict):
        return str(entry.get("label_cn") or entry.get("slot") or "")
    return str(entry or "")


def slot_defs(channels=None):
    """槽清单——从 channels_registry.run_slots 现推，本模块不另存一份。

    返回 (slots, problem)；slots 每项 {slot, label, tier}。
    注册表读不到时 problem 非空 ⇒ 调用方（collect／G13）必须当错误处理，
    不许退回「当成没有必填槽」——那是假通过。
    """
    src = channels
    if src is None:
        src, problem = _read_json(CHANNELS_REGISTRY)
        if src is None:
            return [], "通道注册表读不到（槽清单没有真源）：%s" % problem
    rs = ((src or {}).get("run_slots") or {})
    out = []
    for tier, key in ((TIER_PROJECT, "must_ask_every_project"),
                      (TIER_RUN, "must_ask_every_run")):
        for e in (rs.get(key) or []):
            slot = str((e or {}).get("slot") or "").strip() if isinstance(e, dict) else str(e or "").strip()
            if not slot:
                continue
            rec = {"slot": slot, "label": _label(e), "tier": tier}
            if isinstance(e, dict):
                # 同一个决定在现役 yaml 里可能有多个键名（润色就有两个）：
                # 别名如实登记在表里，这里只转述，不在代码里再写一份名字清单。
                rec["accepts"] = [str(a) for a in (e.get("accepts") or [])]
            out.append(rec)
    if not out:
        return [], "channels_registry.run_slots 里一个槽都没声明 ⇒ 必填集合为空，" \
                   "这不是「都不用问」，是注册表空了"
    return out, None


def slots_by_tier():
    slots, problem = slot_defs()
    if problem:
        return None, None, problem
    pr = [s for s in slots if s["tier"] == TIER_PROJECT]
    rn = [s for s in slots if s["tier"] == TIER_RUN]
    return pr, rn, None


def creation_root(cfg):
    r"""E:\创作 这一根从 config 取；取不到就如实报缺，不写死字面量。

    写死就是第二份抄本——项目根挪一次，这里悄悄还指着老地方（同 GAP-P1 那类坑）。
    """
    paths = (cfg or {}).get("paths")
    if isinstance(paths, dict) and paths.get("creation_root"):
        return str(paths["creation_root"]), "config.paths.creation_root"
    if (cfg or {}).get("creation_root"):
        return str(cfg["creation_root"]), "config.creation_root"
    return None, "config 里没有 paths.creation_root（或 creation_root）⇒ 决定单路径拼不出来"


def project_asset_dir(cfg, project):
    """项目名 → 创作目录下的资产夹名（注册表 asset_dir）。

    项目可以用别名给（config.project_aliases / 注册表 aliases 都算），
    解析不出来的**不猜**：返回 problem，由关口报「项目未登记」。
    """
    reg, problem = _read_json(PROJECTS_REGISTRY)
    if reg is None:
        return None, None, "项目注册表读不到：%s" % problem
    projs = (reg or {}).get("projects") or []
    alias_map = (cfg or {}).get("project_aliases") or {}
    want = str(project or "").strip()
    for prj in projs:
        pid = str((prj or {}).get("id") or "")
        aliases = [str(x) for x in ((prj or {}).get("aliases") or [])]
        for k, v in (alias_map or {}).items():
            if str(k) == pid:
                aliases += [str(x) for x in (v or [])]
        if want and (want == pid or want in aliases):
            return pid, str((prj or {}).get("asset_dir") or pid), None
    return (None, None,
            "项目「%s」不在 projects_registry.projects（含别名）里 ⇒ 无法定位决定单。"
            "要么登记它，要么 --project 给个已登记的代号；这里不替它猜目录名。" % (want or "(空)"))


def sheet_path(cfg, project):
    """决定单路径的唯一取法。返回 (Path | None, info)。"""
    root, src = creation_root(cfg)
    if root is None:
        return None, {"error": src}
    pid, asset, pp = project_asset_dir(cfg, project)
    if pp:
        return None, {"error": pp, "creation_root": root}
    p = Path(root) / asset / SHEET_DIRNAME / SHEET_FILENAME
    return p, {"creation_root": root, "root_source": src, "project_id": pid,
               "asset_dir": asset, "path": str(p),
               "placement_declared":
                   (( _read_json(PROJECTS_REGISTRY)[0] or {}).get("decision_sheet") or {}
                    ).get("placement", "")}


def read_sheet(path):
    """返回 (data, status)：status ∈ ok / missing / corrupt / not_object。"""
    if not path:
        return None, "no_path"
    data, problem = _read_json(path)
    if problem == "文件不存在：%s" % path:
        return None, "missing"
    if problem:
        return None, "corrupt"
    if not isinstance(data, dict):
        return None, "not_object"
    return data, "ok"


def _slot_key_map():
    """槽 id 与中文标签都能查（人只记得住「全片基调句」）。"""
    slots, problem = slot_defs()
    if problem:
        return None, problem
    m = {}
    for s in slots:
        m[s["slot"]] = s
        m[s["label"]] = s
    return m, None


def human_value(entry):
    """从单里的一项取出「人给的值」；来路不是人 ⇒ 视同没给。"""
    if isinstance(entry, dict):
        if str(entry.get("set_by") or "").lower() != "human":
            return None, "set_by!=human"
        v = entry.get("value")
    else:
        v = entry
    if v in (None, "", []):
        return None, "empty"
    return v, None


def collect(cfg, project, args=None, explicit=None):
    """拼出这次运行的决定单上下文，交给 G13 判「有没有留痕」。

    本函数**只取值、不判断值好不好**（审美与取舍不是机器的活，10-02 裁定）。
    永不抛异常：结构性问题进 errors，缺槽进 missing，让关口一次报全。

    `explicit`＝这批由人显式给过的键清单（`run.py` 从 `--set`／`--resume` 台账算出来，走 ctx 传进来）。
    给了它，运行级槽就**只认这份清单里的**：yaml `args:` 里的流级默认值不算你这批的决定
    （否则 `use_llm_polish: false` 会冒充"你决定过这批不润色"，而裁定是运行级每批重新确认）。
    没给（裸 CLI 自审这类没有批次上下文的调用）⇒ 按"在就算给"处理，并在结果里标
    `explicit_marker: absent`，让关口把它报出来——**降级要可见，不许静默**。
    """
    args = args or {}
    out = {"required": [], "values": {}, "sources": {}, "missing": [],
           "ignored_in_sheet": [], "rejected_args": [], "errors": [],
           "alias_used": {}, "conflicting_aliases": [], "inherited_defaults": [],
           "explicit_marker": "present" if explicit is not None else "absent",
           "sheet_status": "unknown", "sheet_path": None, "project_id": None}
    slots, sp = slot_defs()
    if sp:
        out["errors"].append(sp)
        return out
    out["required"] = [s["slot"] for s in slots]
    spath, info = sheet_path(cfg, project)
    if info.get("error"):
        out["errors"].append(info["error"])
        out["sheet_status"] = "unresolvable"
        return out
    out["sheet_path"] = info["path"]
    out["project_id"] = info["project_id"]
    data, status = read_sheet(spath)
    out["sheet_status"] = status
    if status == "missing":
        out["errors"].append(
            "决定单不存在：%s ⇒ 先建空白单再逐槽填值："
            "python %s init %s" % (info["path"], Path(__file__), info["project_id"]))
    elif status != "ok":
        out["errors"].append("决定单读不出（%s）：%s —— 不猜内容" % (status, info["path"]))
    sheet_slots = ((data or {}).get("slots") or {}) if status == "ok" else {}

    by_slot = {s["slot"]: s for s in slots}
    # —— 项目级：只认单里的，且必须是人给的 ——
    for slot in [s["slot"] for s in slots if s["tier"] == TIER_PROJECT]:
        v, why = human_value(sheet_slots.get(slot))
        if v is not None:
            out["values"][slot] = v
            out["sources"][slot] = "sheet"
        else:
            out["missing"].append(slot)
            if slot in args:
                out["rejected_args"].append(slot)
    # —— 运行级：只认这批显式传的；单里存了值也不用 ——
    # ⚠ 判"给没给"只看**在不在**，不看真值：`enable_audio=false` 被 auto_cast 成 False 之后，
    #   写成 `str(v or "")` 会把 false 当成"没给"——那正好把 10-02 那条
    #   「不润色也要显式写 false」的裁定吃掉，逼人写 true 才能过闸。
    # 别名（`accepts`）：同一个决定在现役 yaml 里有两个键名（润色＝use_llm_polish／use_llm），
    # 任一个都算"人给过了"；**两个都给且值不同 ⇒ 报错，不静默挑一个用**。
    for s in [x for x in slots if x["tier"] == TIER_RUN]:
        slot = s["slot"]
        keys = [slot] + [a for a in (s.get("accepts") or [])]
        given = {k: args[k] for k in keys
                 if k in args and str(args.get(k)) != ""}
        if given and explicit is not None:
            kept = {k: v for k, v in given.items() if k in set(explicit)}
            if not kept:
                # 值在 args 里，但来源是 **yaml 默认**（人没在这批动过）⇒ 不算这批的决定
                out["inherited_defaults"].append(slot)
            given = kept
        if given:
            if len({str(v).strip().lower() for v in given.values()}) > 1:
                out["conflicting_aliases"].append({"slot": slot, "given": given})
                out["missing"].append(slot)
            else:
                picked = slot if slot in given else sorted(given)[0]
                out["values"][slot] = given[picked]
                out["sources"][slot] = "args"
                if picked != slot:
                    out["alias_used"][slot] = picked
        else:
            out["missing"].append(slot)
            v, _why = human_value(sheet_slots.get(slot))
            if v is not None:
                out["ignored_in_sheet"].append(slot)
    alias_to_slot = {}
    for s in slots:
        for a in (s.get("accepts") or []):
            alias_to_slot[a] = s["slot"]
    for key in list(args):
        slot = key if key in by_slot else alias_to_slot.get(key)
        if slot and by_slot[slot]["tier"] == TIER_PROJECT:
            out["rejected_args"].append(slot)
    out["missing"] = sorted(set(out["missing"]))
    out["rejected_args"] = sorted(set(out["rejected_args"]))
    out["ignored_in_sheet"] = sorted(set(out["ignored_in_sheet"]))
    out["slot_labels"] = {s["slot"]: s["label"] for s in slots}
    return out


def init_sheet(cfg, project, force=False):
    """建空白决定单：**所有槽留空**。空不是「机器给了个空值」，是等人填形状。"""
    spath, info = sheet_path(cfg, project)
    if info.get("error"):
        return False, info["error"]
    p = Path(info["path"])
    if p.is_file() and not force:
        return False, "已存在，不覆盖（覆盖＝抹掉人给过的值）：%s" % p
    slots, sp2 = slot_defs()
    if sp2:
        return False, sp2
    data = {"schema_version": SCHEMA_VERSION,
            "project": info["project_id"],
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "_note": "本文件只放**人给的值**。运行级槽（每批重给）不放这里，"
                     "放了也不会被采用——见 engine/decision_sheet.py 铁律 4。",
            "_run_level_slots_not_stored_here": [],
            "slots": {}, "history": []}
    for s in slots:
        if s["tier"] != TIER_PROJECT:
            data["_run_level_slots_not_stored_here"].append(s["slot"])
            continue
        data["slots"][s["slot"]] = {"value": "", "label": s["label"],
                                    "set_by": None, "at": None, "note": ""}
    _atomic_write(p, data)
    return True, "空白决定单已建（值全空，等你填）：%s" % p


def set_slot(cfg, project, slot, value, by="human", reason=""):
    """人填一个槽。改项目级槽＝留旧值＋新值＋时间＋by（G5/裁定：旧值不许覆盖掉）。"""
    if str(by or "").lower() != "human":
        return False, "by 必须是 human：这个文件的存在理由就是「值由人给」，" \
                      "脚本或 agent 代填＝机器又替人做了决定（10-02 铁律）"
    km, kp = _slot_key_map()
    if kp:
        return False, kp
    s = km.get(str(slot).strip())
    if not s:
        return False, "槽「%s」不在 channels_registry.run_slots 里 ⇒ 拒绝写入。" \
                      "要加槽先改注册表（那是规则的活），别往单里塞野键" % slot
    if s["tier"] != TIER_PROJECT:
        return False, "「%s」（%s）是**运行级**槽，每批显式传，不进单：" \
                      "进单就成了「沿用上次的」＝机器替这批做决定" % (s["slot"], s["label"])
    spath, info = sheet_path(cfg, project)
    if info.get("error"):
        return False, info["error"]
    data, status = read_sheet(spath)
    if status != "ok":
        return False, "单不可写（%s）：%s。先 --init 建空白单" % (status, info["path"])
    entry = (data.get("slots") or {}).get(s["slot"])
    old, _why = human_value(entry)
    if not isinstance(entry, dict):
        entry = {"label": s["label"]}
    entry.update({"value": value, "set_by": "human",
                  "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "note": str(reason or "")[:400]})
    data.setdefault("slots", {})[s["slot"]] = entry
    data.setdefault("history", []).append(
        {"slot": s["slot"], "old": old, "new": value,
         "at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": "human",
         "reason": str(reason or "")[:400]})
    data["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _atomic_write(Path(info["path"]), data)
    return True, "已记：%s（%s）= %s｜旧值 %s｜单：%s" % (
        s["slot"], s["label"], value, "（空）" if old is None else old, info["path"])


def amend_sheet(cfg, project):
    """把注册表里**新增的槽**并进已存在的单：新槽值一律留空，已填过的一个都不动。

    为什么需要这条：空白单是按建单当时的槽清单生成的；注册表后来加了槽
    （10-02 批 6 加了「开场节奏基准」），老单里就没有那个键 ⇒ G13 报"缺槽"，
    可人在单里翻不到该往哪儿填。那是"看着像拦，其实是没地方填"，最容易把人推向
    `preflight: off`——正是要避免的死法。
    ⚠ 只做加法：已有键（含被人填过的）一个字都不改；要改值走 `set_slot`（留旧值与时间）。
    """
    spath, info = sheet_path(cfg, project)
    if info.get("error"):
        return False, [], info["error"]
    data, status = read_sheet(spath)
    if status != "ok":
        return False, [], "单不可改（%s）：%s。要新建用 init" % (status, info["path"])
    slots, problem = slot_defs()
    if problem:
        return False, [], problem
    sheet_slots = data.setdefault("slots", {})
    added = []
    for s in [x for x in slots if x["tier"] == TIER_PROJECT]:
        if s["slot"] in sheet_slots:
            continue
        sheet_slots[s["slot"]] = {"value": "", "label": s["label"],
                                  "set_by": None, "at": None,
                                  "note": "批 7-1 补进来的新槽，等本人填"}
        added.append(s["slot"])
    if added:
        data.setdefault("history", []).append(
            {"event": "amend_slots", "slots": sorted(added), "new_values": None,
             "at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": "engine",
             "note": "只补空槽，未替人填任何值；改已有槽必须走 set_slot（by: human）"})
        _atomic_write(Path(info["path"]), data)
    return True, added, ("补进 %d 个新槽（值全空，等你填）：%s"
                         % (len(added), "、".join(sorted(added)) or "无"))


def show(cfg, project):
    spath, info = sheet_path(cfg, project)
    if info.get("error"):
        return info["error"]
    data, status = read_sheet(spath)
    c = collect(cfg, project, {})
    lines = ["决定单路径（现拼）：%s" % info["path"],
             "声明的落点（注册表）：%s" % info.get("placement_declared", ""),
             "文件状态：%s" % status, ""]
    labels = {s["slot"]: s["label"] for s in slot_defs()[0]}
    sheet_slots = ((data or {}).get("slots") or {}) if isinstance(data, dict) else {}
    lines.append("项目级（开工填一次，改动要用户明确指定）：")
    for s in [x for x in slot_defs()[0] if x["tier"] == TIER_PROJECT]:
        v, why = human_value(sheet_slots.get(s["slot"]))
        got = ("= " + str(v)) if v is not None else ("（未填：" + str(why) + "）")
        lines.append("  · %-26s %-14s %s" % (s["slot"], s["label"], got))
    lines.append("")
    lines.append("运行级（每批显式传，不进单）：")
    for s in [x for x in slot_defs()[0] if x["tier"] == TIER_RUN]:
        v, _why = human_value(sheet_slots.get(s["slot"]))
        note = "（单里存了值，但**不采用**：每批要重新给）" if v is not None else ""
        lines.append("  · %-26s %-14s %s" % (s["slot"], s["label"], note))
    lines.append("")
    lines.append("本批（不含 --set）缺的必填槽：%s" %
                 ("、".join(c.get("missing") or []) or "无"))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="运行决定单读写（值只由人给，机器不代填）")
    ap.add_argument("cmd", choices=["slots", "paths", "show", "init", "amend", "set", "check"],
                    help="slots=列槽｜paths=拼路径（给校验器吃，黑盒）｜show=看单｜"
                         "init=建空白单｜amend=把新槽并进已有单（值留空）｜"
                         "set=人填一个槽｜check=查缺")
    ap.add_argument("project", nargs="?", default=None)
    ap.add_argument("slot", nargs="?", default=None)
    ap.add_argument("value", nargs="?", default=None)
    ap.add_argument("--by", default="human", help="set 时必须 human，其余一律拒写")
    ap.add_argument("--reason", default="")
    ap.add_argument("--force", action="store_true", help="init 时允许重建（会先拒覆盖）")
    ap.add_argument("--config", default=str(ENGINE / "config.yaml"))
    a = ap.parse_args(argv)

    cfg = {}
    if a.cmd != "slots":
        try:
            import yaml
            cfg = yaml.safe_load(io.open(a.config, encoding="utf-8")) or {}
        except Exception as e:
            print("!! config 读不到（%s: %s）⇒ 路径拼不出，如实报错不猜" % (type(e).__name__, e))
            return 2

    if a.cmd == "slots":
        slots, problem = slot_defs()
        if problem:
            print("!! %s" % problem)
            return 1
        for s in slots:
            print("%-8s %-26s %s" % (s["tier"], s["slot"], s["label"]))
        return 0
    if a.cmd == "paths":
        # 给校验器（check_registry [G]）吃的机器面：路径由本模块现拼，别处不另算一份。
        slots, sp = slot_defs()
        reg, _rp = _read_json(PROJECTS_REGISTRY)
        out = {"creation_root": None, "root_source": None, "error": None,
               "slots": slots, "slots_problem": sp,
               "placement_declared":
                   ((reg or {}).get("decision_sheet") or {}).get("placement", ""),
               "assembled": {}}
        root, src = creation_root(cfg)
        out["creation_root"], out["root_source"] = root, src
        if root is None:
            out["error"] = src
        else:
            for prj in (reg or {}).get("projects") or []:
                pid = str((prj or {}).get("id") or "")
                p, info = sheet_path(cfg, pid)
                if info.get("error"):
                    out["assembled"][pid] = {"error": info["error"]}
                else:
                    sd, st = read_sheet(p)
                    got = []
                    if st == "ok":
                        for s in (sd.get("slots") or {}):
                            v, _why = human_value((sd.get("slots") or {}).get(s))
                            if v is not None:
                                got.append(s)
                    out["assembled"][pid] = {"path": info["path"],
                                             "exists": Path(info["path"]).is_file(),
                                             "status": st,
                                             "asset_dir": info["asset_dir"],
                                             "human_filled": sorted(got),
                                             "project_slots":
                                                 [s["slot"] for s in slots
                                                  if s["tier"] == TIER_PROJECT]}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if (root and not sp) else 1
    if not a.project:
        print("!! show/init/set/check 需要项目代号（如：无音）")
        return 2
    if a.cmd == "show":
        print(show(cfg, a.project))
        return 0
    if a.cmd == "check":
        c = collect(cfg, a.project, {})
        print("路径：%s｜状态：%s" % (c.get("sheet_path"), c.get("sheet_status")))
        if c.get("errors"):
            print("结构问题：")
            for e in c["errors"]:
                print("  ✗ %s" % e)
        print("缺必填槽：%s" % ("、".join(c.get("missing") or []) or "无"))
        if c.get("ignored_in_sheet"):
            print("⚠ 单里存了运行级槽的值，**不会被采用**：%s" % "、".join(c["ignored_in_sheet"]))
        return 1 if (c.get("missing") or c.get("errors")) else 0
    if a.cmd == "init":
        ok, msg = init_sheet(cfg, a.project, force=a.force)
        print(("✓ " if ok else "✗ ") + msg)
        return 0 if ok else 1
    if a.cmd == "amend":
        ok, added, msg = amend_sheet(cfg, a.project)
        print(("✓ " if ok else "✗ ") + msg)
        return 0 if ok else 1
    if not a.slot or a.value is None:
        print("!! set 需要 槽 与 值：decision_sheet.py set <项目> <槽> <值> --by human")
        return 2
    ok, msg = set_slot(cfg, a.project, a.slot, a.value, by=a.by, reason=a.reason)
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
