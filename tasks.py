# -*- coding: utf-8 -*-
"""任务模块注册表。

新增任务类型：写一个函数，用 @task("名字") 注册即可被工作流 YAML 使用。
函数签名 fn(params: dict, ctx: dict) -> dict（结果可被后续步骤用 {{step_id.field}} 引用）。

ctx 可用键：cfg(全局配置) / args(工作流参数) / run_id / log(日志函数) / wf_root(本目录)。
"""
import base64
import copy
import fnmatch
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import requests

import task_state

REGISTRY = {}


def task(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def log(ctx, msg):
    ctx["log"](msg)


# 本机服务一律直连：trust_env=False 无视代理环境变量与 Windows 注册表代理，
# 防止 Clash 等系统代理把 127.0.0.1 请求劫持到远端节点导致探活全挂（2026-09-04 事故）
SESSION = requests.Session()
SESSION.trust_env = False
_LAST_HTTP_ERR = ""


def http_ok(url, timeout=2):
    try:
        return SESSION.get(url, timeout=timeout).status_code == 200
    except Exception as e:
        global _LAST_HTTP_ERR
        _LAST_HTTP_ERR = f"{type(e).__name__}: {str(e)[:150]}"
        return False


def img_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def img_is_blank(path):
    """尺寸对但整幅近乎纯色 = 模型没画出内容，不能算成功产物。"""
    from PIL import Image
    with Image.open(path) as im:
        lo, hi = im.convert("L").resize((32, 32)).getextrema()
    return hi - lo < 12


# ---------------------------------------------------------------- llm
def ensure_llm(ctx, key):
    m = ctx["cfg"]["models"][key]
    if not m.get("remote"):
        raise RuntimeError(f"{key}: 非云端后端，已不再支持本地模型")
    return True


@task("llm")
def t_llm(p, ctx):
    """云端 LLM 调用 + 兜底链。params: backend(auto|名字|逗号列表) / system /
    prompt / max_tokens / temperature / timeout / enabled / static /
    read_from(读该文件内容当作用户消息，如回写 prompt_file 前的中文稿) /
    write_to(结果回写该文件，translate 步把英文稿写回 prompt_file) /
    skip_if_no_cjk(正文扣除 <d> 台词后无中文字符则不调模型、原样放行——纯英文稿不白花钱)

    enabled=false 时不调模型，直接把 static 当结果返回 —— 预留接口但不接上，
    下游 {{步骤.text}} 照常可用。
    """
    if str(p.get("enabled", True)).lower() in ("false", "0", "no"):
        txt = str(p.get("static", ""))
        log(ctx, f"[llm] enabled=false，跳过模型调用，直接用 static（{len(txt)} 字符）")
        return {"text": txt, "backend": "static", "elapsed": 0.0}
    original = ""
    rf = str(p.get("read_from") or "")
    if rf:
        rfp = Path(rf)
        if not rfp.is_file():
            raise RuntimeError(f"read_from 文件不存在: {rfp}")
        original = rfp.read_text(encoding="utf-8", errors="replace").strip()
    if str(p.get("skip_if_no_cjk", "")).lower() in ("true", "1", "yes"):
        body = re.sub(r"<d>.*?</d>", "", original, flags=re.S)  # 台词豁免同 G7
        if not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]", body):
            log(ctx, f"[llm] 正文无中文字符，按 skip_if_no_cjk 原样放行"
                     f"（{len(original)} 字符），不调模型")
            return {"text": original, "backend": "passthrough", "elapsed": 0.0}
    cfg = ctx["cfg"]
    backend = str(p.get("backend", "auto"))
    if backend == "auto":
        chain = list(cfg.get("fallback_chain") or [])
    else:
        chain = [b.strip() for b in backend.split(",") if b.strip()]
    errors = []
    for key in chain:
        m = cfg["models"].get(key)
        if not m:
            errors.append(f"{key}: config.yaml 无此后端")
            continue
        try:
            if not ensure_llm(ctx, key):
                errors.append(f"{key}: 启动超时")
                continue
            msgs = []
            if p.get("system"):
                msgs.append({"role": "system", "content": str(p["system"])})
            user_msg = original if original else str(p.get("prompt", ""))
            msgs.append({"role": "user", "content": user_msg})
            body = {"model": m["name"], "messages": msgs,
                    "max_tokens": int(p.get("max_tokens", 512)),
                    "temperature": float(p.get("temperature", 0.7))}
            headers = {}
            if m.get("remote"):
                env_key = m.get("api_key_env")
                api_key = os.environ.get(env_key, "") if env_key else ""
                if not api_key:
                    errors.append(f"{key}: 未设置 {env_key}（网页「云端 API 设置」里填）")
                    continue
                headers["Authorization"] = f"Bearer {api_key}"
            t0 = time.time()
            r = SESSION.post(m["base_url"].rstrip("/") + "/v1/chat/completions",
                              json=body, timeout=int(p.get("timeout", 300)),
                              headers=headers)
            if r.status_code != 200:
                errors.append(f"{key}: HTTP {r.status_code} {r.text[:120]}")
                continue
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                # LLM 偶尔把结果裹进 markdown 围栏；G7 对首行逐字比对，围栏必须剥掉
                text = re.sub(r"^```[\w-]*\n?", "", text)
                text = re.sub(r"\n?```\s*$", "", text).strip()
            wt = str(p.get("write_to") or "")
            if wt:
                wfp = Path(wt)
                wfp.parent.mkdir(parents=True, exist_ok=True)
                wfp.write_text(text, encoding="utf-8")  # 无 BOM，与 speak-ui 落盘同口径
                log(ctx, f"[llm] 结果已回写 {wfp}（{len(text)} 字符）")
            el = round(time.time() - t0, 1)
            log(ctx, f"[llm] 由 {key} 服务（{el}s, {len(text)} 字符）")
            return {"text": text, "backend": key, "elapsed": el}
        except Exception as e:
            errors.append(f"{key}: {type(e).__name__} {str(e)[:120]}")
    raise RuntimeError("兜底链全部失败: " + " | ".join(errors))


# ---------------------------------------------------------------- vision 判分
VL_KEY_FILE = Path("E:/密钥文件/阿里多模态.txt")


# ── 审美判分与闭环自动出图：已退役（2026-11-04 用户裁「所有带美学判定的都交给人来判，
#      机器只负责能实际判定的缺陷」）───────────────────────────────────────────
# 摘掉的本体：`vl_score_image`（云端 VL 给单图打 0-100 分＋扣分理由）与
# `@task("auto")` 的闭环（出图 → VL 判分 → 分数不到 threshold 就自动改写提示词重跑，
# 轮尽后**交回分数最高的那一轮**）。它两处都在替人做审美裁断：一处判"好不好"，
# 一处按这个判断选片。正身逐行在 `backups/_治理_20261104/归档件/审美判定退役_20261104/tasks_py_退役前.py`
# （md5 8b82b4ca32f583b17f2f6e3273e883d3；引擎里那两个 .bak 是同一份东西的第二副本，11-04 已合并掉）。
# 为什么现在才摘干净：2026-10-19 D20 那次裁定"美学判断交给人眼三分类审片"，
# 但只摘了 `@task("vl_aesthetic")` 的注册、函数体故意留着"等用户在场再裁"——
# 一个不在注册表里、却仍在模块里的判分器，下一个 agent 读到就能直接调。这次连本体一起走。
# 支撑证据两条，都是本机实测：① 11-04 七批离线复核，五种"批内画风尺"取法零分离
#   （`D:/AIWorkflow/tmp/_ruler_probe/`）；② LAION 美学分被用户实圈 36 张否掉
#   （可用组 9.34 vs 不可用组 9.60，AUC 0.374，方向还是反的）。
# 保留的事实型核查不动：`vl_content_check`／`t_vl_qc`（谁在场／动作／武器／有无瑕疵）、
# `_batch_consistency_qc`（批内**身份**尺：同人同装，可测）。
# 替代路径写在桩里，别自己猜。

_TOMB_AUTO = ("[任务已退役] auto（闭环自动出图：AI 判分 → 自动改写 → 自动选最优轮）\n"
              "⇒ 退役：2026-11-04 用户裁定「审美判定一律交给人，机器只判可实际判定的缺陷」\n"
              "⇒ 原因：这条链的驱动力是云端 VL 的 0-100 美学分——判「好不好」和选「哪一轮」都是机器在裁；"
              "而美学分在本机两次被证伪（11-04 七批五种取法零分离；LAION 美学分 AUC 0.374 比随机差）\n"
              "⇒ 替代：出草稿交人挑 —— py run.py image_draft_batch --set theme=<主题> --set count=<张数>；"
              "挑中后精修 —— py run.py image_refine --set manifest=<那份草稿 manifest> --set pick=<编号>\n"
              "⇒ 要恢复：正身在 backups/_治理_20261104/归档件/审美判定退役_20261104/"
              "tasks_py_退役前.py（与本文件逐行可对），把注册为 'auto' 的那段贴回即可，"
              "但那是改判据，需人重新裁")

_TOMB_AESTH = ("[任务已退役] vl_aesthetic（五维美学打分＋改进句）\n"
               "⇒ 退役：2026-11-04 同上裁定（2026-10-19 D20 已摘注册，这次连函数体一起摘）\n"
               "⇒ 原因：构图／光影／色彩／纵深／冲击五个维度全是审美；且它长期空转"
               "（VL key 文件不存在 ⇒ 恒 no-op，却照样在报告里显示「这一步已完成」）\n"
               "⇒ 替代：人眼三分类审片（审片站 approved／flagged／rejected ＋ 飞书目审）；"
               "要事实在场核查用 vl_qc（谁在场／动作／瑕疵）\n"
               "⇒ 要恢复：见上方归档件同一条路径")


@task("auto")
def t_auto(p, ctx):
    """路障桩：不跑闭环，只把原因、替代命令、恢复步骤打全。"""
    raise RuntimeError(_TOMB_AUTO)


@task("vl_aesthetic")
def t_vl_aesthetic(p, ctx):
    """路障桩：见上。注册留着是为了**报错报得清楚**，不是为了能被跑。"""
    raise RuntimeError(_TOMB_AESTH)


# ---------------------------------------------------------------- comfyui
def parse_loras(v):
    """LoRA 两种写法：YAML 里的 [{name, strength}] 列表，或命令行字符串
    "flux/A.safetensors:0.8,flux/B.safetensors"（--set 传不了列表）。
    带盘符的路径里有冒号，只有冒号后能转成 float 才当 strength。"""
    if not v or str(v).strip() in ("", "None", "[]"):
        return []
    if isinstance(v, list):
        return v
    out = []
    for part in str(v).split(","):
        part = part.strip()
        if not part:
            continue
        head, sep, tail = part.rpartition(":")
        try:
            out.append({"name": head if sep else part,
                        "strength": float(tail) if sep else 1.0})
        except ValueError:
            out.append({"name": part, "strength": 1.0})
    return out


TOMBSTONE_KEY = "_OFFICIAL-PATH-TOMBSTONE"


def load_template(ctx, rel):
    """模板加载的**唯一入口**（2026-10-19 第⑫条(b)）。

    读到退役桩就停下把确切原因与替代方案打出来，**不许调用方自己猜**——
    「拿到 FileNotFoundError 就换个像的模板」正是『每个 agent 用法都不一样』的成因之一。
    桩的形状：`{"_OFFICIAL-PATH-TOMBSTONE": "v1-json", "_退役": …, "_原因": …, "_替代": …, "_恢复": …}`，
    由 `backups/_治理_20261019/retire_flux_templates_20261019.py` 生成。
    """
    path = Path(ctx["wf_root"]) / str(rel)
    tpl = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(tpl, dict) and str(tpl.get(TOMBSTONE_KEY, "")).startswith("OFFICIAL-PATH-TOMBSTONE"):
        raise RuntimeError(
            "[模板已退役] %s\n%s\n⇒ 正身： %s\n⇒ 原因： %s\n⇒ 替代： %s\n⇒ 要恢复： %s"
            % (rel, tpl.get(TOMBSTONE_KEY),
               tpl.get("_归档在哪", "见 engine/comfy/ 下的退役声明牌"),
               tpl.get("_原因", "未写"), tpl.get("_替代", "未写"), tpl.get("_恢复", "未写")))
    return tpl


def build_graph(tpl, p, seed):
    g = copy.deepcopy(tpl)
    prompt = str(p.get("prompt", "")).strip()
    if not prompt or prompt == "None":
        raise ValueError("提示词为空或为字面量 \"None\"，拒绝提交（会白跑一趟 GPU）。"
                         "检查 YAML 里 prompt 引用的上游步骤是否产出了文本。")
    # LoRA 链注入：KSampler 的 model 输入改挂 LoraLoaderModelOnly 链
    loras = parse_loras(p.get("loras"))
    kss = [k for k, v in g.items() if v["class_type"] == "KSampler"]
    if len(kss) != 1:
        raise ValueError(f"模板需恰好 1 个 KSampler 才能挂 LoRA/注入参数，实际 {len(kss)} 个")
    ks = kss[0]
    src = g[ks]["inputs"]["model"]
    for i, l in enumerate(loras, 1):
        g[f"lora_{i}"] = {"class_type": "LoraLoaderModelOnly",
                          "inputs": {"lora_name": str(l["name"]).replace("/", "\\"),
                                     "strength_model": float(l.get("strength", 1.0)),
                                     "model": src}}
        src = [f"lora_{i}", 0]
    g[ks]["inputs"]["model"] = src
    rep = {"__PROMPT__": prompt, "__SEED__": int(seed),
           "__STEPS__": int(p.get("steps", 28)),
           "__GUIDANCE__": float(p.get("guidance", 3.5)),
           "__PREFIX__": str(p.get("prefix", "wf"))}
    # scale_by：把 YAML 声明的成品尺寸折算成基图尺寸注入模板。
    # 模板带放大节点（如一步式的 UpscaleModelLoader 4x）时，YAML 的 width/height
    # 写的是最终产物尺寸，KSampler 仍用基图 latent；否则尺寸闸门会把"放大后的
    # 产物"判为 ≠ 请求尺寸而误报失败。
    base_w, base_h = _explicit_size(p, {}, "出图模板（build_graph）")
    scale = float(p.get("scale_by", 1.0) or 1.0)
    if scale != 1.0:
        # 模板带放大节点时，YAML 声明的成品尺寸 → 基图尺寸注入 KSampler
        base_w = max(1, round(base_w / scale))
        base_h = max(1, round(base_h / scale))
    rep["__W__"] = base_w
    rep["__H__"] = base_h

    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str) and v in rep:
            return rep[v]
        return v
    return walk(g)

# ---------------------------------------------------------------- 可选首尾帧（W1c／W4c）
_KEYFRAME_MODES = ("t2va", "i2va", "l2va", "fl2va")
# 两种"按帧图条件化"的 H3 节点：单遍走 ImageToVideo，R3 二采走 AudioConditioningT8。
_H3_CONDITIONERS = ("MiniMaxH3ImageToVideo", "MiniMaxH3AudioConditioningT8")
# 每个模式要哪几帧槽；Ref2VA 不在这里，它走素材槽注入（apply_reference_materials）
_SLOT_NEEDS = {"t2va": (), "i2va": ("first_frame",), "l2va": ("last_frame",),
               "fl2va": ("first_frame", "last_frame")}


def _loadimage_of(graph, link):
    """link=[node_id, slot] -> (node_id, node)；只认上游是 LoadImage 的帧源。"""
    if not (isinstance(link, list) and link and str(link[0]) in graph):
        return None, None
    nid = str(link[0])
    node = graph[nid]
    if str(node.get("class_type") or "") != "LoadImage":
        return None, None
    return nid, node


def _free_node_id(graph, start=310):
    taken = {int(n) for n in graph if str(n).isdigit()}
    nxt = start
    while nxt in taken:
        nxt += 1
    return str(nxt)


def apply_keyframe_mode(graph, mode, n_refs, optional=None):
    """按 input_mode 把首尾帧槽对齐到实际素材：该接的接上、用不到的整节摘掉。

    计划 W1c：T2VA 0 张 / I2VA 1 张首帧 / L2VA 1 张尾帧 / FL2VA 首尾各 1 张。
    W4c 起同一套逻辑也管 R3 二采图（条件化节点是 MiniMaxH3AudioConditioningT8），
    所以这里遍历**所有**条件化节点而不是只挑第一个：二采有两遍条件化，两遍都要带帧。
    `optional=None` 时读模板 `_meta.keyframes_optional`；老模板没标就按静态连线判，
    静态缺哪一端就明确报错 —— 绝不让 __REF2__ 之类字面量被送进渲染。
    """
    mode = str(mode or "").strip().lower()
    if mode not in _KEYFRAME_MODES:
        raise ValueError(f"input_mode 只认 {list(_KEYFRAME_MODES)}，收到 {mode!r}")
    hosts = [(nid, node) for nid, node in graph.items()
             if str(node.get("class_type") or "") in _H3_CONDITIONERS]
    if not hosts:
        return graph                      # 不是帧图条件化（如静态 Ref2VA），不在这里改
    if optional is None:
        optional = bool(((graph.get("_meta") or {}).get("keyframes_optional")))
    static = {slot for _nid, node in hosts for slot in ("first_frame", "last_frame")
              if slot in (node.get("inputs") or {})}
    if not optional and not static:
        return graph                      # 旧模板本来就没有帧槽（不该发生），原样交给它
    if not optional and set(_SLOT_NEEDS[mode]) - static:
        miss = "、".join(sorted(set(_SLOT_NEEDS[mode]) - static))
        raise ValueError(f"{mode.upper()} 需要 {miss} 槽，模板里没有这一端且没标可选 —— "
                         f"单遍换 comfy/h3_keyframes_optional_api.json，"
                         f"二采换 comfy/h3_two_pass_modes_api.json")
    want = _SLOT_NEEDS[mode]
    want_n = {"t2va": 0, "i2va": 1, "l2va": 1, "fl2va": 2}[mode]
    if n_refs != want_n:
        need = {"t2va": "0 张（文生视频）", "i2va": "恰好 1 张首帧",
                "l2va": "恰好 1 张尾帧", "fl2va": "首帧+尾帧 2 张"}[mode]
        raise ValueError(f"{mode.upper()} 需要 {need}，收到 {n_refs} 张 —— "
                         f"缺图/多图在提交前拦住，不把字面量送去渲染")

    # 先清空所有条件化节点的帧槽链接，把还能复用的 LoadImage 按占位符收下来
    spare = {}
    for _hid, hnode in hosts:
        ins = hnode.setdefault("inputs", {})
        for slot in ("first_frame", "last_frame"):
            fid, fnode = _loadimage_of(graph, ins.pop(slot, None))
            if fid:
                spare[str(fnode["inputs"].get("image"))] = fid
    for placeholder, fid in list(spare.items()):
        graph.pop(fid, None)
        spare.pop(placeholder)
    # 帧槽 ↔ 占位符的对应由模式决定（L2VA 的唯一一张就是尾帧；T2VA 一个都不接）
    mapping = {}
    if mode == "i2va":
        mapping = {"first_frame": "__REF1__"}
    elif mode == "l2va":
        mapping = {"last_frame": "__REF1__"}
    elif mode == "fl2va":
        mapping = {"first_frame": "__REF1__", "last_frame": "__REF2__"}
    made = {}
    for slot, placeholder in mapping.items():
        nid = spare.get(placeholder)
        if nid is None:
            nid = _free_node_id(graph)
            graph[nid] = {"class_type": "LoadImage", "inputs": {"image": placeholder}}
        made[placeholder] = nid
    for _hid, hnode in hosts:
        ins = hnode.setdefault("inputs", {})
        for slot in want:
            ins[slot] = [made[mapping[slot]], 0]
    return graph


# ---------------------------------------------------------------- 二采 R3（W4a）
_TWO_PASS_PLAN_NODE = "MiniMaxH3LearnedTwoPassParityPlanT8Advanced"


def apply_two_pass(g, p):
    """把 R3 二采（pruned INT8＋turbo4 alpha8＋learned latent upscale）的声明参数落到图上。

    计划 W4a：**二采是 recipe，不是第六种 input_mode**。这里只做三件事——
      ① 校验这份模板确实是二采图（没有 parity-plan 节点就明说换模板，不静默当单遍跑）；
      ② `scale_by` 必须显式给（不混函数默认/CLI 默认），2.0 撞已知崩溃边界要一次确认；
      ③ 可选 Bunny 增强：给了 `lora2` 才插 5b（与已验证 runner `run_tp_fast.build_graph` 同构），
         没给就是中性日用，图上一个 Bunny 节点都不留。
    → 返回 (graph, rep_updates)
    """
    plan_node = None
    base_lora_node = None
    for nid, node in g.items():
        ct = str(node.get("class_type") or "")
        if ct == _TWO_PASS_PLAN_NODE:
            plan_node = nid
        if ct in ("LoraLoaderBypassModelOnly", "LoraLoaderModelOnly") \
                and str((node.get("inputs") or {}).get("lora_name") or "") == "__LORA__":
            base_lora_node = base_lora_node or nid
    if plan_node is None:
        raise ValueError("这份模板不是二采图（找不到 %s）—— "
                         "要用 R3 请指向 comfy/h3_two_pass_api.json，"
                         "单遍模板 comfy/h3_i2v_fl2va_api.json 请去掉 two_pass"
                         % _TWO_PASS_PLAN_NODE)
    if "__LEN__" not in json.dumps(g, ensure_ascii=False):
        raise ValueError("二采模板缺少 __LEN__/__W__/__H__ 占位，参数进不去就是模板被改坏了")

    scale = p.get("scale_by")
    if scale in (None, ""):
        raise ValueError("二采必须显式给 scale_by（1.0=不放大／1.25=日用中性默认／2.0=原 D 档）——"
                         "代码不代替人选放大倍率，历史事故都是这么攒出来的")
    scale = float(scale)
    frames = int(p.get("length") or 0)
    if scale >= 2.0 and frames >= 264:
        # 已知崩溃边界（10-21 实测 2.0 在 11s/264 帧崩过）：不静默拦，也不假装没发生。
        if str(p.get("confirm_big_scale", "")).lower() not in ("true", "1", "yes", "on"):
            raise ValueError(
                "scale_by=%.2f × %d 帧 落在已知崩溃边界（2.0 在 11s/264 帧崩过）。"
                "确认要烧这一批请加 --set confirm_big_scale=true；"
                "否则降到 1.25 或缩短帧数。" % (scale, frames))

    rep = {
        "__BASE_STEPS__": int(p.get("steps") or 8),
        "__COARSE_STEPS__": int(p.get("two_pass_coarse_steps") or 4),
        "__REFINE_STEPS__": int(p.get("two_pass_refine_steps") or 4),
        "__SCALE2__": scale,
    }
    lora2 = str(p.get("lora2") or "").strip()
    if lora2 and not str(lora2).lower().startswith("comfy/"):
        if base_lora_node is None:
            raise ValueError("要挂 Bunny 增强 LoRA，但模板里没有 __LORA__ 基底 LoRA 节点可接")
        taken = {int(n) for n in g if str(n).isdigit()}
        nxt = 250
        while nxt in taken:
            nxt += 1
        # S2：显式 0 是有效决定，不能再用 `or 0.5` 吞掉（0 为假值）。
        # 只有「没给」(None/空串) 才回退到 bunny_strength / 0.5。
        strength = p.get("lora2_strength")
        if strength in (None, ""):
            strength = p.get("bunny_strength")
        if strength in (None, ""):
            strength = 0.5
        g[str(nxt)] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"model": [base_lora_node, 0],
                                  "lora_name": str(lora2).replace("/", "\\"),
                                  "strength_model": float(strength)}}
        # 先改接再插入，避免 5b 自指造成 dependency_cycle
        for nid, node in g.items():
            if nid == str(nxt):
                continue
            ins = node.get("inputs") or {}
            for ik, iv in list(ins.items()):
                if ik == "model" and isinstance(iv, list) and iv and \
                        str(iv[0]) == base_lora_node:
                    ins[ik] = [str(nxt), 0]
        rep["__BUNNY_NODE__"] = str(nxt)
    return g, rep


