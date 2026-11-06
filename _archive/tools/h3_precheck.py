#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""h3_precheck.py — H3 项目的素材预检（项目无关）

在提交任何一个镜头之前跑，拦的是"素材本身就不对"这一类问题：

  1. 卡完整性（复用 h3_prompt_builder.lint_cards）
  2. 角色参考图：裁切后必须正好 1 张脸（0 张=裁掉了人，≥2 张=双人图没裁开）
  3. 场景参考图：裁切后必须 0 张脸（有脸会把人物姿态带进所有镜）
  4. shots 里引用的 image / last_image / images 必须存在
  5. 参考图的裁切框必须在图内、面积不能太小

用法：
  py h3_precheck.py --project <project>/h3
  py h3_precheck.py --project <project>/h3 --json out.json
  py h3_precheck.py --project <project>/h3 --trace [precheck_trace.json]
"""
import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import h3_prompt_builder as B  # noqa: E402
import h3_trace as T  # noqa: E402

# OpenCV 5 移除了 Haar 级联分类器，且级联 xml 在中文路径下读不了。
# 改用 YuNet DNN（232 KB），模型放在 ASCII 路径 tools/models/ 下。
# 模型缺失时判 FACE_OK=False，预检直接报 error——不再用 info 放行，
# 否则"0 error"会是一句没有依据的结论。
_YUNET_PATH = os.path.join(HERE, "models", "yunet.onnx")
# 2026-11-01 角色/场景分开量：同一阈值管两类素材不成立。
# 角色图要低阈值抓背景里的第二个人（旧 cmdr 图背景船员 score=0.63、脸宽 2.0%）；
# 场景图要高一点并忽略小噪点（新 bridge 图在 0.5 会冒 1.3% 的假脸）。
FACE_SCORE = 0.6
FACE_MIN_WIDTH_PCT = {"character": 0.015, "scene": 0.030}


def _load_yunet():
    try:
        if not os.path.isfile(_YUNET_PATH) or os.path.getsize(_YUNET_PATH) < 10000:
            return None
        return cv2.FaceDetectorYN.create(_YUNET_PATH, "", (320, 320),
                                         FACE_SCORE, 0.3, 5000)
    except Exception:
        return None


_YUNET = _load_yunet()
FACE_OK = _YUNET is not None


def imread_unicode(path):
    """OpenCV 的 imread 在 Windows 上读不了中文路径，用 fromfile + imdecode。"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def count_faces(path, crop=None, kind="character"):
    img = imread_unicode(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    if crop:
        x0, y0, x1, y1 = [float(v) for v in crop]
        img = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if img.size == 0:
        return 0
    if not FACE_OK:
        return -1
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(_YUNET_PATH, "", (w, h), FACE_SCORE, 0.3, 5000)
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    if faces is None:
        return 0
    min_w = w * FACE_MIN_WIDTH_PCT.get(kind, FACE_MIN_WIDTH_PCT["character"])
    return int(sum(1 for b in faces if float(b[2]) >= min_w))


def resolve(base_dir, p, cards=None):
    if not p:
        return None
    if os.path.isabs(p):
        return p
    # 镜头里的 cmdr / adjutant / bridge 是卡名，指向裁切产物
    if cards:
        names = set((cards["characters"].get("roles") or {}).keys()) |                 set((cards["scenes"].get("scenes") or {}).keys())
        if p in names:
            return os.path.normpath(os.path.join(base_dir, "assets", "crops", p + ".png"))
        assets = (cards["shots"].get("defaults") or {}).get("assets_dir")
        if assets:
            return os.path.normpath(os.path.join(assets, p))
    return os.path.normpath(os.path.join(base_dir, p))


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="H3 素材预检")
    ap.add_argument("--project", required=True)
    ap.add_argument("--json", default=None)
    ap.add_argument("--trace", nargs="?", const="", default=None,
                    help="写资产链 trace；不给路径则写 <project>/out/precheck_trace.json")
    ap.add_argument("--comfy-input", default=None,
                    help="ComfyUI input 目录；给了就比对暂存图与项目裁切图的 sha1，防止同名旧图顶替")
    a = ap.parse_args(argv)

    cards = B.load_project(a.project)
    proj = cards["dir"]
    issues = []

    if not FACE_OK:
        issues.append({"code": "face_detector_unavailable", "level": "error",
                       "msg": "人脸检测不可用（%s 缺失/加载失败）：预检不能放行，"
                              "先修检测器再谈 0 error" % _YUNET_PATH})

    # 1) 卡
    for i in B.lint_cards(cards):
        issues.append({"code": i.code, "level": i.level, "msg": i.msg})

    # 2) 角色参考图：正好一张脸
    for name, c in (cards["characters"].get("roles") or {}).items():
        ref = c.get("reference") or {}
        path = resolve(proj, ref.get("file"))
        if not path:
            continue
        if not os.path.isfile(path):
            issues.append({"code": "ref_missing", "level": "error",
                           "msg": "角色 %s 参考图不存在：%s" % (name, path)})
            continue
        n = count_faces(path, ref.get("crop"), kind="character")
        if n == -1:
            continue
        if n is None:
            issues.append({"code": "ref_unreadable", "level": "error",
                           "msg": "角色 %s 参考图读不出：%s" % (name, path)})
        elif n >= 2:
            issues.append({"code": "ref_face_count", "level": "error",
                           "msg": "角色 %s 裁切后有 %d 张正面脸（≥2 说明是多人图，需要裁开）"
                                  % (name, n)})
        elif n == 0:
            # 侧脸/背影角色图很常见，Haar 正面检测会漏，交人确认
            issues.append({"code": "ref_face_none", "level": "warn",
                           "msg": "角色 %s 裁切后检测不到正面脸（可能是侧脸/背影，确认裁切里只有一个人）"
                                  % name})

    # 3) 场景参考图：不能有脸
    for name, s in (cards["scenes"].get("scenes") or {}).items():
        ref = s.get("reference") or {}
        path = resolve(proj, ref.get("file"))
        if not path:
            continue
        if not os.path.isfile(path):
            issues.append({"code": "scene_ref_missing", "level": "error",
                           "msg": "场景 %s 参考图不存在：%s" % (name, path)})
            continue
        n = count_faces(path, ref.get("crop"), kind="scene")
        if n == -1:
            continue
        elif n:
            issues.append({"code": "scene_has_face", "level": "error",
                           "msg": "场景 %s 参考图里有 %d 张脸（会把人物姿态带进每一镜）" % (name, n)})

    # 4) 镜头引用的图片
    shots = (cards["shots"].get("shots") or [])
    for s in shots:
        sid = s.get("id", "?")
        need = []
        for k in ("image", "last_image"):
            if s.get(k):
                need.append((k, s[k]))
        for img in s.get("images") or []:
            need.append(("images", img))
        for k, p in need:
            if not os.path.isfile(resolve(proj, p, cards)):
                issues.append({"code": "shot_image_missing", "level": "error",
                               "msg": "[%s] %s 指向的图不存在：%s" % (sid, k, p)})
        if s.get("mode") in ("fl2va",) and not s.get("last_image"):
            issues.append({"code": "fl2va_no_last", "level": "warn",
                           "msg": "[%s] fl2va 没有 last_image；渲染器会按 I2VA 首行处理" % sid})

    # 5) 裁切面积
    for group, key in ((cards["characters"].get("roles") or {}, "角色"),
                       (cards["scenes"].get("scenes") or {}, "场景")):
        for name, c in group.items():
            crop = (c.get("reference") or {}).get("crop")
            if not crop:
                continue
            x0, y0, x1, y1 = [float(v) for v in crop]
            area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            if area < 0.08:
                issues.append({"code": "crop_too_small", "level": "warn",
                               "msg": "%s %s 的裁切只占 %.1f%% 面积" % (key, name, area * 100)})

    # 6) 暂存图与项目裁切图是否同一份（同名旧图是最隐蔽的顶替）
    if a.comfy_input:
        inp = os.path.abspath(a.comfy_input)
        for group in (cards["characters"].get("roles") or {},
                      cards["scenes"].get("scenes") or {}):
            for name in group:
                staged = os.path.join(inp, name + ".png")
                src = os.path.join(proj, "assets", "crops", name + ".png")
                if not os.path.isfile(staged):
                    continue
                if not os.path.isfile(src):
                    issues.append({"code": "crop_missing", "level": "error",
                                   "msg": "%s 的裁切产物不存在：%s（先跑 h3_crop.py）"
                                          % (name, src)})
                    continue
                if _sha1(staged) != _sha1(src):
                    issues.append({"code": "staged_stale", "level": "error",
                                   "msg": "%s 在 ComfyUI input 里是旧图（sha1 不同）：%s；"
                                          "这批会用错图" % (name, staged)})

    errs = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    infos = [i for i in issues if i["level"] == "info"]
    for i in issues:
        print("%-5s %-18s %s" % (i["level"].upper(), i["code"], i["msg"]))
    print("\n预检：%d error / %d warn / %d info / %d 镜"
          % (len(errs), len(warns), len(infos), len(shots)))
    if a.json:
        with io.open(a.json, "w", encoding="utf-8") as f:
            f.write(json.dumps(issues, ensure_ascii=False, indent=2))
    if a.trace is not None:
        trace_path = os.path.abspath(a.trace or os.path.join(proj, "out", "precheck_trace.json"))
        try:
            tr = T.build_precheck_trace(cards, proj, a.comfy_input,
                                        count_faces, B.scene_for_shot, resolve)
            tr["issues"] = issues
            os.makedirs(os.path.dirname(trace_path) or ".", exist_ok=True)
            with io.open(trace_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(tr, ensure_ascii=False, indent=1))
            print("trace: %s" % trace_path)
        except Exception as e:
            print("TRACE FAIL: %s" % e, file=sys.stderr)
            return 1
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
