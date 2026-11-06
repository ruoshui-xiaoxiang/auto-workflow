#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跑前自审闸 G1–G8 + G12（本地 H3 出片链）

定位：纯算术 / 纯字符串 / 纯文件属性的判定。**不含任何模型意见**——
"好不好/像不像"这类需要人判断的，一律不在这里，走人工关口（H）。

G7 的前提（2026-09-28）：**先认格式，再选判据**。提示词已按通道刻意分成四套格式
（本地 H3 官方骨架 / 本地 H3 全参考六段 / 云端中文十块 / 图片无格式），
认格式的逻辑与 `tools/prompt_format.py` 同源（2026-10-19 Phase 4 起真源在 tools/；
`tmp/wzy/` 那份与它 md5 全等 b66ae6ac，只作兜底），通道与格式对不上就报**混用**。

设计动因（实测）：2026-09-18 连跑四条 H3（每条 7 分 25–42 秒）全部作废，
根因是 ref_images 槽位配错——同一张图占多个槽、三条声明"薇拉"的镜挂的全是
白玖璃。那是 G2/G3 一次就能拦住的错误。

用法（独立命令行）：
  py check_preflight.py --prompt-file P.txt --refs A.png,B.png,C.png,D.png \
      --w 864 --h 1536 --length 124 --steps 8 --seed 42 \
      [--lora xxx.safetensors] [--ref-video V.mp4] [--slot-label 1=薇拉,2=白玖璃] \
      [--prompt-kind video|h3_i2va|image] [--duration 5.2] [--provider local|ark] \
      [--check-service] [--strict] [--json out.json]

被引擎调用：from check_preflight import run_checks; run_checks(spec) -> Report
退出码：0 = 通过（可能有警告）；1 = 有 error 级问题；2 = 参数/环境自身不可用。
--strict 时警告也按失败处理。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------- 项目常量（改动请同步 桌面《本地工作流_关口化方案_待审.md》） ----------------
# 两把尺要分清，别混成一把：
#   官方硬界（model card）＝时长 4–15s ⇒ @24fps 名义 **96–360 帧**；362 帧＝15.08s 超 15s ⇒ 官方就拒。
#   本机放行界（B1 裁定 10-23）＝官方区间 ∩ T8 节点 length 的 **17n+5 网格**（nodes_minimax_h3.py:105）
#     ⇒ 下沿取 107（=5+17·6，4.46s），上沿取 **345**（=5+17·20，14.38s；网格上 362 的下一格）。
#     345/107 这两个数是**我们的网格裁定**，官方并没有写 345；改文案时不许挂到官方名义下。
#   107–123：官方允许、低于本机节点声明的训练下限 ⇒ **放行＋warn**（10-23 裁定：不以未实测禁选）。
# 写稿契约 h3_official_spec 仍按官方 96–360 判（那是"能不能这样写"），G6 判"这台机器放不放行"。
H3_MIN_FRAMES = 107     # 本机放行下沿：17n+5 网格里 ≥ 官方 4s 的第一格（4.46s）
H3_MAX_FRAMES = 345     # 本机放行的官方时长上限（≈14.38s）；362 既超官方 15s 也停止用于新批
H3_LOCAL_TRAINED_MIN = 124   # 本机节点 tooltip 的已训练区间下限；107–123 允许但标风险
H3_FPS = 24
# 官方硬界（model card：时长 4–15s）换算成 @24fps 的帧数——与上面的"本机放行界"是两把尺
OFFICIAL_MIN_FRAMES = 96
OFFICIAL_MAX_FRAMES = 360
# 已停用（10-24 质量核查 P1-②）：以前用 REF_VIDEO_MIN/MAX_FRAMES = 48/360 当"每段 2–15s"的代理判据，
# 那是**隐含 24fps 假设**的错尺子——300 帧在 10fps 下是 30s（该拦）却落在 48–360 里被放过。
# 现在按下面的秒数区间＋实测 fps 判（`g4_slots_and_quota` 里 `secs = n / fps`）。常数已删，别再请回来。
REF_MEDIA_MIN_SECONDS = 2.0    # 官方：每段参考视频／参考音频 2–15 秒
REF_MEDIA_MAX_SECONDS = 15.0
REF_VIDEO_ALIGN = "17n+5"      # 参考帧按 17n+5 截齐（102 → 90）
TRUTH_9_16 = {"576x1024", "864x1536", "288x512", "1152x2048"}   # 9:16 且 32 倍数
ARK_LIMIT_IMAGES, ARK_LIMIT_VIDEOS, ARK_LIMIT_AUDIOS = 30, 10, 10
# ⚠ 10-02 批 6 查出的**未校验项**（用户裁定：只登记不补校验）：`ARK_LIMIT_AUDIOS` 声明后在本文件
#    与引擎里都零使用 ⇒ 「音频参考最多 10 个」这条上限**从来没被检查过**。
#    不擅自补校验的原因：没有通道真源支撑这个数（可灵/云端各家音频上限未实测，GAP-C5），
#    凭一个来路不明的数字去拦提交就是编造判据（R4-06 同一条）。
#    已登记：`R_作用域与例外登记表.md` 待决列 ＋ 扫描器 `gates.qc_wiring.unused_declared_constants`。
ARK_LIMIT_TOTAL_ASSETS, ARK_LIMIT_REF_SECONDS = 50, 30.0
# 官方 MiniMaxAI/MiniMax-H3 模型卡：Ref2VA 输入规格（与 ARK 云端额度是两套，别混）
# 逐字出处 README.zh-CN:85：「图像 ≤9 张／视频 ≤3 段（每段 2–15s、总 ≤15s）／音频 ≤3 段
# （每段 2–15s、总 ≤15s、不可作为唯一输入）／所有输入类型的文件总数最多为 12 个」。
# ⚠ 那行把音频算**一类 ≤3**；T8 节点 schema 拆成 ref_video_audios／ref_audios 各 max 3
#   ⇒ 下面的 H3_REF_MAX_AUDIOS 用的是节点口径，跨类合计那条读法只在 G4 warn（见 g4_slots_and_quota）。
H3_REF_MAX_IMAGES, H3_REF_MAX_VIDEOS, H3_REF_MAX_AUDIOS = 9, 3, 3
H3_REF_MAX_TOTAL, H3_REF_MAX_SECONDS = 12, 15.0

TEN_BLOCKS = ["生成目标", "参考素材职责", "未采用素材", "主体与关系", "场景与环境",
              "事件脚本", "镜头", "风格与光影", "保持一致", "声音"]
CORE_BLOCKS = ["主体与关系", "事件脚本", "保持一致", "镜头", "声音"]   # 缺了会直接改写画面

# 运镜器材名词会被模型实体化渲进画面（历史教训）
CAMERA_GEAR = ["稳定器", "斯坦尼康", "摇臂", "云台", "轨道车", "滑轨", "手持摄影机",
               "摄影机", "摄像机", "三脚架", "无人机", "dolly", "steadicam",
               "gimbal", "crane", "slider", "rig"]
# 会被字面化渲染的措辞（"蝶形双翼"真的渲成了蝴蝶翅膀）
LITERAL_RISK = ["蝶形", "蝴蝶翼", "天使羽翼", "羽翼", "球状裙撑", "紧身胸衣", "立领包颈"]
SILENT_ROLE = ["哑女", "无声", "全程不出声"]
SILENT_REQUIRED = ["不出声", "不张嘴"]

# ---------------- 格式底座（判格式/判混用的唯一口径来源） ----------------
# 2026-09-28 起提示词**按通道刻意分成四套格式**，目的是让混用一眼可见：
#   本地 H3 视频（i2va/fl2va）＝ 官方骨架：逐字首行指令 + 空行 + 恰三字段 + `[Shot 1]` 正文
#   本地 H3 视频（ref2va）    ＝ 官方全参考六段：subject_definitions → summary →
#                                retention_analysis → detailed_description →
#                                overall_soundscape → non_diegetic_music（真源
#                                ComfyUI_H3/prompts/official_h3/ref-en.txt §7）
#   云端 SD 视频              ＝ 中文十块模板（必填核心五块），已**移出 H3**
#   图片（首帧/定妆）          ＝ 无强制格式，只查共性坑
# 认格式的逻辑只写一份：`prompt_format.py`（h3_rule_gate.py 同源共用）。
# 2026-10-19 Phase 4：真源上移到 `tools/`（与 `tmp/wzy/` 那份 md5 全等 b66ae6ac，实测两者都能
# 干净导入、都不改 CWD）。`tmp\wzy` 两条**暂时保留在最后当兜底**——Phase 5 归档 tmp\wzy 时一并删。
# ⚠ 顺带记一个既有隐患（本次未改）：`_load_prompt_format()` 用的是普通 `import prompt_format`，
#   不是 `spec_from_file_location`。所以若别的模块（如 h3_rule_gate）已经先从 tmp\wzy 把它 import 过，
#   `sys.modules` 里的缓存会赢，这里的搜索顺序就**不起作用**。今天无害——两份逐字节相同；
#   但只要有人改其中一份，"改了不生效"或"生效的是哪份说不准"就会出现。
# 导入失败时本文件退回内置兜底判定，并**显式 warn**——"底座不在"必须让闸自己说出口，
# 不能静默按某一套旧口径放行（教训见手册 R2-02：改分派必须同批核对所有调用方）。
PF_SEARCH_DIRS = [os.environ.get("H3_PROMPT_FORMAT_DIR", ""),
                  str(Path(__file__).resolve().parent),
                  str(Path(__file__).resolve().parent.parent / "tmp" / "wzy"),
                  r"D:\AIWorkflow\tmp\wzy"]


def _load_prompt_format():
    for d in PF_SEARCH_DIRS:
        f = Path(d) / "prompt_format.py" if d else None
        if f and f.is_file():
            if d not in sys.path:
                sys.path.insert(0, d)
            try:
                import prompt_format
                return prompt_format, None
            except Exception as e:                      # 在却 import 不了，比不在更该喊
                return None, "%s 导入失败：%s" % (f, e)
    return None, "没找到 prompt_format.py（查过 %s）" % " / ".join(
        [x or "(空)" for x in PF_SEARCH_DIRS])


PF, PF_ERR = _load_prompt_format()


def _load_official_spec():
    """W2：格式核心唯一真源＝同目录 h3_official_spec.py。

    2026-10-23 前 G7 自己维护一份首行表（I2VA/FL2VA/L2VA 三形），房内闸与对白闸又各写一份
    ⇒ 同一份 FL2VA 稿在三道闸里判成不同模式。现在三闸都调 h3_official_spec：
      detect_skeleton_mode() / detect_format() / analyze()。
    导入失败**不退回第二份表**：G7 明说"格式核心不可用"，宁可红也不静默换口径。
    """
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import h3_official_spec as _spec
        return _spec, None
    except Exception as e:
        return None, "%s 导入失败：%s" % (Path(__file__).resolve().parent / "h3_official_spec.py", e)


SPEC, SPEC_ERR = _load_official_spec()

# 骨架/六段指纹：**从格式核心取**（单一真源）；SPEC 不可用时才用下方等值镜像，
# 且 G7 会显式 warn/error 说明本次是降级判定。
SKELETON_INSTRUCTION = ("For the target video, at 0.00 seconds into the target video, "
                        "<Picture 1> (from [Shot 1]) is fully referenced.")
BASE_FIELDS = ("integrated_multimodal_description:", "overall_soundscape:",
               "non_diegetic_music:")
REF2VA_FIELDS = ("subject_definitions:", "summary:", "retention_analysis:",
                 "detailed_description:", "overall_soundscape:", "non_diegetic_music:")
