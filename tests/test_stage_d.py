# -*- coding: utf-8 -*-
"""阶段 D（输出目录统一）的离线单测。

不碰显存、不起 ComfyUI、不调模型：只用 tmp_path 摆目录树。
跑法：cd E:\\LocalAI\\workflows && python -m pytest tests -q
"""
import json
import sys
from pathlib import Path

import yaml
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run as engine                     # noqa: E402
from tasks import relocate               # noqa: E402

WF = ROOT / "workflows"


def test_scaffold_imports_work():
    assert engine.ROOT == WF.parent
    assert (WF / "image_draft_batch.yaml").exists()


def test_relocate_moves_files_and_clears_source(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    a = staging / "draft_20260903_113813_00001_.png"
    b = staging / "draft_20260903_113813_00002_.png"
    a.write_bytes(b"aa")
    b.write_bytes(b"bb")

    dst = tmp_path / "out" / "20260903_113813" / "draft"
    got = relocate([str(a), str(b)], dst)

    assert sorted(p.name for p in dst.iterdir()) == sorted([a.name, b.name])
    assert not a.exists() and not b.exists()          # 是搬不是复制
    assert [Path(g).name for g in got] == sorted([a.name, b.name])
    assert all(Path(g).read_bytes() in (b"aa", b"bb") for g in got)


def test_relocate_appends_suffix_on_name_clash(tmp_path):
    s1, s2 = tmp_path / "s1", tmp_path / "s2"
    s1.mkdir()
    s2.mkdir()
    f1, f2 = s1 / "same.png", s2 / "same.png"
    f1.write_bytes(b"first")
    f2.write_bytes(b"second")

    dst = tmp_path / "out"
    relocate([str(f1)], dst)
    got = relocate([str(f2)], dst)

    assert Path(got[0]).name == "same_1.png"
    assert Path(got[0]).read_bytes() == b"second"      # 谁后来谁带序号
    assert (dst / "same.png").read_bytes() == b"first"  # 已存在的不动


def test_relocate_empty_list_creates_no_directory(tmp_path):
    assert relocate([], tmp_path / "never") == []
    assert not (tmp_path / "never").exists()


def test_relocate_raises_when_source_missing(tmp_path):
    """缺失不静默跳过：本函数存在的全部理由就是"不信任 ComfyUI 写到哪了"，
    静默返回 [] 会让精修在 sizes[0] 上裸崩，正好是阶段 D 要消灭的那类失败。"""
    with pytest.raises(RuntimeError) as e:
        relocate([str(tmp_path / "ghost.png")], tmp_path / "out")
    assert "ghost.png" in str(e.value)


def test_relocate_raises_on_partial_drop(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    ok = staging / "draft_x_00001_.png"
    ok.write_bytes(b"aa")
    with pytest.raises(RuntimeError) as e:
        relocate([str(ok), str(staging / "draft_x_00002_.png")], tmp_path / "out")
    assert "只搬到 1 个" in str(e.value)


def test_batch_dir_wiring_in_source():
    src = (ROOT / "run.py").read_text(encoding="utf-8")
    # 批次夹名用 batch_id（manifest 所在夹）而不是 parent_run（manifest 内的 run_id）：
    # 后者在"照精修报告底部命令再精修一次"时会指向精修自己的 id，等于把批次拆成新夹
    assert 'batch_dir = Path(cfg["output_root"]) / str(batch_id or run_id)' in src
    assert 'RunReport(batch_dir / f"{a.workflow}_{run_id}.html"' in src
    assert 'manifest_path = batch_dir / f"{a.workflow}_{run_id}.manifest.json"' in src
    assert '"batch_dir": batch_dir' in src
    # .log 必须留在 log_dir，别被顺手搬进交付夹
    assert 'Logger(Path(cfg["log_dir"]) / f"{a.workflow}_{run_id}.log")' in src


def test_ctx_keys_and_reserved_set_stay_in_sync():
    """步骤完成时执行 ctx[sid] = out，所以每往 ctx 加一个键，就多一个能被
    同名步骤 id 顶掉的位置。用 AST 比对两个集合，比硬搜字符串稳：不依赖换行
    位置，且能抓住将来漏掉的任何键。"""
    import ast
    tree = ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))
    ctx_keys = reserved = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id == "ctx" and isinstance(node.value, ast.Dict):
            ctx_keys = {k.value for k in node.value.keys}
        elif tgt.id == "reserved" and isinstance(node.value, ast.Set):
            reserved = {e.value for e in node.value.elts}
    assert ctx_keys is not None and reserved is not None, "run.py 里找不到 ctx / reserved"
    assert ctx_keys == reserved, f"未进保留字的 ctx 键: {ctx_keys - reserved}"


