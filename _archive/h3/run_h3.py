# -*- coding: utf-8 -*-
"""MiniMax H3 本地 I2V 测试/生产脚本（直调 ComfyUI /prompt，原生节点）。

用法:
  py run_h3.py <首帧图片路径> <提示词> [--w 832 --h 480 --len 124 --steps 20 --seed 42 --out h3_i2v]

流程: 复制首帧到 ComfyUI input -> 构建原生 H3 I2V 工作流 -> POST /prompt -> 轮询 /history -> 落盘 mp4。
"""
import sys, time, json, shutil, os, argparse, urllib.request, urllib.error, uuid

HOST = "http://127.0.0.1:8189"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUTPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"  # 与 ComfyUI 启动参数 --output-directory 保持一致

MODEL = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
REF2VA_MODEL = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
# 生产标准（用户 2026-09-13 定）：最低 8 步 + turbo8step LoRA；4 步版画面有缺陷已弃用。
# 想禁用 LoRA 传 --lora ""
DEFAULT_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"

# 噪声调度平移（SigmaShift / DualClock 的 shift_video）。2026-09-21 前是写死的 12.0。
# 依据：高噪声步主要管粗结构与运动、低噪声步管细节纹理 —— 调大 shift＝把采样时间挪给运动，
# 代价是画质/保真下降（探测论文口径"控制强度与运动量此消彼长"，且过大反而动态下降）。
SHIFT_VIDEO = 12.0


def http_json(method, url, data=None, retries=600):
    """ComfyUI 在执行长任务时事件循环被占死，/history 这类 GET 会超时——
       那不是任务失败，是服务器暂时不接电话。2026-09-21 烬骨辞镜8/9/10 就是这样
       被客户端误判成 FAIL（GPU 其实还在正常出片）。GET 一律重试，
       POST /prompt（提交）不重试，避免把同一镜排两遍队。"""
    body = None
    req = urllib.request.Request(url, method=method)
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    for k in range(retries if data is None else 1):
        try:
            with urllib.request.urlopen(req, body, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError):
            if data is not None or k == retries - 1:
                raise
            time.sleep(10)
    raise RuntimeError("http_json 重试耗尽: " + url)


def build_workflow(prompt, w, h, length, steps, seed, img_filename,
                   lora_name=None, lora_strength=1.0, with_audio=True,
                   last_img_filename=None):
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": img_filename}},
        "2": {"class_type": "UNETLoader",
              "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "5": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "6": {"class_type": "VAELoader",
              "inputs": {"vae_name": VAE}},
        "7": {"class_type": "MiniMaxH3ImageToVideo",
              "inputs": {"clip": ["5", 0], "vae": ["6", 0], "prompt": prompt,
                         "width": w, "height": h, "length": length,
                         "first_frame": ["1", 0]}},
        "8": {"class_type": "ConditioningZeroOut",
              "inputs": {"conditioning": ["7", 0]}},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["6", 0]}},
        "12": {"class_type": "SaveVideo",
               "inputs": {"video": ["11", 0], "filename_prefix": "h3_i2v",
                          "format": "mp4", "codec": "h264"}},
    }
    # 视频合成：可选接 H3 原生音轨（audio VAE 解码 KSampler 的 AV 联合 latent）
    cv_inputs = {"images": ["10", 0], "fps": 24.0}
    if with_audio:
        wf["14"] = {"class_type": "VAELoader",
                    "inputs": {"vae_name": AUDIO_VAE}}
        wf["15"] = {"class_type": "VAEDecodeAudio",
                    "inputs": {"samples": ["9", 0], "vae": ["14", 0]}}
        cv_inputs["audio"] = ["15", 0]
    wf["11"] = {"class_type": "CreateVideo", "inputs": cv_inputs}
    # model 链: UNETLoader -> [LoRA] -> SigmaShift -> LowVRAMAttention
    model_src = ["2", 0]
    if lora_name:
        wf["13"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["2", 0], "lora_name": lora_name,
                               "strength_model": lora_strength}}
        model_src = ["13", 0]
    wf["3"] = {"class_type": "MiniMaxH3SigmaShift",
               "inputs": {"model": model_src, "shift_video": SHIFT_VIDEO, "shift_audio": 3.0}}
    wf["4"] = {"class_type": "MiniMaxLowVRAMAttention",
               "inputs": {"model": ["3", 0], "head_chunks": 4}}
    wf["9"] = {"class_type": "KSampler",
               "inputs": {"model": ["4", 0], "positive": ["7", 0], "negative": ["8", 0],
                          "latent_image": ["7", 1], "seed": seed, "steps": steps,
                          "cfg": 1.0, "sampler_name": "dpmpp_2m", "scheduler": "beta",
                          "denoise": 1.0}}
    if last_img_filename:
        wf["21"] = {"class_type": "LoadImage", "inputs": {"image": last_img_filename}}
        wf["7"]["inputs"]["last_frame"] = ["21", 0]
    return wf


