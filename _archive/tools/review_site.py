# -*- coding: utf-8 -*-
"""review_site.py —— 本地 ↔ 审片站（huahuayoueryuan /studio）的推片与拉清单 CLI。

它在干什么（批 1）：
  · 把本地生成好的镜头（成片/单镜）压成网页预览版，推上审片站并挂到对应镜头的版本号下；
  · 把你在网页上写的意见，拉回来变成「待重做清单」，我按镜号单镜重渲，不整批重跑。
与现役 `review_publish.py` 的分工：那个管**旧的散装审片夹**（/review/<hex>/，上传即公网可见）；
这个管**新的审片站**（私有元数据 + 画布 + 流程状态）。两条都在，不互相替换。

凭证：
  · 站点用你现有的产品后台口令（同一个 /api/login）。
  · `login` 会交互式问你要口令；token 存 `D:\\AIWorkflow\\tokens\\review_site_token.json`（0600）。
  · 任何输出都不回显口令或 token；`--token-stdin` 可从别处管道喂 token。
  · 也可以设环境变量 REVIEW_TOKEN / REVIEW_PASS 供 CI 用（本脚本不会把它打印出来）。

用法：
  py -3.12 review_site.py login
  py -3.12 review_site.py list
  py -3.12 review_site.py init --name 仙戮·双生 --aspect 竖屏 9:16 --shots 镜头表.json
  py -3.12 review_site.py push --pid <id> --shot S07 成片.mp4 --channel 本地H3 --cost 0.6 --dur 15
  py -3.12 review_site.py push --pid <id> --shot S07 成片.mp4 --recode   # 本地压到 4Mbps+faststart 再传
  py -3.12 review_site.py pull --pid <id>          # 待重做清单（含意见正文与时间码）
  py -3.12 review_site.py note --pid <id> --shot S07 --t 6.2 --sev blocker --text "起手慢半拍"
  py -3.12 review_site.py status --pid <id> --shot S07 --to approved
  py -3.12 review_site.py url                       # 打印工作室地址
退出码：0 成功／1 参数或本地文件问题／2 远端失败／3 未登录或 token 过期
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

SITE = os.environ.get("REVIEW_SITE", "https://www.huahuayoueryuan.com")
TOKEN_FILE = r"D:\AIWorkflow\tokens\review_site_token.json"
FFMPEG = r"D:\AIWorkflow\tools\ffmpeg.exe"
FFPROBE = r"D:\AIWorkflow\LivePortrait-main\bin\ffprobe.exe"
PREVIEW_K = "4000k"          # 私有审片预览默认档；D6 裁前不改 review_publish.py
TOKEN_TTL_DAYS = 7


def die(code, msg):
    print(msg)
    sys.exit(code)


# ---------------- 凭证与 token ----------------
def load_token():
    if os.environ.get("REVIEW_TOKEN"):
        return os.environ["REVIEW_TOKEN"].strip(), "env"
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fp:
            d = json.load(fp)
        return d.get("token", ""), TOKEN_FILE
    except Exception:
        return "", ""


def save_token(tok):
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as fp:
        json.dump({"token": tok, "site": SITE, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "expires_hint": time.strftime("%Y-%m-%d", time.localtime(time.time() + TOKEN_TTL_DAYS * 86400))}, fp, ensure_ascii=False, indent=2)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


def api(path, method="GET", body=None, raw=None, tok=None, ctype="application/json", quiet_ok=False):
    h = {}
    if tok:
        h["Authorization"] = "Bearer " + tok
        h["X-Client"] = "cli"          # 让服务端留痕分得开"他手点的"与"脚本跑的"
    data = None
    if raw is not None:
        data = raw
        h["Content-Type"] = "application/octet-stream"
        h["Content-Length"] = str(len(raw))
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = ctype
    req = urllib.request.Request(SITE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            b = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 401 and not quiet_ok:
            die(3, "!! 未登录或 token 过期 ⇒ 先跑 `review_site.py login`（HTTP 401，不回显凭证）")
        txt = e.read().decode("utf-8", "replace")[:400]
        die(2, "!! 远端 HTTP %s：%s" % (e.code, txt))
    except Exception as e:
        die(2, "!! 连不上 %s：%s" % (SITE, type(e).__name__))
    if not b:
        return {}
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        die(2, "!! 返回不是 JSON（可能被 nginx 拦了）：%s" % b[:200])


# ---------------- 媒体探针 ----------------
def probe(path):
    if os.path.isfile(FFPROBE):
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                            "format=duration,bit_rate:stream=width,height,r_frame_rate,codec_type",
                            "-of", "json", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            try:
                j = json.loads(r.stdout or "{}")
            except Exception:
                j = {}
            f = j.get("format", {})
            st = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
            fr = st.get("r_frame_rate") or "30/1"
            try:
                a, bb = fr.split("/")
                fps = round(float(a) / float(bb), 3)
            except Exception:
                fps = 30.0
            dur = float(f.get("duration") or 0)
            br = int(f.get("bit_rate") or 0)
            if not br and dur:
                br = int(os.path.getsize(path) * 8 / dur)
            return {"dur": dur, "bitrate_k": round(br / 1000), "fps": fps,
                    "width": int(st.get("width") or 0), "height": int(st.get("height") or 0)}
    # 兜底：从 ffmpeg -i 的 stderr 里抠 Duration/Stream
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    txt = (r.stderr or "") + (r.stdout or "")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
    dur = 0.0
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    mb = re.search(r"(\d+)x(\d+)", txt)
    fps = 30.0
    fm = re.search(r"(\d+(?:\.\d+)?) fps", txt)
    if fm:
        fps = float(fm.group(1))
    size = os.path.getsize(path)
    return {"dur": dur, "bitrate_k": int(size * 8 / max(dur, 1) / 1000) if dur else 0,
            "fps": fps, "width": int(mb.group(1)) if mb else 0, "height": int(mb.group(2)) if mb else 0}


def recode(src, dst, k=PREVIEW_K):
    """网页预览版：目标码率 + faststart（moov 必须在最前，否则浏览器要拖到文件尾才起播）。"""
    cmd = [FFMPEG, "-y", "-i", src, "-c:v", "libx264", "-preset", "veryfast",
           "-b:v", k, "-maxrate", k, "-bufsize", "2M", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", dst]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        die(2, "!! ffmpeg 压片失败：%s" % (r.stderr or "")[-400:])
    return dst


def moov_first(path):
    """核对 box 顺序：ftyp→moov 必须在 mdat 前，否则 faststart 没生效。"""
    with open(path, "rb") as fp:
        data = fp.read(4000000)
    order = []
    i = 0
    while i + 8 <= len(data):
        size = int.from_bytes(data[i:i + 4], "big")
        typ = data[i + 4:i + 8].decode("latin1")
        if typ not in ("ftyp", "moov", "mdat", "free", "skip", "wide", "uuid"):
            break
        order.append(typ)
        if typ == "mdat":
            break
        i += max(size, 8)
    return order


def make_thumb(src, dst, at):
    t = max(0.0, min(at, 1e6))
    cmd = [FFMPEG, "-y", "-ss", "%.3f" % t, "-i", src, "-frames:v", "1",
           "-vf", "scale=480:-2", "-q:v", "3", dst]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and os.path.isfile(dst)


# ---------------- 子命令 ----------------
def cmd_login(a):
    pw = a.password or os.environ.get("REVIEW_PASS") or getpass.getpass("产品后台口令（输入不回显）：")
    req = urllib.request.Request(SITE + "/api/login", data=json.dumps({"password": pw}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        die(3, "!! 登录被拒（HTTP %s）。口令不对或被限流，脚本不打印任何凭证。" % e.code)
    except Exception as e:
        die(2, "!! 连不上 %s：%s" % (SITE, type(e).__name__))
    if not j.get("ok"):
        die(3, "!! 登录失败（服务端给了否定应答，不回显原因里的敏感内容）")
    save_token(j["token"])
    print("✓ 已登录，token 存到 %s（约 %d 天内有效，过期重跑 login）" % (TOKEN_FILE, TOKEN_TTL_DAYS))
    print("  工作室：%s/studio" % SITE)


def cmd_url(a):
    tok, src = load_token()
    print("工作室：%s/studio" % SITE)
    print("token：%s" % ("已在位（来源 %s）" % src if tok else "无 ⇒ 先跑 login"))


def cmd_list(a):
    tok, _ = load_token()
    if not tok:
        die(3, "未登录：先跑 review_site.py login")
    d = api("/api/review/projects", tok=tok)
    if not d.get("projects"):
        print("（还没有项目）")
        return
    for p in d["projects"]:
        c = p["counts"]
        print("%-10s %-26s %3d 镜 / %3d 版  通过%s 待审%s 打回%s  阻塞%s  更新%s"
              % (p["id"], p["name"][:26], c["shots"], c["versions"],
                 c["by_status"].get("approved", 0) + c["by_status"].get("delivered", 0),
                 c["by_status"].get("submitted", 0), c["by_status"].get("flagged", 0),
                 c["open_blockers"], p.get("updatedAt", "")))
    print("\n工作室：%s/studio" % SITE)


def cmd_init(a):
    tok, _ = load_token()
    if not tok:
        die(3, "未登录：先跑 review_site.py login")
    shots = []
    if a.shots:
        raw = json.load(open(a.shots, encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("shots", [])
        for i, s in enumerate(raw, 1):
            shots.append({"no": s.get("no", i), "sb": s.get("sb", ""), "seg": s.get("seg", "未分段"),
                          "title": s.get("title", ""), "dur": s.get("dur", 0),
                          "channel": s.get("channel", ""), "cost": s.get("cost", 0),
                          "prompt_ref": s.get("prompt_ref", ""),
                          "key": s.get("key") or s.get("sb") or ("S%02d" % int(s.get("no", i)))})
    if a.file:
        die(1, "!! --file（从生产账本直接读）本批未接，别替你猜字段；先用 --shots 给镜头表")
    d = api("/api/review/project", method="POST", tok=tok,
            body={"name": a.name, "aspect": a.aspect, "note": a.note, "shots": shots})
    proj = d["project"]
    print("✓ 项目已建：%s（pid=%s，%d 镜）" % (proj["name"], proj["id"], len(proj["shots"])))
    print("  工作室：%s/studio" % SITE)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fp:
            json.dump({"pid": proj["id"], "name": proj["name"], "shots": [s["key"] for s in proj["shots"]]}, fp, ensure_ascii=False, indent=2)
        print("  pid 已写到 %s" % a.out)


def cmd_push(a):
    tok, _ = load_token()
    if not tok:
        die(3, "未登录：先跑 review_site.py login")
    src = os.path.abspath(a.file)
    if not os.path.isfile(src):
        die(1, "!! 文件不存在：%s" % src)
    meta = probe(src)
    dur = a.dur or meta["dur"]
    print("   源：%s  %.1f MB  %.1fs  %skbps  %sx%s  %.2ffps"
          % (os.path.basename(src), os.path.getsize(src) / 1048576.0, meta["dur"],
             meta["bitrate_k"], meta["width"], meta["height"], meta["fps"]))
    up_file = src
    tmpdir = os.path.join(os.environ.get("TEMP", "."), "review_site_push")
    os.makedirs(tmpdir, exist_ok=True)
    if a.recode:
        up_file = os.path.join(tmpdir, os.path.splitext(os.path.basename(src))[0] + "_prev.mp4")
        print("   压预览版 %s …" % (a.bitrate_k or PREVIEW_K))
        recode(src, up_file, "%dk" % int(a.bitrate_k or int(PREVIEW_K.rstrip("k"))))
        meta = probe(up_file)          # 记账要用**实际上传那版**的码率/尺寸，不是源片
        up_meta = meta
        order = moov_first(up_file)
        if "moov" not in order[:2]:
            die(2, "!! faststart 没生效（box 顺序 %s）⇒ 不上传，先修编码" % order)
        print("   预览版：%.1f MB  %skbps  box 顺序 %s"
              % (os.path.getsize(up_file) / 1048576.0, up_meta["bitrate_k"], "->".join(order)))
    elif not a.no_check:
        order = moov_first(src)
        if src.lower().endswith((".mp4", ".mov")) and "moov" in order and order.index("moov") > 1:
            print("   ⚠ moov 不在前面（%s），网页会像卡在加载——建议加 --recode 或先 -movflags +faststart" % "->".join(order))

    ver = a.ver or 0
    qs = {"shot": a.shot, "ver": ver, "dur": round(dur, 3), "fps": meta["fps"],
          "bitrate_k": a.bitrate_k or meta["bitrate_k"], "width": meta["width"], "height": meta["height"],
          "channel": a.channel or "", "cost": a.cost or 0, "prompt_ref": a.prompt_ref or "", "gates": a.gates or ""}
    q = urllib.parse.urlencode({k: v for k, v in qs.items() if v not in (0, "", None) or k == "cost"})
    data = open(up_file, "rb").read()
    if a.dry_run:
        print("[dry-run] 将 PUT /api/review/project/%s/media?%s  （%d 字节，不联网）" % (a.pid, q, len(data)))
        return
    d = api("/api/review/project/%s/media?%s" % (a.pid, q), method="PUT", raw=data, tok=tok)
    print("✓ 版本已挂上：%s（%d 字节）" % (d["url"], d["bytes"]))

    # 首帧缩略：取全片 1/3 处（开头常是黑场/淡入，抽中间更认得出镜头）
    tpath = os.path.join(tmpdir, "%s_thumb.jpg" % a.shot)
    if make_thumb(up_file, tpath, dur / 3.0):
        tdata = open(tpath, "rb").read()
        api("/api/review/project/%s/media?%s" % (a.pid, urllib.parse.urlencode({"shot": a.shot, "kind": "thumb"})),
            method="PUT", raw=tdata, tok=tok)
        print("✓ 首帧缩略已上传（取自 %.1fs 处）" % (dur / 3.0))
    else:
        print("  ! 缩略图没抽出来（卡片会显示占位），不影响播放")
    print("  画布：%s/studio" % SITE)


def cmd_pull(a):
    tok, _ = load_token()
    if not tok:
        die(3, "未登录：先跑 review_site.py login")
    d = api("/api/review/todo?pid=" + a.pid, tok=tok)
    items = d["items"]
    if not items:
        print("✓ 待重做清单为空（%s）" % d["project"])
        return
    lines = ["# 待重做清单 · %s（%s 生成，pid=%s）" % (d["project"], time.strftime("%Y-%m-%d %H:%M"), d["pid"]),
             "", "共 %d 个镜头被打回。按镜号单镜重渲，不整批重跑。" % len(items), ""]
    for it in items:
        lines.append("## %s（分镜表 %s）· %s · %ss · 渠道 %s · 当前 v%s · 状态 %s"
                     % (it["no"] or it["key"], it.get("sb") or "-", it.get("seg") or "-", it.get("dur") or "?",
                        it.get("channel") or "-", it.get("current_version") or "无", it["status"]))
        for b in it["blockers"]:
            lines.append("  - [%s] @%s %s ｜ %s%s" % (b["id"], _fmt(b["t"]), b["type"], b["text"],
                                                      ("（判据 " + b["rule_ref"] + "）") if b.get("rule_ref") else ""))
        lines.append("")
    txt = "\n".join(lines)
    print(txt)
    out = a.out or os.path.join(os.getcwd(), "待重做清单_%s.md" % a.pid)
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(txt)
    print("已写到 %s" % out)


def _fmt(t):
    m = int(t // 60)
    return "%d:%04.1f" % (m, t - m * 60)


def cmd_note(a):
    tok, _ = load_token()
    d = api("/api/review/project/%s/comment" % a.pid, method="POST", tok=tok,
            body={"shot": a.shot, "t": a.t, "type": a.type, "severity": a.sev, "text": a.text, "rule_ref": a.rule})
    print("✓ 意见已记：%s @%s [%s]（%s）" % (d["comment"]["shot"], _fmt(a.t), d["comment"]["severity"], d["comment"]["id"]))


def cmd_status(a):
    tok, _ = load_token()
    d = api("/api/review/project/%s/status" % a.pid, method="POST", tok=tok,
            body={"shots": a.shot.split(","), "to": a.to, "reason": a.reason})
    if d["changed"]:
        print("✓ 已改：", ", ".join("%s %s→%s" % (c["shot"], c["from"], c["to"]) for c in d["changed"]))
    for r in d["rejected"]:
        print("!! 被拦：%s（%s）" % (r.get("shot"), r.get("reason") or "%d 条阻塞级意见未解决" % r["blockers"]))
    if not d["changed"]:
        sys.exit(1)


def cmd_resolve(a):
    tok, _ = load_token()
    api("/api/review/project/%s/comment/resolve" % a.pid, method="POST", tok=tok,
        body={"id": a.id, "reason": a.reason})
    print("✓ 意见 %s 已标解决" % a.id)


def cmd_flow(a):
    tok, _ = load_token()
    d = api("/api/review/flow", tok=tok)
    f = d["flow"]
    if a.set_states:
        states = json.load(open(a.set_states, encoding="utf-8"))
        f = api("/api/review/flow", method="PUT", tok=tok, body={"states": states})["flow"]
        print("✓ 状态机词表已更新（改的是 flow.json，不动代码）")
    print("状态档：", " / ".join("%s(%s)" % (s["label"], s["key"]) for s in f["states"]))
    print("意见类型：", " ".join(f["comment_types"]))
    print("严重度：", " ".join("%s(%s)" % (x["label"], x["key"]) for x in f["severity"]))


def _vis(a, to):
    """把某个版本公开到放映厅（或撤回）。服务端有闸：未通过的镜头置 public 会被 403 拒。"""
    tok, _ = load_token()
    ver = a.ver
    if not ver:
        d = api("/api/review/project/" + a.pid, tok=tok)
        s = [x for x in d["project"]["shots"] if x["key"] == a.shot][0]
        vids = [v for v in (s.get("versions") or []) if v.get("kind") != "thumb"]
        if not vids:
            die(1, "!! %s 还没有可播版本" % a.shot)
        ver = vids[-1]["ver"]
    d = api("/api/review/project/%s/visibility" % a.pid, method="POST", tok=tok,
            body={"shot": a.shot, "ver": ver, "to": to, "reason": "本地脚本"})
    print("✓ %s v%s 可见性 → %s（放映厅当前 %d 条）" % (a.shot, ver, to, d["show_items"]))


def cmd_report(a):
    tok, _ = load_token()
    d = api("/api/review/report?pid=" + a.pid, tok=tok)
    out = a.out or os.path.join(os.getcwd(), "审片报告_%s.md" % a.pid)
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(d["markdown"])
    nl = chr(10)
    print("✓ 报告 %d 行 / %d 条意见 / %d 条留痕 → %s"
          % (d["markdown"].count(nl) + 1, d["comments"], d["events"], out))


def cmd_node(a):
    """把角色/场景/参考图钉到画布上（图按原样上传，服务器不转码）。"""
    tok, _ = load_token()
    if not os.path.isfile(a.file):
        die(1, "!! 图不存在：%s" % a.file)
    raw = open(a.file, "rb").read()
    if len(raw) > 4 * 1048576:
        die(1, "!! 图 %d MB 超 4MB 上限，先在本地缩" % (len(raw) / 1048576))
    ext = os.path.splitext(a.file)[1].lower()
    mime = "data:image/png;base64," if ext == ".png" else "data:image/jpeg;base64,"
    d = api("/api/review/project/%s/node" % a.pid, method="POST", tok=tok,
            body={"title": a.title or os.path.basename(a.file), "kind": a.kind,
                  "note": a.note, "image": mime + base64.b64encode(raw).decode()})
    print("✓ 辅助节点已钉上：%s → %s" % (d["node"]["title"], d["node"]["img"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("login"); p.add_argument("--password", default=""); p.set_defaults(f=cmd_login)
    p = sub.add_parser("url"); p.set_defaults(f=cmd_url)
    p = sub.add_parser("list"); p.set_defaults(f=cmd_list)
    p = sub.add_parser("init")
    p.add_argument("--name", required=True); p.add_argument("--aspect", default="竖屏 9:16")
    p.add_argument("--note", default=""); p.add_argument("--shots", default="", help="镜头表 JSON（数组或 {shots:[...]}）")
    p.add_argument("--file", default="", help="预留：从生产账本读（本批未接）")
    p.add_argument("--out", default="", help="把 pid 写到这个文件")
    p.set_defaults(f=cmd_init)
    p = sub.add_parser("push")
    p.add_argument("file"); p.add_argument("--pid", required=True); p.add_argument("--shot", required=True)
    p.add_argument("--ver", type=int, default=0); p.add_argument("--dur", type=float, default=0)
    p.add_argument("--channel", default=""); p.add_argument("--cost", type=float, default=0)
    p.add_argument("--prompt-ref", dest="prompt_ref", default=""); p.add_argument("--gates", default="")
    p.add_argument("--bitrate-k", dest="bitrate_k", type=int, default=0)
    p.add_argument("--recode", action="store_true", help="本地压预览版（含 faststart 校验）再传")
    p.add_argument("--no-check", dest="no_check", action="store_true", help="跳过 moov 顺序检查")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p.set_defaults(f=cmd_push)
    p = sub.add_parser("pull"); p.add_argument("--pid", required=True); p.add_argument("--out", default="")
    p.set_defaults(f=cmd_pull)
    p = sub.add_parser("note")
    p.add_argument("--pid", required=True); p.add_argument("--shot", required=True)
    p.add_argument("--t", type=float, default=0.0); p.add_argument("--type", default="其他")
    p.add_argument("--sev", default="advice"); p.add_argument("--text", required=True)
    p.add_argument("--rule", default="")
    p.set_defaults(f=cmd_note)
    p = sub.add_parser("status")
    p.add_argument("--pid", required=True); p.add_argument("--shot", required=True, help="逗号分隔可批量")
    p.add_argument("--to", required=True); p.add_argument("--reason", default="")
    p.set_defaults(f=cmd_status)
    p = sub.add_parser("resolve")
    p.add_argument("--pid", required=True); p.add_argument("--id", required=True); p.add_argument("--reason", default="本地脚本标解决")
    p.set_defaults(f=cmd_resolve)
    p = sub.add_parser("publish"); p.add_argument("--pid", required=True)
    p.add_argument("--shot", required=True); p.add_argument("--ver", type=int, default=0)
    p.set_defaults(f=lambda a: _vis(a, "public"))
    p = sub.add_parser("unpublish"); p.add_argument("--pid", required=True)
    p.add_argument("--shot", required=True); p.add_argument("--ver", type=int, default=0)
    p.set_defaults(f=lambda a: _vis(a, "private"))
    p = sub.add_parser("report"); p.add_argument("--pid", required=True); p.add_argument("--out", default="")
    p.set_defaults(f=cmd_report)
    p = sub.add_parser("node"); p.add_argument("--pid", required=True); p.add_argument("file")
    p.add_argument("--title", default=""); p.add_argument("--kind", default="ref")
    p.add_argument("--note", default="")
    p.set_defaults(f=cmd_node)
    p = sub.add_parser("flow"); p.add_argument("--set-states", dest="set_states", default="")
    p.set_defaults(f=cmd_flow)

    a = ap.parse_args(argv)
    a.f(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
