#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""跑前自审闸 G1–G8 + G12（本地 H3 出片链）

定位：纯算术 / 纯字符串 / 纯文件属性的判定。**不含任何模型意见**——
"好不好/像不像"这类需要人判断的，一律不在这里，走人工关口（H）。

设计动因（实测）：2026-09-18 连跑四条 H3（每条 7 分 25–42 秒）全部作废，
根因是 ref_images 槽位配错——同一张图占多个槽、三条声明"薇拉"的镜挂的全是
白玖璃。那是 G2/G3 一次就能拦住的错误。

用法（独立命令行）：
  py check_preflight.py --prompt-file P.txt --refs A.png,B.png,C.png,D.png \
      --w 864 --h 1536 --length 124 --steps 8 --seed 42 \
      [--lora xxx.safetensors] [--ref-video V.mp4] [--slot-label 1=薇拉,2=白玖璃] \
      [--duration 5.2] [--provider local|ark] [--check-service] [--strict] [--json out.json]

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
H3_MIN_FRAMES = 124            # H3 训练区间约 124–362 帧 @24fps
H3_MAX_FRAMES = 362
H3_FPS = 24
REF_VIDEO_MIN_FRAMES = 48      # ref_videos 吃 IMAGE 帧序列的区间
REF_VIDEO_MAX_FRAMES = 360
REF_VIDEO_ALIGN = "17n+5"      # 参考帧按 17n+5 截齐（102 → 90）
TRUTH_9_16 = {"576x1024", "864x1536", "288x512", "1152x2048"}   # 9:16 且 32 倍数
ARK_LIMIT_IMAGES, ARK_LIMIT_VIDEOS, ARK_LIMIT_AUDIOS = 30, 10, 10
ARK_LIMIT_TOTAL_ASSETS, ARK_LIMIT_REF_SECONDS = 50, 30.0

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

FACE_MIN_PX = 300              # 经验阈值：低于此不宜当"脸锚"（启发式，警告级，非硬界）
YUNET_ONNX = r"D:\AIWorkflow\models\face\face_detection_yunet_2023mar.onnx"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


class Report:
    def __init__(self):
        self.items = []          # (level, gate, text)

    def ok(self, gate, text):
        self.items.append(("ok", gate, text))

    def warn(self, gate, text):
        self.items.append(("warn", gate, text))

    def error(self, gate, text):
        self.items.append(("error", gate, text))

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


