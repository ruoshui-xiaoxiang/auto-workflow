# -*- coding: utf-8 -*-
"""qc_batch_consistency.py —— 批内 DINO 相对尺（10-03 批 7-4 接进引擎；11-04 判据换轴）。

它只回答一个问题：**同一批产物是不是"同一个人、同一身衣服、同一个姿态族"**。
它**不回答**"这批画风漂没漂"，也不回答"这张能不能进片"、"好不好看"。

🔴 11-04 改名原因（这次改动的全部实质，别略过）：
  旧文档把它写成"画风／光照／介质层在批内漂没漂"，但它的取法是**脸框归一裁「头＋上身」
  再送 DINOv2**——那个 patch 里占篇幅最大的是脸、头发和衣服，所以它量的是**身份与造型的
  批内一致度**。11-04 一批主题裸跑（`古风大家闺秀`，四张人判都好，只差在换脸／换服制／换道具）
  被它按旧口径判成 FAIL（均值 0.761／最低 0.716），就是这么来的。
  同日离线复核（`D:/AIWorkflow/tmp/_ruler_probe/`，七批全量重跑）给出两条硬结论：
    ① 它**抓不到画风**：三批人判打回的（画风漂 0.770/0.728、变白 0.853/0.817、
       偏卡通 0.846/0.824）里只有第一批被拦，后两批读数比未打回批还"干净"；
    ② 任何**批内相对**统计都抓不到"整批一起偏"——12 个风格标量（L／饱和／明暗占比／
       拉普拉斯方差／梯度／中间调／平坦比）的相对离散，三批打回的全部**低于**三批未打回的。
       打回是因为它们**一起**偏白／偏卡通，不是批内互相散。⇒ 想抓它得靠锚图／绝对带，
       而绝对带换项目就失效（10-02 实测 3/3 假拦），那条路仍是"只报不拦"。
  ⇒ 所以这次**不新造画风尺**（按②造不出来），只做两件能证伪的事：
     判据改名为它实际量的东西；加 `identity_lock` 声明——**只有"这批本该同一个人／同一身
     衣服"时才允许它拦人**，主题裸跑／探索批只报数不拦（verdict=report_only，读数照进台账）。

★ 为什么只有这一把尺进了引擎，绝对带没进（用户 10-02 批 6 问 4 裁定：
「只接相对尺，绝对带只报不拦」）：
  10-02 实测把 `qc.py` 那套绝对带（faceL／faceWhite／lpalex／gedge／faceHR）拿去测
  **另一个项目的未打回基线稿 ⇒ 3/3 全 FAIL**。绝对带是**在一个项目的 12 张人判样本上
  标定的**，换项目就失效；而"同批互比"是产物之间比，不依赖锚图也不依赖项目标定，
  跨项目仍成立（通用角色库三张互比 均值 0.801／最低 0.776，落在它自己的口径里）。

★ 算法与标定它的那份原稿逐字对齐（`D:/AIWorkflow/tmp/wzy/qc.py` 的
  `norm_patch` + `dino_emb` + 批内互比那三行）。**不是"另写一把更好的尺"**：
  阈值 0.75／0.80 是在那套取法上标出来的，取法一改数就不可比，带就作废。
  对齐点：脸框归一取「头＋上身」→ 384×384 INTER_AREA → DINOv2-base `pooler_output`
  → 两两余弦 → `min < 0.75` 拦、`mean < 0.80` 警示。
  已知带（同一取法实测；⚠️ 这是**身份带**不是画风带，11-04 逐位复现）：
    身份散：古风主题裸跑 0.761／0.716、dz0b2 0.770／0.728、dz0b 0.795／0.689
    身份稳：标定 F 批 0.876／0.844（＝`tmp/wzy/dz0b2ppp/F1..F3_raw.png`，
            11-04 复跑 0.8765／0.8443，与 10-02 登记逐位吻合）、
            机甲主题裸跑 0.874／0.831、dz0f 六张 0.911／0.857
    （`dz0f` 那批六张不是标定素材，别拿它的数和 0.876 混着引用。）

★ 三条不许含糊的规矩：
  ① **可测的图少于 2 张 ⇒ verdict = not_measured，绝不写 ok**。单张产物批内互比在数学上
     不存在，把它当"通过"是最坏的一种假阴（GAP-G3 抱怨的就是裁判件没接线，
     接了线却静默放行是它的升级版）。
  ② 检不到脸的图**排除并计数**，不猜、不用整图代替（整图和脸归一 patch 不是同一个量）。
     全部图都没脸 ⇒ not_measured（原因写清楚），不是 pass。
  ③ 模型／依赖取不到 ⇒ not_measured ＋ 如实报缺什么，**不抛错也不放行**。
     本机默认 Python 有 torch／cv2／transformers／insightface，**缺 lpips**——本尺用不到它
     （lpips 是绝对带那侧的），所以不需要第二个解释器；DINO 走 `local_files_only=True`，
     **不联网**，免得引擎出图步骤卡在一次下载上。

★ 它测不到什么（10-03 接线当天量的，11-04 又量了一遍，别把"过这把尺"读成"这批能进片"）：
  同一取法下，人判打回的三批里只有**画风漂**那批被这把尺抓到：
    dz0b2（画风漂）  均值 0.770 最低 0.728 → FAIL ✅ 抓到了（但抓到的是脸／装也跟着散）
    dz0b2p（变白）   均值 0.853 最低 0.817 → ok   ✗ 抓不到
    dz0b2pp（偏卡通）均值 0.846 最低 0.824 → ok   ✗ 抓不到
    标定 F 批（未打回）均值 0.876 最低 0.844 → ok  ✅ 与 10-02 登记逐位吻合（差 <5e-5）
  11-04 补的两轮离线量测（`tmp/_ruler_probe/candidates.py`＋`scalars.py`，七批）：
    换整图 DINO、换色板／纹理直方图余弦、换 12 个风格标量的相对离散——
    **五种取法在"打回批 vs 未打回批"上全部重叠，无一硬分离**；
    且标量离散那一轮里，三批打回的**每一个标量都比三批未打回的更不散**。
  ⇒ 结论不是"尺子不够好"，是**批内相对量在原理上看不见"整批一起偏"**：
     一起偏白、一起偏卡通，批内照样整齐。要抓它只能靠锚图／绝对带（只报不拦那条侧）。
     所以"画风一致性"这一维**交人眼**（图发飞书是他审片的默认通道），
     这把尺只负责它真能负责的那一维：**这批是不是同一个人、同一身衣服**。

用法：
  python tools/qc_batch_consistency.py --dir <批次夹> [--print-json] [--strict]
  python tools/qc_batch_consistency.py --images a.png b.png c.png
  # 引擎里：from qc_batch_consistency import measure  （tasks.py t_comfyui 收尾调用）

退出码：默认恒 0（只报不拦＝给 CLI 的约定，拦由引擎做）；`--strict` 时 fail 退 1。
"""

