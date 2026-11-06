# -*- coding: utf-8 -*-
"""手册自写文档的 Markdown 表格完整性自检（只读，不改任何文件）。

用法：  py -3 99_维护\\check_tables.py
退出码： 0＝全部表格列数自洽；1＝有行与所在表的表头列数不一致。

为什么要这个：本手册里 20_/30_/00_ 三处文档是人写的，表格单元里出现过
`|`（正则、命令行管道）就会把一列劈成两列——渲染时表现为整表错位，
而这类缺陷**肉眼读 markdown 源码看不出来**。
规则：只数**未转义**的 `|`（`\\|` 是 markdown 表格里的合法转义，不算分隔符）。
"""
import io
import os
import re
import sys

ROOT = r"E:\本地工作流规范手册"

# 只查自写文档；01–10 是真源副本，格式不归本手册管
TARGETS = [
    r"00_读我\读我_总览与导航.md",
    r"00_读我\硬参数速查表.md",
    r"00_读我\版本裁定与冲突表.md",
    r"00_读我\重构方案_两层分离_待审.md",
    r"20_通用规范层\20_索引与分类判据.md",
    r"20_通用规范层\G2_提示词结构与接口契约.md",
    r"20_通用规范层\G4_一致性与锚点方法.md",
    r"20_通用规范层\G_作用域与例外登记表.md",
    r"30_项目层\30_项目索引.md",
    r"30_项目层\P_武昭君仪\规则.md",
    r"30_项目层\P_武昭君仪\真源指针.md",
]

SEP = r"(?<![\\])\|"          # 未转义的竖线


def cells(line):
    return len(re.findall(SEP, line)) - 1


def check(path):
    text = io.open(path, encoding="utf-8").read()
    lines = text.split("\n")
    problems, blocks = [], 0
    i = 0
    while i < len(lines):
        if lines[i].startswith("|"):
            hdr = cells(lines[i])
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                if cells(lines[j]) != hdr:
                    problems.append((j + 1, cells(lines[j]), hdr, lines[j][:46]))
                j += 1
            blocks += 1
            i = j
        else:
            i += 1
    return blocks, problems


def main():
    bad_total = 0
    for rel in TARGETS:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            print("!! 缺文件 %s" % rel)
            bad_total += 1
            continue
        blocks, probs = check(p)
        if probs:
            bad_total += len(probs)
            print("BAD  %s（%d 个表，%d 行错位）" % (rel, blocks, len(probs)))
            for ln, got, want, frag in probs[:8]:
                print("       行 %-5d 列数=%d 应为=%d | %s" % (ln, got, want, frag))
            if len(probs) > 8:
                print("       … 其余 %d 行省略" % (len(probs) - 8))
        else:
            print("OK   %s（%d 个表）" % (rel, blocks))
    print("-" * 56)
    if bad_total:
        print("共 %d 处需要修（单元里的裸 `|` 改成 `\\|`，或换分隔符）" % bad_total)
        return 1
    print("全部表格列数自洽")
    return 0


if __name__ == "__main__":
    sys.exit(main())
