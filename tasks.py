# -*- coding: utf-8 -*-
"""任务模块注册表。

新增任务类型：写一个函数，用 @task("名字") 注册即可被工作流 YAML 使用。
函数签名 fn(params: dict, ctx: dict) -> dict（结果可被后续步骤用 {{step_id.field}} 引用）。

ctx 可用键：cfg(全局配置) / args(工作流参数) / run_id / log(日志函数) / wf_root(本目录)。
"""
import base64
import copy
import fnmatch
import io
import json
import os
import random
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import requests

REGISTRY = {}


def task(name):
    def deco(fn):
        REGISTRY[name] = fn
        return fn
    return deco


CREATE_NO_WINDOW = 0x08000000


def log(ctx, msg):
    ctx["log"](msg)


def http_ok(url, timeout=2):
    try:
        return requests.get(url, timeout=timeout).status_code == 200
    except Exception:
        return False


def pid_of_port(port):
    out = subprocess.run("netstat -ano", shell=True, capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 5 and f[3] == "LISTENING" and f[1].endswith(f":{port}"):
            return int(f[4])
    return None


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
    if m.get("remote"):
        # 云端：不需要本地拉起；可用性在请求时判定（网络错误会进兜底链错误列表）
        return True
    base = m["base_url"].rstrip("/")
    if http_ok(base + "/v1/models"):
        return True
    logf = Path(ctx["cfg"]["log_dir"]) / f"launcher_{key}_{ctx['run_id']}.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    log(ctx, f"[llm] {key} 未就绪，自动拉起: {m['launcher']}（输出 {logf.name}）")
    with open(logf, "wb") as fh:
        proc = subprocess.Popen(m["launcher"], shell=True,
                                creationflags=CREATE_NO_WINDOW,
                                stdin=subprocess.DEVNULL, stdout=fh, stderr=fh)
        t0 = time.time()
        while time.time() - t0 < m.get("startup_timeout", 300):
            time.sleep(3)
            if http_ok(base + "/v1/models"):
                log(ctx, f"[llm] {key} 已就绪（等待 {time.time() - t0:.0f}s）")
                return True
            if proc.poll() is not None:
                tail = logf.read_text(encoding="utf-8",
                                      errors="replace").strip()[-300:]
                raise RuntimeError(
                    f"{key} 的 launcher 已退出（code={proc.returncode}），"
                    f"多半是显存被占或模型路径不对，详见 {logf}"
                    f"\n{tail}")
    log(ctx, f"[llm] {key} 启动超时（{m.get('startup_timeout', 300)}s），"
             f"launcher 输出见 {logf}")
    return False


@task("llm")
def t_llm(p, ctx):
    """本地 LLM 调用 + 兜底链。params: backend(auto|名字|逗号列表) / system /
    prompt / max_tokens / temperature / timeout / enabled / static

    enabled=false 时不调模型、不触发 launcher、不参与显存仲裁，直接把 static
    当结果返回 —— 预留接口但不接上，下游 {{步骤.text}} 照常可用。
    """
    if str(p.get("enabled", True)).lower() in ("false", "0", "no"):
        txt = str(p.get("static", ""))
        log(ctx, f"[llm] enabled=false，跳过模型调用，直接用 static（{len(txt)} 字符）")
        return {"text": txt, "backend": "static", "elapsed": 0.0}
    cfg = ctx["cfg"]
    backend = str(p.get("backend", "auto"))
    if backend == "auto":
        chain = list(cfg.get("fallback_chain") or [])
    elif backend == "local":
        # webui「仅本地」：从兜底链剔除 remote（云端），只留本地后端
        chain = [k for k in (cfg.get("fallback_chain") or [])
                 if not cfg["models"].get(k, {}).get("remote")]
        if not chain:
            raise RuntimeError("local: 兜底链里没有本地模型（config.yaml models 均标 remote）")
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
            msgs.append({"role": "user", "content": str(p.get("prompt", ""))})
            body = {"model": m["name"], "messages": msgs,
                    "max_tokens": int(p.get("max_tokens", 512)),
                    "temperature": float(p.get("temperature", 0.7))}
            headers = {}
            if m.get("remote"):
                env_key = m.get("api_key_env")
                key = os.environ.get(env_key, "") if env_key else ""
                if not key:
                    errors.append(f"{key}: 未设置 {env_key}（网页「云端 API 设置」里填）")
                    continue
                headers["Authorization"] = f"Bearer {key}"
            t0 = time.time()
            r = requests.post(m["base_url"].rstrip("/") + "/v1/chat/completions",
                              json=body, timeout=int(p.get("timeout", 300)),
                              headers=headers)
            if r.status_code != 200:
                errors.append(f"{key}: HTTP {r.status_code} {r.text[:120]}")
                continue
            text = r.json()["choices"][0]["message"]["content"]
            el = round(time.time() - t0, 1)
            log(ctx, f"[llm] 由 {key} 服务（{el}s, {len(text)} 字符）")
            return {"text": text, "backend": key, "elapsed": el}
        except Exception as e:
            errors.append(f"{key}: {type(e).__name__} {str(e)[:120]}")
    raise RuntimeError("兜底链全部失败: " + " | ".join(errors))


# ---------------------------------------------------------------- vision 判分
VL_KEY_FILE = Path("E:/密钥文件/阿里多模态.txt")


def vl_score_image(image_path, api_key=None, base_url=None, model=None,
                   rewrite_prompt=None):
    """云端多模态判分一张图：压缩后上传 qwen-vl，返回
    {score, dims:{face,compose,quality,mood}, reasons[], suggestion, model}。
    如果 rewrite_prompt 传了（当前提示词），让 VL 同时输出改写后的提示词（new_prompt 字段）。
    key 默认读 E:\\密钥文件\\阿里多模态.txt（DashScope 按量，免费额度）。"""
    if not Path(image_path).is_file():
        raise RuntimeError(f"判分图不存在: {image_path}")
    key = api_key or os.environ.get("AW_VL_API_KEY", "")
    base = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = model or os.environ.get("AW_VL_MODEL") or "qwen-vl-plus"
    if not key and VL_KEY_FILE.exists():
        lines = VL_KEY_FILE.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            key = lines[0].strip()
        if len(lines) > 1 and lines[1].strip():
            base = lines[1].strip().rstrip("/")
    if not key:
        raise RuntimeError("未配置多模态 API Key（AI 判分不可用，见 E:\\密钥文件\\阿里多模态.txt）")
    from PIL import Image
    img = Image.open(image_path)
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    if rewrite_prompt:
        # VL 直接闭环模式：判分 + 改写提示词
        prompt = ('这是一张 AI 生成的人物图，当前提示词是：\n'
                  f'"{rewrite_prompt}"\n\n'
                  '请从 人物面部/姿势、构图、画质细节、整体氛围 四个维度打分（每维 0-25，总分 0-100），'
                  '指出主要扣分点，并根据扣分点直接改写提示词（保持主题不变，针对性增强）。'
                  '只输出 JSON：{"score":总分,"dims":{"face":..,"compose":..,"quality":..,"mood":..},'
                  '"reasons":[".."],"suggestion":"..","new_prompt":"改写后的英文提示词"}')
    else:
        # 纯判分模式
        prompt = ('这是一张 AI 生成的人物图。请从 人物面部/姿势、构图、画质细节、整体氛围 四个维度'
                  '打分（每维 0-25，总分 0-100），指出主要扣分点和一句改进建议。'
                  '只输出 JSON：{"score":总分,"dims":{"face":..,"compose":..,"quality":..,"mood":..},'
                  '"reasons":[".."],"suggestion":".."}')
    body = {"model": model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt}]}],
            "max_tokens": 400}
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"多模态 API HTTP {e.code}: "
                           f"{e.read().decode('utf-8','replace')[:200]}")
    txt = d["choices"][0]["message"]["content"]
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    try:
        parsed = json.loads(txt)
    except Exception:
        parsed = {"score": None, "raw": txt[:500]}
    parsed["model"] = model
    return parsed


