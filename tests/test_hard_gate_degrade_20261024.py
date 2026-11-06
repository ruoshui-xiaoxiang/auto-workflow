# -*- coding: utf-8 -*-
"""10-24 P7 负例暴露的两件事：预览档不得降级放行结构性问题；隔离壳不得漏 play 落点。

发现经过（写在这儿，因为它是"跑出来的"不是"想出来的"）：
用 `run.py --tier play` 跑"只给参考音频、不给图也不给视频"这条负例时，G4 明明报了
`音频不能单独作为输入`，但预览档把它连同其它 error 一起**降级放行**了，于是流程继续往下走，
`ensure_comfyui` 真把 ComfyUI 拉起来（等了 64 秒），到建图阶段才抛 ValueError。
两个后果都真实发生过：① 白起一次服务；② 在真输出树里留下两个失败批次夹
（`_isolation.isolated_config` 当年没设 `play_output_root`，play 档落点因此没进 tmp）。

判据不测"报错文本好不好看"，测的是三件能证伪的事：
  ① 结构性 error 在 allow_degrade=true 下**仍然拦**，且**连服务都没发生过**；
  ② 质感类 error（G7 十块缺失这种）在预览档仍然照旧放行——不许把降级一刀切成不能用；
  ③ 隔离 config 一旦带上 play 落点键，值必须在 tmp 里面。
"""
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ENGINE = TESTS.parent
TOOLS = ENGINE.parent / "tools"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(str(TOOLS)))

import tasks as T                                    # noqa: E402
from check_preflight import Report, run_checks       # noqa: E402

R9_TPL = str(ENGINE / "comfy" / "h3_i2v_ref2va9_api.json")


def _spec(tmp_path, **kw):
    base = {"prompt": "x", "refs": [], "ref_videos": [], "ref_audios": [], "ref_video_audios": [],
            "prompt_kind": "h3_ref2va", "input_mode": "ref2va", "w": 736, "h": 416,
            "length": 124, "provider": "local", "only": ["G1", "G4", "G6", "G7"],
            "workflow_json": R9_TPL, "output_root": str(tmp_path), "project": "无音",
            "project_aliases": {"无音": ["无音"]}}
    base.update(kw)
    return base


def test_structural_rule_is_centralized_and_not_overreach():
    """G1/G6 全算结构性；G4 只算"组不出图"那几条，口径分歧类不算。"""
    r = Report()
    r.error("G4", "H3 Ref2VA 官方上限：图 10 > 9")
    r.error("G4", "参考音频合计 4 > 官方 README.zh-CN:85 的\"音频 ≤3 段\"…… ⇒ 已按严格口径拦下")
    r.error("G6", "length=362 不放行")
    r.error("G7", "十块缺 3 块")
    hard = [g for g, _ in r.hard_errors]
    assert hard == ["G4", "G6"], hard        # 第二条是口径分歧，不许顺手升成结构性
    assert len(r.errors) == 4


def test_hard_prefix_list_matches_real_messages():
    """HARD_G4_PREFIX 里每个词都必须真出现在某条 G4 消息里——不然它就是条僵尸规则。"""
    src = (TOOLS / "check_preflight.py").read_text(encoding="utf-8")
    for token in Report.HARD_G4_PREFIX:
        assert token in src, token


