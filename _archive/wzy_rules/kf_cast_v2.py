# -*- coding: utf-8 -*-
"""粗臂男「角色设定图」第二版 —— 两条路线各一张，给他挑，挑完才谈训练集。

上一版 A09b 的两个硬伤：
  ① 四视图不自洽：正视图没画义肢、第二视图义肢跑到左臂、背视图两条 ⇒ 下游 arm6 里配角丢义肢就是这缺陷。
  ② 风格强度不够：只是"比 A09 干净"，离 A01 那档平滑着色还有一截 ⇒ 拿它测画风是弱载体。

两条路线（不是 A/B 归因实验，是设计迭代，所以允许同时动多处）：
  candA_puretext   纯文字重做，**不挂 A09**（挂了就把它那身真人照片质感一起带进来）。
                   修①：逐视图写死义肢在哪一侧，按几何推一遍（正面＝画面左侧；背面＝画面右侧；
                        右侧面完整可见；左侧面只露肩甲）。
                   修②：把渲染流派写成材质层的正面描述（哑光次表面散射、大块明暗过渡、污渍以色块贴图表现、
                        发束成片、金属为着色器高光），并把"汗渍／油污／脏污"这类**照片级微表面词全部撤掉**——
                        它们是把画面拽向实拍的力。
                   代价：与 A09 **不是同一张脸**。
  candB_fromA09    挂 A09＋A01 双锚：A09 只取身份（同一张脸）／体型／服装款式／义肢位置与做旧配色，
                   A01 只取渲染流派与版式。**这条如果成立，才是能直接顶替 A09 上生产的那张。**
                   风险（已知规律）：参考图会连姿态、质感、画风一起带 ⇒ 可能跟不到渲染感，仍是真人照片。
                   这条同时是在测另一件事：**"锚的画风 ≠ 目标画风时，写死职责句能不能只取身份不取质感"。**
"""
import io, json, os, sys, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ASSET = r'E:\创作\武昭君仪\武昭君仪资产包'
OUT = os.path.join(HERE, 'kf_out', 'cast')
SEED = 20260926
W, H = 2048, 1152
A01 = os.path.join(ASSET, 'A01 武君仪·赛博红衣基线.png')
A09 = os.path.join(ASSET, 'A09 粗臂男（混混）.png')

# ── 两条路线共用的部分（版式／人物／服装），逐视图几何写死 ──────────────────
LAYOUT = """【版式】
角色设定四视图：同一名男性在纯净浅灰无缝棚拍背景前，从左到右并排站立四次——正面、右侧面、背面、左侧面。
四个视图为同一个人、同一套服装、同一比例，头顶与鞋底留白均匀，身高一致、光照一致，画面里没有任何道具、家具、文字、标识与水印。
站姿自然放松，双臂垂在身侧，双脚与肩同宽。"""

# 义肢位置按几何逐视图写死：他的右臂＝正面看画面左侧、背面看画面右侧
PROSTHESIS = """【机械右臂在四个视图中的位置（逐视图必须一致，这是同一个人的同一条义肢）】
他的**右臂**从肩头到手指是一整条机械义肢，左臂是正常肉臂。四个视图里必须这样出现：
视图一（正面）：义肢出现在**画面左侧**那条手臂，完整可见，金属手指朝前。
视图二（他面向画面右的右侧面）：他的右肩朝向观者，**义肢完整可见**，垂在身体近侧。
视图三（背面）：义肢出现在**画面右侧**那条手臂，完整可见，能看到肩甲与后侧管线。
视图四（他面向画面左的左侧面）：他的左肩朝向观者，**近侧这条是肉臂**；义肢只在身体远侧露出肩甲与手背一小部分。
义肢外观：做旧的暗黄褐色涂装，外露液压杆、管线、金属关节与五根金属手指，漆面磨损、边缘露出锈迹与划痕。四条视图里义肢只有一条，不得出现两条，不得缺失。"""

FIGURE = """【人物】
东亚成年男性，约三十岁，体格壮硕，肩背宽厚，胸臂肌肉发达，站姿沉稳而有压迫感。极短的黑色平头，发际线整齐。脸型偏方，浓眉，颧骨高，下颌宽，鼻梁挺直，嘴唇薄，表情凶悍冷漠、眼神警惕。左臂肌肉线条明显。"""

COSTUME = """【服装】
上身穿一件灰白色罗纹背心，领口与袖口松垮，表面有深浅不均的做旧污渍色块。腰间系一件深灰褐色外套，两只衣袖在身前交叉束紧，衣摆垂在大腿前侧。下身深灰绿色多口袋工装裤，裤腿宽松、膝部起皱。脚穿深棕色高帮军靴，鞋带系紧。脸、颈与手臂上有几处浅色擦痕与泥污色块。"""

