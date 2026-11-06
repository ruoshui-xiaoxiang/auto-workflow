# -*- coding: utf-8 -*-
"""说话出片 —— 自然语言出图/出片本地 UI

用法:
  python server.py            # 127.0.0.1:8790
  python server.py --port 8790

只做「自然语言 + 参考图 → 调引擎 run.py」，不绕过 preflight / 人工关口。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT.parent
WORKFLOWS = ENGINE / "workflows"
NL_DIR = ENGINE / "tmp" / "nl_ui"
UPLOAD = NL_DIR / "uploads"
LOGS = NL_DIR / "logs"
HTML = ROOT / "index.html"

for d in (NL_DIR, UPLOAD, LOGS):
    d.mkdir(parents=True, exist_ok=True)

PY = r"C:\Users\若水\AppData\Local\Programs\Python\Python312\python.exe"
if not Path(PY).exists():
    PY = sys.executable

H3_TEMPLATE = """For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, 16:9. {body}

overall_soundscape: {soundscape}

non_diegetic_music: N/A
"""

DEFAULT_SOUNDSCAPE = (
    "Quiet ambient room tone with soft natural background. "
    "Subtle physical foley matching on-screen action. No spoken dialogue unless written as (Sx) lines."
)

# 出片三种模式（10-14 他指定：娱乐通道直接选模式＋档位＋预置画幅，不给精细微调）
#   first      ＝ fl2va 锁首帧：1 张图当 first_frame（几何锚，锁机位与构图）
#   first_last ＝ fl2va 两头夹：2 张图（首帧＋尾帧），两端钉住、中间由模型自己走
#   refs       ＝ ref2va 多参考图：4 张图（身份/第二主体/场景道具/画风），锁身份不锁机位
# 每个模式下面挂它自己能跑的档位（档位＝工作流 + 少量覆盖参数；LoRA 与步数**成对**给，
# 引擎里本来就有 "4step LoRA 只能配 4 步" 的硬校验，所以绝不让 UI 单独调步数）。
LORA8 = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
LORA4 = "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"

VIDEO_MODES = {
    "first": {
        "slots": 1, "kind": "i2va",
        "tiers": {
            "std8":    {"workflow": "h3_i2va_video", "label": "标准 · 8 步 turbo@0.7",
                        "note": "默认档。降强度是治 identity drift 的方向。竖屏 5.2s 约 8–9 分钟。"},
            "draft4":  {"workflow": "h3_i2va_video", "label": "草稿 · 4 步 turbo",
                        "sets": {"steps": "4", "lora": LORA4, "lora_strength": "1.0"},
                        "note": "最快，但 4 步版画质你 09-13 判过弃用——只配看构图与走位。"},
            "fight8":  {"workflow": "h3_fl2va_fight_play", "label": "打斗 · 8 步 + 武器内容 LoRA",
                        "note": "双 LoRA 模板（turbo@1.0 + Bunny_weapon@0.5）。只锁首帧，不支持尾帧。"},
            "clean20": {"workflow": "h3_fl2va_clean_play", "label": "精细 · 20 步不挂 LoRA",
                        "note": "identity drift 最轻的一档，代价是慢约 2.5 倍（10–15 分钟）。"},
        },
    },
    "first_last": {
        "slots": 2, "kind": "i2va",
        "tiers": {
            "std8":    {"workflow": "h3_fl2va_dual_play", "label": "标准 · 8 步 turbo@0.7",
                        "note": "两头夹只钉两端，中间路径仍是抽签——同参多跑两条挑一条。"},
            "draft4":  {"workflow": "h3_fl2va_dual_play", "label": "草稿 · 4 步 turbo",
                        "sets": {"steps": "4", "lora": LORA4, "lora_strength": "1.0"},
                        "note": "最快，用来验证首尾帧两张图配得对不对。"},
            "clean20": {"workflow": "h3_fl2va_dual_clean_play", "label": "精细 · 20 步不挂 LoRA",
                        "note": "漂移最轻、最慢。"},
        },
    },
    "refs": {
        "slots": 4, "kind": "ref2va",
        "tiers": {
            "refstd":  {"workflow": "h3_ref2va_play", "label": "标准 · 4 步 ref2v（配对）",
                        "note": "ref2va 只有 4-step 版 LoRA，与步数严格配对，没有别的档。"
                               "锁身份但**不锁机位**（模板无 first_frame）。"},
        },
    },
}
MODE_ALIAS = {"fl2va": "first", "i2va": "first", "ref2va": "refs", "first_frame": "first"}
MODE_LABELS = {"first": "锁首帧", "first_last": "锁首尾帧", "refs": "多参考图（四图）"}

# 娱乐流归档独立命名空间：产物落 资源池\娱乐流\批次\<run_id>\，
# 不跟 agent 正式出片（无音 / 武昭君仪 …）混在同一个批次池里。
PLAY_PROJECT = "娱乐流"
PLAY_OUTPUT_ROOT = "E:\\图像影音资源池\\娱乐流\\批次"


def tier_of(mode: str, tier: str) -> dict:
    """取档位；tier 缺省或非法 → 该模式的第一档（标准档）。"""
    tiers = VIDEO_MODES[mode]["tiers"]
    return tiers.get(str(tier or "").strip(), next(iter(tiers.values())))


# 出片三种模式（10-14 他指定：娱乐通道直接选模式＋预置画幅，不给精细微调）
# 定义已上移到本文件常量区（VIDEO_MODES 带 tiers），这里只留通道归一化。


def norm_mode(v) -> str:
    s = str(v or "first").strip().lower()
    return VIDEO_MODES.get(s) and s or MODE_ALIAS.get(s, "")


# 画幅预置：全部是 32 的倍数（H3 硬要求）。9:16 / 16:9 才不被 G5 warn；
# native 是 H3 设计尺寸 1344×768＝7:4，G5 会 warn，留给他自己权衡。
RATIOS = {
    "v916":   (864, 1536),   # 竖屏真 9:16，推荐
    "v916s":  (576, 1024),   # 竖屏 9:16 省卡档（最快）
    "h169":   (1536, 864),   # 横屏真 16:9
    "h169s":  (1024, 576),   # 横屏 16:9 省卡档
    "native": (1344, 768),   # H3 原生画布 7:4（G5 warn）
}
# 时长预置：帧数必须落在 17n+5 网格，合法区间 124–362（@24fps）
LENGTHS = {
    "5.2":  (124, 5.1667),
    "8.0":  (192, 8.0),
    "10.1": (243, 10.125),
    "15.1": (362, 15.0833),
}
# 竖屏长镜在这台 16GB/32GB 上有换页悬崖（226 帧竖屏曾测到 13.1 s/帧），提醒但不拦
LONG_VERTICAL_WARN = {"v916": {"10.1", "15.1"}, "v916s": {"15.1"}}

# ref2va 模式的槽位数（模板 comfy/h3_i2v_ref2va_api.json 带 __REF1..4__）
REF2VA_SLOTS = 4

SKELETON_INSTRUCTION = (
    "For the target video, at 0.00 seconds into the target video, "
    "<Picture 1> (from [Shot 1]) is fully referenced."
)
REF2VA_FIELDS = ("subject_definitions:", "summary:", "retention_analysis:",
                 "detailed_description:", "overall_soundscape:", "non_diegetic_music:")

# H3 禁词（只警告，不拦；拦在 G7）
BANNED = re.compile(
    r"\b(NO|NOT|Never|don't|do not|avoid|禁止|不许|不要|避免|dolly|tripod|crane|steadicam)\b",
    re.I,
)

CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
DIALOGUE = re.compile(r"<d>.*?</d>", re.S)
GEAR = re.compile(
    r"\b(dolly|tripod|crane|steadicam|gimbal|slider|rig|dron[e|c]|handheld rig)\b|摄影机|摄像机|三脚架|无人机",
    re.I,
)
KEYISH = re.compile(r"sk-[A-Za-z0-9.\-_]{6,}")

COMMON_RULES = """硬性规则（违反任何一条，本地 H3 的格式闸 G7 会把这次提交直接拦下）：
1) 只输出提示词本身：不要 markdown 代码块、不要解释、不要任何前后缀。
2) **输出里除了 <d>…</d> 内的台词，一个中文字符都不许出现**（包括夹在英文词里的字，如 "matte青-gray" 必须写成 "matte blue-grey"）。英文双引号只用于画面里可见的文字（招牌、书信），不要用引号包台词。
3) 台词逐字放 <d>[中文]原文</d> 内（保留原语言、不翻译），说话人编号 (S1)(S2) 写在 <d> 外。
4) 纯正向描述。禁止禁令句（no / not / never / don't / avoid / 不要 / 禁止 —— H3 实测禁令无效），也禁止写"这是一段视频/用于生成/模型应当"这类元叙述。
5) 禁止摄影器材名词（tripod / dolly / gimbal / crane / steadicam / slider / rig / 摄影机），运镜一律写成自然英文动词（Push In / Pan Left / Track Right / Zoom Out / Hold Static）。
6) 主体必须具体，但**具体只能来自你确实知道的东西**：用户写了的、或看图清单里有的。
   两者都没有时，一律回指参考图（the woman in <Picture 1>, same hairstyle, same robe and colours），
   **绝不许发明**服装款式、配色、家具、地面、窗、光源、背景物件——编出来的细节就是"动起来换人"的拉力来源。
