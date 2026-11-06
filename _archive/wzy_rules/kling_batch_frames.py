# -*- coding: utf-8 -*-
"""可灵批量出 12 镜机位首帧：每镜按 V5 定稿模板（8 参考图+正向写法+枪包法句）提交 image_to_image，
轮询下载到 首帧图/可灵机位图/。P1B 已有 V5 定稿跳过。"""
import json, subprocess, time, sys
from pathlib import Path

REF_DIR = Path(r'E:/创作/武昭君仪/首帧图/可灵参考素材')
OUT = Path(r'E:/创作/武昭君仪/首帧图/可灵机位图')
OUT.mkdir(parents=True, exist_ok=True)
IMG8 = r'E:/创作/武昭君仪/武昭君仪资产包/P01 沉铁长枪（白麻布裹严）.png'
KLING = r'C:/Users/若水/.workbuddy-ai/binaries/node/versions/22.22.2-3/kling'

REFS = ['jy_正面.png', 'jy_侧面.png', 'jy_背面.png', 'hh_正面.png', 'hh_侧面.png',
        'hh_背面.png', 'sc03.png', IMG8]

HEAD = ('图片1、图片2、图片3是同一个女子的三视图（深蓝藏青华丽长袍、宽袖、高盘发髻带银饰）。'
        '图片4、图片5、图片6是同一个粗壮男混混的三视图（灰色背心、右臂机械义体）。'
        '图片7是场景。图片8是一杆白麻布裹严的长枪。生成一张16:9电影构图画面：')
TAIL = ('高精度CG半写实，古风武侠与赛博朋克并置，湿地面反射霓虹光，浅景深。')

# 枪状态句（按镜）
def spear(state):
    if state == 'back':   # 背在背上裹严
        return ('女子背上竖直背着一杆与图片8相同的长枪——枪杆通体被同一层白麻布紧贴包住、'
                '从枪头一端到枪尾一端完全覆盖，两端收细打结、封口严实，看不到任何内部材质、'
                '没有松散开的布条，枪头朝上、位置端正。')
    if state == 'hand':   # 手持裹严
        return ('女子双手横持一杆与图片8相同的长枪，枪杆通体被白麻布裹严、两端打结封口。')
    if state == 'loose':  # 布条松散
        return ('女子横持长枪架住男子的机械臂，枪杆上的白麻布条松散开来、布头垂下，枪杆仍大部裹着布。')
    if state == 'unwrap': # 扯布中
        return ('女子单手擎枪，正扯下枪上的白麻布条、布条在空中飘落、一端已缠在她左腕上，'
                '露出的枪杆是暗色合金、枪头寒光。')
    if state == 'bare':   # 裸枪
        return ('女子手持裸枪——暗色合金枪杆、柔韧有弹性、枪头寒光，白麻布条缠在她的左腕上。')
    return ''