def test_manifest_without_run_id_fails_loud(tmp_path):
    """manifest 缺 run_id 时，parent_run or run_id 会静默退化成自己的 run_id，
    精修产物就落进一个新夹 —— 直接违反"一个批次一夹"，且没有任何报错。"""
    import subprocess
    man = tmp_path / "image_draft_batch_20260101_000000.manifest.json"
    man.write_text(json.dumps({"workflow": "image_draft_batch",
                               "images": [{"index": 1, "step": "draft",
                                           "file": "x.png", "seed": 1}]}),
                   encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "run.py"), "image_refine",
                        "--set", f"manifest={man}", "--set", "pick=1"],
                       capture_output=True, cwd=str(ROOT))
    err = (r.stderr or b"").decode("utf-8", "replace")
    assert r.returncode == 2, f"期望退出码 2，实得 {r.returncode}\n{err}"
    # 按字节查 ASCII 子串：stderr 含中文，用 text=True 会被 Windows 的 GBK 解码噎住
    assert b"run_id" in r.stderr, err


def test_report_img_src_is_relative(tmp_path):
    batch = tmp_path / "out" / "20260903_113813"
    (batch / "draft").mkdir(parents=True)
    img = batch / "draft" / "draft_20260903_113813_00001_.png"
    img.write_bytes(b"x")
    steps = [{"id": "draft", "task": "comfyui", "label": "出草稿", "hint": ""}]
    rp = engine.RunReport(batch / "image_draft_batch_20260903_113813.html",
                          "image_draft_batch", "20260903_113813", steps)
    rp.state["draft"]["images"] = [str(img)]

    html, n = rp._images()

    assert n == 1
    assert 'src="draft/draft_20260903_113813_00001_.png"' in html   # 正斜杠，且相对报告
    assert "file://" not in html                                     # 绝对 file: URI 会破自包含
    assert str(tmp_path) not in html


def test_resolve_pick_finds_manifest_in_output_root(tmp_path):
    batch = tmp_path / "out" / "20260903_113813"
    draft = batch / "draft"
    draft.mkdir(parents=True)
    img = draft / "draft_20260903_113813_00001_.png"
    img.write_bytes(b"x")
    (batch / "image_draft_batch_20260903_113813.manifest.json").write_text(
        json.dumps({"run_id": "20260903_113813", "workflow": "image_draft_batch",
                    "images": [{"index": 1, "step": "draft", "file": str(img),
                                "seed": 7, "prompt": "p", "width": 832,
                                "height": 1216, "steps": 12}]},
                   ensure_ascii=False), encoding="utf-8")
    cfg = {"log_dir": tmp_path / "logs", "output_root": tmp_path / "out"}

    chosen, parent, batch_id = engine.resolve_pick(cfg, "20260903_113813", "1")

    assert parent["run_id"] == "20260903_113813"
    assert chosen[0]["seed"] == 7
    assert Path(chosen[0]["file"]).exists()
    assert batch_id == "20260903_113813"


def test_resolve_pick_batch_id_is_the_folder_not_the_inner_run_id(tmp_path):
    """精修报告的落款命令印的是精修自己的 run_id；照它再精修一次时，
    批次号必须取 manifest 所在夹（上游草稿夹），否则会新开一夹把批次拆散。"""
    batch = tmp_path / "out" / "20260903_113813"
    (batch / "final").mkdir(parents=True)
    img = batch / "final" / "refine_20260903_142015_00.png"
    img.write_bytes(b"x")
    (batch / "image_refine_20260903_142015.manifest.json").write_text(
        json.dumps({"run_id": "20260903_142015", "workflow": "image_refine",
                    "images": [{"index": 1, "step": "refine", "file": str(img),
                                "seed": 9, "prompt": "p", "width": 1664,
                                "height": 2432, "steps": 12}]},
                   ensure_ascii=False), encoding="utf-8")
    cfg = {"log_dir": tmp_path / "logs", "output_root": tmp_path / "out"}

    chosen, parent, batch_id = engine.resolve_pick(cfg, "20260903_142015", "1")

    assert parent["run_id"] == "20260903_142015"   # 父指针仍记那次精修自己
    assert batch_id == "20260903_113813"           # 但产物进的是草稿那一夹


def test_resolve_pick_still_accepts_absolute_manifest_path(tmp_path):
    mp = tmp_path / "elsewhere" / "m.manifest.json"
    mp.parent.mkdir()
    mp.write_text(json.dumps({"run_id": "X", "images": [
        {"index": 1, "file": "p", "seed": 3}]}, ensure_ascii=False), encoding="utf-8")
    cfg = {"log_dir": tmp_path / "logs", "output_root": tmp_path / "out"}

    chosen, parent, batch_id = engine.resolve_pick(cfg, str(mp), "1")

    assert parent["run_id"] == "X" and chosen[0]["seed"] == 3
    assert batch_id == "elsewhere"