"""

SYSTEM_I2VA = (
    "你是 H3 I2VA（首帧视频）提示词合规改写器。把用户的中文描述改写为 H3 官方骨架英文。\n"
    + COMMON_RULES
    + """7) 输出结构逐字如下：第一行一字不改地写
   For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
   空一行，然后恰好三个字段、按此序、字段名逐字一致、字段之间空一行：
   integrated_multimodal_description: → overall_soundscape: → non_diegetic_music:
   正文接在字段名同一行后面（首帧骨架是行内式）。
8) integrated_multimodal_description: 正文以 [Shot 1] 开头；先写画面风格与实拍质感，再写人物外貌/服装/构图/场景，再沿时间线写动作与状态变化。
9) <Picture 1> 就是首帧本身：人物外貌、站位、景别、色温必须与首帧一致，不得凭空改场景（用户没写室内就不要写室内）。
10) 多拍内容按 [Shot N] 分段，并在句首给 At MM:SS.mmm 切点；只有一拍就只写 [Shot 1]。
11) overall_soundscape 用 1-4 句英文写环境声与动作声（H3 原生出声，这块不能省）；non_diegetic_music 写配器/速度/节奏，无配乐就写 N/A。
12) 不要引用第二个 Picture 槽（首帧通道只有一张图进模型）。
"""
)

SYSTEM_REF2VA = (
    "你是 H3 Ref2VA（四图全参考）提示词合规改写器。把用户的中文描述改写为 H3 官方全参考六段英文。\n"
    + COMMON_RULES
    + """7) 输出恰好六段、按此序、字段名逐字一致、段与段之间空一行，且**字段名单独占一行、内容从下一行开始**：
   subject_definitions: → summary: → retention_analysis: → detailed_description: → overall_soundscape: → non_diegetic_music:
