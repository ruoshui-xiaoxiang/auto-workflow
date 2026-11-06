# -*- coding: utf-8 -*-
r"""tasks_image_gen.py · `t_image` —— 图像源的唯一入口（2026-10-19 第⑤条，用户裁『接，先做最小可用版』）。

为什么单独一个文件
------------------
`tasks.py` 已经 2800+ 行／14 个 task，而且它同目录堆着三个 `.bak` 说明改动频繁
⇒ 在这种文件上做大规模搬移，撞车概率高。本模块用**同一个 `@task` 注册器**，
由 `run.py` 末尾 `import tasks_image_gen` 挂上，不改 `tasks.py` 一行。

三条硬规矩（都写进代码，不靠记性）
--------------------------------
1. **不许自动回落**（I9）：`source=jimeng` 而即梦不可用 ⇒ 抛错停下，报**具体原因码**与修复命令。
   要换本地必须**人先同意**，而且是**批级**授权：`--set local_approved=yes`，同批不许混源。
   理由不是洁癖：即梦 lite 挂参考实测锁脸 0.738~0.76，本地 Z-Image 纯文字天花板 0.60、
   跨镜最好 0.519 ⇒ 悄悄回落等于换脸，而闸看不出画面里有几个主体。
2. **参考图槽位与 `--ref` 顺序逐位绑定由代码保证**：返回值里的 `refs_bound` 就是证据，
   写进 manifest ⇒ 「参考图传反把女1的脸安到 B 侧」那种事故事后可查。
3. **`kind` 只决定 QC 口径，不参与回落决策**：`cast`/`first_frame` 查跨镜身份，
   `set`/`grid`/`prop` 不查（场景与道具没有"同一张脸"这回事）。
"""
from __future__ import annotations

from pathlib import Path

import jimeng_client as J
from tasks import REGISTRY, log, task

# 需要查身份的 kind（其余只查"有没有产物"）
_IDENTITY_KINDS = ("cast", "first_frame")


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v]
    s = str(v).strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


def _best_identity_sim(anchor, files):
    """锚点 vs 每张产物的 ArcFace 余弦，取最好的一张。**复用 tools/qc.py 那把尺**，
    不在这里另起一套 insightface 封装——两把尺量同一件事早晚漂（阈值注册表里
    `qc_absolute_bands` 的 authority 已经指向 tools/qc.py）。

    读不到脸一律返回 None（＝未测量），**不当 0 分、更不当通过**。
    """
    import sys
    tools = Path(__file__).resolve().parent.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import qc                                   # noqa: E402  本机尺子（中文路径走 imdecode）
    a_img = qc.imread(str(anchor))
    fa, _ = qc.face(a_img)
    if fa is None:
        return None
    best = None
    for f in files:
        img = qc.imread(str(f))
        if img is None:
            continue
        fb, _ = qc.face(img)
        if fb is None:
            continue
        s = float(fa.normed_embedding @ fb.normed_embedding)
        best = s if best is None else max(best, s)
    return best


