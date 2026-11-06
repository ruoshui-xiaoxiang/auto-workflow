# -*- coding: utf-8 -*-
r"""打戏编排验证 · 首帧出图（火山 Seedream i2i，挂定妆脸锚）。

分两步跑，先看小样再铺开：
  py gen_combat_frames.py 1     # 只出 C01 / C04（两张挂脸锚的主体帧）
  py gen_combat_frames.py 2     # 出 C02 / C03 / C05（C02、C05 从 C01 裁一块无脸参考）
  py gen_combat_frames.py txt   # 只写 5 份 H3 视频提示词 + 预缩 864x1536，不出图

铁律落点：
  - 指定角色必挂参考图，纯文字锁不住脸 → C01 挂玄袍男锚、C04/C05 挂素衣女锚。
  - 参考图会像素级继承杂物与人脸 → 当参考用的裁切一律避开头部（y 从 30% 往下）。
  - 验证类出图手填提示词、关服务端润色（不传 --optimize-prompt）。
  - arkcli 落盘是固定名，每张跑完立刻改名，否则互相覆盖。
"""
import json
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import combat_prompts as CP  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(HERE, "首帧")          # Seedream 原生 1440x2560
H3DIR = os.path.join(HERE, "首帧_h3864")     # 预缩到 H3 出片尺寸
REFS = os.path.join(HERE, "参考裁切")
TXT = os.path.join(HERE, "h3_prompts")
LOG = os.path.join(HERE, "calls.log")

ARK = os.path.join(os.path.expanduser("~"), "AppData", "Local", "nodejs",
                   "node_modules", "@volcengine", "ark-cli", "bin",
                   "arkcli-windows-amd64.exe")
EP = "ep-20260907000534-mlrdb"
SIZE = "1440x2560"                            # 9:16，与 864x1536 同比例，纯等比下采样
ANCHOR_DIR = r"E:\创作\烬骨辞\图\定妆"
ANCHORS = {"char_xiaojinyan.png": "萧烬言", "char_shenqingci.png": "沈清辞"}


