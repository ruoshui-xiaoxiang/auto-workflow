# -*- coding: utf-8 -*-
r"""jimeng_client.py · 即梦（dreamina-canvas CLI）的**唯一**客户端（2026-10-19 第⑤条，用户裁『接，先做最小可用版』）。

为什么要有这个文件
------------------
即梦此前**根本不在 engine 里**：盘上 17 份 wrapper 各自 subprocess 调 CLI，
并发/断点/重试/保序各写一遍——这正是「同一个能力散在多处、每个 agent 用法不一样」的图像侧版本。
本模块只解决三件事：① 开批前能问一次可用性（`probe`，不跑到第三张才发现授权过期）
② 提交与下载（`generate`，内置三个实测踩过的坑）③ **参考图槽位与 `--ref` 顺序逐位绑定由代码保证**。

CLI 契约全部来自本机 `--help` 与 `model list` 的**实测返回**（2026-10-19 12:30），不是猜的：
  auth status                → {loggedIn, expiresAt, profile, region, version}
  model list --type image    → items[].modes[].{name, flags[], references{min,max}}
  resource upload --file --project-id [--resource-id 幂等键]
  node create image --mode --model --ratio --resolution --count --prompt [--ref ...] --run --wait
                               --credit-ceiling N --format json --non-interactive
  resource download <res-id> -o <path|dir>
🔴 `--ref` 只收 `node:` / `res:` / `uri:` / `vid:` 四种前缀——**没有 `file:`**。
   老 wrapper 里写的 `--ref file:{绝对路径}` 是不成立的形态（它自己的注释也写着「may need res: after upload」），
   所以本地素材必须先 `resource upload` 换 resourceId，再按顺序传 `--ref res:<id>`。

错误码（不许自动回落，一律抛出去让人决定）
------------------------------------------
JM_CLI   CLI 不在位                      JM_AUTH  未登录/授权过期（附 expiresAt 与重登命令）
JM_MODEL 模型或档位不可调用               JM_SPEC  参数超出 model list 的允许域（本地就拦，不消耗一次生成）
JM_CREDIT 报价超 credit-ceiling           JM_EMPTY_ID 返回里没有 resourceId（重试后仍空）
JM_DL    下载失败                         JM_NET / JM_UNKNOWN
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

DEFAULT_CLI = r"C:\Users\若水\bin\dreamina-canvas.exe"
DEFAULT_MODEL = "seedream_5.0_lite"      # 用户默认档：实测 creditsAmount=0（免费）
TIMEOUT_SUBMIT = 900                      # --run --wait 会等生成进终态


class JimengError(RuntimeError):
    def __init__(self, code, msg, hint=""):
        super().__init__("[%s] %s%s" % (code, msg, (" ⇒ " + hint) if hint else ""))
        self.code = code
        self.hint = hint


def cli_path(cfg=None):
    p = str(((cfg or {}).get("jimeng") or {}).get("cli") or DEFAULT_CLI)
    if not Path(p).is_file():
        raise JimengError("JM_CLI", "即梦 CLI 不在位：%s" % p,
                          "确认装过 dreamina-canvas；或 config.yaml 里写 jimeng.cli 指到实际路径")
    return p


def _run(cli, args, timeout=180, parse=True):
    """跑一次 CLI。返回 (dict|str, 原始文本)。非零退出也带 JSON 错误体，交给调用方判。"""
    cmd = [cli] + args + ["--format", "json", "--non-interactive"]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if not parse:
        return out, out
    data = None
    i = out.find("{")
    if i >= 0:
        try:
            data, _ = json.JSONDecoder().raw_decode(out, i)
        except ValueError:
            data = None
    return data, out


def _err_of(data):
    """取 (code, message)。⚠ 只返回两个值——第一版返回四元组，
    而 `generate` 里按两元组解包 ⇒ 一旦 CLI 报错就先炸 ValueError，把真错误码盖掉。
    2026-10-19 接线实测踩到，故收敛成固定二元组。

    ★ 同日 17:40 二次修：**把 `error.validation` 拼进 message**。
    起因：`resource upload` 空 project-id 时 CLI 明明白白回了
    `reasonCode=CLI_INPUT_REQUIRED / fieldPath=project-id`，而我这里只取 message
    ⇒ 上层看到一句"Invalid command input"，我据此**误判成中文路径问题**并改错了地方。
    丢掉结构化字段＝把可定位的错变成猜。"""
    e = (data or {}).get("error") or {}
    msg = e.get("message") or ""
    v = e.get("validation") or {}
    if isinstance(v, dict) and v:
        bits = "; ".join("%s=%s" % (k, v[k]) for k in
                         ("reasonCode", "fieldPath", "detail") if v.get(k))
        msg = "%s ｜validation: %s" % (msg, bits)
    return (e.get("code") or "JM_UNKNOWN", msg)


# ───────────────────────────────────────────────────────────── probe（只读）
def probe(cfg=None, model=None):
    """开批前问一次：能不能用、这个档能不能用、允许域是什么。**不提交任何东西。**"""
    model = model or DEFAULT_MODEL
    out = {"model": model, "ok": False, "reason_code": "", "detail": "", "caps": {}}
    try:
        cli = cli_path(cfg)
    except JimengError as e:
        out.update(reason_code=e.code, detail=str(e))
        return out
    out["cli"] = cli
    d, raw = _run(cli, ["auth", "status"], timeout=60)
    if not isinstance(d, dict) or not d.get("ok"):
        code, msg = _err_of(d)
        out.update(reason_code="JM_AUTH", detail="auth status 失败：%s %s" % (code, msg))
        return out
    a = d.get("data") or {}
    out["logged_in"] = bool(a.get("loggedIn"))
    out["expires_at"] = a.get("expiresAt") or ""
    if not out["logged_in"]:
        out.update(reason_code="JM_AUTH",
                   detail="未登录或授权已过期（expiresAt=%s）" % out["expires_at"],
                   hint="本人跑 `dreamina-canvas auth login` 走 OAuth（实测 6 小时要重点一次）")
        return out
    d2, raw2 = _run(cli, ["model", "list", "--type", "image"], timeout=90)
    if not isinstance(d2, dict) or not d2.get("ok"):
        code, msg = _err_of(d2)
        out.update(reason_code="JM_NET" if "network" in code or "timeout" in code else "JM_MODEL",
                   detail="model list 失败：%s %s" % (code, msg))
        return out
    found = None
    for it in (d2.get("data") or {}).get("items") or []:
        if it.get("model") == model:
            found = it
            break
    if not found:
        out.update(reason_code="JM_MODEL",
                   detail="账号下查不到模型 %s ⇒ 停，等你裁（不许自动降档：实测 4.7 档锁脸 0.76→0.63 且要花钱）" % model,
                   hint="可跑 `dreamina-canvas model list --type image` 看现有档")
        return out
    caps = {}
    for m in found.get("modes") or []:
        flags = {f.get("flag"): f for f in (m.get("flags") or [])}
        caps[m.get("name")] = {
            "refs_min": (m.get("references") or {}).get("min", 0),
            "refs_max": (m.get("references") or {}).get("max", 0),
            "ratio": (flags.get("--ratio") or {}).get("values") or [],
            "ratio_required": bool((flags.get("--ratio") or {}).get("required")),
            "resolution": (flags.get("--resolution") or {}).get("values") or [],
            "count_max": (flags.get("--count") or {}).get("max", 1),
        }
    out.update(ok=True, caps=caps, reason_code="", detail="可用")
    return out


# ─────────────────────────────────────────────────────────── 参数本地预检
def check_spec(caps, mode, ratio, resolution, count, n_refs):
    """按 `model list` 的允许域**在本地**拦，不消耗一次生成机会（JM_SPEC）。"""
    c = (caps or {}).get(mode)
    if not c:
        raise JimengError("JM_SPEC", "模型档 %s 没有 %s 模式（可用：%s）"
                          % (DEFAULT_MODEL, mode, list((caps or {}).keys())))
    if not (c["refs_min"] <= n_refs <= c["refs_max"]):
        raise JimengError("JM_SPEC", "%s 模式要求参考图 %d~%d 张，本次给了 %d 张"
                          % (mode, c["refs_min"], c["refs_max"], n_refs))
    if c["ratio_required"] and not ratio:
        raise JimengError("JM_SPEC", "该档 %s 模式必须给 --ratio（可选 %s）" % (mode, c["ratio"]))
    if ratio and c["ratio"] and ratio not in c["ratio"]:
        raise JimengError("JM_SPEC", "ratio=%s 不在允许域 %s" % (ratio, c["ratio"]))
    if resolution and c["resolution"] and resolution not in c["resolution"]:
        raise JimengError("JM_SPEC", "resolution=%s 不在允许域 %s" % (resolution, c["resolution"]))
    if count > c["count_max"]:
        raise JimengError("JM_SPEC", "count=%d 超上限 %d" % (count, c["count_max"]))
    return True


# ───────────────────────────────────────────────────────────── 上传素材
def upload(cfg, file_path, project_id):
    """本地文件 → 项目资源，返回 resourceId。

    幂等键用**文件内容 md5**派生：CLI 文档明写「省略时自动生成，跨进程重试须复用同一值」
    ⇒ 同一张锚点图重复上传不会在画布里堆出 N 份副本。

    ⚠ 2026-10-19 17:38 实测两条边界：
      ① **中文路径没问题**（`E:\\图像影音资源池\\HM860发布会\\素材\\主持人形象_….jpg` 上传成功，
         拿到 `5811a42c-95ab-4aea-b7b0-34ce0d905ba8`）。我一度判成"CLI 吃不了非 ASCII 路径"，
         那是**因为报错里丢了 validation 字段**才猜错的，已修 `_err_of`；当时顺手加的
         ASCII 暂存副本逻辑已撤——建立在假前提上的代码比没代码更坏（它会把素材悄悄复制到别处）。
      ② `--project-id` **必填且不能是空串**（CLI 回 `CLI_INPUT_REQUIRED / fieldPath=project-id`）
         ⇒ 空值在本地就拒，并说清怎么给。
    """
    p = Path(file_path)
    if not p.is_file():
        raise JimengError("JM_SPEC", "要上传的文件不存在：%s" % p)
    if not str(project_id or "").strip():
        raise JimengError(
            "JM_SPEC",
            "resource upload 缺 project-id（CLI 实测：CLI_INPUT_REQUIRED / fieldPath=project-id）。\n"
            "   两条给法：① 本批临时——`--set project_id=<画布UUID>`；\n"
            "   ② 长期——在 config.yaml 末尾追加 `jimeng: {project_id: <画布UUID>}`（该文件有行号锚，只能追加）。")
    # 幂等键必须是**合法 UUID**（实测：`res-<hex>` 这种自造前缀被 CLI 判
    # `cli.invalid_command`，与 project-id 那次同一类错）。用 uuid5 从文件内容派生：
    # 同一张图重复上传得到同一个 id ⇒ 跨进程重试复用、画布里不堆副本。
    # ⚠ 10-19 17:43 二次修：**键要按画布分开**。原来只用内容 md5 ⇒ 同一张锚点图
    #    传过 A 画布后再传 B 画布，服务端回 `service.5 / This request was already submitted`
    #    （实测：主持人形象先传进 `engine接线验证_20261019`，再传 `HM860发布会_关键帧` 就撞了）。
    #    ⇒ 种子改成 `project_id + md5`：同画布重试仍幂等，跨画布各留一份合法登记。
    rid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                         "jimeng-anchor:%s:%s" % (str(project_id).strip(),
                                                  hashlib.md5(p.read_bytes()).hexdigest())))
    cli = cli_path(cfg)
    args = ["resource", "upload", "--file", str(p), "--project-id", str(project_id),
            "--resource-id", rid]
    d, raw = _run(cli, args, timeout=300)
    if not isinstance(d, dict) or not d.get("ok"):
        code, msg = _err_of(d)
        raise JimengError("JM_NET" if "network" in code else code, "上传失败：%s" % msg)
    got = ((d.get("data") or {}).get("resourceId")
           or (d.get("data") or {}).get("id") or rid)
    return str(got)


# ───────────────────────────────────────────────────────────── 生成
def generate(cfg, prompt, mode="t2i", refs=None, ratio=None, resolution="2K",
             count=1, out_dir=None, title="jimeng", model=None, project_id=None,
             credit_ceiling=0, dry=False, log=lambda m: None):
    """提交一次即梦生成并把产物落到 out_dir。返回 {files, refs_bound, raw}。

    refs 是**有序**列表，元素可以是本地路径（自动 upload）或 `res:<id>`/裸 id。
    🔴 槽位 1..N 与 `--ref` 的出现顺序逐位绑定由这里保证，不靠人手数——
       参考图传反把女1的脸安到 B 侧是 2026 年真发生过的事故。
    """
    model = model or DEFAULT_MODEL
    refs = [str(x) for x in (refs or [])]
    out = {"files": [], "refs_bound": [], "model": model, "mode": mode,
           "credit_ceiling": credit_ceiling, "dry": bool(dry)}
    cli = cli_path(cfg)
    pr = probe(cfg, model=model)
    if not pr["ok"]:
        raise JimengError(pr["reason_code"] or "JM_UNKNOWN",
                          "即梦不可用：%s %s" % (pr["detail"], pr.get("hint") or ""),
                          hint="按规矩**不许自动回落本地出图**，要换本地得你先同意（授权是批级）")
    check_spec(pr["caps"], mode, ratio, resolution, count, len(refs))

    for i, r in enumerate(refs, 1):
        if r.startswith(("node:", "res:", "uri:", "vid:")):
            rid = r
        elif Path(r).is_file():
            rid = "res:" + upload(cfg, r, project_id)
            log("[jimeng] 参考图 %d 上传 → %s" % (i, rid))
        else:
            rid = "res:" + r
        out["refs_bound"].append({"slot": i, "input": r, "ref": rid})

    args = ["node", "create", "image", "--mode", mode, "--model", model,
            "--resolution", resolution, "--count", str(count), "--prompt", prompt,
            "--title", title]
    if project_id:
        args += ["--project-id", str(project_id)]
    if ratio:
        args += ["--ratio", ratio]
    for b in out["refs_bound"]:
        args += ["--ref", b["ref"]]
    if dry:
        d, raw = _run(cli, args + ["--dry-run"], timeout=180)
        out["dry_plan"] = raw[:1500]
        return out
    d, raw = _run(cli, args + ["--run", "--wait", "--credit-ceiling", str(credit_ceiling), "--yes"],
                  timeout=TIMEOUT_SUBMIT)
    if not isinstance(d, dict) or not d.get("ok"):
        code, msg = _err_of(d)
        if "credit" in code.lower():
            raise JimengError("JM_CREDIT", "报价超过 credit-ceiling=%d：%s" % (credit_ceiling, msg),
                              hint="确认要花钱就抬 --credit-ceiling，别偷偷降档")
        raise JimengError(code or "JM_UNKNOWN", "生成失败：%s" % msg)
    data = d.get("data") or {}
    # 🔴 产物号在 `data.submission.resources[].resourceId`，**不在 `data.node.resources`**
    #   （实测：node.status 一直是 "empty"、node.resources=[]，而 submission.state=succeeded
    #    且 resources[0].state=succeeded）。第一版只找 node 那层 ⇒ 明明出图了却报 JM_EMPTY_ID。
    sub = data.get("submission") or {}
    out["submission_state"] = sub.get("state")
    out["quote"] = data.get("quote") or {}
    res_list = [r for r in (sub.get("resources") or []) if isinstance(r, dict)]
    ids = [str(r.get("resourceId")) for r in res_list
           if r.get("resourceId") and str(r.get("state", "succeeded")) == "succeeded"]
    out["resource_states"] = [{"id": str(r.get("resourceId")), "state": r.get("state")}
                              for r in res_list]
    if not ids:
        ids = [str(x) for x in (data.get("resourceIds") or []) if x]
    if not ids:
        # 坑②：submission 里没有成功态的 resourceId ⇒ 明确报错，**不瞎猜别的字段、不自动重跑生成**
        raise JimengError("JM_EMPTY_ID",
                          "submission.state=%s，resource_states=%s，quote=%s ⇒ 没拿到成功产物号。"
                          "原始返回：%s" % (sub.get("state"), out["resource_states"],
                                          out.get("quote"), raw[:500]))
    if not ids:
        raise JimengError("JM_EMPTY_ID", "生成返回里没有 resourceId ⇒ 产物没落地，原始返回：%s"
                          % raw[:400])
    out["resource_ids"] = ids
    out_dir = Path(out_dir or ".")
    out_dir.mkdir(parents=True, exist_ok=True)
    for n, rid in enumerate(ids, 1):
        dst = out_dir / ("%s_%02d.png" % (title, n))
        if dst.exists():
            dst.unlink()          # 坑①：CLI 见目标已存在会**静默跳过下载**，先删
        _, draw = _run(cli, ["resource", "download", rid, "-o", str(dst),
                             "--project-id", str(project_id)] if project_id
                       else ["resource", "download", rid, "-o", str(dst)], timeout=300)
        if not dst.is_file() or dst.stat().st_size < 1024:
            raise JimengError("JM_DL", "下载后文件不对：%s（%s）"
                              % (dst, (draw or "")[-200:]))
        out["files"].append(str(dst))
        log("[jimeng] 已落 %s（%d 字节）" % (dst.name, dst.stat().st_size))
    return out
