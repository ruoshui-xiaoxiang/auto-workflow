# -*- coding: utf-8 -*-
r"""运镜词表对账（2026-10-03 批 10 立；用户裁「R2-05 对齐官方表」的防回归钉）。

为什么要有它：可写运镜的权威在官方模板 `prompts\official_h3\base-en.txt` §4.3，
但这句话在**四个文档**里各转写了一遍，历史上转写会漂（曾同时存在「14 类」「13 类」
与机器表 14 项三种说法，其实三个数都对、只是口径不同）。
本脚本每次现读官方原文，再逐行核对四处转写：**表里不抄值，比对靠现读**。

只报不拦（与 check_layers / check_registry 同一口径）：它查的是文档一致性，
不是产物质量，拦人之前要先有人裁。
"""
import io
import os
import re
import sys

OFFICIAL = r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\base-en.txt"
TARGETS = [
    (r"E:\本地工作流规范手册\20_通用规范层\R2_提示词结构与接口契约.md", "R2-05"),
    (r"D:\AIWorkflow\ComfyUI_H3\H3提示词工程规则方案.md", "方案 §五"),
    (r"D:\AIWorkflow\ComfyUI_H3\H3提示词规则_现行合并版.md", "现行合并版"),
    (r"E:\本地工作流规范手册\00_读我\硬参数速查表.md", "硬参数速查表"),
]
MACHINE_TABLE = r"D:\AIWorkflow\tmp\wzy\h3_rule_gate.py"


def official():
    if not os.path.isfile(OFFICIAL):
        return None, None, None, "官方模板不在：%s（换了机器就要重装权重仓的 skill）" % OFFICIAL
    s = io.open(OFFICIAL, encoding="utf-8", errors="replace").read()
    i = s.find("4.3 Camera Motion")
    if i < 0:
        return None, None, None, "官方 §4.3 找不到——**厂商改了运镜表，本层判据要重读官方**"
    seg = s[i:s.find("### 4.4", i)]
    rows = re.findall(r"^\|\s*(Motion type|Amplitude|Speed)\s*\|\s*([^|]+?)\s*\|", seg, re.M)
    mot = [v.strip() for k, v in rows if k == "Motion type"]
    amp = [v.strip() for k, v in rows if k == "Amplitude"]
    spd = [v.strip() for k, v in rows if k == "Speed"]
    return mot, amp, spd, None


def bare(v):
    return re.sub(r"[^A-Za-z]", "", v).lower()


def check_line(text, mot, amp, spd):
    """返回这一份转写缺了官方哪几行（按去符号后的字母比对，中英标点差异不算缺）。"""
    blob = bare(text)
    miss = [m for m in mot if bare(m) not in blob]
    return miss


def selftest(mot, amp, spd):
    """反向自证：植入坏转写必须被抓，正确转写不得误伤。"""
    good = "／".join("`%s`" % m for m in mot) + "／".join("`%s`" % a for a in amp + spd)
    assert not check_line(good, mot, amp, spd), "正向样本都被判缺 ⇒ 比对逻辑有误伤"
    one_short = good.replace(mot[3], "`Zoom In Only`")
    assert check_line(one_short, mot, amp, spd), "删掉一行运动类型没被抓 ⇒ 这把尺是摆设"
    no_amp = "／".join("`%s`" % m for m in mot)
    miss = [a for a in amp + spd if bare(a) not in bare(no_amp)]
    assert len(miss) == 4, "幅度／速度四档全丢了却没报：%s" % miss
    print("  selftest ✓ 缺 1 行 / 丢 4 档 都能抓到，正确样本不误伤")
    return 0

def main():
    if "--selftest" in sys.argv:
        mot, amp, spd, err = official()
        return selftest(mot, amp, spd) if not err else 1
    mot, amp, spd, err = official()
    print("=" * 72)
    print("check_cam_vocab.py · 运镜词表对账（只报不拦）")
    print("权威：%s" % OFFICIAL)
    print("=" * 72)
    if err:
        print("!! %s" % err)
        return 1
    print("官方 §4.3：运动类型 %d 行 ｜ 幅度 %d 档 ｜ 速度 %d 档" % (len(mot), len(amp), len(spd)))
    hard = 0
    for path, tag in TARGETS:
        if not os.path.isfile(path):
            print("  !! 文件不在：%s（%s）" % (path, tag))
            hard += 1
            continue
        s = io.open(path, encoding="utf-8", errors="replace").read()
        miss = check_line(s, mot, amp, spd)
        amp_miss = [a for a in amp + spd if bare(a) not in bare(s)]
        # 渲染自洽：词表行里出现 `` 是排版损伤（官方单元格自带反引号，转写时容易双包），
        # 只比字母的那道检查看不见它，所以单独查一遍——守卫的盲区也要自己堵。
        bad_fmt = [n for n, l in enumerate(s.split("\n"), 1)
                   if "``" in l and any(k in l for k in ("受控词表", "运镜", "运动类型", "幅度"))]
        if bad_fmt:
            print("  !!   %-14s 词表行有双反引号（渲染会坏）：第 %s 行"
                  % (tag, "、".join(str(n) for n in bad_fmt[:5])))
            hard += 1
        if not miss and not amp_miss:
            print("  OK   %-14s 12 行齐全、幅度与速度两档都在" % tag)
            continue
        hard += 1
        if miss:
            print("  !!   %-14s 缺官方运动类型行：%s" % (tag, "、".join(miss)))
        if amp_miss:
            print("  !!   %-14s 缺幅度／速度档位：%s" % (tag, "、".join(amp_miss)))
    # 机器表：它允许比官方宽（同义词），但不许比官方窄
    if os.path.isfile(MACHINE_TABLE):
        t = io.open(MACHINE_TABLE, encoding="utf-8", errors="replace").read()
        m = re.search(r"CAM_EN\s*=\s*\[(.*?)\]", t, re.S)
        if not m:
            print("  !! 机器表 CAM_EN 读不到（改名了？那这条对账就是空跑）")
            hard += 1
        else:
            items = re.findall(r"'([^']+)'", m.group(1))
            roots = set(bare(x) for x in items)
            narrow = [x for x in mot
                      if not any(r in bare(x) or bare(x) in r for r in roots)]
            print("  %s 机器表 CAM_EN %d 项%s" % (
                "OK  " if not narrow else "!!  ", len(items),
                "" if not narrow else "，比官方窄了：%s" % "、".join(narrow)))
            if narrow:
                hard += 1
    print("-" * 72)
    print("官方行数 %d ｜ 转写不符 %d 处 ｜ 本脚本只报不拦：退出码 0" % (len(mot), hard))
    return 0


if __name__ == "__main__":
    sys.exit(main())
