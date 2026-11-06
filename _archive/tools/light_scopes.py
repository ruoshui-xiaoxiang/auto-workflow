# -*- coding: utf-8 -*-
r"""检光（light_scopes.py）·从成片／关键帧**量光**，不判好坏。

## 它为什么长这样
上一轮定的分工：**能进机检的只有示波器族读数，而且只报不拦**。所以这份脚本
- **一个阈值都没有**（除了 IRE 的定义边界）：不建闸、不注册编号、不进任何现役 yaml、不判废；
- **口径全写在输出里**：用的哪套亮度方程、full 还是 limited 摆幅、抽了第几帧、肤色判据是什么，
  报表抬头就带着，免得三个月后没人记得这些数是怎么来的；
- **没核到的东西不进判据**：矢量示波器上「肤色线」的绝对角度我没查到原始文档，
  所以这里只报**按我自己声明的约定算出的角度**，并给一张**同约定算出的基色靶刻度**当对照，
  要判偏移得由你给 `--skin-line-deg`（默认 None＝不判）。

## 量的五项
1. **黑位／白位／中灰落点**：Y' 的 p0.1／p1／p50／p95／p99.5（IRE）。
2. **削顶与塌黑**：线性值 ≥ 削顶线 与 ≤ 黑底 的像素数与占比（丢细节的证据，不判该不该丢）。
3. **光比（两种代理）**：a) 全域线性光 p90／p10 换算成「档」；b) 若检出人脸，脸框左半 vs 右半
   的线性亮度中位数换算成「档」——这条最接近片场说的「1:1／2:1／4:1／8:1 ↔ 0／1／2／3 档」，
   但它是**代理**（画面没有测光表，只有像素），所以标 `heuristic`。
4. **对比度跨度**：线性光 p95／p5 的档数（低对比／高对比的客观刻度，与「影调 low/high-key」对得上）。
5. **肤色簇**：面积占比、相对中性点的色度角（约定见下）、饱和距离 R。占比 0 时其余全报 `n/a`
   ——**「没测到」不等于「合格」**（这是踩过的坑，所以单独留一列）。

## 约定与方程（全部写死在这里，一处一份）
· 亮度 Y' 用 **Rec.709 系数在编码值上**算（波形监视器就是这么算的）：
  `Y' = 0.2126R' + 0.7152G' + 0.0722B'`，R'G'B'∈[0,1]。
· IRE：full 摆幅 0–255 → 0–100；limited 摆幅 16–235 → 0–100。`--range auto` 时视频读容器元数据，
  读不到就按 full 并在报表里**明说是猜的**。
· 线性光（算档数用）：`Y = Y' ** 2.4`（BT.1886 的简化幂律，黑位提升不计，够用于相对比较）。
  档数 `stops = log2(Y_hi / Y_lo)`。
· 色度角：`atan2(Cb-128, Cr-128)`，**0° 朝 +R−Y（红靶方向），逆时针为正**，单位度；
  基色靶刻度由同一公式现算，不抄外部数值。
· 肤色判据：OpenCV YCrCb 经验窗（Cr 133–173、Cb 77–127）——**这是启发式**，暗肤／极端光会漏。

## 摆幅只换算一次（10-04 拿抖音范例实测后立的口径）
本机探针实测（`D:\AIWorkflow\tmp\wzy\range_chain_probe.py`）：**`cv2.VideoCapture` 自己会把
tv(16–235) 展成 full(0–255)**，而且**超出 16–235 的码值在解码那一步就被夹掉**
（写 0 与写 16 都读到 0；写 235 与写 255 都读到 255）。所以
- 视频**不再走 cv2 解码**：改走 `ffmpeg -f rawvideo -pix_fmt yuv420p` 直读**码值域**的
  Y／Cb／Cr 平面，容器的 `color_range` 旗**只在这一步用一次**（limited ⇒ `(Y−16)/219`）；
  这样 >235 的超白与 <16 的亚黑才量得出来，而不是被解码链抹平后又被我当成"削顶 8%"。
- 找不到 ffmpeg 时才退回 cv2 解码，并**强制按 full 算**＋在报表抬头写明"解码链已展幅、
  超范围细节已被夹掉"——绝不再套第二次 limited。
- 码值域的 tv 色度围绕 128 压缩（系数 219/255），进肤色窗／饱和距离前先按
  `128 + (c−128)×255/219` 归到与靶刻度同一把尺上；**色度角不受这个缩放影响**（两轴同比例），
  只有饱和距离 R 受。
- 图片没有容器旗 ⇒ 按 full；BGR→YCrCb 本来就是 full 域，与上面同一把尺。

用法：
    python light_scopes.py --in <视频或图片目录或单图> [--out 目录] [--range auto|full|limited]
                            [--nframes 8] [--face] [--skin-line-deg 数值] [--json]
    python light_scopes.py --selftest        # 合成帧自检（关系性断言，不硬编码有争议的量）
"""
import argparse
import io
import json
import math
import os
import subprocess
import sys
import time

import cv2
import numpy as np

BT709 = (0.2126, 0.7152, 0.0722)
CLIP_HI = 99.5                 # IRE：≥ 此值算「削顶候选」（定义边界，不是判据）
CLIP_LO = 0.5                  # IRE：≤ 此值算「塌黑候选」
SKIN_CR = (133, 173)
SKIN_CB = (77, 127)
MIN_ANGLE_AREA = 200          # 肤色面积（亮度像素当量）低于此 ⇒ 角度／饱和不报（没测到 ≠ 合格）
MIN_ROI_AREA = 400            # 同上，够这个数才敢拿包围盒当主体区
MIN_TONE_SAMPLES = 200        # 暗部／亮部色度样本数低于此 ⇒ 冷暖分区不报（色度网格上的样本）
QUANT_FLOOR = (1.0 / 255.0) ** 2.4      # 线性光的量化地板（一个 code 值），见 ire_to_linear 注释