# 六段里**独有且够特殊**的三个：判"骨架混进六段"只能看这一组。用全量 REF2VA_FIELDS 会把
# 骨架自带的 overall_soundscape / non_diegetic_music 误判成混用（A 线 23 镜全假报，实测踩过）。
# `summary:` 也太通用（正文可能出现该英文词），故不入判据。
REF2VA_ONLY = ("subject_definitions:", "retention_analysis:", "detailed_description:")
# 官方 base-en §2.1 的第一行按模式分四形。FL2VA 首行里的 Picture 1/2 **不带尖括号**，
# L2VA 的 <Picture 1> 带。具体判定一律走 SPEC.detect_skeleton_mode，本文件不重写规则。
ALIGN_FIRST_PREFIX = "How the reference pictures align with the target video"
FL2VA_FIRST_LINE = (ALIGN_FIRST_PREFIX + " — "
                    "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                    "Picture 2 (from Shot {N}) aligns with the {S}-second mark of the target video.")
L2VA_FIRST_LINE = (ALIGN_FIRST_PREFIX + " — "
                   "<Picture 1> (from [Shot {N}]) aligns with the {S}-second mark of the target video.")
BLOCK_CN_RE = re.compile(u"【([^】]{1,12})】")
FMT_LABEL = {"h3_skeleton": "本地 H3 官方骨架（三字段）",
             "h3_ref2va": "本地 H3 全参考六段",
             "sd_tenblock": "云端 SD 中文十块",
             "plain": "无强制格式（图片口径／未分块）"}
FMT_CHANNEL = {"h3_skeleton": "h3", "h3_ref2va": "h3",
               "sd_tenblock": "cloud", "plain": "image"}
if SPEC is not None:
    SKELETON_INSTRUCTION = SPEC.I2VA_FIRST_LINE
    BASE_FIELDS = tuple(SPEC.BASE_FIELDS)
    REF2VA_FIELDS = tuple(SPEC.REF_FIELDS)
    REF2VA_ONLY = tuple(SPEC.REF2VA_ONLY_FIELDS)
elif PF is not None:
    SKELETON_INSTRUCTION = PF.SKELETON_INSTRUCTION
    BASE_FIELDS = tuple(PF.BASE_FIELDS)
    REF2VA_FIELDS = tuple(PF.REF2VA_FIELDS)
    REF2VA_ONLY = tuple(PF.REF2VA_ONLY)


FACE_MIN_PX = 300              # 经验阈值：低于此不宜当"脸锚"（启发式，警告级，非硬界）
YUNET_ONNX = r"D:\AIWorkflow\models\face\face_detection_yunet_2023mar.onnx"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


class Report:
    def __init__(self):
        self.items = []          # (level, gate, text)
        self.hard = []           # 结构性 error：这批素材/参数**根本组不出可提交的图**
        # 为什么单开一条：`--tier play` 的 allow_degrade 会把 error 降级成 warn 放行
        # （预览档要的就是"质感问题别拦我"）。但"只给音频没给图/视频""槽位数对不上""帧数越界"
        # 不是质感问题，是**这条链在物理上不存在**——降级放行只会让它走到更远的地方才炸，
        # 而且那之前已经把 ComfyUI 拉起来了（10-24 跑 P7 负例时就是这么发生的）。

    def ok(self, gate, text):
        self.items.append(("ok", gate, text))

    def warn(self, gate, text):
        self.items.append(("warn", gate, text))

    # 哪些 error 属于"结构性"＝这条链在物理上组不出来，**预览档也不许降级放行**。
    # 逐条列出来而不是按闸门整类算，是为了不误伤：G4 里"两种音频读法不一致"那种分歧
    # 是判断口径问题（可以降级），"图 > 9 张""音频单独输入""文件不存在"是真组不出图。
    HARD_GATES = ("G1", "G6")                     # 锚点缺/空字节、帧数越界
    HARD_G4_PREFIX = ("官方上限", "个图槽", "个槽，只挂", "文件不存在",
                      "不能单独", "每段区间", "引用 <Video")

    def error(self, gate, text, hard=None):
        self.items.append(("error", gate, text))
        if hard is None:
            hard = (gate in self.HARD_GATES
                    or (gate == "G4" and any(k in text for k in self.HARD_G4_PREFIX)))
        if hard:
            self.hard.append((gate, text))

    @property
    def hard_errors(self):
        return list(self.hard)

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "error"]

    @property
    def warns(self):
        return [i for i in self.items if i[0] == "warn"]

    def render(self):
        icon = {"ok": "  ✓", "warn": "  !", "error": "  ✗"}
        lines = []
        for lv, gate, text in self.items:
            lines.append(f"{icon[lv]} [{gate}] {text}")
        lines.append("")
        lines.append(f"结论：error={len(self.errors)} warn={len(self.warns)}")
        return "\n".join(lines)


# ---------------- 小工具 ----------------
def _md5(p: Path, bufsize: int = 1 << 16) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def _video_stats(p: Path):
    """无 ffprobe：用 cv2 取 帧数/宽高/fps；取不到返回 None 三元组。"""
    try:
        import cv2
    except Exception:
        return None, None, None, None
    try:
        cap = cv2.VideoCapture(str(p))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cap.release()
        return (n or None), (w or None), (h or None), (fps or None)
    except Exception:
        return None, None, None, None


def _largest_face_px(p: Path):
    """返回该图最大人脸框的短边像素；无脸/不可用时返回 None。"""
    if not Path(YUNET_ONNX).is_file():
        return None
    try:
        import cv2
        import numpy as np
        try:
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
        except Exception:
            pass
    except Exception:
        return None
    try:
        raw = np.fromfile(str(p), dtype=np.uint8)          # 中文路径绕开 imread 坑
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if img is None:
            return None
        det = cv2.FaceDetectorYN.create(YUNET_ONNX, "", (320, 320), 0.5, 0.3, 5000)
        h, w = img.shape[:2]
        scale = 640.0 / max(h, w)
        small = cv2.resize(img, (int(w * scale), int(h * scale)))
        det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = det.detect(small)
        if faces is None or len(faces) == 0:
            return None
        best = max((f[2] * f[3] for f in faces))
        side = int(round((best ** 0.5) / scale))
        return side
    except Exception:
        return None


def _parse_slots(prompt: str):
    """抽 <Picture N> 是 X / @图片N 是 X 的声明；返回 {N: 角色名}。"""
    out = {}
    pat = re.compile(r"(?:<Picture\s*(\d+)>|@图片\s*(\d+)|图片\s*(\d+))[^，。;；\n]{0,12}?[是为:：]\s*([^，。;；\n（(]{1,20})")
    for m in pat.finditer(prompt):
        n = int(next(g for g in m.groups()[:3] if g))
        name = m.group(4).strip()
        out.setdefault(n, name)
    # 官方职责句常写成「<Picture 1> 薇拉的脸锚」（没有"是"字），这种点名也要认出来
    pat2 = re.compile(r"(?:<Picture\s*(\d+)>|@图片\s*(\d+))\s*[是为:：]?\s*"
                      r"([\u4e00-\u9fa5A-Za-z]{1,6})(?=的)")
    for m in pat2.finditer(prompt):
        out.setdefault(int(m.group(1) or m.group(2)), m.group(3).strip())
    return out


def _slot_count_in_template(workflow_json: Path, mode=None):
    """模板里 __REFn__ 占位符个数 = 引擎真实能吃的参考图槽位数。

    W1c 的可选首尾帧模板是例外：模板文件里 __REF1__/__REF2__ 都在，但
    `build_graph_video` 会按 input_mode 删掉用不到的 LoadImage——所以这里按模式给
    真实槽位（T2VA 0 / I2VA 1 / L2VA 1 / FL2VA 2），否则 T2VA 会被误报"缺图"。
    """
    try:
        txt = Path(workflow_json).read_text(encoding="utf8")
    except Exception:
        return None
    try:
        meta = (json.loads(txt).get("_meta") or {})
    except Exception:
        meta = {}
    if meta.get("optional_keyframes"):
        want = {"t2va": 0, "i2va": 1, "l2va": 1, "fl2va": 2}.get(str(mode or "").lower())
        if want is not None:
            return want
    return len(set(re.findall(r"__REF(\d+)__", txt)))


def _template_is_dynamic(workflow_json: Path):
    """W4c：模板自己声明"参考槽位按素材数动态注入"（`_meta.dynamic_reference_slots`）。"""
    try:
        return bool((json.loads(Path(workflow_json).read_text(encoding="utf8"))
                     .get("_meta") or {}).get("dynamic_reference_slots"))
    except Exception:
        return False


# ---------------- G1–G8 / G12 ----------------
def g1_files(rep, refs, ref_videos):
    missing, empty = [], []
    for f in list(refs) + list(ref_videos):
        p = Path(f)
        if not p.is_file():
            missing.append(str(p))
        elif p.stat().st_size == 0:
            empty.append(str(p))
    if missing:
        rep.error("G1", f"锚点缺失 {len(missing)} 个: {missing}", hard=True)
    if empty:
        rep.error("G1", f"锚点是 0 字节: {empty}", hard=True)
    if not missing and not empty:
        rep.ok("G1", f"锚点 {len(list(refs)) + len(list(ref_videos))} 个全部存在且非空")


def g2_md5_slots(rep, refs, ref_videos):
    hashes = {}
    for i, f in enumerate(list(refs) + [f"[视频]{v}" for v in ref_videos], 1):
        p = Path(f if not str(f).startswith("[视频]") else f.split("]", 1)[1])
        if not p.is_file():
            continue
        try:
            hashes.setdefault(_md5(p), []).append((i, p.name))
        except Exception as e:
            rep.error("G2", f"槽 {i} {p.name} 读不了（无法查重）: {type(e).__name__}: {e}")
    dup = {h: v for h, v in hashes.items() if len(v) > 1}
    if dup:
        for h, v in dup.items():
            rep.error("G2", f"md5 全等（{h[:8]}）被挂在多槽: "
                            f"{' / '.join(f'槽{i}={n}' for i, n in v)} —— 多占的槽等于没挂")
    else:
        rep.ok("G2", f"逐槽 md5 无重复（共 {len(hashes)} 个不同文件）")


def _looks_like_role_name(s: str) -> bool:
    """官方职责句常写「@图片1 只采用其面容特征——…」，那不是身份声明。"""
    if not s or len(s) > 10:
        return False
    if any(k in s for k in ("采用", "不采用", "特征", "款式", "配色", "参考", "质感",
                            "影调", "构图", "仅", "只", "用作", "作为")):
        return False
    return True


def _sidecar(p: Path):
    """锚点身份卡片：<图片文件>.anchor.json，形如
       {"character": "薇拉", "role": "face|costume|scene|style"}
       没有这张卡时，G3 只能靠文件名猜，猜不到就交人工。

       ⚠ 10-02 批3.1（D2 强制迁移 / D3 改后缀）之后，**同后缀曾经装过两种东西**：
       `烬骨辞` 那 12 份是「镜位→挂哪几张锚」的**绑定记录**（键 anchor_kind/anchors/shot），
       不是身份卡。它们已按裁定改成 `.shots.json` ⇒ 这里**只认 `.anchor.json`**，
       不再顺手读 `.shots.json`。读到带旧键的 `.anchor.json` 一律当**未迁移完**，
       由 g3_identity 报 error，**不由脚本补猜**（R4-06）。"""
    for cand in (Path(str(p) + ".anchor.json"), p.with_suffix(".anchor.json")):
        if cand.is_file():
            try:
                return json.loads(cand.read_text(encoding="utf8"))
            except Exception:
                return None
    return None


# schema v2 已把 `anchor_kind` 判为旧字段名（= 绑定记录混进了身份卡命名空间）。
LEGACY_SIDECAR_KEYS = ("anchor_kind",)


def _sidecar_legacy(card):
    """返回这份卡的旧字段名清单；空 = 合规。"""
    return [k for k in LEGACY_SIDECAR_KEYS if k in (card or {})]