# ---------------------------------------------------------------- Ref2VA 素材槽（W4c）
# 出处：官方 README.zh-CN:85（图 ≤9／视频 ≤3 段／音频 ≤3 段／总文件 ≤12）。
# ⚠ 那行把音频当**一类 ≤3**，节点 schema 拆成 ref_video_audios／ref_audios **各 max 3**；
#   这里的 video_audios＋audios 各 3 是**按节点口径的解**，合计口径见 G4 的 warn 与
#   AW_H3_AUDIO_STRICT（理由写在 apply_reference_materials 文档与 registry.audio_cap_reading）。
_REF_CAPS = {"images": 9, "videos": 3, "video_audios": 3, "audios": 3}
_REF_TOTAL = 12
_REF_KEY = {"images": "ref_images.ref_image_", "videos": "ref_videos.ref_video_",
            "video_audios": "ref_video_audios.ref_video_audio_",
            "audios": "ref_audios.ref_audio_"}
_REF_LABEL = {"images": "图", "videos": "参考视频", "video_audios": "参考片原声",
              "audios": "独立音频"}

def apply_reference_materials(graph, materials):
    """官方 Ref2VA 输入上限 9 图／3 参考视频／3 视频原声／3 独立音频，总文件 ≤12。

    ⚠ 上限的**出处与解释**（10-24 第三方复查要求挂行号）：官方 `README.zh-CN:85` 一行写全
    「图像 ≤9 张／视频 ≤3 段（每段 2–15s、总 ≤15s）／音频 ≤3 段（每段 2–15s、总 ≤15s、
    不可作为唯一输入）／所有输入类型文件总数 ≤12」——那里音频是**一类 ≤3**。
    T8 节点 schema 却把它拆成 `ref_video_audios` 与 `ref_audios` **各 max 3**。
    本函数按**节点口径**建图（每类各 ≤3），合计 ≤3 的官方读法由 `check_preflight` 的 G4
    以 warn 暴露、设 `AW_H3_AUDIO_STRICT=1` 才按合计 error。**这是我们选的解，不是逐字官方**，
    改的人请先看 `channels_registry.json → input_modes.modes.ref2va.audio_cap_reading`。

    槽位按**实际素材数**注入，不再靠模板里预先摆死的 4 个 LoadImage：
      · 图 → LoadImage → `ref_images.ref_image_k`
      · 视频 → LoadVideo → GetVideoComponents.images → `ref_videos.ref_video_k`
      · 视频原声 → 同一个 GetVideoComponents.audio → `ref_video_audios.ref_video_audio_k`
      · 独立音频 → LoadAudio → `ref_audios.ref_audio_j`
    超上限、音频当唯一输入、`ref_video_audio_k` 没有同号视频 —— 全在建图前抛，不提交。

    W4c 起也管 R3 二采的 Ref2VA：二采有**两遍**条件化（两个
    MiniMaxH3AudioConditioningT8 节点），素材必须两遍都挂同一套，否则第二遍丢掉锚还看不出来。
    所以这里遍历所有条件化宿主，每种素材只建一个加载节点、由宿主共用。
    """
    materials = {k: [str(x) for x in (materials or {}).get(k) or [] if str(x).strip()]
                 for k in _REF_CAPS}
    counts = {k: len(v) for k, v in materials.items()}
    _REF_HOSTS = ("MiniMaxH3ReferenceToVideo", "MiniMaxH3AudioConditioningT8")
    hosts = [(nid, node) for nid, node in graph.items()
             if str(node.get("class_type") or "") in _REF_HOSTS]
    if not hosts:
        if any(counts.values()):
            raise ValueError("有参考素材但图里没有 Ref2VA/二采条件化节点 —— 换 "
                             "comfy/h3_i2v_ref2va9_api.json，别把素材挂到不相干的图上")
        return graph
    over = ["%s %d 个 > 官方上限 %d" % (_REF_LABEL[k], counts[k], _REF_CAPS[k])
            for k in _REF_CAPS if counts[k] > _REF_CAPS[k]]
    if over:
        raise ValueError("Ref2VA 超官方上限：" + "；".join(over))
    total = counts["images"] + counts["videos"] + counts["audios"]
    if total > _REF_TOTAL:
        raise ValueError(f"Ref2VA 总文件 {total} > 官方上限 {_REF_TOTAL}"
                         f"（图＋视频＋独立音频；参考片原声取自同号视频，不另算一份文件）")
    if not counts["images"] and not counts["videos"] and (counts["audios"]
                                                          or counts["video_audios"]):
        raise ValueError("音频不能作为唯一输入（官方口径）：必须与图像或视频同用")
    for j in range(counts["video_audios"]):
        if j >= counts["videos"]:
            raise ValueError(f"第 {j+1} 段参考音频原声没有对应的第 {j+1} 段参考视频 —— "
                             f"`ref_video_audio_{j}` 只能挂在同号视频上")
    for nid, node in hosts:
        keys = [k for k in (node.get("inputs") or {}) if str(k).startswith("ref_images.")]
        if keys and len(keys) != counts["images"]:
            raise ValueError(f"节点 {nid} 写死了 {len(keys)} 个参考图槽，本次给 "
                             f"{counts['images']} 张 —— 多退少补都会留字面量或静默丢图；"
                             f"请改用 comfy/h3_i2v_ref2va9_api.json 或 "
                             f"comfy/h3_two_pass_modes_api.json（按素材数动态注入）")
        # 清掉静态素材槽（含它们自带的加载节点），统一由下面的动态注入接管。
        # S5：`ref_image_size` 是节点的**档位参数**（max/…），不是素材槽；以前按
        # `ref_` 前缀一并 pop，动态模板提交时报 required_input_missing。
        ins = node.setdefault("inputs", {})
        for k in [k for k in ins
                  if str(k).startswith("ref_") and str(k) != "ref_image_size"]:
            link = ins.pop(k)
            fid, _f = _loadimage_of(graph, link)
            if fid:
                graph.pop(fid, None)
    taken = {int(n) for n in graph if str(n).isdigit()}

    def _alloc(n=1):
        ids, nxt = [], 200
        while len(ids) < n:
            while nxt in taken:
                nxt += 1
            ids.append(str(nxt))
            taken.add(nxt)
            nxt += 1
        return ids if n > 1 else ids[0]

    loaders = {}
    for name in materials["images"]:
        nid = _alloc()
        graph[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
        loaders.setdefault("images", []).append((nid, 0))
    comps = {}
    for k, name in enumerate(materials["videos"]):
        vid, comp = _alloc(2)
        graph[vid] = {"class_type": "LoadVideo", "inputs": {"file": name}}
        graph[comp] = {"class_type": "GetVideoComponents", "inputs": {"video": [vid, 0]}}
        loaders.setdefault("videos", []).append((comp, 0))
        comps[k] = comp
    for k in range(counts["video_audios"]):
        loaders.setdefault("video_audios", []).append((comps[k], 1))
    for name in materials["audios"]:
        nid = _alloc()
        graph[nid] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
        loaders.setdefault("audios", []).append((nid, 0))
    for _nid, node in hosts:
        ins = node.setdefault("inputs", {})
        for kind, links in loaders.items():
            for idx, (src_id, slot) in enumerate(links):
                ins[_REF_KEY[kind] + str(idx)] = [src_id, slot]
    return graph


def build_graph_video(tpl, p, seed, extra_rep=None, ref_videos=None, input_mode=None,
                      ref_materials=None):
    """视频图的填充（H3 等）。与 build_graph 的区别：
      - **不要求"恰好 1 个 KSampler"**（H3 走 SamplerCustomAdvanced + T8 双时钟，没有 KSampler）
      - **不做 LoRA 链注入**（视频图的 LoRA 由模板自己用 __LORA__ 占位）
      - 多支持 __LEN__（帧数）与 __REF1__..__REFn__（参考图文件名）
      - ref_videos：动态注入 LoadVideo -> GetVideoComponents 并挂进
        MiniMaxH3* 节点的 ref_videos.ref_video_K（模板里预先摆帧序列节点没意义，
        数量可变；接线方式与 ComfyUI_H3/run_h3.py 一致，只取 images 输出，
        **刻意不接参考片原声**——参考片的对白/配乐会污染成片音轨）
    """
    g = copy.deepcopy(tpl)
    # W1c/W4c 模板元数据不是 ComfyUI 节点：先取用再剥离（否则提交时会被当成未注册节点）
    tpl_meta = dict(g.get("_meta") or {})
    g.pop("_meta", None)
    prompt = str(p.get("prompt", "")).strip()
    if not prompt or prompt == "None":
        raise ValueError("提示词为空或字面量 \"None\"，拒绝提交（会白跑一趟 GPU）。")
    rep = {
        "__PROMPT__": prompt,
        "__SEED__": int(seed),
        "__STEPS__": int(p.get("steps", 8)),
        "__W__": _size_from_params(p, "width", "出片模板（build_graph_video）"),
        "__H__": _size_from_params(p, "height", "出片模板（build_graph_video）"),
        "__LEN__": int(p.get("length", 124)),
        "__PREFIX__": str(p.get("prefix", "wf")),
        "__LORA__": str(p.get("lora", "")).replace("/", "\\"),
        "__LORA_STRENGTH__": float(p.get("lora_strength", 1.0)),
        "__LORA2__": str(p.get("lora2", "")).replace("/", "\\"),
        "__LORA2_STRENGTH__": float(p.get("lora2_strength", 0.3)),
        "__LORA3__": str(p.get("lora3", "")).replace("/", "\\"),
        "__LORA3_STRENGTH__": float(p.get("lora3_strength", 0.3)),
        "__HEAD_CHUNKS__": int(p.get("head_chunks", 4)),
        # W4c：R3 全模式图的条件化模式名由 input_mode 决定（默认 I2VA＝现役口径）
        "__TASK_TYPE__": {"t2va": "T2VA", "i2va": "I2VA", "fl2va": "FL2VA",
                          "l2va": "L2VA", "ref2va": "Ref2VA"}.get(
            str(p.get("input_mode") or input_mode or "").strip().lower(), "I2VA"),
    }
    if extra_rep:
        rep.update(extra_rep)

    # W1c：可选首尾帧——按模式删 LoadImage/socket（旧模板无 input_mode 时原样走）
    # Ref2VA 不接首尾帧（素材走 ref_* 槽），跳过帧槽修剪，否则会把它的模式名当成非法值
    mode = str(p.get("input_mode") or input_mode or "").strip().lower()
    if mode and mode != "ref2va":
        n_refs = sum(1 for k in rep
                     if str(k).startswith("__REF") and str(k).endswith("__"))
        g = apply_keyframe_mode(g, mode, n_refs,
                                optional=bool(tpl_meta.get("keyframes_optional"))
                                or bool(tpl_meta.get("optional_keyframes")))
    elif mode == "ref2va":
        for _nid, _node in list(g.items()):
            if str(_node.get("class_type") or "") in ("MiniMaxH3ImageToVideo",
                                                      "MiniMaxH3AudioConditioningT8"):
                ins = _node.get("inputs") or {}
                for slot in ("first_frame", "last_frame"):
                    fid, _f = _loadimage_of(g, ins.pop(slot, None))
                    if fid:
                        g.pop(fid, None)

    # W4a：R3 二采是 recipe——显式 scale_by、4+4 步分记、可选 Bunny 增强节点
    if str(p.get("two_pass", "")).lower() in ("true", "1", "yes", "on"):
        g, tp_rep = apply_two_pass(g, p)
        for k, v in tp_rep.items():
            rep.setdefault(k, v)

    # W4c：Ref2VA 素材槽按实际数量注入（9图/3视频/3视频原声/3独立音频，总 ≤12）
    if ref_materials is not None:
        g = apply_reference_materials(g, ref_materials)

    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str) and v in rep:
            return rep[v]
        return v
    g = walk(g)

    if ref_videos and ref_materials is None:
        # 旧路径（静态 4 图模板）：只动态补参考视频。W4c 的 9 图模板走下面
        # apply_reference_materials，图/视频/视频原声/独立音频一次注入。
        host = None
        for nid, node in g.items():
            ins = node.get("inputs") or {}
            if str(node.get("class_type", "")).startswith("MiniMaxH3") and any(
                    str(k).startswith("ref_images.") for k in ins):
                host = nid
                break
        if host is None:
            raise RuntimeError("模板里没有 MiniMaxH3 参考节点（带 ref_images.* 的那个），"
                               "无法挂参考视频 —— 换 h3_i2v_ref2va_api.json 这类模板")
        taken = {int(nid) for nid in g if str(nid).isdigit()}
        nxt = 200
        for k, nm in enumerate(ref_videos):
            while nxt in taken or (nxt + 1) in taken:
                nxt += 2
            vid, comp = str(nxt), str(nxt + 1)
            taken.update({nxt, nxt + 1})
            g[vid] = {"class_type": "LoadVideo", "inputs": {"file": nm}}
            g[comp] = {"class_type": "GetVideoComponents",
                       "inputs": {"video": [vid, 0]}}
            g[host]["inputs"][f"ref_videos.ref_video_{k}"] = [comp, 0]
            nxt += 2
    return g


def _history_outputs(r, base, prompt_id, out_dir, expected_prefix=None):
    """只认 **这个 prompt_id** 的产物；没完成返回 None。"""
    try:
        resp = SESSION.get(f"{base}/history/{prompt_id}", timeout=10)
        if resp.status_code != 200:
            return None
        h = (resp.json() or {}).get(prompt_id)
    except Exception:
        return None
    if not h:
        return None
    st = h.get("status") or {}
    if st.get("status_str") == "error":
        raise RuntimeError("ComfyUI 执行出错: "
                           + json.dumps(st.get("messages", []), ensure_ascii=False)[:400])
    files = []
    for node_out in (h.get("outputs") or {}).values():
        for kind in ("images", "videos", "gifs"):
            for im in node_out.get(kind, []):
                if not isinstance(im, dict) or not im.get("filename"):
                    continue
                name = im["filename"]
                if expected_prefix and (not name.startswith(expected_prefix)
                        or Path(name).suffix.lower() not in (".mp4", ".webm", ".mov")):
                    continue
                files.append(str(Path(out_dir) / im.get("subfolder", "") / name))
    return files or None


