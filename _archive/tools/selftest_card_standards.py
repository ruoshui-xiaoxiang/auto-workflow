#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""selftest_card_standards.py — 卡片层三条硬规则的坏例闸（2026-11-01）

每条规则都带一个"必须红"的坏例，跑不通就退出 1：

  S1 角色/场景参考图的真人脸数（阈值按角色/场景分开）
  S2 说话人编号按本镜发声顺序，不按角色卡固定号
  S3 场景状态就近沿用；基础描述状态中性，不得与锚点打架

用法：
  py -3.12 D:/AIWorkflow/tools/selftest_card_standards.py [--project <project>/h3]

也可被 `h3_spider.cli selftest` 调用：`run_checks(project)` 返回
{ok, failed, checks}，不依赖命令行退出码。
"""
import argparse
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import h3_prompt_builder as B
import h3_precheck as P
from PIL import Image

CFM01 = r"D:/AIWorkflow/画风库/图片风格/已确认_帝国女军官_20261029/交付_2560/已确认-01_舰桥·背身全身_无框舷窗.png"
CFM02 = r"D:/AIWorkflow/画风库/图片风格/已确认_帝国女军官_20261029/交付_2560/已确认-02_舰桥·侧脸近景_指挥台.png"
DEFAULT_PROJECT = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"


def make_crop(src, box, out):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    x0, y0, x1, y1 = box
    im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))).save(out)
    return out


def render_shot(cards, sid):
    raw = [s for s in cards["shots"]["shots"] if s["id"] == sid][0]
    shot = B.normalize_shot(raw, cards["shots"].get("defaults") or {}, cards)
    return B.render(shot), shot


def run_checks(project=DEFAULT_PROJECT, verbose=True):
    """跑 S1/S2/S3；返回 {ok, failed, checks}，不抛异常。"""
    checks, failed = [], []

    def check(name, cond, detail=""):
        cond = bool(cond)
        if verbose:
            print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                                 ("  " + detail) if detail else ""))
        checks.append({"name": name, "ok": cond, "detail": detail})
        if not cond:
            failed.append(name)

    tmp = tempfile.mkdtemp(prefix="h3_selfcheck_")
    try:
        # S1：旧裁切（带背景船员）必须红，新裁切必须绿
        try:
            old_cmdr = make_crop(CFM02, [0.04, 0.02, 0.64, 0.98],
                                 os.path.join(tmp, "cmdr_old.png"))
            new_cmdr = make_crop(CFM02, [0.10, 0.02, 0.58, 1.00],
                                 os.path.join(tmp, "cmdr_new.png"))
            old_bridge = make_crop(CFM01, [0.28, 0.00, 1.00, 1.00],
                                   os.path.join(tmp, "bridge_old.png"))
            new_bridge = make_crop(CFM01, [0.42, 0.02, 1.00, 0.98],
                                   os.path.join(tmp, "bridge_new.png"))
            check("S1 旧角色图应检出 2 张真人脸",
                  P.count_faces(old_cmdr, kind="character") == 2,
                  "实际 %s" % P.count_faces(old_cmdr, kind="character"))
            check("S1 新角色图应检出 1 张",
                  P.count_faces(new_cmdr, kind="character") == 1)
            check("S1 旧场景图应检出 1 张（人）",
                  P.count_faces(old_bridge, kind="scene") == 1)
            check("S1 新场景图应检出 0 张",
                  P.count_faces(new_bridge, kind="scene") == 0)
        except Exception as e:
            check("S1 setup", False, repr(e))

        try:
            cards = B.load_project(project)
        except Exception as e:
            check("卡加载", False, repr(e))
            cards = None

        if cards:
            # S2：单人镜一律 S1；不按卡上固定号
            for sid in ("U02", "U05", "U08", "U11"):
                try:
                    text, shot = render_shot(cards, sid)
                except Exception as e:
                    check("S2 %s render" % sid, False, repr(e))
                    continue
                says = [l for l in text.splitlines() if "says" in l]
                hit = next((l for l in says if "(S1) says" in l),
                           says[0] if says else "")
                pos = hit.find("(S1) says")
                detail = ((hit[max(0, pos - 50):pos + 120] + "…")
                          if pos >= 0 else (hit[:120] + "…" if hit else "无 says 行"))
                check("S2 %s 说话人应为 (S1)" % sid, "(S1) says" in text,
                      "实际 %s" % detail)
                check("S2 %s 不应出现 (S2) says" % sid,
                      "(S2) says" not in text)

            # S3：基础描述状态中性；状态就近沿用
            try:
                sc = cards["scenes"]["scenes"]["bridge"]
                bad = [w for w in B.STATE_WORDS
                       if w in (sc.get("outside") or "").lower()]
                check("S3 场景基础 outside 应状态中性", not bad,
                      "残留 %s" % bad)

                t01, _ = render_shot(cards, "U01")
                t02, shot02 = render_shot(cards, "U02")
                t05, _ = render_shot(cards, "U05")
                t06, shot06 = render_shot(cards, "U06")
                check("S3 U01 不应出现 shattered",
                      "shattered" not in t01.lower())
                check("S3 U02 应沿用 U01 的 largely intact",
                      "largely intact" in t02)
                check("S3 U02 的 state_source 应为 U01",
                      (shot02.get("_scene") or {}).get("_state_source") == "U01")
                check("S3 U05 应为 roughly half", "roughly half" in t05)
                check("S3 U06 应沿用 U05 的 roughly half",
                      "roughly half" in t06)
                check("S3 U06 的 state_source 应为 U05",
                      (shot06.get("_scene") or {}).get("_state_source") == "U05")
            except Exception as e:
                check("S3 setup", False, repr(e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return {"ok": not failed, "failed": failed, "checks": checks}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    a = ap.parse_args(argv)
    r = run_checks(a.project, verbose=True)
    print("\n%d 项失败" % len(r["failed"]))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
