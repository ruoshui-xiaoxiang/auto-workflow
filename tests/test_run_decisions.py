# -*- coding: utf-8 -*-
"""批 5-2 回归：运行决定单的「写出—读回—拦截」闭环（10-02 裁定①②＋G-1..G-3）

这组测试存在的理由（同 9-14「裁判件没接线」那条教训）：
留痕机制最怕三种死法，这里一条条钉住——
  ① 静默补默认：缺槽时代填一个值 ⇒ 整套「由人决定」变成摆设；
  ② 绕过无痕：关掉闸跑掉，事后查不到 ⇒ 台账里必须有一条 bypassed；
  ③ 判据越权：机器开始评「这个值好不好」 ⇒ 审美这一维机器是瞎的（R4-08），
     所以这里断言 G13 **只**在留痕层面报错，值再怪也不拦。
"""
import io
import json
import re
import sys
import tokenize
import warnings
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent          # engine/
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent / "tools"))

import tasks as T                                      # noqa: E402
from decision_sheet import (amend_sheet, collect, init_sheet, read_sheet, set_slot,  # noqa: E402
                            sheet_path, slot_defs, TIER_PROJECT, TIER_RUN)
import check_preflight as cp                           # noqa: E402
from check_preflight import Report, g13_run_decisions  # noqa: E402

ENGINE = ROOT
TOOLS = ROOT.parent / "tools"
# 路径形状的坏转义，两种形状：① **单个字母**＋`:＼`＋字母（盘符开头的 `"D:\AIWorkflow…"`）
# ② 反斜杠＋字母一路拼到「.扩展名」（`"engine\tasks.py"`）。
# ⚠ 为什么不写成「凡是 反斜杠＋字母 就算」：`"\n\n"`、`b'\x89PNG\r\n'` 也长那样，那是真转义。
# ⚠ ①里那个「单个字母」的限定不是洁癖：`"summary:\n[Shot 1]"` 也是 字母＋冒号＋反斜杠＋字母，
#    不加限定就把现役 fixture 全误伤了（第一次试跑就是这么红了 6 条）——
#    尺子误伤多了，真坏的那条反而没人看。
# ⚠ 2026-10-19 又窄化一次：把 `%` 加进①的负向断言。原因是 `"%s:\n%s"`（h3_official_spec.py:668，
#    Ref2VA 六段装配用的格式串）里的 `s:\n` 长得和盘符 `s:\` 一模一样，而 `s` 前面是 `%`
#    （非字母数字）⇒ 命中①，成了长期误报。`%s:` 是 Python 格式符的尾巴，不是盘符。
#    这是与上面「单个字母」同一类的窄化，不是放宽：真盘符路径 `"D:\AIWorkflow"` 里 `D` 前面是
#    引号，仍然命中。改完 test_the_escape_detector_itself_detects 的 4 个坏样本必须仍全被抓。
_PATH_ESC = re.compile(r"(?<![A-Za-z0-9%])[A-Za-z]:\\[A-Za-z]"
                       r"|(?<!\\)\\[A-Za-z][\w\-]*\.[A-Za-z]")


def _cfg(tmp_path, creation_root=None):
    """最小 config：只给决定单要用的那两根（缺哪根就如实报缺，不许写死盘符）。"""
    return {"log_dir": str(tmp_path / "logs"),
            "project": "无音",
            "project_aliases": {"无音": ["wuyin", "无音"]},
            "paths": {"creation_root": str(creation_root or tmp_path)}}


def _fill(tmp_path, slots=None, root=None):
    """把**全部项目级槽**由"人"填上值。
    ⚠ 槽清单从注册表现读，不在这儿硬编——10-02 批 7 加了「开场节奏基准」，
       硬编的那版测试当时就会漏填一个槽、把"缺槽"当成正常，是假绿。"""
    ok, msg = init_sheet(_cfg(tmp_path, root), "无音")
    assert ok, msg
    cfg = _cfg(tmp_path, root)
    for s in (slots or [x["slot"] for x in slot_defs()[0] if x["tier"] == TIER_PROJECT]):
        ok, msg = set_slot(cfg, "无音", s, "人给的值-" + s, by="human", reason="测试")
        assert ok, msg
    return cfg


# ---------------- 写出方：落账、读回、摘要绑定 ----------------

