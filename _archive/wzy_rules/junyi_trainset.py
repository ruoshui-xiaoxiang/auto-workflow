# -*- coding: utf-8 -*-
"""武君仪 · 形象训练集生成器（云端 Seedream，画风锁在 09-27 定的「高精度CG半写实3D渲染」基线上）。

产物落他本机既有约定：`D:\\AIWorkflow\\training\\datasets\\君仪\\1_junyi\\Jxx.png + Jxx.txt`
（照 `datasets\\脸A\\1_faceA` 的形状：触发词开头、英文逗号短语、一条图一个 txt）。

★ 这批图跟"角色设定图"的目标是相反的，别用同一套写法：
  设定图要**干净、灰棚、可比**；训练集要**背景／光照／景别／角度尽量打散**。
  原因：faceA 那批 25 张全是棚拍，caption 里 `plain light grey studio background` 是**常量不是变量**，
  LoRA 会把"灰棚底"一起学进身份里（`training\\docs\\脸A_LoRA训练日志_20260916.md` 已记）。
  ⇒ 本轮 caption 里照样如实写背景与布光，但**图片本身背景必须多样**，这样它才是可归因给文本的变量。

锚点顺序与生产首帧同构（scene → face → costume → prop），保证分布对齐：
  · 脸 = `anchors/dingzhuang/junyi_face_real.png`（古代线那张改挂 junyi_face_ancient）
  · 服装 = A01 红衣／A02 白衣（原始素材、画风基线真源）
  · 场景 = SC01／SC02／SC03／SC05／SC06／SC07
  · 道具 = P01（持杆的四张挂；"人＋杆一起训"是外部调研里唯一成熟的锁道具做法）

⚠️ 项目纪律照旧：提示词里不出现"枪"字，一律"白麻布缠的长杆"。
⚠️ 出完必须逐张目检：身份跑偏／多长一根杆／背景仍是灰棚／水印没裁净，任一条就把该张剔出训练集，
   不能只数够张数。caption 是从"驱动这张图的属性元组"生成的，目检不符时要改 caption 而不是改图了事。
"""
import io, json, os, re, sys, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ASSET = r'E:\创作\武昭君仪\武昭君仪资产包'
ANCH = os.path.join(HERE, 'anchors', 'dingzhuang')
OUT = r'D:\AIWorkflow\training\datasets\君仪\1_junyi'
SEED = 20260926
TRIG = 'junyi'

A = lambda t: os.path.join(ASSET, t)
FACE = {'cyber': os.path.join(ANCH, 'junyi_face_real.png'),
        'anc': os.path.join(ANCH, 'junyi_face_ancient.png')}
COS = {'red': A('A01 武君仪·赛博红衣基线.png'), 'white': A('A02 武君仪·古代白衣.png')}
PROP = A('P01 沉铁长枪（白麻布裹严）.png')
SCN = {'SC01': A('SC01 洛阳宅院外墙·夜.png'), 'SC02': A('SC02 黄昏雾林泥地.png'),
       'SC03': A('SC03 下层区霓虹巷道.png'), 'SC05': A('SC05 弱电井栖身处.png'),
       'SC06': A('SC06 楼间长廊.png'), 'SC07': A('SC07 食品店柜台.png')}
SCN_CN = {'SC01': 'SC01 洛阳宅院外墙·夜', 'SC02': 'SC02 黄昏雾林泥地', 'SC03': 'SC03 下层区霓虹巷道',
          'SC05': 'SC05 弱电井栖身处', 'SC06': 'SC06 楼间长廊', 'SC07': 'SC07 食品店柜台'}

# ── 画风段：candB 那轮验证过有效的"材质层"写法（不是加形容词，是写成像方式）────────
RENDER = """【画风】
高精度CG半写实3D渲染，游戏引擎实时渲染的角色质感。皮肤是均匀哑光的次表面散射材质，只有大块的明暗过渡与柔和的高光带，没有毛孔、没有毛细血管、没有真实汗湿反光、没有皮肤微纹理。头发是一整片带高光带的发束，不是一根根真发。布料有清晰的织纹与缝线贴图，污渍以色块与贴图边缘表现。金属件是着色器高光与环境贴图反射，不是真实镜面。整体锐利干净，无胶片颗粒、无传感器噪点、无文字与水印。"""

COS_CN = {'red': '深红色东方剪影劲装（交领、束腰、护腕、暗云纹）',
          'white': '月白色古代劲装（交领、束腰、银线云纹）'}
COS_EN = {'red': 'deep crimson cross-collar martial robe with dark sash and bracers',
          'white': 'moon-white ancient cross-collar robe with silver cloud embroidery'}
POLE_EN = 'holding a long pole tightly wrapped in white linen'

