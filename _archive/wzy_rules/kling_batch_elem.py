# -*- coding: utf-8 -*-
"""可灵 Element 绑定批量出 12 镜首帧（枪/君仪/混混三主体锁死跨图一致）。"""
import json, subprocess, time, sys
from pathlib import Path

REF_DIR = Path(r'E:/创作/武昭君仪/首帧图/可灵参考素材')
OUT = Path(r'E:/创作/武昭君仪/首帧图/可灵机位图')
OUT.mkdir(parents=True, exist_ok=True)
KLING = r'C:/Users/若水/.workbuddy-ai/binaries/node/versions/22.22.2-3/kling'
SC03 = str(REF_DIR / 'sc03.png')

JY, HH, QIANG = '322411437247859', '322411445254511', '322411431250654'
ELEM = ('[{"id":"%s","bindName":"武君仪"},{"id":"%s","bindName":"混混"},'
        '{"id":"%s","bindName":"长枪"}]' % (JY, HH, QIANG))

TAIL = '16:9电影构图，高精度CG半写实，古风武侠与赛博朋克并置，湿地面反射霓虹光，浅景深。'

SHOTS = {
 'P1A': '霓虹巷道中两人面对面站定对峙，全景、正面机位——<<<%(hh)s>>>在画面右侧、<<<%(jy)s>>>在画面左侧，两人全身入画、相距两米、目光相接；<<<%(q)s>>>竖直背在<<<%(jy)s>>>背后、枪头朝上、位置端正。',
 'P1B': '霓虹巷道中两人对峙，中景、机位偏向男子一侧——<<<%(hh)s>>>在画面右侧、赤手空拳、抬手指着<<<%(jy)s>>>叫嚣，<<<%(jy)s>>>在画面左侧站定；<<<%(q)s>>>竖直背在<<<%(jy)s>>>背后、枪头朝上、位置端正。',
 'P1C': '霓虹巷道中两人对峙，近景、两人半身入画——<<<%(hh)s>>>在画面右侧举右拳起势、面目凶狠，<<<%(jy)s>>>在画面左侧抬左臂格挡起势、神色冷静；<<<%(q)s>>>背在<<<%(jy)s>>>背后。',
 'P1D': '霓虹巷道中两人对峙，机位在<<<%(jy)s>>>左侧后方——<<<%(jy)s>>>在画面左前、侧身而立，<<<%(hh)s>>>在画面右后压身逼近；<<<%(q)s>>>竖直背在<<<%(jy)s>>>背后、位置端正。',
 'P2A': '霓虹巷道中两人对峙，<<<%(jy)s>>>半身近景在画面左侧——她神色一凛、右手反伸向背后握住背上的<<<%(q)s>>>（枪仍裹着白布），<<<%(hh)s>>>在画面右侧狞笑、抬起右臂机械义体、关节泛着蓝白电光。',
 'P2B': '霓虹巷道中两人交手，中景、机位偏向男子一侧——<<<%(jy)s>>>在画面左侧双手横持<<<%(q)s>>>（枪杆通体白麻布裹严、两端打结封口），<<<%(hh)s>>>在画面右侧、右臂机械义体高抬要砸下。',
 'P2C': '霓虹巷道中两人错开站位，全景——<<<%(jy)s>>>在画面左侧单手持<<<%(q)s>>>、枪尖斜指地面，<<<%(hh)s>>>在画面右前压低身体、机械臂横在胸前。',
 'P2D': '霓虹巷道中两人角力，近景——<<<%(hh)s>>>右臂机械义体电光暴涨、蓝白电弧四溢、高高扬起，<<<%(jy)s>>>在画面左侧横持<<<%(q)s>>>架住这一击、枪杆上的白麻布条已被震得松散开、布头垂下。',
}

BASH = r'C:\Users\若水\.workbuddy-ai\binaries\PortableGit\versions\1.2.0\bin\bash.exe'
KLING_POSIX = '/c/Users/若水/.workbuddy-ai/binaries/node/versions/22.22.2-3/kling'

def run(cmd, timeout=180):
    """经 PortableGit bash 执行：参数值一律加引号（elements 单引号、其余双引号），防路径/<<<被解析。"""
    parts = []
    i = 0
    while i < len(cmd):
        a = str(cmd[i])
        if a.startswith('--') and i + 1 < len(cmd) and not str(cmd[i + 1]).startswith('--'):
            val = str(cmd[i + 1])
            if a == '--elements':
                parts.append(a + " '" + val + "'")
            else:
                parts.append(a + ' "' + val + '"')
            i += 2
        elif not a.startswith('--'):
            parts.append('"' + a.replace('"', '') + '"')
            i += 1
        else:
            parts.append(a)
            i += 1
    bash_cmd = KLING_POSIX + ' ' + ' '.join(parts)
    return subprocess.run([BASH, '-c', bash_cmd], capture_output=True, text=True,
                          encoding='utf8', errors='replace', timeout=timeout)

def submit(shot, scene):
    import re
    prompt = ('图片1是场景（霓虹巷道）。' + (scene % {'jy': JY, 'hh': HH, 'q': QIANG}) + TAIL)
    cmd = ['image_to_image', '--skill-name', 'kling-cli', '--skill-version', '0.2.0',
           '--model', 'kling-image-v3_0', '--aspectRatio', '16:9', '--imageCount', '1',
           '--elements', ELEM, '--image', SC03, prompt]
    r = run(cmd)
    m = re.search(r'"generation_id"\s*:\s*"([^"]+)"', r.stdout + r.stderr)
    if not m:
        print('[%s] 提交失败:' % shot, (r.stdout + r.stderr)[-300:], flush=True)
        return None
    print('[%s] 已提交 %s' % (shot, m.group(1)), flush=True)
    return m.group(1)

def poll_dl(gid, shot):
    for _ in range(30):
        time.sleep(20)
        r = run(['query_tasks', '--skill-name', 'kling-cli', '--skill-version', '0.2.0', gid])
        try:
            j = json.loads(r.stdout)
            b = j.get('body', {})
            if b.get('status') in ('COMPLETED', 'succeed'):
                ws = b.get('works', [])
                if ws:
                    u = ws[0].get('url') or ws[0].get('urlWithoutWatermark')
                    subprocess.run(['curl', '-sL', '-A', 'Mozilla/5.0', '-o',
                                    str(OUT / ('%s_首帧.png' % shot)), u], check=True)
                    print('[%s] 已下载（Element版）' % shot, flush=True)
                    return True
                return False
            if b.get('status') in ('FAILED', 'CANCELLED'):
                print('[%s] 任务失败' % shot, flush=True)
                return False
        except Exception as e:
            print('[%s] 轮询异常 %s' % (shot, e), flush=True)
    return False

if __name__ == '__main__':
    only = sys.argv[1:] or list(SHOTS)
    for shot in only:
        if shot not in SHOTS:
            continue
        gid = submit(shot, SHOTS[shot])
        if gid:
            poll_dl(gid, shot)
