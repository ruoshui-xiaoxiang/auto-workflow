# -*- coding: utf-8 -*-
"""万相批量跑第一章（首帧模式）：有首帧的镜并行提交，轮询下载。
用法: python wan_batch_ch1.py          # 全部有首帧的镜
      python wan_batch_ch1.py H01 H02  # 指定镜
断点：已有产物跳过；任务ID记录在 wan_ch1_tasks.json。
"""
import json, subprocess, time, sys, os
from pathlib import Path
import requests

WZY = Path(r'D:/AIWorkflow/tmp/wzy')
OUT = WZY / 'wan_ch1_out'
OUT.mkdir(parents=True, exist_ok=True)
TASKS = WZY / 'wan_ch1_tasks.json'
SERVER = 'root@47.250.138.158:/opt/product-site/downloads/'
URLBASE = 'https://www.huahuayoueryuan.com/downloads/'

_key = Path(r'E:/密钥文件/阿里多模态.txt').read_text(encoding='utf8').strip().splitlines()[0]
HDR = {'Authorization': 'Bearer ' + _key, 'Content-Type': 'application/json',
       'X-DashScope-Async': 'enable'}
SUB = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis'


def upload(path):
    fn = 'wanch1_' + path.name
    subprocess.run(['bash', '-c',
                    'scp -i ~/.ssh/server_deploy_key -o StrictHostKeyChecking=no "%s" %s%s'
                    % (str(path).replace('\\', '/'), SERVER, fn)], check=True)
    return URLBASE + fn


def submit(shot, prompt, ff):
    url = upload(ff)
    body = {'model': 'wan3.0-video',
            'input': {'prompt': prompt,
                      'media': [{'type': 'first_frame', 'url': url}]},
            'parameters': {'resolution': '480P', 'ratio': 'adaptive',
                           'duration': int(round(shot['secs'])), 'prompt_extend': False}}
    r = requests.post(SUB, headers=HDR, json=body, timeout=60)
    j = r.json()
    if r.status_code != 200 or 'task_id' not in j.get('output', {}):
        print('[%s] 提交失败 %s %s' % (shot['id'], r.status_code,
              json.dumps(j, ensure_ascii=False)[:200]), flush=True)
        return None
    print('[%s] 已提交 %s (%ds 480P)' % (shot['id'], j['output']['task_id'], shot['secs']), flush=True)
    return j['output']['task_id']


def poll(tid, name, timeout=1200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get('https://dashscope.aliyuncs.com/api/v1/tasks/' + tid, headers=HDR, timeout=30)
        st = r.json().get('output', {}).get('task_status', '')
        if st == 'SUCCEEDED':
            u = r.json()['output'].get('video_url')
            if u:
                dst = OUT / ('%s_wan_480p.mp4' % name)
                subprocess.run(['curl', '-sL', '-A', 'Mozilla/5.0', '-o', str(dst), u], check=True)
                print('[%s] 完成并下载 %s' % (name, dst.name), flush=True)
                return True
        if st in ('FAILED', 'CANCELED'):
            print('[%s] 任务失败' % name, flush=True)
            return False
        time.sleep(20)
    print('[%s] 轮询超时' % name, flush=True)
    return False


if __name__ == '__main__':
    data = json.load(open(WZY / 'wan_ch1_prompts.json', encoding='utf8'))
    only = set(sys.argv[1:])
    tasks = json.load(open(TASKS, encoding='utf8')) if TASKS.is_file() else {}
    pending = []
    for s in data:
        if only and s['id'] not in only:
            continue
        dst = OUT / ('%s_wan_480p.mp4' % s['id'])
        if dst.is_file() and dst.stat().st_size > 100000:
            print('[%s] 已有产物跳过' % s['id'], flush=True)
            continue
        if not s['has_ff']:
            print('[%s] 缺首帧跳过' % s['id'], flush=True)
            continue
        if s['id'] in tasks:
            tid = tasks[s['id']]
            print('[%s] 复用任务ID %s 轮询' % (s['id'], tid), flush=True)
            if poll(tid, s['id']):
                continue
        tid = submit(s, s['prompt'], Path(s['first_frame']))
        if tid:
            tasks[s['id']] = tid
            json.dump(tasks, open(TASKS, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
            pending.append((tid, s['id']))
    for tid, name in pending:
        poll(tid, name)
    print('本轮结束。已完成:', [f.name for f in OUT.glob('*.mp4')])