def test_record_and_load_roundtrip_is_key_bound(tmp_path):
    cfg = {"log_dir": str(tmp_path)}
    dig = T.content_digest(T.digest_parts("提示词A", ["r1.png"], [], 864, 1536, 124))
    miss = T.record_run_decisions(cfg, "无音", "wf", "G13", dig,
                                  {"use_llm_polish": False, "enable_audio": False},
                                  ("use_llm_polish", "enable_audio", "resolution_tier"),
                                  {"use_llm_polish": "args", "enable_audio": "args"})
    assert miss == ["resolution_tier"], "缺的必填槽必须如实暴露，不许补齐"
    got = T.load_run_decisions(cfg, "无音", "wf", "G13", dig)
    assert got and got["by"] == "human" and got["decisions"]["enable_audio"] is False
    assert got["sources"]["enable_audio"] == "args", "「by: human」要有来路背书，不是自夸"
    # 两个入口必须给同一个结果（键的拼法只有一处）
    assert T.load_run_decisions_by_key(cfg, T.gate_key("无音", "wf", "G13", dig)) == got


def test_false_is_a_decision_not_an_empty_slot(tmp_path):
    """★ 10-02 裁定的正面钉：不润色／不要音频都要**显式写 false** 才算给过。

    写成「看真值」的实现会把 false 当成没给 ⇒ 逼人写 true 才能过闸，裁定从内部被吃掉。
    """
    p = tmp_path / "无音项目" / "_项目档案"
    p.mkdir(parents=True)
    cfg = _cfg(tmp_path)
    c = collect(cfg, "无音", {"use_llm_polish": False, "enable_audio": False,
                              "resolution_tier": "std"})
    assert set(c["values"]) == {"use_llm_polish", "enable_audio", "resolution_tier"}
    assert not [s for s in c["missing"]
                if s in ("use_llm_polish", "enable_audio", "resolution_tier")]


def test_load_returns_none_never_a_default(tmp_path):
    cfg = {"log_dir": str(tmp_path)}
    assert T.load_run_decisions(cfg, "无音", "wf", "G13", "deadbeef") is None
    assert T.load_run_decisions_by_key(cfg, None) is None


def test_changing_prompt_invalidates_previous_decisions(tmp_path):
    cfg = {"log_dir": str(tmp_path)}
    d1 = T.content_digest(T.digest_parts("提示词A", [], []))
    d2 = T.content_digest(T.digest_parts("提示词B", [], []))
    T.record_run_decisions(cfg, "无音", "wf", "G13", d1, {"a": "1"}, ("a",))
    assert T.load_run_decisions(cfg, "无音", "wf", "G13", d2) is None, \
        "内容一变旧决定就该失效，否则上一批的值会沿用到这一批"


def test_corrupt_ledger_raises_instead_of_guessing(tmp_path):
    d = tmp_path
    d.mkdir(parents=True, exist_ok=True)
    (d / "gate_approvals.json").write_text("{坏掉的台账", encoding="utf-8")
    with pytest.raises(RuntimeError):
        T.record_run_decisions({"log_dir": str(d)}, "无音", "wf", "G13", "x", {}, ())


# ---------------- 绕过必须留字据（R5-07） ----------------

def test_bypass_records_evidence(tmp_path):
    cfg = {"log_dir": str(tmp_path)}
    key = T.record_gate_bypass(cfg, "无音", "h3_i2va_video", "config.preflight=off",
                               gates=["G1", "G13"])
    entry = T.read_approvals(cfg)["bypassed"][key]
    assert entry["by"] == "human" and "preflight" in entry["reason"]
    assert entry["gates"] == ["G1", "G13"]


def test_preflight_off_writes_bypass_into_ledger(tmp_path):
    """关掉开关那条路，绕过的痕迹必须落到台账里，而不是只进日志。"""
    cfg = _cfg(tmp_path)
    cfg = dict(cfg, preflight="off", comfyui={"root": str(tmp_path)})
    logs = []
    ctx = {"cfg": cfg, "args": {"theme": "t"}, "batch_dir": str(tmp_path),
           "log": logs.append, "wf_root": str(ROOT), "workflow": "h3_i2va_video"}
    T.preflight_or_die({"prompt": "x", "ref_images": [], "width": 864, "height": 1536,
                        "length": 124}, ctx, [], [])
    assert any("留字据" in m for m in logs)
    data = json.loads((Path(cfg["log_dir"]) / "gate_approvals.json")
                      .read_text(encoding="utf-8"))
    assert data.get("bypassed"), "绕过了却没字据＝绕过无痕，这条就是要堵的洞"


# ---------------- 决定单本体：值只能人给 ----------------

