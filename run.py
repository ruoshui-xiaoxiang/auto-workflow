# -*- coding: utf-8 -*-
"""auto-workflow 引擎入口。

用法:
  python run.py <workflow> [--set key=value ...]
  python run.py --list

一个工作流 = workflows\\ 下一个 YAML；任务类型在 tasks.py 注册。
新增工作流只需新增 YAML，不改引擎代码。
"""
import argparse
import html as _html
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from tasks import REGISTRY  # noqa: E402

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
                  "files": "整理 / 归档文件", "shell": "执行命令"}
TASK_HINTS = {"llm": "把主题改写成模型听得懂的提示词",
              "comfyui": "调用 ComfyUI 生成图片",
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
                cells.append(
                    f'<figure class="cell" data-idx="{idx}" onclick="tg(this)">'
                    f'<span class="badge">{idx}</span>'
                    f'<img loading="lazy" src="{_html.escape(rel_src(f, self.path))}" alt="img{idx}">'
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
 .box.done{{border-left-color:#2e9e5b}} .box.failed{{border-left-color:#d64545}} .box.skipped{{border-left-color:#b08a2e}}
 .sid{{font-size:11px;color:#7d8590}} .name{{font-size:15px;font-weight:600;margin:2px 0}}
 .hint{{font-size:12px;color:#9aa2ad}} .el{{font-size:13px;margin-top:6px;color:#cfd4da}}
 .st{{font-size:11px;margin-top:2px;color:#7d8590}}
 main{{padding:0 26px 30px}} h3{{font-size:14px;color:#cfd4da;margin:18px 0 8px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
 .cell{{margin:0;position:relative;cursor:pointer;border:2px solid transparent;border-radius:6px;overflow:hidden;background:#1c2129}}
 .cell.sel{{border-color:#2f7fd6}} .cell img{{width:100%;display:block}}
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


def write_manifest(path, run_id, workflow, outputs):
    """逐张记录 index/seed/file/prompt/尺寸/步数 —— 编号选图与精修复现的依据。"""
    images, idx = [], 0
    for sid, out in outputs.items():
        if not isinstance(out, dict):
            continue
        files = out.get("files") or []
        seeds = out.get("seeds") or []
        for i, f in enumerate(files):
            idx += 1
            images.append({"index": idx, "step": sid, "file": str(f),
                           "seed": seeds[i] if i < len(seeds) else None,
                           "prompt": out.get("prompt", ""),
                           "width": out.get("width"), "height": out.get("height"),
                           "steps": out.get("steps")})
    data = {"run_id": run_id, "workflow": workflow,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "images": images}
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
    if "显存不足" in msg:
        return ("显存不够：显卡正被别的模型占着。\n"
                "怎么办：先关掉别的模型（桌面工具里点「停止所有模型」），"
                "或等当前生图跑完再试。")
    if "启动超时" in msg:
        return ("模型启动超时。\n"
                "怎么办：看本次日志里 launcher 的输出，通常是显存被占、"
                "或模型路径/端口配置不对。")
    if "兜底链全部失败" in msg:
        return ("所有 LLM 后端都不可用。\n"
                "怎么办：检查 config.yaml 的 fallback_chain，"
                "以及每个后端对应的 launcher 能不能手动跑通。")
    if "找不到 manifest" in msg or "编号不存在" in msg:
        return f"选图参数不对：{msg}\n怎么办：打开上一次的 HTML 报告，确认编号后重试。"
    if "未知任务类型" in msg:
        return f"{msg}\n怎么办：任务类型要在 tasks.py 里注册过才能用。"
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
        for h in hist:
            if h.get("run_id") != run_id and h.get("status") == "running":
                h["status"] = "error"
                h["detail"] = "中断（进程未正常收尾）"
    # 一次运行会写 2~3 次（running → success/error），按 run_id 覆盖而非堆条目，
    # 否则 30 条上限只装得下十几次运行
    hist[:] = [h for h in hist if h.get("run_id") != run_id]
    hist.insert(0, entry)
    data["history"] = hist[:30]
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="auto-workflow 引擎")
    ap.add_argument("workflow", nargs="?", help="workflows\\ 下的 YAML 名（不带扩展名）")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    help="覆盖工作流参数, 如 --set count=3 --set theme=xxx")
    ap.add_argument("--list", action="store_true", help="列出可用工作流")
    a = ap.parse_args()

    wf_dir = ROOT / "workflows"
    if a.list or not a.workflow:
        for f in sorted(wf_dir.glob("*.yaml")):
            w = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            print(f"{f.stem:24s} {w.get('description', '')}")
        return

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    wf_file = wf_dir / f"{a.workflow}.yaml"
    if not wf_file.exists():
        print(f"工作流不存在: {wf_file}", file=sys.stderr)
        sys.exit(2)
    wf = yaml.safe_load(wf_file.read_text(encoding="utf-8"))

    run_id = time.strftime("%Y%m%d_%H%M%S")
    args = dict(wf.get("args") or {})
    for s in a.sets:
        k, _, v = s.partition("=")
        args[k.strip()] = auto_cast(v.strip())

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
    reserved = {"cfg", "args", "run_id", "log", "outputs", "wf_root", "batch_dir"}
    clash = [m["id"] for m in steps_meta if m["id"] in reserved]
    if clash:
        print(f"步骤 id 与引擎保留字冲突: {clash}（保留字: {sorted(reserved)}）",
              file=sys.stderr)
        sys.exit(2)

    log = Logger(Path(cfg["log_dir"]) / f"{a.workflow}_{run_id}.log")
    report = RunReport(batch_dir / f"{a.workflow}_{run_id}.html",
                       a.workflow, run_id, steps_meta)
    manifest_path = batch_dir / f"{a.workflow}_{run_id}.manifest.json"

    def status_extra():
        return {"report": str(report.path), "manifest": str(manifest_path),
                "parent_run": parent_run, "picked": picked_idx,
                "steps": [{"id": s["id"],
                           "status": report.state.get(s["id"], {}).get("status",
                                                                       "pending"),
                           "elapsed": report.state.get(s["id"], {}).get("elapsed")}
                          for s in steps_meta]}

    def refresh_status():
        """步骤边界重写 running 条目：两段式一次跑十几分钟，
        只在头尾写的话监控器全程看到的是"所有步骤 pending"。"""
        update_status(cfg, a.workflow, run_id, "running", extra=status_extra())

    ctx = {"cfg": cfg, "args": args, "run_id": run_id, "log": log,
           "outputs": {}, "wf_root": ROOT, "batch_dir": batch_dir}

    log(f"=== 工作流 {a.workflow} 开始 run_id={run_id} args={args} ===")
    log(f"报告: {report.path}（双击打开，运行中自动刷新）")
    update_status(cfg, a.workflow, run_id, "running", extra=status_extra())
    report.write(running=True)
    t0 = time.time()
    cur_sid = None
    try:
        for i, step in enumerate(raw_steps, 1):
            sid = steps_meta[i - 1]["id"]
            cur_sid = sid
            tname = step.get("task")
            if tname not in REGISTRY:
                raise ValueError(f"步骤 {sid}: 未知任务类型 {tname}（可用: {list(REGISTRY)}）")
            params = render({k: v for k, v in step.items()
                             if k not in CONTROL_KEYS}, ctx)
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
            refresh_status()
        log(f"=== 工作流完成，总耗时 {time.time() - t0:.1f}s ===")
        write_manifest(manifest_path, run_id, a.workflow, ctx["outputs"])
        update_status(cfg, a.workflow, run_id, "success", extra=status_extra())
        report.finish(True)
    except KeyboardInterrupt:
        log("✘ 工作流被手动中断")
        if cur_sid:
            report.set(cur_sid, "failed", detail="手动中断")
        update_status(cfg, a.workflow, run_id, "error", "手动中断（Ctrl-C）",
                      extra=status_extra())
        report.finish(False, detail="已手动中断。")
        sys.exit(130)
    except Exception as e:
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
