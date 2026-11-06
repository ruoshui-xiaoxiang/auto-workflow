# -*- coding: utf-8 -*-
r"""本地出图通道跑「范例光影骨架」——手填提示词、关润色、零成本。

提示词**不重写一遍**：直接从待审文档 C 段抓 K1–K6 那六条，免得出现两份事实源。
默认只跑 K1/K3/K4/K5 四条（分别对应范例的「渐强侧光」「最柔一镜」「正面平光」「最强侧光」
四种影调），一条一镜、每锁一个种子，跑完把产物路径打出来给检光回量。

    python run_local_light.py            # 跑默认四条
    python run_local_light.py --all      # 六条全跑
    python run_local_light.py --steps 20 --w 768 --h 1344
"""
import argparse
import io
import os
import re
import subprocess
import sys

DOC = "E:/创作/_待审文档/范例光影结构_转提示词_待审_20261004.md"
COMFY_RUN = "D:/AIWorkflow/tools/comfy_run.py"
WORKFLOW = "D:/AIWorkflow/engine/comfy/draft_flux_api.json"
OUT = "E:/图像影音资源池/_公共素材/中式色彩_20261004/范例/本地出图_对照"


def keyframes(section="### C."):
    """从待审文档指定小节（`### C.`＝第一轮，`### C-2`＝明度修正轮）抓 K… 提示词。
    返回 {编号: 单行提示词}；编号允许带后缀字母（K1b）。**提示词只有一份，在文档里**。"""
    s = io.open(DOC, encoding="utf-8").read()
    c = s.split(section, 1)[1].split("##", 1)[0]
    block = re.search(r"```text\n(.*?)\n```", c, re.S).group(1)
    txt = re.sub(r"\s*\n\s*", " ", block)                     # 每条 K 提示词被折成多行，先并回一行
    out = {}
    for m in re.finditer(r"\bK(\d[a-z]?)\s+(.*?)(?=\s+\bK\d[a-z]?\s+|$)", txt, re.S):
        out["K" + m.group(1)] = m.group(2).strip()
    # 展开「K1d = K1c plus …」这种给人看的简写：实跑必须是完整一句，不能让模型去解引用。
    for k in list(out):
        m = re.match(r"^(K\d[a-z]?)\s+plus\s+(.*)$", out[k])
        if m:
            base = m.group(1)
            if base not in out:
                print("展开失败：%s 引用了不存在的 %s" % (k, base))
                continue
            out[k] = out[base] + ", " + m.group(2).rstrip(".") + "."
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="K1,K3,K4,K5")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--section", default="### C.", help="`### C.` 第一轮｜`### C-2` 明度修正轮｜`### C-4` Z-Image 轮")
    ap.add_argument("--workflow", default=WORKFLOW, help="默认 FLUX；Z-Image 传 engine/comfy/z_image_turbo_api.json")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--guidance", type=float, default=3.5)
    ap.add_argument("--w", type=int, default=768)
    ap.add_argument("--h", type=int, default=1344)
    ap.add_argument("--seed-base", type=int, default=20261004,
                    help="配对对照：两轮用同一组种子，只差提示词那一根轴")
    a = ap.parse_args()
    ks = keyframes(a.section)
    want = sorted(ks) if a.all else [x.strip() for x in a.only.split(",") if x.strip()]
    print("抓到 %d 条关键帧提示词：%s｜本轮跑 %s" % (len(ks), " ".join(sorted(ks)), " ".join(want)))
    missing = [k for k in want if k not in ks]
    if missing:
        print("文档里没有这几条：%s" % missing)
        return 2
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    for i, k in enumerate(want):
        p = ks[k]
        print("\n=== %s（%d 词）===\n%s" % (k, len(p.split()), p[:160]))
        cmd = [sys.executable, COMFY_RUN, "--workflow", a.workflow,
               "--set", "PROMPT=" + p,
               "--set", "W=%d" % a.w, "--set", "H=%d" % a.h,
               "--set", "STEPS=%d" % a.steps, "--set", "GUIDANCE=%g" % a.guidance,
               "--seed", str(a.seed_base + i),               # 一条一个固定种子，可复算
               "--prefix", "光影骨架_" + k, "--out", OUT]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (r.stdout or "").strip().splitlines()[-6:]
        print("\n".join(tail))
        if r.returncode:
            print("  退出码 %d｜%s" % (r.returncode, (r.stderr or "").strip()[-300:]))
    print("\n落点：%s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