def test_init_sheet_has_no_machine_filled_values(tmp_path):
    cfg = _cfg(tmp_path)
    ok, msg = init_sheet(cfg, "无音")
    assert ok, msg
    p, info = sheet_path(cfg, "无音")
    assert p == Path(info["path"]) and "无音项目" in str(p), "落点跟项目走（10-02 裁定①）"
    data, status = read_sheet(p)
    assert status == "ok"
    for slot, entry in (data.get("slots") or {}).items():
        assert entry.get("value") in (None, ""), "空白单里不许有任何值：%s" % slot
        assert entry.get("set_by") is None
    assert set(data.get("_run_level_slots_not_stored_here") or {}) == \
        {s["slot"] for s in slot_defs()[0] if s["tier"] == TIER_RUN}, \
        "运行级槽不进单：进单就变成「沿用上次的」"


def test_set_slot_refuses_machine_provenance(tmp_path):
    cfg = _cfg(tmp_path)
    init_sheet(cfg, "无音")
    ok, msg = set_slot(cfg, "无音", "aspect_ratio", "16:9", by="agent")
    assert not ok and "human" in msg, "非 human 的来路一律拒写"
    ok, msg = set_slot(cfg, "无音", "enable_audio", "false", by="human")
    assert not ok and "运行级" in msg, "运行级槽不许存进单（每批重给）"
    ok, msg = set_slot(cfg, "无音", "随便一个野键", "x", by="human")
    assert not ok and "不在 channels_registry" in msg, "注册表没声明的键拒绝写入"


def test_project_level_change_keeps_history(tmp_path):
    cfg = _cfg(tmp_path)
    init_sheet(cfg, "无音")
    set_slot(cfg, "无音", "aspect_ratio", "9:16", by="human", reason="开工")
    set_slot(cfg, "无音", "aspect_ratio", "16:9", by="human", reason="你明确说要换")
    p, info = sheet_path(cfg, "无音")
    data, _ = read_sheet(Path(info["path"]))
    hist = data.get("history") or []
    assert len(hist) == 2 and hist[-1]["old"] == "9:16" and hist[-1]["by"] == "human", \
        "旧值不许被覆盖掉——「这次为什么变了」要能复盘"


def test_project_level_slot_cannot_be_passed_per_batch(tmp_path):
    """10-02 裁定②的关键含义：常用画幅属项目级 ⇒ 按批传上来只报不用，并算错误。"""
    cfg = _fill(tmp_path)
    c = collect(cfg, "无音", {"aspect_ratio": "16:9", "use_llm_polish": False,
                              "enable_audio": False, "resolution_tier": "std"})
    assert "aspect_ratio" in c["rejected_args"]
    assert c["values"].get("aspect_ratio") == "人给的值-aspect_ratio", \
        "按批传上来的项目级值绝不能盖掉单里人给过的值（要改就走 set_slot，留旧值与时间）"