def log(msg):
    line = msg.strip()
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def crop_ref(src_png, box, dst_png):
    """按归一化框裁一块当参考；cv2 读不了中文路径，走 numpy 字节中转。"""
    buf = np.frombuffer(open(src_png, "rb").read(), np.uint8)
    im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit("参考源读不了：%s" % src_png)
    H, W = im.shape[:2]
    x0, y0, x1, y1 = box
    cut = im[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
    os.makedirs(os.path.dirname(dst_png), exist_ok=True)
    ok, out = cv2.imencode(".png", cut)
    out.tofile(dst_png)
    log("  参考裁切 %s -> %s（%dx%d）" % (os.path.basename(src_png),
                                        os.path.basename(dst_png), cut.shape[1], cut.shape[0]))
    return dst_png


def gen(sid, prompt, inputs, anchor_of):
    dst = os.path.join(FRAMES, "%s.png" % sid)
    if os.path.exists(dst):
        log("%s 已有首帧，跳过（要重出先删 %s）" % (sid, dst))
        return dst
    tmp = os.path.join(HERE, "_tmp_%s" % sid)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    cmd = [ARK, "+gen", prompt, "--format", "json", "--size", SIZE,
           "--save-to", tmp, "--output-format", "png", "--no-open"]
    for p in inputs:
        cmd += ["--input", "@" + p]
    with open(LOG, "a", encoding="utf-8") as f:      # 参数留痕：裸调用不进批次归档，自己记
        f.write("%s CMD %s\n" % (sid, json.dumps(cmd, ensure_ascii=False)))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", shell=False)
    got = [os.path.join(tmp, n) for n in os.listdir(tmp)] if os.path.isdir(tmp) else []
    got = [p for p in got if p.lower().endswith((".png", ".jpg", ".jpeg"))]
    if r.returncode != 0 or not got:
        log("%s FAIL rc=%s\n%s" % (sid, r.returncode, ((r.stdout or "") + (r.stderr or ""))[-800:]))
        return None
    os.makedirs(FRAMES, exist_ok=True)
    shutil.move(got[0], dst)
    shutil.rmtree(tmp, ignore_errors=True)
    # 身份卡片：让机器能核对"这一镜挂的是谁"，不靠肉眼猜标签
    card = {"character": anchor_of or "无人物", "shot": sid,
            "anchors": [os.path.basename(p) for p in inputs],
            "anchor_kind": "face" if anchor_of and not anchor_of.startswith("仅") else "prop_or_env"}
    open(dst + ".anchor.json", "w", encoding="utf-8").write(
        json.dumps(card, ensure_ascii=False, indent=2))
    log("  OK %s  %dx%d  参考=%s" % (sid, *reversed(cv2.imdecode(
        np.frombuffer(open(dst, "rb").read(), np.uint8), cv2.IMREAD_COLOR).shape[:2]),
        [os.path.basename(p) for p in inputs] or "无"))
    return dst


def stage1():
    for s in CP.SHOTS:
        if s["sid"] not in ("C01", "C04"):
            continue
        a = os.path.join(ANCHOR_DIR, s["anchor_img"])
        if not os.path.exists(a):
            raise SystemExit("脸锚不存在：%s" % a)
        prompt = "%s\n%s\n%s\n%s\n竖屏 9:16 高清单帧，画面里不要任何文字。" % (
            CP.SCENE, CP.AXIS, s["img"], CP.STYLE)
        gen(s["sid"], prompt, [a], ANCHORS[s["anchor_img"]])


def stage2():
    c01 = os.path.join(FRAMES, "C01.png")
    if not os.path.exists(c01):
        raise SystemExit("先跑 stage 1 出 C01")
    for s in CP.SHOTS:
        sid = s["sid"]
        if sid in ("C01", "C04"):
            continue
        inputs, who = [], None
        if s.get("ref_from"):
            _, box = s["ref_from"]
            inputs = [crop_ref(c01, box, os.path.join(REFS, "%s_ref.png" % sid))]
            who = "仅取道具/环境，不采用人物"
        if s.get("anchor_img"):
            a = os.path.join(ANCHOR_DIR, s["anchor_img"])
            inputs.insert(0, a)
            who = ANCHORS[s["anchor_img"]]
        head = "%s\n%s\n%s\n%s" % (CP.SCENE, CP.AXIS, s["img"], CP.STYLE)
        if s.get("role_note") and inputs:
            head += "\n" + s["role_note"]
        gen(sid, head + "\n竖屏 9:16 高清单帧，画面里不要任何文字。", inputs, who)


def write_txt():
    os.makedirs(TXT, exist_ok=True)
    os.makedirs(H3DIR, exist_ok=True)
    n = 0
    for s in CP.SHOTS:
        sid = s["sid"]
        blocks = [
            "【场景与环境】" + CP.SCENE + CP.AXIS,
            "【主体与关系】" + CP.SUBJ[sid],
            "【事件脚本】" + s["vid_evt"],
            "【镜头】" + s["vid_cam"],
            "【风格与光影】" + CP.STYLE,
            "【声音】" + CP.SOUND[sid],
            "【保持一致】" + CP.KEEP.format(beat=CP.BEAT[sid],
                                          extra=CP.KEEP_EXTRA[sid]),
        ]
        open(os.path.join(TXT, "%s.txt" % sid), "w", encoding="utf-8").write(
            "\n\n".join(blocks) + "\n")
        n += 1
        src = os.path.join(FRAMES, "%s.png" % sid)
        if os.path.exists(src):
            im = cv2.imdecode(np.frombuffer(open(src, "rb").read(), np.uint8), cv2.IMREAD_COLOR)
            small = cv2.resize(im, (864, 1536), interpolation=cv2.INTER_AREA)
            ok, out = cv2.imencode(".png", small, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            out.tofile(os.path.join(H3DIR, "%s.png" % sid))
    log("已写 %d 份 H3 提示词；预缩产物在 %s" % (n, H3DIR))


if __name__ == "__main__":
    which = (sys.argv[1] if len(sys.argv) > 1 else "1").lower()
    {"1": stage1, "2": stage2, "txt": write_txt}[which]()
