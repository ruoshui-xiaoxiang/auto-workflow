# -*- coding: utf-8 -*-
"""第一章 H3 批次驱动器（整批已授权，无人值守；每镜跑完立刻自检并留痕）。

为什么要有这个文件：今晚人不在，14 镜按链序串行，任何一镜的产物都是下一镜的首帧输入，
手搓命令必然记错顺序。这里把「提交 → 等落盘 → 抽末帧 → 自检 → 记账」锁成一条，
并且**只往 ledger 追加，不覆盖**，出问题能回溯到第几次重跑。

判定纪律：机器只给 completed / 待判 / 判废，不给 confirmed（人眼没过就不算过）。
决策闸 D1：首镜实测 s/帧 决定后续长镜是否降档（见 出片计划.md §4）。
"""
import os, sys, json, time, subprocess, argparse, re
import numpy as np, cv2

_FILE_RE = re.compile(r'"([A-Za-z]:[^"]*?\.mp4)"')   # 引擎 stdout 里的 JSON 路径是双反斜杠

WZY = r'D:\AIWorkflow\tmp\wzy'
H3 = os.path.join(WZY, 'h3')
KF = os.path.join(WZY, 'kf_out')
LEDGER = os.path.join(H3, 'ledger.json')
ENGINE = r'D:\AIWorkflow\engine'
PY = sys.executable
OUTDIR = r'D:\AIWorkflow\ComfyUI_H3\output'
# 引擎跑完会把产物 relocate 出 ComfyUI 的 output 目录（→ 资源池\武昭君仪\批次\<ts>\video\）。
# 03:30 踩过：只在 OUTDIR 找 mp4，把一次成功的渲染（1648s / 362 帧）判成"无产物"并停了整批。
POOLDIR = r'E:\图像影音资源池\武昭君仪\批次'
# 1344×768 实测（H05，362 帧，含 VAE+音频解码）：1648.4s = 4.55 s/帧 → D1 闸（6.5）通过，不降档。
# 02:25 那次"328 帧跑 70 分钟"是我看错表（把 02:25 当 03:10），不是换页悬崖；已记入 ledger。
RES = (1344, 768)
POOL = {'SC01': 'anc', 'SC02': 'anc'}


def log(*a):
    print('[%s]' % time.strftime('%H:%M:%S'), *a, flush=True)


def load_ledger():
    return json.load(open(LEDGER, encoding='utf8')) if os.path.isfile(LEDGER) else {}


def save_ledger(d):
    json.dump(d, open(LEDGER, 'w', encoding='utf8'), ensure_ascii=False, indent=1)


def patch_ledger(key, val):
    """只往盘上写自己这一条，写前重新读盘合并。
    08:07 踩过：驱动全程用内存里那份 led，每镜结束整份覆盖写回，
    把我 05:36 在外部标的 H08=判废（复制主角脸）在 05:53 又冲回成 completed。
    外部改判（人/我自己复盘）必须能活过驱动的下一次落盘。"""
    d = load_ledger()
    d[key] = val
    save_ledger(d)
    return d


def grab_last_frame(mp4, dst, back=2, size=None):
    cap = cv2.VideoCapture(mp4)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, n - 1 - back))
    ok, fr = cap.read(); cap.release()
    if not ok: return None
    TW, TH = size or RES
    h, w = fr.shape[:2]
    if (w, h) == (TW, TH):
        cv2.imwrite(dst, fr); return dst
    r = TH / h; im = cv2.resize(fr, (int(round(w * r)), TH), interpolation=cv2.INTER_CUBIC)
    x = (im.shape[1] - TW) // 2
    im = im[:, max(0, x):max(0, x) + TW]
    cv2.imwrite(dst, im)
    return dst


def _prompt_path(job):
    return os.path.join(H3, '%s_video.txt' % job['id'])


def prompt_fp(job):
    """现行提示词文件的 md5（前 12 位）。写进账本，日后能证明这张成片是哪一版词渲的。"""
    import hashlib
    path = _prompt_path(job)
    if not os.path.isfile(path):
        return None
    return hashlib.md5(open(path, 'rb').read()).hexdigest()[:12]


def knobs_now():
    """这批开着哪几条"未实测候选句"。全关也要记（on=[] 是一个事实）。
    09-27 他定：规则不能定死，不然中途出偏移不知道是哪条造成的 ⇒ 生效配方必须可回查。"""
    p = os.path.join(H3, 'knobs.json')
    if not os.path.isfile(p):
        return {'on': None, 'note': '无 knobs.json（提示词表未重出或为旧版）⇒ 生效配方未知'}
    d = json.load(open(p, encoding='utf8'))
    return {'on': d.get('on'), 'text': d.get('text'), 'src_mtime': d.get('src_mtime')}


def prompt_mt(job):
    path = _prompt_path(job)
    return time.strftime('%F %T', time.localtime(os.path.getmtime(path))) if os.path.isfile(path) else None