@task("auto")
def t_auto(p, ctx):
    """闭环自动出图（agent 最小闭环）：云端 LLM 规划提示词 → 出图 → VL 判分 →
    低分时改写提示词重跑（最多 max_tries 轮），直到达标或轮尽。

    两种改写模式：
    - rewrite_mode="text"（默认，成本低）：VL 判分 → 文本 LLM 读理由改写提示词
    - rewrite_mode="vl"（成本高，信息无损）：VL 看图 + 读提示词 → 直接输出改写后的提示词

    params: theme(中文需求) / prompt(初始英文提示词，空=由 LLM 从 theme 生成) /
    count / width / height / steps / loras / seed / workflow(comfy 模板) /
    threshold(默认 78) / max_tries(默认 3) / backend(默认 cloud，可 auto) /
    rewrite_mode(默认 text，可选 vl) / prefix。
    返回 {"files": 最优轮产物, "scores": 对应分数, "rounds": [...], "prompt"}。
    """
    threshold = int(p.get("threshold", 78))
    max_tries = int(p.get("max_tries", 3))
    cfg = ctx["cfg"]
    theme = str(p.get("theme", "")).strip()
    prompt = str(p.get("prompt", "") or "").strip()
    backend = str(p.get("backend", "cloud"))
    rewrite_mode = str(p.get("rewrite_mode", "text")).strip().lower()
    t0 = time.time()
    rounds = []

    def gen_prompt_text(round_no, feedback=""):
        """文本 LLM 模式：生成/改写提示词。"""
        nonlocal prompt
        sys_p = ("你是 FLUX 提示词工程师。任务：把中文需求转成 60~120 词的英文照片级提示词，"
                 "只输出提示词本身，不要任何解释或引号。")
        if round_no == 1 and prompt:
            return prompt
        user = f"中文主题：{theme}"
        if round_no == 1:
            user += "\n请输出英文照片级提示词。"
        else:
            user += (f"\n上轮 AI 判分（0-100）与扣分理由：{feedback}\n"
                     f"请针对上述扣分点改写/增强提示词（保持主题不变），只输出新的英文提示词。")
        lp = {"system": sys_p, "prompt": user, "max_tokens": 300,
              "temperature": 0.7, "backend": backend}
        r = t_llm(lp, ctx)          # 云端优先，本地兜底；缺额时后方 chain 接管
        prompt = str(r["text"]).strip()
        return prompt

    best = {"score": -1, "files": []}
    for i in range(1, max_tries + 1):
        # 生成当前轮提示词
        if i == 1:
            if prompt:
                cur_prompt = prompt
            elif rewrite_mode == "vl":
                # VL 模式第一轮：让文本 LLM 生成初始提示词（VL 不参与第一轮生成）
                cur_prompt = gen_prompt_text(1, "")
            else:
                cur_prompt = gen_prompt_text(1, "")
        else:
            # 第二轮起：根据 rewrite_mode 决定改写方式
            if rewrite_mode == "vl":
                # VL 直接改写：用上轮第一张图 + 当前提示词，让 VL 输出 new_prompt
                prev_files = rounds[-1].get("files") or []
                if prev_files:
                    try:
                        vl_result = vl_score_image(prev_files[0], rewrite_prompt=prompt)
                        new_p = str(vl_result.get("new_prompt", "")).strip()
                        if new_p:
                            cur_prompt = new_p
                            log(ctx, f"[auto] VL 直接改写提示词: {cur_prompt[:90]}")
                        else:
                            # VL 没返回 new_prompt，回退到文本 LLM
                            log(ctx, "[auto] VL 未返回 new_prompt，回退文本 LLM 改写")
                            feedback = f"第{i-1}轮 {rounds[-1].get('score')} 分，理由：" + "；".join(rounds[-1].get("reasons") or [])
                            cur_prompt = gen_prompt_text(i, feedback)
                    except Exception as e:
                        log(ctx, f"[auto] VL 改写失败({e})，回退文本 LLM 改写")
                        feedback = f"第{i-1}轮 {rounds[-1].get('score')} 分，理由：" + "；".join(rounds[-1].get("reasons") or [])
                        cur_prompt = gen_prompt_text(i, feedback)
                else:
                    cur_prompt = gen_prompt_text(i, "")
            else:
                # 文本 LLM 改写
                feedback = f"第{i-1}轮 {rounds[-1].get('score')} 分，理由：" + "；".join(
                    rounds[-1].get("reasons") or [])
                cur_prompt = gen_prompt_text(i, feedback)

        log(ctx, f"[auto] 第 {i}/{max_tries} 轮 提示词: {cur_prompt[:90]}")
        cp = {"workflow": p.get("workflow", "comfy/draft_flux_api.json"),
              "prompt": cur_prompt, "count": int(p.get("count", 1)),
              "width": p.get("width", 832), "height": p.get("height", 1216),
              "steps": p.get("steps", 12), "loras": p.get("loras", ""),
              "seed": p.get("seed", ""), "prefix": p.get("prefix", "auto"), 
              "stage": p.get("stage", "final")}
        got = t_comfyui(cp, ctx)
        files = list(got["files"])
        scores = []
        for f in files:
            try:
                s = vl_score_image(f)
            except Exception as e:
                log(ctx, f"[auto] 判分失败({Path(f).name}): {e}；跳过本轮评价")
                s = {"score": None, "reasons": []}
            scores.append(s)
            log(ctx, f"[auto] 第{i}轮 {Path(f).name}: {s.get('score')} 分")
        avg = [s["score"] for s in scores if isinstance(s.get("score"), (int, float))]
        round_score = round(sum(avg) / len(avg), 1) if avg else None
        reasons = []
        for s in scores:
            reasons.extend(s.get("reasons") or [])
        rounds.append({"round": i, "score": round_score, "reasons": reasons,
                       "prompt": cur_prompt, "files": files})
        if round_score is not None and round_score >= threshold:
            best = {"score": round_score, "files": files}
            log(ctx, f"[auto] 第{i}轮达到阈值 {threshold}，接受")
            break
        if round_score is not None and round_score > best["score"]:
            best = {"score": round_score, "files": files}
        time.sleep(1)   # 给云端限流留呼吸
    # 没达标也把最好一轮的产物交回
    if best["files"]:
        return {"files": best["files"],
                "scores": [best["score"]] * len(best["files"]),
                "rounds": rounds, "prompt": prompt,
                "elapsed": round(time.time() - t0, 1)}
    raise RuntimeError("auto: 未产出任何有效图片")


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
    base_w = int(p.get("width", 640))
    base_h = int(p.get("height", 960))
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


