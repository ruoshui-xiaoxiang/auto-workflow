# -*- coding: utf-8 -*-
"""auto-workflow 引擎入口。

用法:
  python run.py <workflow> [--set key=value ...]
  python run.py --list

一个工作流 = workflows\\ 下一个 YAML；任务类型在 tasks.py 注册。
新增工作流只需新增 YAML，不改引擎代码。
"""
import argparse
import hashlib
import html as _html
import json
import os
import re
import sys
import time
import traceback
import uuid
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from tasks import (REGISTRY, GateAwaiting, GateDenied, list_pending,  # noqa: E402
                   read_approvals, record_approval)
import tasks  # noqa: E402  W5b：--cancel / --adopt 要用 cancel_submission / adopt_late_output
import tasks_image_gen  # noqa: E402,F401  注册 `task: image`（即梦/本地图源，2026-10-19 第⑤条）
                        # 只要 import 就会把 image 挂进 REGISTRY；不 import 的话 YAML 里写
                        # `task: image` 会得到"未知任务类型"，而那看起来像 YAML 写错了。
from delivery_root import delivery_root  # noqa: E402  交付根的唯一推导处（10-02 批1 GAP-E1）
import run_plan  # noqa: E402  W1：RunPlan 纯解析器（只解析不提交）
import task_state  # noqa: E402  S1：来源/依赖绑定与 resume 失效判定

PLACE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def dig(ctx, path):
    cur = ctx
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def render(obj, ctx, strict=True):
    """把 {{args.x}} / {{step_id.field}} / {{run_id}} / {{cfg.*}} 渲染成实际值。

    整串恰好是一个占位符时保留原始类型（int/bool 等），混排时转字符串。
    strict=True 时占位符解析为 None 直接报错 —— 否则会把 "None" 当内容
    喂给模型（历史上真出过用字面量 "None" 当提示词出图的事故）。
    """
    if isinstance(obj, str):
        m = PLACE.fullmatch(obj.strip())
        if m:
            v = dig(ctx, m.group(1))
            if v is None and strict:
                raise ValueError(f"占位符 {{{{{m.group(1)}}}}} 解析为空："
                                 f"检查 YAML 是否声明了该 args，或上游步骤 id 拼写")
            return v

        def _sub(mm):
            v = dig(ctx, mm.group(1))
            if v is None and strict:
                raise ValueError(f"占位符 {{{{{mm.group(1)}}}}} 解析为空")
            return "" if v is None else str(v)

        return PLACE.sub(_sub, obj)
    if isinstance(obj, list):
        return [render(x, ctx, strict) for x in obj]
    if isinstance(obj, dict):
        return {k: render(v, ctx, strict) for k, v in obj.items()}
    return obj


def auto_cast(v):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    # Python 的 int()/float() 把下划线当数字分隔符（int("1_2")==12），
    # 会把 run_id 形如 20260903_033032 的值吃掉下划线，故含下划线一律不转数字
    if "_" not in v:
        for cast in (int, float):
            try:
                return cast(v)
            except ValueError:
                pass
    return v


def _load_cfg():
    """全局 config 的唯一读取口（main() 内三处共用）。

    测试隔离（W0）：环境变量 AW_CONFIG_PATH 存在时改读它指向的隔离副本——
    engine/tests/conftest.py 跑测试时把它指到 session tmp 里的 config，
    status/审批/落点全在 tmp，真跑 run.py 的子进程也走这一条，不碰真台账。
    生产运行不设这个变量，读的仍是引擎自带 config.yaml，唯一真源不变。
    """
    override = os.environ.get("AW_CONFIG_PATH")
    src = Path(override) if override else (ROOT / "config.yaml")
    return yaml.safe_load(src.read_text(encoding="utf-8"))


RETIRED_KEY = "_已退役"


def load_workflow(path):
    """工作流 YAML 的**唯一加载入口**（与 `tasks.load_template()` 同一族规矩）。

    读到退役桩就停下把原因、替代命令、恢复步骤打全，**不许调用方自己猜**——
    「拿到 FileNotFoundError 就换一条像的」正是『每个 agent 用法都不一样』的成因。
    桩的形状：顶层 `retired: true` ＋ `_已退役`／`_原因`／`_替代`／`_恢复` 四段说明。
    """
    wf = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if str(wf.get("retired", "")).lower() in ("true", "yes", "1"):
        msg = ("[工作流已退役] %s\n%s\n⇒ 原因： %s\n⇒ 替代： %s\n⇒ 要恢复： %s"
               % (Path(path).name, wf.get(RETIRED_KEY, ""), wf.get("_原因", "未写"),
                  wf.get("_替代", "未写"), wf.get("_恢复", "未写")))
        # 退出码 78＝EX_CONFIG：调用方/脚本要靠它区分"路封了"和"这次跑崩了"。
        # 这是本仓退役桩的硬约定（tools/_路障桩模板.py、官方路径.json 的 deprecated._note）。
        print(msg, file=sys.stderr)
        raise SystemExit(78)
    return wf


class Logger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def rel_src(image_path, report_path):
    """报告里引图一律用相对路径，基准是报告自己所在的批次夹。
    绝对路径（含 file: URI）会让文件夹一拷走就全线裂图，自包含就不成立。
    反斜杠必须转成 /：Windows 浏览器对 file:// 页里的 \\ 相对路径处理不一致。"""
    return os.path.relpath(str(image_path), Path(report_path).parent).replace("\\", "/")


DEFAULT_LABELS = {"llm": "润色 / 生成提示词", "comfyui": "出图",
                  "video": "出视频", "gate": "关口",
                  "files": "整理 / 归档文件", "shell": "执行命令"}
TASK_HINTS = {"llm": "把主题改写成模型听得懂的提示词",
              "comfyui": "调用 ComfyUI 生成图片",
              "video": "调用 ComfyUI 生成视频（提交前先过跑前自审闸）",
              "gate": "auto=机制自审；human=发飞书等你回话才继续",
              "files": "把产物复制到归档目录",
              "shell": "跑一条命令行"}
CONTROL_KEYS = ("task", "id", "label", "hint", "when", "retry", "continue_on_error")


class RunReport:
    """每次运行生成一个自动刷新的 HTML 报告，双击即看。

    做在引擎层而不是任务插件：进度要在步骤之间更新，而 task 只在单点运行。
    零依赖、不开服务、不占端口、不常驻进程（不与 ComfyUI 抢显存）。
    实时刷新靠 <meta http-equiv="refresh">，结束时去掉该标签停止刷新。
    """

    def __init__(self, path, workflow, run_id, steps):
        self.path = Path(path)
        self.workflow = workflow
        self.run_id = run_id
        self.steps = steps
        self.state = {s["id"]: {"status": "pending", "elapsed": None,
                                "detail": "", "images": []} for s in steps}
        self.t0 = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def set(self, sid, status, elapsed=None, detail="", images=None):
        st = self.state.setdefault(sid, {"status": "pending", "elapsed": None,
                                         "detail": "", "images": []})
        st["status"] = status
        if elapsed is not None:
            st["elapsed"] = elapsed
        if detail:
            st["detail"] = detail
        if images is not None:
            st["images"] = list(images)
        self.write(running=True)

    def finish(self, ok, detail=""):
        self.write(running=False, ok=ok, detail=detail)

    def _boxes(self):
        out = []
        for s in self.steps:
            st = self.state.get(s["id"], {})
            status = st.get("status", "pending")
            el = st.get("elapsed")
            eltxt = f"{el:.1f}s" if isinstance(el, (int, float)) else "…"
            label = s.get("label") or DEFAULT_LABELS.get(s["task"], s["task"])
            hint = s.get("hint") or TASK_HINTS.get(s["task"], "")
            out.append(
                f'<div class="box {status}">'
                f'<div class="sid">{_html.escape(str(s["id"]))}</div>'
                f'<div class="name">{_html.escape(str(label))}</div>'
                f'<div class="hint">{_html.escape(str(hint))}</div>'
                f'<div class="el">{eltxt}</div>'
                f'<div class="st">{_html.escape(status)}</div></div>')
        return "\n".join(out)

    def _images(self):
        blocks, idx = [], 0
        for s in self.steps:
            imgs = self.state.get(s["id"], {}).get("images") or []
            if not imgs:
                continue
            cells = []
            for f in imgs:
                idx += 1
                src = _html.escape(rel_src(f, self.path))
                if Path(str(f)).suffix.lower() in (".mp4", ".webm", ".mov", ".m4v"):
                    media = f'<video controls preload="metadata" src="{src}"></video>'
                else:
                    media = f'<img loading="lazy" src="{src}" alt="img{idx}">'
                cells.append(
                    f'<figure class="cell" data-idx="{idx}" onclick="tg(this)">'
                    f'<span class="badge">{idx}</span>'
                    f'{media}'
                    f'<figcaption>{_html.escape(Path(str(f)).name)}</figcaption>'
                    f'</figure>')
            blocks.append(f'<h3>步骤 {_html.escape(str(s["id"]))} 的产物'
                          f'（点图选编号）</h3><div class="grid">{"".join(cells)}</div>')
        return "\n".join(blocks), idx

    def write(self, running, ok=None, detail=""):
        boxes = self._boxes()
        imgs, _n = self._images()
        done = sum(1 for s in self.steps if self.state.get(s["id"], {}).get("status")
                   in ("done", "failed", "skipped"))
        refresh = '<meta http-equiv="refresh" content="2">' if running else ""
        head = "运行中" if running else ("成功" if ok else "失败")
        cmd = (f"python run.py image_refine --set manifest={self.run_id} "
               f"--set pick=&lt;编号,逗号分隔&gt;")
        body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">{refresh}