def newest_mp4(after_ts, stdout=''):
    """产物可能在 ComfyUI output，也可能已被引擎 relocate 到资源池批次目录。
    先信引擎自己报的路径（stdout 里的 files 列表），再退回扫盘。"""
    c = []
    for m in _FILE_RE.finditer(stdout or ''):
        p = m.group(1).replace('\\\\', '\\')
        if p.lower().endswith('.mp4') and os.path.isfile(p):
            c.append(p)
    for d in (OUTDIR, POOLDIR):
        if not os.path.isdir(d): continue
        for root, _, fs in os.walk(d):
            for f in fs:
                if not f.lower().endswith('.mp4'): continue
                p = os.path.join(root, f)
                try:
                    if os.path.getmtime(p) >= after_ts - 5 and os.path.getsize(p) > 100000:
                        c.append(p)
                except OSError:
                    pass
    return max(set(c), key=os.path.getmtime) if c else None


TRANSIENT = ('HostBuffer.read_file_slice', 'read_file_slice failed', 'mkl_malloc',
             'cudaErrorMemoryAllocation', 'os error 1455', 'The paging file is too small')
COMFY_LOG = r'D:\AIWorkflow\logs\comfyui_h3.log'


def comfy_err_tail(after_ts):
    """引擎 stdout 只回 execution_error，真正的报错文本在 ComfyUI 服务端日志里。
    不读它就分不清"内存挤爆"和"提示词违规"，前者该重试、后者不该。"""
    try:
        with open(COMFY_LOG, 'rb') as f:
            f.seek(max(0, os.path.getsize(COMFY_LOG) - 12000))
            return f.read().decode('utf8', 'replace').replace('\r', '\n')
    except OSError:
        return ''


def submit(job, first_frame, tries=3):
    """aimdo 的锁页缓冲在内存吃紧时会分配失败（03:39/03:40 实测：1.9GB 空闲 + 6GB 被 Windows 压缩，
    两次都在建模前 13 秒挂掉）。这类失败不是提示词/资产问题，重试即可；
    但必须只重试这种，真失败（审核、缺文件）不能重试——那会白烧一晚上。"""
    last = (None, 0.0, '')
    for k in range(tries):
        t0 = time.time()
        cmd = [PY, os.path.join(ENGINE, 'run.py'), 'h3_i2va_batch', '--project', '武昭君仪',
               '--set', 'theme=武昭君仪-第一章-%s' % job['id'],
               '--set', 'prompt_file=%s' % os.path.join(H3, '%s_video.txt' % job['id']),
               '--set', 'ref_images=%s' % first_frame,
               '--set', 'width=%d' % job.get('w', RES[0]),
               '--set', 'height=%d' % job.get('h', RES[1]),
               '--set', 'length=%d' % job['frames'], '--set', 'duration=%.2f' % job['secs'],
               '--set', 'steps=8', '--set', 'seed=%d' % job['seed']]
        if job.get('no_audio'): cmd += ['--set', 'no_audio=true']
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf8', errors='replace',
                           cwd=ENGINE, timeout=job['frames'] * 8 + 1200)
        wall = time.time() - t0
        out = (r.stdout or '') + (r.stderr or '')
        mp4 = newest_mp4(t0, out)
        tail = (r.stdout or '')[-500:] + (r.stderr or '')[-500:]
        err = comfy_err_tail(t0)
        last = (mp4, wall, tail + '\n--comfy--\n' + err[-400:])
        if mp4:
            return mp4, wall, tail + ('\n[第 %d 次尝试成功]' % (k + 1) if k else '')
        transient = any(t in out or t in err for t in TRANSIENT)
        if not transient:
            return mp4, wall, tail + '\n--comfy--\n' + err[-400:]
        if k < tries - 1:
            log('  瞬时故障(锁页内存)，60s 后重试 %d/%d' % (k + 1, tries - 1))
            time.sleep(60)
    return last



def qc(mp4, job):
    cmd = [PY, os.path.join(WZY, 'video_qc.py'), '--video', mp4, '--shot', job['id'],
           '--pool', POOL.get(job['scene'], 'cyb'), '--light']
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='')      # 别和 GPU 上的渲染抢
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf8',
                       errors='replace', env=env, timeout=900)
    j = os.path.join(WZY, 'qc_video', job['id'] + '.json')
    return json.load(open(j, encoding='utf8')) if os.path.isfile(j) else {'raw': r.stdout[-400:]}


