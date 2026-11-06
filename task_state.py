# -*- coding: utf-8 -*-
"""S1 任务安全：输入绑定与恢复判定（纯函数，无网络、无进程、无 GPU）。

用途：
  · run.py 把 resume_binding 写进 manifest，--resume 时按步骤比较依赖；
  · h3_movie 每镜记录 shot_binding，防止改 seed／同路径素材／模板后仍跳过；
  · 旧 manifest 没有指纹时不静默继承：能证明的编译步可复用，证明不了的
    生成/审核步明确失效。

判据只认内容哈希，不认 mtime／文件名／“看起来一样”。
"""
import hashlib
import json
from pathlib import Path

SCHEMA = 1

# 影响生成/审核的参数。execution tier / allow_degrade 只改降级策略，不进这里。
PARAM_KEYS = (
    "width", "height", "length", "fps", "steps", "lora", "lora_strength",
    "lora2", "lora2_strength", "seed", "scale_by", "two_pass",
    "two_pass_coarse_steps", "two_pass_refine_steps", "input_mode",
    "prompt_kind", "use_llm_polish", "enable_audio", "resolution_tier",
    "audio_mode", "audio_post", "degrade_sizes", "output_width",
    "output_height", "head_chunks", "crop", "out_size", "confirm_big_scale",
    "llm_backend",
)
COMPILE_KEYS = ("use_llm_polish", "prompt_kind", "llm_backend")
COMPILE_IDS = {"snapshot", "translate", "compile_check"}
MEDIA_KEYS = ("ref_images", "ref_videos", "ref_video_audios", "ref_audios")


def _norm(v):
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in sorted(v.items())}
    return v


def _as_list(v):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [x for x in list(v) if str(x).strip()]


def sha256_file(path):
    p = Path(str(path))
    try:
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def md5_file(path):
    p = Path(str(path))
    try:
        if not p.is_file():
            return None
        h = hashlib.md5()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()[:8]
    except OSError:
        return None


def prompt_binding(args):
    """提示词单一真源：prompt_file 优先，其次内联 prompt。"""
    pf = str((args or {}).get("prompt_file") or "")
    if pf:
        p = Path(pf)
        text = (p.read_text(encoding="utf-8", errors="replace").strip()
                if p.is_file() else "")
        return {"origin": "file", "path": str(p), "sha256": sha256_file(p),
                "resolved_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    text = str((args or {}).get("prompt") or "")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"origin": "inline", "path": None, "sha256": digest,
            "resolved_sha256": digest}


def media_binding(args):
    out = {}
    for key in MEDIA_KEYS:
        out[key] = [{"path": str(v), "sha256": sha256_file(v)}
                    for v in _as_list((args or {}).get(key))]
    return out


def template_binding(engine_root, wf):
    for step in (wf or {}).get("steps") or []:
        for key in ("workflow", "workflow_json"):
            rel = str(step.get(key) or "").strip()
            if rel.startswith("comfy/") and rel.endswith(".json"):
                return {"path": rel,
                        "sha256": sha256_file(Path(engine_root) / rel)}
    return {"path": None, "sha256": None}


def workflow_binding(engine_root, workflow_name):
    rel = f"workflows/{workflow_name}.yaml"
    return {"path": rel, "sha256": sha256_file(Path(engine_root) / rel)}


def build_binding(engine_root, workflow_name, wf, args):
    args = dict(args or {})
    return {
        "schema": SCHEMA,
        "workflow": workflow_binding(engine_root, workflow_name),
        "template": template_binding(engine_root, wf),
        "prompt": prompt_binding(args),
        "media": media_binding(args),
        "params": {k: _norm(args.get(k)) for k in PARAM_KEYS if k in args},
        "compile": {k: _norm(args.get(k)) for k in COMPILE_KEYS if k in args},
    }


def step_scope(step):
    sid = str((step or {}).get("id") or "")
    task = str((step or {}).get("task") or "")
    if sid in COMPILE_IDS or task == "llm":
        return ("workflow", "prompt", "compile")
    return ("workflow", "template", "prompt", "media", "params", "compile")