def g3_identity(rep, prompt, refs, slot_labels):
    parsed = _parse_slots(prompt)
    declared = {n: w for n, w in parsed.items() if _looks_like_role_name(w)}
    duty = [n for n, w in parsed.items() if not _looks_like_role_name(w)]
    if duty:
        rep.warn("G3", f"槽 {duty} 写的是职责句而不是点名身份 —— 机器判不了挂没挂对人，"
                       f"这一槽需人工核对")
    if not parsed:
        rep.warn("G3", "提示词里没解析到 `<Picture N> 是 X` / `@图片N 是 X` 的身份声明 —— 无法核对槽位")

    slot_map, slot_role = {}, {}
    for i, f in enumerate(refs, 1):
        sp = Path(f)
        card = _sidecar(sp) or {}
        legacy = _sidecar_legacy(card)
        if legacy:
            # 强制迁移后这是**真错**不是提醒：旧字段名的卡里 `role` 是缺的，
            # 走下面的分支就会被当成"没标角色"⇒ 静默降级成靠文件名猜，
            # 猜错了还显示成核对通过。报出来，不许脚本补猜（R4-06）。
            rep.error("G3", f"槽 {i} {sp.name} 的身份卡还是旧字段名 {legacy}"
                            f"（schema v2 已强制：`anchor_kind` 属镜位绑定记录，"
                            f"该类文件 10-02 起应叫 `.shots.json`）"
                            f"⇒ 本槽角色无法核对，请人工迁移这份卡后再跑，脚本不代填")
        if card.get("role"):
            slot_role[i] = str(card["role"])
        label = slot_labels.get(i) or card.get("character")
        if label:
            slot_map[i] = label
        else:
            hit = [nm for nm in _known_names(prompt, refs) if nm in sp.name]
            slot_map[i] = hit[0] if hit else None

    # 编号越界：所有被引用的编号都要在（图＋参考视频）范围内
    for n in sorted(parsed):
        if n > len(refs):
            rep.error("G3", f"提示词引用 <Picture {n}>，但只挂了 {len(refs)} 张图 —— 编号越界，"
                            f"该编号会指向不存在的槽位")

    checked = 0
    for n, who in sorted(declared.items()):
        if n > len(refs):
            continue
        actual = slot_map.get(n)
        if not actual:
            rep.warn("G3", f"槽 {n} 身份未标注（文件名和 --slot-label 都对不上），"
                           f"提示词却声明为「{who}」—— 机器无法判定，请人工核对这一槽")
            continue
        checked += 1
        if actual not in who and who not in actual:
            rep.error("G3", f"槽 {n} 冲突：提示词声明「{who}」，实际挂的是「{actual}」"
                            f"({Path(refs[n-1]).name})")
    if checked:
        rep.ok("G3", f"已核对 {checked} 个槽位的声明身份，无冲突" if not rep.errors
               else f"已核对 {checked} 个槽位的声明身份")

    # 只量"当脸锚用"的槽：造型/道具/场景/画风锚脸小是正常设计，不该报
    for i, f in enumerate(refs, 1):
        p = Path(f)
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
            continue
        role = slot_role.get(i)
        if role:
            if role not in ("face", "脸", "定妆", "身份"):
                continue
        else:
            tag = f"{slot_map.get(i) or ''}{p.stem}".lower()
            if not any(k in tag for k in ("脸", "面容", "face", "定妆", "身份")):
                continue
        px = _largest_face_px(p)
        if px is None:
            rep.warn("G3", f"槽 {i} {p.name} 标称脸锚但量不到人脸，请人工确认")
        elif px < FACE_MIN_PX:
            rep.warn("G3", f"槽 {i} {p.name} 最大人脸约 {px}px < {FACE_MIN_PX}px"
                           f"（启发式阈值，非硬界）—— 当脸锚可能锁不住，"
                           f"考虑重拍拉近而不是提高分辨率")


def _known_names(prompt, refs):
    """只认提示词里点名过的角色名去撞文件名 —— 拿文件名自己造标签会误报
       （曾经把 a0.png 当成"槽1 是 a0"，与声明的「甲」判成冲突）。"""
    return [w for w in sorted({v for v in _parse_slots(prompt).values()},
                              key=len, reverse=True) if _looks_like_role_name(w)]


def g4_slots_and_quota(rep, refs, ref_videos, workflow_json, provider, duration, channel=None,
                       keyframe_mode=None, ref_audios=None, ref_video_audios=None):
    ref_audios = list(ref_audios or [])
    ref_video_audios = list(ref_video_audios or [])
    if workflow_json:
        slots = _slot_count_in_template(Path(workflow_json), keyframe_mode)
        if _template_is_dynamic(Path(workflow_json)):
            slots = None      # W4c 9 图版按素材数注入，模板里本来就没有固定槽
        if slots is None:
            if not _template_is_dynamic(Path(workflow_json)):
                rep.warn("G4", f"读不到模板 {workflow_json}，无法核对参考图槽位数")
        elif len(refs) > slots:
            _hint = (f"（{str(keyframe_mode).upper()} 模式不接这么多图：T2VA 0 张、"
                     f"I2VA/L2VA 1 张、FL2VA 2 张）" if keyframe_mode else
                     f"（引擎按 __REFi__ 逐个替换，第 {slots+1} 张无处可去）")
            rep.error("G4", f"挂了 {len(refs)} 张图，但本次模板只用 {slots} 个图槽 —— "
                            f"多出的会被静默丢弃{_hint}")
        elif len(refs) < slots:
            _need = "（缺尾帧：FL2VA 要首帧+尾帧两张）" if str(keyframe_mode or "").lower() == "fl2va" else ""
            rep.error("G4", f"模板有 {slots} 个槽，只挂 {len(refs)} 张{_need} —— "
                            f"未填充的占位符会以字面量 __REF{len(refs)+1}__ 提交给 LoadImage，直接失败")
    total = 0
    for v in ref_videos:
        p = Path(v)
        if not p.is_file():
            continue
        n, w, h, fps = _video_stats(p)
        if n is None:
            rep.warn("G4", f"参考视频 {p.name} 取不到帧数（无 ffprobe，cv2 失败）")
            continue
        kept = max([k for k in range(n + 1) if k % 17 == 5 and k <= n] or [0])
        # 每段 2–15s 用**实测秒数**判（帧数 ÷ 真实 fps），不用"帧数 48–360"代判：
        # 后者隐含 24fps 假设，遇到 30fps 的参考片会把 4.8s 当成 12s、把 12s 当成 4.8s（漏判/误判都会发生）
        secs = n / (fps or H3_FPS)
        if not (REF_MEDIA_MIN_SECONDS <= secs <= REF_MEDIA_MAX_SECONDS):
            rep.error("G4", f"参考视频 {p.name} 实测 {secs:.2f}s（{n} 帧 @{fps:.1f}fps），"
                            f"不在官方每段 {REF_MEDIA_MIN_SECONDS:g}–{REF_MEDIA_MAX_SECONDS:g}s 区间", hard=True)
        if kept and kept < n:
            rep.warn("G4", f"参考视频 {p.name} {n} 帧按 {REF_VIDEO_ALIGN} 截到 {kept} 帧，"
                           f"丢 {n-kept} 帧（约 {(n-kept)/(fps or H3_FPS):.2f}s 的收尾动作）")
        total += secs
    audio_total = 0.0
    for label, items, count_in_total in (("参考片原声", ref_video_audios, False),
                                         ("独立参考音频", ref_audios, True)):
        for v in items:
            p = Path(v)
            if not p.is_file():
                rep.error("G4", f"{label} {p.name} 文件不存在 —— 挂上去就会在提交时炸", hard=True)
                continue
            secs = _audio_seconds(p)
            if secs is None:
                rep.warn("G4", f"{label} {p.name} 取不到时长（soundfile/wave 都失败）——"
                               f"2–15s 与合计 ≤15s 这条**没判到**，请人工核对")
                continue
            if not (REF_MEDIA_MIN_SECONDS <= secs <= REF_MEDIA_MAX_SECONDS):
                rep.error("G4", f"{label} {p.name} 实测 {secs:.2f}s，不在官方 2–15s 每段区间", hard=True)
            if count_in_total:
                # 官方"音频总时长 ≤15s"指的是独立上传的参考音频；
                # 参考片原声跟着视频同文件走，与"视频总时长 ≤15s"是同一份额度
                audio_total += secs
    if provider != "ark" and str(channel or "").strip().lower() == "h3":
        # 本地 H3 走官方 Ref2VA 输入规格；ARK 云端额度是另一套，见下。
        # 只在 channel=h3 时生效，别误伤图片链（图片也可能挂多张参考）。
        # W4c：音频此前"只登记不判"，现在段长/合计/总数/不可单独输入都进闸了。
        if len(refs) > H3_REF_MAX_IMAGES:
            rep.error("G4", f"H3 Ref2VA 官方上限：图 {len(refs)} > {H3_REF_MAX_IMAGES}", hard=True)
        if len(ref_videos) > H3_REF_MAX_VIDEOS:
            rep.error("G4", f"H3 Ref2VA 官方上限：参考视频 {len(ref_videos)} > {H3_REF_MAX_VIDEOS}", hard=True)
        for label, items, cap in (("参考片原声", ref_video_audios, H3_REF_MAX_AUDIOS),
                                  ("独立参考音频", ref_audios, H3_REF_MAX_AUDIOS)):
            if len(items) > cap:
                rep.error("G4", f"H3 Ref2VA 官方上限：{label} {len(items)} > {cap}", hard=True)
        n_files = len(refs) + len(ref_videos) + len(ref_audios)
        if n_files > H3_REF_MAX_TOTAL:
            # 参考片原声取自同号参考视频，不是额外一份上传文件 ⇒ 不计入 12
            rep.error("G4", f"H3 Ref2VA 官方上限：总文件 {n_files}"
                            f"（图＋视频＋独立音频；视频原声随视频同文件）> {H3_REF_MAX_TOTAL}")
        if total > H3_REF_MAX_SECONDS:
            rep.error("G4", f"H3 Ref2VA 官方上限：参考视频合计 {total:.1f}s > {H3_REF_MAX_SECONDS}s")
        if audio_total > H3_REF_MAX_SECONDS:
            rep.error("G4", f"H3 Ref2VA 官方上限：参考音频合计 {audio_total:.1f}s > "
                            f"{H3_REF_MAX_SECONDS}s")
        if not refs and not ref_videos and (ref_audios or ref_video_audios):
            rep.error("G4", "H3 Ref2VA 官方口径：音频**不能单独**作为输入，必须与图像或视频同用"
                            "（现在只有音频）", hard=True)
        # 官方 README.zh-CN:85 写"音频：≤3 段"（一类），而 T8 节点把 ref_video_audios 与 ref_audios
        # 各自上限都设成 3 ⇒ 两种读法（跨类合计 3 / 每类各 3）在这里**不一致**。
        # 默认按节点（每类各 3，运行时真能挂上），合计 >3 只 warn 并点名分歧；要严格判成 error：
        # spec["audio_strict_total"]=True 或环境变量 AW_H3_AUDIO_STRICT=1。
        # 这条分歧已登记在 channels_registry.official_unvalidated ＋ ref2va.audio_cap_reading，不装判过。
        n_audio_all = len(ref_audios) + len(ref_video_audios)
        strict = audio_policy()["strict"]
        if n_audio_all > H3_REF_MAX_AUDIOS:
            msg = (f"参考音频合计 {n_audio_all}（独立 {len(ref_audios)}＋视频原声 "
                   f"{len(ref_video_audios)}）> 官方 README.zh-CN:85 的\"音频 ≤3 段\"——"
                   f"但 T8 节点是**每类各 3**（ref_video_audios≤3 且 ref_audios≤3），"
                   f"两种读法不一致")
            if strict:
                rep.error("G4", msg + " ⇒ 已按严格口径（AW_H3_AUDIO_STRICT）拦下")
            else:
                rep.warn("G4", msg + " ⇒ 默认按节点口径放行，严格判法见 registry.official_unvalidated")
    if provider == "ark":
        if len(refs) > ARK_LIMIT_IMAGES:
            rep.error("G4", f"云端素材额度：图 {len(refs)} > {ARK_LIMIT_IMAGES}")
        if len(ref_video_names(ref_videos)) > ARK_LIMIT_VIDEOS:
            rep.error("G4", f"云端素材额度：视频 {len(ref_videos)} > {ARK_LIMIT_VIDEOS}")
        if len(refs) + len(ref_videos) > ARK_LIMIT_TOTAL_ASSETS:
            rep.error("G4", f"云端素材额度：总素材 {len(refs)+len(ref_videos)} > {ARK_LIMIT_TOTAL_ASSETS}")
        if total > ARK_LIMIT_REF_SECONDS:
            rep.error("G4", f"云端素材额度：参考素材合计 {total:.1f}s > {ARK_LIMIT_REF_SECONDS}s")
    rep.ok("G4", f"槽位/额度核对完成（图 {len(refs)}，参考视频 {len(ref_videos)}，"
                 f"视频原声 {len(ref_video_audios)}，独立音频 {len(ref_audios)}，"
                 f"视频合计约 {total:.1f}s，音频合计约 {audio_total:.1f}s，provider={provider}）")


