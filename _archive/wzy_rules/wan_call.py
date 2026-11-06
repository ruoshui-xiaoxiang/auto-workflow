# -*- coding: utf-8 -*-
"""万相 3.0 调用器（token-plan 百炼计划）。
用法:
  python wan_call.py t2v "<提示词>" 5 480P           # 文生视频测试
  python wan_call.py i2v "<提示词>" 5 480P <首帧图>  # 图生视频（图先传到服务器）
支持断点：任务提交后把 task id 记进 wan_tasks.json，轮询续查。
"""
import json, os, sys, time, subprocess, argparse
from pathlib import Path
import requests

CFG = json.load(open(r'C:/Users/若水/.bailian/config.json', encoding='utf8'))
PLAN = CFG.get('token-plan', {})
_lines = Path(r'E:/密钥文件/阿里多模态.txt').read_text(encoding='utf8').strip().splitlines()
KEY = _lines[0].strip() if _lines else PLAN.get('api_key', '')
ENDPOINT = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis'
TASKS = Path(r'D:/AIWorkflow/tmp/wzy/wan_tasks.json')
OUT = Path(r'D:/AIWorkflow/tmp/wzy/wan_out')
OUT.mkdir(parents=True, exist_ok=True)

HDR = {'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'}


def submit(prompt, duration, resolution, media=None, ratio='adaptive'):
    body = {'model': 'wan3.0-video',
            'input': {'prompt': prompt},
            'parameters': {'resolution': resolution, 'ratio': ratio,
                           'duration': int(duration), 'prompt_extend': False}}
    if media:
        body['input']['media'] = media
    r = requests.post(ENDPOINT, headers={**HDR, 'X-DashScope-Async': 'enable'},
                      json=body, timeout=60)
    j = r.json()
    if r.status_code != 200 or 'task_id' not in j:
        print('提交失败:', r.status_code, json.dumps(j, ensure_ascii=False)[:500])
        return None
    print('已提交 task_id=%s' % j['task_id'])
    return j['task_id']


def poll(task_id, timeout=1800):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get('https://dashscope.aliyuncs.com/api/v1/tasks/' + task_id,
                         headers=HDR, timeout=30)
        j = r.json()
        st = j.get('output', {}).get('task_status', '')
        if st in ('SUCCEEDED', 'Succeeded', 'succeeded'):
            return j
        if st in ('FAILED', 'Failed', 'CANCELED', 'Canceled'):
            print('任务失败:', json.dumps(j, ensure_ascii=False)[:600])
            return j
        print('[%s] %s ...' % (time.strftime('%H:%M:%S'), st), flush=True)
        time.sleep(15)
    return None


def download(j, name):
    try:
        url = j['output']['video_url'] or j['output']['results']['video_url']
    except Exception:
        url = json.dumps(j, ensure_ascii=False)
        print('拿不到下载地址:', url[:400])
        return None
    dst = OUT / name
    subprocess.run(['curl', '-sL', '-o', str(dst), url], check=True)
    print('已下载:', dst, dst.stat().st_size)
    return dst


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['t2v', 'i2v'])
    ap.add_argument('prompt')
    ap.add_argument('duration', type=int)
    ap.add_argument('resolution', default='480P')
    ap.add_argument('image', nargs='?')
    a = ap.parse_args()
    media = None
    if a.mode == 'i2v':
        if not a.image:
            sys.exit('i2v 需要首帧图')
        # 本机图先传到用户服务器，用公网 URL（百炼 media 只收 URL）
        import hashlib
        fn = 'wanff_' + hashlib.md5(Path(a.image).name.encode('utf8')).hexdigest()[:10] + '.png'
        # Windows 中文用户名路径在 ssh/scp 下有编码问题，走 bash 执行（POSIX 路径）
        bash_cmd = ('scp -i ~/.ssh/server_deploy_key -o StrictHostKeyChecking=no '
                    '"%s" root@47.250.138.158:/opt/product-site/downloads/%s'
                    % (a.image.replace('\\', '/'), fn))
        subprocess.run(['bash', '-c', bash_cmd], check=True)
        url = 'https://www.huahuayoueryuan.com/downloads/' + fn
        print('首帧已传:', url)
        media = [{'type': 'first_frame', 'url': url}]
    tid = submit(a.prompt, a.duration, a.resolution, media)
    if not tid:
        sys.exit(1)
    res = poll(tid)
    if res and res.get('output', {}).get('task_status') in ('SUCCEEDED', 'Succeeded'):
        download(res, '%s.mp4' % tid[:8])
    else:
        print('任务未成功，见上方输出')