def _slot_count_in_template(workflow_json: Path):
    """模板里 __REFn__ 占位符个数 = 引擎真实能吃的参考图槽位数。"""
    try:
        txt = Path(workflow_json).read_text(encoding="utf8")
    except Exception:
        return None
    return len(set(re.findall(r"__REF(\d+)__", txt)))


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
        rep.error("G1", f"锚点缺失 {len(missing)} 个: {missing}")
    if empty:
        rep.error("G1", f"锚点是 0 字节: {empty}")
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
       没有这张卡时，G3 只能靠文件名猜，猜不到就交人工。"""
    cand = Path(str(p) + ".anchor.json")
    if not cand.is_file():
        cand = p.with_suffix(".anchor.json")
        if not cand.is_file():
            return None
    try:
        return json.loads(cand.read_text(encoding="utf8"))
    except Exception:
        return None


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


def g4_slots_and_quota(rep, refs, ref_videos, workflow_json, provider, duration):
    if workflow_json:
        slots = _slot_count_in_template(Path(workflow_json))
        if slots is None:
            rep.warn("G4", f"读不到模板 {workflow_json}，无法核对参考图槽位数")
        elif len(refs) > slots:
            rep.error("G4", f"挂了 {len(refs)} 张图，但模板只有 {slots} 个 __REFn__ 槽 —— "
                            f"多出的会被静默丢弃（引擎按 __REFi__ 逐个替换，第 {slots+1} 张无处可去）")
        elif len(refs) < slots:
            rep.error("G4", f"模板有 {slots} 个槽，只挂 {len(refs)} 张 —— "
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
        if n < REF_VIDEO_MIN_FRAMES or n > REF_VIDEO_MAX_FRAMES:
            rep.error("G4", f"参考视频 {p.name} 帧数 {n}（{fps:.1f}fps）不在 "
                            f"{REF_VIDEO_MIN_FRAMES}–{REF_VIDEO_MAX_FRAMES} 区间")
        if kept and kept < n:
            rep.warn("G4", f"参考视频 {p.name} {n} 帧按 {REF_VIDEO_ALIGN} 截到 {kept} 帧，"
                           f"丢 {n-kept} 帧（约 {(n-kept)/(fps or H3_FPS):.2f}s 的收尾动作）")
        secs = n / (fps or H3_FPS)
        total += secs
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
                 f"视频合计约 {total:.1f}s，provider={provider}）")


def ref_video_names(videos):
    return [Path(v).name for v in videos]


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
        rep.error("G6", "缺 length（帧数）")
        return
    if not (H3_MIN_FRAMES <= length <= H3_MAX_FRAMES):
        rep.error("G6", f"length={length} 不在训练区间 {H3_MIN_FRAMES}–{H3_MAX_FRAMES} 帧")
        return
    secs = length / H3_FPS
    if duration and abs(secs - float(duration)) > 0.35:
        rep.warn("G6", f"length {length} 帧 = {secs:.2f}s，与期望时长 {duration}s 差 "
                       f"{abs(secs-float(duration)):.2f}s")
    rep.ok("G6", f"length={length} → {secs:.2f}s @ {H3_FPS}fps")


def _camera_gear_in_prompt(prompt):
    """英文按整词忽略大小写匹配，避免 rig 误中 frigates/bright；支持中英相邻。"""
    return [g for g in CAMERA_GEAR
            if (re.search(r"(?<![A-Za-z0-9_])" + re.escape(g) + r"(?![A-Za-z0-9_])",
                          prompt, re.IGNORECASE | re.ASCII)
                if g.isascii() else g in prompt)]


def g7_prompt_format(rep, prompt, blocks_required, provider, kind="video"):
    if kind in ("h3_i2va", "video"):
        # 官方 base-en 首帧模式：不能套中文十块，也不能当普通图片无格式放行。
        # 2026-09-28 变更：**十块模板已移出 H3**（改为云端 SD/Seedance 专用格式，见
        # ComfyUI_H3/云端SD提示词模板_十块.md）。A/B 实测：十块写法 4/5 条出现乱码、
        # 官方骨架 0/5（脚本 wzy/ab_tenblock.py）。故 video 与 h3_i2va 同判据。
        instruction = ("For the target video, at 0.00 seconds into the target video, "
                       "<Picture 1> (from [Shot 1]) is fully referenced.")
        fields = ("integrated_multimodal_description:", "overall_soundscape:",
                  "non_diegetic_music:")
        if not prompt.startswith(instruction + "\n\n"):
            rep.error("G7", "H3 I2VA 缺官方首帧指令或空行")
        if not all(prompt.count(field) == 1 for field in fields):
            rep.error("G7", "H3 I2VA 必须恰有三个基础字段")
        elif [prompt.index(f) for f in fields] != sorted(prompt.index(f) for f in fields):
            rep.error("G7", "H3 I2VA 三字段顺序错误")
        elif not prompt.split(fields[0], 1)[1].lstrip().startswith("[Shot 1]"):
            rep.error("G7", "H3 I2VA 正文必须从 [Shot 1] 开始")
        if any(x in prompt for x in ("subject_definitions:", "retention_analysis:",
                                     "<Subject", "<Video", "<Audio")):
            rep.error("G7", "H3 I2VA 含全参考格式或未挂素材标签")
        if any(int(n) != 1 for n in re.findall(r"<Picture\s*(\d+)>", prompt)):
            rep.error("G7", "H3 I2VA 只挂首帧，不允许引用其他 Picture 槽")
        gear = _camera_gear_in_prompt(prompt)
        if gear:
            rep.error("G7", f"提示词出现运镜器材名词 {gear} —— 会被实体化画进画面")
        return
    if kind != "video":
        # 图片提示词没有十块标准，只查"会被实体化/字面化"这类共性坑
        gear = _camera_gear_in_prompt(prompt)
        if gear:
            rep.error("G7", f"提示词出现运镜器材名词 {gear} —— 会被实体化画进画面")
        risk = [w for w in LITERAL_RISK if w in prompt]
        if risk:
            rep.warn("G7", f"字面化风险词 {risk}（图片口径）")
        if prompt.strip() == "None":
            rep.error("G7", "提示词是字面量 None")
        return
    missing = [b for b in CORE_BLOCKS if f"【{b}】" not in prompt]
    if missing:
        rep.error("G7", f"缺核心分块: {missing}（缺任何一块，模型都会自行补戏）")
    absent = [b for b in blocks_required if f"【{b}】" not in prompt]
    if absent:
        rep.warn("G7", f"十块中未出现: {absent}")
    declared = _parse_slots(prompt)
    nums = sorted({int(m.group(1) or m.group(2))
                   for m in re.finditer(r"(?:<Picture\s*(\d+)>|@图片\s*(\d+))", prompt)})
    if nums and declared:
        rep.ok("G7", f"提示词引用编号 {nums}，身份声明 {len(declared)} 处")
    if provider == "local" and "【镜头】" in prompt:
        seg = prompt.split("【镜头】", 1)[1].split("【", 1)[0]
        if not re.search(r"(缓|缓缓|推|拉|移|摇|跟|环绕|升|降|静止|固定)", seg):
            rep.warn("G7", "【镜头】段没有运镜时序词 —— r2v 会自己决定机位，通常会平推")
        gear = _camera_gear_in_prompt(prompt)
        if gear:
            rep.error("G7", f"提示词出现运镜器材名词 {gear} —— 会被实体化渲进画面")
    if any(k in prompt for k in SILENT_ROLE):
        if not all(k in prompt for k in SILENT_REQUIRED):
            rep.error("G7", "声明了哑女/无声角色，但没写全「全程不出声、不张嘴」—— 会被开口")
    risk = [w for w in LITERAL_RISK if w in prompt]
    if risk:
        rep.warn("G7", f"字面化风险词 {risk} —— 历史案例：『蝶形双翼』被渲成真实蝴蝶翅膀")
    if len(prompt) < 120:
        rep.warn("G7", f"提示词仅 {len(prompt)} 字，像是占位/验证用的，正式出片请换定稿")
    if "None" == prompt.strip():
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


# ---------------- 编排 ----------------
ALL_GATES = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G11", "G12"]


def run_checks(spec, rep=None):
    """spec.only 可指定子集（引擎侧默认不跑 G8 服务探活与 G12 全池扫描，
       前者引擎自己会拉服务，后者每次出片扫几百份台账不值当）。"""
    rep = rep or Report()
    sel = set(spec.get("only") or ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"])
    refs = [str(x) for x in (spec.get("refs") or [])]
    ref_videos = [str(x) for x in (spec.get("ref_videos") or [])]
    prompt = spec.get("prompt") or ""
    provider = spec.get("provider", "local")
    if "G1" in sel:
        g1_files(rep, refs, ref_videos)
    if "G2" in sel:
        g2_md5_slots(rep, refs, ref_videos)
    if "G3" in sel:
        g3_identity(rep, prompt, refs, spec.get("slot_labels") or {})
    if "G4" in sel:
        g4_slots_and_quota(rep, refs, ref_videos, spec.get("workflow_json"), provider,
                           spec.get("duration"))
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
                             kind=str(spec.get("prompt_kind") or "video"))
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
    ap.add_argument("--base-url", default="http://127.0.0.1:8189")
    ap.add_argument("--pool-root", default=r"E:\图像影音资源池")
    ap.add_argument("--only", default="", help="只跑这些闸，逗号分隔，如 G1,G2,G3,G11")
    ap.add_argument("--theme")
    ap.add_argument("--batch-id", dest="batch_id")
    ap.add_argument("--project")
    ap.add_argument("--output-root", dest="output_root")
    ap.add_argument("--aliases", help="项目代号表 JSON 或 JSON 文件，如 {\"仙戮\":[\"xianlu\"]}")
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
            "w": a.w, "h": a.h, "length": a.length, "duration": a.duration,
            "lora": a.lora, "workflow_json": a.workflow_json, "provider": a.provider,
            "seed": a.seed, "base_url": a.base_url, "pool_root": a.pool_root,
            "check_service": a.check_service,
            "only": [x.strip().upper() for x in a.only.split(",") if x.strip()] or None,
            "theme": a.theme, "batch_id": a.batch_id,
            "output_root": a.output_root, "project": a.project,
            "project_aliases": aliases}
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
