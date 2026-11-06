# -*- coding: utf-8 -*-
"""第一章收尾：拼片 → 自检报告 → 上传到他网站审片区。

拆三个动作，各自可单独跑：
  --stitch   按 RUN 顺序把 H3 成片统一成 1280×720/24fps/aac 再 concat（重编码，必须带 -vf fps=24）
  --report   读 ledger + 重自检(qc_video/qc_asr)，出一份《自检报告.md》：逐镜 completed / 待判 / 判废
  --upload   传到 www.huahuayoueryuan.com 的 /review/<hash>/（生产机，只写静态文件，不碰任何服务）

画幅账：H3 出 1344×768（7:4），Seedance 那 8 条是 1280×720（16:9）。
统一到 1280×720＝H3 垂直裁 12px 再缩（1344×756→1280×720），不放大、不变形。
"""
import os, sys, json, time, hashlib, subprocess, argparse, re

_RES_RE = re.compile(r'Video:[^\n]*?\b(\d{3,5})x(\d{3,5})\b')

WZY = r'D:\AIWorkflow\tmp\wzy'
H3 = os.path.join(WZY, 'h3')
FF = r'D:\AIWorkflow\tools\ffmpeg.exe'
LED = os.path.join(H3, 'ledger.json')
BUILD = os.path.join(WZY, 'ch1_build')
SERVER = 'root@47.250.138.158'
KEY = '"$USERPROFILE/.ssh/server_deploy_key"'
OS = ['ssh', '-i', os.path.expandvars('$USERPROFILE/.ssh/server_deploy_key'),
      '-o', 'UserKnownHostsFile=/tmp/qoder_known_hosts', '-o', 'StrictHostKeyChecking=yes', SERVER]
SCP = OS + ['-o', 'UserKnownHostsFile=/tmp/qoder_known_hosts'] if False else [
    'scp', '-i', os.path.expandvars('$USERPROFILE/.ssh/server_deploy_key'),
    '-o', 'UserKnownHostsFile=/tmp/qoder_known_hosts', '-o', 'StrictHostKeyChecking=yes']


def log(*a): print('[%s]' % time.strftime('%H:%M:%S'), *a, flush=True)


def probe(src):
    """一次 ffmpeg -i 同时拿画幅和有无音轨（不引 cv2，也少起一次进程）。"""
    r = subprocess.run([FF, '-i', src], capture_output=True, text=True)
    e = r.stderr or ''
    m = _RES_RE.search(e)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0), 'Audio:' in e