try:
    import h3_audio_policy as _h3_audio_policy   # 同目录零依赖模块
except ImportError:      # 被人从别的 cwd 引进来时兜底
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent))
    import h3_audio_policy as _h3_audio_policy


def ref_video_names(videos):
    return [Path(v).name for v in videos]


# 读法本身**不在这里定义**：唯一真源是 tools/h3_audio_policy.py（零依赖，面板也能安全引用）。
# 本文件只把它转接进来，并给旧名字留个别名，免得有人还在 `from check_preflight import audio_reading_policy`。
audio_reading_policy = _h3_audio_policy.audio_reading_policy
audio_policy = audio_reading_policy

def _audio_seconds(path):
    """参考音频时长（秒）。soundfile 优先，退回 stdlib wave；取不到返回 None。"""
    p = Path(str(path))
    if not p.is_file():
        return None
    try:
        import soundfile as sf
        info = sf.info(str(p))
        return float(info.frames) / float(info.samplerate or 0 or 1)
    except Exception:
        pass
    try:
        import wave
        with wave.open(str(p), "rb") as w:
            fr, rate = w.getnframes(), w.getframerate()
            return float(fr) / float(rate) if rate else None
    except Exception:
        return None


def g4b_video_tags(rep, prompt, ref_videos):
    """提示词里引用了 <Video N> 却没挂参考视频＝白写；反过来挂了没引用＝白烧时间。"""
    nums = sorted({int(m.group(1)) for m in
                   re.finditer(r"<Video\s*(\d+)>", prompt or "")})
    if nums and not ref_videos:
        rep.error("G4", f"提示词引用 <Video {nums}> 但本次没挂任何参考视频 —— "
                        f"这些引用会被模型当成空素材，行为不可预测")
    for n in nums:
        if n > len(ref_videos):
            rep.error("G4", f"提示词引用 <Video {n}>，但只挂了 {len(ref_videos)} 段参考视频")
    if ref_videos and not nums:
        rep.warn("G4", f"挂了 {len(ref_videos)} 段参考视频，但提示词里没有 <Video N> 引用 —— "
                       f"素材白占额度（实测代价：加一段参考视频多烧约 8 分钟）")


def g7b_character_needs_anchor(rep, prompt, refs, names):
    """铁律：指定角色必须带参考图出脸，纯文字出脸必漂。
       提示词里点了这些角色的名，却一张参考图都没挂 → 拦。"""
    if not names or refs:
        return
    hit = [n for n in names if n and n in (prompt or "")]
    if hit:
        rep.error("G7", f"提示词点名角色 {hit} 却没挂任何参考图 —— 纯文字出脸必漂；"
                        f"要裸跑请清空 config.characters_needing_anchor 并注明是对照实验")


def g5_resolution(rep, w, h):
    if not w or not h:
        rep.error("G5", "缺 width/height")
        return
    if w % 32 or h % 32:
        rep.error("G5", f"{w}x{h} 不是 32 的倍数（VAE 会报尺寸错）")
        return
    tag = f"{w}x{h}"
    portrait = h >= w
    r = (h / w) if portrait else (w / h)          # 长边/短边，方向分开判
    if abs(r - 16 / 9) <= 0.02:
        side = "9:16 竖屏" if portrait else "16:9 横屏"
        if portrait and tag in TRUTH_9_16:
            rep.ok("G5", f"{tag} 是 {side} 且 32 倍数")
        else:
            rep.ok("G5", f"{tag} 比例接近 {side}（非白名单分辨率，留意模型是否支持）")
    else:
        rep.warn("G5", f"{tag} 长短边比 {r:.3f}，既不是 9:16(1.778) 也不是 16:9 —— "
                       f"如 768x1344 实为 4:7，出片会被裁或变形")


def g6_length(rep, length, duration):
    if not length:
        rep.error("G6", "缺 length（帧数）", hard=True)
        return
    if not (H3_MIN_FRAMES <= length <= H3_MAX_FRAMES):
        secs = length / H3_FPS
        official = OFFICIAL_MIN_FRAMES <= length <= OFFICIAL_MAX_FRAMES
        why = []
        if not official:
            why.append(f"官方硬界 4–15s＝{OFFICIAL_MIN_FRAMES}–{OFFICIAL_MAX_FRAMES} 帧"
                       f"（本次 {length} 帧＝{secs:.2f}s）")
        if official:
            why.append(f"官方硬界内（4–15s＝{OFFICIAL_MIN_FRAMES}–{OFFICIAL_MAX_FRAMES} 帧），"
                       f"但超出本机放行界 {H3_MIN_FRAMES}–{H3_MAX_FRAMES}"
                       f"（=官方区间 ∩ T8 的 17n+5 网格；**345/107 是我们的裁定，不是官方数字**）")
        if length == 362:
            why.append("362 帧＝15.08s 超官方 15s，且旧 362 批次已停止用于新批（见 W5c 清单）")
        rep.error("G6", f"length={length} 不放行：" + "；".join(why)
                        + "。要改判据请动 H3_MIN/MAX_FRAMES 并同步 09 号记录，别在提示词里绕。")
        return
    secs = length / H3_FPS
    if duration and abs(secs - float(duration)) > 0.35:
        rep.warn("G6", f"length {length} 帧 = {secs:.2f}s，与期望时长 {duration}s 差 "
                       f"{abs(secs-float(duration)):.2f}s")
    # 107–123：官方允许、本机未训到位 —— 放行但必须留风险字据（B1 裁定第 2 句）
    if length < H3_LOCAL_TRAINED_MIN:
        rep.warn("G6", f"length={length} 在官方区间内但低于本机节点声明的训练下限 "
                       f"{H3_LOCAL_TRAINED_MIN} 帧 ⇒ 属未实测组合，允许提交、结果按实验留痕")
    rep.ok("G6", f"length={length} → {secs:.2f}s @ {H3_FPS}fps")


def _camera_gear_in_prompt(prompt):
    """英文按整词忽略大小写匹配，避免 rig 误中 frigates/bright；支持中英相邻。"""
    return [g for g in CAMERA_GEAR
            if (re.search(r"(?<![A-Za-z0-9_])" + re.escape(g) + r"(?![A-Za-z0-9_])",
                          prompt, re.IGNORECASE | re.ASCII)
                if g.isascii() else g in prompt)]


# 否定引导词：**词表唯一真源＝ `prompt_lint.NEG`**（09-28 起改成 import，不再手抄镜像）。
# 原来这里是独立手写的 25 词，与 NEG 差一个「切忌」——同一句"切忌三脚架入画"在 G7 算禁令句
# （低危）、在词表闸算正面点名（高危）。**同义判据两张词表＝必然漂移**，这正是 R2-07 立的规矩，
# 现在由代码而非注释来保证。底座不在时退回下面的等值镜像，并由 G7 显式 warn 说明本次是兜底判定。
#
# 2026-10-19 Phase 4 补记（实测口径，别把它说重了）：兜底镜像与 NEG 目前**集合完全相同**
#   —— live 37 条 ／ mirror 37 条（26 中 + 11 英）／ set 相等 ／ 双向差集为空。
#   唯一差别是**顺序**（index 27 处 `does not` vs `don't`），而消费点 :572 是
#   `any(b in seg for b in BAN_LEADS)`——纯成员判定，与顺序无关 ⇒ **今天降级不会改判据**。
#   风险是潜伏的：将来给 NEG 补词而忘了同步镜像，才会静默漂。
_BAN_MIRROR = ("不要", "不许", "不可", "禁止", "没有", "去掉", "不出现", "不采用", "不添加",
               "一概不", "无需", "不描述", "看不见", "不露", "不画", "不得", "不准", "不应",
               "不宜", "切勿", "切莫", "严禁", "请勿", "绝不", "绝对不会", "切忌")


def _load_ban_words():
    """**先试 `ban_words`（纯数据，无 I/O、无 chdir），再退回 `prompt_lint`。**

    2026-10-19 Phase 4 改。原来只从 PF_SEARCH_DIRS 里 `import prompt_lint` 拿 NEG，而
    `prompt_lint.py` 是**武昭君仪（wzy）项目**脚本，不是通用底座：
      · `:18` `D = r'D:/AIWorkflow/tmp/wzy'`（写死）
      · `:19` `os.chdir(D)` ← **import 时就改进程工作目录**
      · `:33` `BASELINE = open(D + '/style_baseline.txt')` ← **import 时就读盘**
      · `:31` `STYLE_PROFILE = os.environ.get('WZY_STYLE', ...)` ← 变量名里就写着 WZY
    实测（从 `C:\\` 起进程）：`import check_preflight` 之后 `os.getcwd()` 变成
    `D:\\AIWorkflow\\tmp\\wzy`。⇒ ① 所有 import 了本文件的进程，之后的相对路径都按 tmp\\wzy 解析；
    ② tmp\\wzy 一没，`os.chdir` 与那个 `open()` 都抛 ⇒ 静默落到 `_BAN_MIRROR`，G7 只 warn、闸还是绿的。
    `ban_words.py` 是同一张表的纯数据副本（实测 37 条**逐字同序**，且 import 它不动 CWD），
    把通用闸对项目临时目录的依赖彻底断开。
    🔴 两份不许漂：`tools/check_official_path.py [P9]` 会同时加载两者逐个比对 NEG。
    """
    tools_dir = str(Path(__file__).resolve().parent)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    bw_err = None
    try:
        import ban_words
        return ban_words.NEG_USABLE, None
    except Exception as e:                      # 在却 import 不了，比不在更该喊
        bw_err = "%s 导入失败：%s" % (os.path.join(tools_dir, "ban_words.py"), e)
    for d in PF_SEARCH_DIRS:
        f = Path(d) / "prompt_lint.py" if d else None
        if f and f.is_file():
            if d not in sys.path:
                sys.path.insert(0, d)
            try:
                import prompt_lint
                words = tuple(w for w in prompt_lint.NEG if len(w) >= 2)
                return words, None
            except Exception as e:
                return None, "%s 导入失败：%s（ban_words 也不可用：%s）" % (f, e, bw_err)
    return None, "没找到 prompt_lint.py（查过 %s）；ban_words 也不可用：%s" % (
        " / ".join([x or "(空)" for x in PF_SEARCH_DIRS]), bw_err)


_BAN_EN_MIRROR = ("do not", "don't", "does not", "never ", "no ", "not ", "without", "avoid",
                  "with no", "nor ", "cannot")
_ALL_BAN, BAN_ERR = _load_ban_words()
if not _ALL_BAN:
    _ALL_BAN = _BAN_MIRROR + _BAN_EN_MIRROR
# 中英分家只是**取值方式**，不是第二张表：两侧都从同一份 `prompt_lint.NEG` 切出来。
# 10-03 批 16 之前这里是本文件自有的 8 个英文词，而词表闸那份一个英文词都没有 ⇒
# 同一句 "do not show any tripod" 在 G7 算禁令句、在词表闸算肯定句点名（09-28 那条漂移的英文版）。
BAN_LEADS = tuple(w for w in _ALL_BAN if not w.isascii())
BAN_LEADS_EN = tuple(w for w in _ALL_BAN if w.isascii())
# 句末边界同样并回底座：旧写法只认中文标点，英文正文里"整段"被当成一句，
# 器材词的禁令句判定会管到隔壁句子去。
_SENT_END = tuple(PF.SENT_END_MARKS) if PF is not None else ("。", "！", "？", "；", "\n", ". ", "! ", "? ", "; ")