SHOTS = {
 'P1A': ('全景正面', 'back',
   '霓虹巷道中两人面对面站定对峙，全景、正面机位——男子在画面右侧、女子在画面左侧，两人全身入画、相距两米、目光相接。'),
 'P1C': ('近景对峙', 'back',
   '霓虹巷道中两人对峙，近景、两人半身入画——男子在画面右侧举右拳起势、面目凶狠，女子在画面左侧抬左臂格挡起势、神色冷静。'),
 'P1D': ('侧景偏君仪', 'back',
   '霓虹巷道中两人对峙，机位在女子左侧后方——女子在画面左前、侧身而立，男子在画面右后压身逼近，突出女子的侧身与背上的枪。'),
 'P2A': ('近景君仪', 'back',
   '霓虹巷道中两人对峙，女子半身近景在画面左侧——她神色一凛、右手反伸向背后握住背上枪杆（枪仍裹着白布），男子在画面右侧狞笑、抬起右臂机械义体、关节泛着蓝白电光。'),
 'P2B': ('中景混混侧', 'hand',
   '霓虹巷道中两人交手，中景、机位偏向男子一侧——女子在画面左侧双手横持裹白布长枪，男子在画面右侧、右臂机械义体高抬要砸下。'),
 'P2C': ('全景微偏', 'hand',
   '霓虹巷道中两人错开站位，全景——女子在画面左侧持裹白布长枪、枪尖斜指地面，男子在画面右前压低身体、机械臂横在胸前。'),
 'P2D': ('近景对峙', 'loose',
   '霓虹巷道中两人角力，近景——男子右臂机械义体电光暴涨、蓝白电弧四溢、高高扬起，女子在画面左侧横枪架住这一击、枪杆上的白麻布条已被震得松散开、布头垂下。'),
 'P3A': ('特写君仪', 'unwrap',
   '霓虹巷道中两人交手，女子近景在画面左侧——她单手擎枪、正扯下枪上的白麻布条、布条在空中飘落、一端已缠在她左腕上，露出的枪杆是暗色合金；男子在画面右侧、机械臂闪着过载电光。'),
 'P3B': ('中景对峙', 'bare',
   '霓虹巷道中两人对峙，中景——女子在画面左侧持裸枪而立（暗色合金枪杆、枪头寒光、白麻布条缠在左腕上），男子在画面右侧、背贴着巷墙、喘着粗气。'),
 'P3C': ('全景', 'bare',
   '霓虹巷道中两人对峙，全景——男子背贴巷墙、机械臂电光四溢、作垂死反扑状，女子在画面中横枪以待、枪头寒光。'),
 'P3D': ('远景收场', 'bare',
   '霓虹巷道中战斗收场，远景全景——男子瘫坐在墙根、机械臂无力垂着，女子持枪而立、枪尖指着他，画面开阔。'),
}

def run(cmd, timeout=180):
    # Windows 下 kling 是脚本包装，需经 shell 执行
    if isinstance(cmd, list):
        cmd = ' '.join('"%s"' % c if ' ' in str(c) else str(c) for c in cmd)
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf8',
                          errors='replace', timeout=timeout)

def submit(shot, cam, spear_state, scene):
    cmd = [KLING, 'image_to_image', '--skill-name', 'kling-cli', '--skill-version', '0.2.0',
           '--model', 'kling-image-v3_0', '--aspectRatio', '16:9', '--imageCount', '1']
    for r in REFS:
        p = Path(r)
        if not p.is_absolute():
            p = REF_DIR / p
        cmd += ['--image', str(p)]
    prompt = HEAD + scene + spear(spear_state) + TAIL
    cmd.append(prompt)
    r = run(cmd)
    import re
    m = re.search(r'"generation_id"\s*:\s*"([^"]+)"', r.stdout + r.stderr)
    if not m:
        print('[%s] 提交失败:' % shot, (r.stdout + r.stderr)[-300:], flush=True)
        return None
    print('[%s] 已提交 %s' % (shot, m.group(1)), flush=True)
    return m.group(1)

def poll_dl(gid, shot):
    for _ in range(30):
        time.sleep(20)
        r = run([KLING, 'query_tasks', '--skill-name', 'kling-cli', '--skill-version', '0.2.0', gid])
        try:
            j = json.loads(r.stdout)
            b = j.get('body', {})
            if b.get('status') in ('COMPLETED', 'succeed'):
                ws = b.get('works', [])
                if ws:
                    u = ws[0].get('url') or ws[0].get('urlWithoutWatermark')
                    subprocess.run(['curl', '-sL', '-A', 'Mozilla/5.0', '-o',
                                    str(OUT / ('%s_首帧.png' % shot)), u], check=True)
                    print('[%s] 已下载 %s_首帧.png' % (shot, shot), flush=True)
                    return True
                print('[%s] 完成但无 works' % shot, flush=True)
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
            print('未知镜号:', shot); continue
        dst = OUT / ('%s_首帧.png' % shot)
        if dst.is_file() and dst.stat().st_size > 100000:
            print('[%s] 已有，跳过' % shot, flush=True)
            continue
        cam, spear_state, scene = SHOTS[shot]
        gid = submit(shot, cam, spear_state, scene)
        if gid:
            poll_dl(gid, shot)