def crop_169(w, h):
    """居中裁到严格 16:9，返回 crop=W:H:X:Y 死数。
    别用 crop='min(iw,ih*16/9)'... 那种表达式——逗号会被 ffmpeg 当滤镜链分隔符，
    报 "No such filter"（03:51 实测）。也别用 crop=ih*16/9:ih：那是给比 16:9 更宽的素材用的，
    H3 的 1344x768(1.750) 比 16:9(1.778) 窄，那条式子算出宽 1365 > 1344 直接报错。"""
    if not w or not h: return None
    if w * 9 > h * 16:                      # 比 16:9 宽 → 裁宽
        tw = int(h * 16 / 9) // 2 * 2; th = h
    else:                                   # 比 16:9 窄（含 7:4）→ 裁高
        tw = w; th = int(w * 9 / 16) // 2 * 2
    return 'crop=%d:%d:%d:%d' % (tw, th, (w - tw) // 2, (h - th) // 2)


def norm_to_720(src, dst):
    """居中裁到严格 16:9 → 缩 1280x720；24fps；aac 128k。
    无音轨的段补一条静音，否则和有声段一起 concat 会整条链崩（Seedance 那 8 条要逐条查）。"""
    (w, h), a = probe(src)
    cf = crop_169(w, h)
    if not cf:
        log('  探不到画幅', os.path.basename(src)); return None
    cmd = [FF, '-y', '-v', 'error', '-i', src]
    if not a:
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo']
    cmd += ['-vf', cf + ",scale=1280:720,fps=24,setsar=1",
            '-c:v', 'libx264', '-preset', 'medium', '-crf', '19', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-ac', '2']
    if not a:
        cmd += ['-map', '0:v:0', '-map', '1:a:0', '-shortest']
    cmd += [dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.isfile(dst) or os.path.getsize(dst) < 20000:
        log('  归一失败', os.path.basename(src), (r.stderr or '')[-300:]); return None
    return dst


def stitch():
    os.makedirs(BUILD, exist_ok=True)
    led = json.load(open(LED, encoding='utf8'))
    jobs = json.load(open(os.path.join(H3, 'jobs.json'), encoding='utf8'))
    order = ['H01', 'H02', 'H03', 'H04', 'H05', 'H06', 'H07', 'H08', 'H09', 'H10', 'H11',
             'H12', 'H13', 'H14', 'H15', 'H16', 'H17', 'H18', 'H19', 'H20', 'H21', 'H22', 'H23']
    SEED = {'H01': 'S01 古代线：留信、夜行、雾起、倒地.mp4', 'H02': 'S02 霓虹初醒.mp4',
            'H06': 'S02 霓虹初醒.mp4', 'H09': 'T09 巷道冲突：围拽与警告.mp4',
            'H10': 'T10 巷道冲突：外板下坠与红符号.mp4', 'H11': 'T11 巷道冲突：喝止与新武器之疑.mp4',
            'H12': 'T12 巷战第一合：扯枪与撞空当.mp4', 'H03': 'T04 古代线：雾涌探土、往回走.mp4'}
    PK = r'E:\创作\武昭君仪\武昭君仪资产包'
    parts, missing = [], []
    for sid in order:
        src = None
        if sid in led and led[sid].get('mp4') and os.path.isfile(led[sid]['mp4']):
            src = led[sid]['mp4']
        elif sid in SEED and os.path.isfile(os.path.join(PK, SEED[sid])):
            src = os.path.join(PK, SEED[sid])
        if not src:
            missing.append(sid); continue
        dst = os.path.join(BUILD, '%s.mp4' % sid)
        if not os.path.isfile(dst):
            if not norm_to_720(src, dst): missing.append(sid); continue
        parts.append(dst)
    lst = os.path.join(BUILD, 'list.txt')
    open(lst, 'w', encoding='utf8').write('\n'.join("file '%s'" % p.replace('\\', '/') for p in parts))
    out = os.path.join(BUILD, '武昭君仪_第一章_粗拼.mp4')
    subprocess.run([FF, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', lst,
                    '-vf', 'fps=24,format=yuv420p', '-c:v', 'libx264', '-preset', 'medium',
                    '-crf', '20', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out],
                   check=True)
    log('粗拼完成 %s（%d 段，缺 %s）' % (out, len(parts), missing or '无'))
    return out, missing


def report():
    led = json.load(open(LED, encoding='utf8'))
    jobs = {j['id']: j for j in json.load(open(os.path.join(H3, 'jobs.json'), encoding='utf8'))}
    L = ['# 第一章 H3 批次 · 自检报告（机器判，人未过）\n',
         '> 判定口径：**completed＝机器项全过**；待判＝有机器项不合格；confirmed 只能由人给，本报告不产出 confirmed。\n']
    done = [k for k, v in led.items() if v.get('verdict')]
    L.append('\n## 逐镜\n\n| 镜 | 帧 | 成片s | 实s | 用时 | s/帧 | 判定 | 不合格项 | 身份 | 风格 | 运动 | 音轨 |')
    L.append('|---|---|---|---|---|---|---|---|---|---|---|---|')
    for sid in sorted(jobs, key=lambda x: int(x[1:])):
        v = led.get(sid, {})
        q = v.get('qc') or {}
        asr = {}
        f = os.path.join(WZY, 'qc_asr', sid + '.json')
        if os.path.isfile(f): asr = json.load(open(f, encoding='utf8'))
        L.append('| %s | %d | %.1f | %.2f | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            sid, jobs[sid]['frames'], jobs[sid]['dur'], q.get('secs') or 0,
            v.get('wall') or '—', v.get('spf') or '—', v.get('verdict') or '未跑',
            '、'.join(v.get('bad') or []) or '—',
            ('%.2f' % q['arc_min']) if q.get('arc_min') is not None else '待补测',
            q.get('dino_flag') or '待补测', ('%.2f' % q['flow_mean']) if q.get('flow_mean') is not None else '—',
            asr.get('verdict') or '待补测'))
    L.append('\n## 中止与重跑记录\n')
    for k, v in led.items():
        if k.endswith('_attempt1') or v.get('reason'):
            L.append('- **%s**：%s' % (k, v.get('reason', '')))
            if v.get('lesson'): L.append('  - 取数：%s' % v['lesson'])
    L.append('\n## 机器判不了、必须人看的\n')
    L.append('- 表演与叙事是否成立（机器只看规格/身份/风格/运动/有声）。\n'
             '- 台词是否**真的逐字**：whisper-small 中文本身有错字，ASR 只判"有没有说、说的是不是这句"。\n'
             '- 混引擎观感：Seedance 8 条与 H3 若干条接在一起，跳不跳。\n'
             '- 那根长杆有没有在某一镜变成裸木杆或两根（首帧锁得住，中途漂移机器现在测不了）。\n'
             '- **背景招牌上的可读汉字**（H07 三拍未清，替身句压不住）：见 `h3/烧字清单.md`，遮/补/重拍由你定。\n'
             '- **远景小脸的身份**：脸 <190px 时 ArcFace 落在不可信区，机器既不能说对也不能说丢，只能你看。\n')
    p = os.path.join(H3, '自检报告.md')
    open(p, 'w', encoding='utf8').write('\n'.join(L))
    log('报告：', p)
    return p


def upload(path):
    h = hashlib.sha1((path + str(time.time())).encode()).hexdigest()[:16]
    dst = '/opt/product-site/public/review/%s/' % h
    # 审片码率：这台机下行实测只有 ~60KB/s，1.2Mbps 的 720p 网页才放得动
    web = os.path.join(BUILD, 'review_web.mp4')
    subprocess.run([FF, '-y', '-v', 'error', '-i', path, '-c:v', 'libx264', '-preset', 'slow',
                    '-b:v', '1200k', '-maxrate', '1500k', '-bufsize', '2400k', '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '96k', web], check=True)
    subprocess.run(OS + ['mkdir -p %s' % dst], check=True)
    subprocess.run(SCP + [web, '%s:%s' % (SERVER, dst)], check=True)
    page = ('<meta charset=utf-8><title>武昭君仪 第一章 粗拼审片</title>'
            '<video controls preload=metadata style="width:100%%" src="review_web.mp4"></video>'
            '<p>审片区无鉴权，只靠这串 16 位路径；审完告知即删。</p>')
    lp = os.path.join(BUILD, 'index.html')
    open(lp, 'w', encoding='utf8').write(page)
    subprocess.run(SCP + [lp, '%s:%s' % (SERVER, dst)], check=True)
    url = 'https://www.huahuayoueryuan.com/review/%s/' % h
    log('已上传：', url)
    return url


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--stitch', action='store_true')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--upload', action='store_true')
    a = ap.parse_args()
    if a.stitch or not (a.report or a.upload):
        p, miss = stitch()
    if a.report or a.upload: report()
    if a.upload: upload(p)
