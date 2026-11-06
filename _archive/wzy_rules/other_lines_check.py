# -*- coding: utf-8 -*-
"""另两条产物线（WorkBuddy 的三阶打斗 12 镜 ＋ 万相 3.0 第一章 23 镜稿）过同一批闸的结果。

为什么要这个：第一章这条线有四道闸（词表闸/法条闸/结构闸 G7/枪硬闸）＋台词逐字纪律，
另两条线的提示词是**另一个工具写的、一份都没过过闸**。归属没定之前，先把差距量出来。
只读、只报，不改它们任何一份提示词，也不生成任何东西。
"""
import json
import os
import re
import sys

D = r'D:/AIWorkflow/tmp/wzy'
# 09-28 真源搬家：三阶 12 镜现在在 prompts_H3官方骨架/（文件名去掉了镜名后缀），
# 旧目录 prompts/ 留着的是拆分前的十块稿与 ref2va 试验稿——两种命名都扫，别漏。
PR = r'D:/AIWorkflow/ComfyUI_H3/prompts'
PR_SKEL = r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架'
SRC = os.path.join(D, 'c12_source.txt')          # 第一章正文（台词唯一真源）
DLG = re.compile(r'<d>(.*?)</d>', re.S)                       # 官方对白标签（[中文] 前缀另剥）
DLG2 = re.compile(r'["“]([^"”“]{2,40})["”]')     # 十块/万相：说:"…" 引号式

sys.path.insert(0, D)
import prompt_lint as L                            # noqa: E402
import prompt_rules as R                           # noqa: E402
import prompt_format as PF                         # noqa: E402  认格式/切区的共用底座

# 第一章立的字面纪律（另两条线要不要一起受约束＝归属问题的一部分）
LITERAL_BAN = ['枪', '金属', '刃', '矛头', '云肩', '披膊', 'BJD', '人偶']
TEXT = open(SRC, encoding='utf8').read()


def fmt_of(t, want='h3'):
    """G7 那一列的现代表述。旧写法是 `'PASS' if 'integrated...' in t else '非官方骨架（中文十块）'`
       ——那是**二值**判断：六段格式、无格式图片稿都会被叫成"中文十块"，而 09-28 之后
       真正的缺陷叫**混用**（该通道的格式对不对），不是"是不是骨架"。
       want 必须按线给：三阶＝本地 H3，万相＝云端 SD ——拿 H3 尺子量万相的十块稿，
       23 份全会被误报成混用（同一次会话里 G7 就踩过这个对称的错误）。"""
    kind = PF.detect(t)
    mix = PF.mixing(t, want=want)
    lab = {'h3_skeleton': 'H3 官方骨架', 'h3_ref2va': 'H3 六段',
           'sd_tenblock': '中文十块（云端 SD 通道格式）',
           'plain': '无格式（图片/纯文本稿）'}[kind]
    return lab + ('｜✗ 混用：%s' % '；'.join(mix) if mix else '')


def verbatim(q):
    """台词是否逐字存在于正文（去掉标点空格后做子串判定）。"""
    k = re.sub(r'[^\w]', '', q)
    return k in re.sub(r'[^\w]', '', TEXT)


def report(tag, files, want='h3'):
    print('\n' + '=' * 72)
    print('【%s】%d 份' % (tag, len(files)))
    if not files:
        print('  ✗ 一份都没取到 ⇒ 不判"全部合规"。先确认目录/命名是否又搬过家')
        return []
    rows = []
    for f in files:
        t = open(f, encoding='utf8').read()
        dl = [re.sub(r'^\[中文\]\s*', '', d).strip() for d in DLG.findall(t)]
        if not dl and PF.detect(t) == 'sd_tenblock':
            # 只对**十块稿**退到引号式台词，且只认「」：H3 骨架/六段的台词一律认 <d> 标签，
            # 拿通用引号当台词会把拟声词（"轰"的一声…）切成一句假台词（本次实测踩到）。
            dl = [d.strip() for d in re.findall(u'「([^」]{2,40})」', t)]
        miss = [q for q in dl if not verbatim(q)]
        vis, _ = R.split_dialogue(t)               # 字面纪律查画面区，台词区另计
        hits = sorted({w for w in LITERAL_BAN if w in vis})
        dhits = sorted({w for w in LITERAL_BAN if w in t and w not in hits})
        r = L.scan_text(PF.visual_zone(t))
        law = R.scan_rules(t)
        rows.append((os.path.basename(f), len(dl), len(miss), len(hits), r['n_pos'],
                     sum(len(u) for _r, u, _l in law), fmt_of(t, want), hits[:4], miss[:2], dhits))
    print('%-30s %3s %4s %4s %5s %4s  %s' % ('文件', '台词', '非原文', '违字面', '肯定点名', '法条', '格式/混用'))
    for b, nd, nm, nh, npos, nlaw, g7, hits, miss, dhits in rows:
        print('%-30s %3d %4d %4d %5d %4d  %s%s' % (b[:29], nd, nm, nh, npos, nlaw, g7[:60],
              ('   字面:' + '、'.join(hits)) if nh else ''))
        if dhits:
            print('%33s（台词区另有 %s：按 WZJY-W1 不拦）' % ('', '、'.join(dhits)))
        if miss:
            print('%33s⚠ 台词正文查无：%s' % ('', ' / '.join('「%s」' % m[:18] for m in miss)))
    tot_d = sum(x[2] for x in rows)
    print('小结：台词非原文 %d 条／画面区字面违规命中 %d 处／格式混用 %d 份' % (
        tot_d, sum(x[3] for x in rows), sum('✗ 混用' in x[6] for x in rows)))
    return rows


if __name__ == '__main__':
    skel = [os.path.join(PR_SKEL, f) for f in sorted(os.listdir(PR_SKEL))
            if f.startswith('wuzhaojunyi_三阶')]
    old = [os.path.join(PR, f) for f in sorted(os.listdir(PR))
           if f.startswith('wuzhaojunyi_三阶')]
    report('三阶打斗 12 镜（H3 官方骨架真源，WorkBuddy 写的提示词）', skel)
    if old:
        report('三阶旧落点 prompts/ 里残留的同名稿', old)
    w = json.load(open(os.path.join(D, 'wan_ch1_prompts.json'), encoding='utf8'))
    tmp = os.path.join(D, 'tmp_wan')
    os.makedirs(tmp, exist_ok=True)
    for s in w:
        open(os.path.join(tmp, '%s_wan.txt' % s['id']), 'w', encoding='utf8').write(s['prompt'])
    files = sorted(os.path.join(tmp, f) for f in os.listdir(tmp))
    report('万相 3.0 第一章 23 镜提示词稿（其中 10 镜已出片 480P）', files, want='cloud')
    print('\n注：本报告不判废、不拦截——它只回答一个问题：另两条线相对第一章纪律，缺了哪几道检查。')
