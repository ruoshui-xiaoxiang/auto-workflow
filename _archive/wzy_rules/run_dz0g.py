# -*- coding: utf-8 -*-
"""批 0-G：用他给的燕云捏脸图当脸锚＋发型锚，派生全身定妆。

两条臂（唯一变量＝渲染风格那一句）：
  R  写实电影级 CG（全片现行画风，赛博城市场景是写实挂）
  C  贴原图的 3D 游戏 CG 质感（更靠近他给的参考图本身）
锚点职责写死：只锁面容与发型，不采用其景别／机位／构图／背景／光位。
"""
import io
import json
import os
import sys

sys.path.insert(0, r"D:/AIWorkflow/tmp/jianlai_test")
import ark_img

OUT = os.environ.get("DZOUT", r"D:/AIWorkflow/tmp/wzy/dz0g")
ANCHOR = r"D:/AIWorkflow/tmp/wzy/ref/junyi_ref1.jpg"

BODY = """把参考图里这位女子的面容与发型原样保留，给她做一张全身定妆立像。
身材是超模比例：非常高挑，接近九头身，腿特别长，肩颈舒展平直，腰细，锁骨清楚，站姿挺拔、重心稳，是练过的挺拔而不是摆姿势。手长指节干净。
服装是仙气古风劲装，游戏时装风格：交领右衽窄袖上衣，袖口在腕上束紧并加绑臂；腰束宽带，外面再勒一条革带，革带上挂一枚旧玉佩和一只布钱袋；下身及膝短裙摆、两侧开衩，内衬同色长裤；黑色高筒靴，靴口与裙摆之间露出一段长腿；肩后一件做旧金属短披膊，披膊外再叠一条不透明的长后摆，只在身后垂落，不透肉不露肩；腰侧与背后垂下两三条细长飘带，随风向后飘；衣缘有细银线绣纹。配色月白、鸦青、银灰，加一点冷蓝渐变，素净华丽，不用明艳红金。
她右手扶一杆长枪，枪身与她等高，枪头朝上，深色木杆，枪头下方缠皮绳。武器只能是冷兵器的长枪。
背景中性灰，单光源从左前方 45 度，柔光，低对比。
参考图只用于锁定面容与发型；不要采用参考图的景别、机位、构图、背景、光位和画幅——本图必须是竖幅 9:16 全身立像，人物从头顶到靴底完整入画，头顶留白，脚下看到地面。
不要出现任何文字、签名、印章、二维码、水印，一个汉字都不要有；不要火枪、不要枪托、不要扳机；不要露肩抹胸、不要透视装。"""

STYLE = {
    "R": "渲染成写实电影级 CG 人像质感：皮肤有真实次表面散射与柔雾哑光质感，发丝根根分明，丝绸与金属有物理反射，接近真人摄影但五官是理想化的。",
    "C": "渲染成高级 3D 游戏 CG 人像质感：与参考图同一套材质语言，皮肤柔雾瓷感、发丝成束有高光、金属与水晶有干净的高光反射，介于写实与风格化之间。",
}

os.makedirs(OUT, exist_ok=True)
res = {}
for arm in ("R", "C"):
    for k in range(3):
        seed = 2026100101 + (0 if arm == "R" else 3) * 1 + k
        prompt = STYLE[arm] + "\n" + BODY
        try:
            urls = ark_img.call(prompt, [ark_img.data_uri(ANCHOR)], seed, 1536, 2688)
            p = ark_img.fetch(urls[0], os.path.join(OUT, "%s%d_raw.png" % (arm, k + 1)))
            res[arm + str(k + 1)] = os.path.basename(p)
            print("OK", arm + str(k + 1), os.path.getsize(p) // 1024, "KB")
        except Exception as e:
            res[arm + str(k + 1)] = None
            print("FAIL", arm + str(k + 1), str(e)[:200])
json.dump(res, io.open(os.path.join(OUT, "dz0g_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("done", sum(1 for v in res.values() if v), "/6")
