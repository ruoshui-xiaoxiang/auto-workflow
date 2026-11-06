# -*- coding: utf-8 -*-
"""把"已判废但还在真源目录里躺着"的提示词稿搬进素材池归档，**验过 sha256 才删源**。

为什么要有这个脚本（2026-09-28 的实际教训）：三阶 12 镜的中文十块旧稿在 09-28 迁成官方骨架后
**仍留在 `ComfyUI_H3/prompts/`**。留着不是无害的——任何按 `wuzhaojunyi_三阶{sid}_*.txt` 写的
glob 都还能命中它们，`detail_p_beats.py` 就是这样把 09-27 的旧文本重放进"已经比它更新"的稿子里的
（P1B 事件脚本 425 字被写成 341 字，手册冲突表风险 23）。
⇒ 判废的东西要**从真源目录里挪走**，而不是只在文档里写一句"以某某为准"。

规矩（沿用 `tools/pool_reorg.py` 的既有约定，不新发明）：
  · **保相对路径**落到 `池/<项目>/_判废归档_<日期>/<原相对路径>`，防同名互撞、也方便日后按原样还原；
  · 每次动文件写一份 `_归档_MANIFEST/<stamp>/MANIFEST.md`：源绝对路径、大小、mtime、sha256、
    判废原因、授权出处（哪句用户原话）；
  · **先复制 → 逐份 sha256 复核 → 全对才删源**；任一份对不上就留着不动（保守失败）；
  · 默认 `--dry-run`，要真删必须显式给 `--delete-after-verify`。

用法：
    python archive_superseded_prompts.py --dry-run
    python archive_superseded_prompts.py --delete-after-verify
"""
import argparse
import hashlib
import os
import shutil
import sys
import time

POOL = r'E:\图像影音资源池'
SRC_ROOT = r'D:/AIWorkflow/ComfyUI_H3'          # 相对路径的基准，还原时按原样落回
REL_DIR = 'prompts'                              # 只动这一个子目录里的这批文件
PROJ = '武昭君仪'
STAMP = '20260928'
FILES = ['wuzhaojunyi_三阶P1A_拦路.txt', 'wuzhaojunyi_三阶P1B_试探.txt',
         'wuzhaojunyi_三阶P1C_吃亏.txt', 'wuzhaojunyi_三阶P1D_力不敌.txt',
         'wuzhaojunyi_三阶P2A_激发.txt', 'wuzhaojunyi_三阶P2B_棍架.txt',
         'wuzhaojunyi_三阶P2C_棍扫.txt', 'wuzhaojunyi_三阶P2D_过载.txt',
         'wuzhaojunyi_三阶P3A_亮枪.txt', 'wuzhaojunyi_三阶P3B_枪花.txt',
         'wuzhaojunyi_三阶P3C_崩弹.txt', 'wuzhaojunyi_三阶P3D_点喉.txt']
REASON = ('09-28 起三阶 12 镜的现行真源＝`ComfyUI_H3/prompts_H3官方骨架/`（官方 I2VA 骨架）；'
          '这批中文十块稿是它的前身，已判废。留在 `prompts/` 里会被旧 glob 命中并造成误写'
          '（手册冲突表·风险 23 与 C63）。')
AUTH = '用户 2026-09-28 原话：「prompts\\ 里那 12 份旧十块稿……这个清掉」'


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 16), b''):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', default=True)
    ap.add_argument('--delete-after-verify', action='store_true',
                    help='复制→sha256 逐份复核→全对才删源；不给这个旗标就只复制不删')
    a = ap.parse_args()
    do_delete = a.delete_after_verify

    dst_dir = os.path.join(POOL, PROJ, '_判废归档_' + STAMP, REL_DIR)
    os.makedirs(dst_dir, exist_ok=True)
    rows, missing = [], []
    for name in FILES:
        src = os.path.join(SRC_ROOT, REL_DIR, name)
        if not os.path.isfile(src):
            missing.append(src)
            continue
        st = os.stat(src)
        dst = os.path.join(dst_dir, name)
        h_src = sha256(src)
        shutil.copy2(src, dst)
        h_dst = sha256(dst)
        ok = h_src == h_dst
        rows.append((name, st.st_size, time.strftime('%Y-%m-%d %H:%M',
                                                     time.localtime(st.st_mtime)),
                     h_src, h_dst, dst))
        print('%-40s %7d  %s  %s' % (name, st.st_size, h_src[:12], '✓ sha 一致' if ok else '✗ 不符'))
    bad = [r for r in rows if r[3] != r[4]]
    if missing:
        print('\n✗ 源里找不到 %d 份（可能已被搬走/改名）：%s' % (len(missing), missing[:3]))
    if bad:
        print('✗ %d 份 sha 不符 ⇒ **一律不删源**' % len(bad))
        return 1
    if not rows:
        print('✗ 一份都没取到 ⇒ 停手，别当"已经清干净了"')
        return 1

    man_dir = os.path.join(POOL, '_归档_MANIFEST',
                           time.strftime('%Y%m%d_%H%M%S') + '_三阶十块旧稿判废')
    os.makedirs(man_dir, exist_ok=True)
    lines = ['# 判废归档清单 · 三阶 12 镜中文十块旧稿', '',
             '生成：%s ｜ 工具：`tmp/wzy/archive_superseded_prompts.py` ｜ 删除动作：%s'
             % (time.strftime('%Y-%m-%d %H:%M:%S'),
                ('**已按 sha256 复核后删源**' if do_delete else '未执行（dry-run，源仍在原位）')),
             '', '## 为什么判废', REASON, '', '## 授权出处', AUTH, '',
             '## 落点', ' `%s`（保原相对路径 `%s/`，可原样还原）' % (dst_dir, REL_DIR), '',
             '| 文件 | 字节 | 原 mtime | sha256 | 归档路径 |', '|---|---|---|---|---|']
    for name, size, mtime, hs, hd, dst in rows:
        lines.append('| %s | %d | %s | `%s` | `%s` |' % (name, size, mtime, hs, dst))
    if missing:
        lines += ['', '⚠ 运行时源里已不存在的文件：%s' % '、'.join(missing)]
    man = os.path.join(man_dir, 'MANIFEST.md')
    with open(man, 'w', encoding='utf8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n清单已写：', man)

    if not do_delete:
        print('（dry-run）源未删除。要真删：加 --delete-after-verify')
        return 0
    n = 0
    for name, _s, _m, _h, _d, _dst in rows:
        src = os.path.join(SRC_ROOT, REL_DIR, name)
        if sha256(src) == _h:                      # 删前再核一次，防中途被人改过
            os.remove(src)
            n += 1
        else:
            print('✗ %s 删除前复核不一致 ⇒ 留着不动' % name)
    print('已删源 %d/%d 份；归档与清单在 %s' % (n, len(rows), dst_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