def step_digest(binding, step):
    # R5：除绑定外，步骤自身的实际字段（含 YAML 级 lora_strength/seed/steps/
    # prompt_file 等覆盖）必须进摘要；只看顶层 args 会漏掉步骤级覆盖。
    payload = {
        "binding": {k: (binding or {}).get(k) for k in step_scope(step)},
        "step": {k: _norm(v) for k, v in (step or {}).items()
                 if k not in ("label", "hint")},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def attach_steps(binding, steps):
    b = dict(binding or {})
    b["steps"] = {str(s.get("id")): step_digest(binding, s)
                  for s in (steps or []) if s.get("id")}
    return b


def _legacy_evidence(prev_manifest, curr_args):
    """旧 manifest 只有 args/images；能证明的只有参数、提示词和参考图。"""
    man = prev_manifest or {}
    prev_args = man.get("args") or {}
    curr_args = dict(curr_args or {})
    keys = [k for k in PARAM_KEYS if k in prev_args or k in curr_args]
    params_match = all(
        _norm(prev_args.get(k)) == _norm(curr_args.get(k)) for k in keys)
    imgs = man.get("images") or []
    last = imgs[-1] if imgs else {}
    curr_prompt = prompt_binding(curr_args)["resolved_sha256"]
    prompt_match = None
    # R2：旧 manifest 的顶层 args 才是**原稿来源**；images[].prompt_sha256
    # 记的是该步实际消费的 prompt（常见是编译稿），拿它比原稿必然不同。
    if prev_args.get("prompt_file") or prev_args.get("prompt"):
        prompt_match = prompt_binding(prev_args)["resolved_sha256"] == curr_prompt
    elif last.get("prompt_sha256"):
        # 更老的结构没有 args.prompt_file，只能退回 image 字段；仅作兼容兜底。
        prompt_match = curr_prompt[:16] == last["prompt_sha256"]
    media_match = None
    prev_refs = last.get("ref_images")
    if isinstance(prev_refs, list):
        media_match = [r.get("md5") for r in prev_refs] == [
            md5_file(p) for p in _as_list(curr_args.get("ref_images"))]
    compile_match = all(
        _norm(prev_args.get(k)) == _norm(curr_args.get(k)) for k in COMPILE_KEYS)
    return {"params": params_match, "prompt": prompt_match,
            "media": media_match, "compile": compile_match,
            "any": bool(prev_args or imgs)}


def select_resume_steps(done_prev, steps, prev_binding, curr_binding,
                        prev_manifest=None, curr_args=None):
    """返回 {reusable, invalidated, basis}。

    · 有逐步骤指纹：按顺序比较；一旦某步失效，后续所有步都失效（顺序依赖）。
    · 旧 manifest 无指纹：只复用能证明的编译步；生成/审核步缺模板证据，明确失效。
    """
    done = {str(x) for x in (done_prev or set())}
    curr = {str(s.get("id")): step_digest(curr_binding, s)
            for s in (steps or []) if s.get("id")}
    reusable, invalidated = set(), {}
    if prev_binding and prev_binding.get("steps"):
        prev = prev_binding.get("steps") or {}
        blocked = None
        for s in steps or []:
            sid = str(s.get("id") or "")
            if sid not in done:
                continue
            if blocked:
                invalidated[sid] = f"上游步骤 {blocked} 已失效"
                continue
            if prev.get(sid) and prev.get(sid) == curr.get(sid):
                reusable.add(sid)
            else:
                invalidated[sid] = "依赖指纹变化" if prev.get(sid) else "缺该步指纹"
                blocked = sid
        return {"reusable": reusable, "invalidated": invalidated,
                "basis": "binding"}

    ev = _legacy_evidence(prev_manifest, curr_args)
    blocked = None
    for s in steps or []:
        sid = str(s.get("id") or "")
        if sid not in done:
            continue
        if blocked:
            invalidated[sid] = f"上游步骤 {blocked} 已失效"
            continue
        if step_scope(s) == ("workflow", "prompt", "compile"):
            ok = bool(ev.get("prompt")) and bool(ev.get("compile"))
            if ok:
                reusable.add(sid)
                continue
        invalidated[sid] = ("旧 manifest 无依赖指纹，不能证明未变"
                            if not ev.get("any") else
                            "旧 manifest 缺模板/工作流指纹，生成/审核步不能复用")
        blocked = sid
    return {"reusable": reusable, "invalidated": invalidated, "basis": "legacy"}


def shot_binding(engine_root, workflow_rel, params, ref_images):
    """h3_movie 单镜绑定：生成参数＋参考图内容＋实际模板。"""
    p = dict(params or {})
    return {
        "schema": SCHEMA,
        "workflow": {"path": workflow_rel,
                     "sha256": sha256_file(Path(engine_root) / workflow_rel)},
        "params": {k: _norm(p.get(k)) for k in PARAM_KEYS if k in p},
        "media": [{"path": str(v), "sha256": sha256_file(v)}
                  for v in _as_list(ref_images)],
    }