def verdict(job, q):
    """机器判据 → 只出 completed / 待判 / 判废，不判好坏。"""
    bad = []
    if (q.get('w'), q.get('h')) != (job.get('w', RES[0]), job.get('h', RES[1])): bad.append('画幅')
    if (q.get('n') or 0) % 17 != 5: bad.append('帧数不在17n+5')
    if q.get('secs', 0) + 0.05 < job['dur']: bad.append('时长不够台词')
    am = q.get('arc_min')
    # 分清"测了但不好"和"light 模式压根没测"：后者不能记成不合格项，
    # 否则整批每条都挂着"有脸帧不足"的莫须有罪名（H07 04:03 就是这样被记成待判的）。
    # 顺序有讲究：脸太小（<190px，ArcFace 落不可信区）要先判，否则会把"测不准"报成"身份丢"。
    if 'face_frames' in q:
        if q['face_frames'] < 4: bad.append('有脸帧不足')
        elif (q.get('face_px') or 0) < 190: bad.append('身份机器判不了(脸%dpx)' % (q.get('face_px') or 0))
        elif am is not None and am < 0.45: bad.append('身份丢(%.2f)' % am)
    if q.get('dino_flag') and q['dino_flag'] != '带内': bad.append('漂出基线')
    if q.get('flow_mean') is not None and q['flow_mean'] < 0.35: bad.append('几乎不动')
    au = q.get('audio')
    if not au: bad.append('无音轨')
    elif au.get('rms', 0) < 0.005: bad.append('音轨近乎静音')
    return ('completed' if not bad else '待判'), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='frm', default='H05')
    ap.add_argument('--only', default=None, help='只跑这几镜，逗号分隔')
    a = ap.parse_args()
    jobs = json.load(open(os.path.join(H3, 'jobs.json'), encoding='utf8'))
    only = set(x.strip() for x in a.only.split(',')) if a.only else None
    led = load_ledger()
    order = [j['id'] for j in jobs]
    started = only is not None
    for job in jobs:
        if only:
            if job['id'] in only: pass
            else: continue
        else:
            if not started and job['id'] != a.frm: continue
            started = True
        # 有产物就不重跑：待判＝等人眼，重跑等于把 27 分钟 GPU 扔掉。
        # （旧条件只跳 completed，会让看门狗在收尾时把"待判"的 H07 整条重渲一遍。）
        if led.get(job['id'], {}).get('verdict') in ('completed', '待判') and not only:
            e = led[job['id']]
            w = ''
            if e.get('prompt_md5') and e['prompt_md5'] != prompt_fp(job):
                w = ' ⚠账本指纹≠现行提示词 ⇒ 成片是旧版词渲的，别当已验'
            elif not e.get('prompt_md5'):
                w = ' ⚠账本无提示词指纹（旧记录）⇒ 无法证明成片对应现行版本'
            log('skip', job['id'], '已有产物（%s）%s' % (e['verdict'], w)); continue
        ff = job['first_frame']
        if not os.path.isabs(ff): ff = os.path.join(KF, ff)
        if not os.path.isfile(ff):
            log('!! 缺首帧，跳过并停链：', job['id'], ff)
            break
        log('提交 %s  %d帧  首帧=%s' % (job['id'], job['frames'], os.path.basename(ff)))
        mp4, wall, tail = submit(job, ff)
        if not mp4:
            # 「无产物」有两种：一种是我们自己 interrupt 掉的（引擎尾巴里写 execution_interrupted），
            # 一种是真失败。前者不能占用镜号键——否则会把同镜下一次在跑的尝试盖成"失败"（02:26 真撞过）。
            ours = 'execution_interrupted' in tail
            k = job['id'] + ('_aborted' if ours else '_failed')
            led[k] = dict(verdict='主动中止' if ours else '判废', error='无产物',
                          note='本驱动自己 interrupt 的，不代表模型失败' if ours else '',
                          tail=tail[-300:], ts=time.strftime('%F %T'))
            led = patch_ledger(k, led[k]); log('FAIL 无产物', k, '（中止，继续）' if ours else '（真失败，停批）')
            if not ours: break
            continue
        spf = wall / job['frames']
        q = qc(mp4, job)
        v, bad = verdict(job, q)
        if led.get(job['id'], {}).get('verdict') == 'completed' and v != 'completed':
            log('  已有 completed，不覆盖'); continue
        led[job['id']] = dict(verdict=v, mp4=mp4, prompt_md5=prompt_fp(job),
                              prompt_src_mtime=prompt_mt(job), knobs=knobs_now(),
                              wall=round(wall), spf=round(spf, 2),
                              bad=bad, qc={k: q.get(k) for k in
                                           ('n', 'fps', 'secs', 'face_px', 'arc_min', 'dino_vs_base',
                                            'dino_flag', 'flow_mean', 'audio', 'corner_edge_ratio',
                                            'sheet')}, ts=time.strftime('%F %T'), seed=job['seed'])
        led = patch_ledger(job['id'], led[job['id']])
        log('%s %s  %.0fs (%.2f s/帧)  %s' % ('✔' if v == 'completed' else '!', v, wall, spf, bad or ''))
        nxt = order.index(job['id']) + 1
        if nxt < len(jobs) and jobs[nxt].get('first_frame_from') == job['id']:
            dst = os.path.join(KF, '%s_first.png' % jobs[nxt]['id'])
            if grab_last_frame(mp4, dst, size=(job.get('w', RES[0]), job.get('h', RES[1]))):
                jobs[nxt]['first_frame'] = dst
                json.dump(jobs, open(os.path.join(H3, 'jobs.json'), 'w', encoding='utf8'),
                          ensure_ascii=False, indent=1)
                log('  抽末帧 →', jobs[nxt]['id'], '首帧')
        if spf > 6.5:
            log('D1 闸触发：s/帧 %.2f > 6.5，停批等人/或降档重排' % spf)
            break


if __name__ == '__main__':
    main()
