# -*- coding: utf-8 -*-
"""H3 一键成片的尺寸／降级梯子（2026-10-03 用户裁「删除硬编码，全部强制要求显式配置」）。

以前 `_H3_PROFILES` 三个档都写死 736x416，`_retry_ladder` 里又写死 736x416 / 640x352
两级降级——意思是：**代码替每一批决定了构图尺寸，还在显存吃紧时替人偷偷换过尺寸**。
现在这两处都要求从人写的配置里来，量不到的那一步就报错。

只用 dry_run 路径（不起 ComfyUI、不烧卡），测的是参数装配这一段。
"""
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import tasks as T                                       # noqa: E402

GEN = {"width": 736, "height": 416}
# 成片尺寸是另一件事（标准化那一步的目标），测试里照常显式给满
OUT = {"output_width": 1920, "output_height": 1080}


def _manifest(tmp_path, defaults=None, shots=None):
    m = {"title": "测试批", "profile": "stable_t8", "seed_base": 42,
         "defaults": dict(defaults or {}),
         "shots": shots or [{"id": "s01", "prompt": "p", "ref_images": ["a.png"]}]}
    fp = tmp_path / "shots.json"
    fp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return str(fp)


def _ctx(tmp_path, args=None):
    return {"cfg": {"comfyui": {"base_url": "http://127.0.0.1:1"}},
            "batch_dir": str(tmp_path / "batch"), "run_id": "R1",
            "args": args or {}, "log": lambda m: None, "step_id": "movie"}


# ── 1. profile 里不许再有尺寸 ─────────────────────────────────────
def test_profiles_no_longer_carry_a_size():
    for name, prof in T._H3_PROFILES.items():
        assert "width" not in prof and "height" not in prof, \
            "%s 又长出尺寸兜底：代码替人决定画布就是这次裁定要删的东西" % name


def test_profiles_still_carry_the_channel_facts():
    """尺寸走了，但**通道侧的事实**必须留着：步数与 LoRA 的配对是实测出来的，
       挪进配置文件只会让人写错然后"能跑但质量错"。"""
    for name, prof in T._H3_PROFILES.items():
        assert prof.get("steps") and prof.get("lora"), name
        assert prof.get("length") and prof.get("head_chunks"), name


def _plan(out):
    """dry_run 的返回值里就带 plan 路径——从盘上重读，不信函数返回的摘要。"""
    return json.loads(io.open(out["files"][0], encoding="utf-8").read())


# ── 2. 尺寸必须显式给，四种给法 ──────────────────────────────────
def test_manifest_defaults_supply_the_size(tmp_path):
    out = T.t_h3_movie(dict(OUT, manifest=_manifest(tmp_path, GEN), dry_run="true"), _ctx(tmp_path))
    assert out["dry_run"] is True
    plan = _plan(out)
    assert plan["shots"][0]["generation"]["width"] == 736, "尺寸没落到这一镜的实际参数里"


def test_step_params_supply_the_size(tmp_path):
    out = T.t_h3_movie(dict(OUT, manifest=_manifest(tmp_path), dry_run="true", width=832, height=480), _ctx(tmp_path))
    g = _plan(out)["shots"][0]["generation"]
    assert (g["width"], g["height"]) == (832, 480)


def test_args_or_set_supply_the_size(tmp_path):
    out = T.t_h3_movie(dict(OUT, manifest=_manifest(tmp_path), dry_run="true"), _ctx(tmp_path, {"width": 640, "height": 352}))
    assert _plan(out)["shots"][0]["generation"]["width"] == 640


def test_per_shot_size_is_allowed_but_not_mixed_silently(tmp_path):
    """逐镜给尺寸是可以的，但**每一镜都得给**——不许出现"6 镜按一个尺寸、
       第 7 镜让代码凑"的混合批次。"""
    shots = [{"id": "s01", "prompt": "a", "ref_images": ["x.png"],
              "generation": {"width": 736, "height": 416}},
             {"id": "s02", "prompt": "b", "ref_images": ["y.png"]}]
    with pytest.raises(RuntimeError) as e:
        T.t_h3_movie(dict(OUT, manifest=_manifest(tmp_path, shots=shots), dry_run="true"), _ctx(tmp_path))
    msg = str(e.value)
    assert "s02" in msg, "报错没点名是哪一镜缺尺寸"
    assert "defaults" in msg, "报错没告知第三种给法（写进 manifest defaults）"


def test_size_must_be_multiple_of_32(tmp_path):
    with pytest.raises(RuntimeError, match="32 的倍数"):
        T.t_h3_movie(dict(OUT, manifest=_manifest(tmp_path, {"width": 735, "height": 416}), dry_run="true"),
                     _ctx(tmp_path))


def test_output_size_still_required_for_the_final_file(tmp_path):
    """成片尺寸（output_width/height）是另一个数：它归标准化那一步，
       以前代码兜底 1920x1080，现在同样必须显式。"""
    with pytest.raises(RuntimeError, match="output_width"):
        T.t_h3_movie({"manifest": _manifest(tmp_path, GEN), "dry_run": "true"},
                     _ctx(tmp_path))