def build_workflow_t8(prompt, w, h, length, steps, seed, img_filename,
                      lora_name=None, lora_strength=1.0, with_audio=True,
                      last_img_filename=None):
    """T8 双时钟采样链：视频/音频各自独立的 sigma 时基（H3 原生协议的推荐路径）。
    原生 KSampler 单一时基会让音频在低步数下变噪；T8 DualClock 分开处理。"""
    wf = {
        "1": {"class_type": "LoadImage",
              "inputs": {"image": img_filename}},
        "2": {"class_type": "UNETLoader",
              "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "5": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "6": {"class_type": "VAELoader",
              "inputs": {"vae_name": VAE}},
        "14": {"class_type": "VAELoader",
               "inputs": {"vae_name": AUDIO_VAE}},
        "7": {"class_type": "MiniMaxH3ImageToVideo",
              "inputs": {"clip": ["5", 0], "vae": ["6", 0], "prompt": prompt,
                         "width": w, "height": h, "length": length,
                         "first_frame": ["1", 0]}},
    }
    if last_img_filename:
        wf["21"] = {"class_type": "LoadImage", "inputs": {"image": last_img_filename}}
        wf["7"]["inputs"]["last_frame"] = ["21", 0]
    # model 链: UNETLoader -> [LoRA] -> LowVRAMAttention -> DualClockSampler
    src = ["2", 0]
    if lora_name:
        wf["13"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["2", 0], "lora_name": lora_name,
                               "strength_model": lora_strength}}
        src = ["13", 0]
    wf["4"] = {"class_type": "MiniMaxLowVRAMAttention",
               "inputs": {"model": src, "head_chunks": 4}}
    wf["16"] = {"class_type": "MiniMaxH3DualClockSamplerT8",
                "inputs": {"model": ["4", 0], "av_latent": ["7", 1], "steps": steps,
                           "shift_video": SHIFT_VIDEO, "shift_audio": 3.0,
                           "sampler_name": "dual_clock_euler", "scheduler": "native_flow"}}
    wf["17"] = {"class_type": "BasicGuider",
                "inputs": {"model": ["16", 0], "conditioning": ["7", 0]}}
    wf["18"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    wf["19"] = {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["18", 0], "guider": ["17", 0], "sampler": ["16", 1],
                           "sigmas": ["16", 2], "latent_image": ["7", 1]}}
    wf["20"] = {"class_type": "MiniMaxH3AVDecodeT8",
                "inputs": {"av_latent": ["19", 0], "video_vae": ["6", 0],
                           "audio_vae": ["14", 0]}}
    cv_inputs = {"images": ["20", 0], "fps": 24.0}
    if with_audio:
        cv_inputs["audio"] = ["20", 1]
    wf["11"] = {"class_type": "CreateVideo", "inputs": cv_inputs}
    wf["12"] = {"class_type": "SaveVideo",
                "inputs": {"video": ["11", 0], "filename_prefix": "h3_i2v",
                           "format": "mp4", "codec": "h264"}}
    return wf