import argparse
import glob
import io
import json
import os
import sys

# ── 阈值（权威就在这个文件里；`thresholds_registry.json` 记的是"指针"，不是第二份值）──
DINO_BATCH_MIN_FAIL_LO = 0.75
DINO_BATCH_MEAN_WARN_LO = 0.80

PATCH = 384
MODEL_ID = "facebook/dinov2-base"
HF_CACHE = "D:/AIWorkflow/models/hf"
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

_model = None
_processor = None
_face_app = None
_lazy_error = None


def _np_cv():
    import numpy as np
    import cv2
    return np, cv2


def lazy(device="cpu"):
    """加载一次，进程内复用。失败不抛——把原因留在 _lazy_error，由调用方如实记 not_measured。"""
    global _model, _processor, _face_app, _lazy_error
    if _model is not None and _face_app is not None:
        return True
    if _lazy_error:
        return False
    try:
        import torch
        from transformers import AutoModel, AutoImageProcessor
        from insightface.app import FaceAnalysis
        _processor = AutoImageProcessor.from_pretrained(MODEL_ID, cache_dir=HF_CACHE,
                                                        local_files_only=True)
        _model = AutoModel.from_pretrained(MODEL_ID, cache_dir=HF_CACHE,
                                           local_files_only=True).to(device).eval()
        _face_app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
        _face_app.prepare(ctx_id=-1, det_size=(1024, 1024))
        return True
    except Exception as e:
        _lazy_error = "%s: %s" % (type(e).__name__, str(e)[:200])
        return False


