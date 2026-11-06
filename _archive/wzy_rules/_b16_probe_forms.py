# -*- coding: utf-8 -*-
"""补词形之前的**实证步**：候选英文形在现役 20 份稿面里到底出现没有、出现几次。

规矩：补进判据表的英文词形只有两种可以收——
 ① 现役正文里查得到（实证：本层的判据得能看见本层已经写出来的东西）；
 ② 官方三模板里查得到（照抄官方形）。
其余一律不收（凭印象造词＝把闸按在自己的猜测上，下一批正文换个写法又瞎）。
命中 0 的候选当场打 ✗，由我判"是词形错还是正文确实没写"。
"""
import io
import json
import os
import re
import sys

BK = r"E:\本地工作流规范手册\99_维护\_改前备份_20261003_正文英译"
MF = os.path.join(r"D:\AIWorkflow\tmp\wzy", "h3_rewrite_manifest.json")
OFF = [r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\base-en.txt",
       r"D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\ref-en.txt"]

CAND = {
    "LOCK_SHAPE_EN": ["exactly one", "the same", "unchanged", "hold unchanged",
                      "single shot", "one continuous", "the full vertical",
                      "holds the full", "keep the first-frame appearance",
                      "keeps the first-frame appearance"],
    "LOCK_STATE_EN": ["stays", "keeps", "holds", "never exposed", "fully bound",
                      "with nothing added", "stays carried", "remain",
                      "wound around", "is not taken up", "does not take it up"],
    "UNWRAP_EN": ["unbound", "no longer cloth-bound", "bare", "unwrapped", "takes the staff",
                  "lifts the staff", "draws", "shaft bare", "cold-edged", "wound around her left wrist",
                  "pulls the cloth", "cloth falls", "loosens"],
    "LIGHT_NOUN_EN": ["light", "glow", "neon", "lamp", "glare", "reflection", "halo", "beam"],
    "LIGHT_BAD_V_EN": ["shoots", "streams", "strikes", "hits", "beams out", "spits", "erupts",
                       "lashes", "laser"],
    "底线_MARK_EN": ["never touches", "no contact", "never make contact", "does not touch",
                     "never lands", "not touch", "without touching", "never connects",
                     "never breaks", "carries no", "is lettering-free", "with no"],
    "FX_POS_EN": ["fine", "sparse", "translucent", "glint", "ember", "dust", "sparks",
                  "scattered", "flicker", "molten", "shimmer", "thin", "pale"],
    "FX_BAD_EN": ["energy wave", "laser", "shockwave", "light wave", "explosion", "blast",
                  "plasma", "fireball"],
    "ABSTRACT_EN": ["masterful", "effortless", "with authority", "fluid", "precise",
                    "controlled", "elegant", "composed", "skilled", "overbearing",
                    "unhurried", "settled", "cold and clear", "presence"],
    "BODY_EN": ["hand", "arm", "shoulder", "wrist", "knee", "foot", "hip", "back",
                "chest", "chin", "finger", "eye", "head", "leg", "waist"],
    "CAM_RESULT_ONLY_EN": ["fully in frame", "stays visible", "keep both figures",
                           "hold both figures whole inside frame", "fills the frame",
                           "never leaves the frame", "in shot", "whole inside frame"],
    "NEG_EN": ["do not", "don't", "does not", "never", "no ", "not ", "without", "avoid",
               "with no", "carries no", "free of", "nothing", "nor ", "neither"],
}


def corpus():
    mf = json.load(io.open(MF, encoding="utf-8"))
    txts = []
    for f in mf["files"]:
        p = f["path"]
        if os.path.isfile(p):
            txts.append((os.path.basename(p), io.open(p, encoding="utf-8").read()))
    return txts


def main():
    ps = corpus()
    joined = " \n".join(t for _n, t in ps).lower()
    off = ""
    for o in OFF:
        if os.path.isfile(o):
            off += io.open(o, encoding="utf-8").read().lower()
    print(u"现役 %d 份｜官方模板 %d 字节" % (len(ps), len(off)))
    for tbl, cands in CAND.items():
        print(u"\n── %s" % tbl)
        for c in cands:
            cl = c.lower()
            if cl.isascii():
                pat = r"(?<![A-Za-z0-9])" + re.escape(cl).replace(r"\ ", r"[\s]+") + r"(?![A-Za-z0-9])"
                try:
                    n = len(re.findall(pat, joined))
                except re.error:
                    n = joined.count(cl)
            else:
                n = joined.count(cl)
            nf = len(re.findall(r"(?<![A-Za-z0-9])" + re.escape(cl) + r"(?![A-Za-z0-9])", off)) \
                if cl.isascii() else 0
            mark = u"✓" if n else (u"◆官方" if nf else u"✗ 0")
            print(u"   %-46s 现役 %3d｜官方 %2d  %s" % (c, n, nf, mark))


if __name__ == "__main__":
    main()