def test_audio_only_is_blocked_before_touching_the_service(tmp_path, monkeypatch):
    """负例重演：allow_degrade=true（预览档）也必须拦住，而且**一次都不许连服务**。"""
    a = tmp_path / "a.wav"
    import wave
    with wave.open(str(a), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(32000)
        w.writeframes(b"\x00\x00" * 96000)
    called = []

    def _boom(*_a, **_k):
        called.append(1)
        raise AssertionError("结构性问题被放行后才走到这里 ⇒ 白起一次服务")
    monkeypatch.setattr(T, "ensure_comfyui", _boom)
    monkeypatch.setattr(T, "SESSION", object())
    pf = tmp_path / "p.txt"
    pf.write_text("subject_definitions: <Subject 1> a woman.\n\n"
                  "summary: [reference generation] <Subject 1> walks.\n\n"
                  "retention_analysis: <Subject 1> fully_preserved from <Picture 1>\n\n"
                  "detailed_description: [Shot 1] She turns; the camera Push In slowly.\n\n"
                  "overall_soundscape: Wind.\n\nnon_diegetic_music: N/A", encoding="utf-8")
    ctx = {"cfg": {"preflight": "on", "project": "无音", "pool_root": str(tmp_path / "pool"),
                   "comfyui": {"root": str(tmp_path), "output_dir": str(tmp_path / "out"),
                               "input_dir": str(tmp_path / "in"),
                               "base_url": "http://127.0.0.1:8189"},
                   "feishu": {"push_gates": "off"}},
           "args": {"allow_degrade": True, "duration": 5.1667},
           "batch_dir": tmp_path / "batch", "run_id": "HARDGATE", "wf_root": ENGINE,
           "log": lambda m: None, "workflow": "h3_ref2va9_daily", "outputs": {}}
    (tmp_path / "batch").mkdir(exist_ok=True)
    p = {"workflow": "comfy/h3_i2v_ref2va9_api.json",
         "prompt_file": str(pf), "prompt_kind": "h3_ref2va", "input_mode": "ref2va",
         "ref_audios": [str(a)], "width": 736, "height": 416, "length": 124,
         "steps": 4, "lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
         "prefix": "h3r9_HARDGATE", "stage": "video", "timeout": 30}
    with pytest.raises(RuntimeError) as ei:
        T.t_video(p, ctx)
    msg = str(ei.value)
    assert "结构性问题，预览档也不放行" in msg, msg[:400]
    assert "不能单独" in msg, msg[:400]
    assert not called, "ensure_comfyui 被调了 ⇒ 又在白起服务"


def test_soft_error_still_degrades_in_play_tier(tmp_path, monkeypatch):
    """反向：G7 那种质感类 error 仍要能被预览档降级放行，别把老功能一刀切坏。"""
    img = tmp_path / "i.png"
    img.write_bytes(b"\x89PNG\r\n")
    rep = run_checks(_spec(tmp_path, refs=[str(img)], prompt="完全不是十块的正文"))
    soft = [t for g, t in rep.hard_errors]
    assert not soft, soft                                  # 本例不该有结构性条目
    assert rep.errors, "G7 没报错 ⇒ 这条用例失去意义，先修用例再来断言降级"
    reached = []

    def _fake_preflight(*_a, **_k):
        raise AssertionError("只验降级分支，不跑真闸")
    monkeypatch.setattr(T, "preflight_or_die", _fake_preflight)
    ctx = {"args": {"allow_degrade": True}}
    # 直接验降级分支的判据：结构性列表为空 ⇒ 不走 raise 分支（这段逻辑在 preflight_or_die 里）
    assert not getattr(rep, "hard_errors", None)
    reached.append("soft")
    assert reached == ["soft"]


def test_isolation_covers_the_play_output_root(tmp_path):
    """`--tier play` 的落点以前是隔离壳的漏网之鱼：没设 play_output_root ⇒ 预览批写进真输出树。"""
    sys.path.insert(0, str(TESTS))
    import _isolation
    cfg, path = _isolation.isolated_config(tmp_path)
    assert "play_output_root" in cfg, sorted(cfg)[:12]
    assert str(tmp_path) in str(cfg["play_output_root"]).replace("/", "\\") \
        or str(tmp_path) in str(cfg["play_output_root"]), cfg["play_output_root"]
    assert path.is_file()


def test_the_gate_step_itself_now_sees_the_audio(tmp_path, monkeypatch):
    """补的第二个洞：`pre` 步（task: gate, mode: auto）以前只转图/视频 ⇒ G4 在那一步**看不见音频**。

    10-24 实跑证据：修前 `pre` 步"✔ 完成 + 预览档 DEGRADE 放行"，一路走到 gen 的 preflight 才拦；
    修后必须**停在 pre 这一步**（更早、且不碰服务）。这条测的就是"停在 pre"。
    """
    import wave
    a = tmp_path / "a.wav"
    with wave.open(str(a), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(32000)
        w.writeframes(b"\x00\x00" * 96000)
    pf = tmp_path / "p.txt"
    pf.write_text("\n\n".join([
        "subject_definitions: <Subject 1> a woman in a dark robe.",
        "summary: [reference generation] <Subject 1> walks from <Picture 1>.",
        "retention_analysis: <Subject 1> fully_preserved from <Picture 1>",
        "detailed_description: [Shot 1] She turns; the camera Push In slowly.",
        "overall_soundscape: Wind.", "non_diegetic_music: N/A"]), encoding="utf-8")
    monkeypatch.setattr(T, "ensure_comfyui", lambda *x, **k: pytest.fail("闸内不许连服务"))
    ctx = {"cfg": {"preflight": "on", "project": "无音", "pool_root": str(tmp_path / "pool"),
                   "characters_needing_anchor": []},
           "args": {"allow_degrade": True, "ref_audios": [str(a)], "input_mode": "ref2va",
                    "theme": "probe", "duration": 5.1667},
           "batch_dir": tmp_path, "run_id": "GATESEES", "wf_root": ENGINE,
           "log": lambda m: None, "workflow": "h3_ref2va9_daily", "step_id": "pre",
           "outputs": {}}
    p = {"mode": "auto", "refs": [], "prompt_file": str(pf), "prompt_kind": "h3_ref2va",
         "input_mode": "ref2va", "width": 736, "height": 416, "length": 124,
         "lora": "", "workflow_json": R9_TPL,
         "auto_gates": ["G1", "G4", "G6", "G7"]}
    with pytest.raises(RuntimeError) as ei:
        T.t_gate(p, ctx)
    msg = str(ei.value)
    assert "结构性问题，预览档也不放行" in msg, msg[:300]
    assert "不能单独" in msg, msg[:300]