def test_comfyui_task_relocates_right_after_poll_with_stage_param():
    src = (ROOT / "tasks.py").read_text(encoding="utf-8")
    # t_comfyui: 快照 + 零产物检查 + 一出炉就搬
    assert "pre_snapshot=pre_snapshot)" in src
    assert 'if not got:' in src
    assert ('got = relocate(got, Path(ctx["batch_dir"]) / str(p.get("stage", "draft")), ctx["log"])\n'
            '        files.extend(got)') in src
    # t_refine: 一出炉就搬（Task 3 会加快照）
    assert ('got = relocate(got, Path(ctx["batch_dir"]) / "final", ctx["log"])\n'
            '        out_files.extend(got)') in src


def test_refine_cleans_its_input_copies():
    src = (ROOT / "tasks.py").read_text(encoding="utf-8")
    assert "dst.unlink(missing_ok=True)" in src           # 本轮副本用完即删
    assert "input_dir.glob" in src and "refine_*" in src  # 上轮失败留下的残余下次开头清


def test_one_stage_workflow_archives_to_final_not_auto_out():
    """阶段 D 前 image_batch_draft 靠 files.copy_new 把图复制去 auto_out；
    relocate 上线后暂存区会被搬空，那一步会静默复制 0 个文件、却仍报 success。"""
    y = yaml.safe_load((WF / "image_batch_draft.yaml").read_text(encoding="utf-8"))
    ids = [s.get("id") for s in y["steps"]]
    assert "archive" not in ids
    assert "files" not in [s.get("task") for s in y["steps"]]
    gen = [s for s in y["steps"] if s.get("id") == "generate"][0]
    assert gen["stage"] == "final"       # 一步式的产物是成品，不是草稿


def test_two_stage_workflows_keep_default_stage():
    for name, step_id in (("image_draft_batch.yaml", "draft"),
                          ("image_refine.yaml", "refine")):
        y = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
        step = [s for s in y["steps"] if s.get("id") == step_id][0]
        assert "stage" not in step       # 缺即 draft（refine 走自己的 task，恒 final）


def test_config_distinguishes_staging_from_delivery():
    """暂存（ComfyUI 的 output_dir、引擎日志）与交付根必须是两个不同地方。

    2026-09-20 改：原来这条钉死一个旧绝对路径（E:\\FLUX_Workflow\\out），
    交付根换成资源池派生之后就一直红。改成按语义断言，不再钉路径。

    2026-11-04 修一处**真 bug**（不是环境问题）：这条曾把「resolve 过的交付根」拿去和
    「没 resolve 的 pool_root」比字符串前缀。本机 `E:\\图像影音资源池` 是 Junction →
    `E:\\繁星\\30_素材库`，`.resolve()` 会跟过去，于是永远不等 ⇒ 恒红（用户 11-04 前
    一直挂着这条红）。两条规矩：
      · 判「是不是同一个地方／谁包含谁」时，**两边都 resolve**，用 `Path.is_relative_to`
        按路径分量比，不用 `str.startswith`（`E:\\pool2` 也算以 `E:\\pool` 开头）。
      · 判「配置里那段项目名对不对」时，用**配置原文**的 parts——那是人的意图，
        resolve 之后 junction 可能把整段换成别的目录树，判真实路径会把意图判丢。
    """
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg_delivery = Path(cfg["output_root"])            # 配置原文（G11 判的就是它）
    delivery = cfg_delivery.resolve()                  # 盘上真实身份（junction 会跟过去）
    staging = Path(cfg["comfyui"]["output_dir"]).resolve()
    pool = Path(cfg["pool_root"]).resolve()
    assert staging != delivery, "暂存目录不能就是交付根，产物会散落"
    assert cfg.get("pool_root") and cfg.get("project") and cfg.get("batch_subdir"), \
        "交付根须由 pool_root/project/batch_subdir 派生（G11）"
    assert delivery.is_relative_to(pool), \
        f"交付根 {delivery} 不在资源池 {pool} 下（config 写的是 {cfg['pool_root']}）"
    assert cfg["project"] in cfg_delivery.parts, \
        "output_root 的项目段必须等于当前 project（按配置原文判，见 docstring 第 2 条）"
    assert not Path(cfg["log_dir"]).resolve().is_relative_to(delivery), \
        "日志不能写进交付夹，批次夹要自包含交付物"

