# -*- coding: utf-8 -*-
"""画风归因第三轮 · 第 1 张：渲染流派（高精度CG半写实3D）的**粗臂男**设定四视图卡。

为什么要这张：arm1–arm5 之后，"真人感从哪来"还剩两种解释——
  C1 配角锚 A09 本身是真人照片感，挂它就把那一派带进画面（＝锚的问题，可换卡解决）；
  C2 "现代混混男／机械义肢"这个对象在 Seedream 里的先验就是写实照片（＝词的问题，换卡也救不了）。
要判这一刀，必须先有一张**同设定、同版式、但属基线画风**的配角卡；有了它才能做 arm6（只换锚、文字不动）。

本轮控制变量：
  · 版式与 A01／A09 完全一致（浅灰棚拍、四视图、2048×1152），换卡后 arm6 里"第几张是什么形状"不变。
  · 设定逐项从 A09 目视抄进文字（平头／壮硕／右臂黄褐义肢／灰白背心／腰系外套／工装裤／军靴／泥污），
    让"除了渲染流派，别的都没变"尽量成立。
  · ⚠️ **不挂 A09 当锚**。挂它＝把它那身真人照片质感一起带进来，这张卡就白做；
    而且按已有教训，风格锚只能挂原始素材，挂派生物是二手锚链、逐代掉质感。
    代价写清楚：这张卡与 A09 **不是同一张脸**，身份靠文字承载。它当的是"体型＋服装＋画风"三件事的锚。
  · 只挂 A01 当画风锚，且职责句写死"只取渲染流派与版式，不取人物/性别/服装/颜色"。

偏差点（留痕）：上一轮我说"把'打结'那处一并改掉"，但设定卡里根本没有杆（A09 也没杆），
"打结"是【道具锁句】里的问题，不在这张的作用域；arm6 又必须"文字一字不动"才成立单变量。
⇒ 打结措辞的验证从这两张里摘出去，留作第三步，不在本轮夹带。
"""
import io, json, os, sys, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ASSET = r'E:\创作\武昭君仪\武昭君仪资产包'
OUT = os.path.join(HERE, 'kf_out', 'cast')
SEED = 20260926
W, H = 2048, 1152                      # 与 A01／A09 逐字同尺寸，换进锚位时不改变输入形状

STYLE_ANCHOR = os.path.join(ASSET, 'A01 武君仪·赛博红衣基线.png')

PROMPT = """【参考素材职责】
第一张（A01 武君仪·赛博红衣基线）＝只采用这张图的**渲染流派与画面版式**：高精度CG半写实的3D渲染质感、浅灰无缝棚拍背景、四视图并排的站位与留白、均匀柔光的布光方式。不采用其中的人物、面容、性别、年龄、服装、配色、道具与任何角色设定。

【画风】
高精度CG半写实3D渲染，游戏过场动画与角色模型展示质感。皮肤为柔和次表面散射的平滑着色，看不到毛孔与照片级皮肤微纹理；发丝成束、边缘干净；布料有清晰的织纹与缝线贴图，金属件为带高光反射的着色材质；整体锐利干净，无胶片颗粒、无传感器噪点、无景深虚化。

【版式】
角色设定四视图：同一名男性在纯净浅灰无缝棚拍背景前，从左到右并排站立四次——正面、左侧面、背面、右侧面。四个视图为同一个人、同一套服装、同一比例，头顶与鞋底留白均匀，身高一致、光照一致。站姿自然放松，双臂垂在身侧，双脚与肩同宽。画面里没有任何道具、家具、文字、标识与水印。

【人物设定】
东亚成年男性，约三十岁，体格壮硕，肩背宽厚，胸臂肌肉发达，站姿沉稳而有压迫感。极短的黑色平头，发际线整齐。脸型偏方，浓眉，颧骨高，下颌宽，鼻梁挺直，嘴唇薄，表情凶悍冷漠、眼神警惕。脸、颈与手臂上有泥污擦痕与浅表划伤。
右侧从肩头到手指是一整条做旧的黄褐色机械义肢：外露液压杆、管线、金属关节与五根金属手指，漆面磨损、边缘露出锈迹与划痕。左臂为正常肉臂，肌肉线条明显。

【服装】
上身穿一件带汗渍与油污的灰白色罗纹背心，领口与袖口松垮。腰间系一件深灰褐色外套，两只衣袖在身前交叉束紧，衣摆垂在大腿前侧。下身深灰绿色多口袋工装裤，裤腿宽松、膝部起皱。脚穿脏污的深棕色高帮军靴，鞋带系紧。

【排除】
不要真人照片质感，不要毛孔级皮肤，不要影楼写真，不要胶片颗粒，不要漫画与卡通描边，不要多余人物。"""


def main():
    import seedream as SD
    import numpy as np, cv2
    os.makedirs(OUT, exist_ok=True)
    scale = max(1.0, (1600000 / (W * H)) ** 0.5)
    ow, oh = int(round(W * scale / 32) * 32), int(round(H * scale / 32) * 32)
    print('== 渲染流派配角卡：%dx%d（请求 %dx%d）｜锚 1 张 A01｜seed %d' % (W, H, ow, oh, SEED))
    print('   提示词 %d 字  sha %s' % (len(PROMPT), hashlib.md5(PROMPT.encode()).hexdigest()[:12]))
    io.open(os.path.join(OUT, 'cast_card_prompt.txt'), 'w', encoding='utf8').write(PROMPT)

    urls = SD.call(PROMPT, [SD.data_uri(STYLE_ANCHOR)], SEED, ow, oh)
    raw = SD.fetch(urls[0], os.path.join(OUT, 'cast_card_raw.png'))
    im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
    h, w = im.shape[:2]
    cut = int(round(h * 0.02))
    im = im[cut:h - cut * 6, cut:w - cut]
    h2, w2 = im.shape[:2]
    if w2 / h2 > W / H:
        nw = int(round(h2 * W / H)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
    else:
        nh = int(round(w2 * H / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
    im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
    dst = os.path.join(OUT, 'A09b 粗臂男（混混）·CG渲染版.png')
    cv2.imencode('.png', im)[1].tofile(dst)
    print('   →', dst, im.shape[1], 'x', im.shape[0])
    json.dump({'ts': time.strftime('%F %T'), 'img': dst, 'seed': SEED, 'wh': [W, H],
               'anchor': os.path.basename(STYLE_ANCHOR),
               'prompt_sha': hashlib.md5(PROMPT.encode()).hexdigest()[:12],
               'note': '画风锚＝A01（只取渲染流派与版式）；未挂 A09，故与 A09 非同一张脸，身份靠文字。'},
              io.open(os.path.join(OUT, 'cast_card_manifest.json'), 'w', encoding='utf8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