def build_workflow_ref2va(prompt, w, h, length, steps, seed, ref_names,
                          lora_name=None, lora_strength=1.0, with_audio=True,
                          ref_image_size="match", ref_video_names=None):
    """多图/多视频参考（Ref2VA）：靠参考图/视频/音频锁角色，无 first_frame。
    ref_names = 已复制到 ComfyUI input 目录的参考图文件名列表（提示词用 <Picture 1..N> 指代）。
    ref_video_names = 参考视频文件名列表（走 LoadVideo->GetVideoComponents 转帧序列，
    提示词用 <Video k> 指代；官方要求 24fps / 48-360 帧 / 2-15s，内部按 17n+5 截齐，
    超过生成长度的部分会被丢弃）。"""
    wf = {
        "2": {"class_type": "UNETLoader",
              "inputs": {"unet_name": REF2VA_MODEL, "weight_dtype": "default"}},
        "5": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "14": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
    }
    ref_inputs = {}
    for i, nm in enumerate(ref_names):
        nid = str(100 + i)
        wf[nid] = {"class_type": "LoadImage", "inputs": {"image": nm}}
        # 键名格式经内省确认为 "ref_images.ref_image_N"（组名.前缀序号）
        ref_inputs[f"ref_images.ref_image_{i}"] = [nid, 0]
    # 参考视频：LoadVideo(file) -> GetVideoComponents(video)
    #   输出 [0]=images [1]=audio [2]=fps [3]=bit_depth，只取 images 接 ref_videos.ref_video_K
    #   刻意不接 ref_video_audios：参考片的原声（对白/配乐）会污染哑女镜的音轨
    for k, nm in enumerate(ref_video_names or []):
        vid, comp = str(200 + k * 2), str(201 + k * 2)
        wf[vid] = {"class_type": "LoadVideo", "inputs": {"file": nm}}
        wf[comp] = {"class_type": "GetVideoComponents", "inputs": {"video": [vid, 0]}}
        ref_inputs[f"ref_videos.ref_video_{k}"] = [comp, 0]
    wf["7"] = {"class_type": "MiniMaxH3ReferenceToVideo",
               "inputs": {"clip": ["5", 0], "vae": ["6", 0], "audio_vae": ["14", 0],
                          "prompt": prompt, "width": w, "height": h, "length": length,
                          "ref_image_size": ref_image_size, **ref_inputs}}
    src = ["2", 0]
    if lora_name:
        wf["13"] = {"class_type": "LoraLoaderModelOnly",
                    "inputs": {"model": ["2", 0], "lora_name": lora_name,
                               "strength_model": lora_strength}}
        src = ["13", 0]
    wf["4"] = {"class_type": "MiniMaxLowVRAMAttention",
               "inputs": {"model": src, "head_chunks": 4}}
    wf["16"] = {"class_type": "MiniMaxH3DualClockSamplerT8",
                "inputs": {"model": ["4", 0], "av_latent": ["7", 1], "steps": steps,
                           "shift_video": SHIFT_VIDEO, "shift_audio": 3.0,
                           "sampler_name": "dual_clock_euler", "scheduler": "native_flow"}}
    wf["17"] = {"class_type": "BasicGuider",
                "inputs": {"model": ["16", 0], "conditioning": ["7", 0]}}
    wf["18"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}}
    wf["19"] = {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["18", 0], "guider": ["17", 0], "sampler": ["16", 1],
                           "sigmas": ["16", 2], "latent_image": ["7", 1]}}
    wf["20"] = {"class_type": "MiniMaxH3AVDecodeT8",
                "inputs": {"av_latent": ["19", 0], "video_vae": ["6", 0],
                           "audio_vae": ["14", 0]}}
    cv_inputs = {"images": ["20", 0], "fps": 24.0}
    if with_audio:
        cv_inputs["audio"] = ["20", 1]
    wf["11"] = {"class_type": "CreateVideo", "inputs": cv_inputs}
    wf["12"] = {"class_type": "SaveVideo",
                "inputs": {"video": ["11", 0], "filename_prefix": "h3_i2v",
                           "format": "mp4", "codec": "h264"}}
    return wf


