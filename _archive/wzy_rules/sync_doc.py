# -*- coding: utf-8 -*-
"""把 h3 真源的产物整份回写进他在审的桌面文档「一·七」节（幂等，可反复跑）。

规则来源：脚本一改就要整份回写进桌面文档，别只改代码。
边界：从 '## 一·七' 到 '## 二、全片视觉基线' 之间整段替换；两头的正文一个字不碰。
"""
import os, re, sys

WZY = r'D:\AIWorkflow\tmp\wzy'
DOC = r'E:\创作\武昭君仪\武昭君仪_剧本与资产盘点_v1.md'
A = '## 一·七'
B = '## 二、全片视觉基线'

def build():
    sec = open(os.path.join(WZY, 'h3', '一·七_H3适配.md'), encoding='utf8').read().rstrip()
    tab = open(os.path.join(WZY, 'h3', 'H3分镜与提示词.md'), encoding='utf8').read()
    tab = tab[:tab.index('## 逐镜提示词全文')]
    tab = tab.replace('# 第一章 · H3 适配分镜表与提示词（真源 h3_shots.py 生成，勿手改）',
                      '### 分镜总表与逐镜内容（真源 h3_shots.py 生成，勿手改）')
    tab = tab.replace('## 逐镜内容', '### 逐镜内容')
    tab = re.sub(r'^### (H\d\d)', r'#### \1', tab, flags=re.M)
    dz = open(os.path.join(WZY, 'h3', '定妆词.md'), encoding='utf8').read()
    dz = dz.replace('# 《武昭君仪》定妆词（按 V3 总表 index (1).md 写）',
                    '### 定妆词全文（h3/定妆词.md）')
    dz = dz.replace('\n## ', '\n#### ')
    tail = ('> 逐镜提示词全文（官方 I2VA 骨架，23 份）见 `D:\\AIWorkflow\\tmp\\wzy\\h3\\'
            'H3分镜与提示词.md` 末节，以及单镜文件 `h3\\Hxx_video.txt`；'
            '跑批日志 `h3\\run.log`。\n')
    return '\n\n'.join([sec, dz.rstrip(), tab.rstrip(), tail]) + '\n\n'

def main():
    blk = build()
    d = open(DOC, encoding='utf8').read()
    if A not in d or B not in d:
        print('桌面文档里找不到节边界，拒绝改写', file=sys.stderr); return 1
    a, b = d.index(A), d.index(B)
    new = d[:a] + blk + d[b:]
    open(DOC, 'w', encoding='utf8').write(new)
    print('一·七 已整份回写：%d 字（文档 %d → %d 字）' % (len(blk), len(d), len(new)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
