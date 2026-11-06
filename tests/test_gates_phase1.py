# -*- coding: utf-8 -*-
"""阶段一关口（G1–G8 / G10 / G11）的回归测试。

这些用例的来源全是真实事故或真实历史参数：
  · 9-18 四条 H3 全废＝参考图槽位配错（同图占多槽 + 声明角色与实挂不符）
  · manifest 里 seed/width/height/steps 全为 null，且不记槽位 → 事后无法复现
  · output_root 写死在别的项目下 → 仙戮产物串进无音批次夹
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent      # engine/
TOOLS = ROOT.parent / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

import check_preflight as cp                        # noqa: E402
from check_preflight import run_checks              # noqa: E402
from run import write_manifest                      # noqa: E402
from tasks import preflight_or_die                  # noqa: E402


def _png(tmp, name, color):
    """写一张纯色小图当锚点（内容不同 → md5 不同）。
       注意：本机 tmp 路径含中文，cv2.imwrite 会静默失败，必须 imencode + write_bytes。"""
    import numpy as np
    import cv2
    p = tmp / name
    ok, buf = cv2.imencode(".png", np.full((64, 48, 3), color, dtype=np.uint8))
    assert ok
    p.write_bytes(buf.tobytes())
    return str(p)


def _ref2va_prompt(n=4):
    """官方全参考六段的最小合法样本（ref-en.txt §7 的骨架，字段顺序逐字对齐）。

    为什么默认提示词从中文十块换成六段：2026-09-28 起十块**移出 H3**、只属云端 SD 通道，
    本地 H3 稿写十块＝混用（G7 直接 error）。这条 `_spec` 挂的是 h3_i2v_ref2va 模板，
    所以"好例子"必须是六段格式，否则 test_good_spec_passes 会替旧格式背书。
    """
    subs = "\n".join("<Subject %d> is the person in <Picture %d>, with long black hair."
                     % (i, i) for i in range(1, n + 1))
    keep = "\n".join("<Subject %d> (appears in [Shot 1]): fully_preserved - the identity and "
                     "hairstyle are retained." % i for i in range(1, n + 1))
    return ("subject_definitions:\n%s\n\nsummary:\n[reference generation] The target video "
            "shows <Subject 1> walking forward in the yard.\n\nretention_analysis:\n%s\n\n"
            "detailed_description:\n[Shot 1] At 00:00.000, <Subject 1> walks forward and the "
            "others stay behind.\n\noverall_soundscape:\nWind tone and footsteps continue "
            "throughout the scene.\n\nnon_diegetic_music:\nN/A\n" % (subs, keep))


def _spec(tmp, refs=None, prompt=None, **kw):
    if refs is None:
        refs = [_png(tmp, f"a{i}.png", i * 40) for i in range(4)]
    base = {"refs": refs, "prompt": prompt or _ref2va_prompt(),
            "prompt_kind": "h3_ref2va",
            "w": 864, "h": 1536, "length": 124, "provider": "local",
            "workflow_json": str(ROOT / "comfy" / "h3_i2v_ref2va_api.json"),
            # 10-02：G11 进了 run_checks 的默认子集 ⇒ "好例子"必须自带合法落点，
            # 否则 test_good_spec_passes 会因为「没有 output_root」红。
            # 补的是**夹具缺口**，不是放宽判据——落点确实是产物归档的前提。
            "output_root": str(tmp / "图像影音资源池" / "无音" / "批次" / "b1"),
            "project": "无音", "project_aliases": {"无音": ["wuyin", "无音", "沈无音"]}}
    base.update(kw)
    return base


def test_good_spec_passes(tmp_path):
    rep = run_checks(_spec(tmp_path))
    assert not rep.errors, rep.render()


def test_g2_blocks_same_image_in_two_slots(tmp_path):
    r1 = _png(tmp_path, "same1.png", 11)
    r2 = _png(tmp_path, "same2.png", 22)
    refs = [r1, r2, r1, r2]                      # 两张图占四槽
    rep = run_checks(_spec(tmp_path, refs=refs))
    gates = {g for _, g, _ in rep.errors}
    assert "G2" in gates
    assert any("槽1" in t and "槽3" in t for _, _, t in rep.errors)


def test_g3_blocks_declared_role_conflict(tmp_path):
    """9-18 的翻车现场：提示词说 <Picture 2> 是薇拉，槽 2 挂的却是白玖璃。"""
    refs = [_png(tmp_path, f"s{i}.png", i) for i in range(4)]
    # 身份只由 sidecar 卡决定（实际身份卡片随锚点一起存）
    for i, r in enumerate(refs, 1):
        label = "白玖璃" if i in (1, 2, 3, 4) else "薇拉"
        Path(str(r) + ".anchor.json").write_text(json.dumps(
            {"character": label, "role": "costume"}, ensure_ascii=False), encoding="utf-8")
    prompt = ("【主体与关系】<Picture 2> 是薇拉。【事件脚本】对撞。"
              "【保持一致】不变。【镜头】中景缓缓前推。【声音】风声。")
    rep = run_checks(_spec(tmp_path, refs=refs, prompt=prompt))
    assert any(g == "G3" and "冲突" in t for _, g, t in rep.errors)


def test_g4_blocks_slot_count_mismatch(tmp_path):
    """模板里的 __REFn__ 个数＝引擎真能吃的槽数：少挂会以字面量提交直接失败，
       多挂会被静默丢弃（两种都得拦，静默丢弃尤其阴）。"""
    tpl = tmp_path / "tpl.json"
    tpl.write_text(json.dumps({"1": {"class_type": "LoadImage",
                                     "inputs": {"image": "__REF1__"}},
                               "2": {"class_type": "LoadImage",
                                     "inputs": {"image": "__REF2__"}}}), encoding="utf-8")
    too_many = [_png(tmp_path, f"b{i}.png", i) for i in range(3)]
    rep = run_checks(_spec(tmp_path, refs=too_many, workflow_json=str(tpl)))
    assert any(g == "G4" and "静默丢弃" in msg for _, g, msg in rep.errors)
    too_few = [_png(tmp_path, f"c{i}.png", i) for i in range(1)]
    rep2 = run_checks(_spec(tmp_path, refs=too_few, workflow_json=str(tpl)))
    assert any(g == "G4" and "__REF2__" in msg for _, g, msg in rep2.errors)


def test_g5_warns_on_4_to_7_aspect(tmp_path):
    rep = run_checks(_spec(tmp_path, w=768, h=1344))
    assert any(g == "G5" and lv == "warn" for lv, g, _ in rep.items)
    rep2 = run_checks(_spec(tmp_path, w=865, h=1536))
    assert any(g == "G5" and lv == "error" for lv, g, _ in rep2.items)


def test_g6_length_bounds(tmp_path):
    assert any(g == "G6" for _, g, _ in run_checks(_spec(tmp_path, length=60)).errors)
    assert not any(g == "G6" for _, g, _ in run_checks(_spec(tmp_path, length=124)).errors)


def _g7(tmp, **kw):
    """只跑 G7，返回 [(level, text)]——这组断言只关格式判据，别让 G1/G4 的文件系统噪声掺进来。"""
    rep = run_checks(_spec(tmp, **dict(kw, only=["G7"])))
    return [(lv, t) for lv, g, t in rep.items if g == "G7"]


def test_g7_catches_missing_block_gear_and_literal_risk(tmp_path):
    """缺核心分块＝十块判据，只在云端通道跑（H3 侧写十块改判混用）；
       器材名词/哑女/字面化风险是跨通道共性坑，两条通道都得拦。"""
    no_block = "【主体与关系】<Picture 1> 是甲。【事件脚本】走路。【镜头】前推。【声音】风。"

    errs = [t for lv, t in _g7(tmp_path, prompt=no_block, provider="ark",
                               prompt_kind="video") if lv == "error"]
    assert any("保持一致" in t for t in errs), errs
    # 同一段文本挂本地 H3：报混用，不再报缺块（缺块判据已随十块一起剥给云端）
    errs = [t for lv, t in _g7(tmp_path, prompt=no_block, provider="local",
                               prompt_kind="h3_ref2va") if lv == "error"]
    assert any("混用" in t for t in errs), errs
    assert not any("保持一致" in t for t in errs), errs

    gear = ("【主体与关系】<Picture 1> 是甲。【事件脚本】走路。【保持一致】不变。"
            "【镜头】用稳定器环绕跟拍。【声音】风。")
    for prov, kind in (("ark", "video"), ("local", "h3_ref2va")):
        errs = [t for lv, t in _g7(tmp_path, prompt=gear, provider=prov,
                                   prompt_kind=kind) if lv == "error"]
        assert any("稳定器" in t and "器材" in t for t in errs), (prov, errs)

    silent = ("【主体与关系】<Picture 1> 是哑女。【事件脚本】抬手。【保持一致】不变。"
              "【镜头】中景缓推。【声音】风。")
    assert any("不出声" in t for lv, t in _g7(tmp_path, prompt=silent, provider="ark",
                                              prompt_kind="video") if lv == "error")
    risk = ("【主体与关系】<Picture 1> 是甲。【事件脚本】走路。【保持一致】不变。"
            "【镜头】中景缓推。【声音】风。") + "\n背后展开蝶形双翼。"
    assert any(lv == "warn" and "蝶形" in t for lv, t in
               _g7(tmp_path, prompt=risk, provider="ark", prompt_kind="video"))
    # 六段（H3 现行主力格式）里出现器材名词同样拦——共性坑不随格式豁免
    h3_gear = _ref2va_prompt().replace("the others stay behind",
                                       "the others stay behind, filmed with 稳定器")
    assert any("稳定器" in t for lv, t in _g7(tmp_path, prompt=h3_gear) if lv == "error")


def test_g11_blocks_cross_project_landing(tmp_path):
    refs = [_png(tmp_path, f"c{i}.png", i) for i in range(4)]
    spec = _spec(tmp_path, refs=refs, only=["G11"], project="无音",
                 project_aliases={"无音": ["wuyin", "无音"], "仙戮": ["xianlu", "仙戮"]},
                 theme="xianlu_shot5_A",
                 output_root=str(tmp_path / "图像影音资源池" / "无音" / "批次" / "b1"))
    assert any(g == "G11" and "仙戮" in t for _, g, t in run_checks(spec).errors)
    spec2 = dict(spec, project="仙戮",
                 output_root=str(tmp_path / "图像影音资源池" / "仙戮" / "批次" / "b1"))
    assert not any(g == "G11" for _, g, _ in run_checks(spec2).errors)


def test_manifest_records_params_and_ref_slots(tmp_path):
    refs = [_png(tmp_path, f"m{i}.png", i) for i in range(4)]
    outputs = {"gen": {"files": [str(tmp_path / "v.mp4")], "seed": 42, "count": 1,
                       "elapsed": 553.0, "length": 124, "prompt": "P"}}
    step_params = {"gen": {"ref_images": refs, "width": 864, "height": 1536,
                           "steps": 8, "length": 124, "lora": "lora.safetensors",
                           "lora_strength": 1.0}}
    data = write_manifest(tmp_path / "m.json", "r1", "h3_ref2va_video", outputs,
                          args={"theme": "t", "api_key": "secret", "api_key_env": "X"},
                          step_params=step_params, cfg={"project": "仙戮"},
                          batch_dir=tmp_path)
    e = data["images"][0]
    # 历史上这些全是 null（write_manifest 只认复数 seeds 与 out["width"]）
    assert (e["seed"], e["width"], e["height"], e["steps"], e["length"]) == (42, 864, 1536, 8, 124)
    assert e["lora"] == "lora.safetensors" and e["elapsed"] == 553.0
    assert [r["slot"] for r in e["ref_images"]] == [1, 2, 3, 4]
    assert all(len(r["md5"]) == 8 for r in e["ref_images"]), "逐槽指纹是查重依据"
    assert len({r["md5"] for r in e["ref_images"]}) == 4
    assert data["args"] == {"theme": "t"}, "args 快照必须脱敏，不能把 key 类字段写进台账"
    assert data["project"] == "仙戮"


def test_preflight_or_die_blocks_and_honours_switch(tmp_path):
    refs = [_png(tmp_path, "p1.png", 1)] * 2          # 故意同图占两槽
    tpl = ROOT / "comfy" / "h3_i2v_ref2va_api.json"
    logs = []
    ctx = {"cfg": {"preflight": "on", "project": "无音", "project_aliases": {},
                   "log_dir": str(tmp_path / "logs"),
                   "comfyui": {"root": str(tmp_path)}},
           "args": {"theme": "t"}, "batch_dir": str(tmp_path), "log": logs.append,
           "wf_root": str(ROOT)}
    p = {"prompt": "【主体与关系】<Picture 1> 是甲。【事件脚本】走。【保持一致】不变。"
                   "【镜头】缓推。【声音】风。",
         "ref_images": refs, "width": 864, "height": 1536, "length": 124, "steps": 8}
    with pytest.raises(RuntimeError, match="跑前自审未通过"):
        preflight_or_die(p, ctx, refs, [], tpl)
    assert any("[preflight:G2][ERROR]" in m for m in logs)
    # 关掉开关必须真放行（应急绕过路径）——10-02 起多一条要求：绕过必须留字据（R5-07）
    ctx["cfg"] = dict(ctx["cfg"], preflight="off")
    preflight_or_die(p, ctx, refs, [], tpl)
    assert any("跳过跑前自审" in m for m in logs)
    led = json.loads((tmp_path / "logs" / "gate_approvals.json").read_text(encoding="utf-8"))
    assert led.get("bypassed"), "关闸只进日志＝绕过无痕；现在必须在台账里查得到"
    assert any("preflight" in str(v.get("reason")) for v in led["bypassed"].values())


def test_preflight_fails_closed_when_checker_missing(tmp_path, monkeypatch):
    """闸本身不可用时必须停下，不能"算了继续跑"。"""
    ctx = {"cfg": {"preflight": "on"}, "args": {}, "batch_dir": str(tmp_path),
           "log": lambda m: None, "wf_root": str(tmp_path)}
    monkeypatch.setattr(cp, "run_checks", None)
    with pytest.raises((RuntimeError, TypeError)):
        preflight_or_die({"prompt": "x", "ref_images": [], "width": 864, "height": 1536,
                          "length": 124}, ctx, [], [], tmp_path / "nope.json")


def test_config_has_project_derivation_keys():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert {"pool_root", "project", "batch_subdir", "project_aliases", "preflight"} <= set(cfg)
    assert cfg["project"] in Path(cfg["output_root"]).parts
    assert "xianlu" in cfg["project_aliases"].get("仙戮", []), "别名表要能认出 latin 代号"
