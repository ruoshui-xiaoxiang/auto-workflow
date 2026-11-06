# -*- coding: utf-8 -*-
'''长枪道具锚（批 1 的第一件）。

假设：前面 52 张纯文字里 13 张把长枪长成燧发枪，病根很可能是"枪"这个字本身
——中文语料里"长枪＋皮绳＋木杆"高频共现的是火绳枪/燧发枪。这一版全部改用
**矛／槊／长刃冷兵器**的措辞，并逐条点名禁掉火器结构，看变异是否消失。
'''
import io
import json
import os
import sys

sys.path.insert(0, r'D:/AIWorkflow/tmp/jianlai_test')
import ark_img

OUT = r'D:/AIWorkflow/tmp/wzy/qiang'
os.makedirs(OUT, exist_ok=True)
SEED0 = 2026100401

BODY = '''一件**中国传统长柄冷兵器——长矛（槊）**，单独竖立在画面正中，**画面里没有任何人、没有任何手扶它**。
全长约一人高（1.8 米），整件器物从最上端的刃尖到最下端的尾鐏**完整入画，上下都不裁切**。

矛头：钢制叶形双刃尖，长约一掌半，中脊凸起，刃面有锻打折叠纹和使用磨痕，刃口发亮、刃身偏暗灰，靠根部收出两个小小的倒须。
矛头与杆的连接处缠一圈**深色旧皮绳**扎紧，皮绳外再垂两绺很短的暗色缨穗。
杆：硬木长杆，深褐近黑，**通直、光素、没有木节、没有缠绕物、没有加装件**，从矛头正下方一直连续到底，直径自上而下非常缓慢地加粗。
杆尾：一只**铜质尾鐏**（金属尾套），收成一个钝尖。

背景中性灰，单光源从左前方 45 度，柔光，低对比，地面淡淡投影。写实电影级道具定妆照，50mm，全件清晰可读，浅景深但不糊结构。竖幅 9:16。

硬性禁止：**这不是火器**——不要枪托、不要握把、不要扳机、不要扳机护圈、不要击发机构、不要燧发夹、不要火门、不要准星照门、不要金属箍夹、不要弹匣、不要枪管；不要西洋骑枪、不要护手盘、不要旗帜红缨球；不要出现任何文字、签名、印章、题字、水印，一个汉字都不要有；不要人物、不要手、不要其他道具。'''

VARIANTS = {
    'P1': '',
    'P2': '\n\n追加：杆身在中段略微加粗形成一处便于握持的收腰，仍为同一根木杆、无任何加装物。',
    'P3': '\n\n追加：整件器物带明显使用痕迹——杆身有磕碰压痕与旧蜡色包浆，矛头根部有暗锈。',
    'P4': '\n\n追加：缨穗稍长一些、垂到矛头下方约一手掌，暗青色。',
    'P5': '\n\n追加：矛头更窄更长，呈柳叶形，倒须几乎不明显。',
    'P6': '\n\n追加：杆呈八角形截面而不是圆形，棱角清楚，仍为深色硬木、无加装物。',
}

res = []
for i, k in enumerate(sorted(VARIANTS)):
    pr = BODY + VARIANTS[k]
    io.open(os.path.join(OUT, k + '.txt'), 'w', encoding='utf-8').write(pr)
    try:
        urls = ark_img.call(pr, [], SEED0 + i, 1536, 2688)
        p = ark_img.fetch(urls[0], os.path.join(OUT, k + '_raw.png'))
        print('OK', k, os.path.getsize(p) // 1024, 'KB')
        res.append([k, 'ok'])
    except Exception as e:
        print('FAIL', k, repr(e)[:160])
        res.append([k, 'fail'])

json.dump(res, io.open(os.path.join(OUT, 'qiang_result.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('done', sum(1 for r in res if r[1] == 'ok'), '/', len(res))
