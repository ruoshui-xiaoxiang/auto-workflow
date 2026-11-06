# -*- coding: utf-8 -*-
"""云端 Seedream 出图（本项目自带一份，横屏参数；不复用剑来那个写死 1536×2688 的脚本）。

用法：
  python seedream.py <out_dir> <prefix> <prompt_file> <img1> [img2 ...] [--n 2] [--wh 1344x768] [--seed N]
模型 doubao-seedream-4-0-250828（本账号实测唯一可用档，5-0-pro 报 400/404）。
密钥从 ~/.arkcli/config.yaml 读，不回显。产物右下角带"AI生成"烧录水印，出图后自动裁掉外圈再居中裁到目标画幅。
"""
import base64, io, json, os, re, sys, urllib.request

MODEL = 'doubao-seedream-4-0-250828'
URL = 'https://ark.cn-beijing.volces.com/api/v3/images/generations'
CONF = r'C:/Users/若水/.arkcli/config.yaml'

def key():
    m = re.search(r'^\s*api_key\s*:\s*[\"\']?(\S+?)[\"\']?\s*$', io.open(CONF, encoding='utf8').read(), re.M)
    if not m: raise SystemExit('NO_KEY_IN_CONFIG')
    return m.group(1)

def data_uri(p):
    ext = os.path.splitext(p)[1].lstrip('.').lower() or 'png'
    return 'data:image/%s;base64,%s' % (ext, base64.b64encode(open(p, 'rb').read()).decode())

def call(prompt, imgs, seed, w, h):
    body = dict(model=MODEL, prompt=prompt, size='%dx%d' % (w, h), response_format='url',
                sequential_image_generation='disabled', seed=seed)
    if imgs: body['image'] = imgs if len(imgs) > 1 else imgs[0]
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + key()}, method='POST')
    with urllib.request.urlopen(req, timeout=300) as r:
        return [d['url'] for d in json.loads(r.read().decode()).get('data', [])]

def fetch(u, dst):
    with urllib.request.urlopen(u, timeout=180) as r:
        open(dst, 'wb').write(r.read())
    return dst

def main():
    import numpy as np, cv2
    a = sys.argv[1:]
    out, prefix, pf = a[0], a[1], a[2]
    rest = a[3:]
    n, wh, seed = 1, '1344x768', 20260926
    for flag in ('--n', '--wh', '--seed'):
        if flag in rest:
            i = rest.index(flag); v = rest[i + 1]; rest = rest[:i] + rest[i + 2:]
            {'--n': lambda: None, }  # noqa
            if flag == '--n': n = int(v)
            if flag == '--wh': wh = v
            if flag == '--seed': seed = int(v)
    W, H = [int(x) for x in wh.split('x')]
    # Seedream 只吃面积够大的尺寸；按目标宽高比放大到 ≥1.6MP 再出，回来缩到目标
    scale = max(1.0, (1600000 / (W * H)) ** 0.5)
    ow, oh = int(round(W * scale / 32) * 32), int(round(H * scale / 32) * 32)
    os.makedirs(out, exist_ok=True)
    prompt = io.open(pf, encoding='utf8').read().strip()
    imgs = [data_uri(p) for p in rest]
    for k in range(n):
        try:
            urls = call(prompt, imgs, seed + k * 7, ow, oh)
        except Exception as e:
            print('FAIL', k, str(e)[:220]); continue
        for u in urls:
            raw = fetch(u, os.path.join(out, '%s_s%d_raw.png' % (prefix, k)))
            im = cv2.imdecode(np.fromfile(raw, np.uint8), cv2.IMREAD_COLOR)
            h, w = im.shape[:2]
            # 右下角水印：Seedream 4-0 实测烧在右下角约 1/9 宽 × 1/14 高，裁掉外圈再居中裁画幅
            cut = int(round(h * 0.02))
            im = im[cut:h - cut * 6, cut:w - cut]
            h2, w2 = im.shape[:2]
            if w2 / h2 > W / H:                      # 太宽 → 裁宽
                nw = int(round(h2 * W / H)); x = (w2 - nw) // 2; im = im[:, x:x + nw]
            else:                                    # 太高 → 裁高
                nh = int(round(w2 * H / W)); y = (h2 - nh) // 2; im = im[y:y + nh, :]
            im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA)
            dst = os.path.join(out, '%s_s%d.png' % (prefix, k))
            cv2.imencode('.png', im)[1].tofile(dst)
            print('OK', os.path.basename(dst), im.shape[1], 'x', im.shape[0])

if __name__ == '__main__':
    main()
