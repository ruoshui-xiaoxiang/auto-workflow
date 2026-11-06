# -*- coding: utf-8 -*-
"""画风归因第三轮 · 第 2 张：arm6 —— 只把 H12 首帧的第五张锚从 A09（真人照片感）换成 A09b（CG 渲染版），
提示词文字**一字不动**、seed 不变、锚的张数与尺寸不变。

判据（唯一变量＝第五张锚的渲染流派）：
  arm6 的男性若跟着变成渲染感 ⇒ C1 成立：真人感是**配角锚带进来的**，解法＝换卡（可修、可推广到 A08/A06/A07/A10）。
  arm6 的男性仍是真人照片感 ⇒ C2 成立：真人感是"现代混混男/机械义肢"这个**对象先验**带进来的，
                                 换卡无用，只能靠后期（换脸/风格化滤镜）或换引擎。
对照物是 arm1_base（现行配置，prompt sha da7787e07c8f），不重复烧钱。

⚠️ 已知污染，出图后一起看：A09b 本身四视图不自洽（正视图没有义肢、背视图两条义肢），
   所以 arm6 里男性的义肢可能变形或缺失——那是**卡的设定缺陷**，不算本臂的判据；
   本臂只读"皮肤/材质是照片感还是渲染感"这一维。
"""
import importlib.util, io, json, os, re, sys, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'kf_out', 'ab')
CAST = os.path.join(HERE, 'kf_out', 'cast')
SEED = 20260926
BASE_SHA = 'da7787e07c8f'          # arm1_base 的提示词指纹，必须逐字复现
NEW_CARD = os.path.join(CAST, 'A09b 粗臂男（混混）·CG渲染版.png')


def load():
    spec = importlib.util.spec_from_file_location('hs', os.path.join(HERE, 'h3_shots.py'))
    H = importlib.util.module_from_spec(spec)
    sys.modules['hs'] = H
    spec.loader.exec_module(H)
    H.build(H.load_ch1())
    for s in H.SHOTS:
        H.timing(s)
    return H


def main():
    import seedream as SD
    import numpy as np, cv2
    H = load()
    s = [x for x in H.SHOTS if x['id'] == 'H12'][0]
    assert os.path.isfile(NEW_CARD), '先跑 kf_cast_render.py 出 A09b'

    refs = list(H.kf_refs(s))
    old = [i for i, p in enumerate(refs) if os.path.basename(p).startswith('A09')]
    assert len(old) == 1, '第五张锚没找到：' + str([os.path.basename(p) for p in refs])
    i = old[0]
    old_card = refs[i]
    refs[i] = NEW_CARD                       # ← 本轮唯一改动

    prompt = H.compile_kf(s)
    sha = hashlib.md5(prompt.encode()).hexdigest()[:12]
    assert sha == BASE_SHA, '提示词与 arm1 不一致（%s≠%s），单变量前提破了' % (sha, BASE_SHA)

    W, Hh = 1344, 768
    scale = max(1.0, (1600000 / (W * Hh)) ** 0.5)
    ow, oh = int(round(W * scale / 32) * 32), int(round(Hh * scale / 32) * 32)
    print('== arm6_render_cast  锚 %d 张  第%d张 %s → %s' % (
        len(refs), i + 1, os.path.basename(old_card)[:24], os.path.basename(NEW_CARD)[:30]))
    print('   提示词 %d 字  sha %s（与 arm1 逐字相同）  seed %d' % (len(prompt), sha, SEED))

    urls = SD.call(prompt, [SD.data_uri(p) for p in refs], SEED, ow, oh)
    raw = SD.fetch(urls[0], os.path.join(OUT, 'arm6_render_cast_raw.png'))
    im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
    h, w = im.shape[:2]; cut = int(round(h * 0.02))
    im = im[cut:h - cut * 6, cut:w - cut]
    h2, w2 = im.shape[:2]
    if w2 / h2 > W / Hh:
        nw = int(round(h2 * W / Hh)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
    else:
        nh = int(round(w2 * Hh / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
    im = cv2.resize(im, (W, Hh), interpolation=cv2.INTER_AREA)
    dst = os.path.join(OUT, 'arm6_render_cast.png')
    cv2.imencode('.png', im)[1].tofile(dst)
    io.open(os.path.join(OUT, 'arm6_render_cast_prompt.txt'), 'w', encoding='utf8').write(prompt)
    print('   →', os.path.basename(dst))

    p = os.path.join(OUT, 'manifest3.json')
    old_m = json.load(io.open(p, encoding='utf8')) if os.path.isfile(p) else {}
    old_m['arm6_render_cast'] = dict(
        img=dst, seed=SEED, prompt_sha=sha, prompt_len=len(prompt), ts=time.strftime('%F %T'),
        refs=[os.path.basename(x) for x in refs],
        swapped={'slot': i + 1, 'out': os.path.basename(old_card), 'in': os.path.basename(NEW_CARD)},
        single_variable='只换第五张锚，提示词逐字等于 arm1_base',
        known_pollution='A09b 四视图不自洽（正视图无义肢/背视图双义肢），义肢形态不作本臂判据')
    json.dump(old_m, io.open(p, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('\n产物与生效配方：', OUT)


if __name__ == '__main__':
    main()
