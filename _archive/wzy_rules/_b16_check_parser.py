# -*- coding: utf-8 -*-
r"""批 16 底座改动的**回归对账**：新解析式 vs 旧解析式，同语料逐份比。

要证的事只有两条（改现役解析式的三重预验之二、之三）：
1. **中文稿判定面逐字不变**——20 份改前备份（中文正文＋`X.Y–Z.W 秒`＋`Throughout:` 标签）
   在新旧两套解析式下，beats 数、四区切分、dialog 数必须**完全相同**；
2. **英文稿恢复可见**——20 份现役稿（英文正文＋`X.Y-Z.Ws:`）在新解析式下 beats 不再为空。

旧解析式不是"我记得长这样"，是**按字面量重新编译一份**贴回去跑，跑完立刻还原。
用法：python _b16_check_parser.py
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, r"D:\AIWorkflow\tmp\wzy")
import prompt_format as PF        # noqa: E402

BK = r"E:\本地工作流规范手册\99_维护\_改前备份_20261003_正文英译"
MF = os.path.join(r"D:\AIWorkflow\tmp\wzy", "h3_rewrite_manifest.json")

OLD_THROUGHOUT = re.compile(u"Throughout\\s*[::]?\\s*", re.I)
OLD_UNIT = u"秒"
OLD_BEAT_CN = re.compile(r"(\d+\.\d+)\s*[–-]\s*(\d+\.\d+)\s*" + OLD_UNIT +
                         r"\s*[::]?\s*(.*?)(?=\d+\.\d+\s*[–-]\s*\d+\.\d+\s*" + OLD_UNIT + r"|$)",
                         re.S)


def measure(text):
    reg = PF.regions(text)
    bs = PF.beats(text)
    return {
        "kind": reg["kind"],
        "n_beats": len(bs),
        "beats": [(b[0], b[1]) for b in bs],
        "style": reg["style"], "camera": reg["camera"],
        "body": reg["body"], "invariant": reg["invariant"],
        "n_dlg": len(reg["dialog"]),
    }


def with_old(fn):
    """把两条旧字面量贴回模块，跑完还原（异常也还原）。"""
    keep = (PF._THROUGHOUT_RE, PF._BEAT_CN)
    PF._THROUGHOUT_RE, PF._BEAT_CN = OLD_THROUGHOUT, OLD_BEAT_CN
    try:
        return fn()
    finally:
        PF._THROUGHOUT_RE, PF._BEAT_CN = keep


def main():
    mf = json.load(io.open(MF, encoding="utf-8"))
    pairs = []
    for f in mf["files"]:
        p = f["path"]
        b = os.path.join(BK, os.path.basename(os.path.dirname(p)) + u"__" + os.path.basename(p))
        if os.path.isfile(b) and os.path.isfile(p):
            pairs.append((os.path.basename(p), io.open(b, encoding="utf-8").read(),
                          io.open(p, encoding="utf-8").read()))
    print(u"对账份数：%d（每份测改前/改后两稿 ⇒ %d 个样本）" % (len(pairs), 2 * len(pairs)))

    diffs_cn, gained_en, lost_en = [], [], []
    for name, old, new in pairs:
        for tag, txt, bucket in ((u"改前(中文)", old, diffs_cn), (u"改后(英文)", new, None)):
            a = with_old(lambda t=txt: measure(t))
            b = measure(txt)
            if bucket is not None:                     # 中文稿：必须逐字不变
                if a != b:
                    keys = [k for k in a if a[k] != b[k]]
                    bucket.append((name, tag, keys,
                                   {k: (str(a[k])[:60], str(b[k])[:60]) for k in keys}))
            else:                                      # 英文稿：旧解析式应当瞎、新解析式应当看得见
                if a["n_beats"] != b["n_beats"] or a["camera"] != b["camera"]:
                    gained_en.append((name, a["n_beats"], b["n_beats"],
                                      bool(a["camera"]), bool(b["camera"])))
                if b["n_beats"] < a["n_beats"]:
                    lost_en.append((name, a["n_beats"], b["n_beats"]))

    print(u"\n[1] 中文稿回归：新旧解析式差异 %d 份 %s"
          % (len(diffs_cn), u"✓ 逐字一致" if not diffs_cn else u"✗ 有变"))
    for n, t, keys, d in diffs_cn[:10]:
        print(u"   %s %s 变动字段 %s" % (n, t, keys))
        for k, (o, w) in d.items():
            print(u"      %s: 旧=%s | 新=%s" % (k, o, w))

    print(u"\n[2] 英文稿恢复可见：%d 份的节拍数或运镜区发生变化" % len(gained_en))
    for n, ob, nb, oc, nc in gained_en:
        print(u"   %-34s 节拍 %d→%d｜运镜区 %s→%s" % (n, ob, nb,
               u"有" if oc else u"空", u"有" if nc else u"空"))
    if lost_en:
        print(u"   ✗ 反而变瞎的：%s" % lost_en)

    ok = not diffs_cn and not lost_en and len(gained_en) > 0
    print(u"\n结论：%s" % (u"✓ 中文稿零回归、英文稿由瞎转可见" if ok else u"✗ 不通过，别合"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
