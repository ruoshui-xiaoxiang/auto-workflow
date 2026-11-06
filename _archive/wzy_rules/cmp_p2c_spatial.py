# -*- coding: utf-8 -*-
"""P2C 对照板：dual(Bunny) vs triple(Bunny+spatial-physics)，同首帧同seed。
上下两排各 6 帧（每 22 帧抽一帧），看"受力感/碰撞/重心"差异。"""
import subprocess
from pathlib import Path

FFMPEG = r"D:/AIWorkflow/tools/ffmpeg.exe"
BASE = Path(r"E:/创作/武昭君仪/_H3实测")
A = BASE / "三阶打斗_P2C/shots/三阶打斗_P2C/raw/wzhj_p2c_00001_.mp4"      # dual
B = BASE / "对照_spatial_P2C/shots/对照_spatial_P2C/raw/wzhj_p2csp_00001_.mp4"  # triple
OUT = Path(r"D:/AIWorkflow/tmp/wzy/qc_sheet/p2c_dual_vs_spatial.jpg")
OUT.parent.mkdir(parents=True, exist_ok=True)


def strip(mp4, tag):
    tmp = OUT.parent / ("_%s.png" % tag)
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                    "-vf", "select='not(mod(n\\,22))',scale=480:-1,tile=6x1",
                    "-frames:v", "1", "-vsync", "0", str(tmp)], check=True)
    return tmp


if __name__ == "__main__":
    from PIL import Image, ImageDraw, ImageFont
    a, b = strip(A, "dual"), strip(B, "triple")
    ia, ib = Image.open(a), Image.open(b)
    font = ImageFont.truetype(r"C:/Windows/Fonts/msyh.ttc", 26)
    W, H = ia.size
    canvas = Image.new("RGB", (W, H * 2 + 70), (240, 240, 245))
    dr = ImageDraw.Draw(canvas)
    dr.text((8, 6), "上：dual（turbo+Bunny）＝现行 12 镜链配置", fill=(20, 20, 20), font=font)
    dr.text((8, H + 40), "下：triple（turbo+Bunny+spatial-physics 0.3）＝格挡反击抽射同款", fill=(20, 20, 20), font=font)
    canvas.paste(ia, (0, 34))
    canvas.paste(ib, (0, H + 68))
    canvas.save(OUT, quality=88)
    print("saved", OUT)