# ── 3. 降级梯子：只降人声明过的画布 ───────────────────────────────
def test_degrade_sizes_parse():
    assert T._parse_degrade_sizes("736x416,640x352") == [(736, 416), (640, 352)]
    assert T._parse_degrade_sizes(" 736×416 ") == [(736, 416)]   # 全角乘号也认
    assert T._parse_degrade_sizes("") == []
    with pytest.raises(RuntimeError, match="写法不对"):
        T._parse_degrade_sizes("736-416")


def test_ladder_without_declared_sizes_never_touches_the_canvas():
    base = dict(GEN, length=124, steps=8, lora="x", head_chunks=4)
    lad = T._retry_ladder(base)
    assert [c["width"] for c in lad] == [736, 736], \
        "没声明降级画布却出现第二种尺寸 ⇒ 梯子又自己造数了"
    assert lad[-1]["head_chunks"] == 8, "分块这一档还在（那是显存参数，不是画面）"


def test_ladder_uses_declared_smaller_canvases_in_order():
    base = {"width": 1024, "height": 576, "length": 124, "steps": 8, "lora": "x",
            "head_chunks": 4}
    lad = T._retry_ladder(base, T._parse_degrade_sizes("736x416,640x352"))
    assert [(c["width"], c["height"], c["head_chunks"]) for c in lad] == [
        (1024, 576, 4),      # 原样重试
        (1024, 576, 8),      # 先只加显存分块（不动画面）
        (736, 416, 8), (640, 352, 8)]   # 再按**人声明过的**画布往下降


def test_ladder_skips_rungs_that_are_not_smaller():
    """声明了个**更大**的画布——那不叫"降"，跳过，别照着它把片子放大。"""
    base = {"width": 640, "height": 352, "length": 124, "steps": 8, "lora": "x",
            "head_chunks": 4}
    lad = T._retry_ladder(base, T._parse_degrade_sizes("1024x576,640x352"))
    assert {c["width"] for c in lad} == {640},         "声明了更大的画布却被当成降级档用上了：%s" % lad


def test_ladder_never_changes_steps_or_lora():
    base = {"width": 1024, "height": 576, "length": 124, "steps": 8,
            "lora": "eight.safetensors", "head_chunks": 4}
    for c in T._retry_ladder(base, T._parse_degrade_sizes("736x416")):
        assert c["steps"] == 8 and c["lora"] == "eight.safetensors"


# ── 4. 现役那条流：拿真 yaml 装配一遍（dry_run，不起 ComfyUI）───────
def test_the_live_one_click_movie_yaml_still_assembles(tmp_path):
    """删兜底之后，`workflows/h3_one_click_movie.yaml` 必须**照旧装配得起来**。

    装配面用 run.py 自己的 `render` 走一遍，所以这里量到的是现役真实行为，
    不是我对 yaml 结构的印象。装配不起来 = 这条流从此跑不动，属于最贵的回归。
    """
    import yaml
    from run import render, CONTROL_KEYS

    wf = ROOT / "workflows" / "h3_one_click_movie.yaml"
    doc = yaml.safe_load(io.open(wf, encoding="utf-8"))
    args = dict(doc.get("args") or {})
    mf = tmp_path / "shots.json"
    mf.write_text(json.dumps({"title": "装配检查", "profile": str(args.get("profile")),
                              "shots": [{"id": "s01", "prompt": "p",
                                         "ref_images": ["a.png"]}]},
                             ensure_ascii=False), encoding="utf-8")
    args["manifest"] = str(mf)
    ctx = {"cfg": {"comfyui": {"base_url": "http://127.0.0.1:1"}}, "args": args,
           "run_id": "CHK", "log": lambda m: None, "outputs": {},
           "batch_dir": str(tmp_path / "batch")}
    step = [s for s in doc["steps"] if s.get("task") == "h3_movie"][0]
    p = render({k: v for k, v in step.items() if k not in CONTROL_KEYS}, ctx)
    p["dry_run"] = "true"
    out = T.t_h3_movie(p, ctx)
    plan = _plan(out)
    g = plan["shots"][0]["generation"]
    assert g["width"] % 32 == 0 and g["height"] % 32 == 0, g
    # 钉"链路"不钉"值"：值归人（本轮裁定），改了像素不该测试红。
    assert (g["width"], g["height"]) == (int(args["width"]), int(args["height"])), \
        "yaml 写的单镜尺寸没原样落到这一镜 ⇒ 中间那层 render 漂了"
    assert (plan["output"]["width"], plan["output"]["height"]) == \
        (int(args["output_width"]), int(args["output_height"])), plan["output"]
    assert plan["degrade_sizes"], (
        "现役这条流在 yaml 里声明过 degrade_sizes，plan 里却是空的 " \
        "⇒ 要么 args 被删空，要么 _parse_degrade_sizes 与 render 之间断了；" \
        "两种都意味着 OOM 时不再自动降画布，而这本该是看得见的决定")