@task("image")
def t_image(p, ctx):
    """出图（即梦优先，本地兜底需人批）。

    params:
      source      jimeng | local            默认 jimeng
      kind        cast | first_frame | set | grid | prop   默认 first_frame
      prompt      文本，或 prompt_file 指文件
      refs        **有序**参考图（本地路径或 res:/node:/uri:/vid: 前缀）
      ratio / resolution / count / model / project_id / title
      anchor      身份比对基准图（kind 属 cast/first_frame 时用它算 ArcFace 余弦）
      local_approved  切本地必须显式给 yes（批级授权，同批不许混源）
      enabled     默认 true；false 时整步跳过（给"首帧已存在"的老流程留口）
    """
    if str(p.get("enabled", True)).lower() in ("false", "0", "no"):
        log(ctx, "[image] enabled=false，跳过出图")
        return {"skipped": True}

    cfg = ctx.get("cfg") or {}
    jcfg = cfg.get("jimeng") or {}
    source = str(p.get("source") or "jimeng").strip().lower()
    kind = str(p.get("kind") or "first_frame").strip().lower()
    prompt = str(p.get("prompt") or "").strip()
    if not prompt and p.get("prompt_file"):
        pf = Path(str(p["prompt_file"]))
        if not pf.is_file():
            raise RuntimeError("image: prompt_file 不存在：%s" % pf)
        prompt = pf.read_text(encoding="utf-8-sig").strip()
    if not prompt:
        raise RuntimeError("image: 没有 prompt 也没有可读的 prompt_file")
    refs = _as_list(p.get("refs"))
    count = int(p.get("count") or 1)
    batch = Path(ctx["batch_dir"])
    out_dir = (batch / str(p.get("out") or kind)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    def _fail_no_fallback(code, detail):
        """即梦不行 ⇒ 停。绝不悄悄换本地：换源要人同意，且是批级。"""
        raise RuntimeError(
            "🔴 即梦出图不可用 [%s]：%s\n"
            "   按规矩**不许自动回落本地出图**（两个画风有差异，不能混用；实测锁脸 0.755 vs 本地 0.60 上限）。\n"
            "   两条路，都由你本人选：① 修即梦（登录/额度/档位）后重跑本批；\n"
            "   ② 整批改本地：加 --set source=local --set local_approved=yes（批级授权，同批不许混源）。"
            % (code, detail))

    if source == "jimeng":
        pr = J.probe(cfg, model=str(p.get("model") or J.DEFAULT_MODEL))
        if not pr["ok"]:
            _fail_no_fallback(pr["reason_code"] or "JM_UNKNOWN",
                              "%s %s" % (pr["detail"], pr.get("hint") or ""))
        log(ctx, "[image] 即梦可用（登录到期 %s，档 %s）" % (pr.get("expires_at"), pr["model"]))
        try:
            r = J.generate(cfg, prompt=prompt,
                           mode="i2i" if refs else "t2i",
                           refs=refs,
                           ratio=str(p.get("ratio") or "16:9"),
                           resolution=str(p.get("resolution") or "2K"),
                           count=count,
                           out_dir=str(out_dir),
                           title=str(p.get("title") or ctx.get("run_id") or "image"),
                           model=str(p.get("model") or J.DEFAULT_MODEL),
                           project_id=str(p.get("project_id") or jcfg.get("project_id") or ""),
                           credit_ceiling=int(p.get("credit_ceiling", jcfg.get("credit_ceiling", 0))),
                           log=lambda m: log(ctx, m))
        except J.JimengError as e:
            _fail_no_fallback(getattr(e, "code", "JM_UNKNOWN"), str(e))
        files, refs_bound = r["files"], r["refs_bound"]
        meta = {"source": "jimeng", "model": r["model"], "mode": r["mode"],
                "quote": r.get("quote"), "submission_state": r.get("submission_state"),
                "resource_ids": r.get("resource_ids"), "refs_bound": refs_bound}
    elif source == "local":
        if str(p.get("local_approved") or "").strip().lower() not in ("yes", "true", "1", "y"):
            raise RuntimeError("🔴 切本地出图需要**批级授权**：加 --set local_approved=yes。\n"
                               "   理由：即梦与本地两个画风有差异、不能混用（用户 2026-10-19 定的硬规矩），"
                               "而且本地纯文字锁脸天花板 0.60，低于即梦挂参考的 0.738~0.76。")
        raise RuntimeError("image: source=local 的最小实现还没接（要走 ComfyUI 的 Z-Image 模板）；"
                           "现役本地出图仍用 run.py 的图片链工作流（image_draft_batch 等）。"
                           "本 task 现在只保证**不会自动回落**这一条。")
    else:
        raise RuntimeError("image: source 只能是 jimeng 或 local，给了 %r" % source)

    if not files:
        raise RuntimeError("image: 跑完没有任何产物（out_dir=%s）" % out_dir)
    for f in files:
        if not Path(f).is_file() or Path(f).stat().st_size < 1024:
            raise RuntimeError("image: 产物不像真图：%s" % f)

    # QC 口径：只有角色/首帧类查身份；场景、九宫格、道具没有"同一张脸"这回事
    sim = None
    anchor = str(p.get("anchor") or "").strip()
    if kind in _IDENTITY_KINDS and anchor and Path(anchor).is_file():
        try:
            sim = _best_identity_sim(anchor, files)
            log(ctx, "[image] 身份比对（%s vs %d 张产物）最好 %s"
                % (Path(anchor).name, len(files),
                   "未测出脸" if sim is None else "%.3f" % sim))
        except Exception as e:
            log(ctx, "[image] ⚠ 身份比对没做成（%s）⇒ 报 None，不当 0 分也不当通过" % e)
    elif kind in _IDENTITY_KINDS:
        log(ctx, "[image] ⚠ kind=%s 该查身份但没给 anchor ⇒ 未测量（**不是通过**）" % kind)

    meta.update({"kind": kind, "files": files, "count": len(files),
                 "identity_sim": sim, "identity_checked": sim is not None})
    log(ctx, "[image] 完成：%d 张 → %s" % (len(files), out_dir))
    return meta
