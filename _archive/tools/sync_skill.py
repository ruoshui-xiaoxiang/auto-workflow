#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""sync_skill.py · 影视 Skill 的副本同步检查器（默认只读、只报不拦）。

为什么要有它（10-02 批 4·4／GAP-M1）：skill 事实源、E 盘逐字镜像、D 盘去本机化副本
三份东西长得一样但用途不同，**快照不自动跟随**——改了一份、另两份静默过期。
实测已经漂过：通道真源已到 10-02，而 skill 的 `references\` 最新只到 09-23。

三条轴分开报，别混成一件事：
  [A] 逐字镜像是否等值：事实源 vs `E:\公共记忆\skills\cinematic-video-production\`，
      **逐文件 sha256**（这一份的约定就是逐字一致，所以能比哈希）。
  [B] 去本机化副本是否**漏了敏感东西**：不能比哈希（内容本就该不同），
      改成扫残留词表——本机绝对路径／账户与密钥字样／项目与角色实名／私有记忆双链。
  [C] 上游是否比 skill 新：`D:\AIWorkflow\ComfyUI_H3\*.md`（通道真源）里有任何一份
      比 skill 的 `references\` 新 ⇒ skill 里的通道口径是旧的。这条就是 GAP-M1 的量化。

铁律（与 `feedback-copy-not-move` 同一条）：`--mirror` 只做 **copy＋复核**，
**永不删源、永不删多余文件**——"这份该不该留"是判定，判定权在人不在脚本。
多余文件一律报出来交人处理。
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys

SRC = r"C:\Users\若水\.qoder\skills\cinematic-video-production"
MIRROR = r"E:\公共记忆\skills\cinematic-video-production"
# 2026-10-08 D 盘收干净：去本机化便携包已迁 E 盘归档（用户裁定）
PORTABLE = r"E:\归档区\cinematic-video-production-portable\cinematic-video-production"
# 即梦短剧/打戏技能事实源（.qoder 为同步镜像，编辑只改这里）
JIMENG_SRC = r"E:\创作\即梦技能包\skills"
JIMENG_MIRROR = r"C:\Users\若水\.qoder\skills"
UPSTREAM = r"D:\AIWorkflow\ComfyUI_H3"
# 通道真源里这几份是 skill 必须跟上的（其余是历史／对照件，不参与 [C]）
CHANNEL_DOCS = ["H3提示词工程规则方案.md", "H3提示词规则_现行合并版.md", "云端SD提示词模板_十块.md",
                "图片链_工作流规则.md", "千问云端_工作流规则.md", "即梦云端_工作流规则.md",
                "可灵云端_工作流规则.md", "Vidu云端_工作流规则.md", "海螺云端_工作流规则.md"]
RESIDUAL = [
    (r"[A-Za-z]:\\\\?Users\\\\?", "本机用户路径"),
    (r"[A-Za-z]:\\\\?(?:AIWorkflow|创作|图像影音资源池|LocalAI)", "本机项目/资产路径"),
    (r"(api[_ ]?key|apikey|sk-[A-Za-z0-9]{6,}|Bearer\s+[A-Za-z0-9])", "密钥字样"),
    (r"(?:[¥￥$]|\d+(?:\.\d+)?\s*(?:元|块|积分|tokens?))[^\n]{0,24}"
     r"|(?:单价|实付|报价|余额|积分|充值)[^\n]{0,16}\d", "账户与价格（带数字才算漏网）"),
    (r"\[\[[^\]\[]+\]\]", "私有记忆双链（方括号里须有内容，示例写法不算）"),
    (r"(无音|沈无音|薇拉|白玖璃|武昭君仪|武君仪|烬骨辞|仙女星系|机械战星|仙戮)", "项目与角色实名"),
]
B=chr(92)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def listing(root, exts=(".md", ".txt")):
    out = {}
    if not os.path.isdir(root):
        return out
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in ("__pycache__", ".git", "node_modules")]
        for f in fn:
            if f.lower().endswith(exts):
                p = os.path.join(dp, f)
                out[os.path.relpath(p, root).lower()] = p
    return out


def check_mirror(src_files, mir_files):
    same, stale, missing, extra, errors = [], [], [], [], []
    for rel, p in sorted(src_files.items()):
        if rel not in mir_files:
            missing.append(rel)
            continue
        try:
            if sha256(p) == sha256(mir_files[rel]):
                same.append(rel)
            else:
                stale.append(rel)
        except Exception as e:
            errors.append("%s：%s" % (rel, e))
    extra = sorted(set(mir_files) - set(src_files))
    return same, stale, missing, extra, errors


def apply_mirror(src_files, stale, missing, root=MIRROR):
    """只 copy，复制完**重新从盘上读哈希**复核（台账自己写的数不作数）。"""
    moved = []
    for rel in stale + missing:
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst) or root, exist_ok=True)
        with open(src_files[rel], "rb") as fh:
            data = fh.read()
        with open(dst, "wb") as fh:
            fh.write(data)
        src_h = hashlib.sha256(data).hexdigest()
        dst_h = sha256(dst)
        moved.append((rel, src_h == dst_h))
    bad = [r for r, ok in moved if not ok]
    return moved, bad


def check_residual(files):
    hits = []
    for rel, p in sorted(files.items()):
        try:
            t = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for rx, label in RESIDUAL:
            for m in re.finditer(rx, t):
                line = t[:m.start()].count("\n") + 1
                hits.append((label, rel, line, m.group(0)[:38]))
                break                      # 每条规则每文件只报首个，避免刷屏
    return hits


def check_upstream(refs_dir):
    """[C] 通道真源 vs skill references 的新旧。测不到就写测不到，不猜。"""
    newest_ref_day, ref_count = None, 0
    if os.path.isdir(refs_dir):
        days = []
        for f in os.listdir(refs_dir):
            if f.lower().endswith(".md"):
                ref_count += 1
                days.append(os.path.getmtime(os.path.join(refs_dir, f)))
        if days:
            newest_ref_day = max(days)
    rows, newest_up = [], None
    for f in CHANNEL_DOCS:
        p = os.path.join(UPSTREAM, f)
        if not os.path.isfile(p):
            rows.append((f, None, "文件不存在"))
            continue
        mt = os.path.getmtime(p)
        newest_up = mt if newest_up is None or mt > newest_up else newest_up
        lag = None
        if newest_ref_day is not None:
            lag = round((mt - newest_ref_day) / 86400.0, 1)
        rows.append((f, lag, None))
    return rows, newest_up, newest_ref_day, ref_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mirror", action="store_true",
                    help="把 [A] 报出的 陈旧＋缺失 从事实源 copy 到镜像，复制后逐份重读哈希复核")
    ap.add_argument("--json", action="store_true", help="结构化输出（扫描器可用来替掉自己写死的那几个数）")
    ap.add_argument("--strict", action="store_true", help="有陈旧／漏网敏感项时返回 1")
    a = ap.parse_args()

    src_files = listing(SRC)
    mir_files = listing(MIRROR)
    port_files = listing(PORTABLE)
    refs_dir = os.path.join(SRC, "references")

    same, stale, missing, extra, errors = check_mirror(src_files, mir_files)
    res = check_residual(port_files)
    rows, newest_up, newest_ref, ref_count = check_upstream(refs_dir)

    if not a.json:
        print("=" * 72)
        print("sync_skill.py · 影视 Skill 三副本同步检查（默认只读）")
        print("事实源 %d 份 ｜ 镜像 %d 份 ｜ 去本机化副本 %d 份 ｜ skill references %d 篇"
              % (len(src_files), len(mir_files), len(port_files), ref_count))
        print("=" * 72)
        print("[A] 逐字镜像：等值 %d ｜ 陈旧 %d ｜ 缺失 %d ｜ 镜像多余 %d ｜ 读失败 %d"
              % (len(same), len(stale), len(missing), len(extra), len(errors)))
        for r in (stale + missing)[:12]:
            print("      需刷新 %s" % r)
        if extra:
            print("  ⚠ 镜像里有 %d 个事实源没有的文件：%s"
                  % (len(extra), "、".join(extra[:8])))
            print("    ⇒ **脚本不删**：该不该留是判定，判定权在人（同 status 不设 experiment 档）")
        for e in errors[:5]:
            print("  !! [A] %s" % e)

        print("[B] 去本机化副本残留词表：命中 %d 处" % len(res))
        for label, rel, line, frag in res[:15]:
            print("      %-14s %s:%d  %r" % (label, rel, line, frag))
        if len(res) > 15:
            print("      … 其余 %d 处省略" % (len(res) - 15))

        print("[C] 上游通道真源 vs skill references 的新旧（天，正数＝skill 落后）")
        for f, lag, why in rows:
            print("      %-34s %s" % (f, ("落后 %s 天" % lag) if (lag is not None and lag > 0) else ("已跟上" if lag is not None and lag <= 0 else (why or "测不到"))))
        if newest_up and newest_ref:
            print("      汇总：最新通道真源比 skill references 最新一篇新 %s 天"
                  % round((newest_up - newest_ref) / 86400.0, 1))
        elif not newest_ref:
            print("  !! [C] skill references 测不到时间戳 ⇒ 这项没跑，不算通过")

    if a.mirror:
        moved, bad = apply_mirror(src_files, stale, missing)
        print("--mirror：copy %d 个并**重读哈希复核**，复核不过 %d 个%s"
              % (len(moved), len(bad), ("：" + "、".join(bad)) if bad else ""))
        if bad:
            return 1

    data = {"mirror": {"same": len(same), "stale": stale, "missing": missing,
                       "extra": extra, "errors": errors},
            "residual_hits": len(res),
            "residual_labels": sorted({l for l, _r, _x, _f in res}),
            "upstream_lag_days": [r[1] for r in rows],
            "refs_count": ref_count,
            "src_count": len(src_files), "mirror_count": len(mir_files),
            "portable_count": len(port_files)}
    if a.json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")

    bad = bool(stale or missing or res)
    if a.strict and bad:
        print("!! --strict：有陈旧或敏感残留 ⇒ 退出码 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

