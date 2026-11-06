# -*- coding: utf-8 -*-
"""G7 判据改造后的对照验证（只读，不改任何提示词/脚本）。

要验的三件事，按 2026-09-28 的格式契约逐条对上：
  ① 新真源（官方骨架 12 份）在 G7 下必须**零 error**——否则一开闸就把现役稿全拦死；
  ② 官方六段（ref2va）必须走**六段判据**而不是骨架判据（这就是 C57：
     h3_ref2va_video.yaml 没写 prompt_kind，旧代码 `or "video"` 把六段送进骨架分支，
     会假报"缺官方首帧指令"）；
  ③ 中文十块进本地 H3＝**混用 error**（提示词是故意这么改的，避免混用），
     同一段文本走云端通道时改判十块内容缺块，两者不能互相冒充。

用法：python verify_g7_dispatch.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, r'D:/AIWorkflow/tools')
import check_preflight as C  # noqa: E402

PR = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts')
SKEL = Path(r'D:/AIWorkflow/ComfyUI_H3/prompts_H3官方骨架')
REFEN = PR / 'official_h3' / 'ref-en.txt'


def run(prompt, **spec):
    s = dict(prompt=prompt, only=['G7'], refs=['a.png'], characters=[])
    s.update(spec)
    rep = C.run_checks(s)
    g7 = [(lv, t) for lv, g, t in rep.items if g == 'G7']
    err = [t for lv, t in g7 if lv == 'error']
    wrn = [t for lv, t in g7 if lv == 'warn']
    fmt = next((t for lv, t in g7 if lv == 'ok' and '通道＝' in t), '(没报格式)')
    return err, wrn, fmt


def official_ref2va():
    """从官方 ref-en.txt §7 的 Complete Example 里取六段原文（真源，不是我编的）。"""
    t = REFEN.read_text(encoding='utf8')
    seg = t.split('## 7. Complete Example', 1)[1]
    body = seg.split('```text', 1)[1].split('```', 1)[0]
    return body.strip()


def main():
    fails = []

    def check(name, got, want):
        ok = got == want
        print('%-4s %-46s 期望 %s / 实得 %s' % ('✓' if ok else '✗', name, want, got))
        if not ok:
            fails.append(name)

    print('=' * 100)
    print('① 新真源：官方骨架 12 份（通道 h3）⇒ 必须零 error')
    print('=' * 100)
    tot_e = tot_w = 0
    for f in sorted(SKEL.glob('*.txt')):
        err, wrn, fmt = run(f.read_text(encoding='utf8'), prompt_kind='h3_i2va',
                            provider='local')
        tot_e += len(err)
        tot_w += len(wrn)
        print('  %-30s %-58s err=%d warn=%d' % (f.stem[:30], fmt[:58], len(err), len(wrn)))
        for t in err:
            print('      ✗ %s' % t[:110])
        for t in wrn:
            print('      ! %s' % t[:110])
    check('骨架 12 份零 error', tot_e, 0)
    print('  （警告合计 %d 条，逐条列出供裁）' % tot_w)

    print()
    print('=' * 100)
    print('② 官方六段 ref2va（yaml 未声明 prompt_kind＝旧代码的坑）⇒ 走六段判据、零 error')
    print('=' * 100)
    six = official_ref2va()
    for kind in ('h3_ref2va', 'video'):          # video＝h3_ref2va_video.yaml 的实际取值
        err, wrn, fmt = run(six, prompt_kind=kind, provider='local')
        print('  kind=%-10s %s' % (kind, fmt[:70]))
        for t in err + wrn:
            print('      · %s' % t[:110])
        check('六段 kind=%s 零 error' % kind, len(err), 0)
        check('六段 kind=%s 识别为六段' % kind, '全参考六段' in fmt, True)

    print()
    print('=' * 100)
    print('③ 混用矩阵（同一段文本，通道不同判据必须不同）')
    print('=' * 100)
    ten = (PR / 'ref2va_test.txt').read_text(encoding='utf8')   # 拆分前的旧十块写法
    err, wrn, fmt = run(ten, prompt_kind='video', provider='local')
    print('  十块 + 本地 H3：%s' % fmt[:70])
    for t in err:
        print('      ✗ %s' % t[:118])
    check('十块进 H3 报混用', any('混用' in t for t in err), True)
    err2, wrn2, fmt2 = run(ten, prompt_kind='video', provider='ark')
    print('  十块 + 云端 SD：%s' % fmt2[:70])
    for t in err2 + wrn2:
        print('      · %s' % t[:118])
    check('同稿走云端不再报混用', any('混用' in t for t in err2), False)
    check('同稿走云端识别为十块', '十块' in fmt2, True)

    err, wrn, fmt = run(six, prompt_kind='video', provider='ark')
    print('  六段 + 云端 SD：%s' % fmt[:70])
    for t in err:
        print('      ✗ %s' % t[:118])
    check('六段进云端报混用', any('混用' in t for t in err), True)

    print()
    print('=' * 100)
    print('④ 图片口径与骨架内部故障')
    print('=' * 100)
    img = '21岁女子，清冷骨相，宽袖襦裙，写实3D CG渲染，竖幅构图，单人立像'
    err, wrn, fmt = run(img, prompt_kind='image', provider='local', characters='none')
    print('  图片稿：%s' % fmt[:70])
    check('图片稿零 error', len(err), 0)
    err, wrn, fmt = run(img + '，用稳定器环绕拍摄', prompt_kind='image',
                        provider='local', characters='none')
    check('图片稿器材名词仍拦', any('器材' in t for t in err), True)

    base = (SKEL / 'wuzhaojunyi_三阶P1A.txt').read_text(encoding='utf8')
    for name, txt, want in [
            ('骨架删掉首行指令', base.split('\n\n', 1)[1], True),
            ('骨架混进六段字段', base + '\nsubject_definitions:\nX', True),
            ('骨架多挂 Picture 2', base + ' <Picture 2>', True),
            ('骨架正文不从 [Shot 1] 开始',
             base.replace('[Shot 1] 高精度CG', '[Take 1] 高精度CG', 1), True),
            ('整段无格式文本给 H3', '她在雪地里走了三步，镜头缓推。' * 6, True)]:
        err, wrn, fmt = run(txt, prompt_kind='h3_i2va', provider='local')
        print('  %-24s %s' % (name, fmt[:56]))
        for t in err:
            print('      ✗ %s' % t[:118])
        check(name, any(('混用' in t or '骨架' in t or '认不出' in t) for t in err), want)

    print()
    print('=' * 100)
    if fails:
        print('✗ 未通过 %d 项：%s' % (len(fails), '；'.join(fails)))
    else:
        print('✓ 全部通过')
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