def ire_from_y(y, rng):
    """**码值域** Y（0–255）→ IRE。摆幅旗只在这里换算一次。"""
    lo, hi = (16.0, 235.0) if rng == "limited" else (0.0, 255.0)
    return (np.asarray(y, dtype=np.float32) - lo) / (hi - lo) * 100.0


def luma_to_ire(bgr, rng):
    """BGR（uint8）→ Y'（0–255 编码值）→ IRE。图片／cv2 兜底那条用；视频走 ire_from_y。"""
    ch = cv2.split(bgr.astype(np.float32))
    b, g, r = [c / 255.0 for c in ch]
    y = (BT709[0] * r + BT709[1] * g + BT709[2] * b) * 255.0
    return ire_from_y(y, rng)


def chroma_to_full(cb, cr, rng):
    """码值域色度 → 与靶刻度同一把尺（full 域等价 0–255）。
    limited 的色度围绕 128 压缩了 219/255，不归一下肤色窗和饱和 R 会整体偏小；
    **色度角不受这个缩放影响**（两轴同比例），只有 R 受。"""
    cb = np.asarray(cb, dtype=np.float32)
    cr = np.asarray(cr, dtype=np.float32)
    if rng != "limited":
        return cb, cr
    k = 255.0 / 219.0
    return 128.0 + (cb - 128.0) * k, 128.0 + (cr - 128.0) * k


def ire_to_linear(ire):
    """IRE（0–100，可超）→ 线性光（简化幂律）。
    ⚠ 下限钉在**一个量化台阶** `(1/255)**2.4`：暗部真塌成 0 时 log2 会炸成 nan／inf，
    而「纯黑 vs 纯白」本来就是无上限的光比——取一个可解释的地板（一个 code 值）
    才能让档数有限可比，报表里也照样说得出"暗部已经没数据了"（另有塌黑占比那一条）。
    地板与 IRE 轴自洽：full 摆幅下 1 个 code ＝ 100/255 ≈ 0.392 IRE，正好落在地板处。"""
    return np.maximum(np.clip(np.asarray(ire, dtype=np.float32) / 100.0, 0.0, None) ** 2.4,
                      QUANT_FLOOR)


def stops(hi, lo):
    if hi <= 0 or lo <= 0:
        return float("nan")
    return math.log2(hi / lo)


def angle_and_R(cb, cr):
    """一维色度样本 →（色度角度、饱和距离），约定见模块抬头。"""
    cb = np.asarray(cb, dtype=np.float32) - 128.0
    cr = np.asarray(cr, dtype=np.float32) - 128.0
    return np.degrees(np.arctan2(cb, cr)), np.hypot(cb, cr)


def chroma_angle_deg(bgr):
    """给一组 BGR 像素，按声明的约定算色度角（度）与饱和距离。输入 BGR×N。"""
    ycc = cv2.cvtColor(bgr.reshape(1, -1, 3), cv2.COLOR_BGR2YCrCb).reshape(-1, 3).astype(np.float32)
    return angle_and_R(ycc[:, 2], ycc[:, 1])



def target_scale():
    """同约定下现算基色靶刻度（不抄外部数值）：R/G/B 与青黄品。"""
    px = {"红靶 R": (0, 0, 255), "绿靶 G": (0, 255, 0), "蓝靶 B": (255, 0, 0),
          "青靶 C": (255, 255, 0), "黄靶 Y": (0, 255, 255), "品靶 M": (255, 0, 255)}
    out = {}
    for k, v in px.items():
        ang, rad = chroma_angle_deg(np.array([v], dtype=np.uint8))
        out[k] = (round(float(ang[0]), 1), round(float(rad[0]), 1))
    return out


def skin_sel(cb, cr):
    """肤色窗（作用在 full 域等价色度上，见 chroma_to_full）——**启发式**，见模块抬头。"""
    return ((cb >= SKIN_CB[0]) & (cb <= SKIN_CB[1]) &
            (cr >= SKIN_CR[0]) & (cr <= SKIN_CR[1]))


def subject_roi(sel, W, H, sx, sy):
    """主体区＝肤色簇的包围盒；肤色不够就退到**中央 50% 区**并如实标出来。
    sel 是色度分辨率的掩膜（视频 4:2:0 ⇒ 边长是亮度的一半），所以面积按 `sx*sy` 折回亮度像素当量。
    ⚠ 不用 Haar 正脸检测：本机 OpenCV 是 5.0，`cv2.CascadeClassifier` 已不在顶层命名空间，
    而 CG 角色的脸本来就容易过不了真人级联——**换成"看得见的主体区"更诚实，也少一个依赖**。"""
    if sel is not None and int(sel.sum()) * sx * sy >= MIN_ROI_AREA:
        ys, xs = np.nonzero(sel)
        x0, x1 = int(xs.min()) * sx, int(xs.max()) * sx
        y0, y1 = int(ys.min()) * sy, int(ys.max()) * sy
        x1, y1 = min(x1 + sx - 1, W - 1), min(y1 + sy - 1, H - 1)
        if x1 - x0 >= 24 and y1 - y0 >= 24:
            return (x0, y0, x1 - x0, y1 - y0), "肤色包围盒"
    return (int(W * 0.25), int(H * 0.25), int(W * 0.5), int(H * 0.5)), "中央区（肤色不足，退到中央）"


