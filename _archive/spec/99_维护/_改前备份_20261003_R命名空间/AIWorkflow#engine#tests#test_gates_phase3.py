# -*- coding: utf-8 -*-
"""阶段三回归：关口是否真的接进了各条工作流、参考视频注入、两种提示词口径。

这组测试的意义：闸写在文件里但 YAML 没接 = 等于没有（9-14 那 10 个裁判件就是这么废的）。
所以这里逐条检查工作流里真有 gate 步骤、参数能渲染、顺序正确。
"""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent          # engine/
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT.parent / "tools"))

from tasks import REGISTRY, build_graph_video           # noqa: E402
from check_preflight import run_checks                   # noqa: E402

WF = ROOT / "workflows"
PLACE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def load(name):
    return yaml.safe_load((WF / f"{name}.yaml").read_text(encoding="utf-8"))


def test_every_gate_step_param_resolves():
    """gate/video 步骤里的 {{args.X}} 必须在 args 里声明过 ——
       strict 渲染遇到空值会当场报错，宁可在这里先发现。"""
    # 这几个 key 由引擎在"编号选图"运行时注入（run.py resolve_pick），不写在 YAML args 里
    injected = {"picked_files", "picked_seeds", "picked_names", "picked_prompt",
                "manifest", "pick"}
    bad = []
    for f in sorted(WF.glob("*.yaml")):
        w = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        declared = set((w.get("args") or {}).keys())
        for st in (w.get("steps") or []):
            for k, v in st.items():
                if k in ("task", "id", "label", "hint", "when", "retry",
                         "continue_on_error", "auto_gates", "numbering"):
                    continue
                for m in PLACE.finditer(str(v)):
                    path = m.group(1)
                    if path.startswith("args.") and path.split(".")[1] not in declared                             and path.split(".")[1] not in injected:
                        bad.append(f"{f.name}:{st.get('id')}.{k} → {path}")
    assert not bad, f"未声明就引用的参数：{bad}"


def test_all_step_tasks_registered():
    for f in sorted(WF.glob("*.yaml")):
        w = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for st in (w.get("steps") or []):
            assert st.get("task") in REGISTRY, f"{f.name} 用了未注册的任务类型 {st.get('task')}"


def test_h3_flow_has_ordered_gates():
    w = load("h3_ref2va_video")
    ids = [s.get("id") for s in w["steps"]]
    assert ids == ["pre", "H3", "polish", "gen", "H4"], f"关口顺序变了：{ids}"
    by = {s["id"]: s for s in w["steps"]}
    assert by["pre"]["mode"] == "auto"
    assert "G11" in by["pre"]["auto_gates"] and "G2" in by["pre"]["auto_gates"]
    assert by["H3"]["mode"] == "human" and by["H3"]["show_prompt"] is True
    assert by["gen"]["task"] == "video"
    assert by["gen"]["prompt_file"] == "{{args.prompt_file}}", "提示词必须能从文件进引擎"
    assert by["gen"]["ref_videos"] == "{{args.ref_videos}}", "参考视频通道必须在"
    assert by["H4"]["mode"] == "human" and by["H4"]["videos"] == "{{gen.files}}"
    # 旧的内联占位提示词不该再留在工作流里（真源＝prompts/*.txt）
    assert w["args"]["prompt"] in ("", None), "args.prompt 应为空，正文只留一份真源"


def test_image_flows_carry_auto_gate_with_image_kind():
    for name in ("image_draft_batch", "auto_draft", "previz_control", "character_sheet"):
        w = load(name)
        gates = [s for s in w["steps"] if s.get("task") == "gate"]
        assert gates, f"{name} 没有关口步骤"
        g = gates[0]
        assert g["mode"] == "auto", f"{name} 首个关口应是机制自审"
        assert g.get("prompt_kind") == "image", f"{name} 该用图片口径，不然会假报缺十块"
        assert str(g.get("characters")) == "none", f"{name} 是纯文生图探索流，锁脸由 i2i 链把守"
        assert w["steps"].index(g) == 0, f"{name} 的自审应在最前面"