# ── 批 1 八格：刻意把 服装／场景／光／景别／角度／持杆 全部错开 ──────────────
# cn＝写进提示词的画面描述；en＝同一张图的 caption 短语（背景/光/景别/角度/表情/持杆）
CELLS = [
    dict(id='J01', wh=(1792, 1024), cos='red', line='cyber', sc='SC03', pole=True,
         cn='她全身入画、占画面高度约三分之二，正面略偏四分之三侧站立，双手斜托那根白麻布长杆，眼神警觉平视前方；'
            '下层区霓虹巷道夜景，冷蓝全息光从上方打下、暖橙霓虹从右侧墙面反上来，湿地面有反光',
         en='alert steady gaze, holding a long pole wrapped in white linen with both hands, full body framed to the boots, '
            'frontal three-quarter view, cool blue holographic top light with warm orange neon bounce from the right wall, '
            'wet neon alley at night with reflective ground'),
    dict(id='J02', wh=(1152, 1440), cos='red', line='cyber', sc=None, pole=False,
         cn='胸部以上特写，脸占画面宽度约三分之一，头微微转向画面右侧成三分之四侧脸，视线落在画外右下方，眉头轻蹙；'
            '单一暖橙侧光从左后方勾出鬓边碎发，另一侧脸落在阴影里，背景是虚化的暗色街景',
         en='slightly knitted brows, gaze off frame to the lower right, head turned three-quarter, '
            'close-up portrait framed to the chin, warm orange rim light from the left rear with one cheek in shadow, '
            'blurred dark street background with soft bokeh, no weapon'),
    dict(id='J03', wh=(1792, 1024), cos='red', line='cyber', sc='SC06', pole=True,
         cn='七分身，背对镜头站在楼间长廊边，头回转越过肩头看向镜头，右手垂握那根白麻布长杆；'
            '长廊纵深，远处霓虹人流虚化成光点，冷青主调，栏杆在她身侧投下横向阴影',
         en='looking back over her shoulder at the camera, calm serious face, right hand holding a long pole wrapped in white linen down at her side, '
            'seven-eighths body from behind, standing at the railing of a long inter-building corridor, '
            'distant blurred neon crowd lights, cool cyan key light, horizontal railing shadows'),
    dict(id='J04', wh=(1792, 1024), cos='white', line='anc', sc='SC02', pole=True,
         cn='她全身入画，侧身面对画面左侧站立，双手把白麻布长杆横端在身前，重心压低、后脚蹬地，是起手式；'
            '黄昏雾林泥地，低角度暖金侧光穿过雾气，地面湿泥有她脚下的踩痕，远处树干被雾吞掉',
         en='low guarded stance holding a long pole wrapped in white linen horizontally with both hands, weight sunk, focused expression, '
            'left side profile view, full body framed to the boots, dusk misty forest clearing, '
            'low warm golden side light through fog, wet muddy ground with footprints, fog-swallowed tree trunks'),
    dict(id='J05', wh=(1152, 1440), cos='white', line='anc', sc='SC01', pole=False,
         cn='半身到腰，微微仰视机位（镜头略低于她），她下颌微抬、嘴唇抿住，神情冷而自持；'
            '洛阳宅院外墙夜景，清冷月光从画面右上方斜下，墙面是深色砖与瓦檐，呼吸间有极淡的白气',
         en='chin slightly raised, lips pressed, cold composed expression, half body framed to the waist, '
            'slightly low camera angle looking up at her, pale moonlight from the upper right, '
            'dark brick wall and tiled eaves of a mansion exterior at night, faint breath mist, no weapon'),
    dict(id='J06', wh=(1152, 1440), cos='red', line='cyber', sc='SC05', pole=False,
         cn='胸上到腰的近景，她低着头、眼睛向上抬起看镜头，神情有些疲惫，鬓边碎发垂下来压住半边眉；'
            '弱电井室内，单一冷白荧光从头顶斜下打，背后是密集的线缆与金属架，整体偏暗、对比高',
         en='head lowered with eyes lifting to the camera, tired restrained expression, loose strands falling over one brow, '
            'close bust framed to the waist, single cold white fluorescent light from above, '
            'cluttered utility shaft interior with dense cables and metal racks behind, dark high-contrast'),
    dict(id='J07', wh=(1792, 1024), cos='red', line='cyber', sc='SC03', pole=True,
         cn='全身侧面，她面向画面右迈步向前，双手把白麻布长杆平端指向右前方，衣摆与束带随步伐向后扬起；'
            '雨夜巷道，湿墙上有一块破损的全息广告在闪，冷蓝主调里夹一道品红，雨水在地面溅开',
         en='mid-stride walking forward, both hands level a long pole wrapped in white linen pointing ahead, robe hem and sash streaming behind, '
            'resolute expression, right side profile view, full body framed to the boots, rainy alley at night, '
            'a flickering damaged holographic billboard on wet wall, cold blue with a magenta accent, rain splashing on ground'),
    dict(id='J08', wh=(1792, 1024), cos='red', line='cyber', sc='SC07', pole=False,
         cn='四分之三侧的中景，她站在食品店柜台前侧身看向画面左，左手撑在台面上，右手垂着，神情平静带着一点戒备；'
            '柜台上方一盏暖黄吊灯，背后货架与包装杂乱但虚化，整体暖调，与她冷色的脸形成对比',
         en='calm with a trace of wariness, left hand resting on the counter, three-quarter view looking off to the left, '
            'medium shot framed to the knees, warm yellow pendant lamp above the counter, '
            'cluttered but blurred shelves of a small food shop behind, overall warm grade against her cool-lit face, no weapon'),
]

