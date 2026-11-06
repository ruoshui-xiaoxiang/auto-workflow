# -*- coding: utf-8 -*-
"""十块 → H3 官方骨架（I2VA 三段式）转换器。

依据 2026-09-28 的 A/B 实测（`wzy/ab_tenblock.py`）：十块写法 4/5 条出现乱码、
官方骨架写法 0/5 干净 ⇒ 十块移出 H3，H3 视频提示词统一为官方骨架。

转换规则：
- 加官方首行对齐指令 + 恰三字段；正文以 [Shot 1] 开头
- 丢掉【生成目标】的叙事复述（保留"横屏/秒数/一镜到底"这类参数信息，并入首句）
- 丢掉【参考素材职责】【未采用素材】（云端出图专用，H3 视频层不适用）
- 【主体与关系】+【外貌锁定】+【场景与环境】+【事件脚本】+【镜头】+【Motion】+【保持一致】
  合并为一段连续散文（去掉【】标签与 ** 加粗标记）
- 【保持一致】里删掉"元叙述句"（"他只说上面写出的那一句台词""其余时间没有任何说话声"
  ——实测会被 H3 当台词念出来）
- 【声音】→ overall_soundscape；non_diegetic_music: N/A

用法：python to_official.py            # 转全部 12 份
      python to_official.py P1B        # 只转一份并打印
"""
import io
import re
import sys
from pathlib import Path

SRC = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts')
DST = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架')
ORDER = ['P1A', 'P1B', 'P1C', 'P1D', 'P2A', 'P2B', 'P2C', 'P2D',
         'P3A', 'P3B', 'P3C', 'P3D']
INSTRUCTION = ("For the target video, at 0.00 seconds into the target video, "
               "<Picture 1> (from [Shot 1]) is fully referenced.")

# 实测会被念出来的元叙述句（整句删除）
META_PAT = re.compile(
    r'\*{0,2}(?:他|她|两人|二人)?[^。*]{0,20}只说上面写出的那[一句个]字[^。*]{0,60}'
    r'|(?:他|她|两人|二人)全程不出声、不张嘴[^。*]{0,40}'
    r'|(?:两人|二人)全程不出声、不张嘴、没有任何说话声'
    r'|其余时间(?:全程)?(?:没有任何说话声|不出声)'
)


def split_blocks(txt):
    parts = re.split(r'【([^】]+)】', txt)
    out = {}
    for i in range(1, len(parts) - 1, 2):
        out[parts[i].strip()] = parts[i + 1].strip()
    return out


def clean(t):
    t = t.replace('**', '')
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def keep_safe(keep):
    """【保持一致】里只保留"身份/服装/道具/画面"锁句；
    含 台词/说话声/不出声/不张嘴/说话人 的句子一律丢掉
    ——实测这些元叙述句会被 H3 当台词念出来（A/B：十块 4/5 乱码，官方骨架 0/5）。"""
    BAD = ('台词', '说话声', '不出声', '不张嘴', '说话人', '没有任何说')
    sents = re.split(r'(?<=[。；;])', keep)
    out = [s.strip() for s in sents if s.strip() and not any(w in s for w in BAD)]
    t = ''.join(out).strip(' ；;，、')
    t = re.sub(r'[；;]\s*。', '。', t)
    t = re.sub(r'。\s*。', '。', t)
    return t


def convert(sid):
    f = list(SRC.glob('wuzhaojunyi_三阶%s_*.txt' % sid))
    assert len(f) == 1, (sid, f)
    b = split_blocks(io.open(f[0], encoding='utf8').read())
    need = ['主体与关系', '场景与环境', '事件脚本', '保持一致', '镜头', '声音']
    miss = [k for k in need if k not in b]
    assert not miss, (sid, '缺块', miss)

    goal = clean(b.get('生成目标', ''))
    m = re.search(r'横屏\s*16:9\s*单镜[，,]?\s*([\d.]+)\s*秒[，,]?\s*一镜到底', goal)
    param = '横屏 16:9 单镜，%s 秒，一镜到底' % (m.group(1) if m else '5.17')

    style = clean(b.get('风格与光影', ''))
    scene = clean(b['场景与环境'])
    subject = clean(b['主体与关系'])
    appear = clean(b.get('外貌锁定', ''))
    events = clean(b['事件脚本'])
    camera = clean(b['镜头'])
    motion = clean(b.get('Motion', ''))
    keep = keep_safe(clean(b['保持一致']))
    sound = clean(b['声音'])
    for bad in ('那句台词之外，全场安静。', '两句台词之外，全场安静。',
                '那一个字之外，全场安静。', '那句台词之外，全场安静；'):
        sound = sound.replace(bad, '其余时间全场安静。')
    sound = sound.replace('那句台词之外', '其余时间').replace('那一个字之外', '其余时间')

    desc = '[Shot 1] %s %s——%s %s %s %s %s' % (
        style, param, scene, subject, appear, events, camera)
    if motion:
        desc += ' ' + motion
    if keep:
        desc += ' Throughout: ' + keep
    desc = re.sub(r'\s{2,}', ' ', desc).strip()

    return (INSTRUCTION + '\n\n'
            'integrated_multimodal_description:\n' + desc + '\n'
            'overall_soundscape:\n' + sound + '\n'
            'non_diegetic_music:\nN/A\n')


def main():
    only = [a for a in sys.argv[1:] if not a.startswith('-')]
    DST.mkdir(parents=True, exist_ok=True)
    for sid in (only or ORDER):
        txt = convert(sid)
        p = DST / ('wuzhaojunyi_三阶%s.txt' % sid)
        p.write_text(txt, encoding='utf8')
        if only:
            print(txt)
        else:
            print('%s -> %s（%d 字，星号 %d，方括号 %d）' % (
                sid, p.name, len(txt), txt.count('*'), txt.count('【')))


if __name__ == '__main__':
    main()