8) **不得**出现 "For the target video, at 0.00 seconds…" 这句骨架首行指令，也**不得**出现 integrated_multimodal_description:（ref2va 与首帧骨架互斥，混进即拦）。
9) subject_definitions: 每个受跟踪对象单独一行，写法如
   <Subject 1> is the young woman in <Picture 1>, with short hair tied at the nape, a moon-white ruqun and a blue-grey sash.
   四张图的默认职责分工：Picture 1＝主角身份与造型；Picture 2＝第二主体或第二视角；Picture 3＝场景或道具；Picture 4＝画风与光影——这一条必须用英文写死
   "only its photographic texture and lighting are adopted; its people, faces, clothing, composition and background are not adopted"（这句别翻回中文）。
   若用户另说明了职责，以用户为准；编号必须与用户给的图序一致，不得跳号。
10) summary: 一行概述整片发生什么，用 <Subject N> 指代。
11) retention_analysis: 每个标签单独一行，写法如
    <Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - the hairstyle, face, robe colour and sash are retained.
    标记只用 fully_preserved / partially_preserved / transferred / reused，且不得在此段写 (Sx)。
12) detailed_description: 按播放顺序写，用 [Shot N] 起段，切点写 At MM:SS.mmm；正常 350-500 个英文词；每次发声处复用同一个 (Sx)。
13) overall_soundscape 1-3 句英文写环境声与动作声；non_diegetic_music 写配器/速度/动态，无配乐写 N/A。这两段里不要重复台词。
"""
)

# 一次定点修补：只在首稿残留非英文字符时用（G7 对中文是二值判定，不修就整稿被拦）
SYSTEM_REPAIR = (
    "你是提示词修补器。用户给你一份 H3 英文提示词，里面残留了少量非英文字符。"
    "你的唯一任务：把 <d>…</d> 之外残留的非英文字符改成对应英文"
    "（夹在英文词里的中文按语义翻成英文，如 matte青-gray → matte blue-grey）；"
    "把用引号包起来的台词改成 <d>[中文]原文</d> 形式，台词文字本身一字不改。"
    "其余内容、字段名、顺序、行数一律原样保留。只输出修改后的完整提示词，不要解释、不要代码块。"
)

STATE_LOCK = threading.Lock()
STATE = {
    "running": False,
    "run_id": None,
    "workflow": None,
    "mode": None,
    "log": [],
    "result_dirs": [],
    "files": [],
    "exit_code": None,
    "error": None,
    "warnings": [],
}


def _log(line: str) -> None:
    with STATE_LOCK:
        STATE["log"].append(line)
        if len(STATE["log"]) > 800:
            STATE["log"] = STATE["log"][-500:]


def sanitize_h3_body(nl: str) -> tuple[str, list[str]]:
    warns = []
    text = (nl or "").strip()
    if not text:
        return "", ["需求为空"]
    for m in BANNED.finditer(text):
        warns.append(f"含 H3 敏感/禁用词「{m.group(0)}」— G7 可能拦，建议改成正向描述")
    # 不要在这里强行改写用户语义，只做基础收束
    body = text.replace("\n", " ").strip()
    if not body.endswith("."):
        body += "."
    return body, warns


def build_h3_prompt(nl: str) -> tuple[str, list[str]]:
    body, warns = sanitize_h3_body(nl)
    soundscape = DEFAULT_SOUNDSCAPE
    # 用户若在需求里写了 soundscape: ... 则拆出
    if "soundscape:" in body.lower():
        warns.append("需求里出现 soundscape 字样，请确认台词不要写进 soundscape")
    return H3_TEMPLATE.format(body=body, soundscape=soundscape), warns


# ---------------------------------------------------------------- 提示词翻译填充器
def redact(s: str) -> str:
    """任何返回给前端/写日志的文本先剥掉疑似 API Key（凭证连片段都不许回显）。"""
    return KEYISH.sub("sk-***", s or "")


def looks_like_i2va(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith(SKELETON_INSTRUCTION) and "integrated_multimodal_description:" in t


def looks_like_ref2va(text: str) -> bool:
    t = text or ""
    if any(f not in t for f in REF2VA_FIELDS):
        return False
    idx = [t.index(f) for f in REF2VA_FIELDS]
    return idx == sorted(idx)


def cjk_residue(text: str) -> str:
    """<d>…</d> 之外残留的非英文字符（G7 对这条是二值判定，一个字符就拦整稿）。"""
    m = CJK.search(DIALOGUE.sub("", text or ""))
    return m.group(0) if m else ""


def check_draft(text: str, kind: str = "i2va") -> list[str]:
    """出片前本地自查（只报不拦，真判据仍是引擎的 G 闸）。kind ∈ {i2va, ref2va}"""
    warns: list[str] = []
    t = text or ""
    if not t.strip():
        return ["提示词为空"]
    if kind == "ref2va":
        if not looks_like_ref2va(t):
            warns.append("ref2va 通道需要官方英文六段稿（subject_definitions → … → non_diegetic_music）——"
                         "点「中文 → 英文合规稿并填入」生成后再跑")
        if SKELETON_INSTRUCTION in t or "integrated_multimodal_description:" in t:
            warns.append("六段里混进了首帧骨架的首行/字段（G7 判互斥，会 error）")
        if not re.search(r"<(Picture|Video|Audio|Subject)\s*\d+>", t):
            warns.append("六段里没有任何 <Picture N> / <Subject N> 引用 —— 挂了图等于没挂")
    else:
        if not looks_like_i2va(t):
            warns.append("首帧通道需要官方骨架稿（逐字首行 + 三字段）——"
                         "点「中文 → 英文合规稿并填入」生成后再跑")
    bad = cjk_residue(t)
    if bad:
        warns.append(f"正文残留非英文字符「{bad}」—— G7 会判非英文直接拦（<d> 台词除外）")
    hits = sorted({m.group(0) for m in GEAR.finditer(t)})
    if hits:
        warns.append("含运镜器材名词 " + "、".join(hits) + " —— 改成自然英文动词")
    return warns


# 看图登记员：只抄"图里客观有什么"，**不判质量**（判分那条他早就否过：VL 看不出构图与戏）
VL_SYSTEM = (
    "你是画面素材登记员，任务是把参考图里客观存在的内容逐行登记，供后面写提示词时与画面保持一致。"
    "硬性要求：只写看得见的，不补写图里没有的；不评价质量、美感、可用性；不改性别与年龄；"
    "颜色一律写成具体颜色词（如 moon-white、blue-grey、silver）。"
    "每张图一行，格式：图N: 性别与年龄段｜发型与发色｜五官形制（脸型/眉形/眼形/鼻/唇）｜"
    "服装形制与逐项配色｜姿态与手部位置｜景别与机位高度｜光线方向与色温｜背景里看得见的物件。"
    "只输出这些行，不要前言后语、不要编号以外的说明。"
)


def vl_look(paths: list[str], model: str = "") -> tuple[str, str]:
    """云端 VL 抄参考图外观清单。返回 (清单文本, 备注)。失败不抛异常，只回备注。

    模型名实测（2026-10-14）：这把按量 key 的目录里**没有 qwen-vl-plus**（404 model_not_found），
    有的是 qwen3-vl-plus；所以默认走后者，要换用 AW_VL_MODEL 环境变量覆盖。
    """
    model = model or os.environ.get("AW_VL_MODEL") or "qwen3-vl-plus"
    paths = [p for p in (paths or []) if p][:4]
    if not paths:
        return "", "没有参考图，跳过看图"
    _ensure_llm_keys()
    key = os.environ.get("AW_DASHSCOPE_API_KEY", "")
    if not key:
        return "", "没拿到 DashScope key，跳过看图"
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        import yaml
        import tasks
        cfg = yaml.safe_load((ENGINE / "config.yaml").read_text(encoding="utf-8"))
        base = str(cfg["models"]["dashscope"]["base_url"]).rstrip("/")
    except Exception as e:  # noqa: BLE001
        return "", f"看图后端配置读取失败，跳过：{type(e).__name__}"
    content: list[dict] = [{"type": "text", "text": VL_SYSTEM}]
    for i, p in enumerate(paths, 1):
        try:
            raw = Path(p).read_bytes()
        except OSError:
            continue
        mime = "image/png" if Path(p).suffix.lower() == ".png" else "image/jpeg"
        try:  # 有 PIL 就压到 768 长边省 token，没有就发原图
            import io
            from PIL import Image
            buf = io.BytesIO()
            im = Image.open(io.BytesIO(raw)); im.thumbnail((768, 768))
            im.convert("RGB").save(buf, "JPEG", quality=88)
            raw, mime = buf.getvalue(), "image/jpeg"
        except Exception:  # noqa: BLE001
            pass
        content.append({"type": "text", "text": f"图{i}"})
        content.append({"type": "image_url",
                        "image_url": {"url": "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode())}})
    content.append({"type": "text", "text": "现在按格式逐行登记上面这些图。"})
    try:
        r = tasks.SESSION.post(base + "/v1/chat/completions",
                               json={"model": model, "messages": [{"role": "user", "content": content}],
                                     "max_tokens": 900, "temperature": 0.1},
                               timeout=120,
                               headers={"Authorization": "Bearer " + key})
    except Exception as e:  # noqa: BLE001
        return "", f"看图调用异常，跳过：{type(e).__name__}"
    if r.status_code != 200:
        return "", f"看图 HTTP {r.status_code}，跳过"
    try:
        text = redact(r.json()["choices"][0]["message"]["content"].strip())
    except Exception:  # noqa: BLE001
        return "", "看图返回解析失败，跳过"
    return text, f"{model} 已读 {len(paths)} 张图"


def llm_translate(text: str, mode: str, n_refs: int, look: str = "") -> dict:
    """中文 → 该模式的官方英文稿。复用引擎的 tasks.t_llm 与 config.yaml 后端，
    不另起一套 LLM 逻辑（避免双真源）。只返回文本，不落 prompt_file、不提交 GPU。"""
    _ensure_llm_keys()
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    import yaml  # 局部导入：翻译是低频动作，不拖慢 UI 启动
    import tasks

    cfg = yaml.safe_load((ENGINE / "config.yaml").read_text(encoding="utf-8"))
    sink: list[str] = []
    ctx = {
        "cfg": cfg, "args": {}, "run_id": "nl_ui_translate", "log": sink.append,
        "outputs": {}, "wf_root": ENGINE, "workflow": "speak-ui",
        "step_id": "translate", "explicit_args": set(),
    }
    kind = VIDEO_MODES[mode]["kind"]
    if kind == "ref2va":
        system = SYSTEM_REF2VA
        head = (f"参考图共 {n_refs} 张，提交顺序即 <Picture 1>.. 的编号；"
                f"请按上面说的四图职责分工来写。\n\n")
    elif mode == "first_last":
        system = SYSTEM_I2VA
        head = "首帧＝第 1 张参考图、尾帧＝第 2 张（两头夹：两端钉死，中间由模型自己走）。\n\n"
    else:
        system = SYSTEM_I2VA
        head = ("首帧＝第 1 张参考图（它是画面里人物/构图/光线的唯一事实源，"
                "正文不得凭空改场景）。\n\n")
    if look:
        # 看图清单是"与画面同向"的依据：正文里出现的每个具体特征都该能在图里找到
        head += ("【参考图客观登记（看图模型抄出，正文描述必须与它一致、不得与之矛盾）】\n"
                 + look + "\n\n")
    head += "【用户的中文需求】\n"
    def ask(sys_prompt: str, user_msg: str, temperature: float = 0.3) -> dict:
        return tasks.t_llm(
            {"backend": "dashscope", "system": sys_prompt, "prompt": user_msg,
             "max_tokens": 2000, "temperature": temperature, "timeout": 120},
            ctx,
        )

    out = ask(system, head + text)
    drafted = redact(str(out.get("text") or "").strip())
    repaired = ""
    if drafted and cjk_residue(drafted):
        # 首稿残留中文 → 一次定点修补（不修就整稿被 G7 拦，白点一次）
        try:
            cand = redact(str(ask(SYSTEM_REPAIR, drafted, temperature=0.1).get("text") or "").strip())
        except Exception:  # noqa: BLE001
            cand = ""
        if cand and not cjk_residue(cand) and len(cand) > len(drafted) * 0.6:
            repaired = "首稿残留非英文字符，已用同一后端定点补修一次"
            drafted = cand
    return {
        "prompt": drafted,
        "backend": out.get("backend"),
        "elapsed": out.get("elapsed"),
        "repaired": repaired,
        "engine_log": [redact(x) for x in sink][-6:],
    }


def copy_refs(files: list[dict]) -> list[str]:
    """保存上传的参考图，返回绝对路径列表。"""
    out = []
    for f in files:
        name = Path(f.get("name") or "ref.png").name
        data = f.get("data_b64") or ""
        if not data:
            continue
        import base64

        dest = UPLOAD / f"{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}_{name}"
        dest.write_bytes(base64.b64decode(data))
        out.append(str(dest))
    return out


def parse_sets(items: list[str]) -> list[str]:
    args = []
    for kv in items or []:
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        args.extend(["--set", f"{k.strip()}={v.strip()}"])
    return args


def _ensure_llm_keys() -> None:
    """注入 DashScope key：优先已有 env，否则读 阿里.txt 第一把 / webui_settings。"""
    import re as _re
    if os.environ.get("AW_DASHSCOPE_API_KEY"):
        return
    key = ""
    try:
        raw = Path(r"E:\密钥文件\阿里.txt").read_text(encoding="utf-8", errors="replace")
        for ln in raw.splitlines():
            m = _re.search(r"sk-[A-Za-z0-9\.\-_]{8,}", ln.strip())
            if m:
                key = m.group(0)
                break
    except Exception:
        pass
    if not key:
        try:
            cfg = json.loads(Path(r"E:\密钥文件\webui_settings.json").read_text(encoding="utf-8"))
            key = (cfg.get("dashscope") or {}).get("api_key") or ""
        except Exception:
            pass
    if key:
        os.environ["AW_DASHSCOPE_API_KEY"] = key


def run_engine(workflow: str, sets: dict[str, str], log_path: Path,
               extra_args: list[str] | None = None) -> int:
    _ensure_llm_keys()
    cmd = [PY, "run.py", workflow] + list(extra_args or [])
    for k, v in sets.items():
        cmd.extend(["--set", f"{k}={v}"])
    _log("$ " + " ".join(cmd[:8]) + " ...")
    with log_path.open("w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ENGINE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _log(line.rstrip("\n"))
            lf.write(line)
        return proc.wait()


def pick_results(run_id: str | None) -> list[str]:
    files: list[str] = []
    roots = [
        ENGINE / "tmp" / "selftest_批次",
        Path(r"D:\AIWorkflow\ComfyUI_H3\output"),
        Path(r"E:\图像影音资源池"),
    ]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"}:
                continue
            if run_id and (run_id in p.name or run_id in str(p.parent)):
                files.append(str(p))
    # 兜底：最近 2 小时产物
    if not files:
        cutoff = time.time() - 2 * 3600
        for root in [Path(r"D:\AIWorkflow\ComfyUI_H3\output"), ENGINE / "tmp"]:
            if not root.exists():
                continue
            for p in root.rglob("*"):
                try:
                    if p.is_file() and p.suffix.lower() in {".png", ".mp4"} and p.stat().st_mtime > cutoff:
                        files.append(str(p))
                except OSError:
                    pass
    return sorted(set(files), key=lambda x: Path(x).stat().st_mtime, reverse=True)[:40]


def recent_from_pool(hours: float = 3.0) -> list[str]:
    """从归档根按 run_id 目录名捞最近产物。

    为什么不能只扫 ComfyUI output：引擎跑完会把产物 relocate 进
    `E:\\图像影音资源池\\<项目>\\批次\\<run_id>\\video\\`，UI 那个进程一旦重启，
    内存里的 STATE 就空了，「最近产物」区会一片空白 —— 片子明明在盘上。
    按目录名里的时间筛，不做全盘 rglob（资源池十几万个文件，那样会卡住 UI）。
    """
    pool = Path(r"E:\图像影音资源池")
    if not pool.is_dir():
        return []
    cutoff = time.time() - hours * 3600
    found: list[tuple[float, str]] = []
    for proj in pool.iterdir():
        batch_root = proj / "批次"
        if not batch_root.is_dir():
            continue
        for run in batch_root.iterdir():
            if not run.is_dir():
                continue
            try:
                stamp = time.mktime(time.strptime(run.name, "%Y%m%d_%H%M%S"))
            except (ValueError, OverflowError):
                continue
            if stamp < cutoff:
                continue
            for sub in ("video", "image"):
                d = run / sub
                if not d.is_dir():
                    continue
                for f in d.iterdir():
                    if f.is_file() and f.suffix.lower() in {".mp4", ".webm", ".png", ".jpg", ".jpeg", ".webp"}:
                        try:
                            found.append((f.stat().st_mtime, str(f)))
                        except OSError:
                            pass
    found.sort(reverse=True)
    return [p for _, p in found[:20]]


_RECENT_CACHE: tuple[float, list[str]] = (0.0, [])


def status_payload() -> dict:
    """给 /api/status 用：进程活着就报内存状态；空闲且内存空了，回退到盘上捞最近产物。"""
    with STATE_LOCK:
        snap = dict(STATE)
        snap["log"] = list(STATE["log"])
        snap["files"] = list(STATE["files"])
        snap["warnings"] = list(STATE.get("warnings") or [])
        running = bool(STATE["running"])
    snap["files_source"] = "live"
    if not running and not snap["files"]:
        global _RECENT_CACHE
        now = time.time()
        if now - _RECENT_CACHE[0] > 20:
            files: list[str] = []
            for root in (Path(r"D:\AIWorkflow\ComfyUI_H3\output"), NL_DIR):
                if root.is_dir():
                    cutoff = now - 3 * 3600
                    for f in root.rglob("*"):
                        try:
                            if f.is_file() and f.suffix.lower() in {".mp4", ".png"} and f.stat().st_mtime > cutoff:
                                files.append(str(f))
                        except OSError:
                            pass
            def _mt(p: str) -> float:
                try:
                    return Path(p).stat().st_mtime
                except OSError:
                    return 0.0

            _RECENT_CACHE = (now, sorted(files + recent_from_pool(), key=_mt, reverse=True)[:40])
        snap["files"] = _RECENT_CACHE[1]
        snap["files_source"] = "disk"
    return snap


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[nl-ui] " + (fmt % args) + "\n")

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _translate(self) -> None:
        """中文 → 该模式的官方英文稿，只回文本给前端填入输入框；不写 prompt_file、不提交 GPU。"""
        body = self._read_json()
        text = (body.get("text") or "").strip()
        mode = norm_mode(body.get("mode") or body.get("channel"))
        if mode not in VIDEO_MODES:
            self._json(400, {"error": f"未知出片模式 {body.get('mode') or body.get('channel')}，"
                                      f"仅支持 {'/'.join(VIDEO_MODES)}"})
            return
        try:
            n_refs = int(body.get("n_refs") or 0)
        except (TypeError, ValueError):
            n_refs = 0
        slots = VIDEO_MODES[mode]["slots"]
        if not text:
            self._json(400, {"error": "先在需求框里写中文"})
            return
        if n_refs != slots:
            self._json(400, {"error": f"这个模式要正好 {slots} 张参考图（当前 {n_refs} 张）——"
                                      "模板槽位数固定，G4 会按槽位数核对，多挂被静默丢、少挂直接失败"})
            return
        saved = copy_refs(body.get("refs") or [])
        if saved:
            n_refs = len(saved)
        look, look_note = ("", "未看图")
        if str(body.get("use_vl", "true")).lower() in ("1", "true", "yes"):
            look, look_note = vl_look(saved)
        try:
            out = llm_translate(text, mode, n_refs, look=look)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": "翻译失败：" + redact(f"{type(e).__name__}: {e}")[:300]})
            return
        drafted = out["prompt"]
        warns = check_draft(drafted, VIDEO_MODES[mode]["kind"])
        if look:
            warns.insert(0, "ℹ 看图：" + look_note)
        else:
            warns.insert(0, "⚠ 没看成图（" + (look_note or "原因未知") + "）——稿子里的外观/场景是模型按你的文字推的，"
                                   "务必逐条核对；它擅长编出图里没有的服装与家具")
        if out.get("repaired"):
            warns.insert(1, "ℹ " + out["repaired"])
        self._json(200, {
            "ok": True, "mode": mode, "prompt": drafted,
            "chars": len(drafted), "backend": out["backend"], "elapsed": out["elapsed"],
            "warns": warns,
        })

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            body = HTML.read_bytes() if HTML.exists() else b"nl-ui missing index.html"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/api/status":
            self._json(200, status_payload())
            return
        if u.path == "/api/presets":
            # 预置表只在这里出一次，前端下拉由它填（避免 HTML 里再抄一份口径）
            self._json(200, {
                "modes": [{"key": k, "label": MODE_LABELS[k], "slots": v["slots"],
                           "tiers": [{"key": tk, "label": tv["label"], "note": tv.get("note", ""),
                                      "workflow": tv["workflow"]} for tk, tv in v["tiers"].items()]}
                          for k, v in VIDEO_MODES.items()],
                "ratios": [{"key": k, "w": w, "h": h} for k, (w, h) in RATIOS.items()],
                "lengths": [{"key": k, "frames": f, "seconds": s} for k, (f, s) in LENGTHS.items()],
            })
            return
        if u.path == "/api/workflows":
            names = sorted(p.stem for p in WORKFLOWS.glob("*.yaml"))
            self._json(200, {"workflows": names})
            return
        if u.path.startswith("/file/"):
            rel = u.path[len("/file/") :]
            # only allow under known roots
            fp = Path(rel)
            if not fp.is_absolute():
                fp = Path(r"D:\AIWorkflow") / rel
            ok_roots = [
                Path(r"D:\AIWorkflow"),
                Path(r"E:\图像影音资源池"),
                Path(r"D:\AIWorkflow\ComfyUI_H3\output"),
            ]
            if not any(str(fp).startswith(str(r)) for r in ok_roots) or not fp.exists():
                self._json(404, {"error": "not found"})
                return
            data = fp.read_bytes()
            ctype = "image/png" if fp.suffix.lower() == ".png" else (
                "video/mp4" if fp.suffix.lower() == ".mp4" else "application/octet-stream"
            )
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"error": "unknown"})

    def do_POST(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/translate":
            self._translate()
            return
        if u.path != "/api/run":
            self._json(404, {"error": "unknown"})
            return
        body = self._read_json()
        with STATE_LOCK:
            if STATE["running"]:
                self._json(409, {"error": "已有任务在跑"})
                return

        mode = (body.get("mode") or "image").strip().lower()
        nl = (body.get("prompt") or "").strip()
        if not nl:
            self._json(400, {"error": "请填写需求描述"})
            return

        refs = copy_refs(body.get("refs") or [])
        sets: dict[str, str] = {}
        warnings: list[str] = []
        workflow = ""

        # G13 运行级必填槽：每次必须由人显式给值，机器不代填
        polish = body.get("polish")
        if polish is None:
            polish = False
        enable_audio = body.get("enable_audio")
        if enable_audio is None:
            enable_audio = True
        resolution_tier = str(body.get("resolution_tier") or "draft").strip() or "draft"

        if mode == "image":
            workflow = body.get("workflow") or "image_draft_batch"
            count = int(body.get("count") or 1)
            sets = {
                "theme": nl[:80],
                "prompt": nl,
                "count": str(max(1, min(count, 8))),
                "use_llm_polish": "true" if polish else "false",
                "enable_audio": "true" if enable_audio else "false",
                "resolution_tier": resolution_tier,
            }
            if body.get("width"):
                sets["width"] = str(int(body["width"]))
            if body.get("height"):
                sets["height"] = str(int(body["height"]))
        elif mode == "video":
            shot = norm_mode(body.get("shot") or body.get("channel"))
            if shot not in VIDEO_MODES:
                self._json(400, {"error": f"未知出片模式 {body.get('shot') or body.get('channel')}，"
                                          f"仅支持 {'/'.join(VIDEO_MODES)}"})
                return
            spec = VIDEO_MODES[shot]
            kind, slots = spec["kind"], spec["slots"]
            tier = tier_of(shot, body.get("tier"))
            workflow = tier["workflow"]
            # 出片不再走运行期润色（10-14 他指定）：改稿只留「中文 → 英文合规稿并填入」一条路，
            # 那条云端盲改写会把主体写成泛化的 "a person"、还凭空发明场景，改坏了看不见。
            # G13 要这三项显式给值，所以照样传，只是值固定 false。
            polish = False

            ratio = str(body.get("ratio") or "v916").strip()
            len_key = str(body.get("duration") or "5.2").strip()
            if ratio not in RATIOS:
                self._json(400, {"error": f"未知画幅 {ratio}，预置只有 {'/'.join(RATIOS)}"})
                return
            if len_key not in LENGTHS:
                self._json(400, {"error": f"未知时长 {len_key}，预置只有 {'/'.join(LENGTHS)} 秒"})
                return
            width, height = RATIOS[ratio]
            frames, seconds = LENGTHS[len_key]

            if len(refs) != slots:
                self._json(400, {
                    "error": f"「{MODE_LABELS[shot]}」要正好 {slots} 张参考图，当前 {len(refs)} 张。"
                             "模板槽位数是固定的：多挂被静默丢弃、少挂会以 __REFn__ 字面量提交给 "
                             "LoadImage 直接失败（G4 同口径），所以在这儿先挡。"})
                return

            if kind == "ref2va":
                if not looks_like_ref2va(nl):
                    self._json(400, {
                        "error": "多参考图模式要的是官方英文六段稿（subject_definitions → summary → "
                                 "retention_analysis → detailed_description → overall_soundscape → "
                                 "non_diegetic_music）。先点「中文 → 英文合规稿并填入」再开始生成。"})
                    return
                prompt_text = nl
            else:
                # 已经是官方骨架稿就原样用（翻译填充器给的正是这种），否则按骨架包一层
                prompt_text = nl if looks_like_i2va(nl) else build_h3_prompt(nl)[0]

            bad = cjk_residue(prompt_text)
            if bad:
                self._json(400, {
                    "error": f"正文还残留中文「{bad}」，G7 会 0 秒拦下（这次不占显卡）。"
                             "点「中文 → 英文合规稿并填入」拿英文稿再跑；台词会留在 <d>…</d> 里不动。"})
                return

            warnings.extend(check_draft(prompt_text, kind))
            if shot == "first":
                warnings.append("锁首帧：只有这一张图进模型，且它是几何锚——H3 会把第 0 帧重画一遍再往下走，"
                                "脸在动起来了是模型自己补的。想锁身份请用多参考图模式。")
            if shot == "first_last":
                warnings.append("两头夹只钉两端：中间路径（飞行方向、动作次序）仍是抽签，"
                                "同参数多跑两条挑一条；第 2 张尾帧本身要接近出片比例（它是居中裁切）。")
            if ratio == "native":
                warnings.append("1344×768 是 H3 原生画布但比例是 7:4，G5 会 warn；要严格 16:9 用 h169 / h169s。")
            if len_key in LONG_VERTICAL_WARN.get(ratio, ()):
                warnings.append(f"竖屏 {len_key}s（{frames} 帧）在这台 16GB 上有换页悬崖风险"
                                "（226 帧竖屏曾实测 13.1 s/帧）；变慢就降帧数或改横屏。")

            # 同图占多槽＝白占额度还误导模型（09-18 那批四条全废的根因之一，免费一分钟先查）
            digests: dict[str, list[int]] = {}
            for i, rp in enumerate(refs, 1):
                try:
                    digests.setdefault(hashlib.md5(Path(rp).read_bytes()).hexdigest(), []).append(i)
                except OSError:
                    pass
            for dup in [v for v in digests.values() if len(v) > 1]:
                warnings.append(f"第 {'/'.join(str(x) for x in dup)} 张内容完全相同 —— 同图占多槽会误导模型")

            pf = NL_DIR / f"h3_{int(time.time())}_{uuid.uuid4().hex[:6]}.txt"
            pf.write_text(prompt_text, encoding="utf-8")  # 无 BOM
            sets = {
                "prompt_file": str(pf),
                "ref_images": ",".join(refs),
                "width": str(width),
                "height": str(height),
                "length": str(frames),
                "duration": str(seconds),
                "use_llm_polish": "false",
                "enable_audio": "true" if enable_audio else "false",
                "resolution_tier": resolution_tier,
            }
            sets.update(tier.get("sets") or {})   # 档位覆盖参数（步数与 LoRA 成对给）
            warnings.append(f"档位＝{tier['label']}｜{tier.get('note', '')}")
            _log(f"模式={MODE_LABELS[shot]}({shot}) 档位={tier['label']} 工作流={workflow} "
                 f"画幅={width}x{height} 帧数={frames}({seconds}s) 图={len(refs)}张")
        else:
            self._json(400, {"error": "mode 仅支持 image / video"})
            return

        run_id = time.strftime("%Y%m%d_%H%M%S")
        log_path = LOGS / f"{run_id}_{workflow}.log"

        with STATE_LOCK:
            STATE.update(
                {
                    "running": True,
                    "run_id": run_id,
                    "workflow": workflow,
                    "mode": mode,
                    "log": [f"任务 {run_id} 启动 mode={mode} workflow={workflow}"],
                    "result_dirs": [],
                    "files": [],
                    "exit_code": None,
                    "error": None,
                    "warnings": warnings,
                }
            )

        def worker():
            code = -1
            err = None
            try:
                _log(f"参考图: {len(refs)} 张")
                for w in warnings:
                    _log("[warn] " + w)
                code = run_engine(workflow, sets, log_path,
                                  extra_args=["--project", PLAY_PROJECT,
                                              "--output-root", PLAY_OUTPUT_ROOT])
                files = pick_results(run_id)
                with STATE_LOCK:
                    STATE["exit_code"] = code
                    STATE["running"] = False
                    STATE["files"] = files
                    if code != 0:
                        STATE["error"] = f"引擎退出码 {code}，详见日志"
                    STATE["log"].append("=== 完成 ===")
            except Exception as e:  # noqa: BLE001
                err = str(e)
                with STATE_LOCK:
                    STATE["running"] = False
                    STATE["error"] = err
                    STATE["log"].append("[error] " + err)

        threading.Thread(target=worker, daemon=True).start()
        self._json(200, {"ok": True, "run_id": run_id, "warnings": warnings})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"说话出片 UI  http://{args.host}:{args.port}/", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

