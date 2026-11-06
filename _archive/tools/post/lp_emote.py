# -*- coding: utf-8 -*-
"""LivePortrait 微表情驱动（P7：把静帧驱动出表情/口型微动，后处理层工具）。

用法:
  py -3.12 lp_emote.py --source 镜头帧.png --template laugh --out 输出.mp4
  py -3.12 lp_emote.py --source 镜头帧.png --video 驱动.mp4 --out 输出.mp4
  py -3.12 lp_emote.py --list                          # 看可用表情模板

口径:
- 模型与运行环境都在 D:\\AIWorkflow\\LivePortrait-main；用 ComfyUI 的 python_embeded 跑
  （pylibs 已 vendored，onnxruntime 只有 CPU provider——人脸检测走 CPU，够用）；
- 表情模板（wink/laugh/shy/aggrieved/open_lip/shake_face/talking）在 driving_tpl/，
  是从旧格式 pkl 升上来的（补了 c_d_eyes_lst/c_d_lip_lst 占位键；retarget 关时不会被读）；
  官方 d0-d20 视频也可直接当驱动（--video），第一次会自动落模板；
- 速度实测：3-4s 片段（54-100 帧）动画 ~9-13s；静帧源 + 模板 = 无驱动视频依赖（隐私友好）;
- 输出是"整帧回贴"（pasteback 保持背景），适合近景/中景单脸镜；小脸/多脸镜先看 detect 日志。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

LP_ROOT = Path(r"D:\AIWorkflow\LivePortrait-main")
PY = Path(r"D:\AIWorkflow\ComfyUI_H3\python_embeded\python.exe")
TPL_DIR = LP_ROOT / "assets" / "examples" / "driving_tpl"
VIDEO_DIR = LP_ROOT / "assets" / "examples" / "driving"


def list_templates():
    print("[模板] driving_tpl/（表情模板，无需驱动视频）:")
    for f in sorted(TPL_DIR.glob("*.pkl")):
        print(f"  {f.stem}")
    print("[驱动] driving/（官方驱动视频，--video 名或 d 前缀直接给）:")
    vids = sorted({p.stem for p in VIDEO_DIR.glob("*.mp4")})
    print("  " + " ".join(vids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="源图（png/jpg）或源视频")
    ap.add_argument("--template", help="表情模板名（driving_tpl/ 下，不带 .pkl）")
    ap.add_argument("--video", help="驱动视频名（driving/ 下，不带 .mp4）或绝对路径")
    ap.add_argument("--out", help="输出 mp4 路径")
    ap.add_argument("--region", default=None, choices=["exp", "pose", "lip", "eyes", "all"],
                    help="驱动区域（默认 all；只用表情微动时给 exp）")
    ap.add_argument("--no-half", action="store_true", help="关半精度（出黑块时用）")
    ap.add_argument("--list", action="store_true", help="列出可用模板/驱动")
    args = ap.parse_args()

    if args.list:
        list_templates()
        return 0
    if not (args.source and args.out and (args.template or args.video)):
        ap.error("需要 --source 与 --out，且 --template 或 --video 二选一")
    if args.template and args.video:
        ap.error("--template 与 --video 不能同时给")

    if args.template:
        p = TPL_DIR / f"{args.template}.pkl"
        if not p.exists():
            sys.exit(f"!! 模板不存在：{p}（先 --list 看清单）")
        driving = str(p)
    else:
        p = Path(args.video)
        if not p.exists():
            p = VIDEO_DIR / f"{args.video}.mp4"
        if not p.exists():
            sys.exit(f"!! 驱动视频不存在：{args.video}")
        driving = str(p)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = str(LP_ROOT / "bin") + os.pathsep + env.get("PATH", "")

    cmd = [str(PY), "run_lp.py", "--source", str(Path(args.source).resolve()),
           "--driving", driving, "--output_dir", str(out.parent)]
    if args.region:
        cmd += ["--animation_region", args.region]
    if args.no_half:
        cmd += ["--flag_use_half_precision", "False"]

    r = subprocess.run(cmd, cwd=str(LP_ROOT), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (r.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print("  ", line.strip())
    if r.returncode != 0:
        print((r.stderr or "")[-800:], file=sys.stderr)
        sys.exit(f"!! LivePortrait 退出码 {r.returncode}")

    # LP 把输出写成 <source>--<driving>.mp4 放在 output_dir；按 --out 改名
    produced = sorted(out.parent.glob(f"{Path(args.source).stem}--*.mp4"),
                      key=lambda f: f.stat().st_mtime)
    if not produced:
        sys.exit("!! 没找到 LP 输出的 mp4（看上面的日志）")
    src_mp4 = produced[-1]
    if src_mp4 != out:
        if out.exists():
            out.unlink()
        src_mp4.replace(out)
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"OK  {out}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