def _all_gear_in_ban(prompt, gear):
    """这批器材词是不是**只写在禁令句里**（"不出现任何灯具、三脚架…"）。
       是则不算缺陷：本项目的既有纪律是"正面描述点名才高危"。"""
    for g in gear:
        for m in re.finditer(re.escape(g), prompt, re.IGNORECASE if g.isascii() else 0):
            # 句起点一律走底座 `sent_start`（中英标点都算句末）；本地那套 `rfind(...)+1`
            # 在多字符标记（". "）下会把标记的尾巴留在 seg 里，两侧算法不许各写一遍。
            start = PF.sent_start(prompt, m.start()) if PF is not None else \
                max((prompt.rfind(e, 0, m.start()) + len(e) for e in _SENT_END), default=0)
            seg = prompt[max(start, 0):m.start()].lower()
            if not (any(b in seg for b in BAN_LEADS) or any(b in seg for b in BAN_LEADS_EN)):
                return False
    return bool(gear)


def detect_format(prompt):
    """认格式：H3 的骨架/六段一律问格式核心（h3_official_spec），十块/无格式才问底座。

    2026-10-23 W2：H3 分支不再由本文件维护。核心不可用时退回 prompt_format（旧底座），
    并由 G7 显式 error 说明"格式核心不可用"；两者都没有时按 plain 报判不了，不当通过。
    """
    if SPEC is not None:
        fmt = SPEC.detect_format(prompt)
        if fmt:
            return fmt
    t = (prompt or "").strip()
    if not t:
        return "plain"
    if PF is not None:
        fmt = PF.detect(prompt)
        if fmt in ("h3_skeleton", "h3_ref2va"):
            return fmt
    elif any(f in t for f in BASE_FIELDS):
        return "h3_skeleton"
    if BLOCK_CN_RE.search(t):
        return "sd_tenblock"
    return "plain"


# 非空、又不认识、又不是合法泛称 ⇒ 通道**未裁**。这个值不是通道，只是"我不知道"的记号。
CHANNEL_UNADJUDICATED = "未裁"

# ── 10-02 批 4·2b：kind→通道 的归属**改由通道注册表决定**，下面的字面量降级为兜底 ──
# 迁移纪律（＝改现役行为前的三重预验）：注册表推出的三组词表必须与三个字面量**集合相等**才启用；
# 不相等（或表读不到）就用字面量 ⇒ 迁移前的判定逐字不变，差异另由报告显式 warn，不静默换轨。
# 基线：pytest 153 项 ＋ verify_g7_dispatch ＋ prompt_gate 两份输出，改前改后逐字比对。
CHANNELS_REGISTRY_PATH = r"D:\AIWorkflow\engine\channels_registry.json"
_KIND_IMAGE = ("image", "img", "picture", "first_frame", "t2i", "i2i")
_KIND_H3 = ("h3", "h3_i2va", "h3_ref2va", "h3_skeleton", "h3_fl2va", "h3_l2va",
            "h3_t2va", "ref2va", "i2va", "fl2va", "l2va", "t2va")
_KIND_CLOUD = ("cloud", "sd", "seedance", "ark", "kling", "vidu", "hailuo")
# 注册表里的通道 id → 本函数返回的通道名。未映射的（qianwen／jimeng）**不参与路由**，
# 它们的词继续走`未裁`——那是 D7 已裁「暂时不改」的现状，不是遗漏。
_REGISTRY_ID_TO_CHANNEL = {"image_chain": "image", "h3_local": "h3", "cloud_sd": "cloud"}


def _kind_sets_from_registry(path=CHANNELS_REGISTRY_PATH):
    """→ (sets|None, status)。sets = {通道: frozenset(词)}；status 说明用的是表还是兜底。

    路由取 `declared_kind` ＋ **全部** `code_alias_words`（不分 adjudicated 与否）：
    "这个词被归到哪条通道"是**路由事实**，"这条通道该不该共用别人的判据"是**规则裁定**（GAP-C4 登记的
    就是后者未裁）。⇒ 用别名做路由不会把未裁的说成已裁，两者各查各的。
    """
    try:
        with open(path, "rb") as fh:
            reg = json.loads(fh.read().decode("utf-8"))
    except FileNotFoundError:
        return None, {"source": "fallback_literals", "reason": "注册表文件不存在：%s" % path}
    except json.JSONDecodeError as e:
        return None, {"source": "fallback_literals", "reason": "注册表 json 解析失败：%s" % e}
    except Exception as e:
        # ⚠ 单独一档：首版这里写的是 `except Exception` ＋"注册表读不到"，
        #   于是**本模块自己的 bug**（忘了 import io）被伪装成"表缺失、按兜底判"，
        #   看起来像降级运行，实际是代码坏了。⇒ 读文件以外的异常必须标成 code_error，
        #   并在 reason 里带上异常类型，让人一眼看出该修的是脚本不是表。
        return None, {"source": "code_error", "reason": "%s：%s（**这是读表代码自身的问题，不是表缺失**）"
                                   % (type(e).__name__, e)}
    if not isinstance(reg.get("channels"), list) or not reg["channels"]:
        return None, {"source": "fallback_literals", "reason": "注册表没有 channels 段"}
    sets = {v: set() for v in _REGISTRY_ID_TO_CHANNEL.values()}
    for c in reg["channels"]:
        ch = _REGISTRY_ID_TO_CHANNEL.get(c.get("id"))
        if ch is None:
            continue
        for w in c.get("declared_kind") or []:
            sets[ch].add(str(w).strip().lower())
    alias_unadjudicated = []
    for a in reg.get("code_alias_words") or []:
        ch = _REGISTRY_ID_TO_CHANNEL.get(a.get("channel"))
        w = str(a.get("word") or "").strip().lower()
        if ch and w:
            sets[ch].add(w)
            if a.get("adjudicated") is not True:
                alias_unadjudicated.append(w)
    derived = {ch: frozenset(ws) for ch, ws in sets.items()}
    literal = {"image": frozenset(_KIND_IMAGE), "h3": frozenset(_KIND_H3),
               "cloud": frozenset(_KIND_CLOUD)}
    if derived != literal:
        diff = {ch: {"only_in_registry": sorted(derived[ch] - literal[ch]),
                     "only_in_literals": sorted(literal[ch] - derived[ch])}
                for ch in literal if derived[ch] != literal[ch]}
        return None, {"source": "fallback_literals",
                      "reason": "注册表与代码字面量不等 ⇒ 本次仍按字面量判（不静默换轨）",
                      "diff": diff}
    return derived, {"source": "channels_registry", "path": path,
                     "schema_version": reg.get("schema_version"),
                     "alias_words_unadjudicated_routed_anyway": sorted(alias_unadjudicated),
                     "unmapped_channels_not_routed": sorted(
                         c.get("id") for c in reg["channels"]
                         if c.get("id") not in _REGISTRY_ID_TO_CHANNEL)}


KIND_SETS, CHANNEL_REGISTRY_STATUS = _kind_sets_from_registry()
# 生效词表：注册表可用时用注册表的，否则用字面量。两条路径的**集合相等**（上面的 diff 判据），
# 所以路由结果与迁移前逐字一致，区别只在"谁是权威"。
_ACTIVE_KINDS = KIND_SETS if KIND_SETS is not None else {
    "image": frozenset(_KIND_IMAGE), "h3": frozenset(_KIND_H3), "cloud": frozenset(_KIND_CLOUD)}


def channel_of(kind, provider):
    """把 yaml/CLI 的 prompt_kind + provider 归成通道：h3 / cloud / image，或 `未裁`。

    ★10-02 批 4·2b：词表**来自通道注册表**（`channels_registry.json`），代码里的 `_KIND_*` 三元组
    降级为兜底。注册表与字面量不等 / 表读不到 ⇒ 用兜底（判定逐字不变）＋把 `CHANNEL_REGISTRY_STATUS`
    标成 fallback 并让报告显式 warn，**绝不静默换轨**。
    ⚠ 本函数仍然**不裁定**任何通道的归属；未映射的通道（qianwen／jimeng）不进路由，照旧走`未裁`。

    10-02 批1 拆掉了原来那行**无条件**兜底 `return "cloud" if provider in (…) else "h3"`。
    原行为会把"根本不认识的通道词"也悄悄判成 h3，实测代价（不是推测）：
        channel_of('qianwen'|'qwen'|'bailian', 'local') -> h3   千问三个 kind 词全中招
        channel_of('jimeng'  |'dreamina'     , 'local') -> h3   即梦 3 个 kind 词里中 2 个
                                                        （`seedance` 才认）
    ⇒ 通道注册表声明的 kind 与实际认得的 kind 对不上，稿子会被**用错通道的判据**审，
      而且报告里显示成"通道＝h3｜✓"，看着像过了闸。这正是 GAP-C2／C3。
    ⚠ 本函数只负责**不再假装**，它**不裁定**千问/即梦到底算哪条通道 —— 那属风险 28／D7，
      用户裁的是「暂时不改」，所以未裁的处置是"显式记一条、交人工关口"，不是替它定。

    三类输入分开处理：
      ① 具名通道词（下面三个元组里的）→ 显式返回该通道。
      ② 合法泛称 `video` 或空 → 按文档"只定通道不定格式"，由 provider 定 h3/cloud。
         这**不是**假装：`tasks.py` 的 `or "video"` 默认值、`--prompt-kind` 默认值都走这条，
         且 test_gates_phase3 的 C57 用例与"图片流忘声明要 fail loud"用例都依赖它。
      ③ 非空、又不属 ①、也不属 ② → `未裁`。
    """
    k = str(kind or "").strip().lower()
    if k in _ACTIVE_KINDS["image"]:
        return "image"
    if k in _ACTIVE_KINDS["h3"]:
        return "h3"
    if k in _ACTIVE_KINDS["cloud"]:
        return "cloud"
    if k in ("", "video"):
        return "cloud" if str(provider or "").strip().lower() in ("ark", "cloud") else "h3"
    return CHANNEL_UNADJUDICATED



def _g7_body_language(rep, prompt):
    """G7 新增判据（10-03 批 14，用户裁「要建闸」）：官方硬性要求**重写段落用英文**。

    原话三处：`ref-en.txt:5`、`ref-en.txt:217`、`SKILL.md:33`。豁免只有三处——
    `<d>` 内台词／歌词、英文双引号内的画面可见文字（官方 `base-en.txt:146`）、
    逐字首行指令与字段名。判据是**二值**的（有没有非英文字符），不带阈值。
    """
    if PF is None:
        rep.warn("G7", u"正文语言这一条本次**没跑**（格式底座未加载：%s）⇒ 别把它当已通过"
                      % (PF_ERR or u"未知原因"))
        return
    hits = PF.non_english_spans(prompt or u"")
    if not hits:
        return
    sample = u"；".join(u"第 %d 行：%s" % (n, f[:46]) for n, f in hits[:3])
    rep.error("G7", u"重写段落里有 **%d 处非英文字符** —— 官方硬性规定正文用英文"
                    u"（`ref-en:5`「Write all six rewrite sections in English」、`ref-en:217`、`SKILL:33`），"
                    u"只豁免三处：`<d>` 内台词／歌词、英文双引号内的画面可见文字、逐字首行与字段名。"
                    u"前几处：%s ⇒ 两条正路："
                    u"① 把这段改写成英文（**台词仍留原语言**，画内可见文字也留原文）；"
                    u"② 用户点名保留中文（存量中文稿属这一类）——那只能整体关 "
                    u"`config.yaml` 的 `preflight: off`，代价是连 G7 其它判据一起关，"
                    u"且台账 `bypassed` 段会自动留下字据。" % (len(hits), sample))


def _detect_skeleton_mode(prompt):
    """按官方第一行判骨架模式：i2va / fl2va / l2va / t2va；认不出返回 None。

    W2 起直接委托格式核心 `h3_official_spec.detect_skeleton_mode`——
    本文件不再维护第二份首行表，避免与房内闸/对白闸判成不同模式。
    """
    if SPEC is None:
        return None
    return SPEC.detect_skeleton_mode(prompt)


