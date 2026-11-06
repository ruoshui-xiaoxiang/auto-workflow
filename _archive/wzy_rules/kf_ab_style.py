# -*- coding: utf-8 -*-
"""画风单变量对照（任务 #30）：H12 首帧三臂，一次同时判两个假设。

为什么是 H12 一镜三臂而不是 H12/H13 各两臂：
  假设 A＝「正向渲染流派句推得动画风」；假设 B＝「真人感是挂的 A09 那张真人感配角锚拽的」。
  三臂（基线／加句／撤锚）在同一镜上就能把 A、B 分开；结论对 H13 可迁移（同通道同锚族），
  所以这一轮只花 3 张图，不花 6 张。H13 等选定修法之后一次出对的那版。

臂设计（seed 全同，只动一个变量）：
  arm1 base     ＝ 现行锚序（含 A09）＋ STYLE_RENDER_LOCK 关   ← 复现现状，作对照
  arm2 style_on ＝ 现行锚序（含 A09）＋ STYLE_RENDER_LOCK 开   ← 只动文字 ⇒ 判 A
  arm3 no_cast  ＝ 撤掉 A09 那张配角锚 ＋ STYLE_RENDER_LOCK 关 ← 只动锚 ⇒ 判 B

只读地临时改 H.KNOBS_ON，不落盘、不改 h3/ 下任何现行提示词。产物写 kf_out/ab/，
每臂一份 manifest 记"当时开着什么"（跟账本 knobs 同一思路：可归因优先）。
"""
import importlib.util, io, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'kf_out', 'ab')
STYLE_SENTENCE = ('3D rendered CGI character, soft pore-free subsurface-shaded skin, '
                  'stylized-realistic game cinematics look')
ARMS = [('arm1_base', True, False),      # (名字, 挂不挂配角锚, 开不开风格句)
        ('arm2_style_on', True, True),
        ('arm3_no_cast', False, False)]


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
    os.makedirs(OUT, exist_ok=True)
    refs_all = H.kf_refs(s)
    cast_idx = len(refs_all) - 1 if s['id'] in H.CAST_ANCHOR else None
    man = {}
    for name, keep_cast, style_on in ARMS:
        H.KNOBS_ON.clear()
        if style_on:
            H.KNOBS_ON['STYLE_RENDER_LOCK'] = STYLE_SENTENCE
        prompt = H.compile_kf(s)
        refs = list(refs_all) if keep_cast else refs_all[:cast_idx]
        duty_cut = '' if keep_cast else '（本臂撤掉第五张配角锚 ⇒ 职责句里"第五张"悬空，见下方核对）'
        # 撤锚后必须同步删掉职责句里那一段，否则提示词会指向不存在的图（编号对齐是硬纪律）
        if not keep_cast and H.CAST_ANCHOR.get(s['id']):
            tg, nm = H.CAST_ANCHOR[s['id']]
            bad = ('第五张（%s %s）' % (tg, nm))
            if bad in prompt:
                i = prompt.index(bad)
                j = prompt.find('\n\n', i)
                prompt = prompt[:i] + (prompt[j:] if j > 0 else '')
                duty_cut = '已同步删第五张职责句'
        W, Hh = 1344, 768
        scale = max(1.0, (1600000 / (W * Hh)) ** 0.5)
        ow, oh = int(round(W * scale / 32) * 32), int(round(Hh * scale / 32) * 32)
        print('== %s  锚 %d 张  风格句 %s  提示词 %d 字' % (
            name, len(refs), 'ON' if style_on else 'off', len(prompt)))
        try:
            urls = SD.call(prompt, [SD.data_uri(p) for p in refs], 20260926, ow, oh)
        except Exception as e:
            print('   FAIL', str(e)[:200]); man[name] = {'error': str(e)[:300]}; continue
        u = urls[0]
        raw = SD.fetch(u, os.path.join(OUT, name + '_raw.png'))
        im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
        h, w = im.shape[:2]
        cut = int(round(h * 0.02))
        im = im[cut:h - cut * 6, cut:w - cut]
        h2, w2 = im.shape[:2]
        if w2 / h2 > W / Hh:
            nw = int(round(h2 * W / Hh)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
        else:
            nh = int(round(w2 * Hh / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
        im = cv2.resize(im, (W, Hh), interpolation=cv2.INTER_AREA)
        dst = os.path.join(OUT, name + '.png')
        cv2.imencode('.png', im)[1].tofile(dst)
        man[name] = dict(img=dst, style_on=style_on, keep_cast=keep_cast,
                         refs=[os.path.basename(p) for p in refs], note=duty_cut,
                         prompt_len=len(prompt), prompt_sha=H.__dict__ and __import__('hashlib').md5(
                             prompt.encode()).hexdigest()[:12],
                         seed=20260926, ts=time.strftime('%F %T'))
        io.open(os.path.join(OUT, name + '_prompt.txt'), 'w', encoding='utf8').write(prompt)
        print('   →', os.path.basename(dst))
    H.KNOBS_ON.clear()
    json.dump(man, io.open(os.path.join(OUT, 'manifest.json'), 'w', encoding='utf8'),
              ensure_ascii=False, indent=1)
    print('\n三臂产物与生效配方：', OUT)


if __name__ == '__main__':
    main()