def test_run_level_value_stored_in_sheet_is_ignored(tmp_path):
    cfg = _fill(tmp_path)
    p, info = sheet_path(cfg, "无音")
    data, _ = read_sheet(Path(info["path"]))
    data["slots"]["enable_audio"] = {"value": True, "set_by": "human", "at": "x",
                                     "note": "有人手痒存进来了"}
    Path(info["path"]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    c = collect(cfg, "无音", {})
    assert "enable_audio" in c["ignored_in_sheet"]
    assert "enable_audio" in c["missing"] and "enable_audio" not in c["values"]


def test_missing_sheet_and_missing_config_root_both_report(tmp_path):
    c = collect(_cfg(tmp_path), "无音", {})
    assert c["missing"] and c["errors"], "缺单要同时报「缺哪些槽」"
    c2 = collect({"project": "无音"}, "无音", {})
    assert c2["errors"] and "creation_root" in c2["errors"][0], \
        "config 没给根就如实报缺——脚本里不许藏着 E:\\创作 那份抄本"
    c3 = collect(_cfg(tmp_path), "没登记过的项目名", {})
    assert c3["errors"] and "不在 projects_registry" in c3["errors"][0]


# ---------------- G13：只查留痕，不查值 ----------------

def test_yaml_default_is_not_this_batches_decision(tmp_path):
    """★ 流级默认冒充人的决定——这一条堵的就是它。

    `image_draft_batch.yaml` 的 args 里写着 `use_llm_polish: false`。
    如果"参数里存在"就算"人给过了"，那这批根本没做过任何润色决定也能过闸；
    裁定写的是运行级**每批重新确认** ⇒ run.py 必须把"这批显式给过哪些键"带进来。
    """
    cfg = _fill(tmp_path)
    args = {"use_llm_polish": False, "enable_audio": False, "resolution_tier": "std"}
    inherited = collect(cfg, "无音", args, explicit=[])          # 全是 yaml 默认，没人动过
    assert sorted(inherited["inherited_defaults"]) == ["enable_audio", "resolution_tier",
                                                       "use_llm_polish"]
    assert not [s for s in inherited["values"]
                if s in ("use_llm_polish", "enable_audio", "resolution_tier")], \
        "默认值一个都不许被当成这批的决定（项目级那五个来自单，是另一码事）"
    explicit = collect(cfg, "无音", args,
                       explicit=["use_llm_polish", "enable_audio", "resolution_tier"])
    assert not explicit["inherited_defaults"]
    assert set(explicit["values"]) >= {"use_llm_polish", "enable_audio", "resolution_tier"}
    rep = Report()
    g13_run_decisions(rep, inherited)
    assert any("只有 yaml 里的流级默认值" in i[2] for i in rep.items)


def test_alias_names_satisfy_slot_but_conflicts_are_reported(tmp_path):
    """润色这个决定在现役 yaml 里有两个键名（`use_llm_polish` 4 份／`use_llm` 1 份）。
    任一个都算人给过；两个都给且值不同 ⇒ 报错，不静默挑一个。"""
    cfg = _fill(tmp_path)
    c = collect(cfg, "无音", {"use_llm": True, "enable_audio": False,
                              "resolution_tier": "pro"}, explicit=["use_llm"])
    assert c["values"].get("use_llm_polish") is True
    assert c["alias_used"] == {"use_llm_polish": "use_llm"}, "台账存正名，入口认别名"
    bad = collect(cfg, "无音", {"use_llm": True, "use_llm_polish": False},
                  explicit=["use_llm", "use_llm_polish"])
    assert bad["conflicting_aliases"], "两个写法值不同必须报出来"
    assert "use_llm_polish" in bad["missing"]
    rep = Report()
    g13_run_decisions(rep, dict(bad, required=["use_llm_polish"],
                                slot_labels={"use_llm_polish": "要不要润色"},
                                errors=[], sheet_status="ok"))
    assert any("值不一致" in i[2] for i in rep.items if i[0] == "error")


def test_webui_offers_the_run_level_slots():
    """收集入口必须在 webui 那条免终端的路上——不然"每批问人"只在命令行成立，
       而这套系统日常就是从 webui 点的。"""
    import webui
    slots = [s["slot"] for s in slot_defs()[0] if s["tier"] == TIER_RUN]
    assert slots, "槽清单读不到，这条测试就没内容了"
    m = webui.workflow_meta("image_draft_batch")
    assert m.get("decision_slots_error") is None
    for s in slots:
        assert s in m["advanced"], "%s 没进 webui 的高级参数区 ⇒ 免终端那条路给不了这个决定" % s
        assert m["fields"][s].get("value") in (None, ""), \
            "表单里不许预填默认值（预填＝机器替人给）"
    sm = webui.workflow_meta("selftest")
    assert not [s for s in slots if s in sm["advanced"]], "自测不该被决定单绑住"


def test_run_records_explicit_keys_in_ctx():
    """`run.py` 得把"这批显式给过的键"传下去；ctx 里没有这一项，G13 就只能降级。"""
    src = io.open(ROOT / "run.py", encoding="utf-8").read()
    assert "explicit_args" in src, "run.py 不再登记显式来源 ⇒ 流级默认会冒充人的决定"
    assert '"explicit_args": explicit_args' in src, "登记了但没进 ctx ⇒ 传不到关口"


def _rd(**kw):
    base = {"required": ["style_baseline_sentence", "use_llm_polish"],
            "values": {"style_baseline_sentence": "冷素", "use_llm_polish": False},
            "sources": {"style_baseline_sentence": "sheet", "use_llm_polish": "args"},
            "missing": [], "rejected_args": [], "ignored_in_sheet": [],
            "inherited_defaults": [], "alias_used": {}, "conflicting_aliases": [],
            "errors": [], "slot_labels": {"style_baseline_sentence": "全片基调句",
                                          "use_llm_polish": "要不要润色"}}
    base.update(kw)
    return base


def test_g13_blocks_empty_slots():
    rep = Report()
    g13_run_decisions(rep, _rd(missing=["use_llm_polish"]))
    assert any(lv == "error" and "use_llm_polish" in t
               for lv, _, t in rep.items if lv == "error"), "空槽即拦"
    assert any("decision_sheet.py set" in t for _, _, t in rep.items), "报错要给出填法"


def test_g13_passes_without_judging_values():
    """值再怪也不拦：审美与档位取舍是人的活，本闸只确认「有人给过」。"""
    rep = Report()
    g13_run_decisions(rep, _rd(values={"style_baseline_sentence": "极其怪异的一句话",
                                       "use_llm_polish": False}))
    assert not rep.errors and any(lv == "ok" for lv, _, _ in rep.items)


def test_g13_rejects_smuggled_default_source():
    rep = Report()
    g13_run_decisions(rep, _rd(sources={"style_baseline_sentence": "fallback",
                                         "use_llm_polish": "args"}))
    assert any(i[0] == "error" and "来路" in i[2] for i in rep.items)


def test_run_checks_only_runs_g13_when_selected(tmp_path):
    """裸自审 CLI 的默认子里没有 G13：那条路没有批次上下文，
       真出片的路径由引擎侧默认子集负责（G13 在那边是默认开的）。"""
    rep = cp.run_checks({"prompt": "x", "refs": [], "only": ["G7"]})
    assert not any(g == "G13" for _, g, _ in rep.items)
    rep2 = cp.run_checks({"prompt": "x", "refs": [], "only": ["G13"],
                          "run_decisions": None})
    assert any(g == "G13" and lv == "error" for lv, g, _ in rep2.items)


def test_engine_default_subset_includes_g13(tmp_path, monkeypatch):
    """引擎侧（真出片走的那条）默认子集里必须有 G13，且决定单上下文真的接上了。"""
    seen = {}

    def fake_run_checks(spec, rep=None):
        seen["only"] = list(spec["only"])
        seen["rd"] = spec.get("run_decisions")
        return Report()

    monkeypatch.setattr(cp, "run_checks", fake_run_checks)
    cfg = dict(_cfg(tmp_path), preflight="on", comfyui={"root": str(tmp_path)})
    ctx = {"cfg": cfg, "args": {"theme": "t"}, "batch_dir": str(tmp_path),
           "log": lambda m: None, "wf_root": str(ROOT), "workflow": "h3_i2va_video"}
    T.preflight_or_die({"prompt": "x", "ref_images": [], "width": 864,
                        "height": 1536, "length": 124}, ctx, [], [])
    assert "G13" in seen["only"], "error 级关口不该因为调用方式不同而消失"
    assert seen["rd"] is not None, "G13 被要求跑却没接上决定单上下文＝接线坏了"


def test_g13_flags_stray_keys_as_warn_not_error():
    rep = Report()
    g13_run_decisions(rep, _rd(values={"style_baseline_sentence": "冷素",
                                       "use_llm_polish": False, "旧槽名": "x"}))
    assert not rep.errors and any(lv == "warn" and "旧槽名" in t for lv, _, t in rep.items)


def test_g13_never_passes_on_empty_required_list():
    rep = Report()
    g13_run_decisions(rep, _rd(required=[]))
    assert rep.errors, "必填清单为空＝注册表空了，不能当成「都不用问」"
    rep2 = Report()
    g13_run_decisions(rep2, None)
    assert rep2.errors, "接线坏了也要报错，不许静默放行"


def test_real_gate_step_blocks_on_blank_sheet(tmp_path):
    """真走 YAML 的 gate 步（不是只测函数）：空白单＝项目级槽一个都没人给 ⇒ 必须拦。

    单独有这条的理由：G13 的判据在 check_preflight 里绿了，不代表引擎真调到了它——
    9-14 那 10 个裁判件就是这么废的（有代码，没接线）。
    """
    p = _image_gate_step()
    cfg = dict(_cfg(tmp_path), preflight="on", comfyui={"root": str(tmp_path)},
               characters_needing_anchor=[])
    ctx = {"cfg": cfg, "args": {"theme": "首帧测试"}, "workflow": "image_draft_batch",
           "log": lambda m: None, "batch_dir": str(tmp_path / "无音" / "batch"),
           "wf_root": str(ROOT), "step_id": "pre"}
    with pytest.raises(RuntimeError, match="G13"):
        T.REGISTRY["gate"](p, ctx)


def test_real_gate_step_passes_and_leaves_evidence(tmp_path):
    """人把五个项目级槽填进单、这批又显式给了三个运行级槽 ⇒ 放行，且台账里查得到。"""
    p = _image_gate_step()
    cfg = dict(_fill(tmp_path), preflight="on", comfyui={"root": str(tmp_path)},
               characters_needing_anchor=[])
    ctx = {"cfg": cfg, "args": {"theme": "首帧测试", "use_llm_polish": False,
                                "enable_audio": False, "resolution_tier": "std"},
           "workflow": "image_draft_batch", "log": lambda m: None,
           "batch_dir": str(tmp_path / "无音" / "batch"),
           "wf_root": str(ROOT), "step_id": "pre"}
    assert T.REGISTRY["gate"](p, ctx)["auto"] is True
    led = json.loads((Path(cfg["log_dir"]) / "gate_approvals.json")
                     .read_text(encoding="utf-8"))
    entries = list((led.get("run_decisions") or {}).values())
    assert len(entries) == 1, entries
    e = entries[0]
    assert e["by"] == "human" and e["required_missing"] == []
    proj = [s["slot"] for s in slot_defs()[0] if s["tier"] == TIER_PROJECT]
    rn = [s["slot"] for s in slot_defs()[0] if s["tier"] == TIER_RUN]
    assert set(e["sources"]) == set(proj) | set(rn), \
        "来源表必须逐个必填槽都有——槽清单加了新槽时这条会红，而不是悄悄少一格"
    assert all(e["sources"][s] == "sheet" for s in proj), "项目级只能来自单"
    assert all(e["sources"][s] == "args" for s in rn), "运行级只能来自这批参数"


def test_amend_adds_new_slots_empty_and_keeps_human_values(tmp_path):
    """注册表加了槽之后，老单要有"补槽"这条路：补进来的必须是空值，且不动人已填的。

    没有这条入口会怎样：G13 报缺槽，可人在单里翻不到该往哪儿填 ⇒
    看着像拦、其实是没地方填，最容易把人推向 `preflight: off`（那才是要防的死法）。
    """
    cfg = _fill(tmp_path)
    set_slot(cfg, "无音", "aspect_ratio", "9:16", by="human", reason="开工时定的")
    slots, problem = slot_defs()
    assert not problem
    proj = [s["slot"] for s in slot_defs()[0] if s["tier"] == TIER_PROJECT]
    p, info = sheet_path(cfg, "无音")
    data, st = read_sheet(p)
    assert st == "ok"
    # 模拟"注册表比单多一个槽"：先删掉一个键，再 amend 补回来
    victim = proj[-1]
    data["slots"].pop(victim, None)
    Path(info["path"]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ok, added, msg = amend_sheet(cfg, "无音")
    assert ok and added == [victim], msg
    data2, _ = read_sheet(Path(info["path"]))
    assert data2["slots"][victim]["value"] == "" and data2["slots"][victim]["set_by"] is None, \
        "补槽只能补空，不许替人填"
    assert data2["slots"]["aspect_ratio"]["value"] == "9:16", "人已填的值一个字都不许动"
    assert data2["history"][-1]["by"] == "engine" and data2["history"][-1]["event"] == "amend_slots"
    # 幂等：再跑一次不该重复补、也不该改动任何东西
    ok2, added2, _msg2 = amend_sheet(cfg, "无音")
    assert ok2 and added2 == []


def test_new_project_slot_is_required_and_blocks(tmp_path):
    """新加的「开场节奏基准」必须真的进必填集合，并且没填就拦——不是只在表里写着好看。"""
    slots = [s["slot"] for s in slot_defs()[0] if s["tier"] == TIER_PROJECT]
    assert "opening_rhythm_baseline" in slots, "批 6 问 1 裁的槽没进注册表"
    cfg = _fill(tmp_path, slots=[s for s in slots if s != "opening_rhythm_baseline"])
    c = collect(cfg, "无音", {"use_llm_polish": False, "enable_audio": False,
                              "resolution_tier": "std"})
    assert "opening_rhythm_baseline" in c["missing"]
    rep = Report()
    g13_run_decisions(rep, c)
    assert any("opening_rhythm_baseline" in i[2] for i in rep.items if i[0] == "error")


def _image_gate_step():
    d = yaml.safe_load(io.open(WF_DIR / "image_draft_batch.yaml", encoding="utf-8"))
    p = dict(d["steps"][0])
    p.update(prompt="Gunmetal spacecraft crossing a dark starfield.",
             width=1344, height=768)
    assert "G13" in (p.get("auto_gates") or []), "这条流没声明 G13，本测试的前提就没了"
    return p


# ---------------- 覆盖面对账：会产出媒体的流一条都不能漏 ----------------

# 2026-10-19 第⑤条接线时新增 `image`（即梦/本地图源）：**算产媒体**——
# 它产的是首帧/定妆图，正是 G13 要留痕的那类决定（画幅、分辨率、要不要润色都会改变产物）。
# 归类错向的代价：漏进 NON_PRODUCING ⇒ 用它的流从此不跑 G13，而且查不出来（假阴）。
PRODUCING = {"video", "comfyui", "control", "refine", "h3_movie", "image"}
# 2026-11-04：`auto` 从 PRODUCING 挪到 NON_PRODUCING——它现在是**路障桩**（抛错，不产媒体），
# `vl_aesthetic` 同样只注册成桩。留着注册名是为了误引时报错报得清楚，不是为了产东西。
NON_PRODUCING = {"gate", "llm", "feishu", "sheets", "files", "shell", "vl_qc",
                 "auto", "vl_aesthetic"}
WF_DIR = ROOT / "workflows"


def _flows():
    out = []
    for f in sorted(WF_DIR.glob("*.yaml")):
        d = yaml.safe_load(io.open(f, encoding="utf-8"))
        steps = d.get("steps") or []
        tasks = {str(s.get("task")) for s in steps}
        ags = [set(map(str, s.get("auto_gates") or [])) for s in steps if s.get("auto_gates")]
        out.append((f, tasks, ags))
    return out


def test_every_task_kind_is_classified():
    """引擎注册的每种 task 都必须先归类——否则「产媒体」集合会悄悄漏掉新类型，
       漏掉的那条流从此不跑 G13，而这种漏是查不出来的（假阴比假阳坏）。"""
    registered = set(T.REGISTRY)
    unknown = registered - PRODUCING - NON_PRODUCING
    assert not unknown, ("未归类的 task：%s —— 先决定它算不算会产出媒体，"
                         "再谈 G13 覆盖（这个集合决定哪些流必须留痕）" % sorted(unknown))
    assert registered == PRODUCING | NON_PRODUCING, "归类表与注册表必须一一对应"


def test_g13_declared_on_every_producing_flow():
    missing = []
    for f, tasks, ags in _flows():
        if f.name.startswith("selftest"):
            continue
        if tasks & PRODUCING and ags and not all("G13" in a for a in ags):
            missing.append(f.name)
    assert not missing, "这些会产出媒体的流没把 G13 写进 auto_gates：%s" % missing


def test_selftest_flows_stay_out_of_sheet_dependency():
    """自测不许依赖人填过的单，否则自测永远红＝没有自测。"""
    for f, _tasks, ags in _flows():
        if f.name.startswith("selftest"):
            assert all("G13" not in a for a in ags), f.name


# ---------------- 卫生：反斜杠转义这一类坑，机器盯住 ----------------

def _bad_path_escapes(src, name):
    """找两类「不报错就悄悄把路径改坏」的写法。

    类一：非法转义（`\\c`、`\\A`…）——Python 只给 SyntaxWarning，多数时候没人看见。
    类二：**看着就像 Windows 路径**的 反斜杠＋字母（`engine\\tasks.py`、`D:\\AIWorkflow\\…`），
          其中 `\\t`/`\\r`/`\\a` 是**合法**转义 ⇒ 编译器一声不吭，字符串里已经是制表符/BEL。
    类三：类二**发生之后**留在文件里的真控制字符（换页／垂直制表／退格）——反斜杠已经没了，
          类一、二都看不见它，但路径已经指不到东西（本轮手册登记就炸过一次）。
    为什么类二要加「像路径」这个限定：`"\\n"` 也是 反斜杠＋字母，但它是真的换行，
    不算上这个限定就是一把到处乱指的红叉——假阳报多了，真坏的那条反而没人看。
    我在这套框架里为此踩过三次（`\a` 把指针里的路径啃出一个 BEL 来），靠人眼不成立。
    """
    out = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(src, name, "exec")
        except SyntaxError as e:
            out.append("%s SyntaxError：%s" % (name, e))
    for wn in caught:
        if issubclass(wn.category, SyntaxWarning):
            out.append("%s 第 %s 行 SyntaxWarning：%s" % (name, wn.lineno, wn.message))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.STRING:
                continue
            # 类三：字符串里躺着**真控制字符**（换页 0x0C／垂直制表 0x0B／退格 0x08…）。
            #   这不是风格问题，是上面那类坑的"事后尸体"：`\post\fx_light.py` 里的 `\f`
            #   被编译成换页符之后，文件里再也看不到反斜杠＋字母 ⇒ 类二类一都抓不到，
            #   但它指向的路径已经不存在了（本轮手册登记就炸出过一次：源缺失 1 个）。
            ctrl = re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", tok.string)
            if ctrl:
                out.append("%s 第 %d 行：字符串里有真控制字符 %s ⇒ 十有八九是转义把路径啃断了"
                           % (name, tok.start[0],
                              "、".join("0x%02X" % ord(c) for c in set(ctrl))))
            pre = re.match(r"[A-Za-z_]*", tok.string).group(0)
            if "r" in pre.lower():
                continue          # raw 字符串里的反斜杠就是反斜杠，合法
            if _PATH_ESC.search(tok.string[len(pre):].lstrip("'\"")):
                out.append("%s 第 %d 行：非 raw 字符串里有「路径形状的 反斜杠＋字母」"
                           "⇒ 会被静默改坏：%s" % (name, tok.start[0], tok.string[:44]))
    except Exception as e:
        out.append("%s tokenize 失败：%s" % (name, e))
    return out


def test_no_silent_backslash_escape_in_engine_and_tools():
    """扫描范围含两个 `99_维护` 目录 —— 不在引擎里的那些维护脚本同样会踩这个坑
       （本轮就在那两个目录里各抓到一次：docstring 里的盘符路径变成非法转义）。
       目录读不到＝报错，不许"跳过就算过"。"""
    bad, scanned = [], 0
    dirs = [ENGINE, TOOLS, ROOT / "tests",
            Path(r"E:\本地工作流规范手册\99_维护"), Path(r"E:\若水AI电影\99_维护")]
    for d in dirs:
        if not d.is_dir():
            bad.append("%s 这个目录读不到 ⇒ 本条没跑满，不算通过" % d)
            continue
        py = sorted(d.glob("*.py"))
        if not py:
            bad.append("%s 下一个 .py 都没扫到 ⇒ 路径写错了" % d)
        for f in py:
            scanned += 1
            # 2026-10-19 修：原来用 encoding="utf-8" 读。带 BOM 的文件（engine/tasks.py、
            # tools/measure_fight_cuts.py）会把 U+FEFF 当正文字符读进来，compile() 当场
            # SyntaxError ⇒ 这两个文件**从来没被真正扫过**：检测器在 143 个文件里瞎了 2 个，
            # 而 tasks.py 正是最容易长出盘符路径的那个。改 utf-8-sig 对有/无 BOM 都正确，
            # 不是放宽判据（Python 解释器本身就接受源码 BOM，所以这不是代码 bug 是测试 bug）。
            bad += _bad_path_escapes(io.open(f, encoding="utf-8-sig").read(), f.name)
    assert scanned, "一个文件都没扫 ⇒ 这条测试是空跑的"
    assert not bad, "非法转义或路径形状的坏转义（会被静默改坏），共扫 %d 个文件：\n%s" % (
        scanned, "\n".join(bad))


def test_the_escape_detector_itself_detects():
    """反向验证：这条测试不是「永远绿的摆设」——坏写法必须被抓，好写法必须不误伤。"""
    bad_samples = [
        r'x = "D:\AIWorkflow\tools\run.py"',      # 合法转义（\t \r）＝静默改坏
        'x = "engine\\channels.py"',              # \c＝非法转义 SyntaxWarning
        r'def f():' + "\n    " + r'"""见 tools\check.py"""',
        'x = "' + r"\post" + chr(12) + 'x_light.py"',   # 类三：转义已经啃完，只剩真换页符
    ]
    for src in bad_samples:
        hits = _bad_path_escapes(src, "<植入样本>")
        assert hits, "植入的坏样本没被抓到 ⇒ 探测器失效：%r" % src[:40]
    good = [r'x = r"D:\AIWorkflow\tools\run.py"',        # raw：反斜杠就是反斜杠
            r'x = "D:\\AIWorkflow\\tools"',              # 双写：合法且确实是路径分隔
            'x = "第一段\\n第二段"',                       # 真的换行，不是路径
            'x = "E:\\\\创作\\\\无音项目"',
            'x = "summary:\\n[Shot 1] At 00:00.00"']     # 标签＋换行：曾被误伤的那类
    for src in good:
        assert not _bad_path_escapes(src, "<好样本>"), "误伤好写法：%s" % src