def _g7_skeleton(rep, prompt, kind=None):
    """本地 H3 基础三字段骨架判据：官方逐字首行（按模式四形）+ 恰三字段 + [Shot 1] 正文。

    2026-10-23 W2：首行/字段/槽位的全部判定走 `h3_official_spec.analyze()`（格式核心），
    本函数只负责把结果翻译成 G7 的 error/warn 文案。规则 ID 仍是 G7。

    `kind` 是具体模式时（h3_i2va / h3_fl2va / h3_l2va / h3_t2va）必须与首行一致；
    泛称（h3 / h3_skeleton / video）才只看内容。这样"I2VA 忘首行"不会被误当成合法 T2VA。
    """
    if SPEC is None:
        rep.error("G7", "格式核心 h3_official_spec 不可用（%s）⇒ 骨架判据整段未执行，"
                        "不能当通过" % (SPEC_ERR or "未知原因"))
        return
    a = SPEC.analyze(prompt)
    mode = a["mode"]
    head = (prompt or "").lstrip(u"\ufeff").lstrip()
    want = {"h3_i2va": "i2va", "h3_fl2va": "fl2va",
            "h3_l2va": "l2va", "h3_t2va": "t2va"}.get(str(kind or "").strip().lower())
    if mode is None:
        if want == "t2va" and head.startswith(BASE_FIELDS[0]):
            mode = "t2va"          # 显式声明 T2VA：官方无首行，正文必须直接以三字段开头
        else:
            rep.error("G7", "H3 骨架缺官方首行指令，或首行不是官方四形之一"
                            "（I2VA / FL2VA / L2VA 逐字句式；T2VA 需显式声明 h3_t2va，"
                            "且正文直接以 integrated_multimodal_description: 开头）")
    elif want and want != mode:
        rep.error("G7", f"首行是 {mode.upper()}，但 prompt_kind 声明 {want.upper()} —— "
                        "模式不一致（别把 I2VA 稿塞进 FL2VA 链，反之亦然）")
    elif mode in ("i2va", "fl2va", "l2va"):
        rest = prompt.split("\n", 1)[1] if "\n" in prompt else ""
        if not rest.startswith("\n"):
            rep.error("G7", "官方首行指令后必须空一行再进三字段")
    odd = [f for f in BASE_FIELDS if a["counts"].get(f, 0) != 1]
    if odd:
        rep.error("G7", f"H3 骨架三个基础字段必须各出现恰一次，异常：{odd}")
    elif a["order_ok"] is False:
        rep.error("G7", "H3 骨架三字段顺序错误（integrated_multimodal → overall_soundscape "
                        "→ non_diegetic_music）")
    elif not a["body_start_ok"]:
        rep.error("G7", "H3 骨架正文必须从 [Shot 1] 开始")
    tag = [x for x in REF2VA_ONLY if x in prompt]
    if tag:
        rep.error("G7", f"骨架里混进全参考六段字段 {tag}（基础骨架与 ref2va 互斥，同镜只能走一种）")
    loose = [x for x in ("<Subject", "<Video", "<Audio") if x in prompt]
    if loose:
        rep.error("G7", f"骨架含未挂/不该挂的素材标签 {loose}（基础三字段模式只挂首帧/尾帧图）")
    pics = a["pictures"]
    if mode in ("i2va", "l2va"):
        if pics - {1}:
            rep.error("G7", f"{mode.upper()} 只挂一张图（Picture 1），不允许引用其他 Picture 槽")
    elif mode == "fl2va":
        if pics - {1, 2}:
            rep.error("G7", "FL2VA 只允许 <Picture 1>/<Picture 2>（首帧/末帧）")
        # 首行本身必含 "Picture 2"（官方句式）⇒ 只能查**正文**，不能查整段。
        body = prompt.split("\n", 1)[1] if "\n" in prompt else prompt
        if 2 not in pics and "Picture 2" not in body:
            rep.warn("G7", "FL2VA 正文没提 Picture 2/末帧 —— 官方 §3.2 要求描述两帧之间的路径；"
                           "只写首帧会让尾帧只靠接线生效")
        # W2：FL2VA 官方偏好单镜；多镜可以，但每个切点要显式。**只 warn，不写成官方硬规**
        # （官方硬切点格式由 h3_official_spec F3 判，不在这里升级）。
        miss_cut = [n for n, blk in a["shots"]
                    if n and n > 1 and not re.match(r"^\[Shot\s+\d+\]\s+At\s+\d{2}:\d{2}\.\d{3}", blk)]
        if len([n for n, _ in a["shots"] if n]) > 1 and miss_cut:
            rep.warn("G7", f"FL2VA 多镜缺显式切点 [Shot {miss_cut}] —— 官方偏好单镜；"
                           f"多镜请写 `[Shot N] At MM:SS.mmm`（本机按 warn，不升硬规）")
    elif mode == "t2va":
        if pics:
            rep.error("G7", "T2VA 官方无图对齐首行，正文却引用了 <Picture N>")
    _g7_body_language(rep, prompt)
    _g7_meta_prompt(rep, prompt)


META_PROMPT_PATTERNS = [
    (r"must stay visible", u"元指令：保持可见"),
    (r"zero dead air", u"元指令：无空档"),
    (r"End pose is the next", u"元指令：末帧=下镜"),
    (r"ALL established damage", u"元指令：损伤账本"),
    (r"keep first-frame costumes", u"元指令：保持服装"),
    (r"reframes hard on impacts", u"结果式运镜描述"),
]


def _g7_meta_prompt(rep, prompt):
    """G7 补充（2026-10-08 用户「都做」）：元指令/结果描述不产生画面，只报不拦（R3 §五）。

    与 `lint_prompt_meta.py` 同清单；进 preflight 是为了少忘跑一把。
    """
    import re as _re
    text = prompt or u""
    hits = []
    for pat, why in META_PROMPT_PATTERNS:
        m = _re.search(pat, text, _re.I)
        if m:
            hits.append(u"%s「%s」" % (why, m.group(0)[:40]))
    if hits:
        rep.warn("G7", u"正文含元指令/结果描述 %d 处（不产生画面，移到分镜备忘）：%s"
                 % (len(hits), u"；".join(hits[:4])))


def _g7_ref2va(rep, prompt):
    """本地 H3 全参考六段（ref2va）判据：六段齐、按序、**不写**骨架首行指令。

    真源：`ComfyUI_H3/prompts/official_h3/ref-en.txt` §1/§7。
    """
    if SPEC is not None:
        a = SPEC.analyze(prompt)
        missing, dup, order_ok = a["missing"], a["duplicated"], a["order_ok"]
    else:
        missing = [f for f in REF2VA_FIELDS if f not in prompt]
        dup, order_ok = [], None
    if missing:
        rep.error("G7", f"H3 六段缺字段 {missing} —— 六段缺一即退化为部分参考，模型会自行补戏")
    else:
        if dup:
            rep.error("G7", f"H3 六段字段必须各出现恰一次，重复：{dup}")
        if order_ok is False:
            rep.error("G7", "H3 六段顺序错误，应为 subject_definitions → summary → "
                            "retention_analysis → detailed_description → overall_soundscape "
                            "→ non_diegetic_music")
    if SKELETON_INSTRUCTION in prompt or "integrated_multimodal_description:" in prompt:
        rep.error("G7", "六段里混进基础骨架的逐字指令/字段（ref2va 与骨架互斥）")
    if not re.search(r"<(Picture|Video|Audio|Subject)\s*\d+>", prompt):
        rep.error("G7", "六段没有任何 <Picture N>/<Video N>/<Subject N> 引用 —— 挂了素材却没声明"
                        "职责＝素材当空（白烧额度）")
    _g7_body_language(rep, prompt)
    _g7_meta_prompt(rep, prompt)
    d = prompt.split("detailed_description:", 1)
    if len(d) > 1 and "[Shot" not in d[1].split("overall_soundscape:", 1)[0]:
        rep.warn("G7", "detailed_description 里没有 [Shot N] 分镜段 —— 官方按毫秒切点写拍；"
                       "单拍镜可忽略，多拍镜不写＝模型自己决定切点")


def _g7_tenblock(rep, prompt, blocks_required, provider):
    """云端 SD（Seedance）中文十块判据：核心五块必填，缺块＝模型自行补戏。"""
    blocks_required = list(blocks_required or [])
    missing = [b for b in CORE_BLOCKS if u"【%s】" % b not in prompt]
    if missing:
        rep.error("G7", f"缺核心分块: {missing}（缺任何一块，模型都会自行补戏）")
    absent = [b for b in blocks_required if u"【%s】" % b not in prompt]
    if absent:
        rep.warn("G7", f"十块中未出现: {absent}")
    declared = _parse_slots(prompt)
    nums = sorted({int(m.group(1) or m.group(2))
                   for m in re.finditer(r"(?:<Picture\s*(\d+)>|@图片\s*(\d+))", prompt)})
    if nums and declared:
        rep.ok("G7", f"提示词引用编号 {nums}，身份声明 {len(declared)} 处")
    if u"【镜头】" in prompt:
        seg = prompt.split(u"【镜头】", 1)[1].split(u"【", 1)[0]
        if not re.search(u"(缓|缓缓|推|拉|移|摇|跟|环绕|升|降|静止|固定)", seg):
            rep.warn("G7", "【镜头】段没有运镜时序词 —— r2v 会自己决定机位，通常会平推")


