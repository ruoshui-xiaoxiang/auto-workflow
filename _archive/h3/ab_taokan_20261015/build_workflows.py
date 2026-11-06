# -*- coding: utf-8 -*-
"""EP1v2 s7->s8 段间引导 A/B: 搭两张 API 工作流
A) ab_s7_parent_accept.json  链内重生成 s7 -> CandidateSave -> Accept (父片)
B) ab_s8_cont.json           EXPT8 Continuation 出 s8 续段 (context 22)

⚠ 2026-10-15 跑通后本脚本已停止同步: 盘上 JSON 才是事实源(手改过——
   采样器 euler、删 LowVRAM 节点、链名 ab_taokan_h768、画布 768x448、
   clip device=cpu、Source 接新父片)。直接重跑本脚本会用旧常量
   (dual_clock_euler / h448 / 736 画布 / clip default) 重新生成过时
   JSON 并覆盖, 勿跑。跑通配置与结果见提案 §8.4。
"""
import json
import urllib.request
from pathlib import Path

HOST = "http://127.0.0.1:8189"
HERE = Path(__file__).parent
T8 = Path(r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/custom_nodes/comfyui-minimax-h3-audio-T8")
FIXTURE = T8 / "tests/fixtures/api/long_video_candidate_accept_api.json"
EXAMPLE = T8 / "examples/workflows/45-progressive-continuation-split/Continuation_S11_Context22_plain_both_Full_Save_EXP.json"
P7 = Path(r"E:/创作/武昭君仪/单元剧_轻喜版/shots_v2/ep1v2_s7_prompt.txt")
P8 = Path(r"E:/创作/武昭君仪/单元剧_轻喜版/shots_v2/ep1v2_s8_prompt.txt")

UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VVID = "minimax_h3_video_vae_fp16.safetensors"
VAUD = "minimax_h3_audio_vae_fp32.safetensors"
KF = "kf_junyi_costume.png"
CHAIN = "ab_taokan_h448"
CONTRACT = "fdb12aed619aa187ba462d143226195f7398599964765be02f334ee2bd7d6616"
MODEL_ID = "minimax_h3_fl2va_pruned_int8_convrot+turbo8step_v1.0|steps8|dual_clock_euler|native_flow|shift12/3"

S7_PROMPT = P7.read_text(encoding="utf-8").rstrip("\n")
S8_PROMPT = P8.read_text(encoding="utf-8").rstrip("\n")

CONTROL = {"fixed", "increment", "decrement", "randomize"}


def fetch_object_info():
    cache = HERE / "object_info.json"
    with urllib.request.urlopen(HOST + "/object_info", timeout=30) as r:
        data = json.loads(r.read())
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def is_widget(name, spec):
    typ = spec[0]
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if opts.get("forceInput"):
        return False
    if isinstance(typ, str):
        return typ in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO") or typ.startswith("COMFY_DYNAMICCOMBO")
    if isinstance(typ, list):
        return True  # COMBO
    return False


def frontend_to_api(g, obj):
    """ComfyUI graphToPrompt 约定: widgets_values 按 object_info 声明序
    (required 在前 optional 在后) 覆盖全部 widget 型输入(含已转 link 的);
    有 link 的输入用 link 覆盖 widget 值; seed INT 后可能跟 control 串。"""
    links = {lk[0]: lk for lk in g["links"]}
    api = {}
    dropped = []
    for n in g["nodes"]:
        ct = n["type"]
        if ct not in obj:
            dropped.append((n["id"], ct))
            continue
        spec = obj[ct]
        # frontend linked inputs by name
        flink = {}
        for inp in n.get("inputs", []):
            lid = inp.get("link")
            if lid is not None:
                lk = links[lid]
                flink[inp["name"]] = [str(lk[1]), lk[2]]
        inputs = {}
        wv = list(n.get("widgets_values") or [])
        wi = 0
        missing = []
        for section in ("required", "optional"):
            for name, isp in (spec.get("input", {}).get(section) or {}).items():
                if is_widget(name, isp):
                    if wi >= len(wv):
                        missing.append(name)
                        break
                    val = wv[wi]; wi += 1
                    typ = isp[0]
                    if (isinstance(typ, str) and typ == "INT"
                            and "seed" in name and wi < len(wv)
                            and isinstance(wv[wi], str) and wv[wi] in CONTROL):
                        wi += 1  # 前端 control_after_generate, 非 API 输入
                    if name in flink:
                        val = flink[name]
                    inputs[name] = val
                else:
                    if name in flink:
                        inputs[name] = flink[name]
                    # 非 widget 且无 link: 可选未用 -> 略过; 必填由 /prompt 校验兜底
        api[str(n["id"])] = {"class_type": ct, "inputs": inputs}
        leftover = wv[wi:]
        if missing or leftover:
            print(f"  [warn] node {n['id']} {ct}: missing={missing} leftover={leftover}")
    return api, dropped


def build_parent():
    g = json.loads(FIXTURE.read_text(encoding="utf-8"))
    w = {k: v for k, v in g.items()}
    # 1-4 loaders
    w["1"]["inputs"]["vae_name"] = VVID
    w["2"]["inputs"]["vae_name"] = VAUD
    w["3"]["inputs"].update(clip_name=CLIP, type="minimax", device="default")
    w["4"]["inputs"]["unet_name"] = UNET
    # 5: bypass -> real LoRA (生产标准 turbo8step)
    w["5"] = {"class_type": "LoraLoaderModelOnly",
              "inputs": {"model": ["4", 0], "lora_name": LORA, "strength_model": 1.0}}
    # 18: 生产同款 LowVRAM attention; 19: KF 首帧
    w["18"] = {"class_type": "MiniMaxLowVRAMAttention",
               "inputs": {"model": ["5", 0], "head_chunks": 4}}
    w["19"] = {"class_type": "LoadImage", "inputs": {"image": KF}}
    # 6 planner
    p = w["6"]["inputs"]
    p["chain_id"] = CHAIN
    p["segment_index"] = 0
    p["new_duration_seconds"] = 6.0
    p["context_frames"] = 22
    p["minimum_render_frames"] = 124
    p["timeline_start_seconds"] = -1.0
    p["is_final_segment"] = False
    # 8 conditioning: 生产同参 + KF first_frame + s7 原稿
    c = w["8"]["inputs"]
    c["model"] = ["18", 0]
    c["first_frame"] = ["19", 0]
    c["prompt"] = S7_PROMPT
    c["width"], c["height"] = 736, 448
    c["task_type"] = "auto"
    c["audio_mode"] = "native"
    c["audio_denoise_strength"] = 0.35
    c["add_source_as_reference"] = False
    c["prompt_primary_audio_ordinal"] = 0
    c["strict_prompt_tags"] = True
    c["ref_image_size"] = "match"
    c["reference_video_policy"] = "official_2_to_15s"
    # 9 sampler: 8 步 + dual_clock_euler (生产)
    s = w["9"]["inputs"]
    s["steps"] = 8
    s["shift_video"], s["shift_audio"] = 12.0, 3.0
    s["sampler_name"] = "dual_clock_euler"
    s["scheduler"] = "native_flow"
    # 15 candidate save
    cs = w["15"]["inputs"]
    cs["model_id"] = MODEL_ID
    cs["sampling_summary"] = CONTRACT  # 64hex == EXPT8 previous_job_sha256
    cs["candidate_id"] = ""
    cs["bit_depth"], cs["crf"] = 8, 18
    # 16 accept = true
    w["16"]["inputs"]["accept_candidate"] = True
    # 17 seed
    w["17"]["inputs"]["value"] = 20282107
    return w


def build_continuation(obj, parent_candidate_id, parent_revision):
    g = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    w, dropped = frontend_to_api(g, obj)
    print("  dropped frontend-only nodes:", dropped)
    # loaders
    w["1"]["inputs"]["unet_name"] = UNET
    w["10"]["inputs"]["unet_name"] = UNET
    w["2"]["inputs"].update(clip_name=CLIP, type="minimax", device="default")
    w["3"]["inputs"]["vae_name"] = VVID
    w["4"]["inputs"]["vae_name"] = VAUD
    # 模型链: UNET -> LoRA -> LowVRAM -> DualClock (生产同构)
    w["101"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["1", 0], "lora_name": LORA, "strength_model": 1.0}}
    w["102"] = {"class_type": "MiniMaxLowVRAMAttention",
                "inputs": {"model": ["101", 0], "head_chunks": 4}}
    w["103"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["10", 0], "lora_name": LORA, "strength_model": 1.0}}
    w["104"] = {"class_type": "MiniMaxLowVRAMAttention",
                "inputs": {"model": ["103", 0], "head_chunks": 4}}
    w["15"]["inputs"]["model"] = ["102", 0]
    w["16"]["inputs"]["model"] = ["104", 0]
    # 采样参数: 生产 dual_clock_euler (示例里是 euler)
    for k in ("15", "16"):
        w[k]["inputs"].update(steps=8, shift_video=12.0, shift_audio=3.0,
                              sampler_name="dual_clock_euler", scheduler="native_flow")
    # KF 首帧(身份参考) + 两阶段同稿 s8 原稿 + length 166 = 144新 + 22ctx
    w["105"] = {"class_type": "LoadImage", "inputs": {"image": KF}}
    for k, phase in (("5", "low"), ("12", "high")):
        c = w[k]["inputs"]
        assert c.get("phase") == phase, (k, c.get("phase"))
        c["prompt"] = S8_PROMPT
        c["length"] = 166
        c["first_frame"] = ["105", 0]
        c["first_frame_reuse"] = "persistent_identity_reference"
        c["strict_prompt_tags"] = True
    w["14"]["inputs"]["length"] = 166   # 空 latent 脚手架
    w["17"]["inputs"].update(length=166, low_evaluations=4, low_scale=0.5)
    # seeds = 生产 s8 seed
    w["6"]["inputs"]["noise_seed"] = 20282108
    w["13"]["inputs"]["noise_seed"] = 20282108
    w["21"]["inputs"]["seed"] = 20282108
    # Source: 已接受父片
    src = w["23"]["inputs"]
    src.update(chain_id=CHAIN, segment_index=1,
               parent_candidate_id=parent_candidate_id,
               parent_revision=parent_revision,
               previous_job_sha256=CONTRACT, context_frames=22,
               width=736, height=448, low_width=384, low_height=224)
    # 输出前缀 (SaveVideo 只留 API 确认的四个输入)
    sv = w["9"]["inputs"]
    w["9"]["inputs"] = {"video": sv["video"], "filename_prefix": "AB_taokan_s8_cont",
                        "format": "mp4", "codec": "h264"}
    w["25"]["inputs"]["filename_prefix"] = "AB_taokan/LOW"
    w["26"]["inputs"]["filename_prefix"] = "AB_taokan/HIGH"
    return w


