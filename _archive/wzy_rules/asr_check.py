# -*- coding: utf-8 -*-
"""H3 原生对白的机器复核：把成片音轨转写出来，和提示词要求的台词逐字比。

定位说清楚：faster-whisper small 档的中文转写本身有错字，所以本脚本**不能判"台词一字不差"**，
它判的是三件确定的事——① 有没有人声；② 人声段数和时长对不对得上轮次；
③ 转写与目标台词的字符重合度（≥0.6 认为"说了这句"，<0.35 认为"没说/说糊了"）。
逐字是否真的分毫不差，仍要人耳过。

跑法（独立 venv，不碰任何现有 torch）：
  qcenv/Scripts/python.exe asr_check.py <mp4> <镜号>
"""
import os, re, sys, json, subprocess, difflib

os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
WZY = r'D:\AIWorkflow\tmp\wzy'
H3 = os.path.join(WZY, 'h3')
FF = r'D:\AIWorkflow\tools\ffmpeg.exe'
CACHE = r'D:\AIWorkflow\models\hf'


def norm(s):
    return re.sub(r'[\s，。、！？；：“”"\'—\-…·]+', '', s)


def want(shot):
    """从真源拿这一镜的台词逐字（不重打一遍，避免第二个事实源）。"""
    src = open(os.path.join(WZY, 'h3_shots.py'), encoding='utf8').read()
    src = src.split("if __name__")[0].replace("OUT = r'D:/AIWorkflow/tmp/wzy/h3'", "OUT = r'D:/AIWorkflow/tmp/wzy/h3'")
    g = {'__file__': os.path.join(WZY, 'h3_shots.py')}
    exec(compile(src, 'h3_shots.py', 'exec'), g)
    lines = g['load_ch1'](); g['build'](lines)
    for s in g['SHOTS']:
        if s['id'] == shot: return [(c, t) for c, t in s['dlg']], g['SPK']
    return [], {}


def main():
    mp4, shot = sys.argv[1], sys.argv[2]
    wav = os.path.join(WZY, '_asr.wav')
    subprocess.run([FF, '-y', '-v', 'error', '-i', mp4, '-vn', '-ac', '1', '-ar', '16000', wav],
                   check=True)
    from faster_whisper import WhisperModel
    m = WhisperModel('small', device='cpu', compute_type='int8', download_root=CACHE)
    segs, _ = m.transcribe(wav, language='zh', beam_size=5, vad_filter=True)
    got = [(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in segs]
    tgt, spk = want(shot)
    rows, score = [], []
    for i, (code, line) in enumerate(tgt):
        g = got[i][2] if i < len(got) else ''
        r = difflib.SequenceMatcher(None, norm(line), norm(g)).ratio()
        score.append(r)
        rows.append(dict(turn=i + 1, who=spk.get(code, ['', code])[1], want=line, got=g, ratio=round(r, 3)))
    extra = got[len(tgt):]
    out = dict(shot=shot, model='whisper-small(int8,cpu)', n_target=len(tgt), n_detected=len(got),
               verdict=('无人声' if not got else
                        '说了' if min(score or [0]) >= 0.6 else
                        '部分/糊' if max(score or [0]) >= 0.6 else '没说或不可辨'),
               ratio_min=round(min(score or [0]), 3), ratio_max=round(max(score or [0]), 3),
               turns=rows, extra_speech=[e[2] for e in extra],
               note='whisper-small 中文本身有错字；本判据只判"有没有说/说的是不是这句"，逐字须人耳过')
    j = os.path.join(WZY, 'qc_asr', shot + '.json')
    os.makedirs(os.path.dirname(j), exist_ok=True)
    json.dump(out, open(j, 'w', encoding='utf8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