def poll_history(ctx, base, prompt_id, timeout, pre_snapshot=None):
    out_dir = ctx["cfg"]["comfyui"]["output_dir"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            r = requests.get(f"{base}/history/{prompt_id}", timeout=10)
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
            files = []
            for node_out in (h.get("outputs") or {}).values():
                for im in node_out.get("images", []):
                    files.append(str(Path(out_dir) / im.get("subfolder", "")
                                     / im["filename"]))
            return files
    # 超时：history API 没报完成，但图可能已落地（ComfyUI 偶发不更新 status）
    if pre_snapshot is not None:
        img_exts = {".png", ".jpg", ".jpeg", ".webp"}
        current = set(f for f in Path(out_dir).rglob("*")
                      if f.is_file() and f.suffix.lower() in img_exts)
        new_files = current - pre_snapshot
        if new_files:
            log(ctx, f"[poll_history] 超时但发现 {len(new_files)} 个新文件，按成功处理")
            return [str(f) for f in sorted(new_files)]
        raise RuntimeError(f"ComfyUI 执行超时（>{timeout}s）且暂存区无新产物")
    raise RuntimeError(f"ComfyUI 执行超时（>{timeout}s）")


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
        shutil.move(str(src), str(to))
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


def ensure_comfyui(ctx):
    """确保 ComfyUI 在跑并返回 base_url；未运行则先做显存仲裁再拉起。

    出图与精修共用这一份：仲裁端口范围与启动命令只在这里定义一次。
    """
    cfg = ctx["cfg"]["comfyui"]
    base = cfg["base_url"].rstrip("/")
    if http_ok(base + "/system_stats"):
        return base
    for port in cfg.get("kill_ports_before_start") or []:
        pid = pid_of_port(port)
        if pid:
            log(ctx, f"[comfyui] 显存仲裁：结束端口 {port} 上的 llama-server (PID {pid})")
            subprocess.run(f"taskkill /PID {pid} /F", shell=True,
                           capture_output=True)
    time.sleep(3)
    log(ctx, "[comfyui] 启动 ComfyUI ...")
    cmd = cfg.get("launch_cmd") or (
        f'cmd /c ".\\python_embeded\\python.exe -s ComfyUI\\main.py '
        f'--windows-standalone-build --output-directory {cfg["output_dir"]}"')
    with open(cfg.get("log", "comfyui.log"), "ab") as logf:
        subprocess.Popen(cmd, shell=True, cwd=cfg["root"],
                         creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL,
                         stdout=logf, stderr=logf)
        t0 = time.time()
        while time.time() - t0 < cfg.get("startup_timeout", 240):
            time.sleep(3)
            if http_ok(base + "/system_stats"):
                log(ctx, f"[comfyui] 已就绪（{time.time() - t0:.0f}s）")
                return base
    raise RuntimeError("ComfyUI 启动超时")


@task("comfyui")
def t_comfyui(p, ctx):
    """ComfyUI 出图。params: workflow(模板相对路径) / prompt / count / width /
    height / steps / guidance / seed(可空=随机) / prefix / stage(落进批次夹的子目录，默认 draft) /
    loras[{name,strength}] / timeout。服务未运行时自动启动（先按显存仲裁清掉 llama-server）。"""
    base = ensure_comfyui(ctx)
    tpl = json.loads((Path(ctx["wf_root"]) / p["workflow"]).read_text(encoding="utf-8"))
    count = int(p.get("count", 1))
    files, seeds, t0 = [], [], time.time()
    for i in range(count):
        seed = p.get("seed")
        seed = random.randint(0, 2**31 - 1) if seed in (None, "") else int(seed) + i
        graph = build_graph(tpl, p, seed)
        sc = float(p.get("scale_by", 1.0) or 1.0)
        if sc != 1.0:
            log(ctx, f"[comfyui] scale_by={sc}：基图 "
                     f"{int(p.get('width', 640)) // sc}x{int(p.get('height', 960)) // sc} "
                     f"→ 成品 {int(p.get('width', 640))}x{int(p.get('height', 960))}")
        out_dir = Path(ctx["cfg"]["comfyui"]["output_dir"])
        pre_snapshot = set(f for f in out_dir.rglob("*") if f.is_file())
        r = requests.post(base + "/prompt", json={"prompt": graph}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"任务提交失败: {r.text[:300]}")
        pid_ = r.json()["prompt_id"]
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
    exp = (int(p.get("width", 640)), int(p.get("height", 960)))
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
    return {"files": files, "seeds": seeds, "count": len(files),
            "elapsed": round(time.time() - t0, 1),
            "width": sizes[0][0], "height": sizes[0][1],
            "steps": int(p.get("steps", 28)), "prompt": str(p.get("prompt", ""))}


@task("refine")
def t_refine(p, ctx):
    """对选中的草稿做生成式精修（UltimateSDUpscale），保留原构图。

    直接高分辨率重画保不住草稿构图（seed 不跨分辨率），所以精修必须走
    「载入草稿 + 分块重绘放大」。params: files(草稿路径列表) / prompt / template /
    tile / steps / upscale_by / denoise / guidance / prefix / seed / timeout
    """
    cfg = ctx["cfg"]["comfyui"]
    base = ensure_comfyui(ctx)
    tpl_path = Path(ctx["wf_root"]) / p.get("template", "comfy/refine_usdu_api.json")
    tpl = json.loads(tpl_path.read_text(encoding="utf-8"))
    input_dir = Path(cfg.get("input_dir",
                             r"E:\LocalAI\ComfyUI_windows_portable\ComfyUI\input"))
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
        r = requests.post(base + "/prompt", json={"prompt": graph}, timeout=30)
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