def measure_frame(ire, cb, cr, want_subject=True):
    """核心：输入 IRE 亮度面（H×W）＋ full 域等价色度面（h×w），出全部读数。
    视频（码值域直读）与图片（BGR 换算）两条路都汇到这里，**一套算法一份实现**。"""
    flat = np.asarray(ire, dtype=np.float32).ravel()
    lin = ire_to_linear(ire)
    p = lambda q: float(np.percentile(flat, q))
    pl = lambda q: float(np.percentile(lin.ravel(), q))
    m = {
        "ire_p0.1": round(p(0.1), 2), "ire_p1": round(p(1), 2), "ire_p50": round(p(50), 2),
        "ire_p95": round(p(95), 2), "ire_p99.5": round(p(99.5), 2),
        "ire_max": round(float(flat.max()), 2), "ire_min": round(float(flat.min()), 2),
        "clip_hi_px": int((flat >= CLIP_HI).sum()), "clip_hi_pct": round(float((flat >= CLIP_HI).mean() * 100), 3),
        "crushed_lo_px": int((flat <= CLIP_LO).sum()),
        "crushed_lo_pct": round(float((flat <= CLIP_LO).mean() * 100), 3),
        # 越界两列按**声明摆幅的合法白／合法黑**算，跟上面那两列不是一回事：
        # 削顶线 99.5 是「顶到白」，这里量的是「超出合法白／低于合法黑」（旗说 235，码值跑到 236+）。
        "over_white_px": int((flat > 100.0).sum()),
        "over_white_pct": round(float((flat > 100.0).mean() * 100), 3),
        "under_black_px": int((flat < 0.0).sum()),
        "under_black_pct": round(float((flat < 0.0).mean() * 100), 3),
        # 亮面两列＝**发光面积**：≥70 IRE 与 ≥90 IRE 的像素占比。
        # 为什么单独立这两列（10-04 本地对照实测）：曝光中点（p50）分不出
        # 「大面积发光体＋雾」和「单主体打光＋黑背景」这两种完全不同的布光，
        # 亮面占比分得出——它是「风格对齐没有」的结构性指标，不是审美阈值。
        "bright70_pct": round(float((flat >= 70.0).mean() * 100), 2),
        "bright90_pct": round(float((flat >= 90.0).mean() * 100), 3),
        "overall_stops_p90_p10": round(stops(pl(90), pl(10)), 2),
        "contrast_stops_p95_p5": round(stops(pl(95), pl(5)), 2),
    }
    H, W = np.asarray(ire).shape[:2]
    h, w = np.asarray(cb).shape[:2]
    sx, sy = max(W // w, 1), max(H // h, 1)
    sel = skin_sel(cb, cr)
    n = int(sel.sum())
    m["skin_pct"] = round(n / float(sel.size) * 100, 3)
    m["chroma_subsampling"] = "%dx%d" % (sx, sy)
    if n * sx * sy >= MIN_ANGLE_AREA:
        ang, rad = angle_and_R(cb[sel], cr[sel])
        m["skin_angle_deg"] = round(float(np.median(ang)), 1)
        m["skin_sat_R"] = round(float(np.median(rad)), 1)
        m["skin_n"] = n * sx * sy
    else:
        m["skin_angle_deg"] = None
        m["skin_sat_R"] = None
        m["skin_n"] = n * sx * sy
        m["skin_note"] = "肤色面积不足 %d 像素当量 ⇒ 角度不报（没测到 ≠ 合格）" % MIN_ANGLE_AREA
    if want_subject:
        box, roi_kind = subject_roi(sel, W, H, sx, sy)
        x, y, bw, bh = box
        half = max(bw // 2, 1)
        le = ire_to_linear(ire[y:y + bh, x:x + half]).ravel()
        ri = ire_to_linear(ire[y:y + bh, x + half:x + bw]).ravel()
        a, b = float(np.median(le)), float(np.median(ri))
        m["roi_kind"] = roi_kind
        m["roi_box"] = [x, y, bw, bh]
        m["subject_side_stops"] = round(stops(max(a, b), min(a, b)), 2)
        m["subject_brighter_side"] = ("左" if a >= b else "右")
    else:
        m["roi_kind"] = "关（--no-subject）"
        m["roi_box"] = None
        m["subject_side_stops"] = None
        m["subject_brighter_side"] = "—"
    # 冷暖分区（split-tone）：把亮度面按 sx×sy 抽点到色度网格上，各取最暗 10%／最亮 10% 的色度样本。
    # 报的是**角度与饱和**，不报"色温 K 数"——K 数是光源属性，像素里没有，别拿代理数冒充标准数。
    y_small = np.asarray(ire, dtype=np.float32)[::sy, ::sx][:h, :w]
    lo_t = float(np.percentile(y_small, 10))
    hi_t = float(np.percentile(y_small, 90))
    for key, sub in (("shadow", y_small <= lo_t), ("highlight", y_small >= hi_t)):
        cbx, crx = cb[sub], cr[sub]
        m[key + "_ire_p50"] = round(float(np.median(y_small[sub])), 2) if sub.sum() else None
        if cbx.size >= MIN_TONE_SAMPLES:
            ang, rad = angle_and_R(cbx, crx)
            m[key + "_angle_deg"] = round(float(np.median(ang)), 1)
            m[key + "_sat_R"] = round(float(np.median(rad)), 1)
        else:
            m[key + "_angle_deg"] = None
            m[key + "_sat_R"] = None
    if m.get("shadow_angle_deg") is not None and m.get("highlight_angle_deg") is not None:
        d = m["highlight_angle_deg"] - m["shadow_angle_deg"]
        if d > 180:
            d -= 360
        elif d < -180:
            d += 360
        m["tone_sep_deg"] = round(d, 1)      # 亮部相对暗部往哪个方向偏（正＝逆时针＝偏蓝侧）
    else:
        m["tone_sep_deg"] = None
    return m


def frame_bgr(bgr, rng):
    """图片／cv2 兜底那条：BGR → (IRE, full 域等价 Cb, Cr)。BGR 本来就是 full 域，不再缩放色度。"""
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    return (luma_to_ire(bgr, rng), ycc[:, :, 2].astype(np.float32),
            ycc[:, :, 1].astype(np.float32))


def frame_planes(y, cb, cr, rng):
    """视频那条：码值域三平面 → (IRE, full 域等价 Cb, Cr)。摆幅旗在这一步用一次。"""
    ire = ire_from_y(y, rng)
    cbb, crb = chroma_to_full(cb, cr, rng)
    return ire, cbb, crb


def measure(bgr, rng, want_subject=True):
    """兼容入口（自检与图片用）：BGR → 读数。"""
    return measure_frame(*(frame_bgr(bgr, rng)), want_subject=want_subject)



def find_probe():
    """找得到哪个用哪个，并把**用的是哪条路径**报出去（不假装读到了元数据）。"""
    import shutil
    cands = [os.environ.get("LIGHT_SCOPES_FFPROBE", ""), shutil.which("ffprobe") or "",
             r"D:\AIWorkflow\LivePortrait-main\bin\ffprobe.exe"]
    for c in cands:
        if c and os.path.isfile(c):
            return c, "ffprobe"
    try:                                        # 退一步：用 imageio_ffmpeg 自带的 ffmpeg 读 `-i` 摘要
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe(), "ffmpeg"
    except Exception:
        return None, "都没有"


def probe_range(path, is_video):
    """auto：视频读容器 color_range；读不到就按 full，并说明是猜的。"""
    if not is_video:
        return "full", "图片无容器元数据 ⇒ 按 full 摆幅"
    tool, kind = find_probe()
    if not tool:
        return "full", "本机找不到 ffprobe／ffmpeg ⇒ 按 full（**这是猜的**，要准请显式 --range）"
    if kind == "ffprobe":
        args = [tool, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=color_range", "-of", "csv=p=0", path]
    else:
        args = [tool, "-hide_banner", "-i", path]
    try:
        r = subprocess.run(args, capture_output=True, timeout=30)
        out = (r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"))
        if kind == "ffprobe":
            v = out.strip()
        else:                                   # ffmpeg 的流摘要里形如 `bt709(tv, bt709)`
            v = "limited" if "(tv" in out or "bt709(tv" in out else ("full" if "(pc" in out else "")
        if v in ("limited", "tv", "full", "pc"):
            return ("limited" if v in ("limited", "tv") else "full"), \
                "%s 报 color_range=%s（用的工具：%s）" % (kind, v, os.path.basename(tool))
        return "full", "%s 没给出 color_range ⇒ 按 full（**这是猜的**）｜%s" % (kind, os.path.basename(tool))
    except Exception as e:
        return "full", "%s 调用失败（%s）⇒ 按 full（猜的）" % (kind, type(e).__name__)


def find_ffmpeg():
    import shutil
    cands = [os.environ.get("LIGHT_SCOPES_FFMPEG", ""), shutil.which("ffmpeg") or "",
             r"D:\AIWorkflow\tools\ffmpeg.exe",
             r"D:\AIWorkflow\LivePortrait-main\bin\ffmpeg.exe"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def probe_geometry(path):
    """ffprobe 取宽／高／总帧数；取不到就报 None（调用方如实说"猜的"）。"""
    tool, kind = find_probe()
    if kind != "ffprobe":
        return None, None, None
    args = [tool, "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,nb_frames", "-of", "csv=p=0", path]
    try:
        out = subprocess.run(args, capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
        f = [x.strip() for x in out.strip().split(",")]
        w, h = int(f[0]), int(f[1])
        total = int(f[2]) if len(f) > 2 and f[2].isdigit() else None
        return w, h, total
    except Exception:
        return None, None, None


def sample_idx(total, n):
    if not total or total < 1:
        return list(range(max(n, 1)))
    return [int(round(i * (max(total - 1, 0) / max(n - 1, 1)))) for i in range(n)]


def coded_frames_from_video(path, idxs, tmpdir):
    """★视频正路：一次解码，`ffmpeg -f rawvideo -pix_fmt yuv420p` 直读**码值域**三平面。
    不经 `cv2.VideoCapture`——那条链自己会把 tv 展成 full 并把 16–235 以外的码值夹掉，
    超白／亚黑就量不到了（10-04 范例实测）。返回 [(tag, Y, Cb, Cr)]，色度是 4:2:0 的半分辨率。
    宽高取 ffprobe；奇数边一律裁到偶数（yuv420p 要求），并在 tag 上如实标出来。"""
    ff = find_ffmpeg()
    if not ff:
        return None, "本机找不到 ffmpeg ⇒ 没法直读码值域"
    w, h, total = probe_geometry(path)
    if not w or not h:
        return None, "ffprobe 没给出宽高 ⇒ 没法直读码值域"
    w2, h2 = w - (w % 2), h - (h % 2)
    sel = "+".join("eq(n\\,%d)" % i for i in idxs)
    rawp = os.path.join(tmpdir, "planes_%d.yuv" % os.getpid())
    cmd = [ff, "-v", "error", "-i", path, "-vf",
           "select=%s,format=yuv420p,scale=trunc(iw/2)*2:trunc(ih/2)*2" % sel,
           "-vsync", "0", "-f", "rawvideo", rawp]
    try:
        if not os.path.isdir(tmpdir):
            os.makedirs(tmpdir)
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if not os.path.isfile(rawp) or os.path.getsize(rawp) == 0:
            return None, "ffmpeg 取帧失败：%s" % r.stderr.decode("utf-8", "replace")[-200:]
        fsz = w2 * h2 * 3 // 2
        b = np.fromfile(rawp, dtype=np.uint8)
        got = b.size // fsz
        out = []
        for k in range(got):
            p = b[k * fsz:(k + 1) * fsz]
            y = p[:w2 * h2].reshape(h2, w2)
            cb = p[w2 * h2:w2 * h2 + (w2 // 2) * (h2 // 2)].reshape(h2 // 2, w2 // 2)
            cr = p[w2 * h2 + (w2 // 2) * (h2 // 2):].reshape(h2 // 2, w2 // 2)
            out.append(("f%d" % idxs[k], (y, cb, cr)))
        note = "码值域直读 %d/%d 帧（%dx%d→%dx%d，4:2:0）" % (got, len(idxs), w, h, w2, h2)
        if got < len(idxs):
            note += "｜⚠ 尾部 %d 帧没取到（容器帧数与实际可解码帧数不符）" % (len(idxs) - got)
        return out, note
    finally:
        if os.path.isfile(rawp):
            os.remove(rawp)


def bgr_frames_from_video(path, idxs):
    """兜底路（找不到 ffmpeg 时）：cv2 解码。⚠ 它已经把 tv 展成 full 并夹掉超范围码值，
    所以这条**只能按 full 算**，且超白／亚黑量不出来——报表抬头会写明。"""
    cap = cv2.VideoCapture(path)
    out = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if ok:
            out.append(("f%d" % i, fr))
    cap.release()
    return out


def payload_to_frame(p, rng):
    """一帧的两种形态 → (IRE, Cb, Cr)：tuple＝码值域三平面；ndarray＝BGR。"""
    if isinstance(p, tuple):
        return frame_planes(p[0], p[1], p[2], rng)
    return frame_bgr(p, rng)


def frames_from_images(paths):
    out = []
    for p in paths:
        im = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)   # 中文路径走 imdecode
        if im is not None:
            out.append((os.path.basename(p), im))
    return out



def collect_inputs(spec):
    if os.path.isfile(spec):
        return [spec], bool(spec.lower().endswith((".mp4", ".mov", ".mkv", ".avi", ".webm")))
    fs = [os.path.join(spec, f) for f in sorted(os.listdir(spec))
          if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp"))]
    return fs, False


COLS = ["src", "frame", "range", "ire_p0.1", "ire_p1", "ire_p50", "ire_p95", "ire_p99.5",
        "ire_min", "ire_max", "clip_hi_pct", "clip_hi_px", "crushed_lo_pct", "crushed_lo_px",
        "over_white_pct", "over_white_px", "under_black_pct", "under_black_px",
        "bright70_pct", "bright90_pct",
        "overall_stops_p90_p10", "contrast_stops_p95_p5", "roi_kind", "subject_side_stops",
        "subject_brighter_side", "skin_pct", "skin_angle_deg", "skin_sat_R", "skin_n",
        "chroma_subsampling", "shadow_ire_p50", "shadow_angle_deg", "shadow_sat_R",
        "highlight_ire_p50", "highlight_angle_deg", "highlight_sat_R", "tone_sep_deg", "skin_note"]


def _encode_bands(vals, color_range, path):
    """造一张**已知码值**的横条纹片（Y＝vals，U/V＝128 中性）——只用于 16–235 之内的值＋tv 旗。
    ⚠ 实测（10-04，两次跑）：ffmpeg 在"rawvideo 输入 → 带旗的输出"之间自己动手换算：
    `-color_range tv` 把亮度**夹到 16–235**（写 0 存成 16、写 255 存成 235），
    `-color_range pc` 把它**从 16–235 展到 0–255**（写 16 存成 0、写 235 存成 255）。
    ⇒ **超范围码值的片子造不出来**，别拿编码器当尺子；那部分改走纯函数断言（见 range_chain_check）。"""
    import tempfile
    W = H = 96
    band = H // len(vals)
    y = np.zeros((H, W), np.uint8)
    for i, v in enumerate(vals):
        y[i * band:(i + 1) * band, :] = v
    uv = np.full((H // 2, W // 2), 128, np.uint8)
    rawp = os.path.join(tempfile.gettempdir(), "light_scopes", "bands_%s.yuv" % color_range)
    with open(rawp, "wb") as fh:
        fh.write(y.tobytes() + uv.tobytes() + uv.tobytes())
    r = subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p",
                        "-s", "%dx%d" % (W, H), "-i", rawp, "-frames:v", "1",
                        "-c:v", "libx264", "-crf", "0", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-color_range", color_range,
                        "-colorspace", "bt709", path], capture_output=True)
    os.remove(rawp)
    ok = (r.returncode == 0 and os.path.isfile(path))
    return ok, (band if ok else r.stderr.decode("utf-8", "replace")[-160:])


def range_chain_check():
    """★摆幅链自证（10-04 立的，起因就是范例第一版报表把解码链的展幅当成了片子的削顶）。
    分两段，各管各的：
    ① **纯函数**（不碰任何解码器，永远跑）：limited 下 16→0／235→100，且 16–235 之外要给出
       负 IRE 与 >100 IRE（超白、亚黑量得到＝旗只换算了一次）；full 下 0→0／255→100；
       色度归一只改饱和距离、不改色度角。
    ② **真片子**（要 ffmpeg）：tv 旗条纹片走码值域读回来码值**一个没动**；同一张片走 cv2 兜底
       必须被展成 0–255 —— 这条是"为什么不能走它"的活证据，哪天 OpenCV 改了行为这里先响。
    ⚠ 为什么"超范围码值"这段不做成真片子：实测 ffmpeg 在 rawvideo 输入与带旗的输出之间自己动手
    换算（`tv` 夹到 16–235、`pc` 又从 16–235 展到 0–255，写 16 存成 0）——**造不出这种片子**，
    拿编码器当尺子只会量到编码器。所以那条走 ① 的纯函数断言。"""
    import tempfile
    bad = []
    # —— ① 纯函数段：不依赖任何外部工具 ——
    codes = [6, 16, 64, 160, 235, 250]
    plane = np.array([codes], dtype=np.uint8)
    lim = ire_from_y(plane, "limited")
    for j, v in enumerate(codes):
        exp = (v - 16.0) / 219.0 * 100.0
        if abs(float(lim[0, j]) - exp) > 0.02:
            bad.append(u"码值 %d 按 limited 应 %.2f IRE，实得 %.2f" % (v, exp, float(lim[0, j])))
    if not (float(lim[0, 0]) < 0.0 and float(lim[0, -1]) > 100.0):
        bad.append(u"亚黑没给出负 IRE／超白没给出 >100 IRE ⇒ 旗被换算了不止一次")
    full = ire_from_y(plane, "full")
    for j, v in enumerate(codes):
        if abs(float(full[0, j]) - v / 255.0 * 100.0) > 0.02:
            bad.append(u"码值 %d 按 full 应 %.2f IRE，实得 %.2f"
                       % (v, v / 255.0 * 100.0, float(full[0, j])))
    cb, cr = np.array([[128.0, 150.0]]), np.array([[128.0, 140.0]])
    a0, r0 = angle_and_R(*chroma_to_full(cb, cr, "full"))
    a1, r1 = angle_and_R(*chroma_to_full(cb, cr, "limited"))
    if abs(float(a0.flat[1]) - float(a1.flat[1])) > 1e-4:
        bad.append(u"色度归一把色度角也改了（%.2f°→%.2f°）⇒ 归一系数不能这么用"
                   % (a0.flat[1], a1.flat[1]))
    if not float(r1.flat[1]) > float(r0.flat[1]):
        bad.append(u"limited 归一后饱和距离没变大（%.2f→%.2f）⇒ 255/219 那条缩放反了"
                   % (float(r0.flat[1]), float(r1.flat[1])))
    # —— ② 真片子段：要 ffmpeg ——
    if not find_ffmpeg():
        print(u"   · 摆幅链自证：① 纯函数段已跑｜② 真片子段本机没有 ffmpeg ⇒ **跳过**（没跑过 ≠ 过了）")
        return bad
    tmp = os.path.join(tempfile.gettempdir(), "light_scopes")
    if not os.path.isdir(tmp):
        os.makedirs(tmp)
    vals = [16, 64, 160, 235]
    tvp = os.path.join(tmp, "selftest_tv.mp4")
    ok_tv, band = _encode_bands(vals, "tv", tvp)
    if not ok_tv:
        print(u"   · 摆幅链自证：② 造不出条纹片（%s）⇒ **跳过**" % band)
        return bad
    got, note = coded_frames_from_video(tvp, [0], tmp)
    if not got:
        bad.append(u"码值域读帧失败：%s" % note)
    else:
        _, (yy, cb0, cr0) = got[0]
        for i, v in enumerate(vals):
            m = int(np.median(yy[i * band:(i + 1) * band, :]))
            if abs(m - v) > 1:
                bad.append(u"码值 %d 读回来是 %d ⇒ 我的读帧链动了摆幅（%s）" % (v, m, note))
        ire, _, _ = frame_planes(yy, cb0, cr0, "limited")
        for i, v in enumerate(vals):
            exp = (v - 16.0) / 219.0 * 100.0
            m = float(np.median(ire[i * band:(i + 1) * band, :]))
            if abs(m - exp) > 0.5:
                bad.append(u"片上码值 %d 按 limited 应 %.1f IRE，实得 %.1f" % (v, exp, m))
    cap = cv2.VideoCapture(tvp)
    okf, fr = cap.read()
    cap.release()
    if okf:
        g = fr[:, :, 1]
        lo, hi = float(np.median(g[:band, :])), float(np.median(g[-band:, :]))
        if not (lo <= 1.0 and hi >= 254.0):
            bad.append(u"cv2 那条链的展幅行为变了（写 16→读 %.0f，写 235→读 %.0f）"
                       u" ⇒ 重看兜底口径与『只能按 full 算』那条注" % (lo, hi))
    if os.path.isfile(tvp):
        os.remove(tvp)
    print(u"   · 摆幅链自证：① 旗只换算一次（超白 >100／亚黑 <0 量得到）② 码值域直读不展幅"
          u"＋cv2 兜底展幅已验")
    return bad


def selftest():
    """合成帧：只断言**关系性**事实，不硬编码有争议的数值。"""
    W = H = 128
    black = np.zeros((H, W, 3), np.uint8)
    white = np.full((H, W, 3), 255, np.uint8)
    lr = np.zeros((H, W, 3), np.uint8)
    lr[:, :W // 2] = 0
    lr[:, W // 2:] = 255
    red = np.zeros((H, W, 3), np.uint8)
    red[:, :, 2] = 255
    bad = []
    m = measure(black, "full", want_subject=False)
    if abs(m["ire_p50"]) > 0.6:
        bad.append("纯黑 p50 应≈0 IRE，实得 %s" % m["ire_p50"])
    if abs(m["crushed_lo_pct"] - 100.0) > 0.1:
        bad.append("纯黑应 100%% 塌黑，实得 %s" % m["crushed_lo_pct"])
    m = measure(white, "full", want_subject=False)
    if abs(m["ire_p50"] - 100) > 0.6:
        bad.append("纯白 p50 应≈100 IRE，实得 %s" % m["ire_p50"])
    if abs(m["clip_hi_pct"] - 100.0) > 0.1:
        bad.append("纯白应 100%% 削顶，实得 %s" % m["clip_hi_pct"])
    if not (m["bright70_pct"] > 99.0 and m["bright90_pct"] > 99.0):
        bad.append("纯白的发光面积应≈100%%，实得 ≥70：%s｜≥90：%s"
                   % (m["bright70_pct"], m["bright90_pct"]))
    mb = measure(black, "full", want_subject=False)
    if mb["bright70_pct"] > 0.1:
        bad.append("纯黑的发光面积应≈0，实得 %s" % mb["bright70_pct"])
    m = measure(lr, "full", want_subject=False)
    if not (m["overall_stops_p90_p10"] > 8):
        bad.append("左黑右白应给出很大光比（>8 档），实得 %s" % m["overall_stops_p90_p10"])
    m = measure(red, "full", want_subject=False)
    if m["skin_pct"] > 1.0:
        bad.append("纯红帧不该被判成大片肤色，实得 %s%%" % m["skin_pct"])
    lim = measure(white, "limited", want_subject=False)
    if not (lim["ire_p50"] > 105):
        bad.append("同一张白图，limited 摆幅下 IRE 应更高（>105），实得 %s" % lim["ire_p50"])
    sc = target_scale()
    if len(sc) != 6:
        bad.append("基色靶刻度没算全：%s" % list(sc))
    # 冷暖分区方向自证：造一张"暗端偏蓝、亮端偏红"且亮度单调的渐变帧，Δ 必须是负的
    # （约定里蓝靶 +99°、红靶 −19°，亮部往红走＝角度变小＝Δ<0）。方向反了整列作废，所以这条要拦。
    x = np.arange(256, dtype=np.float32)
    t = (x - 128.0) / 128.0
    luma = 30.0 + 0.75 * x
    rr = np.clip(luma + 18.0 * t, 0, 255)
    bb = np.clip(luma - 18.0 * t, 0, 255)
    gg = np.clip(luma, 0, 255)
    split = np.tile(np.stack([bb, gg, rr], axis=-1).astype(np.uint8)[None, :, :], (16, 1, 1))
    ms = measure(split, "full", want_subject=False)
    if ms.get("tone_sep_deg") is None:
        bad.append(u"冷暖分区没读数（样本够的渐变帧都不出数）⇒ 那列作废")
    elif not ms["tone_sep_deg"] < -20.0:
        bad.append(u"暗蓝亮红的渐变帧 Δ 应显著为负，实得 %s ⇒ 冷暖分区那条方向反了" % ms["tone_sep_deg"])
    if not (ms.get("shadow_angle_deg") is not None and ms["shadow_angle_deg"] > 0.0
            > ms["highlight_angle_deg"]):
        bad.append(u"暗部角应偏蓝（正）、亮部角应偏红（负），实得 暗 %s／亮 %s"
                   % (ms.get("shadow_angle_deg"), ms.get("highlight_angle_deg")))
    bad += range_chain_check()
    print("检光自检：%s" % ("✓ 全过（黑=0／白=100／左黑右白光比>8 档／纯红不判肤色／摆幅切换方向正确／"
                             "靶刻度 6 个／冷暖分区方向对／码值域直读不展幅不夹值）"
                       if not bad else "✗ 有问题"))
    for x in bad:
        print("   ✗ %s" % x)
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="检光：只量不判（示波器族读数）")
    ap.add_argument("--in", dest="inp", help="视频／图片目录／单张图")
    ap.add_argument("--out", default=r"D:\AIWorkflow\tmp\light_scopes", help="报表落点")
    ap.add_argument("--range", default="auto", choices=["auto", "full", "limited"])
    ap.add_argument("--nframes", type=int, default=8, help="视频均匀抽几帧")
    ap.add_argument("--no-subject", action="store_true", help="关掉主体区光比那条（只出全域数）")
    ap.add_argument("--skin-line-deg", type=float, default=None,
                    help="你标定后的肤色线角度；给了才会算「偏离线几度」，默认不判")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.inp:
        ap.error("要 --in（或用 --selftest）")
    paths, is_video = collect_inputs(a.inp)
    if not paths:
        print("输入里没有可读的图片或视频：%s" % a.inp)
        return 1
    rng, rng_note = (a.range, "显式指定") if a.range != "auto" else probe_range(paths[0], is_video)
    import tempfile
    tmpdir = os.path.join(tempfile.gettempdir(), "light_scopes")
    todo, frames_note = [], ""
    if is_video:
        _, _, total = probe_geometry(paths[0])
        idxs = sample_idx(total, a.nframes)
        got, note = coded_frames_from_video(paths[0], idxs, tmpdir)
        if got is None:
            rng, todo = "full", bgr_frames_from_video(paths[0], idxs)
            frames_note = "cv2 兜底取 %d 帧" % len(todo)
            rng_note = (u"%s｜⚠ 走的是 cv2 解码：它自己就把 tv(16–235) 展成 full(0–255) 并夹掉超范围码值"
                        u" ⇒ 本表强制按 full 算，超白／亚黑量不到（原因：%s）" % (rng_note, note))
        else:
            todo, frames_note = got, note
    else:
        todo = frames_from_images(paths)
        frames_note = u"图片 %d 张（无容器旗 ⇒ full）" % len(todo)
    rows = []
    for tag, pl in todo:
        m = measure_frame(*(payload_to_frame(pl, rng)), want_subject=not a.no_subject)
        m["src"] = os.path.basename(paths[0]) if is_video else tag
        m["frame"] = tag if is_video else os.path.basename(tag)
        m["range"] = rng
        if a.skin_line_deg is not None and m.get("skin_angle_deg") is not None:
            m["skin_off_line_deg"] = round(m["skin_angle_deg"] - a.skin_line_deg, 1)
        rows.append(m)
    if not rows:
        print("一帧都没取到（检查路径／解码器）")
        return 1
    stamp = time.strftime("%Y%m%d_%H%M%S")
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    csvp = os.path.join(a.out, "检光_%s.csv" % stamp)
    with io.open(csvp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv_writer(fh)
        for r in rows:
            w.writerow(r)
    md = [u"# 检光报表（只量不判）", "",
          u"- 输入：`%s`｜取帧 %d 张（视频则均匀抽）" % (a.inp, len(rows)),
          u"- 取帧口径：%s" % frames_note,
          u"- 摆幅口径：**%s**（%s）——旗只用一次，不在解码链之后再折第二次" % (rng, rng_note),
          u"- 亮度：Rec.709 系数在编码值上算；线性化用 `Y' ** 2.4`（BT.1886 简化，**下限钉在一个量化台阶** "
          u"`(1/255)**2.4`，否则暗部塌成 0 时档数会炸成 nan）；档数 `log2(亮/暗)`",
          u"- 削顶线 %s IRE／塌黑线 %s IRE —— 这是**定义边界**（像素已经没数据了），不是审美阈值" % (CLIP_HI, CLIP_LO),
          u"- 越界两列 `over_white`／`under_black` 另算：按**声明摆幅的合法白 100 IRE／合法黑 0 IRE**——"
          u"「顶到白」与「超出合法白」是两件事，分开报，别拿前者当后者",
          u"- 亮面两列 `bright70`／`bright90`＝**发光面积**（≥70／≥90 IRE 的像素占比）："
          u"曝光中点分不出「大面积发光体＋雾」与「单主体打光＋黑背景」这两种布光，亮面占比分得出",
          u"- 肤色判据：YCrCb 经验窗 Cr %s／Cb %s ⇒ **启发式**，暗肤与极端光会漏" % (SKIN_CR, SKIN_CB),
          u"- 色度角约定：0° 朝 +R−Y（红靶），逆时针为正；靶刻度（同约定现算）：%s"
          % u"、".join(u"%s %.0f°" % (k, v[0]) for k, v in target_scale().items()),
          u"- 肤色线偏移：%s" % (u"已按你给的 %.1f° 算" % a.skin_line_deg if a.skin_line_deg is not None
                                 else u"**未判**（没给 `--skin-line-deg`；我不替你定这条线）"),
          u"- 冷暖分区（split-tone）：亮度面按 `sx×sy` 抽点到色度网格，各取**最暗 10%／最亮 10%**"
          u" 的色度中位角；Δ＝亮部角−暗部角（正＝亮部更偏蓝侧）。**只报角度不报「色温 K 数」**"
          u"——K 是光源属性，像素里没有，别拿代理数冒充标准数",
          u"",
          u"| 帧 | IRE 0.1/1/50/95/99.5 | 削顶% | 塌黑% | 全域档(p90/p10) | 对比档(p95/p5) | 主体区 | 主体左右档 | 肤色% | 肤色角 | 饱和R | 冷暖 暗→亮(Δ) | 亮面≥70／≥90 % |",
          u"|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        tone = u"—"
        if r.get("shadow_angle_deg") is not None and r.get("highlight_angle_deg") is not None:
            tone = u"%.0f°→%.0f°(%+.1f)" % (r["shadow_angle_deg"], r["highlight_angle_deg"],
                                            r["tone_sep_deg"])
        md.append(u"| `%s` | %.1f／%.1f／%.1f／%.1f／%.1f | %.2f | %.2f | %s | %s | %s | %s | %.2f | %s | %s | %s | %s／%s |"
                  % (str(r["frame"])[:18], r["ire_p0.1"], r["ire_p1"], r["ire_p50"], r["ire_p95"],
                     r["ire_p99.5"], r["clip_hi_pct"], r["crushed_lo_pct"],
                     r["overall_stops_p90_p10"], r["contrast_stops_p95_p5"],
                     r.get("roi_kind"),
                 r.get("subject_side_stops") if r.get("subject_side_stops") is not None else "—",
                     r["skin_pct"],
                     r.get("skin_angle_deg") if r.get("skin_angle_deg") is not None else "n/a",
                     r.get("skin_sat_R") if r.get("skin_sat_R") is not None else "n/a",
                     tone, r["bright70_pct"], r["bright90_pct"]))
    mdp = os.path.join(a.out, "检光_%s.md" % stamp)
    io.open(mdp, "w", encoding="utf-8").write(u"\n".join(md))
    print(u"帧数 %d｜摆幅 %s（%s）" % (len(rows), rng, rng_note))
    for r in rows:
        print(u"  %-18s IRE p50=%-6s 削顶%-5.2f%% 塌黑%-5.2f%% 光比%-6s 对比%-6s 肤色%-5.1f%% 角%s"
              % (str(r["frame"])[:18], r["ire_p50"], r["clip_hi_pct"], r["crushed_lo_pct"],
                 r["overall_stops_p90_p10"], r["contrast_stops_p95_p5"], r["skin_pct"],
                 r.get("skin_angle_deg") if r.get("skin_angle_deg") is not None else "n/a"))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
    print(u"报表：%s\n      %s" % (mdp, csvp))
    return 0


def csv_writer(fh):
    import csv
    wr = csv.DictWriter(fh, fieldnames=COLS + ["skin_off_line_deg"], extrasaction="ignore")
    wr.writeheader()
    return wr


if __name__ == "__main__":
    sys.exit(main())