def test_video_graph_injection_matches_run_h3_convention():
    """引擎注入的参考视频接线必须和 ComfyUI_H3/run_h3.py 一致，
       否则'统一走引擎'会悄悄改变生成条件。"""
    tpl = json.loads((ROOT / "comfy" / "h3_i2v_ref2va_api.json").read_text(encoding="utf-8"))
    p = {"prompt": "x", "width": 864, "height": 1536, "length": 124, "steps": 8,
         "lora": "l.safetensors", "lora_strength": 1.0, "prefix": "t"}
    rep = {f"__REF{i}__": f"r{i}.png" for i in range(1, 5)}
    g = build_graph_video(tpl, p, 42, extra_rep=rep, ref_videos=["v1.mp4", "v2.mp4"])
    host = [n for n, v in g.items() if v.get("class_type") == "MiniMaxH3ReferenceToVideo"][0]
    ins = g[host]["inputs"]
    assert ins["ref_videos.ref_video_0"] and ins["ref_videos.ref_video_1"]
    for k, key in ((0, "ref_videos.ref_video_0"), (1, "ref_videos.ref_video_1")):
        comp = ins[key][0]
        assert g[comp]["class_type"] == "GetVideoComponents", "必须走帧序列而不是原视频"
        vid = g[comp]["inputs"]["video"][0]
        assert g[vid]["class_type"] == "LoadVideo"
        assert g[vid]["inputs"]["file"] == f"v{k+1}.mp4"
        assert g[comp]["inputs"]["video"][1] == 0, "只取 images 输出（不接参考片原声）"
    assert len(g) == 18 + 4


def test_video_graph_without_ref_videos_untouched():
    tpl = json.loads((ROOT / "comfy" / "h3_i2v_ref2va_api.json").read_text(encoding="utf-8"))
    p = {"prompt": "x", "width": 864, "height": 1536, "length": 124, "steps": 8,
         "lora": "l.safetensors", "lora_strength": 1.0, "prefix": "t"}
    rep = {f"__REF{i}__": f"r{i}.png" for i in range(1, 5)}
    g = build_graph_video(tpl, p, 42, extra_rep=rep)
    assert len(g) == 18
    host = [n for n, v in g.items() if v.get("class_type") == "MiniMaxH3ReferenceToVideo"][0]
    assert not any(str(k).startswith("ref_videos.") for k in g[host]["inputs"])


def _g7_errors(spec):
    """只取 G7 的 error 文本（这组测试只关心格式判据，别被 G1/G5 干扰）。"""
    spec = dict(spec)
    spec.setdefault("only", ["G7"])
    spec.setdefault("refs", ["a.png"])
    spec.setdefault("characters", "none")
    rep = run_checks(spec)
    return [t for lv, g, t in rep.items if g == "G7" and lv == "error"]


SKEL = ("For the target video, at 0.00 seconds into the target video, "
        "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        "integrated_multimodal_description: [Shot 1] Bright frigates cross the void. "
        "The camera Push In slowly.\n\n"
        "overall_soundscape: Low rumble continues throughout the scene.\n\n"
        "non_diegetic_music: N/A")
# 中文十块：2026-09-28 起**只属云端 SD 通道**（H3 侧的十块写法已实测 4/5 条把
# 元叙述当台词念出乱码，见 wzy/ab_tenblock.py），所以同一份稿子在两个通道判据不同。
TEN = ("【生成目标】一条 5 秒镜【参考素材职责】@图片1 是甲，只采用其身份。"
       "【未采用素材】无【主体与关系】<Picture 1> 是甲，站在废土上。"
       "【场景与环境】龟裂盐碱地，低空浮尘。【事件脚本】0.0-2.5 秒：甲向前走了三步，停下。"
       "【保持一致】服装与发型不变。【镜头】中景，中幅度缓缓前推，收尾停在脸上。"
       "【声音】风声与脚步声，无背景音乐。【风格与光影】冷灰主调，硬侧光，写实3D CG。")
SIX = """subject_definitions:
<Subject 1> is the coffee-shop environment in <Picture 1>, with an exposed brick wall.

summary:
[reference generation] The target video shows <Subject 1> with a seated woman.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - the exposed brick wall is retained.

detailed_description:
[Shot 1] A medium shot establishes <Subject 1>, the coffee shop with its exposed brick wall.

overall_soundscape:
Soft indoor coffee-shop room tone continues throughout the scene.

non_diegetic_music:
N/A
"""
IMG = "21岁女子，清冷骨相，宽袖襦裙，写实3D CG渲染，竖幅构图，单人立像"