def main():
    obj = fetch_object_info()
    for need in ("MiniMaxH3LongVideoConditioningT8", "MiniMaxH3ContinuationSourceEXPT8",
                 "MiniMaxH3ContinuationConditioningEXPT8", "MiniMaxLowVRAMAttention",
                 "LoraLoaderModelOnly", "LoadImage", "PreviewAny"):
        assert need in obj, f"missing node class {need}"
    print("object_info ok, classes:", len(obj))

    parent = build_parent()
    (HERE / "ab_s7_parent_accept.json").write_text(
        json.dumps(parent, ensure_ascii=False, indent=1), encoding="utf-8")
    print("parent nodes:", len(parent))

    cont = build_continuation(obj, "PARENT_TBD", 1)
    (HERE / "ab_s8_cont.json").write_text(
        json.dumps(cont, ensure_ascii=False, indent=1), encoding="utf-8")
    print("continuation nodes:", len(cont))

    # 抽查关键节点
    for tag, wf, ids in (("PARENT", parent, ("5", "8", "9", "15", "16", "17")),
                         ("CONT", cont, ("5", "12", "14", "15", "16", "17", "23", "6", "13", "21"))):
        for i in ids:
            ins = wf[i]["inputs"]
            brief = {k: (v if not isinstance(v, str) or len(v) < 40 else v[:37] + "...")
                     for k, v in ins.items()}
            print(f"[{tag}#{i}] {wf[i]['class_type']}")
            print("   ", json.dumps(brief, ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