def g7_prompt_format(rep, prompt, blocks_required, provider, kind="video", channel=None):
    """**先认格式，再选判据**。旧写法按 kind/块名直接切判据，四套格式并存后必然错判：
    骨架没有【】⇒ 十块判据静默空过；十块已剥给云端⇒ 套在 H3 上是混用而不是缺块。

    通道（h3/cloud/image）由声明定，格式由内容认；两者对不上就报**混用**，
    而不是挑一套判据硬跑（那正是 2026-09-28 十块剥离要防的事故面）。
    """
    ch = str(channel or channel_of(kind, provider)).lower()
    if CHANNEL_REGISTRY_STATUS.get("source") != "channels_registry":
        # 降级运行：词表来自代码兜底。判定与迁移前逐字一致，但"注册表是权威"这句话此刻不成立 ⇒ 明说。
        rep.warn("G7", f"⚠ 通道词表本次**不是**来自 `channels_registry.json`（"
                       f"{CHANNEL_REGISTRY_STATUS.get('reason')}）⇒ 按代码兜底判，行为与迁移前一致，"
                       f"但这次运行属**降级**：注册表与代码的差异（若有）没生效。"
                       f"差异={CHANNEL_REGISTRY_STATUS.get('diff') or '无'}")
    fmt = detect_format(prompt)
    if ch == CHANNEL_UNADJUDICATED:
        # 通道没裁过 ⇒ 不跑格式判据（跑哪套都是错的），也**不打 ✓**——
        # 打 ✓ 就等于替未裁的通道背书，正是原来那行无条件兜底的病。
        # 记 warn 不记 error：拦停等于替 D7 把"未裁"悄悄裁成"不许走"，那越权了。
        rep.warn("G7", f"通道未裁（prompt_kind={str(kind or '').strip()!r} 不属任何已登记通道，"
                       f"也不是合法泛称 video／空）⇒ **G7 格式判定整段未执行**，内容识别到的 "
                       f"{FMT_LABEL.get(fmt, fmt)} 没有被任何判据核过。"
                       f"这一条不算通过：请走人工关口放行并在报告里留痕，"
                       f"或把该通道登记进通道注册表后再跑。"
                       f"（provider={str(provider or '').strip()!r}；未裁定属风险 28／D7，"
                       f"闸本身无权替你裁）")
        return
    if PF is None:
        rep.warn("G7", f"格式底座 prompt_format 未加载（{PF_ERR}）⇒ 本次走内置兜底判定，"
                       f"混用面可能漏报")
    if ch == "h3" and SPEC is None:
        # 格式核心不在＝三道闸会各判各的。宁可红，不静默退回第二份表。
        rep.error("G7", f"格式核心 h3_official_spec 不可用（{SPEC_ERR}）⇒ "
                        f"H3 首行/字段/模式判定不能执行，本次不放行")
    if BAN_ERR:
        rep.warn("G7", f"否定词表 prompt_lint.NEG 未加载（{BAN_ERR}）⇒ 器材名词的「禁令句」"
                       f"判定走等值镜像，可能已与词表闸漂移")
    rep.ok("G7", f"通道＝{ch}｜内容识别为 {FMT_LABEL.get(fmt, fmt)}")

    if ch == "image":
        # 图片（首帧/定妆）没有格式标准，只查"会被实体化/字面化"这类共性坑
        if fmt != "plain":
            rep.warn("G7", f"图片稿套用了视频格式（{FMT_LABEL.get(fmt)}）—— 图片口径不要求分块/字段")
    elif FMT_CHANNEL[fmt] != ch:
        hit = u"、".join(u"【%s】" % b for b in BLOCK_CN_RE.findall(prompt)[:6])
        if fmt == "sd_tenblock" and ch == "h3":
            rep.error("G7", f"混用：中文十块模板出现在本地 H3 视频提示词里（命中块名：{hit}）。"
                            "十块自 2026-09-28 起只属云端 SD 通道"
                            "（真源 ComfyUI_H3/云端SD提示词模板_十块.md）；"
                            "A/B 实测十块写法 4/5 条把元叙述当台词念出乱码，官方骨架 0/5"
                            "（脚本 wzy/ab_tenblock.py）⇒ 改写成官方骨架，不要指望放宽判据")
        elif fmt == "plain" and ch == "h3":
            rep.error("G7", "本地 H3 视频提示词认不出格式：既无官方三字段也无六段指纹"
                            "（也没有中文块名）⇒ 报判不了，不当通过。"
                            "若这其实是**图片**稿，请显式声明 prompt_kind: image"
                            "（图片口径无格式要求）")
        elif fmt == "plain" and ch == "cloud":
            rep.error("G7", "云端 SD 视频稿没有中文分块：该通道唯一格式＝十块模板"
                            f"（必填核心五块 {list(CORE_BLOCKS)}）")
        else:
            rep.error("G7", f"混用：{FMT_LABEL.get(fmt, fmt)} 不该出现在 {ch} 通道提示词里")
    else:
        if fmt == "h3_skeleton":
            _g7_skeleton(rep, prompt, kind=kind)
        elif fmt == "h3_ref2va":
            _g7_ref2va(rep, prompt)
        elif fmt == "sd_tenblock":
            _g7_tenblock(rep, prompt, blocks_required, provider)
    if PF is not None:
        # 通道与格式对不上时，上面那条带出处的混用条已经说清了（含块名），不再叠一条泛化条；
        # 这里收的是"格式内部残留另一套指纹"（如骨架正文里还留着【镜头】块名）这类补漏。
        mix = ([] if ch != "image" and FMT_CHANNEL[fmt] != ch
               else list(PF.mixing(prompt, want=ch)))
        if ch == "cloud" and fmt == "sd_tenblock":
            # 缺块由 _g7_tenblock 报（带"会自行补戏"的处置口径），别在这里重复一遍
            mix = [m for m in mix if not m.startswith(u"缺核心分块")]
        for msg in mix:
            (rep.warn if ch == "image" else rep.error)("G7", f"混用：{msg}")

    gear = _camera_gear_in_prompt(prompt)
    if gear:
        in_ban = _all_gear_in_ban(prompt, gear)
        if ch == "h3" or not in_ban:
            # H3 视频层：**禁令即在点名**（09-22 与 09-26 两轮实测：写"不要武器"真画出手枪、
            # 写"不出现枪"反把缠布长杆渲成子弹）⇒ 即使只写在"不要X"里也照拦，不豁免。
            rep.error("G7", f"提示词出现运镜器材名词 {gear} —— 会被实体化渲进画面"
                            + ("（本次只出现在禁令句里，但 H3 上禁令即在点名，仍拦）"
                               if in_ban and ch == "h3" else ""))
        else:
            # 图片／云端通道：否定式**实测有效**（R2-06），器材词只在禁令句里出现 ⇒ 降 warn。
            # 出处＝四批定妆实测原句「画面里**不出现任何**灯具、灯架、柔光箱、三脚架、支架或器材」，
            # 那四批人审结论里没有任何一张长出器材；正面描述里写器材词仍然是 error（上面那条分支）。
            rep.warn("G7", f"器材名词 {gear} 只写在禁令句里（图片/云端通道否定式实测有效）"
                           "⇒ 降 warn；但若改写成正面描述（如「用三脚架固定」）会立刻变 error")
    if any(k in prompt for k in SILENT_ROLE):
        if not all(k in prompt for k in SILENT_REQUIRED):
            rep.error("G7", "声明了哑女/无声角色，但没写全「全程不出声、不张嘴」—— 会被开口")
    risk = [w for w in LITERAL_RISK if w in prompt]
    if risk:
        rep.warn("G7", f"字面化风险词 {risk} —— 历史案例：『蝶形双翼』被渲成真实蝴蝶翅膀")
    if ch != "image" and len(prompt) < 120:
        rep.warn("G7", f"提示词仅 {len(prompt)} 字，像是占位/验证用的，正式出片请换定稿")
    if prompt.strip() == "None":
        rep.error("G7", "提示词是字面量 None（历史上真出过这事故）")



def g8_environment(rep, lora, workflow_json, lora_dir, check_service, base_url):
    if lora:
        lp = Path(lora)
        cand = lp if lp.is_absolute() else Path(lora_dir) / lora
        if not cand.is_file():
            rep.error("G8", f"LoRA 文件不存在: {cand}")
        elif "ref2va" in str(workflow_json or "") and "ref2v" not in lora:
            rep.error("G8", f"ref2va 通道挂了非 ref2v LoRA（{lora}）—— fl2v LoRA 不能混用")
        else:
            rep.ok("G8", f"LoRA 就位: {cand.name}")
    if check_service:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{base_url}/system_stats", timeout=5) as r:
                ok = json.loads(r.read().decode())
            rep.ok("G8", f"ComfyUI 存活 {base_url}（{len(ok.get('agents', []))} 个实例）")
        except Exception as e:
            rep.error("G8", f"ComfyUI {base_url} 不在线: {type(e).__name__} —— 引擎会自动拉起，"
                            f"但若拉起失败你会白等，建议先手动确认")
    free = _disk_free(Path(workflow_json).parent if workflow_json else Path(__file__).parent)
    if free is not None and free < 2:
        rep.error("G8", f"磁盘剩余 {free:.1f} GB，出片随时写满")
    elif free is not None:
        rep.ok("G8", f"磁盘剩余 {free:.1f} GB")


def _disk_free(p: Path):
    try:
        q = p
        while not q.exists() and q != q.parent:
            q = q.parent
        return shutil_disk_usage(str(q))[2] / 1e9
    except Exception:
        return None


def shutil_disk_usage(path):
    import shutil
    return shutil.disk_usage(path)


def g12_duplicate(rep, prompt, refs, seed, pool_root):
    """查历史台账里有没有同一条提示词已经出过片（逐条比对 prompt 文本，不靠子串）。"""
    if not pool_root or not Path(pool_root).is_dir() or not prompt.strip():
        return
    target = prompt.strip()
    hits, scanned = [], 0
    for mf in Path(pool_root).rglob("*.manifest.json"):
        scanned += 1
        if scanned > 600:
            rep.warn("G12", f"台账扫描到 {scanned} 份就停了（上限保护），去重结论可能不全")
            break
        try:
            data = json.loads(mf.read_text(encoding="utf8"))
        except Exception:
            continue
        for entry in data.get("images", []):
            if str(entry.get("prompt", "")).strip() == target:
                hits.append(f"{mf.parent.name}/{entry.get('file') and Path(str(entry['file'])).name}")
                break
    if hits:
        rep.warn("G12", f"这条提示词历史上已出过片，先确认是不是要重跑: {hits[:4]}")


def g11_project(rep, output_root, project, aliases, theme, batch_id):
    """落点校验：交付根必须由 project 派生；主题里出现别的项目代号＝串项目。
       历史案例：config 的 output_root 还写着 无音\\批次，仙戮四条就落进了无音批次夹。"""
    if not output_root:
        rep.error("G11", "没有 output_root，产物无处归档")
        return
    parts = [str(x) for x in Path(str(output_root)).parts]
    if project and project not in parts:
        rep.error("G11", f"交付根 {output_root} 的项目段不含当前项目「{project}」——"
                         f"config 里 output_root 与 project 不一致，产物会落进别的项目夹")
        return
    hay = f"{theme or ''} {batch_id or ''}".lower()
    hit_proj = None
    for proj, toks in (aliases or {}).items():
        if any(str(t).lower() in hay for t in (toks or [])):
            hit_proj = proj
            break
    if hit_proj and project and hit_proj != project:
        rep.error("G11", f"主题/批次带项目代号「{hit_proj}」，但当前 project 是「{project}」，"
                         f"落点 {output_root} —— 串项目了，改 --project 或改主题")
    else:
        rep.ok("G11", f"落点 {output_root}")


def g13_run_decisions(rep, rd):
    """运行决定留痕（10-02 裁定①②＋F1/F5）。**只查留痕，不查值**。

    必填槽是 `engine/channels_registry.json` 的 `run_slots` 现推出来的，本函数不存副本。
    三条判据，全在「有没有人给过」这一层：
      1) 必填槽每一个都得有人给——缺即 error（空槽即拦，机器不代填）；
      2) 值的来路只能是 `sheet`（项目决定单里人填的）或 `args`（这批显式传的）；
         出现第三种来路＝有代码在兜底填默认 ⇒ error，这条是防将来从内部掏空留痕机制；
      3) 决定单本身读不出（缺／坏／项目未登记）⇒ error，不静默退成「这次没有必填槽」。
    ⚠ 本闸**长不出**「这个值看起来不合理」这类判据：审美、画风、档位与要不要音频是人的活，
      机器在这一维是瞎的（R4-08 同一条）。要加值判据＝改规则，得走元规则 M1（事实证据＋人点头）。
    """
    if rd is None:
        rep.error("G13", "调用方没给决定单上下文，却被要求跑 G13 ⇒ 接线坏了。"
                         "这里不退回「当成没有必填槽」，那是假通过")
        return
    errs = list(rd.get("errors") or [])
    if rd.get("error"):
        errs.append(rd["error"])
    for e in errs:
        rep.error("G13", str(e))
    labels = rd.get("slot_labels") or {}
    required = [str(x) for x in (rd.get("required") or [])]
    if not required:
        if not errs:
            rep.error("G13", "必填槽清单为空——注册表 run_slots 空了或没读到，"
                             "这不是「都不用问」。G13 拒绝在空清单上放行")
        return
    values = rd.get("values") or {}
    sources = rd.get("sources") or {}
    missing = [str(x) for x in (rd.get("missing") or [])]
    if missing:
        rep.error("G13", "这批有 %d 个必填槽没人给值 ⇒ 拦（空槽即拦，机器不代填）：\n"
                         "%s\n"
                         "        两种给法都由你本人给——本批临时值：run.py --set 槽=值"
                         "（裸自审用 --decision 槽=值）；\n"
                         "        项目级的落进决定单：python %s set <项目> 槽 <值> --by human"
                         % (len(missing),
                            "\n".join("        · %s（%s）" % (s, labels.get(s, s))
                                      for s in missing),
                            Path(__file__).resolve().parent.parent
                                 / "engine" / "decision_sheet.py"))
    for slot, src in sorted(sources.items()):
        if src not in ("sheet", "args"):
            rep.error("G13", "槽「%s」的值来路是「%s」，不是人给的（只认 sheet/args）"
                              "⇒ 有代码在代填，请查 decision_sheet.collect" % (slot, src))
    stray = sorted(set(values) - set(required))
    if stray:
        rep.warn("G13", "单/参数里有注册表没声明的键：%s ⇒ 只报不拦（可能是漂了的旧槽名），"
                        "但机器不会采用它" % "、".join(stray))
    for slot in (rd.get("ignored_in_sheet") or []):
        rep.warn("G13", "决定单里存了运行级槽「%s」（%s）的值，**不会被采用**——"
                        "运行级每批重新给（10-02 你划的分界）" % (slot, labels.get(slot, slot)))
    for slot in (rd.get("rejected_args") or []):
        rep.error("G13", "这批按批传了项目级槽「%s」（%s）⇒ 项目级改动要用户明确指定并落回决定单，"
                         "不走 --set 顺手改（10-02 裁定：常用画幅这类属项目级）"
                         % (slot, labels.get(slot, slot)))
    # 值在 args 里，但来源是 **yaml 的流级默认**（人这批没动过）⇒ 不算这批的决定。
    # 不拦这一条，`use_llm_polish: false` 这种写在 yaml 里的默认就会冒充"你决定过这批不润色"，
    # 而裁定是运行级每批重新确认。
    for slot in (rd.get("inherited_defaults") or []):
        rep.error("G13", "槽「%s」（%s）这次只有 yaml 里的流级默认值，没有你这批显式给的 ⇒ 不算决定。"
                          "要过闸请本批明确给一个值（--set %s=<值>）"
                  % (slot, labels.get(slot, slot), slot))
    if rd.get("explicit_marker") == "absent":
        rep.warn("G13", "调用方没传「这批显式给过哪些键」的清单 ⇒ 只能按"
                        "「参数里存在就算给」处理，**流级默认可能被当成人的决定**。"
                        "真出片走引擎（run.py）时这条清单是齐的，只有裸 CLI 会降级")
    # 同一个决定在现役 yaml 里有两个键名（润色＝use_llm_polish／use_llm，10-02 实测登记在表里）：
    # 任一个都算人给过；**两个都给且值不同**不挑一个用，报出来让人当场定一个。
    for rec in (rd.get("conflicting_aliases") or []):
        rep.error("G13", "槽「%s」（%s）这批同时给了多个写法且值不一致：%s ⇒ 不许静默挑一个，"
                         "请只留一个（现役别名登记在 channels_registry.run_slots[].accepts）"
                         % (rec.get("slot"), labels.get(str(rec.get("slot")), ""),
                            ", ".join("%s=%s" % kv for kv in sorted(
                                (rec.get("given") or {}).items()))))
    for slot, alias in sorted((rd.get("alias_used") or {}).items()):
        rep.warn("G13", "槽「%s」这批是用别名「%s」给的（现役两个键名之一）⇒ 认，"
                        "但台账里存的是正名" % (slot, alias))
    given = sorted(set(required) - set(missing))
    if not missing and not rd.get("rejected_args") and not errs:
        n_sheet = len([s for s in given if sources.get(s) == "sheet"])
        n_args = len([s for s in given if sources.get(s) == "args"])
        rep.ok("G13", "必填 %d 槽都有人给过（单里 %d／本批参数 %d）；"
                      "值本身好坏不由本闸判" % (len(required), n_sheet, n_args))