def test_g7_gear_in_ban_sentence_is_graded_by_channel():
    """器材名词的句位分级（09-28 裁定，见通用层 G2-05/G2-06 与手册 C61）：
       · 图片/云端通道：否定式实测有效 ⇒ 只在禁令句里出现 = warn（四批定妆实测没长出器材）；
         但只要改写进正面描述，立刻回到 error。
       · H3 视频通道：禁令即在点名（实测两轮）⇒ **不分级，一律 error**，只是报文里注明它在哪一句。"""
    ban = {"prompt": "纯色背景，画面里不出现任何灯具、灯架、柔光箱、三脚架。",
           "prompt_kind": "image", "provider": "local"}
    rep = run_checks(dict(ban, only=["G7"], refs=["a.png"], characters="none"))
    g7err = [t for lv, g, t in rep.items if g == "G7" and lv == "error"]
    g7warn = [t for lv, g, t in rep.items if g == "G7" and lv == "warn"]
    assert not any("三脚架" in t for t in g7err), g7err
    assert any("三脚架" in t and "降 warn" in t for t in g7warn), g7warn
    # 同一个词挪进正面描述 ⇒ 必须回到 error
    pos = {"prompt": "纯色背景，镜头用三脚架固定拍摄，人物居中。",
           "prompt_kind": "image", "provider": "local"}
    errs = _g7_errors(pos)
    assert any("三脚架" in t and "器材" in t for t in errs), errs
    # H3 通道：即使只写在禁令句里也拦
    h3 = SKEL.replace("The camera Push In slowly.",
                      "Do not show any 三脚架 in frame.")
    errs = _g7_errors({"prompt": h3, "prompt_kind": "h3_i2va", "provider": "local"})
    assert any("三脚架" in t and "器材" in t for t in errs), errs
    assert any("禁令即在点名" in t for t in errs), errs


def test_g7_ban_word_list_is_single_sourced():
    """否定词表只有一份（09-28 实测漂移）：`check_preflight.BAN_LEADS` 曾是手抄镜像，
       与 `prompt_lint.NEG` 差一个「切忌」⇒ 同一句"切忌三脚架入画"在 G7 算禁令句（低危）、
       在词表闸算正面点名（高危）。两张手写词表必然漂，所以现在 G7 直接 import 词表闸那张。
       底座取不到时走等值镜像并 warn——**镜像必须与真源等值**，否则这条测试先响。"""
    from check_preflight import BAN_LEADS, BAN_ERR, _BAN_MIRROR
    if BAN_ERR:                       # 底座不在场：兜底路径本身要出声，不能静默按镜像放行
        rep = run_checks({"prompt": "纯色背景，三脚架入画。", "only": ["G7"],
                          "prompt_kind": "image", "refs": ["a.png"],
                          "characters": "none", "provider": "local"})
        assert any("prompt_lint.NEG 未加载" in t for lv, g, t in rep.items if g == "G7"), rep.items
    else:
        import prompt_lint
        assert set(BAN_LEADS) == {w for w in prompt_lint.NEG if len(w) >= 2}, \
            "G7 的否定词表已与词表闸漂移——这就是「切忌」那次的复发"
    assert set(BAN_LEADS) == set(_BAN_MIRROR), "等值镜像没跟上真源，兜底判定会漂"


def test_g7_three_video_prompt_formats_each_get_their_own_gate():
    """四套格式各走各的判据：H3 骨架 / H3 六段 / 云端十块 / 图片无格式，互不冒充。"""
    assert not _g7_errors({"prompt": SKEL, "prompt_kind": "h3_i2va", "provider": "local"})
    assert not _g7_errors({"prompt": SIX, "prompt_kind": "h3_ref2va", "provider": "local"})
    assert not _g7_errors({"prompt": TEN, "prompt_kind": "video", "provider": "ark"})
    assert not _g7_errors({"prompt": IMG, "prompt_kind": "image", "provider": "local"})


def test_g7_mixing_is_an_error_not_a_silent_pass():
    """混用＝提示词故意分格式后要防的那件事，必须报出来（且要说清去哪条通道）。"""
    errs = _g7_errors({"prompt": TEN, "prompt_kind": "video", "provider": "local"})
    assert any("混用" in t and "十块" in t for t in errs), errs
    errs = _g7_errors({"prompt": SIX, "prompt_kind": "video", "provider": "ark"})
    assert any("混用" in t for t in errs), errs
    # 骨架里混进六段字段（fl2va 与 ref2va 互斥）
    errs = _g7_errors({"prompt": SKEL + "\nretention_analysis:\nx",
                       "prompt_kind": "h3_i2va", "provider": "local"})
    assert any("六段" in t for t in errs), errs
    # 十块里混进骨架字段（云端稿带上了本地格式）
    errs = _g7_errors({"prompt": TEN + "\nnon_diegetic_music: N/A",
                       "prompt_kind": "video", "provider": "ark"})
    assert any("混用" in t for t in errs), errs


