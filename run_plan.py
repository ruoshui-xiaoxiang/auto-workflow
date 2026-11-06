# -*- coding: utf-8 -*-
"""W1 RunPlan：把"这次到底要跑什么"解析成一份可审、可比、可复现的计划。

定位（方案 §2.1／§2.2／§2.3）：
  · **纯解析器**——只读 YAML／模板／提示词，不提交、不联网、不起进程、不写交付根；
  · 包装已有的参数合并与 profile 处理，**不复制业务执行**（真正跑图的仍是 tasks.py）；
  · 模式识别复用 `tools/check_preflight._detect_skeleton_mode`（首行唯一真源），
    模板能力从**实际节点与连线**读，不看文件名（`*fl2va*` 里有一半其实是 I2VA）；
  · 只登记不能从图／YAML 推导的元数据到 channels_registry.json 的 `input_modes` 段。

机械不可执行（缺图、多图、混用格式、图形不存在、模式与模板不符、LoRA 与步数不配对）
一律在**提交前**抛 PlanError，错误文案要说清缺哪张、该换哪个模板。

字段分组按方案 §2.2：身份／输入／配方／几何／文本／声音／流程／版本／执行。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "1"

# 具名列表键：旧逗号字符串继续接，内部立即转列表（方案 §W1 第 6 条）。
# `pick` 刻意不在列——resolve_pick 按逗号字符串解析，转列表会破坏它。
LIST_KEYS = ("ref_images", "refs", "ref_videos", "videos_ref",
             "ref_audios", "ref_video_audios")

# 模式本身（prompt_kind／别名／模板指针／能力）住在 channels_registry.json 的
# `input_modes` 段——本模块**不再写第二份**（质量监督③①：一个真源）。
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
# 官方 Ref2VA 上限（9图/3视频/3视频原声/3独立音频，总文件 12）
REF_CAPS = {"images": 9, "videos": 3, "video_audios": 3, "audios": 3}
REF_TOTAL_FILES = 12


class PlanError(ValueError):
    """机械不可执行。消息必须给出"缺什么 / 在哪 / 换什么"三件事。"""


# ------------------------------------------------------------------ 参数合并
def parse_sets(raw_sets):
    """`--set k=v` → dict；列表键支持旧逗号写法与 JSON 数组两种。

    JSON 数组按**列表**解析并立即转具名结构；解析失败不静默当单条路径
    （方案 §W1 第 6 条：新契约不得把 JSON 字符串默默当单个路径）。
    """
    out = {}
    for s in raw_sets or ():
        k, sep, v = str(s).partition("=")
        if not sep:
            raise PlanError(f"--set 缺少 `=`：{s!r}（应写成 key=value）")
        k, v = k.strip(), v.strip()
        if k not in LIST_KEYS:
            out[k] = v
            continue
        if v == "":
            out[k] = []
        elif v.startswith("["):
            try:
                lst = json.loads(v)
            except json.JSONDecodeError as e:
                raise PlanError(
                    f"--set {k} 的值以 `[` 开头但不是合法 JSON（{e}）——"
                    f"要么写成合法字符串数组，要么用旧逗号写法 a.png,b.png") from e
            if not isinstance(lst, list) or not all(isinstance(x, str) for x in lst):
                raise PlanError(f"--set {k} 的 JSON 只接受字符串数组，实际是 {type(lst).__name__}")
            out[k] = [x.strip() for x in lst if x.strip()]
        else:
            out[k] = [x.strip() for x in v.split(",") if x.strip()]
    return out


def merge_args(wf_args, saved_args, cli_sets):
    """合并三层参数并**逐字段记录来源**（用户显式／续跑回放／YAML 默认）。

    来源不等于授权主体（方案 §W1 第 7 条）：这里只说"这个值从哪来"，
    不判断谁批准了它。
    """
    args = dict(wf_args or {})
    sources = {k: "yaml_default" for k in args}
    for k, v in (saved_args or {}).items():
        if k not in (cli_sets or {}):
            args[k] = v
            sources[k] = "resume_replay"
    for k, v in (cli_sets or {}).items():
        args[k] = v
        sources[k] = "cli_explicit"
    return args, sources


# ------------------------------------------------------------------ 模板能力
def find_template(wf):
    """从工作流步骤里找本次真正用的出片模板（`workflow` / `workflow_json`）。"""
    for step in (wf or {}).get("steps") or []:
        for key in ("workflow", "workflow_json"):
            v = str(step.get(key) or "").strip()
            if v.startswith("comfy/") and v.endswith(".json"):
                return v
    return None


def template_capabilities(tpl):
    """从实际节点/连线读能力：哪几个帧槽真存在、有几个参考图槽。"""
    first = last = False
    ref_slots, ref_video_slots, ref_audio_slots, encoders = set(), set(), set(), set()
    for _nid, node in (tpl or {}).items():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type") or "")
        if ct.startswith("MiniMax"):
            encoders.add(ct)
        for k in (node.get("inputs") or {}):
            ks = str(k)
            if ks == "first_frame":
                first = True
            elif ks == "last_frame":
                last = True
            elif ks.startswith("ref_images"):
                ref_slots.add(ks)
            elif ks.startswith("ref_video_audios") or ks.startswith("ref_audios"):
                ref_audio_slots.add(ks)
            elif ks.startswith("ref_videos"):
                ref_video_slots.add(ks)
    return {"first_frame": first, "last_frame": last,
            "ref_image_slots": len(ref_slots), "ref_video_slots": len(ref_video_slots),
            "ref_audio_slots": len(ref_audio_slots),
            # W1c 可选首尾帧模板：两端都接但都可缺，不能当成"真双端强制"
            "optional_keyframes": bool(((tpl or {}).get("_meta") or {})
                                       .get("optional_keyframes")),
            "keyframes_optional": bool(((tpl or {}).get("_meta") or {})
                                       .get("keyframes_optional")),
            # W4c 动态素材槽：图/视频/音频按实际数量注入，模板里不写死
            "dynamic_reference_slots": bool(((tpl or {}).get("_meta") or {})
                                            .get("dynamic_reference_slots")),
            "encoders": sorted(encoders)}


def detect_mode_from_template(caps, n_images):
    """从有效连线判模式（方案 §W1：不只看文件名或一个可选 socket）。"""
    if caps["ref_image_slots"]:
        return "ref2va", f"模板有 {caps['ref_image_slots']} 个 ref_images.* 槽"
    if caps["first_frame"] and caps["last_frame"]:
        if n_images >= 2:
            return "fl2va", f"模板有 first_frame+last_frame，本次 {n_images} 张图"
        if n_images == 1:
            return "i2va", "模板有 first_frame+last_frame，但本次只给 1 张（首帧）"
        return "t2va", "模板有 first_frame+last_frame，本次 0 张图"
    if caps["first_frame"]:
        return "i2va", "模板只有 first_frame"
    if caps["last_frame"]:
        return "l2va", "模板只有 last_frame"
    raise PlanError("模板里既没有 first_frame／last_frame，也没有 ref_images.* 槽 —— "
                    "不是 H3 出片模板（检查步骤里的 workflow 指向）")


# ------------------------------------------------------------------ 校验
def _check_formats_and_exist(paths, role, kinds):
    bad_ext, missing = [], []
    for p in paths:
        sp = Path(str(p))
        if sp.suffix.lower() not in kinds:
            bad_ext.append(str(p))
        if not sp.is_file():
            missing.append(str(p))
    if bad_ext:
        raise PlanError(f"{role} 混用格式：{bad_ext[:4]} —— 这里只收 "
                        f"{sorted(kinds)}，视频文件请走 ref_videos")
    if missing:
        raise PlanError(f"{role} 图形/files 不存在：{missing[:4]} —— "
                        f"先确认路径，或改用 --set 覆盖")


def check_mode_capacity(mode, n_images, n_videos, caps, meta=None, n_video_audios=0,
                        n_audios=0):
    """模式 × 素材槽的机械容量（提交前拦，不靠模板里留字面量去炸）。

    「这个模式现在有没有入口」由 registry 的 state 决定（meta），不在这里硬编码——
    否则 W1c 接线后要改代码，翻 state 无效（质量监督③ b）。
    W4c：Ref2VA 的 9/3/3/3 与"总文件 12""音频不可单独输入"在这里也判一遍——
    G4 量的是盘上真实文件，这里量的是计划里的数量与配对，两道口径必须一致。
    """
    meta = meta or {}
    state = str(meta.get("state") or "")
    if state == "pending_wiring":
        raise PlanError(f"{mode.upper()} 在 registry 里是「待接入」"
                        f"（{meta.get('basis') or '入口未接线'}）—— 选了也跑不出图")
    if state == "unfrozen_pending_entry" and not (meta.get("capability") or {}).get("template_wired"):
        raise PlanError(f"{mode.upper()} 已解冻但模板未接通"
                        f"（{meta.get('basis') or '入口由 W1c 接线'}）——"
                        f"现在选了也跑不出图；不是因未验证而禁用")
    if mode == "t2va" and n_images:
        raise PlanError(f"T2VA 不接图，收到 {n_images} 张 —— 要首帧用 I2VA、"
                        f"首尾用 FL2VA、只尾帧用 L2VA")
    if mode == "l2va" and n_images != 1:
        raise PlanError(f"L2VA 要恰好 1 张尾帧，收到 {n_images} 张")
    # 模板两端都接（真首尾帧）：少一张就是缺尾帧，**不许**自动降成单首帧继续
    # （dual 模板里第 2 个 LoadImage 会留 __REF2__ 字面量，提交必炸）。
    if caps["last_frame"] and not caps["ref_image_slots"] and n_images < 2 \
            and not caps.get("optional_keyframes"):
        raise PlanError(
            f"缺尾帧：模板同时接了 first_frame／last_frame（真首尾帧），"
            f"本次只有 {n_images} 张图 —— 补第 2 张尾帧；"
            f"或改用只有首帧的 I2VA 模板 (comfy/h3_i2v_fl2va_api.json)")
    if mode == "fl2va":
        if n_images < 2:
            raise PlanError(
                f"FL2VA 缺尾帧：模板同时有 first_frame／last_frame（真首尾帧），"
                f"本次只有 {n_images} 张图 —— 补第 2 张尾帧；"
                f"或改用只有首帧的 I2VA 模板 (comfy/h3_i2v_fl2va_api.json)")
        if n_images > 2:
            raise PlanError(f"FL2VA 只接 first/last 两张，收到 {n_images} 张 —— "
                            f"多出来的参考图请走 Ref2VA")
    if mode == "i2va":
        if n_images == 0:
            raise PlanError("0 张图：文生视频（T2VA）需要「首尾帧都可选」的模板，"
                            "现役模板都强制接首帧 —— W1c 接线后才有入口")
        if n_images != 1:
            raise PlanError(f"I2VA 要恰好 1 张首帧，收到 {n_images} 张"
                            + ("（多张请走 Ref2VA）" if n_images > 1 else ""))
    if mode == "ref2va":
        cap = caps["ref_image_slots"]
        dynamic = bool(caps.get("dynamic_reference_slots"))
        if not dynamic and n_images != cap:
            raise PlanError(f"Ref2VA 模板正好 {cap} 个参考图槽，收到 {n_images} 张 —— "
                            f"缺图会留字面量直接失败，多挂会被静默丢弃，两种都不许")
        if n_images > REF_CAPS["images"]:
            raise PlanError(f"Ref2VA 官方上限 {REF_CAPS['images']} 图，收到 {n_images} 张")
        if n_videos > REF_CAPS["videos"]:
            raise PlanError(f"Ref2VA 官方上限 {REF_CAPS['videos']} 段参考视频，收到 {n_videos} 段")
        if not dynamic and n_videos > caps["ref_video_slots"] and caps["ref_video_slots"]:
            raise PlanError(f"Ref2VA 模板只有 {caps['ref_video_slots']} 个参考视频槽，"
                            f"收到 {n_videos} 段")
        if not dynamic and n_videos and not caps["ref_video_slots"]:
            raise PlanError(f"Ref2VA 模板没有任何参考视频槽，却收到 {n_videos} 段 —— "
                            f"换带 ref_videos.* 的模板，或去掉视频只走参考图")
        if n_video_audios > REF_CAPS["video_audios"] or n_audios > REF_CAPS["audios"]:
            raise PlanError(f"Ref2VA 官方上限：参考片原声 {REF_CAPS['video_audios']}、"
                            f"独立音频 {REF_CAPS['audios']}；收到 "
                            f"{n_video_audios}＋{n_audios}")
        if n_video_audios > n_videos:
            raise PlanError(f"参考片原声 {n_video_audios} 段 > 参考视频 {n_videos} 段 —— "
                            f"`ref_video_audio_k` 只能挂在同号视频上")
        total = n_images + n_videos + n_audios
        if total > REF_TOTAL_FILES:
            raise PlanError(f"Ref2VA 官方上限：总文件 {total}"
                            f"（图＋视频＋独立音频；参考片原声随视频同文件）> {REF_TOTAL_FILES}")
        if not n_images and not n_videos and (n_audios or n_video_audios):
            raise PlanError("Ref2VA 官方口径：音频不能单独作为输入，必须与图像或视频同用")
    elif (n_video_audios or n_audios):
        raise PlanError(f"{mode.upper()} 不接参考音频（{n_video_audios}＋{n_audios} 段）—— "
                        f"参考音频只有 Ref2VA 通道有槽")


def check_recipe_pairing(mode, recipe):
    """task_type 与权重/LoRA 家族配对。硬拦只用于**已知会出事**的组合；
    其余未实测组合不拦，回填 `unverified` 风险标记（计划 §0.5）。"""
    lora = str(recipe.get("lora") or "").lower()
    steps = recipe.get("steps")
    if recipe.get("second_pass"):
        # W4a：R3 二采是 recipe，**不套单遍 8 步校验**——4+4 是分开的两段，
        # 基底 LoRA 必须是已验证那一支（pruned INT8 配 turbo4 alpha8 T8-convert）。
        if not ("4step" in lora and "alpha8" in lora):
            raise PlanError(
                "R3 二采的基底 LoRA 必须是 turbo4 alpha8-T8-convert 那一支（本次 "
                f"lora={recipe.get('lora')}）—— 剪枝 INT8 底模只配过这一支，"
                "换 LoRA 不是换口味，是换整套权重族")
        for k in ("base_steps", "coarse_steps", "refine_steps"):
            if recipe.get(k) in (None, ""):
                raise PlanError(f"R3 二采缺 {k}：4+4 的步数要显式声明，代码不代替人选")
        scale = recipe.get("scale")
        if scale in (None, ""):
            raise PlanError("R3 二采必须显式给 scale_by（1.0/1.25/2.0）")
        # S2：边界判据是**本批真实帧数**（2.0 在 11s/264 帧崩过），不是 base_steps。
        # 以前拿 base_steps 当代理，导致 124 帧×2.0 也被误拦；与 tasks.apply_two_pass 同一口径。
        frames = int(recipe.get("frames") or 0)
        if float(scale) >= 2.0 and frames >= 264 and not recipe.get("confirm_big_scale"):
            raise PlanError(f"scale_by=2.0 × {frames} 帧 落在已知崩溃边界"
                            f"（2.0 在 11s/264 帧崩过）—— "
                            f"要烧请显式 confirm_big_scale=true，否则降 1.25")
        return "verified(R3 二采 4+4，scale=%s)" % scale
    if lora and steps is not None:
        if "ref2v" in lora and int(steps) != 4:
            raise PlanError(f"4-step Ref2V LoRA 必须配 steps=4，本次 steps={steps} —— "
                            f"只改一边会让画质/时长整体漂移")
        if "fl2v" in lora and "8step" in lora and int(steps) != 8:
            raise PlanError(f"8-step FL2V LoRA 必须配 steps=8，本次 steps={steps}")
        if steps == 20:
            raise PlanError(f"20 步是「干净」配方（不挂 LoRA）的步数，本次却挂了 {recipe.get('lora')} —— "
                            f"要 LoRA 走 4/8 步配方，要 20 步请清空 lora")
    if mode == "ref2va" and lora and "ref2v" not in lora:
        raise PlanError(f"Ref2VA 通道要 Ref2V 家族权重，本次 lora={recipe.get('lora')}")
    if mode in ("i2va", "fl2va", "l2va", "t2va") and "ref2v" in lora:
        raise PlanError(f"{mode.upper()} 通道挂了 Ref2V 权重（{recipe.get('lora')}）—— "
                        f"通道与权重家族不匹配")
    known = (not lora and steps == 20) or ("ref2v" in lora and steps == 4) \
        or ("8step" in lora and steps == 8)
    return "verified" if known else "unverified(未实测组合，已在计划里标风险)"


def _sha256_text(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def _as_int(v):
    try:
        return None if v in (None, "") else int(float(v))
    except (TypeError, ValueError):
        return v


def _as_float(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return v


def _req_int(v, field, hint):
    """必需整数：缺失或非数字都抛可读 PlanError（不许漏成裸 ValueError traceback）。"""
    if v in (None, ""):
        raise PlanError(f"缺 {field}：{hint}")
    try:
        return int(float(v))
    except (TypeError, ValueError):
        raise PlanError(f"{field} 不是数字：{v!r} —— {hint}") from None


def _req_float(v, field, hint, default=None):
    if v in (None, ""):
        if default is not None:
            return float(default)
        raise PlanError(f"缺 {field}：{hint}")
    try:
        return float(v)
    except (TypeError, ValueError):
        raise PlanError(f"{field} 不是数字：{v!r} —— {hint}") from None


def _opt_float(v, field):
    """可选浮点：没给就是 None（不是 0），给了但非数字就报错。"""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise PlanError(f"{field} 不是数字：{v!r}") from None


def _recipe_id(recipe):
    lora = str(recipe.get("lora") or "").lower()
    steps = recipe.get("steps")
    if recipe.get("second_pass"):
        # R3 二采自成配方号：4+4 与放大倍率都在名字里，不与单遍 8 步混成一个"标准"
        return "r3-2p%s+%s_x%s" % (recipe.get("coarse_steps"), recipe.get("refine_steps"),
                                   recipe.get("scale"))
    if "ref2v" in lora:
        return f"ref2v{steps}"
    if "8step" in lora or (lora and steps == 8):
        return f"std{steps}"
    if not lora and steps == 20:
        return "clean20"
    return f"custom{steps}" if steps is not None else "unset"


# ------------------------------------------------------------------ registry
def _load_registry(engine_root):
    p = Path(engine_root) / "channels_registry.json"
    if not p.is_file():
        raise PlanError(f"channels_registry.json 不存在：{p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise PlanError(f"channels_registry.json 读不出（{type(e).__name__}: {e}）"
                        f"—— 先修坏 JSON，不要绕过") from e


def _orchestration_of(engine_root, workflow_name):
    """查这条流属于哪种编排：registry.orchestrations.*.flows 是唯一真源。

    查不到就报 unregistered（**不猜**）——以前靠名字里有没有 movie/batch 判，
    名字一漂就把无人值守批次当成单镜，摘要与审核点跟着错。
    """
    try:
        data = _load_registry(engine_root)
    except PlanError:
        return "unregistered", "registry 读不出"
    vals = ((data.get("orchestrations") or {}).get("values") or {})
    for key, spec in vals.items():
        if workflow_name in (spec.get("flows") or []):
            return key, f"registry.orchestrations.{key}.flows"
    return "unregistered", "registry.orchestrations 里没登记这条流"


def load_input_modes(engine_root):
    """读 registry 的 `input_modes` 段（唯一元数据真源；缺段/坏文件都抛可读错）。"""
    try:
        data = _load_registry(engine_root)
    except PlanError as e:
        raise PlanError(str(e) + " —— 模式元数据没有真源，拒绝解析") from None
    modes = ((data.get("input_modes") or {}).get("modes") or {})
    if not modes:
        raise PlanError("channels_registry.json 缺少 input_modes.modes 段 —— "
                        "模式别名/模板指针/能力状态没有真源，拒绝解析")
    return modes


def recipe_key(recipe):
    """把一份配方归到 registry.recipe_matrix 的列名上（归不了返回 None）。"""
    if recipe.get("second_pass"):
        return "r3_two_pass"
    lora = str(recipe.get("lora") or "").lower()
    steps = _as_int(recipe.get("steps"))
    if "ref2v" in lora:
        return "ref2v4"
    if not lora and steps == 20:
        return "clean20"
    if lora and steps == 8:
        return "single8"
    return None


def matrix_cell(engine_root, mode, recipe):
    """模式 × 配方 的格子状态：available／need_graph／not_applicable／未登记。

    W4c 的硬口径：**格子没有真实模板就不是"未验证"，是图形不存在**，必须停在提交前，
    并说清缺哪张图；`not_applicable` 也不能静默跑。
    """
    data = _load_registry(engine_root)
    cells = ((data.get("recipe_matrix") or {}).get("cells") or {})
    row = cells.get(mode) or {}
    key = recipe_key(recipe)
    if key is None:
        return {"state": "unregistered", "reason": "配方不归入矩阵列（自定义步数/权重）"}
    cell = row.get(key)
    if not cell:
        return {"state": "unregistered", "reason": f"registry.recipe_matrix 缺 {mode}×{key} 这格"}
    state = str(cell.get("state") or "")
    if state == "need_graph":
        raise PlanError(f"{mode.upper()} × {key} 需要新建图：{cell.get('reason') or '未写原因'}"
                        f" —— 这不是没验证过，是图形不存在，提交必失败")
    if state == "not_applicable":
        raise PlanError(f"{mode.upper()} × {key} 是**不该存在的格子**："
                        f"{cell.get('reason') or '官方/权重口径不适用'}")
    if state != "available":
        raise PlanError(f"{mode.upper()} × {key} 的格子状态读不懂：{state!r}"
                        f"（只允许 available/need_graph/not_applicable）")
    tpl = str(cell.get("template") or "")
    wf = str(cell.get("workflow") or "")
    if tpl and not (engine_root / tpl).is_file():
        raise PlanError(f"格子说模板是 {tpl}，但文件不存在 —— registry 在撒谎，先修 registry")
    if wf and not (engine_root / "workflows" / f"{wf}.yaml").is_file():
        raise PlanError(f"格子说工作流是 {wf}，但 YAML 不存在 —— registry 在撒谎")
    return {"state": state, "template": tpl, "workflow": wf, "note": cell.get("note") or ""}


def _detect_prompt_mode(prompt):
    """首行判模式的唯一真源在 tools/check_preflight（不在这里重写）。"""
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    try:
        from check_preflight import _detect_skeleton_mode
    except Exception:
        return None
    return _detect_skeleton_mode(prompt)


def audio_reading():
    """本批 Ref2VA 音频走**哪种读法**（唯一真源＝tools/h3_audio_policy.py，这里只转接）。

    为什么要在计划里显示：官方 README.zh-CN:85 说"音频一类 ≤3"，T8 节点却是"每类各 ≤3"，
    用户 10-24 08:15 裁定默认按节点放行、严格读法留成开关 ⇒ 开关一拨，6 段音频就合法了。
    这种事如果只写在注释里，事后根本查不到"当时按哪种读法跑的"（监督方 10-24 终局点名的缺口）。
    读法本身**不在这里实现第二份**；读不到模块就如实报 unknown，不猜"应该是默认档"。
    """
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    try:
        from h3_audio_policy import audio_reading_policy
    except Exception as e:
        return {"reading": "unknown", "strict": None,
                "label_cn": "读法取不到：%s（不猜，按未登记处理）" % type(e).__name__,
                "switch": "AW_H3_AUDIO_STRICT", "switch_value": "(读不到)"}
    return audio_reading_policy()


# ------------------------------------------------------------------ 主入口
PROMPT_KIND_OF_MODE = {"t2va": "h3_t2va", "i2va": "h3_i2va", "l2va": "h3_l2va",
                       "fl2va": "h3_fl2va", "ref2va": "h3_ref2va"}


def derive_prompt_kind(args, mode=None):
    """按 input_mode 派生 prompt_kind（**唯一映射处**，run.py 与解析器共用）。

    返回 (args, None) 或 (args, 错误文案)。没声明 input_mode 的流一律不动。
    """
    im = str((args or {}).get("input_mode") or mode or "").strip().lower()
    if not im:
        return args, None
    pk = PROMPT_KIND_OF_MODE.get(im)
    if not pk:
        return args, "input_mode 只认 %s，收到 %r" % (sorted(PROMPT_KIND_OF_MODE), im)
    args = dict(args or {})
    args["prompt_kind"] = pk
    return args, None


# 参数名写错时，YAML 的默认值会静默顶上（用户以为改了这一轴，其实没生效）。
# S2：只对**已知的近似错名**硬拦，不搞"任何未声明键都拒绝"——旧预设常靠 --set
# 传一些流里没声明的运行级键，全面拒绝会把兼容面打死。
_PARAM_NAME_HINTS = {
    "coarse_steps": "two_pass_coarse_steps",
    "refine_steps": "two_pass_refine_steps",
    "base_steps": "steps（第一遍步数）",
}


def _reject_misspelled_params(args, sources):
    for k in (args or {}):
        if str(k) in _PARAM_NAME_HINTS and (sources or {}).get(k) == "cli_explicit":
            raise PlanError(
                f"参数名 `{k}` 不会被这条工作流读取，传了也会静默用默认值 —— "
                f"要改这一轴请用 `{_PARAM_NAME_HINTS[str(k)]}`")


def build_run_plan(engine_root, workflow_name, wf, args, sources, cfg=None, tier="draft",
                   run_id=None, shot_id=None, attempt_id=None):
    """解析出一份 RunPlan（纯数据）。机械不可执行直接抛 PlanError。

    identity 由调用方传入（run.py 已算好 run_id；shot/attempt 是电影链的单镜维度，
    运行级解析时它们只能是 None，**不编造**）。
    """
    engine_root = Path(engine_root)
    args = dict(args or {})
    sources = dict(sources or {})
    cfg = cfg or {}
    _reject_misspelled_params(args, sources)

    images = list(args.get("ref_images") or args.get("refs") or [])
    videos = list(args.get("ref_videos") or args.get("videos_ref") or [])
    # W4c：Ref2VA 的两路音频（参考片原声／独立音频）进计划，不再只登记不判
    video_audios = list(args.get("ref_video_audios") or [])
    audios = list(args.get("ref_audios") or [])

    # ---- 版本 / 图形 ----
    wf_file = engine_root / "workflows" / f"{workflow_name}.yaml"
    tpl_rel = find_template(wf)
    if not tpl_rel:
        raise PlanError(f"工作流 {workflow_name} 里没有声明出片模板"
                        f"（步骤要写 workflow: comfy/*.json）")
    tpl_path = engine_root / tpl_rel
    if not tpl_path.is_file():
        raise PlanError(f"图形不存在：{tpl_rel} —— 该模板已删/改名，换现役模板或恢复文件")
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    caps = template_capabilities(tpl)

    # registry 是模式元数据的唯一真源（别名／模板指针／能力／状态／prompt_kind）
    registry = load_input_modes(engine_root)

    # ---- 输入模式 ----
    explicit = str(args.get("input_mode") or "").strip().lower()
    if explicit:
        if explicit not in registry:
            raise PlanError(f"input_mode 只认 {sorted(registry)}，收到 {explicit!r}")
        mode, basis = explicit, "explicit(args.input_mode)"
    else:
        mode, basis = detect_mode_from_template(caps, len(images))
    meta = registry.get(mode) or {}

    # 模式与模板能力必须自洽（socket + 编码器类名双证）
    # 可选/动态模板（W1c/W4c）例外：它本来就不静态摆满槽位，由 build_graph_video
    # 按实际素材注入 —— 拿静态连线去要求它，等于用旧口径判新图。
    flexible = bool(caps.get("optional_keyframes") or caps.get("dynamic_reference_slots")
                    or caps.get("keyframes_optional"))
    if mode == "ref2va" and not caps["ref_image_slots"] and not flexible:
        raise PlanError(f"选了 Ref2VA，但模板 {tpl_rel} 没有 ref_images.* 槽")
    if not flexible:
        if mode == "fl2va" and not (caps["first_frame"] and caps["last_frame"]):
            raise PlanError(f"选了 FL2VA，但模板 {tpl_rel} 缺 first_frame 或 last_frame")
        if mode == "i2va" and not caps["first_frame"]:
            raise PlanError(f"选了 I2VA，但模板 {tpl_rel} 没有 first_frame")
        if mode == "l2va" and not caps["last_frame"]:
            raise PlanError(f"选了 L2VA，但模板 {tpl_rel} 没有 last_frame")
    else:
        # 可选图也必须真有"帧图条件化"能力，否则 mode 无处可接
        if mode in ("i2va", "fl2va", "l2va") and not (caps["first_frame"]
                                                      or caps["last_frame"]):
            raise PlanError(f"{mode.upper()} 需要帧图条件化节点，但 {tpl_rel} 两端槽都没有 —— "
                            f"这不是可选图，换 comfy/h3_keyframes_optional_api.json "
                            f"或 comfy/h3_two_pass_modes_api.json")
    # 出片编码器：单遍/可选首尾帧走 MiniMaxH3ImageToVideo，R3 二采走
    # MiniMaxH3AudioConditioningT8（两种都是"按帧图条件化"的 H3 节点）；
    # Ref2VA 只认 ReferenceToVideo。列成集合而不是一个名字，免得把二采图误判成"图形不匹配"。
    # S2：Ref2VA × R3 二采的真实条件节点是 MiniMaxH3AudioConditioningT8（两遍），
    # 不是 ReferenceToVideo；只认后者会把 registry 已登记 available 的格子误拒。
    # 单遍 Ref2VA 仍只认 ReferenceToVideo，不能拿二采图冒充单遍参考链。
    if mode == "ref2va":
        _want_encoders = {"MiniMaxH3ReferenceToVideo"}
        if str(args.get("two_pass", "")).lower() in ("true", "1", "yes", "on"):
            _want_encoders.add("MiniMaxH3AudioConditioningT8")
    else:
        _want_encoders = {"MiniMaxH3ImageToVideo", "MiniMaxH3AudioConditioningT8"}
    if not (_want_encoders & set(caps["encoders"])):
        raise PlanError(f"{mode.upper()} 需要 {'/'.join(sorted(_want_encoders))} 节点，"
                        f"模板 {tpl_rel} 里没有 —— 通道与图形不匹配")

    # ---- 素材：格式、存在、槽位容量（入口可达性由 registry state 决定）----
    _check_formats_and_exist(images, "ref_images", IMAGE_EXT)
    _check_formats_and_exist(videos, "ref_videos", VIDEO_EXT)
    _check_formats_and_exist(video_audios, "ref_video_audios", AUDIO_EXT)
    _check_formats_and_exist(audios, "ref_audios", AUDIO_EXT)
    check_mode_capacity(mode, len(images), len(videos), caps, meta,
                        n_video_audios=len(video_audios), n_audios=len(audios))

    # S2：Ref2VA 的图是**参考图**，不是首帧/尾帧；以前把 images[0] 也算成
    # first_frame，计划和真图各说一套。首/尾帧只属于 I2VA／FL2VA／L2VA。
    first = images[0] if mode in ("i2va", "fl2va") and images else None
    last = images[1] if len(images) >= 2 and mode == "fl2va" else (
        images[0] if mode == "l2va" and images else None)
    references = images if mode == "ref2va" else []

    materials = {
        "first_frame": first,
        "last_frame": last,
        "references": references,
        "ref_videos": videos,
        "ref_video_audios": video_audios,
        "ref_audios": audios,
    }

    # ---- 配方 ----
    # 数值统一在这里归一（int/float），保证 CLI（--set 全是字符串）与面板
    # （已是数值）解析出**同一份** RunPlan —— V1-1 的逐字段相等靠这一步。
    recipe = {
        "recipe_id": None,
        "steps": _req_int(args.get("steps"), "steps", "步数是配方的一等字段，且要与 LoRA 家族配对"),
        "sigmas": args.get("sigmas"),
        "sampler": args.get("sampler"),
        "shift": {"video": _opt_float(args.get("shift_video"), "shift_video"),
                  "audio": _opt_float(args.get("shift_audio"), "shift_audio")},
        "lora": args.get("lora"),
        "lora_strength": _opt_float(args.get("lora_strength"), "lora_strength"),
        "lora2": args.get("lora2"),
        "lora2_strength": _opt_float(args.get("lora2_strength"), "lora2_strength"),
        # Bunny 只在真挂了增强 LoRA 时才有值；lora2 为空 ⇒ None（显示"未选"），
        # 不能因为 YAML 里写着 bunny_strength: 0.5 就显示成"这批开了 Bunny"。
        "bunny": (_opt_float(args.get("bunny_strength"), "bunny_strength")
                  if str(args.get("lora2") or "").strip() else None),
        "bunny_lora": (str(args.get("lora2")).strip() if str(args.get("lora2") or "").strip()
                       else None),
        "second_pass": bool(args.get("two_pass")),
        # W4a：二采是 recipe 的字段，不是 input_mode——4+4 与放大倍率分开记，
        # 不复用单遍的 steps 掩盖真实步数。
        # S2：2.0 崩溃边界按真实帧数（frames）判，和 builder 同一口径。
        "frames": _as_int(args.get("length")),
        "base_steps": _as_int(args.get("steps")),
        "coarse_steps": _as_int(args.get("two_pass_coarse_steps")),
        "refine_steps": _as_int(args.get("two_pass_refine_steps")),
        "scale": _as_float(args.get("scale_by")),
        "confirm_big_scale": bool(args.get("confirm_big_scale")),
    }
    recipe["recipe_id"] = _recipe_id(recipe)
    recipe["pairing"] = check_recipe_pairing(mode, recipe)
    # W4c：模式 × 配方必须有真实格子。need_graph＝图形不存在（不是"没验证"），
    # not_applicable＝不该存在的格子；两种都停在提交前并说清缺什么。
    cell = matrix_cell(engine_root, mode, recipe)
    recipe["matrix"] = cell

    # ---- 几何 ----
    w, h = args.get("width"), args.get("height")
    if w in (None, "") or h in (None, ""):
        raise PlanError("缺画布尺寸：width/height 必须由人显式给（10-03 裁定："
                        "画布是创作决定，代码不代填默认值）")
    base_w = _req_int(w, "width", "画布宽度必须是整数像素")
    base_h = _req_int(h, "height", "画布高度必须是整数像素")
    fps = _req_float(args.get("fps"), "fps", "帧率必须是数字", default=24)
    scale = _req_float(args.get("scale_by"), "scale_by", "缩放必须是数字", default=1.0)
    frames = _req_int(args.get("length"), "length",
                      "H3 必须显式给帧数，不接受模板默认值代填")
    geometry = {
        "base_width": base_w, "base_height": base_h,
        "requested_frames": frames,
        "resolved_frames": frames,
        "fps": fps,
        "scale": scale,
        # S2：这是**估算**，不是实测像素。二采放大节点 size_mode=scale_by、
        # aspect_policy=preserve_source；latent 对齐后的真实像素可能不同，
        # 出片后必须用 probe_video 的实测回填，不能拿这行当"实际尺寸"。
        "expected_high": [int(round(base_w * scale)), int(round(base_h * scale))],
        "expected_high_basis": ("estimate:base×scale（节点 scale_by/preserve_source；"
                                "未实测，真实像素以出片 probe 为准）"),
        "delivery": {"crop": args.get("crop"), "size": args.get("out_size")},
    }

    # ---- 文本 ----
    # prompt_kind 由模式**派生**（唯一映射处 derive_prompt_kind，CLI 与解析器共用）：
    # YAML/前端再写一份就会和 input_mode 漂；G7 判首行用的就是这个词。
    args, _pk_err = derive_prompt_kind(args, mode)
    if _pk_err:
        raise PlanError(_pk_err)
    prompt_file = str(args.get("prompt_file") or "")
    prompt_inline = str(args.get("prompt") or "")
    src_prompt, src_sha, src_kind = prompt_inline, _sha256_text(prompt_inline), "inline"
    if prompt_file:
        pf = Path(prompt_file)
        if not pf.is_file():
            raise PlanError(f"提示词文件不存在：{prompt_file}")
        src_prompt = pf.read_text(encoding="utf-8", errors="replace")
        src_sha, src_kind = _sha256_text(src_prompt), "file"
    if not src_prompt.strip():
        raise PlanError("提示词为空：prompt 与 prompt_file 至少要给一个")
    detected = _detect_prompt_mode(src_prompt)
    if detected and detected != mode:
        raise PlanError(
            f"提示词首行是 {detected.upper()} 口径，但本次解析出的模式是 {mode.upper()} —— "
            f"换提示词，或把 input_mode/素材槽改成与首行一致（G7 会拦混用）")

    text = {
        "source_prompt": {"path": prompt_file or None, "sha256": src_sha, "origin": src_kind},
        "compiled_prompt": None,            # 运行期由 W2 编译链产出；--inspect 只解析不编译
        "compile_mode": ("enforced(W2：原稿快照→批次目录 compiled_<run_id>.txt→"
                         "compile_check 提交前复核；--inspect 阶段未编译)"
                         if str(meta.get("prompt_kind") or "") else "enforced(W2)"),
        "compiler_version": None,
        "prompt_kind": str(meta.get("prompt_kind") or ""),
        "declared_prompt_kind": args.get("prompt_kind"),
        "detected_skeleton_mode": detected,
    }

    # ---- 声音 ----
    sound = {
        "requested_audio": args.get("enable_audio"),
        "audio_mode": args.get("audio_mode"),
        "exported": None,
        "postprocess": args.get("audio_post"),
        "audio_present": None,             # 出片后实测回填
    }

    # ---- 流程 ----
    # W4b：编排以 registry.orchestrations 的 flows 表为真源，不再靠工作流**名字**猜
    # （"名字里带 _play 是参数预设不是档位"踩过同一条坑：命名一漂，判据就错）。
    flow_key, flow_basis = _orchestration_of(engine_root, workflow_name)
    flow = {
        "orchestration": flow_key,
        "orchestration_basis": flow_basis,
        "execution_tier": str(tier or "draft"),
        "approval_basis": {
            "preflight_strict": str(cfg.get("preflight_strict", "off")),
            "preflight": str(cfg.get("preflight", "on")),
        },
        "retry": args.get("retry"),
        "degrade_allowed": bool(args.get("allow_degrade")),
    }

    versions = {
        "yaml": {"path": f"workflows/{workflow_name}.yaml",
                 "sha256": _sha256_text(wf_file.read_text(encoding="utf-8")) if wf_file.is_file() else None},
        "template": {"path": tpl_rel,
                     "sha256": hashlib.sha256(tpl_path.read_bytes()).hexdigest()},
        "builder": "tasks.build_graph_video",
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {"run_id": run_id, "shot_id": shot_id, "attempt_id": attempt_id,
                     "project": str(cfg.get("project") or ""),
                     "workflow": workflow_name},
        "inputs": {"input_mode": mode, "mode_basis": basis,
                   "materials": materials,
                   "counts": {"images": len(images), "videos": len(videos),
                              "video_audios": len(video_audios), "audios": len(audios),
                              "total_files": len(images) + len(videos)
                                             + len(video_audios) + len(audios)},
                   "template_capabilities": caps},
        "recipe": recipe,
        "geometry": geometry,
        "text": text,
        "sound": sound,
        "flow": flow,
        "versions": versions,
        "execution": {"submit_intent": None, "prompt_id": None,
                      "states": [], "outputs": [], "measured": None, "error_class": None},
        "sources": sources,
        "audio": audio_reading(),
        "registry": {"state": meta.get("state"), "aliases": meta.get("aliases") or [],
                     "capability": meta.get("capability") or {}},
    }


def render_summary(plan):
    """人读摘要：一眼看清模式／素材／模板／配方／几何／档位／风险。"""
    if not plan:
        return "（空计划）"
    it = plan["inputs"]
    m = it["materials"]
    r = plan["recipe"]
    g = plan["geometry"]
    f = plan["flow"]
    lines = [
        f"RunPlan v{plan['schema_version']} · {plan['identity']['workflow']}"
        f" · 项目 {plan['identity']['project'] or '-'}",
        f"  模式   {it['input_mode'].upper()}（依据：{it['mode_basis']}）",
        f"  素材   首帧={m['first_frame'] or '-'}  尾帧={m['last_frame'] or '-'}"
        f"  参考图={len(m['references'])}  参考视频={len(m['ref_videos'])}",
        f"  模板   {plan['versions']['template']['path']}（first/last/ref 槽："
        f"{it['template_capabilities']['first_frame']}/"
        f"{it['template_capabilities']['last_frame']}/"
        f"{it['template_capabilities']['ref_image_slots']}）",
        f"  配方   {r['recipe_id']} · steps={r['steps']} · LoRA={r['lora'] or '-'}"
        f"@{r['lora_strength']} · Bunny={r['bunny'] if r['bunny'] is not None else '未选'}",
    ]
    if r.get("second_pass"):
        # 二采要按真实值显示：4+4 两段步数与放大倍率，不用"标准 8 步"糊过去
        lines.append(f"  二采   R3 · base={r.get('base_steps')} + coarse={r.get('coarse_steps')}"
                     f" + refine={r.get('refine_steps')} · scale_by={r.get('scale')}"
                     f"{' · 已确认撞 2.0 崩溃边界' if r.get('confirm_big_scale') else ''}")
    lines += [
        f"  几何   {g['base_width']}x{g['base_height']} × {g['requested_frames']}帧"
        f" @{g['fps']}fps · scale={g['scale']}",
        f"  文本   kind={plan['text']['prompt_kind']} · 源稿 sha256={plan['text']['source_prompt']['sha256'][:12]}…"
        f" · 编译={plan['text']['compile_mode']}",
        f"  流程   {f['orchestration']} · tier={f['execution_tier']} · "
        f"降级={'允许' if f['degrade_allowed'] else '禁止'}",
        f"  格子   {plan['recipe'].get('matrix', {}).get('state') or '-'}"
        f"（{it['input_mode'].upper()} × "
        f"{recipe_key(plan['recipe'])}）· "
        f"模板 {plan['recipe'].get('matrix', {}).get('template') or plan['versions']['template']['path']}",
        f"  音频   {plan.get('audio', {}).get('label_cn') or '（读不到口径模块）'}"
        f" ｜开关 {plan.get('audio', {}).get('switch', 'AW_H3_AUDIO_STRICT')}="
        f"{plan.get('audio', {}).get('switch_value', '?')}"
        f" ｜出处 {plan.get('audio', {}).get('official_source', 'README.zh-CN:85')}",
        f"  状态   {plan['registry'].get('state') or '-'}（未提交；本命令只解析）",
    ]
    return "\n".join(lines)
