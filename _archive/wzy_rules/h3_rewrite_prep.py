# -*- coding: utf-8 -*-
r"""批 15 改写台（prep）：把 20 份 H3 稿**按句切好**并编成清单，供定译与并行分派用。

为什么要台子而不是直接改文件：
  · 台词必须逐字不动 —— 先把 `<d>…</d>` 抠出来当占位符，翻译永远看不见它，回填时原样放回；
  · 公共段必须**一次定译** —— 12 份稿里逐字重复的句子（基调句、站位句、不变量句…）
    靠句文本当键去重，谁改都是同一串英文，跨镜一致性才不会在我这次翻译里漂掉；
  · 逐字比对是硬验收 —— 改完要能说出台词条数不变、公共段份数不变、语言闸 0 命中。

只读，不写任何稿子；只产清单。
"""
import hashlib
import io
import json
import os
import re
import sys

sys.path.insert(0, r"D:\AIWorkflow\tmp\wzy")
import prompt_format as PF                                  # noqa: E402

ROOTS = [r"D:\AIWorkflow\ComfyUI_H3\prompts_H3官方骨架",
         r"D:\AIWorkflow\ComfyUI_H3\prompts_官方三段式",
         r"E:\创作\武昭君仪"]
EXCLUDE_NAMES = {u"三阶打斗_提示词全集.md"}                 # 派生合订本：不手改，随后重生成
CJK = re.compile(u"[\u4e00-\u9fff\u3040-\u30ff]")
DLG = re.compile(r"<d>.*?</d>", re.S)
SENT = re.compile(u"(?<=[。\uFF1B])|\\n")                  # 句号／分号／换行处切
MANIFEST = r"D:\AIWorkflow\tmp\wzy\h3_rewrite_manifest.json"


def sid(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def collect():
    files = []
    for root in ROOTS:
        for dp, _, fs in os.walk(root):
            for f in sorted(fs):
                if not f.endswith((".txt", ".md")) or f in EXCLUDE_NAMES:
                    continue
                p = os.path.join(dp, f)
                t = io.open(p, encoding="utf-8", errors="replace").read()
                if PF.detect(t) in ("h3_skeleton", "h3_ref2va") and PF.non_english_spans(t):
                    files.append((p, t))
    return files


def sentences(line):
    out = []
    for raw in SENT.split(line):
        if raw is None:
            continue
        s = raw.strip()
        if s:
            out.append(s)
    return out


def main():
    files = collect()
    segs = {}
    per_file = []
    for p, t in files:
        lines = t.split("\n")
        ents = []
        for i, line in enumerate(lines, 1):
            for s in sentences(line):
                if DLG.fullmatch(s):
                    continue
                body = DLG.sub(lambda m: " " + m.group(0) + " ", s)
                if len(CJK.findall(body)) < 4:               # 纯英文／纯数字的行不动
                    continue
                k = sid(body)
                e = segs.setdefault(k, {"zh": body, "count": 0, "chars": len(CJK.findall(body)),
                                        "has_dialogue": "<d>" in body})
                e["count"] += 1
                ents.append((i, k))
        per_file.append({"path": p, "name": os.path.basename(p),
                         "lines": len(lines), "segments": ents})
    tot_cjk = sum(v["chars"] for v in segs.values())
    shared = {k: v for k, v in segs.items() if v["count"] >= 2}
    unique = {k: v for k, v in segs.items() if v["count"] == 1}
    doc = {"files": per_file,
           "segments": {k: {"zh": v["zh"], "count": v["count"], "chars": v["chars"],
                           "has_dialogue": v["has_dialogue"], "en": None}
                        for k, v in segs.items()}}
    io.open(MANIFEST, "w", encoding="utf-8", newline="\n").write(
        json.dumps(doc, ensure_ascii=False, indent=1))
    print(u"份数 %d｜待译段 %d 条（公共 %d／单发 %d）｜汉字 %d｜含台词段 %d 条"
          % (len(files), len(segs), len(shared), len(unique), tot_cjk,
             sum(1 for v in segs.values() if v["has_dialogue"])))
    print(u"公共段里最大的 6 条（这些由我定译，一份都不许改口径）：")
    for k, v in sorted(shared.items(), key=lambda x: -x[1]["count"])[:6]:
        print(u"  [x%-2d] %s" % (v["count"], v["zh"][:88]))
    print(u"清单已写：%s（%s 字节）"
          % (MANIFEST, format(os.path.getsize(MANIFEST), ",")))


if __name__ == "__main__":
    main()