# ---------------- 编排 ----------------
ALL_GATES = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G11", "G12", "G13"]


def run_checks(spec, rep=None):
    """spec.only 可指定子集（引擎侧默认不跑 G12 全池扫描——每次出片扫几百份台账不值当，
       G8 服务探活引擎自己会拉服务）。

    ⚠ 10-02 用户裁定：**G11 进默认子集**。
      先更正一句事实：这跟"G11 以前不跑"无关——带 `auto_gates` 的 yaml 全都显式含 G11
      （份数以 `scan_system.py` 现扫为准，本注释不抄计数）。
      本兜底列表只在**没传 `only`** 时生效，也就是裸 CLI、`run_h3.py` 这类直接调用。
      以前它悄悄不跑 G11 ⇒ 直接敲命令行自审的人会以为落点核过了，其实没有。
      这正是要堵的洞：**error 级关口不该因为调用方式不同而消失**。

    ⚠ G13 不在**本函数**的默认子里，但在**引擎侧**（`engine/tasks.py`）的默认子里。
      理由不是"它可选"，是分工：本文件的裸 CLI 只自审一条提示词，没有批次与决定单上下文，
      在这里默认跑 G13 只会把自审工具变成必须先有单；真出片的路径一律经由引擎，
      引擎那边 G13 是默认开的 ⇒ 会产出媒体的流没有一条绕得开。
      要在这里试它：`--only G13 --decision slot=value --project <代号>`。
    """
    rep = rep or Report()
    sel = set(spec.get("only") or ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G11"])
    refs = [str(x) for x in (spec.get("refs") or [])]
    ref_videos = [str(x) for x in (spec.get("ref_videos") or [])]
    prompt = spec.get("prompt") or ""
    provider = spec.get("provider", "local")
    if "G1" in sel:
        # W4c：参考音频也是"会进提交的文件"，存在性与空文件检查不能只覆盖图和视频
        g1_files(rep, refs, list(ref_videos) + list(spec.get("ref_audios") or [])
                 + list(spec.get("ref_video_audios") or []))
    if "G2" in sel:
        g2_md5_slots(rep, refs, ref_videos)
    if "G3" in sel:
        g3_identity(rep, prompt, refs, spec.get("slot_labels") or {})
    if "G4" in sel:
        # W1c：可选首尾帧模板的真实槽位由模式决定。优先用显式 input_mode，
        # 其次按声明的 prompt_kind，最后才退回首行判出的骨架模式。
        _kf = (str(spec.get("input_mode") or "").strip().lower()
               or {"h3_t2va": "t2va", "h3_i2va": "i2va", "h3_l2va": "l2va",
                   "h3_fl2va": "fl2va"}.get(str(spec.get("prompt_kind") or "").lower())
               or _detect_skeleton_mode(prompt))
        g4_slots_and_quota(rep, refs, ref_videos, spec.get("workflow_json"), provider,
                           spec.get("duration"),
                           channel=channel_of(spec.get("prompt_kind"), provider),
                           keyframe_mode=_kf,
                           ref_audios=spec.get("ref_audios") or [],
                           ref_video_audios=spec.get("ref_video_audios") or [])
        g4b_video_tags(rep, prompt, ref_videos)
    if "G5" in sel:
        g5_resolution(rep, spec.get("w"), spec.get("h"))
    if "G6" in sel:
        g6_length(rep, spec.get("length"), spec.get("duration"))
    if "G7" in sel:
        if str(spec.get("characters", "")).lower() == "none":
            pass   # 图片流明确放行裸文字（锁脸在 i2i 锚点那条链把守）
        else:
            g7b_character_needs_anchor(rep, prompt, refs, spec.get("characters") or [])
        if prompt:
            g7_prompt_format(rep, prompt, spec.get("blocks") or TEN_BLOCKS, provider,
                             kind=str(spec.get("prompt_kind") or "video"),
                             channel=spec.get("channel"))
        else:
            rep.error("G7", "没有提示词可校验")
    if "G8" in sel:
        g8_environment(rep, spec.get("lora"), spec.get("workflow_json"),
                       spec.get("lora_dir") or r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\models\loras",
                       bool(spec.get("check_service")),
                       spec.get("base_url") or "http://127.0.0.1:8189")
    if "G11" in sel:
        g11_project(rep, spec.get("output_root"), spec.get("project"),
                    spec.get("project_aliases"), spec.get("theme"), spec.get("batch_id"))
    if "G13" in sel:
        g13_run_decisions(rep, spec.get("run_decisions"))
    if "G12" in sel and spec.get("pool_root"):
        g12_duplicate(rep, prompt, refs, spec.get("seed"), spec["pool_root"])
    return rep


def main():
    ap = argparse.ArgumentParser(description="H3 出片跑前自审闸 G1–G8 + G12")
    ap.add_argument("--prompt-file")
    ap.add_argument("--prompt")
    ap.add_argument("--refs", default="", help="逗号分隔，顺序＝<Picture N> 编号")
    ap.add_argument("--ref-video", action="append", default=[])
    ap.add_argument("--slot-label", default="", help="如 1=薇拉,2=白玖璃")
    ap.add_argument("--w", type=int)
    ap.add_argument("--h", type=int)
    ap.add_argument("--length", type=int)
    ap.add_argument("--duration", type=float)
    ap.add_argument("--steps", type=int)
    ap.add_argument("--seed")
    ap.add_argument("--lora")
    ap.add_argument("--workflow-json")
    ap.add_argument("--provider", default="local", choices=["local", "ark"])
    ap.add_argument("--prompt-kind", dest="prompt_kind", default="video",
                    help="声明提示词种类/通道：video / h3_i2va / h3_ref2va / image。"
                         "格式本身不再靠这个猜——G7 先按内容认格式，此参数只定通道")
    ap.add_argument("--channel", choices=["h3", "cloud", "image"],
                    help="显式指定通道，覆盖由 prompt-kind/provider 推出的结果")
    ap.add_argument("--base-url", default="http://127.0.0.1:8189")
    ap.add_argument("--pool-root", default=r"E:\图像影音资源池")
    ap.add_argument("--only", default="", help="只跑这些闸，逗号分隔，如 G1,G2,G3,G11")
    ap.add_argument("--theme")
    ap.add_argument("--batch-id", dest="batch_id")
    ap.add_argument("--project")
    ap.add_argument("--output-root", dest="output_root")
    ap.add_argument("--aliases", help="项目代号表 JSON 或 JSON 文件，如 {\"仙戮\":[\"xianlu\"]}")
    ap.add_argument("--decision", dest="decisions", action="append", default=[],
                    metavar="槽=值",
                    help="本批由人给定的运行级值，如 --decision prompt_polish=false"
                         "（可重复；G13 用。项目级槽不吃这个参数，要走决定单）")
    ap.add_argument("--check-service", action="store_true")
    ap.add_argument("--strict", action="store_true", help="警告也按失败处理")
    ap.add_argument("--json", help="把结构化结果写到这个文件")
    a = ap.parse_args()

    prompt = ""
    if a.prompt_file:
        p = Path(a.prompt_file)
        if not p.is_file():
            print(f"[G1] 提示词文件不存在: {p}", file=sys.stderr)
            return 2
        prompt = p.read_text(encoding="utf8", errors="replace")
    elif a.prompt:
        prompt = a.prompt

    slot_labels = {}
    for tok in filter(None, (x.strip() for x in a.slot_label.split(","))):
        if "=" in tok:
            k, v = tok.split("=", 1)
            try:
                slot_labels[int(k)] = v.strip()
            except ValueError:
                print(f"--slot-label 格式错: {tok}", file=sys.stderr)
                return 2

    aliases = {}
    if a.aliases:
        src = a.aliases
        if Path(src).is_file():
            src = Path(src).read_text(encoding="utf8")
        try:
            aliases = json.loads(src)
        except Exception as e:
            print(f"--aliases 不是合法 JSON: {e}", file=sys.stderr)
            return 2

    spec = {"prompt": prompt, "refs": [x.strip() for x in a.refs.split(",") if x.strip()],
            "ref_videos": a.ref_video, "slot_labels": slot_labels,
            "prompt_kind": a.prompt_kind, "channel": a.channel,
            "w": a.w, "h": a.h, "length": a.length, "duration": a.duration,
            "lora": a.lora, "workflow_json": a.workflow_json, "provider": a.provider,
            "seed": a.seed, "base_url": a.base_url, "pool_root": a.pool_root,
            "check_service": a.check_service,
            "only": [x.strip().upper() for x in a.only.split(",") if x.strip()] or None,
            "theme": a.theme, "batch_id": a.batch_id,
            "output_root": a.output_root, "project": a.project,
            "project_aliases": aliases}

    # G13 要的「决定单上下文」由 engine/decision_sheet.collect 现拼——本文件不再实现第二套取值
    if "G13" in (spec["only"] or []):
        decisions = {}
        for tok in (a.decisions or []):
            if "=" not in tok:
                print(f"--decision 格式错（要 槽=值）: {tok}", file=sys.stderr)
                return 2
            k, v = tok.split("=", 1)
            decisions[k.strip()] = v.strip()
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
            import yaml
            from decision_sheet import collect
            cfg_p = Path(__file__).resolve().parent.parent / "engine" / "config.yaml"
            cfg = yaml.safe_load(cfg_p.read_text(encoding="utf8")) or {}
            spec["run_decisions"] = collect(cfg, a.project or cfg.get("project"),
                                            decisions, list(decisions))
        except Exception as e:
            spec["run_decisions"] = {
                "errors": ["决定单模块读不出（%s: %s）⇒ G13 不给放行" % (type(e).__name__, e)]}
    rep = run_checks(spec)
    print(rep.render())
    if a.json:
        Path(a.json).write_text(json.dumps(
            {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
             "errors": [list(i) for i in rep.errors],
             "warns": [list(i) for i in rep.warns],
             "items": [list(i) for i in rep.items]}, ensure_ascii=False, indent=2),
            encoding="utf8")
    if rep.errors:
        return 1
    if a.strict and rep.warns:
        print("--strict：存在警告，按失败处理", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