CN = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五'}


def build(c):
    """返回 (锚列表, 提示词)。职责句编号与锚顺序由同一个循环生成，不可能错位。
       ⚠️ 职责句里的锚名一律手写成**短标签**，不用文件名——P01 的文件名带"枪"字，
          直接拼进去会撞项目的永久零"枪"硬闸（生产侧 `compile_kf` 同样只写"第四张（P01）"）。"""
    refs, duty = [], []
    def put(path, label, text):
        refs.append(path)
        duty.append('第%s张（%s）＝%s' % (CN[len(refs)], label, text))
    if c['sc']:
        put(SCN[c['sc']], c['sc'] + ' 场景', '只采用这个场景的空间、材质、光影与色调（%s），不采用其中已有人物、文字与水印。' % SCN_CN[c['sc']])
    put(FACE[c['line']], '武君仪正脸特写', '武君仪的面容、发型与肤色的全部细节，只采用这张脸与头发；'
        '不采用它的服装颜色、衣领样式、背景、构图与任何光色。')
    put(COS[c['cos']], 'A01 服装' if c['cos'] == 'red' else 'A02 服装',
        '只采用%s的款式、剪裁、纹样、束带与护腕，以及这张图的渲染流派与材质质感；'
        '不采用它的灰棚背景、平光布光、并排版式与人物面容。' % COS_CN[c['cos']])
    if c['pole']:
        put(PROP, 'P01 长杆器物', '只采用这根长杆的外形、长度、白麻布斜向缠绕的方式与两端的收口；'
            '不采用它的背景与布光。画面里有且只有这一根长杆，不得出现第二根，不得交叉。')
    prompt = ('【参考素材职责】\n' + '\n'.join(duty) + '\n\n'
              + '【主体】武君仪，年轻女性，身量高挑、肩背舒展、站姿有武人的沉稳。\n'
              + '【画面】' + c['cn'] + '\n' + RENDER + '\n'
              + '【排除】\n不要多余人物，不要第二根长杆，不要真人照片质感，不要影楼写真，'
                '不要毛孔级皮肤，不要胶片颗粒，不要漫画与卡通描边，不要画面里出现任何文字、字幕、标识与水印。')
    cap = '%s, %s, %s' % (TRIG, 'young woman' , c['en'])
    return refs, prompt, cap


def main():
    import seedream as SD
    import numpy as np, cv2
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:] or None
    man = {}
    for c in CELLS:
        if only and c['id'] not in only:
            continue
        refs, prompt, cap = build(c)
        W, H = c['wh']
        scale = max(1.0, (1600000 / (W * H)) ** 0.5)
        ow, oh = int(round(W * scale / 32) * 32), int(round(H * scale / 32) * 32)
        assert all(os.path.isfile(x) for x in refs), [x for x in refs if not os.path.isfile(x)]
        print('== %s  锚%d %s｜%dx%d←%dx%d｜%d字' % (c['id'], len(refs),
              [os.path.basename(x)[:10] for x in refs], W, H, ow, oh, len(prompt)))
        urls = SD.call(prompt, [SD.data_uri(p) for p in refs], SEED, ow, oh)
        raw = os.path.join(OUT, '_raw_' + c['id'] + '.png')
        SD.fetch(urls[0], raw)
        im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
        h, w = im.shape[:2]; cut = int(round(h * 0.02))
        im = im[cut:h - cut * 6, cut:w - cut]
        h2, w2 = im.shape[:2]
        if w2 / h2 > W / H:
            nw = int(round(h2 * W / H)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
        else:
            nh = int(round(w2 * H / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
        dst = os.path.join(OUT, c['id'] + '.png')
        cv2.imencode('.png', im)[1].tofile(dst)
        io.open(os.path.join(OUT, c['id'] + '.txt'), 'w', encoding='utf8').write(cap)
        io.open(os.path.join(OUT, c['id'] + '_prompt.txt'), 'w', encoding='utf8').write(prompt)
        man[c['id']] = dict(img=dst, cap=cap, wh=[W, H], seed=SEED, refs=[os.path.basename(x) for x in refs],
                            prompt_sha=hashlib.md5(prompt.encode()).hexdigest()[:12], ts=time.strftime('%F %T'))
        print('   → %s.png   caption: %s' % (c['id'], cap[:90]))
    p = os.path.join(OUT, 'manifest_trainset.json')
    old = json.load(io.open(p, encoding='utf8')) if os.path.isfile(p) else {}
    old.update(man)
    json.dump(old, io.open(p, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('\n产物：', OUT)


if __name__ == '__main__':
    main()