<title>{_html.escape(self.workflow)} · {_html.escape(self.run_id)}</title>
<style>
 body{{font-family:"Segoe UI","Microsoft YaHei",sans-serif;margin:0;background:#14171c;color:#e8eaed}}
 header{{padding:18px 26px;background:#1c2129;border-bottom:1px solid #2a3038}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#9aa2ad;font-size:13px}}
 .pill{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:12px;background:#2a3038;margin-left:10px}}
 .flow{{display:flex;flex-wrap:wrap;gap:10px;padding:20px 26px}}
 .box{{border:1px solid #2a3038;border-left:5px solid #8a8f98;border-radius:6px;padding:10px 14px;min-width:150px;background:#1c2129}}
 .box.running{{border-left-color:#2f7fd6;background:#16222e}}
 .box.awaiting_human{{border-left-color:#d68a2e;background:#2a2114}}
 .box.done{{border-left-color:#2e9e5b}} .box.failed{{border-left-color:#d64545}} .box.skipped{{border-left-color:#b08a2e}}
 .sid{{font-size:11px;color:#7d8590}} .name{{font-size:15px;font-weight:600;margin:2px 0}}
 .hint{{font-size:12px;color:#9aa2ad}} .el{{font-size:13px;margin-top:6px;color:#cfd4da}}
 .st{{font-size:11px;margin-top:2px;color:#7d8590}}
 main{{padding:0 26px 30px}} h3{{font-size:14px;color:#cfd4da;margin:18px 0 8px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
 .cell{{margin:0;position:relative;cursor:pointer;border:2px solid transparent;border-radius:6px;overflow:hidden;background:#1c2129}}
 .cell.sel{{border-color:#2f7fd6}} .cell img{{width:100%;display:block}} .cell video{{width:100%;display:block}}
 .badge{{position:absolute;top:6px;left:6px;background:#2f7fd6;color:#fff;font-weight:700;border-radius:4px;padding:1px 7px;font-size:13px;z-index:2}}
 figcaption{{font-size:11px;color:#9aa2ad;padding:4px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
 .cmd{{background:#0d1013;border:1px solid #2a3038;border-radius:6px;padding:10px 14px;font-family:Consolas,monospace;font-size:13px;color:#9fd49f;margin-top:8px;white-space:pre-wrap}}
 .err{{background:#2a1517;border:1px solid #5a2a2e;border-radius:6px;padding:10px 14px;color:#f0b6ba;font-size:13px;margin-top:14px;white-space:pre-wrap}}
</style>
<script>
function tg(el){{el.classList.toggle('sel');
 var s=[].slice.call(document.querySelectorAll('.cell.sel'))
   .map(function(x){{return x.getAttribute('data-index')||x.getAttribute('data-idx')}}).join(',');
 document.getElementById('pick').textContent=s||'(还没选)';}}
</script></head><body>
<header><h1>{_html.escape(self.workflow)}<span class="pill">{head}</span></h1>
<div class="sub">run_id {_html.escape(self.run_id)} · 已完成 {done}/{len(self.steps)} 步 · 累计 {time.time() - self.t0:.0f}s</div></header>
<div class="flow">{boxes}</div>
<main>
{imgs if imgs else '<h3>还没有产物</h3>'}
<h3>选中编号</h3><div class="cmd" id="pick">(还没选)</div>
<h3>精修命令（把编号填进去）</h3><div class="cmd">{cmd}</div>
{f'<div class="err">{_html.escape(detail)}</div>' if detail else ''}
</main></body></html>"""
        tmp = self.path.parent / (self.path.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, self.path)


def _md5_head(p, n=8):
    """锚点内容指纹（查重复用同一张图占多槽用得上）；读不到返回 None，不编造。"""
    try:
        h = hashlib.md5()
        with open(str(p), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()[:n]
    except Exception:
        return None


def _as_list(v):
    if v in (None, ""):
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return list(v)


def _plan_digest(plan):
    """计划摘要（进 manifest 的证）：模式/配方/几何/模板/源稿/档位，一眼能对账。"""
    if not plan:
        return None
    try:
        return {
            "schema_version": plan.get("schema_version"),
            "input_mode": plan["inputs"]["input_mode"],
            "recipe_id": plan["recipe"]["recipe_id"],
            "template": plan["versions"]["template"],
            "template_sha256": plan["versions"]["template"]["sha256"],
            "geometry": {k: plan["geometry"][k] for k in
                         ("base_width", "base_height", "requested_frames",
                          "fps", "scale")},
            "source_prompt_sha256": plan["text"]["source_prompt"]["sha256"],
            "prompt_kind": plan["text"]["prompt_kind"],
            "tier": plan["flow"]["execution_tier"],
            "orchestration": plan["flow"]["orchestration"],
        }
    except Exception:
        return None


def write_manifest(path, run_id, workflow, outputs, args=None, step_params=None,
                   cfg=None, batch_dir=None, explicit_args=None, arg_sources=None,
                   resume_binding=None, run_plan=None):
    """逐张记录 index/seed/file/prompt/尺寸/步数 —— 编号选图与精修复现的依据。

    2026-09-20 补齐（G10）：历史上 video 步骤的 seed/width/height/steps 全写成 null
    （这里只认复数 seeds 与 out["width"]，而 video 任务返回的是单数 seed 和 length），
    且不记参考图槽位 —— 于是"四条全废因为槽位配错"那种事事后完全查不出来，
    唯一真源只剩 logs/workflows/<run>.log 第一行的 args=。现在逐槽写 文件+md5 指纹，
    并把本次 args 快照一并落盘（脱敏：不写任何 key，引擎的 key 本来就只走环境变量）。
    S1：再落 explicit_args/arg_sources（人给过什么）与 resume_binding
    （workflow/template/prompt/media/params + 每步摘要）——续跑只复用它证明未变的部分。
    """
    images, idx = [], 0
    for sid, out in outputs.items():
        if not isinstance(out, dict):
            continue
        sp = (step_params or {}).get(sid) or {}
        files = out.get("files") or []
        seeds = out.get("seeds") or ([] if out.get("seed") is None else [out.get("seed")])
        refs = [{"slot": i, "file": str(f), "md5": _md5_head(f)}
                for i, f in enumerate(_as_list(sp.get("ref_images")), 1)]
        refvids = [{"slot": i, "file": str(f), "md5": _md5_head(f)}
                   for i, f in enumerate(_as_list(sp.get("ref_videos") or sp.get("ref_video")), 1)]
        prompt = str(out.get("prompt") or sp.get("prompt") or "")
        entry_common = {
            "width": out.get("width") or sp.get("width"),
            "height": out.get("height") or sp.get("height"),
            "steps": out.get("steps") or sp.get("steps"),
            "length": out.get("length") or sp.get("length"),
            "fps": out.get("fps") or sp.get("fps"),
            "lora": sp.get("lora"),
            "lora_strength": sp.get("lora_strength"),
            "elapsed": out.get("elapsed"),
            "ref_images": refs,
            "ref_videos": refvids,
            "prompt_file": sp.get("prompt_file"),
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16] if prompt else None,
        }
        for i, f in enumerate(files):
            idx += 1
            images.append(dict(entry_common, index=idx, step=sid, file=str(f),
                               seed=seeds[i] if i < len(seeds) else (seeds[0] if len(seeds) == 1 else None)))
    snapshot = {k: v for k, v in (args or {}).items()
                if not re.search(r"key|token|secret|password", str(k), re.I)}
    data = {"run_id": run_id, "workflow": workflow,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "project": (cfg or {}).get("project"),
            "batch_dir": str(batch_dir) if batch_dir else None,
            "args": snapshot, "images": images,
            "explicit_args": sorted(str(k) for k in (explicit_args or [])),
            "arg_sources": dict(arg_sources or {}),
            "resume_binding": resume_binding or {},
            # S2：这次真实执行所用的有效计划摘要（与 --inspect 同一构造器）。
            "run_plan": _plan_digest(run_plan)}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return data


def resolve_pick(cfg, manifest_ref, pick_str):
    """把 --set pick=3,7 的编号映射成 manifest 里的 seed / 文件。
    返回 (选中条目, 父 manifest 全文, 批次夹名) —— 父 manifest 带 run_id 供状态记父指针；
    批次夹名取 manifest **所在那个夹**，因为精修报告底部的命令印的是精修自己的 run_id，
    照它再精修一次时只有按夹归才不会把同一个批次拆成新夹。"""
    ref = str(manifest_ref)
    if os.sep in ref or ":" in ref or ref.endswith(".json"):
        cands = [Path(ref)]
    else:
        cands = sorted(Path(cfg["output_root"]).glob(f"*/*_{ref}.manifest.json"))
    if not cands or not cands[0].exists():
        root = Path(cfg["output_root"])
        where = f"直接路径 {ref}" if cands and str(ref) == str(cands[0]) else f"{root}/*/*_{ref}.manifest.json"
        raise ValueError(f"找不到 manifest: {manifest_ref} —— 查过 {where}"
                         f"（交付根 {root}，一个批次一个夹；批次号取自报告文件名里的 <run_id>）")
    mf = cands[0]
    man = json.loads(mf.read_text(encoding="utf-8"))
    by_idx = {im["index"]: im for im in man.get("images", [])}
    picks = [int(x) for x in str(pick_str).split(",") if x.strip()]
    missing = [p for p in picks if p not in by_idx]
    if missing:
        raise ValueError(f"编号不存在: {missing}（manifest 共 {len(by_idx)} 张）")
    chosen = [by_idx[p] for p in picks]
    return chosen, man, mf.parent.name


def humanize_error(e):
    """把常见失败翻译成可操作的大白话，不甩 traceback。"""
    msg = str(e)
    NL = chr(10)
    if "兜底链全部失败" in msg:
        return ("所有 LLM 后端都不可用。\n"
                "怎么办：检查云端 API Key 是否已设置（网页「云端 API 设置」），"
                "以及网络连接是否正常。")
    if "找不到 manifest" in msg or "编号不存在" in msg:
        return f"选图参数不对：{msg}\n怎么办：打开上一次的 HTML 报告，确认编号后重试。"
    if "未知任务类型" in msg:
        return f"{msg}\n怎么办：任务类型要在 tasks.py 里注册过才能用。"
    if "等人工确认" in msg:
        return (msg + NL + "怎么办：这不是故障，是等你回话。在飞书回一句，或跑 "
                "python run.py --approve last <关口编号>；要否掉用 --deny。")
    if "跑前自审未通过" in msg:
        return (msg + NL + "怎么办：按上面每条 G 指出的改（换锚点/补分块/改分辨率），"
                "改完再跑。应急绕过：config.yaml 里 preflight: off，风险自担。")
    if "跑前自审闸不可用" in msg:
        return (msg + NL + "怎么办：闸本身坏了宁可停下。确认 tools" + os.sep
                + "check_preflight.py 在位。")
    return f"{type(e).__name__}: {msg}"


def update_status(cfg, workflow, run_id, status, detail="", extra=None):
    sf = Path(cfg["status_file"])
    data = {}
    if sf.exists():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    entry = {"workflow": workflow, "run_id": run_id, "status": status,
             "time": time.strftime("%Y-%m-%d %H:%M:%S"), "detail": detail[:300]}
    if extra:
        entry.update(extra)
    data["last_run"] = entry
    hist = data.get("history") or []
    if status == "running":
        # 自愈：Ctrl-C / 断电会让上一次运行永久停在 running
        # 计划 W5a：启动新一次运行**不能**替另一次运行断言"崩了"。
        # 旧实现在这里无条件标 error；现在只有"8189 可达 + /queue 里没有它的 prompt_id"
        # 才算证据，而这版台账还没逐运行保存 prompt_id ⇒ 一律标「状态待确认」，
        # 只把探活结果写进 detail 供人比对。error 只留给本次运行自己的失败。
        try:
            import tasks as _T
            alive = bool(_T.http_ok(cfg["comfyui"]["base_url"] + "/queue"))
        except Exception:
            alive = False     # 桩抛/隔离都按"探活不成立"记，不冒充进程已死
        for h in hist:
            if h.get("run_id") != run_id and h.get("status") == "running":
                h["status"] = "pending_confirm"
                h["detail"] = ("上次运行停在 running；8189 探活%s，且台账未记该次 prompt_id，"
                               "无法判断是否仍在排队/已完成 —— 状态待人工确认"
                               % ("可达" if alive else "失败"))
    # 一次运行会写 2~3 次（running → success/error），按 run_id 覆盖而非堆条目，
    # 否则 30 条上限只装得下十几次运行
    hist[:] = [h for h in hist if h.get("run_id") != run_id]
    hist.insert(0, entry)
    data["history"] = hist[:30]
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_history_run(cfg, run_id):
    """从 status.json 的 history 里翻出那次运行（--resume 用）。"""
    sf = Path(cfg["status_file"])
    if not sf.is_file():
        return None
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return None
    for h in (data.get("history") or []):
        if h.get("run_id") == run_id:
            return h
    return None


def _adoption_roots(cfg, entry):
    roots = []
    man = (entry or {}).get("manifest")
    if man:
        roots.append(Path(man).parent)
    out = (cfg.get("comfyui") or {}).get("output_dir")
    if out:
        roots.append(Path(out))
    return roots


def _find_adoption_submission(cfg, entry, run_id, step_id, prompt_id):
    """R4：迟到回填必须能找到原 run、原 prompt_id、原步骤的提交记录。"""
    safe = re.sub(r"[^\w.-]", "_", str(run_id or "run"))
    roots = _adoption_roots(cfg, entry)
    if cfg.get("output_root"):
        roots.append(Path(cfg["output_root"]))
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.rglob(f"submission_{safe}_*.json"):
            if f in seen:
                continue
            seen.add(f)
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(d.get("run_id") or "") != str(run_id):
                continue
            if str(d.get("prompt_id") or "") != str(prompt_id):
                continue
            sid = str(d.get("step_id") or "")
            stage = str(d.get("stage") or "")
            same_step = (sid == str(step_id)) if sid else (
                str(step_id) == "gen" and
                (stage == "video" or stage.startswith("shots/")))
            if not same_step:
                continue
            d["_submission_file"] = str(f)
            return d
    return None


def _adoption_file_ok(path, roots, cfg, qc_fn=None):
    p = Path(str(path))
    if not p.is_file():
        return False, "missing"
    try:
        if p.stat().st_size <= 0:
            return False, "empty"
        with p.open("rb") as f:
            f.read(1)
    except OSError as e:
        return False, f"unreadable:{type(e).__name__}"
    if not any(_is_under(p, r) for r in roots if r):
        return False, "outside_run_roots"
    suffix = p.suffix.lower()
    if suffix in {".mp4", ".webm", ".mov", ".mkv"}:
        try:
            fn = qc_fn or (lambda _p, _c: tasks.probe_video(_p, _c))
            fn(p, {"cfg": cfg, "log": lambda m: None})
        except Exception as e:
            return False, f"qc_failed:{type(e).__name__}:{str(e)[:120]}"
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        pass
    else:
        return False, f"unexpected_suffix:{p.suffix}"
    return True, ""


def _is_under(path, root):
    try:
        Path(str(path)).resolve().relative_to(Path(str(root)).resolve())
        return True
    except (OSError, ValueError):
        return False


def record_late_adoption(cfg, run_id, step_id, prompt_id, files, qc_fn=None):
    """R4：把原 prompt_id 迟到结果回填到原 run 的**已存在**步骤。

    必须同时满足：原 run 存在、步骤已存在、submission 的 run_id/prompt_id/step_id
    对得上、每个媒体在允许根内且非空/可读、视频过 probe_video。任一条不过就
    返回 False，不写 done/success。
    """
    sf = Path(cfg["status_file"])
    if not sf.is_file():
        return False
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return False
    entry = next((h for h in (data.get("history") or [])
                  if h.get("run_id") == run_id), None)
    if entry is None:
        return False
    steps = entry.get("steps") or []
    hit = next((s for s in steps if str(s.get("id")) == str(step_id)), None)
    if hit is None:
        return False  # 未知步骤不得凭空追加
    sub = _find_adoption_submission(cfg, entry, run_id, step_id, prompt_id)
    if sub is None:
        return False
    files = [str(f) for f in (files or []) if str(f).strip()]
    if not files:
        return False
    roots = _adoption_roots(cfg, entry)
    if not roots:
        return False
    for f in files:
        ok, why = _adoption_file_ok(f, roots, cfg, qc_fn=qc_fn)
        if not ok:
            return False
    hit.update({"status": "done", "restored": True,
                "detail": f"late adopt prompt_id={prompt_id}"})
    entry["steps"] = steps
    entry.setdefault("adoptions", []).append({
        "prompt_id": prompt_id, "step_id": str(step_id),
        "files": files, "submission": str(sub.get("_submission_file") or ""),
        "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    if steps and all(s.get("status") == "done" for s in steps):
        entry["status"] = "success"
        entry["detail"] = "原 prompt_id 迟到结果已回填，全部步骤 done"
    else:
        entry["detail"] = f"原 prompt_id 迟到结果已回填到步骤 {step_id}；其他步骤未完成"
    entry["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if data.get("last_run", {}).get("run_id") == run_id:
        data["last_run"] = entry
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return True


_RESTORE_SUFFIXES = {
    ".mp4", ".webm", ".mov", ".mkv", ".png", ".jpg", ".jpeg", ".webp",
    ".bmp", ".gif", ".wav", ".mp3", ".m4a", ".json", ".txt", ".html", ".csv",
}


def _restore_file_ok(path, root):
    """恢复前的机械核对：存在、非空、可读、后缀合理、不越出本批根。"""
    p = Path(str(path))
    if not p.is_file():
        return False, "missing"
    try:
        if p.stat().st_size <= 0:
            return False, "empty"
        with p.open("rb") as f:
            f.read(1)
    except OSError as e:
        return False, f"unreadable:{type(e).__name__}"
    if p.suffix.lower() and p.suffix.lower() not in _RESTORE_SUFFIXES:
        return False, f"unexpected_suffix:{p.suffix}"
    try:
        p.resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False, "outside_batch"
    return True, ""


def restore_outputs_checked(manifest_path, want_steps, batch_dir=None):
    """R3：恢复产物前核对存在/非空/可读/归属；任一条不过，整步不恢复。"""
    out, invalid = {}, {}
    try:
        man = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception:
        return out, invalid
    root = Path(batch_dir) if batch_dir else Path(manifest_path).parent
    for e in man.get("images", []):
        sid = e.get("step")
        if not sid or (want_steps and sid not in want_steps):
            continue
        d = out.setdefault(sid, {"files": [], "prompt": e.get("prompt", "")})
        f = e.get("file")
        if f:
            ok, why = _restore_file_ok(f, root)
            if ok:
                d["files"].append(str(f))
            else:
                invalid.setdefault(sid, []).append(
                    {"file": str(f), "reason": why})
        for k in ("seed", "width", "height", "steps", "length", "elapsed", "lora"):
            if e.get(k) is not None:
                d.setdefault(k, e[k])
        if e.get("seed") is not None:
            d.setdefault("seeds", []).append(e["seed"])
    for sid in invalid:
        out.pop(sid, None)
    return out, invalid


def restore_outputs(manifest_path, want_steps):
    """向后兼容的薄包装：只返回可恢复产物，不返回失效明细。"""
    return restore_outputs_checked(manifest_path, want_steps)[0]


def _plan_for_run(engine_root, workflow_name, wf, args, sources, cfg, tier, run_id):
    """真实执行与 --inspect 共用的**唯一**有效计划构造入口（S2）。

    两边都走这里，保证"预览的就是将提交的"。纯解析，不提交、不写状态、不触服务。
    """
    return run_plan.build_run_plan(engine_root, workflow_name, wf, args, sources,
                                   cfg=cfg, tier=tier, run_id=run_id)


def resolve_explicit_args(cli_sets, saved_args, saved_manifest=None):
    """哪些键是“人显式给过”的。

    旧 manifest 只有 args、没有来源证据 ⇒ 一个 saved 键都不能升成 human；
    新 manifest 记录 explicit_args（或 arg_sources 里标 cli_explicit/human 的键），
    续跑时只继承这些有证据的键。CLI 本次给的始终算显式。
    """
    explicit = {str(k) for k in (cli_sets or {})}
    man = saved_manifest or {}
    saved_keys = {str(k) for k in (saved_args or {})}
    prev = man.get("explicit_args")
    if isinstance(prev, list):
        explicit |= {str(k) for k in prev if str(k) in saved_keys}
    else:
        sources = man.get("arg_sources") or {}
        explicit |= {str(k) for k, v in sources.items()
                     if v in ("cli_explicit", "human") and str(k) in saved_keys}
    return sorted(explicit)


def handle_gate_cli(cfg, a):
    """免终端放行/否掉人工关口（也可被桌面 .bat 与飞书监听器调用）。

      python run.py --gates                      列当前待批
      python run.py --approve last H3            批准最近一个编号 H3 的待批关口
      python run.py --approve <run_id> <gate>    指定那次运行的关口
      python run.py --deny last H3 --note 戏不对  否掉（改内容后重跑会重新上报）
    """
    NL = chr(10)
    data = read_approvals(cfg)
    pending = data.get("pending") or {}
    if a.gates and a.porcelain:
        if not pending:
            return 0
        k, m = max(pending.items(), key=lambda kv: str(kv[1].get("asked_at") or ""))
        print("	".join([str(m.get("run_id") or ""), str(m.get("workflow") or ""),
                          str(m.get("gate") or "")]))
        return 0
    if a.gates:
        if not pending:
            print("没有待批关口。")
            return 0
        for k, m in sorted(pending.items(), key=lambda kv: kv[1].get("asked_at", "")):
            print(f"{m.get('asked_at')}  [{m.get('gate')}]  {m.get('label')}"
                  f"  run={m.get('run_id')}  项目={m.get('project')}")
            print(f"    key={k}")
        return 0
    run_ref, gid = (a.approve or a.deny)
    approved = bool(a.approve)
    # 2026-10-19 第⑫条(c) 顺手加固：备注要用 `--note`。写成位置参数会被 `workflow`
    # （nargs="?"）静默吃掉 ⇒ 批准/否掉的**理由丢失**而界面照样打印成功——正是本项目最忌的"静默"。
    if getattr(a, "workflow", None):
        print("⚠ 你给的多余参数 %r 被当成 workflow 位置参数忽略了，**不会写进理由**。"
              "理由要用：--note \"%s\"" % (a.workflow, a.workflow), file=sys.stderr)
    if str(gid).upper() == "ALL":
        matches = [k for k, m in pending.items()
                   if run_ref == "last" or m.get("run_id") == run_ref]
    else:
        matches = [k for k, m in pending.items()
                   if (run_ref == "last" or m.get("run_id") == run_ref)
                   and (str(k).split("|")[2] == gid or m.get("gate") == gid)]
    if not matches:
        print(f"找不到待批关口 run={run_ref} gate={gid}。当前待批 {len(pending)} 个；"
              f"用 --gates 看一眼。", file=sys.stderr)
        return 2
    key = matches[0] if run_ref != "last" else max(
        matches, key=lambda k: pending[k].get("asked_at", ""))
    meta = dict(pending.get(key) or {})
    record_approval(cfg, key, "approved" if approved else "denied",
                    note=a.note or "", meta=meta)
    print(f"已{'批准' if approved else '否掉'}：[{meta.get('gate')}] {meta.get('label')}")
    print(f"key={key}")
    if approved:
        print(f"继续跑：python run.py {meta.get('workflow')} --resume {meta.get('run_id')}"
              f"   （关口已记批准，内容不变就不会再问）")
    else:
        print("被否掉的这条改内容（提示词/锚点任一项）后重跑，会当成新关口重新上报。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="auto-workflow 引擎")
    ap.add_argument("workflow", nargs="?", help="workflows\\ 下的 YAML 名（不带扩展名）")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    help="覆盖工作流参数, 如 --set count=3 --set theme=xxx")
    ap.add_argument("--output-root", dest="output_root", default=None,
                    help="覆盖 config.yaml 的 output_root（本次运行的交付根）")
    ap.add_argument("--project", default=None,
                    help="当前项目名；交付根据此从 pool_root 派生（换项目用这个，别改 config 路径）")
    ap.add_argument("--list", action="store_true", help="列出可用工作流")
    ap.add_argument("--gates", action="store_true", help="列出待批的人工关口")
    ap.add_argument("--approve-and-resume", dest="approve_and_resume", action="store_true",
                    help="批准最近一个待批关口并立刻续跑它那次运行（桌面一键批准专用）")
    ap.add_argument("--porcelain", action="store_true",
                    help="配 --gates：只输出最近一个待批关口（run_id<TAB>workflow<TAB>关口号），给批处理脚本用")
    ap.add_argument("--approve", nargs=2, metavar=("RUN_ID", "GATE"),
                    help="批准某次运行的某个关口（RUN_ID 可用 last 取最近一个）")
    ap.add_argument("--deny", nargs=2, metavar=("RUN_ID", "GATE"), help="否掉某个关口")
    ap.add_argument("--note", default="", help="批准/否掉时附一句话，进台账")
    ap.add_argument("--inspect", action="store_true",
                    help="【拟新增 · W1 落地】只解析不提交：打印 RunPlan 摘要与机器快照"
                         "（模式/素材/模板/配方/几何/档位），不建批次夹、不写状态、不碰 GPU")
    ap.add_argument("--resume", default=None, metavar="RUN_ID",
                    help="接着上次跑：已 done 的步骤跳过（不重烧 GPU），只补剩下的")
    ap.add_argument("--cancel", default=None, metavar="RUN_ID",
                    help="【W5b】取消那次运行**自己**已提交的任务："
                         "读 submission_*.json 拿 prompt_id → 具名删除（pending）"
                         "或 /interrupt（--running 时）→ 回读 /queue 核对终态。"
                         "不清队列、不杀服务；未核对成功时不显示\"已取消\"")
    ap.add_argument("--running", action="store_true",
                    help="配 --cancel：那次任务正在执行，需要 /interrupt 而不是只删队列项")
    ap.add_argument("--adopt", default=None, metavar="RUN_ID",
                    help="【W5b】超时后复查：只认那次 prompt_id 的 history 产物，"
                         "绝不把输出目录里别人的新文件认领成自己的结果")
    ap.add_argument("--tier", default=None, metavar="TIER",
                    choices=["play", "draft", "final"],
                    help="档位（2026-10-19 新功能④）："
                         "play＝娱乐流预览——闸门 warn 不拦、产物落 ComfyUI_H3\\output\\娱乐流\\<批次>、"
                         "不进资源池、不交付；draft＝默认＝现役行为；"
                         "final＝强制 preflight_strict=on（正式出片用）。"
                         "不显式给就读 config.yaml 的 tier，读不到按 draft。"
                         "🔴 注意与 workflows/*_play 那批**不是一回事**："
                         "`*_play` 是**参数预设**（20 步／不挂 LoRA／两头夹，见 --list），"
                         "`--tier play` 是**落点与降级**。两者正交、可叠用。"
                         "用 *_play 工作流但没给 --tier play 时会提示一次，免得以为产物进了预览区。")
    a = ap.parse_args()
    is_selftest = str(a.workflow or "").startswith("selftest")

    if a.gates or a.approve or a.deny:
        cfg0 = _load_cfg()
        sys.exit(handle_gate_cli(cfg0, a))

    if a.approve_and_resume:
        # 一键批准：只批"最近一个"待批关口（不用 ALL —— 全批会把你没看的那条也放过去），
        # 然后就地转成 --resume，参数由那次运行的台账自动回放。
        cfg0 = _load_cfg()
        pend = read_approvals(cfg0).get("pending") or {}
        if not pend:
            print("没有待批关口，什么都不用做。")
            return
        k, m = max(pend.items(), key=lambda kv: str(kv[1].get("asked_at") or ""))
        record_approval(cfg0, k, "approved", note=a.note or "桌面一键批准",
                        meta={**m, "source": "bat"})
        print(f"已批准 [{m.get('gate')}] {m.get('label')} · {m.get('theme')}")
        if len(pend) > 1:
            print(f"（还有 {len(pend)-1} 个待批没动 —— 逐条批，别一把全放）")
        a.workflow = m.get("workflow")
        a.resume = m.get("run_id")
        # a.workflow 是刚被改写的：is_selftest 必须重算，否则自测续跑会写进交付根
        is_selftest = str(a.workflow or "").startswith("selftest")
        if not a.workflow or not a.resume:
            print("该待批记录缺 workflow/run_id，无法自动续跑；"
                  "用 --approve <run_id> <gate> 手工批后再跑", file=sys.stderr)
            sys.exit(2)

    wf_dir = ROOT / "workflows"
    if a.list or (not a.workflow and not a.resume and not a.cancel and not a.adopt):
        for f in sorted(wf_dir.glob("*.yaml")):
            w = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if str(w.get("retired", "")).lower() in ("true", "yes", "1"):
                # 退役桩也要列出来：只报"跑不了"不报"为什么、替代是什么"＝逼人来考古。
                print(f"{f.stem:24s} 【已退役】{w.get(RETIRED_KEY, '')}")
                continue
            print(f"{f.stem:24s} {w.get('description', '')}")
        return

    cfg = _load_cfg()

    def _submissions(run_id):
        """找那次运行的提交快照（拿到 prompt_id 的唯一凭据）。"""
        roots = [Path(cfg["output_root"]).parent, Path(cfg.get("pool_root") or ".")]
        found = []
        for r in roots:
            if not r.is_dir():
                continue
            for f in r.glob(f"**/submission_{run_id}_*.json"):
                try:
                    found.append((f, json.loads(f.read_text(encoding="utf-8"))))
                except Exception:
                    continue
        return found

    if a.cancel:
        subs = _submissions(a.cancel)
        if not subs:
            print(f"--cancel {a.cancel}：找不到 submission_*.json，"
                  f"说明那次运行没有已提交的步骤（或 run_id 写错）", file=sys.stderr)
            sys.exit(2)
        base = cfg["comfyui"]["base_url"]
        hist = find_history_run(cfg, a.cancel)
        batch_dir = None
        if hist and hist.get("manifest"):
            batch_dir = str(Path(hist["manifest"]).parent)
        if not batch_dir:
            for _p, _payload in subs:
                if _payload.get("batch_dir"):
                    batch_dir = str(_payload["batch_dir"])
                    break
        if not batch_dir:
            batch_dir = str(subs[0][0].parent)
        try:
            tasks.request_cancel({"batch_dir": batch_dir, "run_id": a.cancel},
                                 reason="cli:cancel")
        except Exception as _e:
            print(f"⚠ 取消意图没落盘（{type(_e).__name__}: {_e}）；"
                  f"队列取消仍会尝试，但运行中的循环可能看不到停止意图",
                  file=sys.stderr)
        cancel_ctx = {"cfg": cfg, "run_id": a.cancel, "batch_dir": batch_dir,
                      "log": lambda m: print(m), "workflow": "", "args": {}}
        results = []
        for path, payload in subs:
            pid = payload.get("prompt_id")
            if not pid:
                results.append({"file": path.name, "skipped": "快照里没有 prompt_id"})
                continue
            res = tasks.cancel_submission(cancel_ctx, base, pid, running=bool(a.running))
            res["file"] = path.name
            results.append(res)
            st = ("cancelled" if res.get("confirmed") else
                  "done" if res.get("state") == "finished" else
                  "error" if res.get("state") == "api_error" else
                  "cancel_requested")
            update_status(cfg, f"cancel:{a.cancel}", a.cancel, st,
                          detail=(f"state={res.get('state')} queue={res.get('queue')} "
                                  f"steps={res.get('steps')}")[:280])
        print(json.dumps(results, ensure_ascii=False, indent=2))
        unconfirmed = [r for r in results
                       if r.get("requested") and not r.get("confirmed")
                       and r.get("state") != "finished"]
        if unconfirmed:
            print("⚠ 有取消请求没核对成功：以上任务**不算已取消**；"
                  "state 已分开标注 finished/unknown/not_dispatched/"
                  "still_queued/api_error，请人工确认 /queue 与产物",
                  file=sys.stderr)
            sys.exit(1)
        requested = [r for r in results if r.get("requested")]
        if requested and all(r.get("state") == "finished" for r in requested):
            print("目标在 history 里已结束；取消是幂等 no-op，未显示为已取消")
        else:
            print("已核对：取消已按 ID 落地且回读队列无目标（未清队列、未停服务）")
        return

    if a.adopt:
        subs = _submissions(a.adopt)
        if not subs:
            print(f"--adopt {a.adopt}：找不到 submission_*.json，无结果可认领",
                  file=sys.stderr)
            sys.exit(2)
        base = cfg["comfyui"]["base_url"]
        hist = find_history_run(cfg, a.adopt)
        batch_dir = None
        if hist and hist.get("manifest"):
            batch_dir = str(Path(hist["manifest"]).parent)
        if not batch_dir:
            for _p, _payload in subs:
                if _payload.get("batch_dir"):
                    batch_dir = str(_payload["batch_dir"])
                    break
        if not batch_dir:
            batch_dir = str(subs[0][0].parent)
        adopt_ctx = {"cfg": cfg, "run_id": a.adopt, "batch_dir": batch_dir,
                     "log": lambda m: print(m)}
        for path, payload in subs:
            pid = payload.get("prompt_id")
            got = tasks.adopt_late_output(adopt_ctx, base, pid,
                                          expected_prefix=None)
            if got:
                step_id = payload.get("step_id") or payload.get("stage") or "video"
                recorded = record_late_adoption(cfg, a.adopt, step_id, pid,
                                                got["files"])
                suffix = "；已回填原任务步骤状态" if recorded else "；原任务状态未找到，未回填"
                print(f"{pid}: 结果在位 {got['files']}{suffix}")
            else:
                print(f"{pid}: 那次提交没有产物（不认领任何目录里的新文件）")
        return

    resume_h = None
    if a.resume:
        if a.resume == "last":
            sf = Path(cfg["status_file"])
            try:
                hist = (json.loads(sf.read_text(encoding="utf-8")).get("history") or [])
            except Exception:
                hist = []
            # 只认停在人工关口的那次；跑成功/真失败的不该被"续跑"
            # 计划 W5a：history 的堆序是最新在前（:422 hist.insert(0, entry)），
            # 正序遍历直接取第一个就是"最新待审"；reversed() 会拿到最旧的 awaiting_human，
            # 正是本批次要修的反向 bug。
            for h in hist:
                if h.get("status") == "awaiting_human":
                    a.resume = h.get("run_id")
                    print(f"--resume last → 最近停在关口的运行：{a.resume}（run_id={a.resume}，"
                          f"asked_at={h.get('time')}，{h.get('workflow')}）")
                    break
            else:
                print("没有停在人工关口的运行可续跑（用 --gates 看待批清单）",
                      file=sys.stderr)
                sys.exit(2)
        resume_h = find_history_run(cfg, a.resume)
        if not resume_h:
            print(f"--resume {a.resume}：在 {cfg['status_file']} 的 history 里找不到那次运行。"
                  f"（history 只留最近若干次；太久远的运行请直接重跑，"
                  f"已批准过的关口不会重复上报）", file=sys.stderr)
            sys.exit(2)
        if not resume_h.get("workflow"):
            print(f"--resume {a.resume}：那次运行没记 workflow，无法续跑", file=sys.stderr)
            sys.exit(2)
        a.workflow = resume_h["workflow"]
        # 🔴 2026-10-19 端到端验证抓出的真 bug：上面 :546 那句"必须重算 is_selftest"
        # 只加在 --approve-and-resume 那条分支上，**plain --resume 这条漏了**。
        # 后果实测：`run.py --resume last` 续跑 selftest_gates 时 is_selftest 还是 False
        # ⇒ :614 的 selftest_output_root 覆盖不生效 ⇒ 自测产物（html＋manifest）
        #   直接落进交付根 `E:\图像影音资源池\无音\批次\20261019_114435\`。
        #   自测本来被刻意排除在交付根外（:698/:703 都带 not is_selftest），这条一路径上全失效。
        is_selftest = str(a.workflow or "").startswith("selftest")
        # 2026-10-15 修：续跑必须回放 project。以前 --resume 不带 --project 就落回
        # config 默认项目 ⇒ 交付根派生到别的项目池（实测把武昭君仪的批续写进了无音池）。
        # 台账里的 run-manifest 记了 project，直接读回；CLI 显式给了就不覆盖。
        if not a.project and resume_h.get("manifest"):
            try:
                _rec = json.loads(Path(resume_h["manifest"]).read_text(encoding="utf-8"))
                _proj = (_rec or {}).get("project")
                if _proj:
                    a.project = _proj
                    print(f"--resume {a.resume}：按台账回放 project={_proj}")
            except Exception as _e:
                print(f"--resume {a.resume}：台账 manifest 读不出 project（{_e}），"
                      f"请显式给 --project，否则交付根会按 config 默认项目派生",
                      file=sys.stderr)
    if a.output_root:
        cfg["output_root"] = a.output_root
    wf_file = wf_dir / f"{a.workflow}.yaml"
    if not wf_file.exists():
        print(f"工作流不存在: {wf_file}", file=sys.stderr)
        sys.exit(2)
    wf = load_workflow(wf_file)

    # selftest 不往交付根写：用独立目录，跑完清理
    selftest_tmp = None
    if is_selftest and cfg.get("selftest_output_root"):
        selftest_tmp = Path(cfg["selftest_output_root"])
        cfg["output_root"] = str(selftest_tmp)
    run_id = a.resume or (time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4])
    # W5b：run_id 加随机尾缀——同一秒里起两条不再互相覆盖状态/夹名；
    # 旧 ID（纯时间戳）照样能读能续，--resume 传什么就用什么。
    # 计划 W1：--set 的列表键旧逗号写法继续接，内部立即转具名列表；
    # JSON 数组按列表解析，不把 JSON 字符串默默当单条路径（parse_sets 里会明确报错）。
    try:
        cli_sets = run_plan.parse_sets(a.sets)
    except run_plan.PlanError as e:
        print(f"--set 解析失败：{e}", file=sys.stderr)
        sys.exit(2)
    for k, v in cli_sets.items():
        if isinstance(v, str):
            cli_sets[k] = auto_cast(v)
    # --resume 自动回放上次台账里记的参数：一键批准之后不需要重敲一长串 --set
    saved_args, resume_manifest = {}, {}
    if resume_h and resume_h.get("manifest") and Path(resume_h["manifest"]).is_file():
        try:
            resume_manifest = json.loads(
                Path(resume_h["manifest"]).read_text(encoding="utf-8"))
            saved_args = resume_manifest.get("args") or {}
        except Exception as e:
            print(f"--resume：上次台账读不出参数（{type(e).__name__}: {e}）", file=sys.stderr)
    # 计划 W1：参数逐字段记录来源（用户显式／续跑回放／YAML 默认）——来源不等于授权主体
    args, arg_sources = run_plan.merge_args(wf.get("args") or {}, saved_args, cli_sets)
    # 计划 W1c／W3：可选首尾帧单流只声明 input_mode，prompt_kind 由模式派生。
    # 映射表与解析器共用 run_plan.derive_prompt_kind（唯一真源），这里不再自写一份。
    args, _pk_err = run_plan.derive_prompt_kind(args)
    if _pk_err:
        print(_pk_err, file=sys.stderr)
        sys.exit(2)

    # 10-02 批 5-2：运行决定单要分清「这批人给的」与「yaml 里写着的默认值」。
    # S1：旧 manifest 只有 args、没有来源证据 ⇒ 不能把 saved 全升成 human。
    # 新 manifest 的 explicit_args/arg_sources 才是有证据的人工值。
    explicit_args = resolve_explicit_args(cli_sets, saved_args, resume_manifest)

    # ===================== 档位（tier）—— 2026-10-19 新功能④ =====================
    # 设计不变式 I12：**tier 的展开只在入口这一处做，tasks.py 里不许出现 `if tier ==`**。
    # 所以这里把抽象档位翻译成**引擎早就认识的具体能力开关**，tasks 只看到
    # `args["allow_degrade"]` 这一个事实，不知道也不需要知道"这是 play 档"。
    #   play   娱乐流预览：闸门 warn 不拦 + 产物落 ComfyUI_H3\output\娱乐流\<批次>
    #          + 不进资源池 + 不交付。捞回来靠**参数重跑**——批次夹里那两份就是为此：
    #          `<workflow>_<run_id>.manifest.json`（args 全量，机器读）＋
    #          `怎么捞回来.md`（把 --tier play 换成 --tier draft 的整条命令，人直接复制）。
    #          ⚠ 2026-10-19 端到端验证更正：这里原先写的是 `batch.json`，**那个文件在这台机器上
    #          从来没被任何代码写过**（设计阶段起的名字漏进了实现与文案）⇒ 以盘上实际产物为准。
    #          不靠文件提升 ——
    #          理由见 官方路径.json 的 forbidden 第 6 条：预览直接进正身＝污染资源池。
    #   draft  默认＝现役行为，一个开关都不动（**向后兼容是这一档的第一职责**）。
    #   final  正式出片：把 preflight_strict 拧到 on（config.yaml 里写 off 也覆盖掉）。
    _cfg_tier = str(cfg.get("tier") or "").strip().lower()
    tier = str(a.tier or _cfg_tier or "draft").strip().lower()
    if tier not in ("play", "draft", "final"):
        print(f"--tier 只许 play/draft/final，给的是 `{a.tier}`", file=sys.stderr)
        sys.exit(2)
    tier_play = (tier == "play")
    args["tier"] = tier
    # 🔴 摊开一个**已经存在的撞名**：workflows 里有一批 `*_play`（h3_fl2va_clean_play /
    #   h3_fl2va_dual_play / h3_fl2va_fight_play …），那是**参数预设**（20 步／不挂 LoRA／
    #   两头夹），与 `--tier play`（落点＋降级）正交。两件事共用一个词＝未来的 agent 一定搞混，
    #   而搞混的表现是"以为产物在预览区、其实写进了资源池正身"——正是 forbidden 第 6 条要防的。
    #   这里不改名（改名会牵动 4 份 yaml 与所有历史台账），只做一次显式提示，把坑摆到台面上。
    if "_play" in str(a.workflow or "") and tier != "play":
        print("[tier] ⚠ 工作流名里带 `_play`，但那是**参数预设**不是档位；"
              "本批档位是 `%s` ⇒ 产物会按 %s 的落点规则走（会进资源池正身）。"
              "要落预览区请加 `--tier play`。" % (tier, tier))
    # 计划 W5a：每次按当前档位重算能力开关——非 play 档显式清 allow_degrade，
    # 防止跨次运行（或同次 args dict 被复用）时残留 play 档的降级开关。
    args["allow_degrade"] = bool(tier == "play")
    if tier == "final":
        if str(cfg.get("preflight_strict", "off")).lower() not in ("on", "true", "1", "yes"):
            print("[tier=final] config.yaml 的 preflight_strict 是 off，本档强制拧成 on"
                  "（正式出片不接受 warn 放行）")
        cfg["preflight_strict"] = "on"
    play_root = None
    if tier == "play" and not a.output_root:
        # 这里取 project 要自己拼一遍：下面「交付根派生」那段才写 cfg["project"]，
        # 在本块之后才执行。等在那后面再改 output_root 就会被 G11 派生覆写回资源池。
        _pj = re.sub(r'[\\/:*?"<>|]', "_",
                     str(a.project or args.get("project") or cfg.get("project") or "").strip())
        # ⚠ 这里**不要再拼 run_id**：下面 :738 会做 `batch_dir = output_root/run_id`，
        #   拼了就成了 `娱乐流/<run_id>_<proj>/<run_id>` 这种双层目录。
        play_root = (Path(cfg.get("play_output_root")
                            or (ROOT.parent / "ComfyUI_H3" / "output" / "娱乐流"))
                     / (_pj or "nopj"))
        cfg["output_root"] = str(play_root)
        print(f"[tier=play] 产物落预览区，不进资源池：{play_root}\\<run_id>")
        print("[tier=play] 闸门 error 降级为 warn（仍逐条进日志）；要正式出片改跑 --tier draft")
    # =========================================================================

    # ---- 交付根派生（G11）：project 决定落点，换项目不必再手改绝对路径 ----
    cfg["project"] = str(a.project or args.get("project") or cfg.get("project") or "")
    cfg.setdefault("project_aliases", {})
    # tier=play 时**跳过派生**：派生会把落点改回资源池，那正好毁掉这一档的目的。
    if not a.output_root and cfg["project"] and cfg.get("pool_root") and not is_selftest and not tier_play:
        derived = delivery_root(cfg, project=cfg["project"])
        if str(derived) != str(cfg.get("output_root") or ""):
            print(f"[G11] 交付根由 project='{cfg['project']}' 派生：{cfg.get('output_root')} -> {derived}")
        cfg["output_root"] = str(derived)
    if cfg.get("pool_root") and cfg["project"] and not is_selftest:
        parts = [str(x) for x in Path(cfg["output_root"]).parts]
        if cfg["project"] not in parts:
            print(f"G11：交付根 {cfg['output_root']} 的项目段不含当前 project "
                  f"'{cfg['project']}' —— 产物会落进别的项目夹。"
                  f"改 --project，或显式 --output-root 并自行确认落点。", file=sys.stderr)
            sys.exit(2)

    # ---- 有效 RunPlan：--inspect 与真实执行**同一个构造器、同一份输入** ----
    # S2：以前只有 --inspect 走 RunPlan，真实执行另走一套参数展开；于是"预览能过、
    # 实跑换配方"或反之都可能发生。现在两边都从 `_plan_for_run` 取计划：
    #   · inspect：打印摘要后退出（不写状态、不建批次夹、不触服务）；
    #   · 执行：计划先过机械校验，再进入后面建批次夹/提交；计划摘要进 manifest。
    # 旧预设直调（没有显式 input_mode）保留兼容：计划解析失败只告警不拦，
    # 因为旧流的模板/步数组合按历史口径仍要能跑；新选择（显式 input_mode）一律硬拦。
    try:
        plan = _plan_for_run(ROOT, a.workflow, wf, args, arg_sources, cfg, tier, run_id)
        plan_error = None
    except run_plan.PlanError as e:
        plan, plan_error = None, str(e)
    if a.inspect:
        if plan_error:
            print(f"RunPlan 解析失败（未提交、未建批次夹）：{plan_error}", file=sys.stderr)
            sys.exit(2)
        print(run_plan.render_summary(plan))
        print("--- run_plan ---")
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if plan_error:
        if str(args.get("input_mode") or "").strip():
            print(f"RunPlan 解析失败（未提交、未建批次夹）：{plan_error}", file=sys.stderr)
            sys.exit(2)
        # 图片链（image_* / prompt_kind=image）不是 H3 出片模板，本来就没有 RunPlan；
        # 这不是“旧预设漂移”，不要拿 H3 模板要求它，也不要用这条警告吓人。
        is_image_flow = (str(wf.get("prompt_kind") or "") == "image"
                         or str(a.workflow or "").startswith("image_"))
        if not is_image_flow:
            print(f"[RunPlan] 旧预设直调：计划未通过机械校验，按兼容路径继续 —— {plan_error}",
                  file=sys.stderr)

    # 编号选图：--set manifest=<run_id 或路径> --set pick=3,7
    parent_run, picked_idx, batch_id = None, [], None
    if "pick" in args and args.get("manifest") not in (None, ""):
        chosen, parent_man, batch_id = resolve_pick(cfg, args["manifest"], args["pick"])
        # 父指针：精修这次运行出自哪次运行，监控器据此串整条链
        parent_run = parent_man.get("run_id")
        if not parent_run:
            print(f"manifest 里没有 run_id（来自 {args['manifest']}）—— 精修必须记下来自哪次运行，"
                  f"否则监控器的 parent_run 链会断，拒绝静默继续", file=sys.stderr)
            sys.exit(2)
        if not batch_id or str(batch_id) in (".", ".."):
            print(f"无法从 manifest 的位置确定批次夹名（来自 {args['manifest']}）—— "
                  f"请把 manifest 放在交付根下的批次夹里再引用，否则产物会散落到交付根",
                  file=sys.stderr)
            sys.exit(2)
        picked_idx = [c["index"] for c in chosen]
        args["picked_files"] = [c["file"] for c in chosen]
        args["picked_seeds"] = [c["seed"] for c in chosen]
        args["picked_names"] = [Path(c["file"]).name for c in chosen]
        args["picked_prompt"] = chosen[0].get("prompt", "")

    # 交付批次夹：一个批次一夹，自包含。精修写进父草稿那一夹，不另起新夹。
    # 引擎自起的 ComfyUI 用 config 的 output_dir，手工起的用 bat 里写死的值，
    # 而 ensure_comfyui 复用存活服务时不校验它在往哪写 —— 所以产物位置由
    # relocate() 在引擎侧兜底，不指望 ComfyUI 自己写对地方（见阶段 D 规格）。
    batch_dir = Path(cfg["output_root"]) / str(batch_id or run_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    raw_steps = wf.get("steps") or []
    steps_meta = [{"id": str(s.get("id") or f"step{i}"), "task": s.get("task"),
                   "label": s.get("label"), "hint": s.get("hint")}
                  for i, s in enumerate(raw_steps, 1)]
    reserved = {"cfg", "args", "run_id", "log", "outputs", "wf_root", "batch_dir",
                "step_id", "workflow", "explicit_args"}
    clash = [m["id"] for m in steps_meta if m["id"] in reserved]
    if clash:
        print(f"步骤 id 与引擎保留字冲突: {clash}（保留字: {sorted(reserved)}）",
              file=sys.stderr)
        sys.exit(2)

    log = Logger(Path(cfg["log_dir"]) / f"{a.workflow}_{run_id}.log")
    report = RunReport(batch_dir / f"{a.workflow}_{run_id}.html",
                       a.workflow, run_id, steps_meta)
    manifest_path = batch_dir / f"{a.workflow}_{run_id}.manifest.json"

    # 「捞回来靠参数重跑，不靠文件提升」（官方路径.json forbidden 第 6 条）。
    # 所以开跑前就把整条 draft 命令写进预览批次里 —— 崩掉的运行也要捞得回来。
    # 放这一段而不是上面 tier 块：那里 manifest_path / batch_dir 都还没定义，
    # 硬引用的话异常会被 try 吞成"没写成"，文件永远出不来（实测差点这么留下）。
    if tier_play:
        try:
            _q = 'cd "%s" && python run.py %s' % (ROOT, a.workflow)
            _q += "".join(' --set "%s=%s"' % (k, args.get(k))
                          for k in sorted(args)
                          if k not in ("tier", "allow_degrade") and args.get(k) not in (None, ""))
            if cfg.get("project"):
                _q += ' --project "%s"' % cfg["project"]
            _q += " --tier draft"
            (batch_dir / "怎么捞回来.md").write_text(
                "# 这批是娱乐流**预览**产物，不在资源池正身里\n\n"
                "- 档位：`play` —— 闸门 error 降级成 warn、不做 QC、不交付\n"
                "- run_id：`%s`\n- 开跑时间：%s\n- 工作流：`%s`\n\n"
                "## 看中了就往正式链上重跑（参数原样回放，只把档位换成 draft）\n\n"
                "```bat\n%s\n```\n\n"
                "🔴 **别把这里的文件直接拷进资源池**。预览与正式的区别不在文件，在"
                "**有没有过全量闸门与 QC** —— 拷进去就等于把没过闸的东西当成了交付物。\n\n"
                "本批完整参数快照以台账为准：`%s`\n"
                % (run_id, time.strftime("%Y-%m-%d %H:%M:%S"), a.workflow, _q, manifest_path),
                encoding="utf-8")
            print("[tier=play] 重跑命令已写：%s" % (batch_dir / "怎么捞回来.md"))
        except Exception as _e:
            print("[tier=play] ⚠ 重跑命令没写成（不影响出片，但捞回来得自己敲参数）："
                  "%s: %s" % (type(_e).__name__, _e))

    resume_done, resume_outputs, resume_from = set(), {}, None
    # S1：恢复前先算本次输入绑定（workflow/template/prompt/media/params + 每步摘要）。
    run_binding = task_state.attach_steps(
        task_state.build_binding(ROOT, a.workflow, wf, args), raw_steps)
    if resume_h is not None:
        done_prev = {s.get("id") for s in (resume_h.get("steps") or [])
                     if s.get("status") == "done"}
        known = {m["id"] for m in steps_meta}
        unknown = sorted(x for x in done_prev if x and x not in known)
        if unknown:
            print(f"--resume：上次有步骤 {unknown} 在本次 YAML 里已不存在，忽略", file=sys.stderr)
        decision = task_state.select_resume_steps(
            done_prev & known, raw_steps,
            (resume_manifest or {}).get("resume_binding"), run_binding,
            prev_manifest=resume_manifest, curr_args=args)
        resume_done = decision["reusable"]
        invalidated = decision["invalidated"]
        if decision["basis"] == "legacy":
            print("--resume：旧 manifest 没有依赖指纹；只复用能证明的编译步，"
                  "生成/审核步不复用（不假继承旧批准）", file=sys.stderr)
        if invalidated:
            print(f"--resume：{len(invalidated)} 个已完成步骤因依赖变化/无证据失效："
                  f"{sorted(invalidated)}；将按顺序重跑这些步骤及其下游",
                  file=sys.stderr)
        resume_outputs, restore_invalid = restore_outputs_checked(
            manifest_path, resume_done, batch_dir=batch_dir)
        if restore_invalid:
            blocked, dropped = False, set()
            for _s in raw_steps:
                _sid = str(_s.get("id") or "")
                if _sid in restore_invalid:
                    blocked = True
                if blocked and _sid in resume_done:
                    resume_done.discard(_sid)
                    dropped.add(_sid)
            for _sid in dropped:
                resume_outputs.pop(_sid, None)
            print(f"--resume：{len(restore_invalid)} 步的产物缺失/为空/越界/不可读，"
                  f"整步及下游不复用：{sorted(dropped)}；原因 "
                  f"{ {k: [x['reason'] for x in v] for k, v in restore_invalid.items()} }",
                  file=sys.stderr)
        resume_from = a.resume
        print(f"--resume {a.resume}：复用已完成 {len(resume_done)} 步 "
              f"{sorted(resume_done)}，回填产物 "
              f"{sum(len(v.get('files', [])) for v in resume_outputs.values())} 个")

    def status_extra():
        # 计划 W5a：steps 每条显式带 restored 布尔——resume 恢复的步骤标 True，
        # 真跑/成功/失败/条件跳过（skipped）标 False 或缺省。
        return {"report": str(report.path), "manifest": str(manifest_path),
                "parent_run": parent_run, "picked": picked_idx,
                "steps": [{"id": s["id"],
                           "status": report.state.get(s["id"], {}).get("status",
                                                                       "pending"),
                           "restored": bool(report.state.get(s["id"], {}).get("restored")),
                           "elapsed": report.state.get(s["id"], {}).get("elapsed")}
                          for s in steps_meta]}

    def dump_manifest():
        """把当前进度写进台账。失败/停住也要有账可查 —— 历史上 manifest 只在
           全部成功时写一次，于是 9-18 那种"四条全废"的运行连参数都没留下。"""
        try:
            write_manifest(manifest_path, run_id, a.workflow, ctx["outputs"],
                           args=args, step_params=step_params, cfg=cfg,
                           batch_dir=batch_dir, explicit_args=explicit_args,
                           arg_sources=arg_sources,
                           resume_binding=run_binding, run_plan=plan)
        except Exception as me:
            log(f"[manifest] 台账写入失败（不影响本步产物）: {type(me).__name__}: {me}")

    def refresh_status():
        """步骤边界重写 running 条目：两段式一次跑十几分钟，
        只在头尾写的话监控器全程看到的是"所有步骤 pending"。"""
        update_status(cfg, a.workflow, run_id, "running", extra=status_extra())

    ctx = {"cfg": cfg, "args": args, "run_id": run_id, "log": log,
           "outputs": {}, "wf_root": ROOT, "batch_dir": batch_dir,
           "workflow": a.workflow, "step_id": None,
           # 决定单用它区分"这批显式给的"与"yaml 默认值"（G13／decision_sheet.collect）
           "explicit_args": explicit_args}
    # S2 的有效计划不进 ctx（那等于扩模板命名空间）：它已经过机械校验，
    # 摘要写进 manifest 作执行证据（dump_manifest → write_manifest(run_plan=plan)）。

    log(f"=== 工作流 {a.workflow} 开始 run_id={run_id} args={args} ===")
    log(f"报告: {report.path}（双击打开，运行中自动刷新）")
    update_status(cfg, a.workflow, run_id, "running", extra=status_extra())
    report.write(running=True)
    t0 = time.time()
    cur_sid = None
    step_params = {}
    try:
        for i, step in enumerate(raw_steps, 1):
            sid = steps_meta[i - 1]["id"]
            cur_sid = sid
            ctx["step_id"] = sid
            ctx["step_label"] = step.get("label")
            tasks.raise_if_cancel_requested(ctx, f"step:{sid}")
            if sid in resume_done:
                # --resume：上次已成功的步骤不再重跑（不占 GPU、不重复烧钱），
                # 产物从台账回填，保证后续步骤的 {{那一步.files}} 仍然可用。
                # 计划 W5a：状态用 done + restored=true，不用 skipped 代替——
                # 条件跳过（gate auto 失败那种）仍单独用 skipped。
                report.set(sid, "done")
                report.state[sid]["restored"] = True
                log(f"↷ 步骤 {sid} 上次已 done（--resume {resume_from}），恢复产物并标 done(restored=true)")
                if sid in resume_outputs:
                    ctx["outputs"][sid] = resume_outputs[sid]
                    ctx[sid] = resume_outputs[sid]
                refresh_status()
                continue
            tname = step.get("task")
            if tname not in REGISTRY:
                raise ValueError(f"步骤 {sid}: 未知任务类型 {tname}（可用: {list(REGISTRY)}）")
            params = render({k: v for k, v in step.items()
                             if k not in CONTROL_KEYS}, ctx)
            step_params[sid] = params if isinstance(params, dict) else {}
            log(f"▶ 步骤 {sid} ({tname}) 开始")
            report.set(sid, "running")
            refresh_status()
            st = time.time()
            out = REGISTRY[tname](params, ctx)
            ctx["outputs"][sid] = out
            ctx[sid] = out   # 让 {{步骤id.字段}} 按文档直接可用
            el = time.time() - st
            imgs = out.get("files") if isinstance(out, dict) else None
            log(f"✔ 步骤 {sid} 完成（{el:.1f}s）: "
                f"{json.dumps(out, ensure_ascii=False)[:300]}")
            report.set(sid, "done", elapsed=el, images=imgs)
            dump_manifest()      # 每步落一次台账：停在关口或中途崩了也留得住参数
            refresh_status()
        log(f"=== 工作流完成，总耗时 {time.time() - t0:.1f}s ===")
        dump_manifest()
        update_status(cfg, a.workflow, run_id, "success", extra=status_extra())
        report.finish(True)
    except tasks.RunCancelled as e:
        dump_manifest()
        log(f"■ 工作流按请求停止：{e}")
        if cur_sid:
            report.set(cur_sid, "cancelled", detail=str(e))
        update_status(cfg, a.workflow, run_id, "cancelled", str(e),
                      extra=status_extra())
        report.finish(False, detail="已按请求停止，不再提交后续步骤。")
        sys.exit(5)
    except GateAwaiting as e:
        dump_manifest()
        log(f"◆ 停在人工关口: {e}")
        if cur_sid:
            report.set(cur_sid, "awaiting_human", detail=str(e))
        update_status(cfg, a.workflow, run_id, "awaiting_human", str(e),
                      extra=status_extra())
        report.finish(False, detail=str(e))
        sys.exit(3)
    except GateDenied as e:
        log(f"✘ 关口被否: {e}")
        if cur_sid:
            report.set(cur_sid, "failed", detail=str(e))
        update_status(cfg, a.workflow, run_id, "denied", str(e), extra=status_extra())
        report.finish(False, detail=str(e))
        sys.exit(4)
    except KeyboardInterrupt:
        log("✘ 工作流被手动中断")
        if cur_sid:
            report.set(cur_sid, "failed", detail="手动中断")
        update_status(cfg, a.workflow, run_id, "error", "手动中断（Ctrl-C）",
                      extra=status_extra())
        report.finish(False, detail="已手动中断。")
        sys.exit(130)
    except Exception as e:
        dump_manifest()
        log(f"✘ 工作流失败: {type(e).__name__}: {e}")
        log(traceback.format_exc().splitlines()[-1])
        if cur_sid:
            report.set(cur_sid, "failed", detail=str(e))
        update_status(cfg, a.workflow, run_id, "error",
                      f"{type(e).__name__}: {e}", extra=status_extra())
        report.finish(False, detail=humanize_error(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
