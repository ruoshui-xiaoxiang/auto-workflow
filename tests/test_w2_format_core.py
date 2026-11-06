# -*- coding: utf-8 -*-
"""W2 验收（V2-1~V2-5）：格式核心单一真源 + 强制英文编译 + 房内规则分层。

V2-1 五模式官方样例非空、齐全，各入口判出的模式一致
V2-2 错首行／字段重复／字段乱序／十块混入／越界 Picture 至少各命中一次
V2-3 中文正文被格式核心同一判定拦；编译不改原稿字节
V2-4 无对白巨物稿不触发 D7/D8；D5 按 Shot 计人；房内专项默认 warn，显式开启才 error
V2-5 编译截断/漏台词时校验非零退出（提交前停住）
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import h3_official_spec as SPEC      # noqa: E402
import h3_rule_gate as RG            # noqa: E402
import check_h3_dialogue as DL       # noqa: E402
import check_preflight as CP         # noqa: E402
import prompt_compile as PC          # noqa: E402

BODY = ("integrated_multimodal_description: [Shot 1] Live-action, cinematic. "
        "A woman stands at a stone gate; the camera Push In slowly.\n\n"
        "overall_soundscape: Wind through the gate.\n\n"
        "non_diegetic_music: N/A")
I2 = CP.SKELETON_INSTRUCTION + "\n\n" + BODY
FL = (CP.FL2VA_FIRST_LINE.replace("{N}", "1").replace("{S}", "5.00") + "\n\n" + BODY)
L2 = (CP.L2VA_FIRST_LINE.replace("{N}", "1").replace("{S}", "5.00") + "\n\n" + BODY)
T2 = BODY
R6 = ("subject_definitions: <Subject 1> a woman in a dark robe.\n\n"
      "summary: [reference generation] <Subject 1> walks through the gate from <Picture 1>.\n\n"
      "retention_analysis: <Subject 1> fully_preserved from <Picture 1>\n\n"
      "detailed_description: [Shot 1] She turns toward the camera and the camera Push In.\n\n"
      "overall_soundscape: Wind.\n\n"
      "non_diegetic_music: N/A")
OFFICIAL = {"i2va": I2, "fl2va": FL, "l2va": L2, "t2va": T2, "ref2va": R6}


# ------------------------------------------------------------------ V2-1
@pytest.mark.parametrize("mode", sorted(OFFICIAL))
def test_official_samples_are_non_empty_and_agree_across_entries(mode):
    text = OFFICIAL[mode]
    assert text.strip()
    assert SPEC.detect_mode(text) == mode, "格式核心自己判不稳"
    # 入口 1：跑前闸 G7 用的首行判据（已委托核心）
    got = SPEC.detect_skeleton_mode(text) if mode != "ref2va" else "ref2va"
    assert got == mode
    # 入口 2/3：房内格式闸与对白闸必须不再各写一份表 —— 合法稿不该报错
    fmt_rows = [c for _rid, chks in RG.check_format(text, channel="h3", expect=mode)
                for c in chks if c["lvl"] == "error"]
    assert not fmt_rows, [(c["name"], c["msg"]) for c in fmt_rows]
    dlg, _ = DL.check_text(text, mode=mode)
    assert not [i for i in dlg if str(i).startswith("D10")], dlg
    # 入口 4：统一入口 check_h3_all 必须认出同一模式，且不因"房子规矩"误升 error
    import check_h3_all as ALL
    det, fmt, rows = ALL.check_one(text, mode=mode)
    assert det == mode, (det, mode)
    assert [r for r in rows if r[0] == "error"] == [], rows


def test_check_h3_all_dispatch_follows_content():
    """不显式给 --mode 时，也要按内容派发（I2VA 稿不能被当成 Ref2VA 审）。"""
    import check_h3_all as ALL
    det, _fmt, rows = ALL.check_one(I2)
    assert det == "i2va"
    assert not [r for r in rows if r[0] == "error"], rows


def _dialogue_shot(n_speakers, shot_label="[Shot 1]"):
    """官方写法：`(S1) says … <d> [S1] 台词</d> + 唇锁句`；台词在 <d> 内不算中文残留。"""
    parts = ["(S%d) says clearly, <d> [S%d] Line%d.</d> She closes her lips."
             % (i, i, i) for i in range(1, n_speakers + 1)]
    return (CP.SKELETON_INSTRUCTION + "\n\n"
            "integrated_multimodal_description: %s " % shot_label + " ".join(parts) +
            "\n\noverall_soundscape: Wind.\n\nnon_diegetic_music: N/A")


def test_check_h3_all_house_escalation():
    import check_h3_all as ALL
    two_in_one_shot = _dialogue_shot(2)
    one_in_one_shot = _dialogue_shot(1)
    # 两镜各一人：不报 D5（按 Shot 计人，不是全篇累加）
    _d, _f, rows_ok = ALL.check_one(_dialogue_shot(1) + "\n\n" + "", mode="i2va")
    assert not [r for r in rows_ok if "一镜一声" in r[2]], rows_ok
    _d, _f, default_rows = ALL.check_one(two_in_one_shot, mode="i2va")
    d5 = [r for r in default_rows if "一镜一声" in r[2]]
    assert d5 and d5[0][0] == "warn", default_rows
    _d2, _f2, house_rows = ALL.check_one(two_in_one_shot, mode="i2va", house_rules=("D5",))
    d5on = [r for r in house_rows if "一镜一声" in r[2]]
    assert d5on and d5on[0][0] == "error", house_rows
    # 单说话人稿在 --house 下也不该冒出 D5
    assert not [r for r in ALL.check_one(one_in_one_shot, mode="i2va",
                                         house_rules=("D5",))[2] if "一镜一声" in r[2]]


def test_ref2va_six_section_is_not_flagged_as_skeleton_mix():
    """回归钉：overall_soundscape/non_diegetic_music 同属官方六段，不能被当成骨架混入。"""
    rows = [c for _rid, chks in RG.check_format(R6, channel="h3", expect="ref2va")
            for c in chks if "混进" in c["msg"]]
    assert not rows, rows
    dlg, _ = DL.check_text(R6, mode="ref2va")
    assert not [i for i in dlg if "混进基础骨架字段" in str(i)], dlg


# ------------------------------------------------------------------ V2-2
def _g7_rows(text, kind="h3_i2va"):
    rep = CP.Report()
    CP._g7_skeleton(rep, text, kind=kind)
    return [m for lv, g, m in rep.items if lv == "error" for _ in ([g] if g == "G7" else [])] or \
        [m for lv, g, m in rep.items if lv == "error"]


def test_bad_first_line_hit():
    bad = "For the target video, hello world.\n\n" + BODY
    assert SPEC.detect_skeleton_mode(bad) is None
    assert _g7_rows(bad), "G7 没拦住乱写的官方首行"


def test_duplicate_field_hit():
    dup = CP.SKELETON_INSTRUCTION + "\n\n" + BODY + "\n\n" + BODY.split("\n\n")[0]
    rows = [c for _rid, chks in RG.check_format(dup, channel="h3", expect="i2va")
            for c in chks if c["lvl"] == "error"]
    assert rows, "字段重复必须命中"


def test_field_order_hit():
    swapped = (CP.SKELETON_INSTRUCTION + "\n\n"
               "integrated_multimodal_description: [Shot 1] A stone gate.\n\n"
               "non_diegetic_music: N/A\n\n"
               "overall_soundscape: Wind.")
    a = SPEC.analyze(swapped)
    assert a["order_ok"] is False, a
    assert _g7_rows(swapped), "G7 没拦住字段乱序"


def test_chinese_tenblock_mixed_in_hit():
    mixed = CP.SKELETON_INSTRUCTION + "\n\n" + BODY.replace(
        "A woman stands at a stone gate", "【镜头】女人站在石门前")
    assert _g7_rows(mixed), "十块/中文混入必须命中"
    assert SPEC.detect_format(mixed) == "h3_skeleton"


def test_picture_index_out_of_range_hit(tmp_path):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n")
    text = (CP.SKELETON_INSTRUCTION.replace("<Picture 1>", "<Picture 3>") + "\n\n"
            "<Picture 3> 是 白衣女子\n\n" + BODY)
    rep = CP.run_checks({"prompt": text, "refs": [str(png)], "ref_videos": [],
                         "prompt_kind": "h3_i2va", "w": 736, "h": 416, "length": 124,
                         "provider": "local", "only": ["G3"], "output_root": str(tmp_path),
                         "project": "无音", "project_aliases": {"无音": ["无音"]}})
    assert any(g == "G3" and "越界" in m for _lv, g, m in rep.errors), rep.render()


# ------------------------------------------------------------------ V2-3
def test_chinese_body_rejected_by_core_and_gates():
    zh = CP.SKELETON_INSTRUCTION + "\n\n" + BODY.replace(
        "A woman stands at a stone gate", "一名女子站在石门前")
    assert SPEC.detect_skeleton_mode(zh) == "i2va"      # 判模式与判语言是两件事
    assert _g7_rows(zh), "G7 必须拦中文正文"
    rows = [c for _rid, chks in RG.check_format(zh, channel="h3", expect="i2va")
            for c in chks if c["lvl"] == "error"]
    assert rows, "H3R23 必须拦中文正文"


def test_snapshot_does_not_touch_source(tmp_path):
    src = tmp_path / "p.txt"
    src.write_bytes(I2.encode("utf-8"))
    before = src.read_bytes()
    state_path, compiled, state = PC.snapshot_source(str(src), str(tmp_path / "out"), "R1")
    assert src.read_bytes() == before, "snapshot 不许改原稿一个字节"
    assert state["needs_compile"] is False and compiled, "纯英文稿应生成 identity 编译稿"
    issues, _ = PC.verify_compiled(str(src), str(tmp_path / "out"), "R1", compiled)
    assert not issues, issues


def test_writeback_detected_before_submit(tmp_path):
    src = tmp_path / "p.txt"
    src.write_text(I2, encoding="utf-8")
    _sp, _cp, _st = PC.snapshot_source(str(src), str(tmp_path / "out"), "R2")
    src.write_text(I2 + "\n\n被回写了", encoding="utf-8")
    compiled = tmp_path / "out" / "compiled_R2.txt"
    compiled.write_text(I2, encoding="utf-8")
    issues, _ = PC.verify_compiled(str(src), str(tmp_path / "out"), "R2", str(compiled))
    assert any(code == "original_changed" for code, _m in issues), issues


# ------------------------------------------------------------------ V2-4
GIANT = (CP.SKELETON_INSTRUCTION + "\n\n"
         "integrated_multimodal_description: [Shot 1] A wooden boat drifts under a cliff.\n\n"
         "overall_soundscape: Water lapping the hull.\n\n"
         "non_diegetic_music: N/A")


def test_no_dialogue_does_not_force_d7_d8():
    issues, _ = DL.check_text(GIANT, mode="i2va")
    codes = [str(i) for i in issues]
    assert not [c for c in codes if c.startswith(("D7", "D8"))], codes


def test_d5_counts_speakers_per_shot():
    two_shots = (_dialogue_shot(1) + "\n\n[Shot 2] " +
                 "(S2) says clearly, <d> [S2] Wait.</d> She closes her lips.")
    one_shot = _dialogue_shot(2)
    i1, _ = DL.check_text(two_shots, mode="i2va")
    assert not [str(i) for i in i1 if str(i).startswith("D5")], i1
    i2, _ = DL.check_text(one_shot, mode="i2va")
    d5 = [str(i) for i in i2 if str(i).startswith("D5")]
    assert d5, "同一镜两个说话人必须报 D5"


def test_house_rules_default_warn_and_error_when_on():
    one_shot = _dialogue_shot(2)
    issues, _ = DL.check_text(one_shot, mode="i2va")
    d5 = [i for i in issues if str(i).startswith("D5")]
    assert d5 and DL._sev(d5[0]) == "warn", [DL._sev(i) for i in d5]
    on, _ = DL.check_text(one_shot, mode="i2va", house_rules=("D5",))
    d5on = [i for i in on if str(i).startswith("D5")]
    assert d5on and DL._sev(d5on[0]) == "error"


# ------------------------------------------------------------------ V2-5
def _cli(*args):
    return subprocess.run([sys.executable, "-B", str(TOOLS / "prompt_compile.py"), *args],
                          capture_output=True, text=True, encoding="utf8",
                          errors="replace", timeout=120)


def test_compile_cli_rejects_truncation(tmp_path):
    src = tmp_path / "p.txt"
    src.write_text(I2, encoding="utf-8")
    out = tmp_path / "out"
    r = _cli("snapshot", "--source", str(src), "--out-dir", str(out), "--run-id", "R3")
    assert r.returncode == 0, r.stdout + r.stderr
    bad = out / "compiled_R3.txt"
    bad.write_text(I2[: len(I2) // 2], encoding="utf-8")
    v = _cli("verify", "--source", str(src), "--state-dir", str(out),
             "--run-id", "R3", "--compiled", str(bad), "--mode", "i2va")
    assert v.returncode != 0, "截断的编译稿必须非零退出（提交前停住）"
    assert "截断" in (v.stdout + v.stderr) or "missing" in (v.stdout + v.stderr).lower()


def test_compile_cli_rejects_untranslated_chinese(tmp_path):
    src = tmp_path / "p.txt"
    src.write_text(CP.SKELETON_INSTRUCTION + "\n\n" + BODY.replace(
        "A woman stands at a stone gate", "一名女子站在石门前"), encoding="utf-8")
    out = tmp_path / "out"
    r = _cli("snapshot", "--source", str(src), "--out-dir", str(out), "--run-id", "R4")
    assert r.returncode == 0
    assert json.loads((out / "source_R4.json").read_text(encoding="utf-8"))["needs_compile"]
    compiled = out / "compiled_R4.txt"
    compiled.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")   # 没翻译
    v = _cli("verify", "--source", str(src), "--state-dir", str(out),
             "--run-id", "R4", "--compiled", str(compiled), "--mode", "i2va")
    assert v.returncode != 0, "带中文的编译稿必须非零退出"