def imread(path):
    np, cv2 = _np_cv()
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def largest_face(img):
    """取面积最大的那张脸（与原稿同一取舍：多人时按脸框面积，不按置信度）。"""
    np, cv2 = _np_cv()
    if not lazy():
        return None, None
    fs = _face_app.get(img)
    if not fs:
        return None, None
    f = max(fs, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    return f, [int(v) for v in f.bbox]


def norm_patch(img):
    """按脸尺寸归一取「头＋上身」→ 胸像与全身可比，消掉景别这个混杂变量。
    ⚠ 这几行几何是从原稿搬的，**别顺手改比例**：改了就和 0.75／0.80 那两条带不同源。"""
    np, cv2 = _np_cv()
    f, box = largest_face(img)
    if f is None:
        return None
    x1, y1, x2, y2 = box
    H, W = img.shape[:2]
    fw, fh = x2 - x1, y2 - y1
    cx = (x1 + x2) // 2
    a, b = max(0, int(cx - 1.5 * fw)), min(W, int(cx + 1.5 * fw))
    c, d = max(0, int(y1 - 0.9 * fh)), min(H, int(y2 + 2.2 * fh))
    crop = img[c:d, a:b]
    if crop.size == 0:
        return None
    return cv2.resize(crop, (PATCH, PATCH), interpolation=cv2.INTER_AREA)


def dino_emb(bgr, device="cpu"):
    import torch
    np, cv2 = _np_cv()
    x = _processor(images=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), return_tensors="pt").to(device)
    with torch.no_grad():
        return _model(**x).pooler_output[0].cpu().numpy().astype(np.float64)


def cos(a, b):
    np, _cv2 = _np_cv()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


# ── 最差一对的"差在哪一维"（只报数，不参与 verdict）──────────────────
# 这批标量抄自历史两份实测记录用过的量（blanch_measure.json 的 L／明暗占比、
# cartoon_measure.json 的 lapvar／edge_gmag／midtone／flat），再加饱和与色度。
# ⚠️ 它们**没有阈值**：10-02 裁定"绝对带只报不拦"仍然有效，这里只把两两差值摆出来，
#     判"像不像同一画风"仍以人眼为准（用户 KPI，见文件头）。
STYLE_SCALARS = ("L_mean", "L_std", "sat_mean", "val_mean",
                 "bright_gt200", "dark_lt80", "lapvar", "edge_gmag", "midtone", "flat")