def test_g7_c57_ref2va_yaml_without_prompt_kind_is_not_blocked():
    """C57：h3_ref2va_video.yaml 不写 prompt_kind ⇒ 旧代码 `or "video"` 把六段送进骨架判据，
    一开闸 ref2va 通道会被"缺官方首帧指令"假报拦死。现在判据按内容识别的格式派发，泛称
    `video` 只定通道不定格式，所以同一份六段稿无论声不声明 kind 都该放行。"""
    for kind in ("video", "h3_ref2va"):
        errs = _g7_errors({"prompt": SIX, "prompt_kind": kind, "provider": "local"})
        assert not any("首帧" in t or "指令" in t for t in errs), (kind, errs)


def test_g7_image_flow_without_prompt_kind_fails_loud():
    """图片流忘写 prompt_kind: image 时，不能静默套用视频判据放行，也不能假报缺块——
    要报"认不出格式 + 若这是图片稿请声明 prompt_kind: image"。"""
    errs = _g7_errors({"prompt": IMG, "prompt_kind": "video", "provider": "local"})
    assert any("认不出格式" in t and "image" in t for t in errs), errs


@pytest.mark.parametrize("kind", ["image", "cloud", "h3"])
@pytest.mark.parametrize("text, expected", [
    ("Boxy frigates pass a bright orange explosion on the right.", None),
    ("BRIGHT FRIGATES cross a dark starfield.", None),
    ("A camera rig follows the ship.", "rig"),
    ("A camera RIG follows the ship.", "rig"),
    ("A rig-mounted camera follows the ship.", "rig"),
    ("用gimbal环绕拍摄", "gimbal"),
    ("用稳定器环绕拍摄", "稳定器"),
    ("A dolly follows the ship.", "dolly"),
])
def test_g7_camera_gear_uses_english_word_boundaries(kind, text, expected):
    """器材名词是跨格式共性坑：三种通道都得拦，且英文按整词匹配（frigates/bright 不算）。"""
    prompt = {"image": text,
              "cloud": TEN.replace("甲向前走了三步，停下。", "甲向前走了三步。" + text),
              "h3": SKEL.replace("The camera Push In slowly.", "The camera " + text)}[kind]
    assert text in prompt, "fixture 替换没命中，测不到东西"
    provider = "ark" if kind == "cloud" else "local"
    errors = _g7_errors({"prompt": prompt, "prompt_kind": kind if kind == "image" else "video",
                         "provider": provider})
    if expected is None:
        assert not errors, errors
    else:
        assert any(expected in message and "器材" in message for message in errors), errors


@pytest.mark.parametrize("fault", [None, "video", "gear", "size", "project"])
def test_image_gate_executes_kind_without_disabling_checks(tmp_path, fault):
    """执行真实 gate→preflight→run_checks 链，而不只检查 YAML 声明。"""
    p = dict(load("image_draft_batch")["steps"][0])
    p.update(prompt="Gunmetal spacecraft crossing a dark starfield.",
             width=1344, height=768)
    # 本条测的是 **kind 派发链**（image 种类不该关掉其它检查），不是决定单链。
    # 摘掉 G13 的理由是事实而不是方便：fixture 用的项目「太空战」按 10-02 口径
    # 还在 projects_registry.projects_not_declared 里（没登记 ⇒ 拼不出决定单 ⇒ G13 必拦），
    # 而"登记它/给它填值"都是人的活，测试不许替它填。
    # G13 那条链在 tests/test_run_decisions.py 里真跑（含真走 gate 步的正反两向）。
    p["auto_gates"] = [g for g in (p.get("auto_gates") or []) if g != "G13"]
    ctx = {"cfg": {"preflight": "on", "project": "太空战",
                   "characters_needing_anchor": ["沈无音"]},
           "args": {"theme": "太空战 首帧测试"},
           "workflow": "image_draft_batch", "log": lambda msg: None,
           "batch_dir": tmp_path / "太空战" / "batch"}
    if fault == "video":
        p.pop("prompt_kind")
    elif fault == "gear":
        p["prompt"] += " 用稳定器环绕拍摄"
    elif fault == "size":
        p["width"] = 1345
    elif fault == "project":
        ctx["cfg"]["project"] = "另一个项目"
    if fault is None:
        assert REGISTRY["gate"](p, ctx)["auto"] is True
    else:
        gate = {"video": "G7", "gear": "G7", "size": "G5", "project": "G11"}[fault]
        with pytest.raises(RuntimeError, match=gate):
            REGISTRY["gate"](p, ctx)


def test_g7b_character_without_anchor():
    prompt = "沈无音在石凳上读书"
    assert any("没挂任何参考图" in t for _, g, t in run_checks(
        {"prompt": prompt, "only": ["G7"], "refs": [], "characters": ["沈无音"]}).errors)
    assert not any("没挂任何参考图" in t for _, g, t in run_checks(
        {"prompt": prompt, "only": ["G7"], "refs": ["anchor.png"],
         "characters": ["沈无音"]}).errors)
    assert not any("没挂任何参考图" in t for _, g, t in run_checks(
        {"prompt": prompt, "only": ["G7"], "refs": [], "characters": "none"}).errors)


