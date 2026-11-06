# -*- coding: utf-8 -*-
"""画风/锚点归因第二轮：撤武器（他 09-27 点名"不带武器跑看看"）。

臂设计（同 seed 20260926，每臂只动一件事；编号在撤锚后重排，保证"第N张"与 images 顺序对齐）：
  arm4_no_prop      ＝ 只撤 P01 道具锚（含删其职责句）。**对杆的文字要求全部保留**
                       ⇒ 判两件事：① 没有道具锚时那根杆会漂成什么；② 道具锚在不在，画风动不动。
  arm5_no_prop_cast ＝ 武器锚＋配角锚都撤 ⇒ 画面里只剩"君仪＋她手里那根杆"的文字要求
                       ⇒ 判上一轮那条假设 C：真人感到底是"现代混混男"这个对象带进来的，还是锚带进来的。
对照物是上一轮的 arm1_base（现行配置），不重复烧钱。

只读地临时改 H.KNOBS_ON / 提示词文本，不落盘、不动 h3/ 下任何现行提示词。
"""
import importlib.util, io, json, os, re, sys, time, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, 'kf_out', 'ab')
SEED = 20260926
# (臂名, 要撤的锚文件关键字, ...)
ARMS = [('arm4_no_prop', ['P01']),
        ('arm5_no_prop_cast', ['P01', 'A09'])]
CN = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六'}


def load():
    spec = importlib.util.spec_from_file_location('hs', os.path.join(HERE, 'h3_shots.py'))
    H = importlib.util.module_from_spec(spec)
    sys.modules['hs'] = H
    spec.loader.exec_module(H)
    H.build(H.load_ch1())
    for s in H.SHOTS:
        H.timing(s)
    return H


def drop_duty(prompt, slot_no):
    """删掉"第N张（…）＝…"那一段职责句。
    ⚠️ 职责句之间只用单个换行分隔，整段【参考素材职责】才以空行结尾——
       所以截断点必须取"下一个第M张的起点"与"下一个空行"里更靠前的那个，
       否则撤一张会把后面几张一起吞掉（dry-run 抓到过）。"""
    mark = '第%s张（' % CN[slot_no]
    i = prompt.find(mark)
    if i < 0:
        return prompt, False
    ends = [len(prompt)]
    j = prompt.find('\n\n', i)
    if j > 0:
        ends.append(j)
    for n in CN.values():
        k = prompt.find('第%s张（' % n, i + 1)
        if k > 0:
            ends.append(k)
    e = min(ends)
    cut = prompt[i:e]
    if cut.endswith('\n'):
        cut = cut[:-1]
    return prompt[:i] + prompt[i + len(cut):], True


def renumber(prompt, removed):
    """撤掉第 k 张之后，后面所有"第N张"整体前移，保持与 images 数组同序。"""
    for k in sorted(removed, reverse=True):
        prompt = prompt.replace('第%s张' % CN[k], '\x00%d' % k)
    out = []
    for tok in re.split(r'(\x00\d)', prompt):
        if tok.startswith('\x00'):
            out.append(tok)
        else:
            out.append(tok)
    prompt = ''.join(out)
    # 逐个把 >k 的编号减 1（从大到小替换避免连锁）
    for k in sorted(removed, reverse=True):
        for n in range(k + 1, 7):
            prompt = prompt.replace('第%s张' % CN[n], '第%s张' % CN[n - 1])
    return re.sub(r'\x00\d', '', prompt)


def main():
    import seedream as SD
    import numpy as np, cv2
    H = load()
    s = [x for x in H.SHOTS if x['id'] == 'H12'][0]
    os.makedirs(OUT, exist_ok=True)
    refs_all = H.kf_refs(s)
    prompt_base = H.compile_kf(s)
    man = {}
    for name, drops in ARMS:
        refs, removed = list(refs_all), []
        prompt = prompt_base
        for kw in drops:
            # ⚠️ 槽位一律按**原始序号**记：先 pop 掉第四张会让第五张前移成"第四张"，
            #    用 pop 后的下标反推会把两张当成同一张（dry-run 抓到过）。
            hit = [i for i, p in enumerate(refs_all) if os.path.basename(p).startswith(kw)]
            if not hit:
                print('   ! 没找到 %s 锚' % kw); continue
            i = hit[0]
            removed.append(i + 1)
            refs = [p for j, p in enumerate(refs_all) if j + 1 not in removed]
        for slot in sorted(set(removed), reverse=True):
            prompt, ok = drop_duty(prompt, slot)
            if not ok:
                print('   ! 职责句里没找到 第%s张' % CN[slot])
        prompt = renumber(prompt, removed)
        W, Hh = 1344, 768
        scale = max(1.0, (1600000 / (W * Hh)) ** 0.5)
        ow, oh = int(round(W * scale / 32) * 32), int(round(Hh * scale / 32) * 32)
        stray = [m for m in re.findall(r'第[一二三四五六]张', prompt) if m not in
                 ['第%s张' % CN[i] for i in range(1, len(refs) + 1)]]
        print('== %-20s 锚 %d 张 %s  提示词 %d 字  悬空编号 %s' % (
            name, len(refs), [os.path.basename(p)[:14] for p in refs], len(prompt), stray or '无'))
        try:
            urls = SD.call(prompt, [SD.data_uri(p) for p in refs], SEED, ow, oh)
        except Exception as e:
            print('   FAIL', str(e)[:200]); man[name] = {'error': str(e)[:300]}; continue
        raw = SD.fetch(urls[0], os.path.join(OUT, name + '_raw.png'))
        im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
        h, w = im.shape[:2]; cut = int(round(h * 0.02))
        im = im[cut:h - cut * 6, cut:w - cut]
        h2, w2 = im.shape[:2]
        if w2 / h2 > W / Hh:
            nw = int(round(h2 * W / Hh)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
        else:
            nh = int(round(w2 * Hh / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
        im = cv2.resize(im, (W, Hh), interpolation=cv2.INTER_AREA)
        dst = os.path.join(OUT, name + '.png')
        cv2.imencode('.png', im)[1].tofile(dst)
        io.open(os.path.join(OUT, name + '_prompt.txt'), 'w', encoding='utf8').write(prompt)
        man[name] = dict(img=dst, dropped=[os.path.basename(refs_all[i - 1][:40]) for i in removed],
                         refs=[os.path.basename(p) for p in refs], prompt_sha=hashlib.md5(
                             prompt.encode()).hexdigest()[:12], prompt_len=len(prompt),
                         seed=SEED, ts=time.strftime('%F %T'))
        print('   →', os.path.basename(dst))
    p = os.path.join(OUT, 'manifest2.json')
    old = {}
    if os.path.isfile(p):
        old = json.load(io.open(p, encoding='utf8'))
    old.update(man)
    json.dump(old, io.open(p, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print('\n产物与生效配方：', OUT)


if __name__ == '__main__':
    main()