def main():
    global SHIFT_VIDEO      # 由 --shift 覆盖（必须在函数开头声明，下面 argparse 要读它当默认值）
    # ⚠️ 兜底工具，不是出片主通道（2026-09-20 关口化定）：
    #    正式出片一律走  py run.py h3_ref2va_video --project <项目> --set prompt_file=...
    #    差别在于：走引擎才有 args 日志、逐步落盘的 manifest 台账（逐槽锚点指纹/帧数/LoRA/seed）
    #    和批次归档；裸跑出来的片曾经堆在 output\ 里 31 条、参数只活在对话里。
    #    本脚本仍可用（手工单条试验方便），但提交前一样要过跑前自审闸，绕不过去。
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=None)
    ap.add_argument("prompt", nargs="?", default=None)
    ap.add_argument("--prompt-file", dest="prompt_file", default=None)
    ap.add_argument("--last-frame", dest="last_frame", default=None,
                    help="尾帧图片路径（仅 fl2va 首帧模式生效）：把视频最后一帧钉成这张，"
                         "配合首帧实现『两头夹动作』；节点原生支持 last_frame，本脚本以前没接。")
    ap.add_argument("--ref-images", dest="ref_images", default=None,
                    help="逗号分隔的参考图路径；给了就走 ref2va 多图参考模式（无首帧，配合 --prompt-file）")
    ap.add_argument("--ref-videos", dest="ref_videos", default=None,
                    help="逗号分隔的参考视频路径（仅 ref2va 生效，最多 3 个）→ 转 24fps 帧序列当 <Video k>；"
                         "官方口径 2-15s / 48-360 帧，建议与 --len 的时长对齐")
    ap.add_argument("--ref-image-size", dest="ref_image_size",
                    choices=["match", "max"], default="match")
    ap.add_argument("--w", type=int, default=832)
    ap.add_argument("--h", type=int, default=480)
    ap.add_argument("--len", type=int, default=124)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--shift", dest="shift", type=float, default=SHIFT_VIDEO,
                    help="噪声调度平移，默认 12.0。调大＝偏向多给运动（画质有代价），"
                         "调小＝偏向保真/细节。测'动作幅度上限'时用")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--lora", default=None)  # None=按模式取默认(fl2va→turbo8step; ref2va→无)
    ap.add_argument("--lora-strength", dest="lora_strength", type=float, default=1.0)
    ap.add_argument("--no-audio", dest="no_audio", action="store_true")
    ap.add_argument("--sampler", choices=["t8", "native"], default="t8")
    ap.add_argument("--out", default="h3_i2v")
    ap.add_argument("--skip-preflight", dest="skip_preflight", action="store_true",
                    help="跳过跑前自审闸（风险自担；正式出片不该用）")
    ap.add_argument("--theme", default=None, help="仅用于自审日志，标明这是哪一镜")
    a = ap.parse_args()
    SHIFT_VIDEO = a.shift

    # 提示词来源：--prompt-file 优先，其次位置参数
    if a.prompt_file:
        with open(a.prompt_file, "r", encoding="utf-8") as f:
            a.prompt = f.read().strip()
    if not a.prompt:
        print("[run_h3] 缺少提示词（位置参数或 --prompt-file）", flush=True)
        sys.exit(2)

    # ---- 跑前自审：兜底路径也不能免检 ----
    if not a.skip_preflight:
        try:
            sys.path.insert(0, r"D:\AIWorkflow\tools")
            from check_preflight import run_checks, TEN_BLOCKS
        except Exception as e:
            print(f"[run_h3] 自审闸不可用（{type(e).__name__}: {e}）—— 拒绝裸跑；"
                  f"确要继续用 --skip-preflight", flush=True)
            sys.exit(2)
        spec = {"prompt": a.prompt,
                "refs": [x.strip() for x in (a.ref_images or "").split(",") if x.strip()],
                "ref_videos": [x.strip() for x in (a.ref_videos or "").split(",") if x.strip()],
                "w": a.w, "h": a.h, "length": a.len, "lora": a.lora, "seed": a.seed,
                "provider": "local", "blocks": TEN_BLOCKS, "theme": a.theme,
                "only": ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]}
        rep = run_checks(spec)
        for lv, gate, msg in rep.items:
            if lv != "ok":
                print(f"[preflight:{gate}][{lv.upper()}] {msg}", flush=True)
        if rep.errors:
            print(f"[run_h3] 跑前自审未通过（{len(rep.errors)} 条 error），拒绝提交 GPU。"
                  f"改完再跑；应急用 --skip-preflight（风险自担）", flush=True)
            sys.exit(1)

    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 参考图（ref2va 模式）或首帧图（fl2va 模式）
    ref_names = []
    if a.ref_images:
        for p in [x.strip() for x in a.ref_images.split(",") if x.strip()]:
            base = os.path.basename(p)
            stem, ext = os.path.splitext(base)
            nm = f"h3ref_{stem}_{uuid.uuid4().hex[:6]}{ext}"
            shutil.copy2(p, os.path.join(INPUT_DIR, nm))
            ref_names.append(nm)

    # 参考视频（ref2va 专用）：同样复制进 input 目录，由 LoadVideo 读取
    ref_video_names = []
    if a.ref_videos:
        for p in [x.strip() for x in a.ref_videos.split(",") if x.strip()]:
            base = os.path.basename(p)
            stem, ext = os.path.splitext(base)
            nm = f"h3refv_{stem}_{uuid.uuid4().hex[:6]}{ext}"
            shutil.copy2(p, os.path.join(INPUT_DIR, nm))
            ref_video_names.append(nm)

    if not ref_names and not ref_video_names and not a.image:
        print("[run_h3] 需要首帧图（位置参数）或 --ref-images / --ref-videos", flush=True)
        sys.exit(2)

    # LoRA 默认按模式取：ref2va 默认不挂，fl2va 默认挂 turbo8step
    if a.lora is None:
        a.lora = "" if (ref_names or ref_video_names) else DEFAULT_LORA

    if ref_names or ref_video_names:
        wf = build_workflow_ref2va(a.prompt, a.w, a.h, a.len, a.steps, a.seed, ref_names,
                                   lora_name=a.lora, lora_strength=a.lora_strength,
                                   with_audio=not a.no_audio, ref_image_size=a.ref_image_size,
                                   ref_video_names=ref_video_names)
        mode = f"ref2va({len(ref_names)}图+{len(ref_video_names)}视频)"
    else:
        base = os.path.basename(a.image)
        stem, ext = os.path.splitext(base)
        img_name = f"h3_{stem}_{uuid.uuid4().hex[:6]}{ext}"
        shutil.copy2(a.image, os.path.join(INPUT_DIR, img_name))
        last_img_name = None
        if a.last_frame:
            lbase = os.path.basename(a.last_frame)
            lstem, lext = os.path.splitext(lbase)
            last_img_name = f"h3L_{lstem}_{uuid.uuid4().hex[:6]}{lext}"
            shutil.copy2(a.last_frame, os.path.join(INPUT_DIR, last_img_name))
        builder = build_workflow_t8 if a.sampler == "t8" else build_workflow
        wf = builder(a.prompt, a.w, a.h, a.len, a.steps, a.seed, img_name,
                     lora_name=a.lora, lora_strength=a.lora_strength,
                     with_audio=not a.no_audio, last_img_filename=last_img_name)
        mode = f"fl2va/{a.sampler}" + ("+尾帧" if last_img_name else "")
    payload = {"prompt": wf, "client_id": "run_h3"}

    print(f"[run_h3] 提交 {mode}: {a.w}x{a.h} len={a.len} steps={a.steps} seed={a.seed}"
          + (f" lora={a.lora}({a.lora_strength})" if a.lora else "")
          + ("" if a.no_audio else " +audio"), flush=True)
    t0 = time.time()
    resp = http_json("POST", HOST + "/prompt", payload)
    pid = resp.get("prompt_id")
    print(f"[run_h3] prompt_id={pid}", flush=True)

    # 轮询 history
    last = ""
    h = {}
    while True:
        time.sleep(5)
        hist = http_json("GET", HOST + f"/history/{pid}")
        if pid not in hist:
            continue
        h = hist[pid]
        status = h.get("status", {})
        st = status.get("status_str", "")
        if st != last:
            print(f"[run_h3] 状态: {st}", flush=True)
            last = st
        if status.get("completed") or st == "error":
            # outputs 可能比 status 晚写入，重读几次防竞态
            for _ in range(8):
                out = h.get("outputs", {})
                has = any(isinstance(v, dict) and any(v.get(k) for k in ("images", "videos", "gifs"))
                          for v in out.values())
                if has or st == "error":
                    break
                time.sleep(2)
                hist2 = http_json("GET", HOST + f"/history/{pid}")
                if pid in hist2:
                    h = hist2[pid]
            break

    # 找输出视频 (0.30.x VIDEO 类型输出在 'images' 键；'animated' 是标志位)
    outputs = h.get("outputs", {})
    for key in ("images", "animated", "videos", "gifs"):
        for nid, out in outputs.items():
            items = out.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                fn = item.get("filename")
                if not fn:
                    continue
                src = os.path.join(OUTPUT_DIR, fn)
                if os.path.exists(src) and fn.lower().endswith((".mp4", ".webm", ".mov", ".gif", ".webp")):
                    dst = os.path.join(OUTPUT_DIR, a.out + os.path.splitext(fn)[1])
                    shutil.copy2(src, dst)
                    print(f"[run_h3] 完成: {dst}  耗时 {time.time()-t0:.0f}s", flush=True)
                    return
    # 输出图片兜底 (无视频时)
    for nid, out in outputs.items():
        items = out.get("images", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            fn = item.get("filename")
            src = os.path.join(OUTPUT_DIR, fn) if fn else None
            if src and os.path.exists(src):
                print(f"[run_h3] 输出图片: {src}  耗时 {time.time()-t0:.0f}s", flush=True)
                return
    # 最终兜底：找本次运行(t0 之后)新生成的 mp4（防 history outputs 时序竞态）
    try:
        cands = []
        for f in os.listdir(OUTPUT_DIR):
            if f.lower().endswith((".mp4", ".webm")):
                fp = os.path.join(OUTPUT_DIR, f)
                if os.path.getmtime(fp) >= t0 - 5:
                    cands.append(fp)
        if cands:
            src = max(cands, key=os.path.getmtime)
            dst = os.path.join(OUTPUT_DIR, a.out + os.path.splitext(src)[1])
            shutil.copy2(src, dst)
            print(f"[run_h3] 完成(兜底): {dst}  耗时 {time.time()-t0:.0f}s", flush=True)
            return
    except Exception as e:
        print(f"[run_h3] 兜底扫描失败: {e}", flush=True)
    print(f"[run_h3] 无输出. history keys={list(outputs.keys())}", flush=True)


if __name__ == "__main__":
    main()