def test_g4_video_tags_must_match_attached_videos(tmp_path):
    """提示词写 <Video 1> 却没挂参考视频＝素材当空；挂了没引用＝白烧约 8 分钟。"""
    assert any("<Video" in t and "没挂" in t for _, g, t in run_checks(
        {"prompt": "<Video 1> 复刻这段动作", "only": ["G4"], "refs": [],
         "ref_videos": [], "workflow_json": str(ROOT / "comfy" / "h3_i2v_ref2va_api.json")}).errors)
    assert any("没有 <Video N> 引用" in t for _, g, t in run_checks(
        {"prompt": "纯文字描述", "only": ["G4"], "refs": [],
         "ref_videos": ["不存在的片.mp4"],
         "workflow_json": str(ROOT / "comfy" / "h3_i2v_ref2va_api.json")}).warns)


def test_config_declares_anchor_characters_and_selftest_root():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert "沈无音" in cfg.get("characters_needing_anchor", [])
    assert cfg.get("selftest_output_root"), "自测流必须有独立落点，不污染交付根"
    assert "selftest" not in str(cfg.get("output_root", ""))


@pytest.mark.parametrize("fault", [None, "instruction", "field", "slot", "gear", "ref_format"])
def test_h3_i2va_native_prompt_gate(fault):
    prompt = ("For the target video, at 0.00 seconds into the target video, "
              "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
              "integrated_multimodal_description: [Shot 1] Bright frigates cross the void.\n\n"
              "overall_soundscape: Low rumble.\n\nnon_diegetic_music: N/A")
    if fault == "instruction":
        prompt = prompt.split("\n\n", 1)[1]
    elif fault == "field":
        prompt = prompt.replace("overall_soundscape:", "wrong_field:")
    elif fault == "slot":
        prompt += " <Picture 2>"
    elif fault == "gear":
        prompt += " camera RIG"
    elif fault == "ref_format":
        prompt += " retention_analysis:"
    errors = run_checks({"prompt": prompt, "prompt_kind": "h3_i2va",
                         "only": ["G7"], "characters": "none"}).errors
    assert bool(errors) == (fault is not None)


def test_h3_i2va_graph_matches_existing_t8_builder():
    import importlib.util
    spec = importlib.util.spec_from_file_location("h3_builder", ROOT.parent / "ComfyUI_H3" / "run_h3.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    p = {"prompt": "native prompt", "width": 1344, "height": 768, "length": 192,
         "steps": 8, "lora": module.DEFAULT_LORA, "lora_strength": 1.0, "prefix": "h3_i2v"}
    tpl = json.loads((ROOT / "comfy" / "h3_i2v_fl2va_api.json").read_text(encoding="utf-8"))
    actual = build_graph_video(tpl, p, 42, extra_rep={"__REF1__": "B.png"})
    expected = module.build_workflow_t8("native prompt", 1344, 768, 192, 8, 42,
                                       "B.png", lora_name=module.DEFAULT_LORA)
    assert actual == expected
    w = load("h3_i2va_video")
    assert [s["id"] for s in w["steps"]] == ["pre", "H3", "gen", "H4"]
    assert w["steps"][0]["prompt_kind"] == "h3_i2va"
    assert w["steps"][2]["prompt_kind"] == "h3_i2va"


@pytest.mark.parametrize("field", ["images", "videos", "gifs"])
def test_video_poll_receives_only_own_prefix(tmp_path, monkeypatch, field):
    import tasks
    class Response:
        status_code = 200
        def json(self):
            return {"pid": {"status": {"completed": True}, "outputs": {"12": {
                field: [{"filename": "other_00001.mp4"},
                        {"filename": "mine_00001.mp4", "subfolder": "video"}]}}}}
    monkeypatch.setattr(tasks.SESSION, "get", lambda *a, **kw: Response())
    monkeypatch.setattr(tasks.time, "sleep", lambda _: None)
    ctx = {"cfg": {"comfyui": {"output_dir": str(tmp_path)}}}
    assert tasks.poll_history(ctx, "unused", "pid", 1, expected_prefix="mine_") == [
        str(tmp_path / "video" / "mine_00001.mp4")]
    with pytest.raises(RuntimeError, match="禁止"):
        tasks.poll_history(ctx, "unused", "pid", 0, pre_snapshot=set(), expected_prefix="mine_")

