# -*- coding: utf-8 -*-
"""feishu_send.py —— 飞书**审片三件套**封装（文本结论 → 逐镜拼图 → 成片）。

为什么要有它（批 2／GAP-D2）：`lark-cli.exe` 实测有 2 处真安装、**全不在 PATH**，
每次调用都得记全路径，换个会话就断；而且它的坑都是踩过才知道的（见下）。
这个脚本把路径锁死、把坑封在内部。

实测到的硬约束（都体现在代码里，不是文档抄的）：
  · **媒体旗标只收 cwd 相对路径，绝对路径与 `..` 一律被拒** ⇒ 必须先 chdir 再传文件名。
  · `--video` **必须配 `--video-cover`**，否则发不出去。
  · **媒体消息不能同时带文字** ⇒ 三件套是"三条消息"不是一条，顺序固定：
    ① 文本结论 ② 逐镜拼图 ③ 成片（＋封面）。
  · 30 MB 上限；超限就改发审片区链接（`review_publish.py`），不要压到失真硬塞。
  · 输出是**带空格的 pretty JSON** ⇒ 用空格敏感的 grep 判成功会静默失配，这里走 json 解析。

边界（不承诺的能力）：
  · **发送侧此前实测可靠；接收侧未证实**（应用只有 im:message.p2p_msg:readonly，
    读群历史被拒 230027）⇒ 本脚本只报"服务端接了单"，不报"你看到了"。
  · high-risk-write 类的命令这里一个都不用；发消息是 write，且**默认就要 --yes 才真发**，
    免得在自动化里悄悄往你群里灌东西。

用法：
  py -3.12 feishu_send.py --text "段2 v5 四条全过"                      # 一条文本
  py -3.12 feishu_send.py --review --text "..." --sheet 拼图.png --film 成片.mp4
  py -3.12 feishu_send.py --review --text "..." --film 成片.mp4 --cover 首帧.png
  py -3.12 feishu_send.py --dry-run --text 自检                          # 不发，只看请求
退出码：0 全部送达服务端／1 参数或体积不合格／2 CLI 报错／3 部分成功
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# 锁死全路径：两处真安装都在 PATH 之外。这里用记忆件里那条**已验证过发送**的，
# 另一处（.hub\\runtimes）只作回退，不并列使用——同一时间只有一个在跑，避免混版本。
LARK = r"C:\Users\若水\.local\share\qoder\lark-cli\node_modules\@larksuite\cli\bin\lark-cli.exe"
LARK_ALT = r"C:\Users\若水\.hub\runtimes\lark-cli\lark-cli.exe"
CHAT_ID = "oc_4f43e84db8b16403e036eb54d57bf49f"   # 用户本人接收群（config.yaml feishu.chat_id）
MAX_MB = 30.0
MEDIA_FLAGS = ("--image", "--file", "--video", "--audio")


def which_cli():
    for p in (LARK, LARK_ALT):
        if os.path.isfile(p):
            return p
    sys.exit("!! 两处 lark-cli.exe 都不在位；本脚本不下载也不改安装，先确认装过")


def rel(path):
    """CLI 只收 cwd 相对路径 ⇒ 把绝对路径拆成 (新 cwd, 相对名)。
    同盘符时用 os.path.relpath；跨盘 relpath 会炸，就临时拷一份到工作目录。"""
    ap = os.path.abspath(path)
    if not os.path.isfile(ap):
        sys.exit("!! 文件不存在：%s" % ap)
    mb = os.path.getsize(ap) / 1048576.0
    if mb > MAX_MB:
        sys.exit("!! %s %.1f MB 超飞书 %s MB 上限 ⇒ 改走 review_publish.py 发审片区链接，"
                 "别压到失真硬塞" % (os.path.basename(ap), mb, MAX_MB))
    cwd = os.path.dirname(ap)
    name = os.path.basename(ap)
    return cwd, name


def run(cli, args, dry):
    cmd = [cli, "im", "+messages-send"] + args + ["--format", "json"]
    if dry:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        print("  !! %s" % out[-400:])
        return False, out
    # pretty JSON 带空格 ⇒ 必须解析，不能 grep 关键字
    try:
        data = json.loads(out)
    except Exception:
        # 视频等路径 CLI 会在 JSON 前后夹带进度/提示行(或输出两个对象):
        # 退回解码第一个完整 JSON 对象,而不是把已成功的发送误判为未确认。
        try:
            idx = out.index("{")
            data, _ = json.JSONDecoder().raw_decode(out, idx)
        except Exception:
            print("  ⚠ 退出码 0 但输出不是 JSON，按未确认处理：%s" % out[:160])
            return False, out
    mid = ""
    def dig(o):
        nonlocal mid
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("message_id", "msgId", "mid") and isinstance(v, str):
                    mid = mid or v
                dig(v)
        elif isinstance(o, list):
            for v in o:
                dig(v)
    dig(data)
    return True, (mid or "已受理")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="", help="文本结论（三件套第 ① 条）")
    ap.add_argument("--sheet", default="", help="逐镜拼图 png（第 ② 条）")
    ap.add_argument("--film", default="", help="成片 mp4（第 ③ 条，须配 --cover）")
    ap.add_argument("--cover", default="", help="成片封面（--film 必需）")
    ap.add_argument("--audio", action="append", default=[], help="音频（可重复给多条；走 --audio 旗标）")
    ap.add_argument("--review", action="store_true", help="按审片三件套的顺序发")
    ap.add_argument("--chat", default=CHAT_ID)
    ap.add_argument("--yes", action="store_true", help="确认要真发（不带就只打印计划）")
    ap.add_argument("--dry-run", action="store_true", help="让 CLI 自己打印请求，不执行")
    a = ap.parse_args(argv)

    if not (a.text or a.sheet or a.film or a.audio):
        sys.exit(__doc__)
    if a.film and not a.cover:
        sys.exit("!! --film 必须配 --video-cover：CLI 明确要求，缺了发不出去")
    if not a.review and sum(bool(x) for x in (a.text, a.sheet, a.film)) + len(a.audio) > 1:
        sys.exit("!! 一次只发一条，除非你明确要 --review（媒体消息不能同时带文字）")

    cli = which_cli()
    go = bool(a.dry_run) or bool(a.yes)
    if not go:
        print("计划（未发）：① 文本 %s ② 拼图 %s ③ 成片 %s＋封面 %s → chat %s"
              % (a.text[:36] or "—", a.sheet or "—", a.film or "—", a.cover or "—", a.chat))
        print("要真发加 --yes；只看请求加 --dry-run")
        return 0

    steps, sent, failed = [], 0, 0

    def add(label, args, cwd=None):
        steps.append((label, args, cwd))

    if a.text:
        add("① 文本", ["--chat-id", a.chat, "--text", a.text])
    if a.sheet:
        cwd, name = rel(a.sheet)
        add("② 逐镜拼图", ["--chat-id", a.chat, "--image", name], cwd)
    for i, apath in enumerate(a.audio, 1):
        # 音乐审听走 --file 附件（mp3 原质）；--audio 只收 Opus 语音（16k 单声道），发音乐会毁音质
        cwd, name = rel(apath)
        add("音%d %s" % (i, os.path.basename(name)), ["--chat-id", a.chat, "--file", name], cwd)
    if a.film:
        cwd, name = rel(a.film)
        _, cover = rel(a.cover)
        add("③ 成片", ["--chat-id", a.chat, "--video", name, "--video-cover", cover], cwd)

    for label, args, cwd in steps:
        old = os.getcwd()
        try:
            if cwd:
                os.chdir(cwd)          # CLI 只收 cwd 相对路径
            print("  %s → %s" % (label, args[-1] if label == "① 文本" else
                                  " ".join(x for x in args if not x.startswith("--"))[:70]))
            ok, info = run(cli, args, a.dry_run)
        finally:
            os.chdir(old)
        sent += ok
        failed += (not ok)
        print("     %s %s" % ("✓" if ok else "!!", str(info)[:90]))
    print("-" * 60)
    if a.dry_run:
        print("dry-run：%d 条请求已生成，**一条都没发**（下面那句『服务端接了单』不适用于本次）" % sent)
    else:
        print("送达服务端 %d 条／失败 %d 条" % (sent, failed))
        print("⚠ 这只证明服务端接了单；**接收侧未证实**，请到群里确认看到了。")
    return 0 if not failed else (3 if sent else 2)


if __name__ == "__main__":
    sys.exit(main())