def poll_history(ctx, base, prompt_id, timeout, pre_snapshot=None, expected_prefix=None):
    """轮询这个 prompt_id 的产物。

    W5b-1：超时**不再扫全输出目录认领新文件**。以前兜底是"目录里多了东西就当成功"，
    并发或别人在同一台机器上出片时会把别人的产物认领成本次结果（台账从此不可信）。
    现在只问这个 prompt_id 的 history；拿不到就失败，并把 prompt_id 留在异常文本里，
    之后靠 adopt_late_output() 事后认领——认领条件仍是同一个 prompt_id。
    """
    out_dir = ctx["cfg"]["comfyui"]["output_dir"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        raise_if_cancel_requested(ctx, f"poll_history:{prompt_id}")
        time.sleep(3)
        try:
            r = SESSION.get(f"{base}/history/{prompt_id}", timeout=10)
            if r.status_code != 200:
                continue
            h = (r.json() or {}).get(prompt_id)
        except Exception:
            continue
        if not h:
            continue
        st = h.get("status") or {}
        if st.get("status_str") == "error":
            raise RuntimeError("ComfyUI 执行出错: "
                               + json.dumps(st.get("messages", []), ensure_ascii=False)[:400])
        if st.get("completed") or h.get("outputs"):
            files = _history_outputs(None, base, prompt_id, out_dir, expected_prefix)
            if files:
                return list(dict.fromkeys(files))
            # status 可能先于 outputs 更新；继续等本 prompt_id 的结果。
    late = _history_outputs(None, base, prompt_id, out_dir, expected_prefix)
    if late:
        log(ctx, f"[poll_history] 超时后 prompt_id={prompt_id} 自己完成了，按它的 history 认领")
        return list(dict.fromkeys(late))
    raise RuntimeError(
        f"ComfyUI 执行超时（>{timeout}s，prompt_id={prompt_id}）；"
        f"没有该 prompt_id 的产物 ⇒ 判失败。不扫输出目录认领别人的新文件；"
        f"要事后认领这一次的结果用 adopt_late_output(prompt_id='{prompt_id}')")


def adopt_late_output(ctx, base, prompt_id, expected_prefix=None):
    """超时之后复查：**只认这个 prompt_id**，绝不用"目录里多了文件"当证据。"""
    out_dir = ctx["cfg"]["comfyui"]["output_dir"]
    files = _history_outputs(None, base, prompt_id, out_dir, expected_prefix)
    if not files:
        return None
    return {"prompt_id": prompt_id, "files": list(dict.fromkeys(files))}


def relocate(files, dst_dir, log_fn=None):
    """把 ComfyUI 暂存目录里的产物搬进交付批次夹，返回新路径列表。

    为什么由引擎搬、而不是让 ComfyUI 直接写对地方：本机输出目录有两个互不同步的
    事实源（config.yaml 的 comfyui.output_dir 与 launchers\\comfyui.bat 里的写死值），
    而复用的服务不会被校验在往哪写 —— prefix 方案会静默把图落进旧目录。
    搬完 ComfyUI 前端 History 缩略图会 404，交付面是批次夹里的 HTML 报告，已知代价。
    """
    dst_dir = Path(dst_dir)
    if not files:
        return []
    dst_dir.mkdir(parents=True, exist_ok=True)
    moved, skipped = [], []
    for f in files:
        src = Path(f)
        if not src.exists():
            skipped.append(str(src))
            continue
        to = dst_dir / src.name
        n = 1
        while to.exists():
            to = dst_dir / f"{src.stem}_{n}{src.suffix}"
            n += 1
        # 新落盘的图常被 Defender 实时扫描短暂锁定，move 报 WinError 32，重试即可
        last_err = None
        for _ in range(5):
            try:
                shutil.move(str(src), str(to))
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                time.sleep(2)
        if last_err is not None:
            raise last_err
        moved.append(str(to))
    if skipped:
        raise RuntimeError(
            f"relocate: 应搬 {len(files)} 个，只搬到 {len(moved)} 个，"
            f"暂存目录里找不到 {skipped}。目标夹 {dst_dir}。"
            f"根因通常是复用的 ComfyUI 服务写到了 cfg.comfyui.output_dir 之外"
            f"（ensure_comfyui 复用存活服务时不校验它在往哪写）。")
    if moved and log_fn:
        log_fn(f"[relocate] {len(moved)} 个产物 -> {dst_dir}")
    return moved


def ensure_comfyui(ctx, relay=False):
    """确保 ComfyUI 在跑并返回 base_url；未运行则自动拉起。

    出图与精修共用这一份：启动命令只在这里定义一次。
    relay=True（R11 接力批）优先用 launch_cmd_relay（无 sage + reserve 6，R11-01 硬条件3），
    并把启动命令写进 logs\\comfyui_launch_flags.json —— 接力守卫靠这个标记确认
    存活服务的采样 attention 配置（服务进程本身查不到自己的启动参数）。
    """
    cfg = ctx["cfg"]["comfyui"]
    base = cfg["base_url"].rstrip("/")
    if http_ok(base + "/system_stats"):
        return base
    log(ctx, "[comfyui] 启动 ComfyUI ...")
    cmd = cfg.get("launch_cmd") or (
        f'cmd /c ".\\python_embeded\\python.exe -s ComfyUI\\main.py '
        f'--windows-standalone-build --output-directory {cfg["output_dir"]}"')
    if relay and cfg.get("launch_cmd_relay"):
        cmd = cfg["launch_cmd_relay"]
        log(ctx, "[comfyui] 接力批：使用 launch_cmd_relay（无 sage + reserve 6）")
    try:
        marker = Path(cfg.get("log", "comfyui.log")).parent / "comfyui_launch_flags.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(
            {"cmd": cmd, "launched_at": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # 标记写不出去只影响下次接力守卫的判读，不拦启动
    with open(cfg.get("log", "comfyui.log"), "ab") as logf:
        subprocess.Popen(cmd, shell=True, cwd=cfg["root"],
                         creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         stdin=subprocess.DEVNULL, stdout=logf, stderr=logf)
        t0 = time.time()
        while time.time() - t0 < cfg.get("startup_timeout", 240):
            time.sleep(3)
            if http_ok(base + "/system_stats"):
                log(ctx, f"[comfyui] 已就绪（{time.time() - t0:.0f}s）")
                return base
    raise RuntimeError("ComfyUI 启动超时")


def _batch_consistency_qc(files, ctx, stage="", identity_lock=True):
    """批内**身份**相对尺（10-03 批 7-4 接进引擎；11-04 判据改名＋加身份锁声明）。

    为什么挂在这里而不是只写一份文档让人自己跑：`GAP-G3` 实测名字像裁判的脚本 15 个、
    其中 14 个在调用面里一次都没出现——**裁判件不接线等于没有裁判**。

    🔴 11-04 这次改的是什么（细节与证据在 `tools/qc_batch_consistency.py` 文件头）：
      这把尺的取法是**脸框归一裁「头＋上身」**，量的是"同一个人、同一身衣服"，
      旧文档却写成"画风／光照／介质漂没漂"。同日一批主题裸跑（古风大家闺秀，
      四张人判都好、只差在换脸换装）被它按旧口径判 FAIL。离线复核证明
      **任何批内相对量都抓不到"整批一起偏"**（五种取法在打回批／未打回批上零分离），
      所以这次不新造画风尺，只把拦人的口子对准它真能判的那一维：
        · `identity_lock=True`（默认＝现役行为不变）：这批声明了"应当同一人／同一装"
          （定妆、i2i 派生、按编号精修）⇒ 照旧 0.75 拦、0.80 警示。
        · `identity_lock=False`：主题裸跑／探索批，换脸换装属预期 ⇒ fail/warn 降级为
          `report_only`，**读数照进台账但不拦**；原判序记在 verdict_by_identity_axis。
      画风一致性这一维**交人眼**（图发飞书），尺子只补一句"最差一对的色调／介质差在哪"。

    三条硬规矩（对应裁定里的三条，一条没动）：
      ① 只有"量出来确实散"才拦：最低 <0.75 → 停批；均值 <0.80 → 只警示。阈值不在这里抄，
         权威在 `tools/qc_batch_consistency.py` 的两行常量，注册表 `qc_batch_dino_floor` 记指针。
      ② 绝对带（faceL／faceWhite／lpalex／gedge／faceHR）**一概不调**——10-02 实测拿它测
         另一个项目的未打回基线稿 3/3 全 FAIL，那是项目标定，不是通用判据。
         尺子里新加的 `worst_pair_delta` 是**两两差值、无阈值、不参与判序**，不是第二条绝对带。
      ③ 量不了就是"未测量"，**绝不写成通过**：清单 <2 张、产物里没脸、环境缺依赖，
         全部如实进台账（verdict=not_measured ＋ reason）。

    逃生口：config `qc.batch_consistency: off`。关掉不自责，但必须在台账 `bypassed`
    留字据（同 R5-07 的规矩），所以这里让它照抛——台账坏了先修台账。
    """
    cfg = ctx.get("cfg") or {}
    knob = str(((cfg.get("qc") or {}) if isinstance(cfg.get("qc"), dict)
                else {}).get("batch_consistency", "on")).lower()
    if knob in ("off", "false", "0", "no"):
        record_gate_bypass(cfg, str(cfg.get("project") or ""), str(ctx.get("workflow") or ""),
                           "config.qc.batch_consistency=off", gates=["批内相对尺"],
                           by="config:qc.batch_consistency=off")
        log(ctx, "[批内相对尺] 已按 config 关闭（台账 bypassed 已留字据）⇒ 本步产物未做批内互比")
        return {"verdict": "off", "reason": "config.qc.batch_consistency=off",
                "n_input": len(files or [])}
    res = {"verdict": "not_measured", "n_input": len(files or []), "n_measurable": 0}
    try:
        tools_dir = str(Path(__file__).resolve().parent.parent / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from qc_batch_consistency import explain, measure
        res = measure([str(f) for f in (files or [])], identity_lock=identity_lock)
    except Exception as e:
        # 尺子起不来＝未测量，不是通过；但也别为了量一把尺把整批 GPU 时间作废。
        res = {"verdict": "not_measured", "n_input": len(files or []), "n_measurable": 0,
               "reason": "尺子没跑起来（%s: %s）" % (type(e).__name__, str(e)[:160])}
    v = str(res.get("verdict"))
    try:
        log(ctx, "[批内相对尺] " + explain(res))
    except Exception:
        log(ctx, "[批内相对尺] verdict=%s" % v)
    if v == "report_only":
        # 只报不拦也要在日志里喊一声，别让"没拦"看起来像"过了"。
        log(ctx, "[批内相对尺] 这批未声明身份锁 ⇒ 不拦（换脸换装属预期）；"
                 "画风一致性请人眼看，图已发飞书")
    if v == "fail":
        raise RuntimeError(
            "批内相对尺拦下（同批产物不是同一个人／同一身衣服）：\n  " + explain(res)
            + "\n  处置：先看上面那一对最差产物到底差在哪（身份尺给的是脸＋装，"
              "色调／介质那几句只报数不判），再决定重挑种子还是改提示词——"
              "**别整批重跑**（成本意识）；"
              "确认这批本就该换脸换装（主题裸跑／探索），别关尺子，"
              "在该工作流的出图步上声明 `identity_lock: false`（只报不拦，读数仍进台账）；"
              "确要整条关掉才临时设 config `qc.batch_consistency: off`（会在台账留字据）。")
    if v == "warn":
        log(ctx, "[批内相对尺][WARN] 均值落在警示带（<%.2f）⇒ 不拦，但这一批要人眼看一遍"
                 % float(res.get("thresholds", {}).get("mean_warn_lo", 0.8)))
    elif v == "not_measured":
        log(ctx, "[批内相对尺] 未测量≠通过（原因见上一行）；本步 %d 张产物没有批内自洽证据"
                 % int(res.get("n_input") or 0))
    return res


@task("comfyui")
def t_comfyui(p, ctx):
    """ComfyUI 出图。params: workflow(模板相对路径) / prompt / count / width /
    height / steps / guidance / seed(可空=随机) / prefix / stage(落进批次夹的子目录，默认 draft) /
    loras[{name,strength}] / timeout。服务未运行时自动启动。"""
    # 尺寸闸门放在**碰服务之前**：以前它在出完图之后才读，"人忘了配尺寸"要先把
    # count 张 GPU 时间烧完才报错，连 ComfyUI 都会被顺手拉起来——最贵的一种失败。
    exp = _explicit_size(p, ctx, "comfyui 出图（尺寸闸门）")
    base = ensure_comfyui(ctx)
    tpl = load_template(ctx, p["workflow"])
    count = int(p.get("count", 1))
    files, seeds, t0 = [], [], time.time()
    for i in range(count):
        seed = p.get("seed")
        seed = random.randint(0, 2**31 - 1) if seed in (None, "") else int(seed) + i
        graph = build_graph(tpl, p, seed)
        sc = float(p.get("scale_by", 1.0) or 1.0)
        if sc != 1.0:
            # 日志用的就是闸门那对值（同一份数读一次，别两处各读各的）
            base_w, base_h = exp
            log(ctx, f"[comfyui] scale_by={sc}：基图 "
                     f"{base_w // sc}x{base_h // sc} "
                     f"→ 成品 {base_w}x{base_h}")
        out_dir = Path(ctx["cfg"]["comfyui"]["output_dir"])
        pre_snapshot = set(f for f in out_dir.rglob("*") if f.is_file())
        r = SESSION.post(base + "/prompt", json={"prompt": graph}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"任务提交失败: {r.text[:300]}")
        pid_ = r.json()["prompt_id"]
        persist_submission(ctx, pid_, graph, p, stage=str(p.get("stage") or "draft"),
                           intent="submit", extra={"seed": seed, "index": i + 1})
        log(ctx, f"[comfyui] 提交 {i + 1}/{count}  seed={seed}  prompt_id={pid_}")
        got = poll_history(ctx, base, pid_, int(p.get("timeout", 900)),
                           pre_snapshot=pre_snapshot)
        if not got:
            raise RuntimeError(
                f"ComfyUI 没产出任何文件（prompt_id={pid_}），"
                f"检查 ComfyUI 日志或模型是否加载失败")
        got = relocate(got, Path(ctx["batch_dir"]) / str(p.get("stage", "draft")), ctx["log"])
        files.extend(got)
        # 一次提交可能产出多张（batch），全部记同一个 seed，供后续按编号复现/精修
        seeds.extend([seed] * len(got))
    log(ctx, f"[comfyui] 完成 {len(files)} 张（{time.time() - t0:.1f}s）")
    sizes = [img_size(f) for f in files]
    bad = [s for s in sizes if s != exp]
    if bad:
        raise RuntimeError(
            f"产物尺寸 {bad[0][0]}x{bad[0][1]} ≠ 请求 {exp[0]}x{exp[1]}"
            f"（{len(bad)}/{len(files)} 张），{p['workflow']} 里有多余的放大节点")
    blank = [f for f in files if img_is_blank(f)]
    if blank:
        raise RuntimeError(f"{len(blank)}/{len(files)} 张是纯色废图，"
                           f"例 {Path(blank[0]).name}；提示词或模型可能有问题")
    # 产物侧机检：尺寸／纯色是"每张自己的硬伤"，批内身份尺是"这一批是不是同一个人同一身衣服"。
    # 两者维度不同，后者是 10-03 唯一被裁可以接进引擎的那把 QC 主尺（见 _batch_consistency_qc）。
    # 身份锁（11-04）：只有这批声明"应当同人同装"时才允许它拦人；默认 True＝现役行为不变，
    # 主题裸跑／探索链在出图步上写 `identity_lock: false`（只报不拦，读数照进台账）。
    idlock = str(p.get("identity_lock",
                       (ctx.get("args") or {}).get("identity_lock", True))
                 ).lower() not in ("false", "0", "no")
    bq = _batch_consistency_qc(files, ctx, stage=str(p.get("stage") or "draft"),
                               identity_lock=idlock)
    return {"files": files, "seeds": seeds, "count": len(files),
            "elapsed": round(time.time() - t0, 1),
            "width": sizes[0][0], "height": sizes[0][1],
            "steps": int(p.get("steps", 28)), "prompt": str(p.get("prompt", "")),
            "batch_qc": bq}


# ---------------------------------------------------------------- W5b 提交/状态/取消
TASK_STATES = ("planned", "awaiting_review", "reviewed", "submitted", "running",
               "unknown_after_timeout", "generated", "qc_failed", "qc_passed",
               "archive_pending", "cancel_requested", "cancelled", "failed", "done")

_HUMAN_STATES = ("awaiting_review", "reviewed", "cancelled")


def assert_task_state(state):
    """状态词只能用人裁过的那一张表——写错一个词就等于发明了"未知即成功"。"""
    if state not in TASK_STATES:
        raise ValueError(f"未知任务状态 {state!r}；可用 {list(TASK_STATES)}")
    return state


def persist_submission(ctx, prompt_id, graph, params, stage=None, intent=None,
                       extra=None):
    """拿到 prompt_id 立刻落盘：完整 API graph、本次参数、提交意图、时间戳。

    为什么必须在轮询**之前**写：超时/断电之后如果没有这份东西，就无法回答
    "那次提交到底投的是什么"，也就无法事后认领（W5b-1）。
    """
    batch = Path(ctx["batch_dir"])
    safe = re.sub(r"[^\w.-]", "_", str(ctx.get("run_id") or "run"))
    # S1：stage 里可能带 shots/<sid>/raw 这种子路径。以前直接拼进文件名会把
    # submission 塞进子目录（文件名变成 raw.json），--cancel/_submissions 的
    # submission_<run>_*.json glob 找不到它，多镜任务就无法按 ID 取消。
    safe_stage = re.sub(r"[^\w.-]+", "_", str(stage or "video")).strip("_")
    path = batch / f"submission_{safe}_{safe_stage or 'video'}.json"
    payload = {
        "prompt_id": prompt_id,
        "run_id": ctx.get("run_id"),
        "workflow": ctx.get("workflow"),
        "stage": stage,
        "step_id": ctx.get("step_id"),
        "batch_dir": str(ctx.get("batch_dir") or "") or None,
        "prefix": (params or {}).get("prefix"),
        "submitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "intent": intent or "submit",
        "params": {k: v for k, v in (params or {}).items()
                   if not str(k).startswith("_")},
        "graph": graph,
    }
    if extra:
        payload.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    return payload, path


def submission_prefixes(ctx, sid):
    """本 run、本镜的真实提交前缀（含 prompt_id）——跨 run 认领的归属证据。"""
    batch = Path(str(ctx.get("batch_dir") or ""))
    run_id = _safe_run_id(ctx.get("run_id"))
    found = []
    if not batch.is_dir():
        return found
    for f in batch.rglob(f"submission_{run_id}_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        stage = str(d.get("stage") or "")
        if stage and stage != f"shots/{sid}/raw":
            continue
        pfx = str(d.get("prefix") or (d.get("params") or {}).get("prefix") or "")
        if pfx:
            found.append({"prefix": pfx, "prompt_id": d.get("prompt_id"),
                          "file": str(f)})
    return found


class RunCancelled(RuntimeError):
    """本 run 收到取消意图：停止后续步骤/提交；不是服务故障。"""


_CANCEL_INTENT = "cancel_intent.json"


def _ctx_batch_dir(ctx_or_dir):
    if ctx_or_dir is None:
        return None
    if isinstance(ctx_or_dir, (str, Path)):
        return Path(ctx_or_dir)
    bd = ctx_or_dir.get("batch_dir")
    return Path(bd) if bd else None


def request_cancel(ctx_or_dir, prompt_id=None, reason="cli"):
    """把取消意图落到本 run 的批次夹：运行中的进程只认这个文件，不轮询全局状态。"""
    bd = _ctx_batch_dir(ctx_or_dir)
    if bd is None:
        return None
    bd.mkdir(parents=True, exist_ok=True)
    path = bd / _CANCEL_INTENT
    data = {
        "requested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "prompt_id": str(prompt_id) if prompt_id else None,
        "reason": str(reason),
        "run_id": (ctx_or_dir.get("run_id")
                   if isinstance(ctx_or_dir, dict) else None),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
    return path


def read_cancel_intent(ctx_or_dir):
    bd = _ctx_batch_dir(ctx_or_dir)
    if bd is None:
        return None
    path = bd / _CANCEL_INTENT
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"corrupt": True, "path": str(path)}


def cancel_requested(ctx_or_dir):
    return read_cancel_intent(ctx_or_dir) is not None


def raise_if_cancel_requested(ctx_or_dir, where=""):
    intent = read_cancel_intent(ctx_or_dir)
    if intent:
        raise RunCancelled(
            f"已收到本 run 的取消意图（{where or '当前步骤'}）：{intent}. "
            f"停止后续步骤，不再提交新任务")


def _queue_ids(q):
    ids = set()
    for lst in ((q or {}).get("queue_running") or []) + \
            ((q or {}).get("queue_pending") or []):
        if isinstance(lst, list) and len(lst) > 1:
            ids.add(str(lst[1]))
        elif isinstance(lst, str):
            ids.add(lst)
    return ids


def _history_present(base, prompt_id):
    try:
        r = SESSION.get(f"{base}/history/{prompt_id}", timeout=15)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        return prompt_id in data
    except Exception:
        return None


def cancel_submission(ctx, base, prompt_id, running=False):
    """按 ID 原子取消：只动这一次任务，不用无 ID 的全局 /interrupt。

    服务端契约（D:/AIWorkflow/ComfyUI_H3/ComfyUI/server.py:1033–1076）：
      POST /api/jobs/{job_id}/cancel → 200 {"cancelled": true|false}
      已完成/未知 ID 都是幂等 no-op（cancelled=false）。
    终态必须分开表达，不能仅凭“不在 queue”就 confirmed：
      cancelled       服务端已取消且回读队列确实不在
      finished        已在 history 里（取消是 no-op）
      unknown         不在队列也不在 history，且服务端未派发
      not_dispatched  服务端明确 cancelled=false，目标仍在队列
      still_queued    服务端说取消了，但回读队列仍在（竞争/取消未落地）
      api_error       HTTP 错误、网络异常或队列回读失败，取消未证实
    """
    pid = str(prompt_id or "").strip()
    steps = []
    if not pid:
        return {"prompt_id": pid, "requested": False, "dispatched": False,
                "confirmed": False, "state": "not_dispatched",
                "still_queued": None, "queue": None, "steps": steps,
                "error": "空 prompt_id，未派发任何取消请求",
                "running_hint": bool(running),
                "note": "空 ID 不算已取消"}

    # 先落本 run 的停止意图：运行中的多镜循环在下一镜/下次提交前会读它。
    # R1：意图写不进去就**不得**继续发取消请求——否则当前任务可能被取消，
    # 但正在跑的循环看不到停止标志，下一镜还会继续提交。
    if _ctx_batch_dir(ctx) is not None:
        try:
            path = request_cancel(ctx, pid, reason="cancel_submission")
            intent = read_cancel_intent(ctx)
            if (not path or not Path(path).is_file() or not intent
                    or intent.get("corrupt")):
                raise OSError("cancel_intent.json 未落盘或不可读")
            steps.append({"endpoint": "cancel_intent", "file": str(path)})
        except Exception as e:
            err = f"取消意图写入失败：{type(e).__name__}: {str(e)[:200]}"
            steps.append({"endpoint": "cancel_intent", "error": err})
            return {"prompt_id": pid, "requested": True, "dispatched": False,
                    "confirmed": False, "state": "intent_write_failed",
                    "still_queued": None, "queue": None, "steps": steps,
                    "error": err, "running_hint": bool(running),
                    "note": ("停止意图没落盘，未发送任何取消请求；"
                             "不得显示为已取消，需修复批次目录权限或人工处理")}

    dispatched = False
    post_error = None
    try:
        r = SESSION.post(f"{base}/api/jobs/{pid}/cancel", timeout=15)
        steps.append({"endpoint": f"/api/jobs/{pid}/cancel",
                      "http": r.status_code})
        if r.status_code == 200:
            data = r.json() or {}
            dispatched = data.get("cancelled") is True
        else:
            post_error = f"HTTP {r.status_code}: {str(getattr(r, 'text', ''))[:200]}"
    except Exception as e:
        post_error = f"{type(e).__name__}: {str(e)[:200]}"
        steps.append({"endpoint": f"/api/jobs/{pid}/cancel",
                      "error": post_error})

    queued, queue_error, in_queue = None, None, False
    try:
        q = SESSION.get(f"{base}/queue", timeout=15).json() or {}
        queued = {k: len(v or []) for k, v in
                  (("running", q.get("queue_running")),
                   ("pending", q.get("queue_pending")))}
        in_queue = pid in _queue_ids(q)
    except Exception as e:
        queue_error = f"{type(e).__name__}: {str(e)[:200]}"
        queued = {"error": queue_error}

    in_history = _history_present(base, pid) if not in_queue else False

    if post_error:
        state, confirmed = "api_error", False
    elif queue_error:
        state, confirmed = "api_error", False
    elif dispatched:
        if in_queue:
            state, confirmed = "still_queued", False
        else:
            state, confirmed = "cancelled", True
    elif in_queue:
        state, confirmed = "not_dispatched", False
    elif in_history:
        state, confirmed = "finished", False
    else:
        state, confirmed = "unknown", False

    error = post_error or queue_error
    notes = {
        "cancelled": "已按 ID 取消；未清队列、未停服务",
        "finished": "目标已在 history 中结束；取消是幂等 no-op，不显示为已取消",
        "unknown": "不在队列也不在 history，服务端未派发取消；不得当已取消",
        "not_dispatched": "服务端明确未派发取消，目标仍在队列；不得当已取消",
        "still_queued": "服务端称已取消，但回读队列仍在；不得当已取消",
        "api_error": "取消请求/回读失败，未证实；不得当已取消",
    }
    return {"prompt_id": pid, "requested": True, "dispatched": dispatched,
            "confirmed": confirmed, "state": state,
            "still_queued": in_queue, "queue": queued, "steps": steps,
            "error": error, "running_hint": bool(running),
            "note": notes[state]}


def content_hash8(path):
    """素材内容指纹前 8 位：参考文件按内容命名，不按序号命名。

    以前 input 目录里是 `wfref_1_同名词.png`，两个批次用同一个文件名（角色名一样很常见）
    就会互相覆盖，归档时两端对不上账（W5b-2）。
    """
    p = Path(str(path))
    if not p.is_file():
        return "missing"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def gate_binding_parts(p, args, ctx=None, media=None):
    """人工关口的**绑定成分**（W5b）：批准绑的不只是提示词与素材，还包括
    这一批真正要提交的全部可变参数与（终审时）媒体内容哈希。

    换 seed / 换步数 / 换强度 / 换模板 / 换素材 / 换一条成片 ⇒ 指纹变 ⇒ 旧批准自动失效，
    不会出现"批过 A 跑了 B"。真源仍然只有 t_gate 一处调用。
    """
    parts = []
    src = dict(args or {})
    src.update({k: v for k, v in (p or {}).items()
                if k in ("seed", "steps", "lora_strength", "lora2_strength",
                         "bunny_strength", "sigmas", "scale_by", "two_pass",
                         "two_pass_coarse_steps", "two_pass_refine_steps",
                         "input_mode", "prompt_kind")})
    for k in ("input_mode", "prompt_kind", "seed", "steps", "sigmas", "lora_strength",
              "lora2_strength", "bunny_strength", "two_pass", "two_pass_coarse_steps",
              "two_pass_refine_steps", "scale_by"):
        if src.get(k) not in (None, ""):
            parts.append((k, str(src.get(k)).lower() if isinstance(src.get(k), str)
                          else src.get(k)))
    tpl = (ctx or {}).get("template_path") or (p or {}).get("workflow_json") \
        or (p or {}).get("workflow")
    if tpl:
        tp = Path(str(tpl))
        if not tp.is_absolute():
            tp = Path(str((ctx or {}).get("wf_root")
                          or Path(__file__).resolve().parent)) / tp
        parts.append(("template", f"{tp.name}@{content_hash8(tp)}" if tp.is_file()
                      else str(tpl)))
    for path in list(media or []):
        parts.append(("media", f"{Path(str(path)).name}@{content_hash8(path)}"))
    return parts


def _sha256_file(path):
    p = Path(str(path))
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_prompt(p):
    """提示词单一真源：优先 prompt_file（prompts/*.txt），其次内联 prompt。
       2026-09-20 补：此前只能 --set prompt="$(cat …)"，于是大家绕开引擎用裸脚本，
       日志/台账/归档就断在另一条路上了。"""
    pf = p.get("prompt_file")
    if pf:
        fp = Path(str(pf))
        if not fp.is_file():
            raise RuntimeError(f"prompt_file 不存在: {fp}")
        return fp.read_text(encoding="utf-8", errors="replace").strip()
    return str(p.get("prompt") or "")


def digest_parts(prompt, refs, ref_videos, w=None, h=None, length=None, lora=None,
                 theme=None):
    """关口摘要的**唯一成分表**：t_gate（人工关口）与 G13（运行决定留痕）都吃它。

    为什么要有这一个函数：摘要成分若在两处各写一遍，两处就会漂——
    漂了以后「批过的内容」和「跑的内容」对不上，留痕就成了摆设。
    """
    return [("prompt", prompt), ("refs", refs), ("ref_videos", ref_videos),
            ("w", w), ("h", h), ("length", length), ("lora", lora), ("theme", theme)]


def collect_run_decisions(cfg, project, args, explicit=None):
    """取「这批由人给过的值」交给 G13。取不到就交错误结构，**绝不当成没有必填槽**。"""
    try:
        eng_dir = str(Path(__file__).resolve().parent)
        if eng_dir not in sys.path:
            sys.path.insert(0, eng_dir)
        from decision_sheet import collect
        return collect(cfg, project, args or {}, explicit)
    except Exception as e:
        return {"errors": ["决定单模块读不出（%s: %s）⇒ G13 不给放行"
                           % (type(e).__name__, e)]}


def preflight_or_die(p, ctx, refs, ref_videos=None, template_path=None, only=None):
    """跑前自审闸 G1–G7 + G11 + G13（tools\\check_preflight.py）。

    为什么挂在 video 任务内部而不是只写在 YAML 里：YAML 步骤能被人删或忘了加，
    挂在提交前的最后一步就绕不过去。warn 只进日志，error 直接拦 —— 拦下来的
    每一条都对应历史上真烧掉的 GPU 时间（9-18 四条全废＝槽位配错）。
    """
    cfg = ctx.get("cfg") or {}
    if str(cfg.get("preflight", "on")).lower() in ("off", "false", "0", "no"):
        record_gate_bypass(cfg, str(cfg.get("project") or ""),
                           str(ctx.get("workflow") or ""),
                           "config.preflight=off",
                           gates=([str(x).upper() for x in (only or [])]
                                  or ["默认子集全部"]),
                           by="config:preflight=off")
        log(ctx, "[preflight] config.preflight=off，本次跳过跑前自审"
                  "（已在批准台账的 bypassed 段留字据：绕过了什么、什么时候、谁绕的）")
        return
    try:
        tools_dir = Path(__file__).resolve().parent.parent / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        from check_preflight import run_checks, TEN_BLOCKS
    except Exception as e:
        raise RuntimeError(f"跑前自审闸不可用（{type(e).__name__}: {e}）—— "
                           f"宁可停下，也不要在没校验的情况下烧 GPU；"
                           f"确要跳过请设 config.yaml preflight: off")
    args = ctx.get("args") or {}
    spec = {"prompt": resolve_prompt(p), "refs": list(refs),
            "ref_videos": list(ref_videos or []),
            # W4c：官方 Ref2VA 还有两路音频素材，spec 一直缺字段 ⇒ G4 只能"登记不判"
            "ref_audios": list(p.get("ref_audios") or []),
            "ref_video_audios": list(p.get("ref_video_audios") or []),
            "prompt_kind": str(p.get("prompt_kind") or "video"),
            "input_mode": str(p.get("input_mode") or ""),
            "w": int(p.get("width") or 0) or None, "h": int(p.get("height") or 0) or None,
            "length": int(p.get("length") or 0) or None,
            "duration": args.get("duration"), "lora": p.get("lora"),
            "workflow_json": str(template_path) if template_path else None,
            "lora_dir": str(Path(str((cfg.get("comfyui") or {}).get("root", ""))) /
                            "ComfyUI" / "models" / "loras"),
            "provider": "local", "seed": p.get("seed"), "blocks": TEN_BLOCKS,
            "only": [str(x).upper() for x in (only or
                                              ["G1", "G2", "G3", "G4", "G5", "G6",
                                               "G7", "G11", "G13"])],
            "characters": [str(x) for x in (cfg.get("characters_needing_anchor") or [])],
            "theme": args.get("theme"), "batch_id": args.get("batch_id"),
            "project": cfg.get("project"), "project_aliases": cfg.get("project_aliases"),
            "output_root": str(ctx.get("batch_dir") or cfg.get("output_root") or "")}
    spec["run_decisions"] = collect_run_decisions(
        cfg, spec["project"], args, ctx.get("explicit_args"))
    rep = run_checks(spec)
    for lv, gate, text in rep.items:
        if lv != "ok":
            log(ctx, f"[preflight:{gate}][{'WARN' if lv == 'warn' else 'ERROR'}] {text}")
    if rep.errors:
        # 2026-10-19 新功能④：娱乐流预览档允许 error 降级为 warn。
        # 🔴 这里读的必须是**具体能力旗标** `allow_degrade`，不是 `tier` ——
        #   设计不变式 I12 要求 tier 的展开只在 run.py 入口做一次，
        #   tasks 里一旦写 `if tier == "play"` 就变成了"每个档位都要在任务层加分支"，
        #   档位与任务从此耦死（这正是 oneshot 与 engine 两套闸口径分叉的老路）。
        # 降级≠绕过：error 一条不落地进日志，且在批准台账留字据，事后能查"这批是降级放行的"。
        #
        # 但**结构性 error 不参与降级**（10-24 P7 负例暴露的）：像"只给音频没给图/视频"
        # "槽位数对不上官方上限""帧数越界"这类，不是质感瑕疵，是这张提交图**根本组不出来**；
        # 预览档放它过去，只会让它走到更远的地方才炸——实际就是先真把 ComfyUI 拉起来、
        # 再在建图阶段抛 ValueError，白等 64 秒的服务装载。判据在 check_preflight.Report.HARD_GATES。
        hard = list(getattr(rep, "hard_errors", []) or [])
        if hard:
            raise RuntimeError(
                "跑前自审未通过（结构性问题，预览档也不放行）：\n" +
                "\n".join(f"  ✗ [{g}] {t}" for g, t in hard) +
                "\n这类是「素材/参数组合不出合法提交图」，与质感无关；"
                "\n真要绕过只能临时设 config.yaml preflight: off（自担风险，且会在台账留字据）。")
        ad = str((ctx.get("args") or {}).get("allow_degrade", "")).lower()
        if ad in ("true", "1", "yes", "on"):
            record_gate_bypass(cfg, str(cfg.get("project") or ""),
                               str(ctx.get("workflow") or ""),
                               "args.allow_degrade=true（娱乐流预览档，由 run.py --tier play 展开）",
                               gates=sorted({g for _, g, _t in rep.errors}),
                               by="tier:play")
            log(ctx, "[preflight][DEGRADE] 预览档放行：error %d 条**全部照记**如下，本批不进正身 ⇒ "
                     "要正式出片请改跑 --tier draft" % len(rep.errors))
            for _lv, g, text in rep.errors:
                log(ctx, "  ✗ [%s] %s" % (g, text))
            return
        raise RuntimeError("跑前自审未通过（G 类）：\n" +
                           "\n".join(f"  ✗ [{g}] {t}" for _, g, t in rep.errors) +
                           "\n修完再跑；确要绕过请临时设 config.yaml preflight: off（并自担风险）。")
    # 过了闸才落台账：这批「由人给过的值」按内容摘要绑定，
    # 提示词/参考图/尺寸一变 digest 就变，旧决定不会被下一批沿用（同人工关口的规矩）。
    if "G13" in spec["only"]:
        rd = spec.get("run_decisions") or {}
        miss = record_run_decisions(
            cfg, spec.get("project"), str(ctx.get("workflow") or ""), "G13",
            content_digest(digest_parts(spec["prompt"], spec["refs"], spec["ref_videos"],
                                        spec["w"], spec["h"], spec["length"],
                                        spec["lora"], spec["theme"])),
            rd.get("values") or {}, rd.get("required") or (), rd.get("sources") or {})
        log(ctx, ("[G13] 这批运行决定已落台账（按内容摘要绑定，改提示词即失效重来）"
                  if not miss else
                  "[G13][WARN] 台账里这批仍缺 %d 槽：%s" % (len(miss), "、".join(miss))))
    log(ctx, f"[preflight] 通过（warn {len(rep.warns)} 条，已记日志）")


@task("video")
def t_video(p, ctx):
    """ComfyUI 出视频（H3 等）。params: workflow(模板相对路径) / prompt /
    ref_images(参考图路径列表，会拷进 ComfyUI input 目录) / width / height / length(帧数) /
    steps / lora / lora_strength / seed(可空=随机) / prefix / stage(落进批次夹子目录，默认 video) /
    timeout。产物收 mp4（含 subfolder），**不做图片的尺寸/废图校验**。服务未运行时自动启动。"""
    raise_if_cancel_requested(ctx, "t_video:before_preflight")
    cfg = ctx["cfg"]["comfyui"]
    tpl_path = Path(ctx["wf_root"]) / p["workflow"]
    tpl = load_template(ctx, p["workflow"])

    def _lst(v):
        if v in (None, ""):
            return []
        return [x.strip() for x in v.split(",") if x.strip()] if isinstance(v, str) else list(v)

    refs = _lst(p.get("ref_images"))
    ref_videos = _lst(p.get("ref_videos"))
    p = dict(p)
    p["prompt"] = resolve_prompt(p)
    # 跑前自审（G1–G7 + G11）：先校验再拉起服务 —— 不该为了当场报错去占 GPU
    preflight_or_die(p, ctx, refs, ref_videos, tpl_path)
    base = ensure_comfyui(ctx, relay=bool(p.get("_relay_chain") or p.get("_relay_mode")))

    # 参考图拷进 ComfyUI input 目录（图内 LoadImage 只认文件名）
    input_dir = Path(cfg.get("input_dir", r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"))
    input_dir.mkdir(parents=True, exist_ok=True)
    extra = {}
    for i, src in enumerate(refs, 1):
        sp = Path(src)
        if not sp.exists():
            raise RuntimeError(f"参考图不存在: {sp}")
        # W5b：文件名带内容哈希 ⇒ 同名不同图不会互相覆盖（归档两端可对账）
        nm = f"wfref_{i}_{content_hash8(sp)}_{sp.name}"
        shutil.copy2(sp, input_dir / nm)
        extra[f"__REF{i}__"] = nm
    # R11 接力模板的链级占位（__CHAIN__/__CANDIDATE__/__REV__/__LOW_W__...）由调用方带进来
    extra.update(dict(p.get("_extra_rep") or {}))
    refv_names = []
    for j, src in enumerate(ref_videos, 1):
        sp = Path(src)
        if not sp.exists():
            raise RuntimeError(f"参考视频不存在: {sp}")
        nm = f"wfrefv_{j}_{content_hash8(sp)}_{sp.name}"
        shutil.copy2(sp, input_dir / nm)
        refv_names.append(nm)
    # W4c：两路参考音频（参考片原声 / 独立音频）同样先拷进 input 再按名挂槽
    def _copy_media(items, tag):
        names = []
        for j, src in enumerate(items, 1):
            sp = Path(src)
            if not sp.exists():
                raise RuntimeError(f"{tag}不存在: {sp}")
            nm = f"wf{tag}_{j}_{content_hash8(sp)}_{sp.name}"
            shutil.copy2(sp, input_dir / nm)
            names.append(nm)
        return names
    refva_names = _copy_media(_lst(p.get("ref_video_audios")), "refva")
    refa_names = _copy_media(_lst(p.get("ref_audios")), "refa")

    seed = p.get("seed")
    seed = random.randint(0, 2**31 - 1) if seed in (None, "") else int(seed)
    dynamic = bool(((tpl.get("_meta") or {}).get("dynamic_reference_slots")))
    ref_materials = ({"images": [extra[f"__REF{i}__"] for i in
                                 range(1, len(refs) + 1)],
                      "videos": refv_names, "video_audios": refva_names,
                      "audios": refa_names} if dynamic else None)
    graph = build_graph_video(tpl, p, seed, extra_rep=extra, ref_videos=refv_names,
                              ref_materials=ref_materials)

    out_dir = Path(cfg["output_dir"])
    pre_snapshot = set(f for f in out_dir.rglob("*") if f.is_file())
    t0 = time.time()
    r = SESSION.post(base + "/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"任务提交失败: {r.text[:300]}")
    pid_ = r.json()["prompt_id"]
    # W5b：拿到 prompt_id **立刻**落盘（完整 graph＋本次参数＋提交意图），
    # 再开始轮询。超时/断电后这份记录就是"那次到底投了什么"的唯一凭据。
    _sub, _sub_path = persist_submission(
        ctx, pid_, graph, p, stage=str(p.get("stage") or "video"),
        intent="relay_parent_submit" if p.get("_relay_chain") else "submit",
        extra={"seed": seed, "submission_http": r.status_code})
    log(ctx, f"[video] 提交 prompt_id={pid_}  seed={seed}  帧数={p.get('length')}  "
             f"参考图{len(refs)}张  参考视频{len(refv_names)}段  "
             f"音频{len(refa_names)}＋{len(refva_names)}段  快照={_sub_path.name}")
    if p.get("_relay_chain"):
        # R11 父段入链：产物不走 history outputs，专用轮询读链 manifest
        accepted, cand_id, rev = _poll_relay_parent(
            ctx, base, pid_, int(p.get("timeout", 3600)), str(p["_relay_chain"]))
        got = [accepted]
        relay_info = {"chain_id": str(p["_relay_chain"]), "candidate_id": cand_id,
                      "revision": rev, "contract_sha": _RELAY_CONTRACT_SHA}
    else:
        got = poll_history(ctx, base, pid_, int(p.get("timeout", 3600)),
                           pre_snapshot=pre_snapshot,
                           expected_prefix=str(p.get("prefix", "wf")))
        relay_info = None
    if not got:
        raise RuntimeError(f"ComfyUI 没产出视频文件（prompt_id={pid_}）")
    if relay_info:
        # R11 接力父段的入链产物**不许搬**：链 manifest 声明的 video_path 就指向它，
        # 搬走＝断链（续段 Source 会 FileNotFound，2026-10-15 E2E 实测）。
        # raw 保留链内原路径，后续 QC/归一化只读不搬。
        log(ctx, f"[relay] 入链产物留原处（不 relocate）：{got[0]}")
    else:
        got = relocate(got, Path(ctx["batch_dir"]) / str(p.get("stage", "video")), ctx["log"])
    log(ctx, f"[video] 完成 {len(got)} 个（{time.time() - t0:.1f}s）")
    return {"files": got, "seed": seed, "count": len(got),
            "elapsed": round(time.time() - t0, 1),
            "width": _explicit_size(p, ctx, "video 出片")[0],
            "height": _explicit_size(p, ctx, "video 出片")[1],
            "length": int(p.get("length", 124)), "fps": float(p.get("fps", 24)),
            "steps": int(p.get("steps", 8)), "prompt": str(p.get("prompt", "")),
            "relay": relay_info}


# ---------------------------------------------------------------- H3 一键成片
# ⚠ profile 里**只有通道侧的事实**（步数与 LoRA 的配对、分块、片长），
#   刻意不放 width/height —— 10-03 用户裁「删除硬编码，全部强制要求显式配置」，
#   画布尺寸是创作决定，以前写死 736x416 等于代码替每一批决定了构图。
#   现在这三处都得从**人写的配置**里拿，顺序：镜头 manifest 的 defaults / 单镜 generation
#   → 这一步 params → 顶层 args / --set；一处都不给就报错（见 t_h3_movie 里的显式校验）。
_H3_PROFILES = {
    # 默认生产档：已在本机现有工作流中验证模型/LoRA/步数配对。
    "stable_t8": {"length": 124, "steps": 8,
                  "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                  "lora_strength": 1.0, "head_chunks": 4},
    # 快速预演档：只能与 4-step LoRA 配套，禁止拿 8-step LoRA 直接减步数。
    "preview_t4": {"length": 124, "steps": 4,
                   "lora": "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
                   "lora_strength": 1.0, "head_chunks": 4},
    # 打斗快速档：8-step Turbo 提速 LoRA 链在内容 LoRA(Bunny) 之前（底模→Turbo→Bunny→Attention）。
    # 实测：与 20 步 Bunny0.5 相比 2.07x 提速（81.5s vs 168.5s），画质 VL 判「基本持平」。
    "fight_fast8": {"length": 124, "steps": 8,
                    "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                    "lora_strength": 1.0,
                    "lora2": "Bunny_weapon_combatV1.safetensors", "lora2_strength": 0.5,
                    "head_chunks": 4},
}


def _parse_degrade_sizes(v):
    """把「显式声明的降级画布梯子」解析成 [(w, h), ...]：写法 `736x416,640x352`。

    没写 ⇒ 返回空列表，OOS 时就只加 head_chunks，**不自动改画布尺寸**。
    写错 ⇒ 直接报错，不静默当成"没配"（静默会让人在显存炸了之后以为会自动降）。
    """
    s = str(v or "").strip()
    if not s or s.lower() in ("none", "[]"):
        return []
    out = []
    for part in s.split(","):
        part = part.strip().lower().replace("×", "x")
        if not part:
            continue
        m = re.fullmatch(r"(\d{2,5})x(\d{2,5})", part)
        if not m:
            raise RuntimeError("degrade_sizes 写法不对：%r（要像 736x416,640x352）" % part)
        out.append((int(m.group(1)), int(m.group(2))))
    return out


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _media_tools(ctx):
    cfg = ctx.get("cfg") or {}
    tools = cfg.get("media_tools") or {}
    ffmpeg = Path(str(tools.get("ffmpeg") or (Path(__file__).resolve().parent.parent / "tools" / "ffmpeg.exe")))
    ffprobe = Path(str(tools.get("ffprobe") or (Path(__file__).resolve().parent.parent /
                                                 "LivePortrait-main" / "bin" / "ffprobe.exe")))
    for label, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if not path.is_file():
            raise RuntimeError(f"{label} 不存在: {path}；一键成片不能跳过机械质检")
    return str(ffmpeg), str(ffprobe)


def _run_media(cmd, timeout=1800):
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout,
                          creationflags=CREATE_NO_WINDOW)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1200:]
        raise RuntimeError(f"媒体命令失败 code={proc.returncode}: {tail}")
    return proc


def probe_video(path, ctx, decode=False):
    """ffprobe 结构检查；可选完整解码。返回可写入 manifest 的确定性媒体数据。"""
    ffmpeg, ffprobe = _media_tools(ctx)
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 1024:
        raise RuntimeError(f"视频不存在或过小: {p}")
    cmd = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)]
    raw = _run_media(cmd, timeout=120).stdout
    try:
        info = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"ffprobe 返回不可解析: {type(e).__name__}: {e}")
    streams = info.get("streams") or []
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos:
        raise RuntimeError(f"没有视频流: {p}")
    v = videos[0]

    def _rate(value):
        try:
            a, b = str(value or "0/1").split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0

    duration = float((info.get("format") or {}).get("duration") or v.get("duration") or 0.0)
    # 帧率以 r_frame_rate 为准：concat -c copy 后 AAC priming 会把 avg_frame_rate
    # 稀释成 23.6 之类，但视频流真实仍是 24/1。
    rfps = _rate(v.get("r_frame_rate"))
    afps = _rate(v.get("avg_frame_rate"))
    fps = rfps if (1.0 <= rfps <= 240.0) else afps
    meta = {"file": str(p), "size": p.stat().st_size,
            "width": int(v.get("width") or 0), "height": int(v.get("height") or 0),
            "fps": round(fps, 4),
            "frames": int(v.get("nb_frames") or 0), "duration": round(duration, 4),
            "video_codec": v.get("codec_name"), "has_audio": bool(audios),
            "audio_codec": audios[0].get("codec_name") if audios else None,
            "sample_rate": int(audios[0].get("sample_rate") or 0) if audios else 0,
            "channels": int(audios[0].get("channels") or 0) if audios else 0}
    if decode:
        proc = _run_media([ffmpeg, "-v", "error", "-i", str(p), "-f", "null", "-"],
                          timeout=max(300, int(duration * 20 + 60)))
        meta["decoded"] = True
        # R8-05（10-03 用户裁「收尾必须逐帧计数」）：容器的 `nb_frames`／`Duration` 会撒谎——
        # AAC priming 与 `-c copy` 都能把它报成 23.6fps 那种假值。上面这趟完整解码本来就要跑，
        # 顺手把解码器自己数出来的 `frame=` 收回来，作为**唯一可信的帧数**进 manifest。
        # ⚠ 这一版**只留痕不拦人**：现役产物没有一份标定过"逐帧数 vs 期望帧数"的容差，
        #    拿没标定的绝对线去 error 就是天天误杀（同"绝对带只报不拦"那条裁定）。
        #    等有几批真实数据后再谈要不要升成硬门。
        counted = [int(x) for x in re.findall(r"frame=\s*(\d+)", proc.stderr or "")]
        if counted:
            meta["frames_decoded"] = int(max(counted))
            container = int(meta.get("frames") or 0)
            if container and meta["frames_decoded"] != container:
                meta["frames_container_disagrees"] = {"container": container,
                                                     "decoded": meta["frames_decoded"]}
    return meta


H3_NATIVE_AUDIO = (32000, 2)     # 官方 README:77：H3 输出 32kHz 立体声。
#   10-24 逐条 ffprobe 过盘上**全部** 8 个在产成片本体（不抽样），8/8 = aac,32000,2：
#   `D:\AIWorkflow\evidence\QA_20261024\audio_spec_probe.txt`（脚本 `probe_audio_spec.py` 可复跑）。
#   之前注释写"6 份实测"是口头账（盘上只有 2 份留痕），已按质量核查 P1-⑤ 换成凭据。
H3_CONCAT_AUDIO = (48000, 2)     # 不是官方规格，是**我们自己**在 :1750/:1773 用
                                 # `-ar 48000 -ac 2` 重采样的结果（构造性事实）⇒ 拼接成片按 48k 判。


def _video_qc(path, ctx, require_audio=True, expected_fps=24.0, expected_length=None,
              expect_audio_spec=None):
    """机械硬门：完整解码、AV 流、fps/时长、音轨规格、长黑帧和长冻结。审美判断留给人。

    `expect_audio_spec=(采样率, 声道)`：原生单镜传 H3_NATIVE_AUDIO、拼接成片传
    H3_CONCAT_AUDIO。此前这两个数**只采集不判**（官方 README 写的是 32kHz 立体声，
    零校验＝官方规格在我们这儿是摆设）。
    """
    ffmpeg, _ = _media_tools(ctx)
    meta = probe_video(path, ctx, decode=True)
    dis = meta.get("frames_container_disagrees")
    if dis:
        # 只留痕：容器说一套、解码器数出来另一套，这件事**必须看得见**，但本版不据此停批
        # （没有标定过的容差就没有拦人的资格——见 probe_video 里那段注释）。
        log(ctx, f"[R8-05][报] 帧数留痕：容器 nb_frames={dis['container']}，"
                 f"完整解码实数={dis['decoded']}（差 {dis['decoded'] - dis['container']} 帧）"
                 f"——以解码实数为准，本条不拦")
    if require_audio and not meta["has_audio"]:
        raise RuntimeError(f"成片没有音轨: {path}")
    if expected_fps and abs(meta["fps"] - float(expected_fps)) > 0.15:
        raise RuntimeError(f"帧率 {meta['fps']} ≠ 期望 {expected_fps}: {path}")
    if expect_audio_spec and meta["has_audio"]:
        want_sr, want_ch = int(expect_audio_spec[0]), int(expect_audio_spec[1])
        got_sr, got_ch = int(meta.get("sample_rate") or 0), int(meta.get("channels") or 0)
        if (got_sr, got_ch) != (want_sr, want_ch):
            raise RuntimeError(
                f"音轨规格 {got_sr}Hz/{got_ch}ch ≠ 期望 {want_sr}Hz/{want_ch}ch: {path}"
                f"（官方 README 的 32kHz 立体声与拼接重采样目标都是硬口径，不是参考值）")
        meta["audio_spec_ok"] = [got_sr, got_ch]
    if expected_length and meta["duration"]:
        want = float(expected_length) / float(expected_fps or 24)
        if abs(meta["duration"] - want) > max(0.75, want * 0.12):
            raise RuntimeError(f"时长 {meta['duration']:.2f}s 与 {expected_length}帧/{expected_fps}fps "
                               f"({want:.2f}s) 偏差过大: {path}")
    filt = "blackdetect=d=0.8:pix_th=0.03,freezedetect=n=0.002:d=2.0"
    proc = _run_media([ffmpeg, "-hide_banner", "-i", str(path), "-vf", filt,
                       "-an", "-f", "null", "-"],
                      timeout=max(300, int(meta["duration"] * 20 + 60)))
    text = proc.stderr or ""
    black = [float(x) for x in re.findall(r"black_duration:([0-9.]+)", text)]
    frozen = [float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", text)]
    meta["black_segments"] = black
    meta["freeze_segments"] = frozen
    if black and max(black) > 1.5:
        raise RuntimeError(f"检测到连续黑帧 {max(black):.2f}s: {path}")
    if frozen and max(frozen) > 3.0:
        raise RuntimeError(f"检测到连续冻结 {max(frozen):.2f}s: {path}")
    # 运动画像（2026-10-07 加，留痕期 alarm_only）：只写 meta、只打印，**不 raise**。
    # 逐帧位移量的是"速度"，说话/缓缓抬头这类慢速连续运动会被单尺误判成冻结
    # （第1集32镜实测：15条被误判、真静止只有1条），所以必须和半秒幅值成对看。
    try:
        import importlib.util as _ilu
        import os as _os
        _spec = _ilu.spec_from_file_location(
            "motion_profile",
            _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "motion_profile.py"))
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mp = _mod.profile(path)
        if _mp:
            meta["motion_profile"] = _mp
            if _mp["verdict"] == "真静止":
                print(f"[motion][alarm_only] {path} 速度{_mp['speed']}/幅值{_mp['amplitude']} px 双低，"
                      f"判真静止：只留痕不拦批（阈值表 motion_dead_*，alarm_only）")
    except Exception as _e:  # 运动画像失败不能拖垮硬门
        meta["motion_profile"] = {"error": str(_e)[:160]}
    meta["qc_passed"] = True
    return meta


def _normalize_clip(src, dst, ctx, width=None, height=None, fps=24,
                    loudness=-16.0, true_peak=-1.5, trim_start_seconds=None):
    if width is None or height is None:
        raise RuntimeError("归一化尺寸必须由调用方显式给（10-03 裁定：代码不留兜底默认）")
    ffmpeg, _ = _media_tools(ctx)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:black,"
          f"format=yuv420p")
    # 输入即 24fps（H3 的 CreateVideo 固定 fps=24，且单镜 QC 已校验），不再叠加
    # fps filter：它会把 124 帧对齐成 123 帧，造成时长/fps 漂移并连锁污染拼接产物。
    af = f"aresample=48000,loudnorm=I={float(loudness)}:TP={float(true_peak)}:LRA=11"
    cmd = [ffmpeg, "-y", "-v", "error"]
    if trim_start_seconds:  # R11 续段：剥掉头部的上下文前缀（重编码路径，输入寻址帧级精确）
        cmd += ["-ss", f"{float(trim_start_seconds):.6f}"]
    cmd += ["-i", str(src), "-vf", vf, "-af", af,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(dst)]
    _run_media(cmd, timeout=3600)
    return str(dst)


def _concat_clips(clips, dst, ctx):
    ffmpeg, _ = _media_tools(ctx)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    listing = dst.with_suffix(".concat.txt")
    lines = []
    for clip in clips:
        # concat demuxer 的单引号转义；Windows 路径统一为 /。
        val = str(Path(clip).resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{val}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        # 重编码而非 -c copy：彻底规范化时间戳，消除 AAC priming/padding 造成的
        # 时长与帧率漂移（concat -c copy 会让 ffprobe 报出 23.6 或 48 这类假帧率）。
        _run_media([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(dst)],
                   timeout=3600)
    finally:
        try:
            listing.unlink()
        except OSError:
            pass
    return str(dst)


def _load_shot_manifest(path):
    fp = Path(str(path))
    if not fp.is_file():
        raise RuntimeError(f"镜头 manifest 不存在: {fp}")
    data = json.loads(fp.read_text(encoding="utf-8-sig"))
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list) or not shots:
        raise RuntimeError("镜头 manifest 必须包含非空 shots 数组")
    seen = set()
    for i, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            raise RuntimeError(f"shots[{i}] 不是对象")
        sid = str(shot.get("id") or f"shot{i:02d}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid) or sid in seen:
            raise RuntimeError(f"镜头 id 非法或重复: {sid}")
        shot["id"] = sid
        seen.add(sid)
        events = shot.get("events") or []
        subjects = shot.get("subjects") or []
        if isinstance(events, list) and len(events) > 2:
            raise RuntimeError(f"{sid}: 单镜事件超过2个，先拆镜再生成")
        if isinstance(subjects, list) and len(subjects) > 2:
            raise RuntimeError(f"{sid}: 单镜主体超过2个，H3稳定性风险过高")
        if not (str(shot.get("prompt") or "").strip() or shot.get("prompt_file")):
            raise RuntimeError(f"{sid}: prompt/prompt_file 至少提供一个")
        refs = shot.get("ref_images") or []
        if isinstance(refs, str):
            refs = [x.strip() for x in refs.split(",") if x.strip()]
        if not refs:
            raise RuntimeError(f"{sid}: 首帧工作流必须提供 ref_images")
        shot["ref_images"] = refs
    return data


def _retry_ladder(base, degrade=()):
    """显存吃紧时的重试梯子：**只有人显式声明过的画布**才会出现在梯子里。

    10-03 之前这里写死了 736x416 / 640x352 两级——OOM 自动换画布看着省事，
    实际是代码在一次失败重试里替人改了构图尺寸和清晰度档位。现在：
      · `degrade` 来自步骤 params / args 的 `degrade_sizes`（写法 `736x416,640x352`）；
      · 没声明 ⇒ 梯子只加 head_chunks（那是显存分块，不是画面），画布一律不动；
      · 声明了但比当前还大 ⇒ 那级没有"降"的意义，跳过（不做绝对值比较之外的判断）。
    步数和 LoRA 的配对永远不动（配错会"能跑但质量错"）。
    """
    cands = [dict(base)]
    if int(base.get("head_chunks", 4)) < 8:
        cands.append(dict(base, head_chunks=8))
    bw = int(base.get("width") or 0)
    bh = int(base.get("height") or 0)
    if bw and bh:
        for (w, h) in degrade or ():
            if w * h < bw * bh:
                cands.append(dict(base, width=w, height=h, head_chunks=8))
    out, keys = [], set()
    for c in cands:
        key = (c.get("width"), c.get("height"), c.get("length"), c.get("steps"),
               c.get("lora"), c.get("head_chunks"))
        if key not in keys:
            keys.add(key); out.append(c)
    return out


def _is_resource_error(exc):
    text = str(exc).lower()
    return any(x in text for x in ("out of memory", "cuda", "hostbuffer", "1450",
                                    "系统资源不足", "显存", "memory allocation"))


def _free_comfyui(ctx):
    try:
        base = (ctx["cfg"]["comfyui"]["base_url"]).rstrip("/")
        SESSION.post(base + "/free", json={"unload_models": True, "free_memory": True}, timeout=20)
    except Exception:
        pass


# ---------------------------------------------------------------- R11 段间接力（2026-10-15 用户裁"接进引擎"）
# 规则真源：E:\本地工作流规范手册\20_通用规范层\R11_段间接续生成.md
# 镜对承接关系＝[人]判（R11-01）：manifest 顶层 "relay_pairs": [["镜N","镜N+1"], ...]
_RELAY_CONTRACT_SHA = "fdb12aed619aa187ba462d143226195f7398599964765be02f334ee2bd7d6616"
_RELAY_TPL_PARENT = "comfy/h3_relay_parent_api.json"
_RELAY_TPL_CONT = "comfy/h3_relay_cont_api.json"
_RELAY_SEAM_TOOL = Path("D:/AIWorkflow/tools/post/seam_check.py")


def _relay_pairs(manifest):
    """解析并校验 relay_pairs（[人]判的镜对，机器只执行）：父镜必须排在子镜前、
    每镜最多当一次子镜、id 必须存在。返回 {子镜id: 父镜id}。"""
    pairs = manifest.get("relay_pairs") or []
    if not pairs:
        return {}
    ids = [s["id"] for s in manifest["shots"]]
    order = {sid: i for i, sid in enumerate(ids)}
    child_of = {}
    for pr in pairs:
        parent, child = str(pr[0]), str(pr[1])
        for sid in (parent, child):
            if sid not in order:
                raise RuntimeError(f"relay_pairs 引用了不存在的镜 id: {sid}（现有 {ids}）")
        if order[child] <= order[parent]:
            raise RuntimeError(f"relay_pairs [{parent},{child}]: 父镜必须排在子镜前面")
        if child in child_of:
            raise RuntimeError(f"relay_pairs: 镜 {child} 被声明为两对接力的子镜")
        if child == parent:
            raise RuntimeError("relay_pairs: 镜不能和自己接力")
        child_of[child] = parent
    return child_of


def _relay_server_guard(ctx):
    """接力批开跑前确认存活服务的 attention 配置。服务进程查不到自己的启动参数，
    靠 ensure_comfyui 落的启动标记（logs\\comfyui_launch_flags.json）判读；
    手工启动服务的人也要写同名文件（或让引擎拉起）。无标记/带 sage 一律拦下——
    带 sage 跑 EXPT8 不是"可能崩"，是必崩且进程直接死（R11-01 硬条件3）。"""
    cfg = ctx["cfg"]["comfyui"]
    mf = Path(cfg.get("log", "comfyui.log")).parent / "comfyui_launch_flags.json"
    cmd = ""
    if mf.is_file():
        try:
            cmd = str(json.loads(mf.read_text(encoding="utf-8")).get("cmd") or "")
        except Exception:
            pass
    if cmd and "sage" not in cmd.lower():
        return
    raise RuntimeError(
        "接力批要求 ComfyUI 以【无 sage】启动（R11-01 硬条件3），现在无法确认：\n"
        f"  启动标记缺失或带 sage（{mf}）。\n"
        "  修法：停掉 8189 的 python 后用无 sage 命令重启，例如——\n"
        "  cd /d D:\\AIWorkflow\\ComfyUI_H3 && python_embeded\\python.exe -s ComfyUI\\main.py "
        "--windows-standalone-build --reserve-vram 6.0 --port 8189 "
        "--output-directory D:\\AIWorkflow\\ComfyUI_H3\\output\n"
        "  或让引擎拉起（config.yaml 的 comfyui.launch_cmd_relay），并确保 "
        "logs\\comfyui_launch_flags.json 记录了实际启动命令。")


def _safe_run_id(run_id):
    """链 id 要落盘进路径：只留 ASCII 字母数字下划线连字符。"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(run_id or "run"))[:40]


def _poll_relay_parent(ctx, base, prompt_id, timeout, chain_id):
    """父段入链的专用轮询：入链产物不走 history outputs（Candidate/Accept 只回字符串），
    poll_history 会空转到超时。这里等 status 完成，然后读链 manifest 拿正式产物。"""
    cfg = ctx["cfg"]["comfyui"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            r = SESSION.get(f"{base}/history/{prompt_id}", timeout=10)
            if r.status_code != 200:
                continue
            h = (r.json() or {}).get(prompt_id)
        except Exception:
            continue
        if not h:
            continue
        st = h.get("status") or {}
        if st.get("status_str") == "error":
            raise RuntimeError("ComfyUI 执行出错(父段入链): "
                               + json.dumps(st.get("messages", []), ensure_ascii=False)[:400])
        if st.get("completed"):
            mdir = Path(cfg["output_dir"]) / "minimax_h3_t8_long_video" / chain_id
            mpath = mdir / "manifest.json"
            if not mpath.is_file():
                raise RuntimeError(f"父段执行完成但找不到链 manifest: {mpath}")
            m = json.loads(mpath.read_text(encoding="utf-8"))
            segs = m.get("segments") or {}
            entry = segs["0"] if isinstance(segs, dict) else segs[0]
            video = mdir / entry["video_path"]
            if not video.is_file():
                raise RuntimeError(f"链 manifest 里的成片不在盘上: {video}")
            return (str(video), str(entry["candidate_id"]),
                    int(entry.get("revision") or m.get("revision") or 1))
    raise RuntimeError(f"父段入链超时（>{timeout}s，prompt_id={prompt_id}）")


def _relay_prefix_frames(cont_path, parent_path, ctx, ctx_frames):
    """续段产物头部有上下文前缀（≈ctx_frames 帧的父段尾巴复读），拼进成片前必须剥掉。
    用前段尾 5 帧与续段头部的滑动 NCC 定位剥离点（R11-02 同源尺）；cv2 不可用时
    退回 ctx_frames 并打警告（最多差 1 帧，接缝报告里会留剥离读数对账）。"""
    try:
        import cv2  # noqa: F401
    except Exception:
        log(ctx, f"[relay] ⚠ 无 cv2，前缀剥离退回 ctx={ctx_frames} 帧（建议装 opencv）")
        return int(ctx_frames)
    try:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_seam_check_r11", _RELAY_SEAM_TOOL)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cont = mod.read_video(cont_path)
        parent = mod.read_video(parent_path)
        cont_t, info = mod.strip_context_prefix(cont, parent, None)  # None=自动探测
        log(ctx, f"[relay] 前缀剥离：{info}")
        return int(info["trimmed"])
    except Exception as e:
        log(ctx, f"[relay] ⚠ 前缀检测失败({e})，退回 ctx={ctx_frames}")
        return int(ctx_frames)


def _relay_seam_report(parent_video, cont_video, out_path, ctx):
    """R11-02 接缝双尺（B 行：链内父段尾 ↔ 剥前缀后续段头），只报不拦。"""
    if not _RELAY_SEAM_TOOL.is_file():
        log(ctx, f"[relay] ⚠ 找不到 {_RELAY_SEAM_TOOL}，跳过接缝测量")
        return None
    cmd = [sys.executable, str(_RELAY_SEAM_TOOL),
           "--chain-prev", str(parent_video), "--cont", str(cont_video),
           "--out", str(out_path)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                       encoding="utf-8", errors="replace", check=True)
        rep = json.loads(Path(out_path).read_text(encoding="utf-8"))
        b = rep.get("B_continuation") or {}
        log(ctx, f"[relay][R11-02][报] 接缝双尺：NCC比 {b.get('ncc_ratio')} / "
                 f"光流比 {b.get('flow_ratio')}（判读线 ≥0.9 无缝、≤1.5 顺滑；"
                 f"完整读数 {out_path}）")
        return {"report": str(out_path), "ncc_ratio": b.get("ncc_ratio"),
                "flow_ratio": b.get("flow_ratio")}
    except Exception as e:
        log(ctx, f"[relay] ⚠ 接缝测量失败（不影响成片）: {e}")
        return None


@task("h3_movie")
def t_h3_movie(p, ctx):
    """多镜一键成片：逐镜 H3 → 机械质检 → 按显式成片尺寸标准化 → 硬切拼接。

    每镜完成即写 h3_movie_state.json；工作流中断后用 --resume 重跑本步骤时，会跳过
    已通过质检的镜头。默认 stable_t8；preview_t4 只配专用 4-step LoRA。
    单镜生成尺寸与成片尺寸（output_width/output_height）**都要人显式给**，见 10-03 裁定。
    每镜后期（剥前缀/接缝/1080p 归一/质检）在后台线程与下一镜渲染重叠（2026-10-15 提速批）。
    """
    manifest = _load_shot_manifest(p.get("manifest"))
    child_of = _relay_pairs(manifest)
    relay_ctx = int(p.get("relay_ctx") or 22)
    if child_of:
        _relay_server_guard(ctx)
        log(ctx, f"[relay] R11 接力批：{len(child_of)} 对 {sorted(child_of.items())}；"
                 f"ctx={relay_ctx}。服务器无 sage 标记确认通过")
    profile_name = str(p.get("profile") or manifest.get("profile") or "stable_t8")
    if profile_name not in _H3_PROFILES:
        raise RuntimeError(f"未知 H3 profile: {profile_name}（可用 {sorted(_H3_PROFILES)}）")
    profile = dict(_H3_PROFILES[profile_name])
    profile.update(manifest.get("defaults") or {})
    profile.update({k: p[k] for k in ("width", "height", "length", "steps", "lora",
                                         "lora_strength", "lora2", "lora2_strength",
                                         "lora3", "lora3_strength",
                                         "head_chunks")
                    if p.get(k) not in (None, "")})
    # 硬约束：已知 LoRA 名称必须与步数一致，避免“能跑但质量错”的静默事故。
    lname = str(profile.get("lora") or "").lower()
    if ("4step" in lname and int(profile["steps"]) != 4) or (
            "8step" in lname and int(profile["steps"]) != 8):
        raise RuntimeError(f"LoRA/steps 不配对: {profile.get('lora')} + {profile['steps']} steps")

    def shot_gen(shot):
        """把「这一镜最终会用的生成参数」合出来，并**逐镜**校验尺寸是显式配的。

        尺寸可以来自四处（都是人写的）：profile ← manifest 顶层 defaults ← manifest
        单镜 generation ← 这一步 params / 顶层 args / --set。任何一镜凑不齐就停在那一镜，
        绝不出现"批里 6 镜按 736x416 跑、第 7 镜按别的跑"这种没人签字的混合批次。
        """
        m = dict(profile)
        m.update(shot.get("generation") or {})
        for k in ("width", "height"):
            if m.get(k) in (None, ""):
                try:
                    m[k] = _need_explicit_int(p, ctx, k, "H3 单镜生成尺寸（%s）" % shot["id"])
                except RuntimeError as e:
                    raise RuntimeError(
                        str(e) +
                        f"\n  ③ 这条流还有一种给法：在镜头 manifest 顶层 defaults 里写 {k}: <像素>，"
                        f"或在该镜的 generation 里单独写"
                        f"（examples/h3_movie_manifest.example.json 的 defaults 就是这种写法）"
                    ) from e
            m[k] = int(m[k])
        if m["width"] % 32 or m["height"] % 32:
            raise RuntimeError("%s: H3 宽高必须是 32 的倍数（现 %dx%d）"
                               % (shot["id"], m["width"], m["height"]))
        return m

    batch = Path(ctx["batch_dir"])
    state_path = batch / "h3_movie_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    except Exception:
        state = {}
    state.setdefault("version", 1)
    state.setdefault("run_id", ctx.get("run_id"))
    state.setdefault("profile", profile_name)
    state.setdefault("shots", {})
    state["manifest"] = str(Path(str(p.get("manifest"))).resolve())
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    degrade = _parse_degrade_sizes(p.get("degrade_sizes")
                                   or (ctx.get("args") or {}).get("degrade_sizes"))
    # 成片尺寸只在这里量**一次**：plan、文件名、归一化调用共用同一对数——
    # 分三处各读一遍，万一某处写法漂了就会出现"台账说一个尺寸、产物是另一个尺寸"。
    # ⚠ 这条流的成片键是 output_width/output_height（width/height 是**单镜生成**尺寸，
    #    两个数不是一回事：前者是交付画幅，后者是模型画布）。
    out_w = _need_explicit_int(p, ctx, "output_width", "h3_movie 成片")
    out_h = _need_explicit_int(p, ctx, "output_height", "h3_movie 成片")
    plan = {"profile": profile_name, "defaults": profile, "shots": [],
            "output": {"width": out_w, "height": out_h,
                       "fps": int(p.get("fps", 24))},
            # 梯子里有没有"降画布"这一级，取决于人显式声明了 degrade_sizes
            "degrade_sizes": ["%dx%d" % s for s in degrade],
            "retry_note": ("显式声明了降级画布" if degrade
                           else "未声明 degrade_sizes ⇒ 显存吃紧时只加 head_chunks，画布不动")}
    for shot in manifest["shots"]:
        entry = {"id": shot["id"], "generation": shot_gen(shot),
                 "events": shot.get("events") or [],
                 "subjects": shot.get("subjects") or [],
                 "continuity": shot.get("continuity") or {}}
        if shot["id"] in child_of:
            entry["relay"] = {"role": "child", "parent": child_of[shot["id"]]}
        elif shot["id"] in set(child_of.values()):
            entry["relay"] = {"role": "parent"}
        plan["shots"].append(entry)
    for entry in plan["shots"]:  # R11-01 硬条件2：接力镜画布必须 64 对齐（lift=2×low）
        if entry.get("relay"):
            g = entry["generation"]
            if g["width"] % 64 or g["height"] % 64:
                raise RuntimeError(f"{entry['id']}: 接力镜画布必须 64 对齐"
                                   f"（现 {g['width']}x{g['height']}，如 768x448）")
    _atomic_json(batch / "h3_movie_plan.json", plan)
    if str(p.get("dry_run", False)).lower() in ("true", "1", "yes"):
        log(ctx, f"[h3_movie] dry_run 通过：{len(plan['shots'])} 镜，未启动 ComfyUI")
        return {"files": [str(batch / "h3_movie_plan.json")], "count": len(plan["shots"]),
                "profile": profile_name, "dry_run": True}

    # ---- A5 断点对账（2026-10-15 用户批准接入）--------------------------------
    # state（h3_movie_state.json）仍是断点真源；这行只把"重启/续跑后会发生什么"
    # 摊在日志首屏：跳过几镜、续投哪几镜（以前要逐行翻"↷ 已完成"日志才拼得出来）。
    # glob 崩溃窗口回收在循环内 raw 缺失分支，不在此处。
    _skip_ids = {s["id"] for s in manifest["shots"]
                 if (state["shots"].get(s["id"]) or {}).get("status") == "done"
                 and Path(str((state["shots"][s["id"]]).get("normalized") or "")).is_file()}
    _run_ids = [s["id"] for s in manifest["shots"] if s["id"] not in _skip_ids]
    log(ctx, f"[h3_movie] 断点对账：共 {len(manifest['shots'])} 镜，"
             f"跳过 {len(_skip_ids)}（已完成且归一文件在位）／续投 {len(_run_ids)}"
             + (f"：{'、'.join(_run_ids)}" if _run_ids else ""))

    normalized = []
    # —— 后期重叠（2026-10-15 提速批）——
    # 镜 N 的后期（剥前缀/接缝/1080p 归一/质检）丢给单线程后台池跑，主线程立刻去渲镜 N+1：
    # 这几十秒以前纯串行，现在与下一镜的 GPU 渲染重叠。state 是断点真源，后台线程也写它
    # ⇒ 所有写入用同一把锁串行化；异常在下一镜开渲前/拼接前的 join 处抛出，行为与旧串行版
    # 一致（raw_done 已落盘，resume 安全）。
    import threading
    from concurrent.futures import ThreadPoolExecutor
    _state_lock = threading.Lock()
    _post_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="h3post")
    _post_futures, _post_results = [], {}

    def _save_state():
        with _state_lock:
            _atomic_json(state_path, state)

    def _make_post(idx, sid, raw, rec, shot, parent_sid, parent_raw, relay_role):
        def _run():
            trim_s = None
            if relay_role == "child" and parent_raw and parent_raw.is_file():
                prefix = _relay_prefix_frames(raw, parent_raw, ctx, relay_ctx)
                rec.setdefault("relay", {})["prefix_frames"] = prefix
                trim_s = prefix / float(p.get("fps", 24))
            norm_p = batch / "shots" / sid / "normalized" / ("%s_%dx%d.mp4" % (sid, out_w, out_h))
            _normalize_clip(raw, norm_p, ctx, width=out_w, height=out_h,
                            fps=int(p.get("fps", 24)),
                            loudness=float(p.get("loudness", -16)),
                            true_peak=float(p.get("true_peak", -1.5)),
                            trim_start_seconds=trim_s)
            if relay_role == "child" and parent_raw and parent_raw.is_file():
                sr = _relay_seam_report(parent_raw, raw,
                                        batch / f"relay_seam_{parent_sid}_{sid}.json", ctx)
                if sr:
                    rec["relay"]["seam"] = sr
            rec["normalized"] = str(norm_p)
            # 计划 W5a：归一后也核对 expected_length —— raw 阶段的时长偏差
            # 可能在归一化（去黑边/补帧/音频对齐）里被掩盖，归一后再验一次。
            _exp_len = rec.get("generation", {}).get("length")
            rec["qc"] = _video_qc(norm_p, ctx, require_audio=True,
                                  expected_fps=float(p.get("fps", 24)),
                                  expect_audio_spec=H3_CONCAT_AUDIO,
                                  expected_length=_exp_len and int(_exp_len) or None)
            vl_question = str(shot.get("vl_question") or p.get("vl_question")
                              or manifest.get("vl_question") or "")
            if vl_question:
                rec["vl"] = vl_content_check(norm_p, ctx, vl_question,
                                             int(p.get("vl_n_frames", 5)))
            rec["status"] = "done"
            with _state_lock:
                _post_results[idx] = str(norm_p)
            _save_state()
            log(ctx, f"[h3_movie] ↻ {sid} 后台后期完成（归一+质检，与下一镜渲染重叠）")
            return str(norm_p)
        return _run

    for idx, shot in enumerate(manifest["shots"], 1):
        # 后台后期若已失败：在下一镜开渲之前中止，不白烧一次 GPU
        # W5a 复核修：QC 失败镜会往里塞 None 占位（保持索引对齐），这里必须跳过——
        # 否则"第 1 镜 QC 失败"会让第 2 镜开渲前直接 AttributeError，整条链崩在收尾之外。
        for _f in _post_futures:
            if _f is None:
                continue
            if _f.done():
                _f.result()
        sid = shot["id"]
        raise_if_cancel_requested(ctx, f"h3_movie:{sid}")
        rec = state["shots"].setdefault(sid, {"status": "pending", "attempts": []})
        norm = Path(str(rec.get("normalized") or ""))
        # S1：上次 done 也要先证明“这批还是这批”。改了 seed／同路径素材／模板
        # 或旧 state 没有指纹 ⇒ 该镜失效重跑，不靠文件名和 mtime 认亲。
        selected = dict(plan["shots"][idx - 1]["generation"])
        # 绑定里必须带**这一镜实际会用的 seed**：只读 YAML 默认时 seed 不在
        # generation 里，改 seed_base 就会被误判成“没变”。
        selected.setdefault("seed", shot.get("seed", int(manifest.get("seed_base", 42)) + idx - 1))
        relay_role = (plan["shots"][idx - 1].get("relay") or {}).get("role")
        parent_sid = child_of.get(sid)
        parent_raw = (Path(str((state["shots"].get(parent_sid) or {}).get("raw") or ""))
                      if parent_sid else None)
        _wf_rel = (_RELAY_TPL_PARENT if relay_role == "parent" else
                   _RELAY_TPL_CONT if relay_role == "child" else
                   "comfy/h3_i2v_fl2va_dual_lora.json"
                   if str(selected.get("lora2") or "").strip()
                   else "comfy/h3_i2v_fl2va_api.json")
        curr_bind = task_state.shot_binding(
            Path(str(ctx.get("wf_root") or Path(__file__).parent)),
            _wf_rel, selected, shot.get("ref_images"))
        if relay_role:
            pr = (state["shots"].get(parent_sid) or {}).get("relay") or {}
            curr_bind["relay"] = {
                "role": relay_role, "parent": parent_sid,
                "parent_candidate": pr.get("candidate_id"),
                "parent_revision": pr.get("revision"),
            }
        if rec.get("status") == "done" and norm.is_file():
            if rec.get("resume_binding") != curr_bind:
                rec["status"] = "stale"
                # 绑定变了就必须真的重渲：只把 status 改成 stale 而留着旧 raw，
                # 下面的 `if not raw.is_file()` 会直接复用旧片，等于假重跑。
                for _k in ("raw", "normalized", "raw_qc_passed", "resume_binding"):
                    rec.pop(_k, None)
                _save_state()
                log(ctx, f"[h3_movie] ↷ {sid} 上次 done 但输入/模板/seed/素材已变"
                         f"或无指纹 ⇒ 失效重跑（不假跳过）")
            else:
                try:
                    _video_qc(norm, ctx, require_audio=True, expected_fps=float(p.get("fps", 24)),
                              expect_audio_spec=H3_CONCAT_AUDIO)
                    with _state_lock:
                        _post_results[idx] = str(norm)
                    log(ctx, f"[h3_movie] ↷ {sid} 已完成且绑定一致，断点续跑跳过生成")
                    continue
                except Exception:
                    rec["status"] = "stale"

        raw = Path(str(rec.get("raw") or ""))
        if relay_role == "parent" and not raw.is_file() and rec.get("relay", {}).get("chain_id"):
            # 断点恢复：父段产物不在批次夹，但链 manifest 里有正式成片就直接认领
            # （A5 的 *_a1 glob 认不出 segment_ 命名，链 manifest 才是父段的崩溃窗口真源）
            try:
                mdir = Path(ctx["cfg"]["comfyui"]["output_dir"]) / "minimax_h3_t8_long_video" \
                    / rec["relay"]["chain_id"]
                m = json.loads((mdir / "manifest.json").read_text(encoding="utf-8"))
                segs = m.get("segments") or {}
                entry = segs["0"] if isinstance(segs, dict) else segs[0]
                v = mdir / entry["video_path"]
                if v.is_file():
                    raw = v
                    rec["relay"].update({"candidate_id": str(entry["candidate_id"]),
                                         "revision": int(entry.get("revision") or 1)})
                    rec["raw"] = str(raw)
                    rec["resume_binding"] = curr_bind
                    rec["status"] = "raw_done"
                    _save_state()
                    log(ctx, f"[relay] ⚠ {sid} 父段断点恢复：链 manifest 认领 {v.name}")
            except Exception:
                pass  # 链还没落到可认领状态，走正常重渲
        if not raw.is_file():
            # A5 崩溃窗口兜底（2026-10-15 批准）：生成已完成、但进程死在 relocate／
            # 写 state 之前时，产物会游离在 ComfyUI 输出目录。S1 收紧：只认**本 run
            # 已有 submission 记录里的 prefix/prompt_id**，不再按镜号 glob 全部历史；
            # 没有归属证据就不认领（等待人工/原 prompt_id 恢复）。
            out_dir = Path(ctx["cfg"]["comfyui"]["output_dir"])
            owned = submission_prefixes(ctx, sid)
            expected_prefix = f"movie_{_safe_run_id(ctx.get('run_id'))}_{sid}_a"
            if not owned:
                log(ctx, f"[h3_movie] {sid} 崩溃窗口：找不到本 run 的 submission 记录，"
                         f"不扫目录认领他批文件")
            elif out_dir.is_dir():
                cands = sorted(out_dir.glob(f"{expected_prefix}*.mp4"),
                               key=lambda f: f.stat().st_mtime, reverse=True)
                for cand in cands:
                    owner = next((x for x in owned
                                  if cand.name.startswith(x["prefix"])), None)
                    if owner is None:
                        log(ctx, f"[h3_movie] {sid} 崩溃候选 {cand.name} 缺本 run/"
                                 f"本镜 prefix 归属证据，拒绝认领")
                        continue
                    try:
                        qc = _video_qc(cand, ctx, require_audio=True,
                                       expected_fps=float(p.get("fps", 24)),
                                       expect_audio_spec=H3_NATIVE_AUDIO,
                                       expected_length=int(selected["length"]))
                    except Exception as exc:
                        # 计划 W5a：崩溃回收候选 QC 失败要留痕、显式跳过——
                        # 之前只 except Exception continue，没记录是哪条失败了。
                        log(ctx, f"[h3_movie] {sid} 崩溃候选 {cand.name} raw QC 失败（{exc}），跳过")
                        continue  # 截断/无音轨/时长不符的落盘残骸，试下一个候选
                    moved = relocate([str(cand)], batch / "shots" / sid / "raw", ctx["log"])
                    raw = Path(moved[0])
                    rec["attempts"].append({"status": "recovered", "from_glob": str(cand),
                                            "qc": qc,
                                            "prompt_id": owner.get("prompt_id"),
                                            "ownership": "same_run_prefix"})
                    rec["raw"] = str(raw)
                    rec["generation"] = selected
                    rec["resume_binding"] = curr_bind
                    rec["status"] = "raw_done"
                    rec["raw_qc_passed"] = True   # 计划 W5a：显式标 QC 通过，后期入口受控
                    _save_state()
                    log(ctx, f"[h3_movie] ⚠ {sid} 崩溃窗口回收：ComfyUI 输出目录的 "
                             f"{cand.name} 复检通过，跳过重新生成")
                    break
        if not raw.is_file() and relay_role:
            # R11 接力镜（父段入链 / EXPT8 续段）。画布是几何合约的一半（64 对齐，
            # R11-01 硬条件2），不许降级梯子改画布 ⇒ degrade 传空，只留 head_chunks 一级。
            last = None
            for attempt_no, attempt in enumerate(_retry_ladder(selected, ()), 1):
                vp = dict(attempt)
                vp.update({"prompt": shot.get("prompt") or "",
                           "prompt_file": shot.get("prompt_file") or "",
                           "prompt_kind": "h3_i2va",
                           "ref_images": shot["ref_images"],
                           "seed": shot.get("seed", int(manifest.get("seed_base", 42)) + idx - 1),
                           "prefix": f"movie_{ctx['run_id']}_{sid}_a{attempt_no}",
                           "stage": f"shots/{sid}/raw",
                           "timeout": int(p.get("timeout", 10800)),
                           "fps": float(p.get("fps", 24))})
                if relay_role == "parent":
                    chain_id = "relay_%s_%s" % (_safe_run_id(ctx["run_id"]), sid)
                    vp.update({"workflow": _RELAY_TPL_PARENT,
                               "_relay_chain": chain_id,
                               "_extra_rep": {"__CHAIN__": chain_id,
                                              "__DUR__": round(int(selected["length"])
                                                               / float(p.get("fps", 24)), 3)},
                               "length": int(selected["length"])})
                    log(ctx, f"[relay] {sid} 父段入链尝试{attempt_no}: 链 {chain_id}，"
                             f"{vp['width']}x{vp['height']}，{vp['length']}帧/{vp['_extra_rep']['__DUR__']}s")
                else:
                    pr = (state["shots"].get(parent_sid) or {}).get("relay") or {}
                    if not pr.get("candidate_id"):
                        raise RuntimeError(
                            f"{sid} 是接力子镜，但父镜 {parent_sid} 还没有入链记录"
                            f"（relay_pairs 要求父镜排在子镜前，父镜须先渲染成功）")
                    vp.update({"workflow": _RELAY_TPL_CONT,
                               "_relay_mode": True,  # 启动分派用：续段掉线重拉也必须无 sage
                               "_extra_rep": {"__CHAIN__": pr["chain_id"],
                                              "__CANDIDATE__": pr["candidate_id"],
                                              "__REV__": int(pr.get("revision") or 1),
                                              "__LOW_W__": int(vp["width"]) // 2,
                                              "__LOW_H__": int(vp["height"]) // 2},
                               "length": relay_ctx + int(selected["length"])})
                    log(ctx, f"[relay] {sid} 续段尝试{attempt_no}: 接 {pr['chain_id']}"
                             f"@{str(pr['candidate_id'])[:24]}…，ctx {relay_ctx}＋{selected['length']} 帧")
                try:
                    # R11 硬条件3 的运行侧一半：接力批每镜开跑前 /free 清模型。
                    # 续段 LOW 的入口自检（LOW MODEL changed during sampling）在
                    # "复用上一镜缓存下来的 ModelPatcher、带着残状态进场"时必炸
                    # （2026-10-15 E2E 实测：手动流程每次 /free 所以没炸过）。
                    _free_comfyui(ctx)
                    time.sleep(2)
                    out = t_video(vp, ctx)
                    raw = Path(out["files"][0])
                    # 接力镜：父段帧数由 planner 量化、续段带上下文前缀，
                    # 实际帧数与请求天然不等（前缀在归一化时剥除）。
                    # expected_length=None 保持 relay 不做硬门——前缀帧容差扛不住。
                    qc = _video_qc(raw, ctx, require_audio=True,
                                   expected_fps=float(p.get("fps", 24)),
                                   expected_length=None,
                                   expect_audio_spec=H3_NATIVE_AUDIO)
                    rec["attempts"].append({"status": "passed", "params": attempt, "qc": qc})
                    rec["raw"] = str(raw)
                    rec["generation"] = attempt
                    rec["resume_binding"] = curr_bind
                    rec["status"] = "raw_done"
                    rec["raw_qc_passed"] = True   # 计划 W5a
                    rec.setdefault("relay", {})
                    if relay_role == "parent":
                        rec["relay"].update(dict(out.get("relay") or {},
                                                 ctx_frames=relay_ctx))
                    else:
                        rec["relay"].update({"role": "child", "parent": parent_sid,
                                             "ctx_frames": relay_ctx})
                    _save_state()
                    break
                except Exception as exc:
                    last = exc
                    # 计划 W5a：QC 失败（_video_qc 抛 RuntimeError）显式留痕、
                    # 设 raw_qc_passed=False —— 不伪装成"生成失败"，retry ladder 无用。
                    if not getattr(rec, "get", lambda *_: None)("raw") and raw.is_file():
                        rec["raw"] = str(raw)
                    rec.setdefault("raw_qc_passed", False)
                    rec["raw_qc_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
                    rec["attempts"].append({"status": "failed", "params": attempt,
                                            "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
                    _save_state()
                    if "超时" in str(exc) or not _is_resource_error(exc):
                        break
                    _free_comfyui(ctx)
                    time.sleep(2)
            if not raw.is_file():
                rec["status"] = "failed"
                _save_state()
                raise RuntimeError(f"{sid} 生成失败，已停止整片（不会重跑已完成镜头）: {last}")

        if not raw.is_file():
            last = None
            for attempt_no, attempt in enumerate(_retry_ladder(selected, degrade), 1):
                vp = dict(attempt)
                # 配了 lora2（内容 LoRA）就走双 LoRA 模板：底模→Turbo(__LORA__)→内容(__LORA2__)→Attention。
                wf = ("comfy/h3_i2v_fl2va_dual_lora.json"
                      if str(vp.get("lora2", "")).strip() else "comfy/h3_i2v_fl2va_api.json")
                vp.update({"workflow": wf,
                           "prompt": shot.get("prompt") or "",
                           "prompt_file": shot.get("prompt_file") or "",
                           "prompt_kind": "h3_i2va", "ref_images": shot["ref_images"],
                           "seed": shot.get("seed", int(manifest.get("seed_base", 42)) + idx - 1),
                           "prefix": f"movie_{ctx['run_id']}_{sid}_a{attempt_no}",
                           "stage": f"shots/{sid}/raw", "timeout": int(p.get("timeout", 10800)),
                           "fps": float(p.get("fps", 24))})
                log(ctx, f"[h3_movie] {sid} 尝试{attempt_no}: {vp['width']}x{vp['height']}x"
                         f"{vp['length']} / {vp['steps']}步 / head_chunks={vp['head_chunks']}")
                try:
                    out = t_video(vp, ctx)
                    raw = Path(out["files"][0])
                    qc = _video_qc(raw, ctx, require_audio=True,
                                   expected_fps=float(p.get("fps", 24)),
                                   expected_length=int(vp["length"]),
                                   expect_audio_spec=H3_NATIVE_AUDIO)
                    rec["attempts"].append({"status": "passed", "params": attempt, "qc": qc})
                    rec["raw"] = str(raw)
                    rec["generation"] = attempt
                    rec["resume_binding"] = curr_bind
                    rec["status"] = "raw_done"
                    rec["raw_qc_passed"] = True   # 计划 W5a
                    _save_state()
                    break
                except Exception as exc:
                    last = exc
                    # 计划 W5a：QC 失败显式留痕（同 relay 分支）
                    if not getattr(rec, "get", lambda *_: None)("raw") and raw.is_file():
                        rec["raw"] = str(raw)
                    rec.setdefault("raw_qc_passed", False)
                    rec["raw_qc_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
                    rec["attempts"].append({"status": "failed", "params": attempt,
                                            "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
                    _save_state()
                    if "超时" in str(exc) or not _is_resource_error(exc):
                        break
                    _free_comfyui(ctx)
                    time.sleep(2)
            if not raw.is_file():
                rec["status"] = "failed"
                _save_state()
                raise RuntimeError(f"{sid} 生成失败，已停止整片（不会重跑已完成镜头）: {last}")

        # 镜 N 的后期丢后台（与镜 N+1 的渲染重叠），不再同步等待
        # 计划 W5a：raw_qc_passed=False 的镜显式标 qc_failed，跳过后期入口
        if rec.get("raw_qc_passed") is False:
            rec["status"] = "qc_failed"
            _save_state()
            log(ctx, f"[h3_movie] {sid} raw QC 失败，跳过后期（normalize/concat）——"
                     f"raw_qc_error={rec.get('raw_qc_error','未知')[:200]}")
            _post_futures.append(None)   # 占位，保持 _post_results 索引对齐
            continue
        _post_futures.append(_post_pool.submit(
            _make_post(idx, sid, raw, rec, shot, parent_sid, parent_raw, relay_role)))

    for _f in _post_futures:  # 等所有后台后期收尾（正常情况下早已全部完成，此处不产生等待）
        if _f is None:
            continue          # QC 失败镜没有后期任务，不往 _post_results（按镜号索引的 dict）里塞
        _f.result()
    # W5a 复核修：_post_results 是 {镜号: 归一片} 的 dict，不是 list。
    # QC 失败镜从一开始就没有条目 ⇒ 按镜号顺序取"有产物的镜"，天然不进 concat。
    normalized = [_post_results[i] for i in range(1, len(manifest["shots"]) + 1)
                  if i in _post_results]
    _post_pool.shutdown(wait=False)

    final = batch / "final" / f"{str(manifest.get('title') or ctx.get('run_id'))}_final.mp4"
    if not normalized:
        # 一镜都没过 QC ⇒ 不许拼空表（ffmpeg 会拿一份 0 镜的"成片"回来并标 done）。
        # 停在明确失败，让人去 h3_movie_state.json 看哪些镜 qc_failed、错在哪。
        _bad = [sid for sid, r in state["shots"].items() if r.get("raw_qc_passed") is False]
        raise RuntimeError(
            f"没有任何一镜通过 raw QC（qc_failed: {'、'.join(sorted(_bad)) or '见 state'}）"
            f"⇒ 不出成片：{state_path}")
    _concat_clips(normalized, final, ctx)
    final_qc = _video_qc(final, ctx, require_audio=True, expected_fps=float(p.get("fps", 24)),
                         expect_audio_spec=H3_CONCAT_AUDIO)
    state["status"] = "done"
    state["final"] = str(final)
    state["final_qc"] = final_qc
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_state()
    log(ctx, f"[h3_movie] 一键成片完成：{len(normalized)} 镜 -> {final}")
    return {"files": [str(final)], "count": 1, "shots": len(normalized),
            "width": final_qc["width"], "height": final_qc["height"],
            "fps": final_qc["fps"], "length": final_qc.get("frames"),
            "elapsed": None, "profile": profile_name, "state": str(state_path)}


# ---------------------------------------------------------------- VL 内容质检软门
VL_KEY_FILE = Path("E:/密钥文件/阿里多模态.txt")


def _vl_credentials():
    """读阿里多模态 key。没有 key 就返回 None——软门跳过，绝不阻塞出片。

    取法：环境变量 AW_VL_API_KEY → 引擎自己配置的 AW_DASHSCOPE_API_KEY →
    E:\\密钥文件\\阿里多模态.txt（第 1 行 key，第 2 行 base 可省）。
    2026-10-18 补环境变量这两路：专用文件在盘上已找不到，而 vl_score_image
    一直是「env 优先」——两个读法不一致会让同一台机器一半判分能用、一半静默跳过。
    同属 DashScope，qwen3-vl-plus 与文本模型共用一把按量付费 key（已实测可用）。
    """
    key = base = ""
    for envk in ("AW_VL_API_KEY", "AW_DASHSCOPE_API_KEY"):
        key = os.environ.get(envk, "").strip()
        if key:
            break
    base = os.environ.get("AW_VL_BASE_URL", "").strip()
    if not key:
        try:
            if not VL_KEY_FILE.is_file():
                return None
            lines = VL_KEY_FILE.read_text(encoding="utf-8").strip().splitlines()
            if not lines or not lines[0].strip():
                return None
            key = lines[0].strip()
            if len(lines) > 1 and lines[1].strip():
                base = lines[1].strip()
        except Exception:
            return None
    return {"key": key,
            "base": (base.rstrip("/") if base
                     else "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "model": os.environ.get("AW_VL_MODEL", "").strip() or "qwen3-vl-plus"}


def _extract_frames(video, ctx, n=5):
    """均匀抽 n 帧（按时间点，不依赖帧数）。返回 [{t, file}]。"""
    ffmpeg, _ = _media_tools(ctx)
    meta = probe_video(video, ctx)
    dur = max(float(meta.get("duration") or 0.1), 0.1)
    d = Path(tempfile.mkdtemp(prefix="vl_frames_"))
    frames = []
    for i in range(int(n)):
        # 末帧时间点留 0.05s 余量，避免 -ss 越界抽不出帧
        t = min(dur * i / max(int(n) - 1, 1), max(dur - 0.05, 0.0))
        out = d / f"f_{i:02d}.png"
        _run_media([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.3f}",
                    "-i", str(video), "-frames:v", "1", str(out)], timeout=120)
        frames.append({"t": round(t, 2), "file": str(out)})
    return frames


def _vl_mime(path):
    """按后缀给 data URI 的 MIME。评审步的输入既可能是抽出来的 png 帧，
    也可能是 jpg 首帧；这里写死 image/png 时抽帧恰好都是 png 所以没暴露问题。"""
    s = Path(path).suffix.lower()
    if s in (".jpg", ".jpeg"):
        return "image/jpeg"
    if s == ".webp":
        return "image/webp"
    return "image/png"


def _vl_ask(cred, image_path, question):
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    mime = _vl_mime(image_path)
    payload = {"model": cred["model"], "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": question},
    ]}]}
    r = requests.post(cred["base"] + "/chat/completions", json=payload, timeout=120,
                      headers={"Authorization": f"Bearer {cred['key']}"})
    if r.status_code != 200:
        raise RuntimeError(f"VL HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def vl_content_check(video, ctx, question, n_frames=5):
    """内容质检软门：抽帧 + 云端 VL 逐帧识别，返回结构化报告。

    软门语义：只返回 report、不抛错、不否决出片；无 key 时返回 disabled。
    question 是需要 VL 逐帧核查的点（谁在场/动作/武器/瑕疵等）。
    """
    cred = _vl_credentials()
    if cred is None:
        return {"enabled": False, "reason": "无 VL key，软门跳过"}
    frames = _extract_frames(video, ctx, int(n_frames))
    answers = []
    for f in frames:
        try:
            answers.append({"t": f["t"], "answer": _vl_ask(cred, f["file"], question),
                            "ok": True})
        except Exception as e:
            answers.append({"t": f["t"], "answer": None, "ok": False,
                            "error": f"{type(e).__name__}: {str(e)[:200]}"})
    return {"enabled": True, "video": str(video), "question": question,
            "frames": answers}


@task("vl_qc")
def t_vl_qc(p, ctx):
    """对视频做内容质检软门。params: files(视频路径列表) / question / n_frames。"""
    files = _as_list(p.get("files"))
    if not files:
        raise RuntimeError("vl_qc 需要 files（要质检的视频列表）")
    question = str(p.get("question") or "")
    if not question:
        raise RuntimeError("vl_qc 需要 question（逐帧核查点，如‘谁在场/动作/武器/瑕疵’）")
    n = int(p.get("n_frames", 5))
    reports = [vl_content_check(f, ctx, question, n) for f in files]
    log(ctx, f"[vl_qc] 完成 {len(reports)} 个视频的内容识别")
    return {"files": files, "reports": reports, "count": len(reports)}


# ── 美学判分整块已摘除（2026-11-04 用户裁定：审美判定一律交给人）──────────
# 摘掉的是三件**替人做审美裁断**的东西：`_AESTHETIC_RUBRIC`（五维 0-20 打分基准）、
# `_vl_score_frame`（单帧打分）、`t_vl_aesthetic`（评审步本体，2026-10-19 D20 已摘注册、
# 函数体当时故意留着等裁），以及 `vl_score_image`＋`@task("auto")` 闭环（见本文件上方）。
# 正身逐行留在 `backups/_治理_20261104/归档件/审美判定退役_20261104/tasks_py_退役前.py`，
# 没重写、没"简化"。
#
# 为什么整块删而不是"留着只报不拦"：D20 那次只摘注册、留函数体，结果是一个
# **不在注册表里、却仍在模块里**的判分器——下一个 agent 读到它就能直接调，
# 审美判定就又回来了。这次连本体一起走。
#
# 保留的是**事实型核查**，它们判的是"在不在、对不对"，不是"好不好"：
#   · `_vl_credentials` / `_extract_frames` / `_vl_mime` / `_vl_ask` / `vl_content_check`
#     —— 谁在场／动作／武器／有无瑕疵（opt-in，无 key 时把 disabled 写进记录，不装成通过）
#   · `t_vl_qc` —— 上面那件的任务化入口
#   · `_batch_consistency_qc` —— 批内**身份**尺（同人同装，可测；画风那一维它判不了，见 R5-15 第 4 条）
# 判"好不好看、像不像想要的风格"从此只有一个入口：人（H3／H4 人工关口、审片站、飞书目审）。
# 依据：11-04 七批离线复核证明批内相对量抓不到"整批一起偏"，五种取法零分离
# （`D:/AIWorkflow/tmp/_ruler_probe/`）；更早一次，LAION 美学分被用户实圈 36 张否掉
# （可用组 9.34 vs 不可用组 9.60，AUC 0.374）。机器判美学在这台机器上**两次**被证伪。

# ── 尺寸／画幅：不留代码兜底（2026-10-03 用户裁「删除硬编码，全部强制要求显式配置」）──
# 为什么值得单独立一条：以前那种「取不到就替人给一个像素数」的写法，让"没配置"和
# "配置成那个数"长得一模一样——出片出来是那个尺寸，没人知道那是代码替人做的决定。
# 取值面只有两层，都是**人写的配置**：步骤 params → ctx["args"]（＝ yaml 顶层 args
# ＋命令行 --set）；两层都没有就报错，绝不替人凑一个数。


def _size_from_params(p, name, tag):
    """图构造器（build_graph*）专用的那一层：它们签名里没有 ctx，
    取值面就只有**这一步的 params**——而 yaml 的 params 正是"人显式写的配置"，够用。"""
    return _need_explicit_int(p, {}, name, tag)


def _need_explicit_int(p, ctx, name, tag):
    """取一个**必须显式给过**的整数：步骤 params → ctx["args"]（yaml 的 args ＋
    命令行 --set）→ 都没有就报错。两层都是人写的配置，代码不参与取值。

    返回**裸值**（不返回来源标签）——调用方到处是把结果直接塞进图/字典/meta，
    返回元组会让"尺寸"变成一个 tuple，那是比硬编码更隐蔽的坏。
    """
    for src_ in (p, (ctx or {}).get("args") or {}):
        try:
            v = src_.get(name)
        except AttributeError:
            v = None
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        try:
            f = float(str(v).strip())
        except ValueError:
            raise RuntimeError(f"{tag}：{name}={v!r} 不是数字像素值。"
                               f"请写整数（例：{name}: 832），不许表达式。")
        if f != int(f):
            raise RuntimeError(f"{tag}：{name}={v!r} 不是**整数**像素——"
                               f"像素没有小数，四舍五入替人改尺寸同样是替人决定。")
        return int(f)
    raise RuntimeError(
        f"{tag}：{name} **没有显式配置**——代码里已按要求删掉兜底默认，不再替人决定尺寸。\n"
        f"  两条给法（任选，都是「人写的配置」）：\n"
        f"    ① 这份 workflow 里写死：步骤 params 加 {name}: <像素>，"
        f"或顶层 args 加 {name}: <像素> 再在步里引 {{{{args.{name}}}}}\n"
        f"    ② 跑的时候命令行给：--set {name}=<像素>\n"
        f"  ⚠ 决定单里的 `aspect_ratio` 只表达**取向**（9:16／16:9），它不造像素尺寸——\n"
        f"     把取向换成像素是机器替你做创作决定，那正是这套框架不让做的事。")


def _explicit_size(p, ctx, tag):
    """一次取齐 width/height，返回 (w, h)。给不了就按上面的口径报错。"""
    return (_need_explicit_int(p, ctx, "width", tag),
            _need_explicit_int(p, ctx, "height", tag))


def _pnum(p, key, default):
    """取数值参数：缺省或空串走 default；**0 / 0.0 是有效值，不能吃掉**（所以不用 `or`）。"""
    v = p.get(key, None)
    return default if v in (None, "") else float(v)


def _pint(p, key, default):
    v = p.get(key, None)
    return default if v in (None, "") else int(v)


def build_graph_control(tpl, p, seed, extra_rep=None):
    """单图输入出图填充。与 build_graph 的区别：
      - **不做 LoRA 链注入**（这类模板不挂 LoRA）
      - 支持 __CTRL_IMAGE__（图文件名）与 __CTRL_STRENGTH__

    2026-09-28 图片链扩展：同一步现在同时服务四种「单图进、单图出」——
      · 控制图（`z_image_cn_canny_api.json`：Canny 锁剪影；yaml 宿主 previz_control）
      · 初始化图（`z_image_i2i_api.json`：`__DENOISE__` 是唯一刻度；宿主 image_i2i）
      · 掩膜图（`z_image_inpaint_api.json`：`__CTRL_IMAGE__` 那张 PNG 的 **alpha 透明处＝要重画的区域**；宿主 image_inpaint）
      · 垫图（`z_image_outpaint_api.json`：`__PAD_L/T/R/B__` + `__FEATHER__`；宿主 image_outpaint）
      · 另有深度图（`z_image_cn_api.json`；宿主 image_depth）
    2026-10-19 更正：上面原先写的是 flux_controlnet_lineart / flux_i2i / flux_inpaint /
      flux_outpaint 四个模板名，属 FLUX 时代写法。FLUX 线已整条裁掉（主模型
      flux1-dev-fp8.safetensors 盘上缺失 ⇒ 10 个 FLUX 模板早已不可跑）。现役五条 image
      workflow 全部走 Z-Image（已逐个核 yaml 的 workflow: 值）。模板由 p["workflow"] 传入、
      本函数无硬编码默认值 ⇒ 这次更正只影响文档、不影响行为。
    旧模板不含这些新占位符 ⇒ 多填几个 rep 键对既有工作流零影响
    （walk 只替换"整值恰好等于占位符"的字符串）。
    """
    g = copy.deepcopy(tpl)
    prompt = str(p.get("prompt", "")).strip()
    if not prompt or prompt == "None":
        raise ValueError("提示词为空或字面量 \"None\"，拒绝提交（会白跑一趟 GPU）。")
    rep = {
        "__PROMPT__": prompt,
        "__SEED__": int(seed),
        "__STEPS__": int(p.get("steps", 20)),
        "__GUIDANCE__": _pnum(p, "guidance", 3.5),
        "__W__": _size_from_params(p, "width", "control 模板（build_graph_control）"),
        "__H__": _size_from_params(p, "height", "control 模板（build_graph_control）"),
        "__PREFIX__": str(p.get("prefix", "ctrl")),
        "__CTRL_STRENGTH__": float(p.get("strength", 0.8)),
        # ---- 2026-09-28 新增（图片链扩展）----
        "__DENOISE__": _pnum(p, "denoise", 1.0),
        "__GROW__": _pint(p, "grow", 6),
        "__PAD_L__": _pint(p, "pad_l", 0),
        "__PAD_T__": _pint(p, "pad_t", 0),
        "__PAD_R__": _pint(p, "pad_r", 0),
        "__PAD_B__": _pint(p, "pad_b", 0),
        "__FEATHER__": _pint(p, "feather", 40),
        "__DEPTH_RES__": _pint(p, "depth_res", 1024),
    }
    if extra_rep:
        rep.update(extra_rep)

    def walk(v):
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str) and v in rep:
            return rep[v]
        return v
    return walk(g)


@task("control")
def t_control(p, ctx):
    """ComfyUI 单图输入出图（一个 src_image 进、图片出）。按模板分四种用法：

      · **控制图**（`comfy/z_image_cn_canny_api.json`，宿主 previz_control）：灰模帧 → Canny → 锁剪影
      · **初始化图**（`comfy/z_image_i2i_api.json`，宿主 image_i2i）：保构图重绘，`denoise` 是唯一刻度
        （⚠ 下面两个数是 **FLUX 时代**实测：0.30 构图相关 0.833；0.60 掉到 0.571＝几乎重画。
         Z-Image 档**未重新标定**，别当 Z-Image 的判据用）
      · **掩膜图**（`comfy/z_image_inpaint_api.json`，宿主 image_inpaint）：src_image 那张 PNG 的
        **alpha 透明处＝要重画的区域**，掩膜外只经 VAE 往返
        （⚠ FLUX 时代实测：掩膜外差异 11.09 ≈ 地板 10.60 ⇒ 掩膜确实被遵守。Z-Image 档未重标）
      · **垫图**（`comfy/z_image_outpaint_api.json`，宿主 image_outpaint）：`pad_l/t/r/b` + `feather` 扩画布
        （⚠️ 原始区四周 feather 像素内会被重画，边界有接缝风险）
      · **深度图**（`comfy/z_image_cn_api.json`，宿主 image_depth）

    2026-10-19 更正：上面原先写的是 flux_controlnet_lineart / flux_i2i / flux_inpaint /
    flux_outpaint。FLUX 线已整条裁掉（主模型 flux1-dev-fp8.safetensors 盘上缺失）。现役五条
    image workflow 全走 Z-Image（已逐个核 yaml 的 workflow: 值）。模板由 p["workflow"] 传入、
    本函数**无硬编码默认值**（对比 t_auto :327 那个坏默认已单独修）⇒ 只影响文档不影响行为。

    params: workflow(模板相对路径) / prompt / src_image(图路径，拷进 input) / strength /
    width / height / steps / seed(可空=随机) / prefix / stage(落进批次夹子目录，默认 control) /
    denoise / grow / pad_l / pad_t / pad_r / pad_b / feather / depth_res / timeout。
    产物图片 relocate 进批次夹。服务未运行时自动启动。"""
    cfg = ctx["cfg"]["comfyui"]
    base = ensure_comfyui(ctx)
    tpl = load_template(ctx, p["workflow"])

    input_dir = Path(cfg.get("input_dir", r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"))
    input_dir.mkdir(parents=True, exist_ok=True)
    src = p.get("src_image") or p.get("src")
    if not src:
        raise RuntimeError("control 任务需要 src_image（灰模帧路径）")
    sp = Path(src)
    if not sp.exists():
        raise RuntimeError(f"控制图不存在: {sp}")
    nm = f"wfctrl_1_{sp.name}"
    shutil.copy2(sp, input_dir / nm)
    extra = {"__CTRL_IMAGE__": nm}

    seed = p.get("seed")
    seed = random.randint(0, 2**31 - 1) if seed in (None, "") else int(seed)
    graph = build_graph_control(tpl, p, seed, extra_rep=extra)

    out_dir = Path(cfg["output_dir"])
    pre_snapshot = set(f for f in out_dir.rglob("*") if f.is_file())
    t0 = time.time()
    r = SESSION.post(base + "/prompt", json={"prompt": graph}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"任务提交失败: {r.text[:300]}")
    pid_ = r.json()["prompt_id"]
    log(ctx, f"[control] 提交 prompt_id={pid_}  seed={seed}  控制图={sp.name}")
    got = poll_history(ctx, base, pid_, int(p.get("timeout", 900)),
                       pre_snapshot=pre_snapshot)
    if not got:
        raise RuntimeError(f"ComfyUI 没产出图片（prompt_id={pid_}）")
    got = relocate(got, Path(ctx["batch_dir"]) / str(p.get("stage", "control")), ctx["log"])
    log(ctx, f"[control] 完成 {len(got)} 张（{time.time() - t0:.1f}s）")
    return {"files": got, "seed": seed, "count": len(got),
            "elapsed": round(time.time() - t0, 1),
            "strength": float(p.get("strength", 0.8)), "prompt": str(p.get("prompt", ""))}


@task("refine")
def t_refine(p, ctx):
    """对选中的草稿做生成式精修（UltimateSDUpscale），保留原构图。

    直接高分辨率重画保不住草稿构图（seed 不跨分辨率），所以精修必须走
    「载入草稿 + 分块重绘放大」。params: files(草稿路径列表) / prompt / template /
    tile / steps / upscale_by / denoise / guidance / prefix / seed / timeout
    """
    cfg = ctx["cfg"]["comfyui"]
    base = ensure_comfyui(ctx)
    tpl_path = Path(ctx["wf_root"]) / p.get("template", "comfy/refine_usdu_zimage_api.json")
    tpl = load_template(ctx, p.get("template", "comfy/refine_usdu_zimage_api.json"))
    input_dir = Path(cfg.get("input_dir",
                             r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"))
    input_dir.mkdir(parents=True, exist_ok=True)

    files = p.get("files") or []
    if isinstance(files, str):
        files = [files]
    if not files:
        raise ValueError("refine 需要 files（草稿路径列表），"
                         "通常由 --set manifest=<run_id> --set pick=3,7 解析得到")

    # USDU 的分块数按面积涨：草稿大 2 倍线性 → 分块多 4 倍。实测本机
    # tile=512/12步 约 9 s/块，20 块 183 s，247 块则 41 min（必超 timeout）。
    tile, by = int(p.get("tile", 1024)), float(p.get("upscale_by", 2.0))
    budget = int(p.get("max_tiles", 64))
    est = []
    for src in files:
        w, h = img_size(src)
        est.append(((int(w * by) + tile - 1) // tile)
                   * ((int(h * by) + tile - 1) // tile))
    over = [(s, n) for s, n in zip(files, est) if n > budget]
    if over:
        src, n = over[0]
        raise ValueError(
            f"{Path(str(src)).name} 是 {img_size(src)[0]}x{img_size(src)[1]}，"
            f"精修要 {n} 块（预算 {budget} 块 ≈ {budget * 9}s），会超时。"
            f"怎么办：确认草稿模板没有多余的放大节点（草稿应与成品同分辨率），"
            f"或调大 --set tile= / 调小 --set upscale_by=")

    # 上一轮中途失败会留下 refine_* 副本；本轮的副本用完即删。不建常驻清理任务。
    for stale in input_dir.glob("refine_*"):
        if stale.is_file():
            stale.unlink(missing_ok=True)
    out_files, seeds, t0 = [], [], time.time()
    for i, src in enumerate(files):
        src = Path(src)
        dst = input_dir / f"refine_{ctx['run_id']}_{i:02d}{src.suffix}"
        shutil.copy2(src, dst)
        seed = p.get("seed")
        seed = random.randint(0, 2**31 - 1) if seed in (None, "") else int(seed) + i
        rep = {"__IMAGE__": dst.name, "__PROMPT__": str(p.get("prompt", "")),
               "__GUIDANCE__": float(p.get("guidance", 3.5)),
               "__TILE__": int(p.get("tile", 1024)),
               "__STEPS__": int(p.get("steps", 12)),
               "__DENOISE__": float(p.get("denoise", 0.35)),
               "__UPSCALE_BY__": float(p.get("upscale_by", 2.0)),
               "__SEED__": int(seed), "__PREFIX__": str(p.get("prefix", "refine"))}

        def walk(v):
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x) for x in v]
            if isinstance(v, str) and v in rep:
                return rep[v]
            return v

        graph = walk(tpl)
        out_dir = Path(ctx["cfg"]["comfyui"]["output_dir"])
        pre_snapshot = set(f for f in out_dir.rglob("*") if f.is_file())
        r = SESSION.post(base + "/prompt", json={"prompt": graph}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"refine 提交失败: {r.text[:300]}")
        pid_ = r.json()["prompt_id"]
        log(ctx, f"[refine] {i + 1}/{len(files)} {src.name} seed={seed} pid={pid_}")
        got = poll_history(ctx, base, pid_, int(p.get("timeout", 900)),
                           pre_snapshot=pre_snapshot)
        if not got:
            raise RuntimeError(
                f"ComfyUI 精修没产出任何文件（prompt_id={pid_}），"
                f"检查 ComfyUI 日志或 USDU 节点是否报错")
        got = relocate(got, Path(ctx["batch_dir"]) / "final", ctx["log"])
        out_files.extend(got)
        seeds.extend([seed] * len(got))
        dst.unlink(missing_ok=True)   # 这张的活干完了，input 里的副本别留
    log(ctx, f"[refine] 完成 {len(out_files)} 张（{time.time() - t0:.1f}s）")
    sizes = [img_size(f) for f in out_files]
    bad = [(f, s) for f, s, src in zip(out_files, sizes, files)
           if s != (int(img_size(src)[0] * by), int(img_size(src)[1] * by))]
    if bad:
        raise RuntimeError(
            f"精修产物尺寸 {bad[0][1][0]}x{bad[0][1][1]} ≠ 草稿 ×{by}，"
            f"USDU 未按要求放大: {Path(str(bad[0][0])).name}")
    return {"files": out_files, "seeds": seeds, "count": len(out_files),
            "elapsed": round(time.time() - t0, 1),
            "width": sizes[0][0], "height": sizes[0][1],
            "prompt": str(p.get("prompt", ""))}


# ---------------------------------------------------------------- files
@task("files")
def t_files(p, ctx):
    """文件操作。action=copy_new: 把 src 下匹配 pattern 的新文件复制到 dst；
    action=clean_old: 删除 dir 下超过 days 天的匹配文件。"""
    action = p.get("action")
    if action == "copy_new":
        src, dst = Path(p["src"]), Path(p["dst"])
        dst.mkdir(parents=True, exist_ok=True)
        pat = str(p.get("pattern", "*"))
        n = 0
        for f in sorted(src.iterdir()) if pat == "*" else sorted(
                x for x in src.iterdir() if fnmatch.fnmatch(x.name, pat)):
            if f.is_file():
                shutil.copy2(f, dst / f.name)
                n += 1
        log(ctx, f"[files] 归档 {n} 个文件 -> {dst}")
        return {"copied": n, "dst": str(dst)}
    if action == "clean_old":
        days = float(p.get("days", 30))
        now, n = time.time(), 0
        for f in Path(p["dir"]).glob(str(p.get("pattern", "*"))):
            if f.is_file() and now - f.stat().st_mtime > days * 86400:
                f.unlink()
                n += 1
        return {"deleted": n}
    raise ValueError(f"未知 files.action: {action}")


# ---------------------------------------------------------------- shell
@task("shell")
def t_shell(p, ctx):
    """执行任意命令行（扩展逃生口）。params: command / timeout"""
    r = subprocess.run(p["command"], shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       timeout=int(p.get("timeout", 300)))
    if r.returncode != 0:
        raise RuntimeError(f"命令失败 code={r.returncode}: "
                           f"{(r.stderr or r.stdout or '')[-300:]}")
    return {"code": r.returncode, "stdout_tail": (r.stdout or "")[-2000:]}


# ---------------------------------------------------------------- sheets
FONT_MSYH = "C:/Windows/Fonts/msyh.ttc"


@task("sheets")
def t_sheets(p, ctx):
    """把一批图拼成总览网格（角色立绘选种用，合并自 pipeline.py 的 make_sheets）。
    params: files(图路径列表) / seeds(可选，图注) / labels(可选，覆盖图注) /
    cols(每行张数，默认 4) / thumb_w/thumb_h(缩略图，默认 480x720) /
    title / out(输出名，默认 sheet_all.png) / font(默认 msyh.ttc)。
    产物落 batch_dir/sheets，返回 {"sheet", "files", "count"}。"""
    from PIL import Image, ImageDraw, ImageFont
    files = [str(f) for f in (p.get("files") or [])]
    if not files:
        raise ValueError("sheets 需要 files（上游出图步骤的产物列表）")
    seeds = p.get("seeds") or []
    labels = p.get("labels") or []
    cols = max(1, int(p.get("cols", 4)))
    tw, th = int(p.get("thumb_w", 480)), int(p.get("thumb_h", 720))
    font_path = str(p.get("font", FONT_MSYH))
    title = str(p.get("title", "批次总览"))
    out_name = str(p.get("out", "sheet_all.png"))
    dst_dir = Path(ctx["batch_dir"]) / "sheets"
    dst_dir.mkdir(parents=True, exist_ok=True)

    existing = []
    for i, f in enumerate(files):
        fp = Path(f)
        if not fp.is_file():
            log(ctx, f"[sheets] 跳过不存在: {f}")
            continue
        if i < len(labels):
            cap = str(labels[i])
        elif i < len(seeds):
            cap = f"seed {seeds[i]}"
        else:
            cap = fp.stem
        existing.append((fp, cap))
    if not existing:
        raise RuntimeError("sheets: 没有任何可拼的图（files 全部不存在）")

    try:
        font_t = ImageFont.truetype(font_path, 40)
        font_s = ImageFont.truetype(font_path, 26)
    except OSError:
        font_t = font_s = ImageFont.load_default()

    rows = (len(existing) + cols - 1) // cols
    gap, pad, label_h = 20, 28, 60
    cw = pad * 2 + tw * cols + gap * (cols - 1)
    ch = pad * 2 + label_h + (label_h + th) * rows + gap * (rows - 1)
    canvas = Image.new("RGB", (cw, ch), (18, 20, 26))
    dr = ImageDraw.Draw(canvas)
    dr.text((pad, pad // 2), title, font=font_t, fill=(235, 238, 245))
    for idx, (fp, cap) in enumerate(existing):
        r, c = divmod(idx, cols)
        x = pad + c * (tw + gap)
        y = pad + label_h + r * (label_h + th + gap)
        with Image.open(fp) as im:
            im = im.convert("RGB").resize((tw, th))
        canvas.paste(im, (x, y))
        dr.text((x + 8, y + 8), cap, font=font_s, fill=(255, 255, 255))
    out_path = dst_dir / out_name
    canvas.save(out_path)
    log(ctx, f"[sheets] 拼好 {len(existing)} 张 -> {out_path}")
    return {"sheet": str(out_path), "files": [str(out_path)],
            "count": len(existing), "width": cw, "height": ch}


# ---------------------------------------------------------------- feishu
def lark_run(lark_cli, cwd, args, timeout=60):
    r = subprocess.run([lark_cli] + args, cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        raise RuntimeError(f"lark-cli exit {r.returncode}: {(r.stderr or out)[:500]}")
    try:
        data = json.loads(out)
    except ValueError:
        data = {}
    if not data.get("ok"):
        raise RuntimeError(f"lark 返回非 ok: {out[:500]}")
    return data


def lark_run_tolerant(lark_cli, cwd, args, timeout=300):
    """跑 lark-cli 并**容错解析输出**——视频/文件那条通路必须用它，不能用 lark_run。

    为什么：`im +messages-send --video …` 会在 JSON 前后夹进度行（`tools/feishu_send.py:82`
    实测注释），`lark_run` 的 `json.loads` 直接失败 ⇒ data={} ⇒ 把**已经发成功**的发送
    误判成"lark 返回非 ok"并抛错。反过来也不能因为退出码 0 就宣布成功——那会把
    "CLI 打印了 JSON 但 ok=false" 当成发了。⇒ 先整体 loads，失败则解码第一个完整 JSON 对象，
    再按 ok 字段判；两者都拿不到才算未确认（返回 ok=False，让调用方留痕而不是瞎重试）。
    """
    r = subprocess.run([lark_cli] + args, cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        return False, {"error": f"lark-cli exit {r.returncode}", "out": out[-500:]}
    try:
        data = json.loads(out)
    except ValueError:
        data = None
        i = out.find("{")
        if i >= 0:
            try:
                data, _ = json.JSONDecoder().raw_decode(out, i)
            except ValueError:
                data = None
    if not isinstance(data, dict):
        return False, {"error": "退出码 0 但输出里没有可解析 JSON ⇒ 按未确认处理",
                       "out": out[:300]}
    return bool(data.get("ok", True)), data


FEISHU_MAX_MB = 30.0          # 飞书单文件上限（feishu_send.py:42 同值，别各写一份）


def _feishu_cover(ffmpeg, video, log):
    """给成片抽一张封面（CLI 的 --video 强制要 --video-cover）。

    封面必须与成片**同目录**：lark-cli 只收 cwd 相对路径，跨目录会被拒（实测，
    见记忆「lark-cli 发视频」条）。抽不到不抛——退回同目录同名 `_cover.jpg`，
    真没有就由调用方报错，而不是悄悄不发。
    """
    v = Path(video)
    cov = v.with_name(v.stem + "_cover.jpg")
    if cov.is_file() and cov.stat().st_size > 1024:
        return str(cov)
    if not ffmpeg or not Path(ffmpeg).is_file():
        log(f"[feishu] 没有 ffmpeg，抽不出封面 ⇒ 视频发不出去（CLI 强制要 --video-cover）")
        return None
    try:
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(v),
                        "-frames:v", "1", "-q:v", "3", str(cov)],
                       cwd=str(v.parent), capture_output=True, timeout=120)
    except Exception as e:
        log(f"[feishu] 抽封面失败：{e}")
        return None
    return str(cov) if cov.is_file() and cov.stat().st_size > 1024 else None


def send_media_to_feishu(cfg, files, videos, caption, log, retries=3):
    """把图＋视频发到接收群。**t_feishu 与人工关口共用这一份实现**（一類信息一个真源）。

    口径：
      · 图走两步（`im images create` → `+messages-send --image <key>`）——现役老路径，不动。
      · 视频走一步（`+messages-send --video <文件> --video-cover <封面>`，CLI 自己上传），
        这是 2026-10-19 用户裁定接回来的能力：设计里的「第一镜成片必发」「终审三分类要看片」
        在只有图路径的引擎内**根本执行不了**。
      · 超 30MB 直接拒并说明改走审片链接，**不压画质硬塞**。
      · 任何一条发失败都抛 RuntimeError（关口侧会捕获并留痕），不静默跳过。
    """
    fcfg = cfg.get("feishu") or {}
    lark_cli = str(fcfg.get("lark_cli") or "")
    chat_id = str(fcfg.get("chat_id") or "")
    if not lark_cli or not Path(lark_cli).is_file():
        raise RuntimeError("未配置 feishu.lark_cli（lark-cli.exe 完整路径）")
    if not chat_id:
        raise RuntimeError("未配置 feishu.chat_id（目标群）")
    ffmpeg = str((cfg.get("tools") or {}).get("ffmpeg")
                 or (Path(__file__).resolve().parent.parent / "tools" / "ffmpeg.exe"))

    sent = {"images": 0, "videos": 0}
    for f in [str(x) for x in (files or [])]:
        fp = Path(f)
        if not fp.is_file():
            log(f"[feishu] 跳过不存在: {f}")
            continue
        if fp.stat().st_size / 1048576.0 > FEISHU_MAX_MB:
            raise RuntimeError(f"feishu: {fp.name} 超 {FEISHU_MAX_MB:.0f}MB 上限 ⇒ 改发审片链接，别压画质硬塞")
        last = None
        for attempt in range(1, retries + 1):
            try:
                up = lark_run(lark_cli, str(fp.parent),
                              ["im", "images", "create",
                               "--data", '{"image_type":"message"}',
                               "--file", f"image={fp.name}", "--as", "bot", "--format", "json"])
                key = (up.get("data") or {}).get("image_key")
                if not key:
                    raise RuntimeError(f"lark 未返回 image_key: {json.dumps(up)[:300]}")
                ok, info = lark_run_tolerant(lark_cli, str(fp.parent),
                                             ["im", "+messages-send", "--chat-id", chat_id,
                                              "--image", key, "--as", "bot", "--format", "json"])
                if not ok:
                    raise RuntimeError(f"发图未确认: {str(info)[:200]}")
                last = None
                break
            except Exception as e:
                last = e
                log(f"[feishu] 图 {fp.name} 失败 (attempt {attempt}/{retries}): {e}")
                time.sleep(8)
        if last is not None:
            raise RuntimeError(f"feishu: {fp.name} 发送 {retries} 次均失败: {last}")
        log(f"[feishu] 已发图 {fp.name}")
        sent["images"] += 1
        time.sleep(2)

    for v in [str(x) for x in (videos or [])]:
        vp = Path(v)
        if not vp.is_file():
            log(f"[feishu] 跳过不存在: {v}")
            continue
        mb = vp.stat().st_size / 1048576.0
        if mb > FEISHU_MAX_MB:
            raise RuntimeError(f"feishu: {vp.name} {mb:.1f}MB 超 {FEISHU_MAX_MB:.0f}MB 上限 "
                               f"⇒ 改发审片链接（review_publish.py），别压画质硬塞")
        cov = _feishu_cover(ffmpeg, vp, log)
        if not cov:
            raise RuntimeError(f"feishu: {vp.name} 拿不到封面 ⇒ 视频发不出去（CLI 强制 --video-cover）")
        last = None
        for attempt in range(1, retries + 1):
            ok, info = lark_run_tolerant(lark_cli, str(vp.parent),
                                         ["im", "+messages-send", "--chat-id", chat_id,
                                          "--video", vp.name, "--video-cover",
                                          Path(cov).name, "--as", "bot", "--format", "json"],
                                         timeout=600)
            if ok:
                last = None
                break
            last = RuntimeError(str(info)[:400])
            log(f"[feishu] 视频 {vp.name} 失败 (attempt {attempt}/{retries}): {last}")
            time.sleep(8)
        if last is not None:
            raise RuntimeError(f"feishu: {vp.name} 发送 {retries} 次均失败: {last}")
        log(f"[feishu] 已发视频 {vp.name}（封面 {Path(cov).name}）")
        sent["videos"] += 1
        time.sleep(2)

    if caption:
        lark_run(lark_cli, str(Path.cwd()),
                 ["im", "+messages-send", "--chat-id", chat_id,
                  "--text", caption, "--as", "bot", "--format", "json"])
        log("[feishu] 配文已发")
    return sent


def push_gate_review(cfg, caption, files, videos, log):
    """人工关口停住时往飞书推一次（**只出向，不等回话**）。返回写进 pending 台账的小结。

    口径：
      · 开关＝config.yaml `feishu.push_gates`：on（缺省）／off／dry（只打印要发什么）。
        缺省选 on 是因为「首帧必发飞书目审」是用户定的硬闸，默认关等于没这条闸。
      · **推送失败不升级成引擎错误**：关口本来就要停（GateAwaiting），再抛一个"发送失败"
        会把"等你批"这件事伪装成"跑挂了"。但必须**留痕**——返回值进 pending 台账的
        `feishu_push`/`push_error`，`--gates` 与待批清单都看得见，绝不静默。
      · 入向读不到（群历史被拒 230027）⇒ 批准仍然走会话或 `run.py --approve`，这里不轮询。
    """
    mode = (os.environ.get("FEISHU_PUSH_GATES")
            or str((cfg.get("feishu") or {}).get("push_gates", "on"))).strip().lower()
    media_n = len([x for x in (files or [])]) + len([x for x in (videos or [])])
    if mode in ("off", "false", "0", "no"):
        log("[gate] feishu.push_gates=off ⇒ 本次不推飞书（只有本地清单与气泡）")
        return {"feishu_push": "off"}
    if mode == "dry":
        log(f"[gate][dry] 本应推飞书：{media_n} 个附件 ＋ 配文 {len(caption or '')} 字"
            f"（dry 模式，一条都没发）")
        return {"feishu_push": "dry", "would_send": media_n}
    try:
        sent = send_media_to_feishu(cfg, files, videos, caption, log)
        log(f"[gate] 已推飞书：图 {sent['images']}／视频 {sent['videos']}＋配文")
        return {"feishu_push": "sent", "pushed_images": sent["images"],
                "pushed_videos": sent["videos"]}
    except Exception as e:
        log(f"[gate][ERROR] 🔴 推飞书失败：{e} ⇒ 关口照旧停住，但**你可能看不到呈审**："
            f"要么自己看 logs/workflows/待批关口.txt，要么把 feishu.push_gates 设 off 认了这个口径")
        return {"feishu_push": "failed", "push_error": str(e)[:300]}



class GateAwaiting(RuntimeError):
    """人工关口未获批准。不是故障，是"等你回话"——单独一个类型，
       好让日志/报告/humanize_error 把它和真错误区分开。"""


class GateDenied(RuntimeError):
    """人工关口被明确否掉（--deny / 飞书回"否"）。"""


# ---------------- 人工关口：批准台账 ----------------
APPROVALS_FILE = "gate_approvals.json"


def approvals_path(cfg):
    return Path(cfg["log_dir"]) / APPROVALS_FILE


def read_approvals(cfg):
    p = approvals_path(cfg)
    if not p.is_file():
        return {"approved": {}, "denied": {}, "pending": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        # 台账坏了不能静默当"没批过"——那会让已批准的关口重复推送，
        # 也不能当"批过了"——那是越权放行。显式停下让人修。
        raise RuntimeError(f"批准台账损坏，拒绝猜测：{p}")
    for k in ("approved", "denied", "pending"):
        data.setdefault(k, {})
    return data


def write_approvals(cfg, data):
    p = approvals_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def gate_key(project, workflow, gate_id, digest):
    return f"{project or '-'}|{workflow or '-'}|{gate_id}|{digest}"


def content_digest(parts):
    """把"这次要拍的东西"压成一个指纹：内容一变，旧批准自动失效。"""
    h = hashlib.sha256()
    for name, val in parts:
        h.update(f"{name}=".encode("utf8"))
        if isinstance(val, (list, tuple)):
            for v in val:
                h.update(str(v).encode("utf8"))
        else:
            h.update(str(val or "").encode("utf8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]


def record_approval(cfg, key, state="approved", note="", meta=None):
    """state: approved | denied。同时清掉 pending。"""
    data = read_approvals(cfg)
    entry = dict(meta or {})
    entry.update({"state": state, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "note": str(note or "")[:400]})
    data[state if state in ("approved", "denied") else "approved"][key] = entry
    if state == "denied":
        data["approved"].pop(key, None)
    else:
        data["denied"].pop(key, None)
    data["pending"].pop(key, None)
    write_approvals(cfg, data)
    return entry


def record_run_decisions(cfg, project, workflow, gate_id, digest, decisions, required=(),
                         sources=None):
    """把「这次运行由人决定的参数」落进批准台账（10-02 批 5-2 写出方）。

    为什么不新开第四个记录文件：`gate_approvals.json` 已经是「按内容摘要绑定的人为动作记录」，
    键沿用 `gate_key(project, workflow, gate_id, digest)` ⇒ **digest 一变旧决定自动失效**，
    不会出现"上次选 720p、这次 1080p 的活儿沿用"。
    ⚠ 铁律（10-02 用户裁定＋R4-06 同一条）：**机器不替人填值**。
    槽没人给就如实存 `null` 并记进 `required_missing`，本函数只负责**暴露缺项**，不负责补齐——
    在这里"顺手给个默认值"就等于机器又替人做了决定，只是换了个形式。
    `by: human` 这句不是自夸，是有 `sources` 逐槽背书的：`sheet`＝决定单里人填的、
    `args`＝这批命令行显式传的，两条来路都不是机器自己想的（G13 判的就是这个）。
    → 返回缺项列表（空＝这批的必填槽都由人给过了）。
    """
    data = read_approvals(cfg)
    data.setdefault("run_decisions", {})
    key = gate_key(project, workflow, gate_id, digest)
    got = {str(k): v for k, v in (decisions or {}).items()}
    missing = sorted({str(s) for s in (required or ())
                      if got.get(str(s)) in (None, "", [])})
    data["run_decisions"][key] = {
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "by": "human",
        "sources": {str(k): str(v) for k, v in (sources or {}).items()},
        "decisions": got,
        "required_missing": missing,
    }
    write_approvals(cfg, data)
    return missing


def load_run_decisions_by_key(cfg, key):
    """按现成的 gate_key 取这批决定。**没有就返回 None**——调用方据此报错，
    不许在这里兜底成"当成没要求"：静默补默认是留痕机制最坏的死法。"""
    if not key:
        return None
    return (read_approvals(cfg).get("run_decisions") or {}).get(str(key))


def load_run_decisions(cfg, project, workflow, gate_id, digest):
    """同一个查法的「按成分给」版本：键的拼法只有 `gate_key` 一处，这里不另算。

    现下消费方＝tests（钉住两个入口结果一致）＋人查台账；
    便签那条拿到的是现成键，走 `load_run_decisions_by_key`。
    """
    return load_run_decisions_by_key(cfg, gate_key(project, workflow, gate_id, digest))


def record_gate_bypass(cfg, project, workflow, reason, gates=(), by="human"):
    """绕过机械闸的唯一合法路径留下的字据（R5-07：改 `preflight: off` 不算解释，得记账）。

    以前 off 只在日志里留一行，日志会滚掉 ⇒「绕过无痕」。
    现在每次绕都在台账 `bypassed` 段落一条：什么时候、哪个项目/流、绕了哪些闸、为什么。
    ⚠ 台账坏了这里会**直接抛**——那不是缺陷，是规矩：宁可停下让人修台账，
      也不能让一次没有字据的绕过悄悄出片（同 `read_approvals` 那条注释）。

    `by` 的口径（2026-10-19 第⑦条，用户裁『改成如实记录来源』）：
      · `human`                     人显式做的动作（本参数缺省值）
      · `config:<键>=off`           靠改 config 绕的——**也是人改的，但触发者是配置**，
                                     统计"人批了多少次绕过"时不该混进来
      · `tier:play`                 娱乐流预览档自动展开的，**没有任何人批过**
    🔴 历史条目（10-19 之前）一律是硬编码的 `human`，**不改写**——改了就没有"当时口径宽松"这段证据。
      所以按 by 统计时，2026-10-19 之前的条目要整段当"来源未区分"处理。
    """
    data = read_approvals(cfg)
    data.setdefault("bypassed", {})
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    key = "%s|%s|%s" % (project or "-", workflow or "-", stamp)
    data["bypassed"][key] = {"at": stamp, "by": str(by or "human"),
                             "reason": str(reason or "")[:400],
                             "gates": [str(g) for g in (gates or [])]}
    write_approvals(cfg, data)
    return key


def register_pending(cfg, key, meta):
    data = read_approvals(cfg)
    m = dict(meta or {})
    m["asked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    data["pending"][key] = m
    write_approvals(cfg, data)


def list_pending(cfg):
    return read_approvals(cfg)["pending"]


@task("gate")
def t_gate(p, ctx):
    """关口步骤（YAML 里当独立一步用，绕不过去的那种在 video 任务内部）。

    params:
      mode: human | auto                  默认 human
      gate_id: 关口编号（H3/G-pre 等）     默认取步骤 id
      label: 给人看的一句话
      files / videos: human 模式要推的东西（图/视频路径列表）
      numbering: 编号映射表，如 ["镜5·A=纯图四锚", "镜5·B=加参考视频"]
      auto_gates: auto 模式要跑的闸，如 [G1,G2,G3,G4,G5,G6,G7,G11]
      refs / ref_videos / prompt / width / height / length / lora /
      workflow_json / strict / required: auto 模式的入参（不填则从 args 取）
      reask_minutes: 同一内容被拒后再推的间隔（默认不自动重推）
    行为：human 未批 → 推飞书 + 记 pending + 抛 GateAwaiting 停住整条链；
          已批 → 放行并在日志注明；被 --deny → 抛 GateDenied。
    """
    cfg = ctx["cfg"]
    args = ctx.get("args") or {}
    mode = str(p.get("mode") or "human").lower()
    gid = str(p.get("gate_id") or ctx.get("step_id") or "gate")

    if mode == "auto":
        return _gate_auto(p, ctx, gid)
    if mode not in ("human",):
        raise ValueError(f"gate.mode 只支持 human/auto，收到 {mode}")

    project = str(cfg.get("project") or "")
    refs = _as_list(p.get("refs")) or _as_list(args.get("ref_images"))
    refv = _as_list(p.get("videos_ref")) or _as_list(args.get("ref_videos"))
    prompt = resolve_prompt(p) or str(args.get("prompt") or "")
    parts = digest_parts(prompt, refs, refv,
                         p.get("width") or args.get("width"),
                         p.get("height") or args.get("height"),
                         p.get("length") or args.get("length"),
                         p.get("lora") or args.get("lora"),
                         args.get("theme"))
    # W5b：批准绑这一批真实提交参数＋（终审时）媒体内容哈希，
    # 换 seed/步数/强度/模板/素材/成片 ⇒ 指纹变 ⇒ 旧批准不继承
    media = [str(x) for x in (list(_as_list(p.get("videos")))
                              + list(_as_list(p.get("files"))))]
    parts += gate_binding_parts(p, args, ctx, media=media)
    digest = content_digest(parts)
    key = gate_key(project, ctx.get("workflow"), gid, digest)
    data = read_approvals(cfg)
    if key in data["approved"]:
        a = data["approved"][key]
        log(ctx, f"[gate:{gid}] 已批准（{a.get('at')} 来源 {a.get('source', '人工')}），放行")
        return {"gate": gid, "approved": True, "key": key, "at": a.get("at")}
    if key in data["denied"]:
        d = data["denied"][key]
        raise GateDenied(f"[gate:{gid}] 你已明确否掉这一步（{d.get('at')}）："
                         f"{d.get('note') or '无备注'}。改内容后重来会自动重新上报。")

    # —— 未批：先上报，再停下 ——
    # 同样内容在 10 分钟内重复跑到这里，不再刷屏（只提示；要重推用 reask_minutes=0）
    pend = (data.get("pending") or {}).get(key)
    if pend:
        try:
            age = (time.time() - time.mktime(time.strptime(
                str(pend.get("asked_at")), "%Y-%m-%d %H:%M:%S"))) / 60.0
        except Exception:
            age = 999.0
        limit = float(p.get("reask_minutes", 10))
        if age < limit:
            log(ctx, f"[gate:{gid}] 已在 {age:.1f} 分钟前上报过（{pend.get('label')}），"
                     f"不重复推送。回飞书或跑 --approve last {gid} 即放行。")
            raise GateAwaiting(f"[gate:{gid}] 等人工确认（上次上报 {age:.1f} 分钟前，未重复推送）。"
                               f"批准后：python run.py --approve last {gid} "
                               f"再 --resume {ctx.get('run_id')}")
    label = str(p.get("label") or ctx.get("step_label") or f"关口 {gid}")
    lines = [f"【关口 {gid} · {label}】",
             f"项目：{project or '-'}  工作流：{ctx.get('workflow') or '-'}  "
             f"run_id：{ctx.get('run_id')}",
             f"主题：{args.get('theme') or '-'}"]
    num = [str(x) for x in (p.get("numbering") or [])]
    if not num:
        # 没手写编号表就自动按发送顺序编号，名字取文件名——报号才有的可报
        media = [str(f) for f in (p.get("files") or [])] +                 [str(v) for v in (p.get("videos") or [])]
        num = [Path(m).name for m in media]
    if num:
        lines.append("编号映射：")
        lines += [f"  {i+1} = {s}" for i, s in enumerate(num)]
    if str(p.get("show_prompt", "")).lower() in ("true", "1", "yes") and prompt:
        lines.append("—— 提示词全文 ——")
        lines.append(prompt[:1500] + ("…" if len(prompt) > 1500 else ""))
    lines.append(f"回复：过 / 改<说哪一处> / 否 <理由>   （gate_key={key}）")
    lines.append("不回就不往下跑，GPU 不动。")
    caption = "\n".join(lines)

    files = _as_list(p.get("files"))
    videos = _as_list(p.get("videos"))
    if not files and not videos:
        caption = caption + "\n（本关口无附件，纯文字确认）"
    # 通知面＝**四件**：待批清单 + 报告 awaiting_human + 桌面气泡 + 飞书出向推送。
    # 2026-10-19 用户裁定把出向推送接回来（第③条）：09-20 那轮"纯本地不走飞书"整段删掉之后，
    # 设计里的「首帧必发飞书目审」「第一镜必发」在引擎内根本没有牙齿——没人拦得住绕过目审直接跑。
    # ⚠ 只接**出向**：入向读不到（群历史被拒 230027），所以"批准"仍然走会话或 --approve，
    #   这里发完不等回话；开关＝config.yaml 的 feishu.push_gates（缺省 on，可写 off / dry）。
    push = push_gate_review(cfg, caption, files, videos,
                            lambda m: log(ctx, m))
    write_pending_note(cfg, gid, label, caption, files, videos, akey=key)
    log(ctx, f"[gate:{gid}] 待批清单已落 logs/workflows/待批关口.txt")
    toast(f"关口待确认：{gid} {label}",
          f"python run.py --approve {ctx.get('run_id')} {gid} 后 --resume last，或在 Qoder 里回我一句「过」")
    meta = {"gate": gid, "label": label, "project": project,
            "workflow": ctx.get("workflow"), "run_id": ctx.get("run_id"),
            "theme": args.get("theme"), "caption": caption}
    meta.update(push)
    register_pending(cfg, key, meta)
    NL = chr(10)
    raise GateAwaiting(
        f"[gate:{gid}] 等人工确认（待批清单与桌面提示已就位）。批准后：" + NL +
        f"  python run.py --approve {ctx.get('run_id')} {gid}" + NL +
        f"再 --resume last。")


def write_pending_note(cfg, gid, label, caption, files=None, videos=None, decisions=None,
                       akey=None):
    """把待批关口写成人能直接看的文本清单（免终端：记事本/资源管理器双击即可）。

    10-02 批 5-2（用户裁定 G-3）：清单里**同时打印这批的运行决定**，
    让人在手机／飞书上看到便签就能直接判"这几个值不对"，不必去开 json。
    值一律由 `record_run_decisions` 人录；这里只复述，**不补默认**。
    """
    try:
        NL = chr(10)
        path = Path(cfg["log_dir"]) / "待批关口.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        media = ([Path(str(f)).name for f in (files or [])]
                 + [Path(str(v)).name for v in (videos or [])])
        block = [f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 关口 {gid} · {label}",
                 caption, ""]
        if media:
            block.append("待审素材（编号即报号顺序）：")
            block += [f"  {i+1}. {m}" for i, m in enumerate(media)]
            block.append("")
        # G-3（10-02 已裁）：便签也打印当次运行决定。单独包一层 try——
        # 外层是 `except Exception: pass`，决定打印出错不该顺手把整张素材清单一起吞掉。
        try:
            dec = decisions
            if dec is None and akey:
                dec = (load_run_decisions_by_key(cfg, akey) or {}).get("decisions")
            if dec:
                block.append("本批运行决定（人录，机器不代填）：")
                block += [f"  · {k} = {('（未给）' if v in (None, '') else v)}"
                          for k, v in sorted(dec.items())]
                block.append("")
        except Exception:
            pass
        block.append("=" * 68)
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(NL.join(block) + NL)
    except Exception:
        pass     # 清单只是便利面，写不进去不能顶掉阻断本身


def toast(title, body):
    """Windows 气泡提示。失败不抛——它是锦上添花，不是通路。"""
    try:
        ps = ("$w=New-Object -ComObject WScript.Shell;"
              f'$w.Popup("{body}",20,"{title}",64)')
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                          "-Command", ps], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _as_list(v):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x) for x in v]


def _gate_auto(p, ctx, gid):
    """auto 模式：复用跑前自审闸，但用于"还没到 video 步骤"的 YAML 位置。"""
    args = ctx.get("args") or {}
    cfg = ctx["cfg"]
    refs = _as_list(p.get("refs")) or _as_list(args.get("ref_images"))
    refv = _as_list(p.get("ref_videos")) or _as_list(args.get("ref_videos"))
    only = [str(x).upper() for x in (p.get("auto_gates") or
                                     ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G11",
                                      "G13"])]
    if str(ctx.get("workflow") or "").startswith("selftest"):
        # 自测的落点在 tmp，不含项目段 —— G11 不适用（真出片时照旧硬拦）。
        # G13 同理要摘掉：自测不该依赖「人填过决定单」，否则自测永远红，
        # 而一个永远红的自测等于没有自测。真出片的路径两条都在。
        only = [g for g in only if g not in ("G11", "G13")]
    chars = p.get("characters")
    # 音频素材：YAML 的 gate 步历来只转图/视频，G4 因此"看不见音频"——
    # 10-24 跑 P7 负例时暴露：`pre` 步把"只给音频"降级放行了，走到 gen 的 preflight 才拦，
    # 而那时候已经白等过一次服务装载。这里两边都兜：步内显式给的优先，没有就从本批 args 取。
    refa = _as_list(p.get("ref_audios")) or _as_list(args.get("ref_audios"))
    refva = _as_list(p.get("ref_video_audios")) or _as_list(args.get("ref_video_audios"))
    spec = {"prompt": resolve_prompt(p) or str(args.get("prompt") or ""),
            "refs": refs, "ref_videos": refv,
            "ref_audios": refa, "ref_video_audios": refva,
            "characters": ("none" if str(chars) in ("none", "None", "") else
                           [str(x) for x in (chars or
                                             (cfg.get("characters_needing_anchor") or []))]),
            "prompt_kind": str(p.get("prompt_kind") or "video"),
            "input_mode": str(p.get("input_mode") or ""),
            "w": int(p.get("width") or args.get("width") or 0) or None,
            "h": int(p.get("height") or args.get("height") or 0) or None,
            "length": int(p.get("length") or args.get("length") or 0) or None,
            "lora": p.get("lora") or args.get("lora"),
            "workflow_json": p.get("workflow_json"),
            "provider": str(p.get("provider") or "local"),
            "seed": p.get("seed") or args.get("seed"),
            "theme": args.get("theme"), "batch_id": args.get("batch_id"),
            "project": cfg.get("project"), "project_aliases": cfg.get("project_aliases"),
            "output_root": str(ctx.get("batch_dir") or cfg.get("output_root") or ""),
            "pool_root": cfg.get("pool_root")}
    preflight_or_die({k: v for k, v in
                      {"prompt": spec["prompt"], "prompt_kind": spec["prompt_kind"],
                       "ref_images": refs, "width": spec["w"],
                       "height": spec["h"], "length": spec["length"], "lora": spec["lora"],
                       # 这两键必须一起给：preflight_or_die 内部是按 params 取音频列表的，
                       # 少一处 = 闸在看一份没有音频的清单（P7 负例当时就是这个形状漏过去的）
                       "ref_audios": refa, "ref_video_audios": refva,
                       "input_mode": spec["input_mode"]}.items()
                      if v not in (None, "")},
                     ctx, refs, refv, spec["workflow_json"], only=only)
    return {"gate": gid, "auto": True, "refs": len(refs), "audios": len(refa) + len(refva),
            "gates": only}


@task("feishu")
def t_feishu(p, ctx):
    """发**图＋视频**到飞书接收群（bot 身份；user 身份 token_missing，只能 --as bot）。

    params: files(图) / videos(视频，2026-10-19 新接) / caption(配文，另发纯文本) /
            enabled(默认 true) / retries(默认 3)。
    实现全在 `send_media_to_feishu`——人工关口（t_gate）用的是**同一份**，
    免得两条通路各自演化出两套口径（这正是 gaze 规则散在 5 处那个病）。
    """
    if str(p.get("enabled", True)).lower() in ("false", "0", "no"):
        log(ctx, "[feishu] enabled=false，跳过发送")
        return {"sent": 0, "skipped": True}
    cfg = ctx["cfg"]
    files = _as_list(p.get("files"))
    videos = _as_list(p.get("videos"))
    if not files and not videos:
        raise ValueError("feishu 需要 files 或 videos（要发送的素材）")
    caption = str(p.get("caption", "") or "").strip()
    retries = int(p.get("retries", 3))
    sent = send_media_to_feishu(cfg, files, videos, caption,
                                lambda m: log(ctx, m), retries=retries)
    return {"sent": sent["images"] + sent["videos"],
            "images_sent": sent["images"], "videos_sent": sent["videos"],
            "caption_sent": bool(caption)}