def style_scalars(path):
    """一张图 → 一组色调／介质标量（512×512 重采样后取，消掉尺寸这个混杂变量）。"""
    np, cv2 = _np_cv()
    img = imread(path)
    if img is None:
        return None
    s = cv2.resize(img, (512, 512), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(s, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY)
    L = lab[:, :, 0].astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    return {
        "L_mean": round(float(L.mean()), 2),
        "L_std": round(float(L.std()), 2),
        "sat_mean": round(float(hsv[:, :, 1].mean()), 2),
        "val_mean": round(float(hsv[:, :, 2].mean()), 2),
        "bright_gt200": round(float((L > 200).mean()), 4),
        "dark_lt80": round(float((L < 80).mean()), 4),
        "lapvar": round(float(lap.var()), 1),
        "edge_gmag": round(float(cv2.magnitude(gx, gy).mean()), 2),
        "midtone": round(float(((L > 80) & (L < 200)).mean()), 4),
        "flat": round(float((np.abs(lap) < 2).mean()), 4),
    }


def pair_style_delta(pa, pb):
    """那一对的标量差（|a−b|，相对量＝差／两者均值）。取不到图就返回 None。"""
    np, _cv2 = _np_cv()
    sa, sb = style_scalars(pa), style_scalars(pb)
    if sa is None or sb is None:
        return None
    out = {}
    for k in STYLE_SCALARS:
        a, b = float(sa[k]), float(sb[k])
        base = (abs(a) + abs(b)) / 2.0
        out[k] = {"abs": round(abs(a - b), 4),
                  "rel": round(abs(a - b) / base, 4) if base > 1e-6 else None}
    out["_per_image"] = {os.path.basename(pa): sa, os.path.basename(pb): sb}
    return out


def list_images(dir_path):
    out = []
    for ext in IMG_EXTS:
        out += glob.glob(os.path.join(dir_path, "*" + ext))
        out += glob.glob(os.path.join(dir_path, "*" + ext.upper()))
    # qc.json／对照表之类不是产物：靠"名字带 _sheet/对照/montage"排除会变成第二套判据，
    # 所以这里只按目录直收，调用方（引擎）传进来的是它自己登记的文件清单。
    return sorted(set(out))


def measure(paths, device="cpu", identity_lock=True):
    """核心入口：返回结构化结果。
    verdict ∈ ok／warn／fail／report_only／not_measured。

    `identity_lock`（11-04 新增，默认 True＝现役行为不变）：
      True  ⇒ 这批**声明了"应当同一个人／同一身衣服"**（定妆、i2i 派生、按编号精修），
              身份散就拦（判序与阈值一个没动）。
      False ⇒ 主题裸跑／探索批：这批本来就该换脸换装，身份离散不是缺陷。
              读数照量照进台账，但 verdict 降级为 `report_only`，**引擎不拦**。
              原判序记在 `verdict_by_identity_axis` 里，不留暗账。
    """
    res = {"schema": 2, "metric": "dino_batch_pairwise_cosine",
           "axis": "同批「同脸同装」一致度（不是画风）",
           "model": MODEL_ID, "device": device,
           "identity_lock": bool(identity_lock),
           "thresholds": {"min_fail_lo": DINO_BATCH_MIN_FAIL_LO,
                          "mean_warn_lo": DINO_BATCH_MEAN_WARN_LO},
           "n_input": len(paths), "n_measurable": 0, "n_no_face": 0, "n_unreadable": 0,
           "mean": None, "min": None, "verdict": "not_measured",
           "reason": None, "per_image": []}
    if not paths:
        res["reason"] = "没有产物可量（清单为空）"
        return res
    if not lazy(device):
        res["reason"] = "尺子起不来，缺的是环境不是片子：%s" % _lazy_error
        return res
    embs, names, measured = [], [], []
    for p in paths:
        try:
            img = imread(p)
        except Exception as e:
            res["n_unreadable"] += 1
            res["per_image"].append({"file": os.path.basename(p), "state": "unreadable",
                                     "err": "%s" % type(e).__name__})
            continue
        if img is None:
            res["n_unreadable"] += 1
            res["per_image"].append({"file": os.path.basename(p), "state": "unreadable"})
            continue
        patch = norm_patch(img)
        if patch is None:
            res["n_no_face"] += 1
            res["per_image"].append({"file": os.path.basename(p), "state": "no_face"})
            continue
        embs.append(dino_emb(patch, device))
        names.append(os.path.basename(p))
        measured.append(p)
        res["per_image"].append({"file": os.path.basename(p), "state": "measured"})
    res["n_measurable"] = len(embs)
    if len(embs) < 2:
        res["reason"] = ("可测图只有 %d 张（<2）⇒ 批内互比在数学上不存在。"
                         "检不到脸 %d 张、读不出 %d 张——**这不是通过，是未测量**"
                         % (len(embs), res["n_no_face"], res["n_unreadable"]))
        return res
    np, _cv2 = _np_cv()
    m = np.array([[cos(x, y) for y in embs] for x in embs])
    iu = np.triu_indices(len(embs), 1)
    pair_vals = m[iu]
    mn, av = float(pair_vals.min()), float(pair_vals.mean())
    k = int(np.argmin(pair_vals))
    ia, ib = int(iu[0][k]), int(iu[1][k])
    res["min"], res["mean"] = round(mn, 4), round(av, 4)
    res["worst_pair"] = [names[ia], names[ib]]
    # 判序固定：先看最低（拦），再看均值（警示）。两条同时命中时报 fail，
    # 因为"有一对明显不是一批"比"整体偏散"更要紧。
    if mn < DINO_BATCH_MIN_FAIL_LO:
        res["verdict"] = "fail"
    elif av < DINO_BATCH_MEAN_WARN_LO:
        res["verdict"] = "warn"
    else:
        res["verdict"] = "ok"
    res["verdict_by_identity_axis"] = res["verdict"]
    # 11-04：这批没声明身份锁（主题裸跑／探索批）⇒ 换脸换装属预期，降级为只报。
    # ok 不降成 report_only（"量过且齐"比"只报"更强，别把好消息写成坏消息）。
    if not res["identity_lock"] and res["verdict"] in ("fail", "warn"):
        res["verdict"] = "report_only"
        res["reason"] = ("这批未声明身份锁（主题裸跑／探索批）⇒ 换脸换装属预期，"
                         "身份轴判序 %s 只报不拦" % res["verdict_by_identity_axis"])
    # 最差一对到底差在哪一维：身份轴已经给了数，这里补色调／介质（无阈值，不参与判序）。
    try:
        res["worst_pair_delta"] = pair_style_delta(measured[ia], measured[ib])
    except Exception as e:
        res["worst_pair_delta"] = None
        res["worst_pair_delta_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    res["bands_note"] = ("这把尺量的是**身份与造型**不是画风——身份散的历史读数 "
                         "0.761/0.716（古风主题裸跑）、0.770/0.728（dz0b2）；"
                         "身份稳的 0.876/0.844（标定 F 批）、0.874/0.831（机甲主题裸跑）。"
                         "画风漂没漂它判不了（11-04 五种取法零分离）⇒ 交人眼")
    return res


def _delta_brief(res):
    """把最差一对的色调／介质差压成一句（只报数，不设阈值）。"""
    d = res.get("worst_pair_delta") or {}
    if not d:
        return None
    tone = max((v for k, v in d.items()
                if k != "_per_image" and v and v.get("rel") is not None),
               key=lambda v: v["rel"], default=None)
    if not tone:
        return None
    key = max((k for k, v in d.items()
               if k != "_per_image" and v and v.get("rel") is not None),
              key=lambda k: d[k]["rel"])
    return "那一对的色调／介质最大差在 %s（相对 %.2f）——只报数，不判" % (
        key, d[key]["rel"])


def explain(res):
    """给人读的一行；数从 res 里取，不另算一遍。"""
    v = res.get("verdict")
    if v == "not_measured":
        return "批内身份尺（DINO 脸框互比）：**未测量**（%s）" % res["reason"]
    lock = "身份锁开" if res.get("identity_lock", True) else "身份锁关（只报不拦）"
    line = ("批内身份尺（DINO 脸框互比）：均值 %.3f 最低 %.3f → %s｜%s｜最差一对 %s"
            % (res["mean"], res["min"], str(v).upper(), lock,
               "↔".join(res.get("worst_pair") or [])))
    if v == "report_only":
        line += "（身份轴判序本应是 %s）" % res.get("verdict_by_identity_axis")
    brief = _delta_brief(res)
    if brief:
        line += "｜" + brief
    return line + "｜带：" + res["bands_note"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="批次夹（直收里面的图；引擎内调用请走 --images）")
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--device", default=os.environ.get("QC_BATCH_DEVICE", "cpu"))
    ap.add_argument("--identity-lock", default="on", choices=["on", "off"],
                    help="off＝这批没声明身份锁（主题裸跑／探索批）⇒ fail/warn 降级为只报")
    ap.add_argument("--print-json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="fail 时退 1（默认只报不拦）")
    a = ap.parse_args(argv)
    paths = list(a.images or [])
    if a.dir:
        paths = list_images(a.dir)
    res = measure(paths, a.device, identity_lock=(a.identity_lock == "on"))
    if a.print_json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(explain(res))
    if a.strict and res["verdict"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
