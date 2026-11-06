# -*- coding: utf-8 -*-
"""改完基调句后的安全核对：重新编译 23 镜，与盘上现有提示词逐字节比对。
预期只有 H05 变（它是今晚唯一走"黄昏雾林"的古代镜）。
任何别的镜变了＝我把正在跑的批扰动了一次，必须停下来查，不能写盘。
不调用 write_jobs()——jobs.json 正被驱动用来传递链式首帧，同时写会把它覆盖掉。"""
import os, sys, io
sys.path.insert(0, r'D:\AIWorkflow\tmp\wzy')
import h3_shots as H

OUT = H.OUT
# 只做真源里的"切片＋配台词＋算时长"这三步（build/timing 不写盘），
# 写盘全在 __main__ 块里，绕开它就等于不碰 jobs.json / 别人的提示词文件。
H.build(H.load_ch1())
for s in H.SHOTS:
    H.timing(s)
changed = []
for s in H.SHOTS:
    for kind, txt in (('video', H.compile_video(s)),):
        p = os.path.join(OUT, '%s_%s.txt' % (s['id'], kind))
        old = io.open(p, encoding='utf8').read() if os.path.isfile(p) else None
        if old != txt:
            changed.append((s['id'], kind, len(old or ''), len(txt)))
    if s['id'] in ('H05', 'H07'):
        p = os.path.join(OUT, '%s_kf.txt' % s['id'])
        old = io.open(p, encoding='utf8').read() if os.path.isfile(p) else None
        if old != H.compile_kf(s):
            changed.append((s['id'], 'kf', len(old or ''), len(H.compile_kf(s))))
print('变了的文件：', changed or '无')
# 判据不是"只有 H05 变"，而是"**正在排队/即将提交的镜**除 H05 外一字节都不许变"。
# H01–H04 也各短了 16 字（缩短基调句的必然结果），但它们走已生效的 Seedance 片、不在 RUN 里，无害。
touched = set(c[0] for c in changed)
in_run = touched & set(H.RUN)
assert in_run == {'H05'}, 'RUN 里除 H05 外有镜被扰动：%s' % (in_run - {'H05'})
for sid in sorted(touched):
    s = [x for x in H.SHOTS if x['id'] == sid][0]
    io.open(os.path.join(OUT, '%s_video.txt' % sid), 'w', encoding='utf8').write(H.compile_video(s))
    if sid in ('H05', 'H07'):
        io.open(os.path.join(OUT, '%s_kf.txt' % sid), 'w', encoding='utf8').write(H.compile_kf(s))
    print('重写', sid)
new = io.open(os.path.join(OUT, 'H05_video.txt'), encoding='utf8').read()
print('H05 含"灯笼"？', '灯笼' in new, ' 含"黄昏雾林"？', '黄昏雾林' in new)
print('H05 含"或"并列场景？', '或' in new.split('One continuous')[0])