RENDER = """【画风（这一层是本轮要立的东西，优先级最高）】
高精度CG半写实3D渲染，游戏引擎实时渲染的角色模型展示质感。皮肤是均匀哑光的次表面散射材质，只有大块的明暗过渡与柔和的高光带，**没有毛孔、没有毛细血管、没有真实汗湿反光、没有皮肤微纹理**。头发是一整片带高光带的发束，不是一根根真发。布料有清晰的织纹与缝线贴图，污渍以色块与贴图边缘表现，不到微表面级。金属义肢是着色器高光与环境贴图反射，不是真实镜面反射。整体锐利干净，无胶片颗粒、无传感器噪点、无景深虚化。"""

DUTY_A = """【参考素材职责】
第一张（A01 武君仪·赛博红衣基线）＝只采用这张图的**渲染流派与画面版式**：高精度CG半写实的3D渲染质感、浅灰无缝棚拍背景、四视图并排的站位与留白、均匀柔光的布光方式。不采用其中的人物、面容、性别、年龄、服装、配色、道具与任何角色设定。

"""

DUTY_B = """【参考素材职责】
第一张（A01 武君仪·赛博红衣基线）＝只采用这张图的**渲染流派与画面版式**：高精度CG半写实的3D渲染质感、浅灰无缝棚拍背景、四视图并排的站位与留白、均匀柔光的布光方式。不采用其中的人物、面容、性别、服装、配色与任何角色设定。
第二张（A09 粗臂男）＝只采用这个人的**身份与设定**：同一张脸、同样的平头与五官比例、同样的壮硕体型、背心与腰系外套与工装裤军靴的款式、机械右臂的位置与做旧暗黄褐配色。不采用它的真人照片质感、不采用它的皮肤微纹理与汗湿反光、不采用它的背景与布光。

"""

EXCLUDE = """

【排除】
不要真人照片质感，不要影楼写真，不要毛孔级皮肤，不要胶片颗粒，不要漫画与卡通描边，不要多余人物，不要第二条机械臂。"""

CANDS = [
    ('candA_puretext', DUTY_A + RENDER + LAYOUT + PROSTHESIS + FIGURE + COSTUME + EXCLUDE, [A01]),
    ('candB_fromA09', DUTY_B + RENDER + LAYOUT + PROSTHESIS + FIGURE + COSTUME + EXCLUDE, [A01, A09]),
]


def main():
    import seedream as SD
    import numpy as np, cv2
    os.makedirs(OUT, exist_ok=True)
    scale = max(1.0, (1600000 / (W * H)) ** 0.5)
    ow, oh = int(round(W * scale / 32) * 32), int(round(H * scale / 32) * 32)
    man = {}
    for name, prompt, refs in CANDS:
        io.open(os.path.join(OUT, name + '_prompt.txt'), 'w', encoding='utf8').write(prompt)
        print('== %-16s 锚 %d 张 %s｜%d 字 sha %s' % (
            name, len(refs), [os.path.basename(x)[:12] for x in refs],
            len(prompt), hashlib.md5(prompt.encode()).hexdigest()[:12]))
        urls = SD.call(prompt, [SD.data_uri(p) for p in refs], SEED, ow, oh)
        raw = SD.fetch(urls[0], os.path.join(OUT, name + '_raw.png'))
        im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
        h, w = im.shape[:2]; cut = int(round(h * 0.02))
        im = im[cut:h - cut * 6, cut:w - cut]
        h2, w2 = im.shape[:2]
        if w2 / h2 > W / H:
            nw = int(round(h2 * W / H)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
        else:
            nh = int(round(w2 * H / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
        dst = os.path.join(OUT, name + '.png')
        cv2.imencode('.png', im)[1].tofile(dst)
        man[name] = dict(img=dst, seed=SEED, refs=[os.path.basename(x) for x in refs],
                         prompt_sha=hashlib.md5(prompt.encode()).hexdigest()[:12],
                         prompt_len=len(prompt), ts=time.strftime('%F %T'))
        print('   →', os.path.basename(dst))
    old = {}
    p = os.path.join(OUT, 'manifest_cast.json')
    if os.path.isfile(p):
        old = json.load(io.open(p, encoding='utf8'))
    old.update(man)
    json.dump(old, io.open(p, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('\n产物与配方：', OUT)


if __name__ == '__main__':
    main()
