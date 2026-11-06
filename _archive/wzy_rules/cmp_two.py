# -*- coding: utf-8 -*-
"""通用两版对照板：cmp_two.py <旧mp4> <新mp4> <输出jpg> <上标题> <下标题>

上下两排各抽 8 帧（每 16 帧一帧），用于逐镜比较提示词/配置改动。
"""
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FFMPEG = r"D:/AIWorkflow/tools/ffmpeg.exe"


def strip(mp4, tmp):
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                    "-vf", "select='not(mod(n\\,16))',scale=480:-1,tile=8x1",
                    "-frames:v", "1", "-vsync", "0", str(tmp)], check=True)
    return Image.open(tmp)


def main():
    old, new, out, t_old, t_new = sys.argv[1:6]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ia = strip(old, out.parent / "_old.png")
    ib = strip(new, out.parent / "_new.png")
    font = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 25)
    W, H = ia.size
    canvas = Image.new("RGB", (W, H * 2 + 78), (240, 240, 245))
    dr = ImageDraw.Draw(canvas)
    dr.text((8, 6), t_old, fill=(20, 20, 20), font=font)
    dr.text((8, H + 42), t_new, fill=(20, 20, 20), font=font)
    canvas.paste(ia, (0, 34))
    canvas.paste(ib, (0, H + 70))
    canvas.save(out, quality=88)
    print("saved", out)


if __name__ == "__main__":
    main()
