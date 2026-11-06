"""auto-workflow WebUI —— 本地网页操作界面（只读壳 + 子进程管理）。

用法：
  python webui.py            # 起服务（默认 127.0.0.1:8787）
  start-webui.bat            # 双击：拉起 + 健康轮询 + 自动开浏览器

定位（C 完整版）：
  - B 底线防呆：默认只露输入框和按钮，参数全藏高级折叠区；错误翻成人话；
                绝不写回 YAML / config / 产物，只读；不提供任何删除能力。
  - A 高级区：  LoRA / 尺寸 / 步数 等在折叠区可改；"显示原始信息"开关给原始输出。
  - 插件口：    status.json 是稳定契约，QS 监控器后续可作插件接入，本模块不约束第三者。

实现：Python 3.12 标准库 http.server，零外部依赖；HTML 内嵌本文件末尾。
引擎不变：只调 `python run.py <wf> --set k=v` 子进程，不 import run（避免耦合）。
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import base64
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import yaml

ROOT = Path(__file__).resolve().parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
LOG_DIR = Path(CFG["log_dir"])
# 10-02 批1 GAP-E1：以前这里直接 `Path(CFG["output_root"])` 读 config 里的**字面量**，
# 而 `run.py` 是按 `pool_root/<project>/批次` 现推的——同一个值两套取法。
# 后果：切了项目以后 webui 列的还是上一个项目的批次夹（它拿的是写死的那行）。
# 现在统一走 delivery_root（叶子模块、无依赖，不破本文件"不 import run"的既定边界）。
from delivery_root import config_literal_is_fresh, delivery_root  # noqa: E402

OUT_ROOT = Path(delivery_root(CFG))
STATUS_FILE = Path(CFG["status_file"])
WF_DIR = ROOT / "workflows"
COMFYUI_CFG = CFG.get("comfyui", {})

# 云端 API 设置：存 `E:\密钥文件`（用户纪律：密钥只放这，不入代码库/工程目录）
SETTINGS_FILE = Path("E:/密钥文件/webui_settings.json")
SETTINGS_LEGACY = ROOT / "settings.json"   # 旧位置（迁移用，读不到新文件时回退）

# 实际模型库候选：工作流/出图真正读取的模型所在（D 盘优先后备）。E 盘 ComfyUI 里的
# 模型与 D 盘是同一份物理文件（硬链接），这里只做展示，不改任何路径配置。
MODEL_LIB_CANDIDATES = ["D:\\Models\\ComfyUI",
                        Path(COMFYUI_CFG.get("root", "")) / "ComfyUI" / "models"]

HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # 回退旧位置（迁移期兼容）
    if SETTINGS_LEGACY.exists():
        try:
            return json.loads(SETTINGS_LEGACY.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_settings(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    # 迁移完成：删掉旧位置，避免两处漂移
    if SETTINGS_LEGACY.exists():
        try:
            SETTINGS_LEGACY.unlink()
        except Exception:
            pass


# 多模态（看图判分）配置：默认读 `E:\密钥文件\阿里多模态.txt`（DashScope 按量 V，免费额度）；
# 也可在 webui 设置面板覆盖（settings.json 的 "vl" 段）。
VL_KEY_FILE = Path("E:/密钥文件/阿里多模态.txt")


def load_vl_config() -> dict:
    """返回 {"api_key","base_url","model"}。优先级：settings.vl > 阿里多模态.txt > 内置默认。"""
    s = load_settings().get("vl") or {}
    key = s.get("api_key") or ""
    base = s.get("base_url") or ""
    model = s.get("model") or ""
    if not key and VL_KEY_FILE.exists():
        lines = VL_KEY_FILE.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            key = lines[0].strip()
        if len(lines) > 1:
            base = lines[1].strip().rstrip("/")
    return {"api_key": key,
            "base_url": base or "https://dashscope.aliyuncs.com/compatible-mode",
            "model": model or "qwen-vl-plus"}


def score_image(image_path: str) -> dict:
    """[2026-11-04 已退役] 云端多模态美学判分——审美判定交给人，机器只判可验证缺陷。

    本体 `tasks.vl_score_image` 已随 `@task("auto")` 闭环一起摘除（不是只摘注册）。
    这里保留函数名是为了**调用点报错报得清楚**：以前直接 `from tasks import vl_score_image`
    会在运行期抛 ImportError，看起来像这个 UI 坏了，而不是这条判分线被裁掉了。
    """
    raise RuntimeError(
        "[判分已退役] VL 美学判分（0-100 分＋扣分理由）已于 2026-11-04 摘除：\n"
        "⇒ 原因：用户裁定「所有带美学判定的都交给人来判，机器只负责能实际判定的缺陷」\n"
        "⇒ 替代：人眼三分类审片（审片站 approved／flagged／rejected ＋ 飞书目审）；"
        "要事实在场核查走 vl_qc（谁在场／动作／瑕疵）\n"
        "⇒ 正身：backups/_治理_20261104/归档件/审美判定退役_20261104/tasks_py_退役前.py")

# ---- 参数白名单：common = 默认区（open `高级`折叠区 = only common 之外的 advanced）----
# 未知参数整体拒绝（422）。值类型由 run.py 的 auto_cast 决定，这里只管字段可改不可改。
WHITELIST = {
    "image_draft_batch": {
        "common": ["theme", "count"],
        "advanced": ["prompt", "use_llm_polish", "width", "height",
                     "steps", "loras", "seed"],
    },
    "image_refine": {
        "common": ["manifest", "pick"],
        "advanced": ["tile", "steps", "upscale_by", "denoise"],
    },
    "image_batch_draft": {
        "common": ["theme", "count"],
        "advanced": ["prompt", "use_llm_polish", "width", "height", "scale_by"],
    },
    "llm_fallback_test": {"common": [], "advanced": []},
    "selftest": {"common": [], "advanced": []},
}
DEFAULT_META = {  # 前端渲染用：label / 类型 / 提示（能自动推导的则留空）
    "theme": {"label": "主题", "type": "text",
              "hint": "LLM 润色关闭时不生效，请改高级参数里的英文提示词"},
    "count": {"label": "数量", "type": "number", "min": 1},
    "prompt": {"label": "英文提示词", "type": "textarea",
               "hint": "LLM 润色关闭时直接用作提示词"},
    "use_llm_polish": {"label": "LLM 润色", "type": "bool"},
    "use_llm": {"label": "LLM 润色", "type": "bool"},
    "width": {"label": "宽", "type": "number", "min": 64},
    "height": {"label": "高", "type": "number", "min": 64},
    "scale_by": {"label": "放大倍数", "type": "number", "min": 1,
                 "hint": "宽高 = 成品尺寸；引擎按此折算基图（一步式 4x）"},
    "steps": {"label": "步数", "type": "number", "min": 1},
    "loras": {"label": "LoRA", "type": "lora",
              "hint": "点下拉添加已装的 LoRA 与强度，留空 = 关掉所有 LoRA"},
    "seed": {"label": "种子", "type": "text",
             "hint": "留空 = 每张随机（默认）"},
    "manifest": {"label": "草稿批次（manifest）", "type": "text",
                 "hint": "用草稿完成后自动填写的值"},
    "pick": {"label": "挑的编号", "type": "text",
             "hint": "草稿报告/网格里挑的编号，逗号分隔"},
    "tile": {"label": "分块大小", "type": "number", "min": 128},
    "upscale_by": {"label": "放大倍数", "type": "number", "min": 1.0},
    "denoise": {"label": "重绘强度", "type": "number", "min": 0.0, "max": 1.0, "step": 0.01},
    "threshold": {"label": "达标分数", "type": "number", "min": 0, "max": 100,
                  "hint": "AI 判分达到即收图（默认 78）"},
    "max_tries": {"label": "最大重试轮数", "type": "number", "min": 1, "max": 8,
                  "hint": "低分时改写提示词重跑，最多几轮（默认 3）"},
    "rewrite_mode": {"label": "改写模式", "type": "select",
                     "options": [["text", "文本 LLM 改写（省，VL判分→文本LLM改）"],
                                 ["vl", "VL 看图直改（贵，信息无损）"]],
                     "hint": "低分重试时由谁改写提示词"},
}
FALLBACK_META = {"label": "参数", "type": "text"}

# ---- 运行决定单的槽（10-02 批 5-2／G13）：入口必须在这儿，不然"每批问人"落不了地 ----
# 清单**不在这里抄一份**：从 channels_registry.run_slots 现推（同 decision_sheet 的取法）。
# 读不到就如实留着，不硬编三个名字——硬编就是第二份抄本，表改了这里不会跟。
def _run_level_slot_meta():
    try:
        from decision_sheet import slot_defs, TIER_RUN
        slots, problem = slot_defs()
        if problem:
            raise RuntimeError(problem)
        meta = {}
        for s in [x for x in slots if x["tier"] == TIER_RUN]:
            meta[s["slot"]] = {
                "label": s["label"] or s["slot"],
                "type": "bool" if s["slot"] in ("use_llm_polish", "enable_audio") else "text",
                "hint": "G13 必填的运行决定（值归人，机器不代填、不判好坏）",
            }
            for a in (s.get("accepts") or []):
                meta[a] = dict(meta[s["slot"]],
                               label=(s["label"] or s["slot"]) + "（现役别名）")
        return meta, None
    except Exception as e:
        return {}, "%s: %s" % (type(e).__name__, e)


RUN_SLOT_META, RUN_SLOT_LOAD_ERROR = _run_level_slot_meta()
DEFAULT_META.update(RUN_SLOT_META)
if RUN_SLOT_LOAD_ERROR:
    print("[webui] 运行决定单槽清单读不到（%s）⇒ 表单里不会出现这些槽，"
          "真跑时 G13 会拦；这是读不到，不是没有要求" % RUN_SLOT_LOAD_ERROR,
          file=sys.stderr)

# 步骤任务类型 -> 中文名（步骤没写 label 时用）—— 对应 tasks.py 的任务注册表
STEP_TASK_NAMES = {"llm": "润色提示词", "comfyui": "生成图片",
                   "video": "H3 出视频", "h3_movie": "多镜一键成片",
                   "gate": "关口", "refine": "精修放大", "files": "整理归档",
                   "shell": "执行命令", "auto": "闭环自动出图（AI 判分重试）"}

# 工作流显示名（下拉里的可读名；空 = 用原名）。value 永远用文件名，不改引擎。
WF_DISPLAY_NAMES = {
    "image_draft_batch": "批量草稿（两段式 · 挑图后精修）",
    "image_batch_draft": "一步出成品（4x 放大）",
    "image_refine": "精修放大（对草稿按编号）",
    # [2026-11-04 退役] auto_draft（闭环自动出图·AI 判分·自动重试）已从面板撤下：
    # 那条链的驱动力是云端美学分，用户裁「审美判定交给人」。桩在 workflows/auto_draft.yaml，
    # 替代＝image_draft_batch 出草稿交人挑 → image_refine 按编号精修。
    "h3_i2va_video": "H3 首帧视频（人工审）",
    "h3_i2va_batch": "H3 首帧视频（无人值守）",
    "h3_ref2va_video": "H3 多参考视频（主力出片）",
    "h3_one_click_movie": "H3 多镜一键成片",
}

# ---- 运行中的子进程（同一时刻最多一个） ----
_proc: subprocess.Popen | None = None
_proc_lock = threading.Lock()


# ---------------------------------------------------------------- 工作流 schema
def workflow_meta(name: str):
    """读 workflow YAML：description + args 默认值 + 字段分组（common/advanced）。"""
    f = WF_DIR / f"{name}.yaml"
    if not f.exists():
        return None
    w = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    args_defaults = w.get("args") or {}
    wl = WHITELIST.get(name, {"common": [], "advanced": []})
    common = [a for a in wl["common"] if a in args_defaults]
    advanced = [a for a in wl["advanced"] if a in args_defaults]
    if not name.startswith("selftest"):
        # 自测不该依赖人填过的单（否则自测永远红＝没有自测），所以只往真出片的流里加槽
        for k in list(RUN_SLOT_META):
            if k not in args_defaults and k not in common and k not in advanced:
                advanced.append(k)   # YAML 没这个 args 也照样给入口：值永远留空等人填
    # 白名单没列、但 YAML 里有的参数也放进 advanced（兜底：新字段不至于被藏没）
    known = set(wl["common"]) | set(wl["advanced"])
    for k in args_defaults:
        if k not in known:
            advanced.append(k)
    fields = {}
    for k in list(common) + list(advanced):
        meta = dict(DEFAULT_META.get(k, FALLBACK_META))
        if k in RUN_SLOT_META:
            # 运行决定单的槽**一律不预填**：yaml 里那句 `use_llm_polish: false` 是**流级默认**，
            # 不是这批的人给的值（10-02 实测：预填会让表单提交时把它当"人给过的"回传，
            # G13 就被绕开了）。留空 + required_decision 标记，让人自己勾。
            meta["value"] = None
            meta["required_decision"] = True
        else:
            meta.setdefault("value", args_defaults.get(k))
        fields[k] = meta
    return {"name": name,
            "display_name": WF_DISPLAY_NAMES.get(name) or name,
            "description": w.get("description", ""),
            "steps": [{"id": s.get("id"),
                       "label": s.get("label") or STEP_TASK_NAMES.get(
                           s.get("task"), s.get("id") or "")}
                      for s in (w.get("steps") or [])],
            "common": common, "advanced": advanced, "fields": fields,
            "decision_slots": sorted(RUN_SLOT_META),
            "decision_slots_error": RUN_SLOT_LOAD_ERROR}


def all_workflows():
    return sorted({f.stem for f in WF_DIR.glob("*.yaml")})


def comfyui_loras():
    """从 ComfyUI 运行时自动枚举已装的 LoRA（含子目录）。

    来源：/object_info/LoraLoader 的 lora_name 选项（官方 API 直接给全列表，自动
    覆盖 D 盘优化模型库）。失败（ComfyUI 没起/版本差异）时回退扫描本地目录。
    返回 ["flux\\Hanfu_Elegant_Flux.safetensors", ...]（后端归一为 / 分隔路径）。
    """
    base = (COMFYUI_CFG.get("base_url") or "http://127.0.0.1:8189").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/object_info/LoraLoader", timeout=5) as r:
            oi = json.loads(r.read().decode("utf-8"))
        names = (oi["LoraLoader"]["input"]["required"]["lora_name"][0] or "").split()
        names = [n.strip() for n in names if n.strip()]
        if names:
            return sorted(set(names))
    except Exception:
        pass
    # 回退：直接扫模型目录（E 盘路径与 D 盘硬链接同一份）
    for cand in MODEL_LIB_CANDIDATES:
        lora_root = Path(cand) / "loras"
        if lora_root.is_dir():
            out = []
            for f in sorted(lora_root.rglob("*.safetensors")):
                out.append(str(f.relative_to(lora_root)).replace("\\", "/"))
            if out:
                return out
    return []


def out_batches():
    """列出 out\\ 下的批次夹：run_id / 内含报告与 manifest / 草稿与成品数。"""
    if not OUT_ROOT.is_dir():
        return []
    rows = []
    for d in sorted(OUT_ROOT.iterdir()):
        if not d.is_dir():
            continue
        docs = [p.name for p in d.glob("*.html")]
        mans = [p.name for p in d.glob("*.manifest.json")]
        draft_dir, final_dir = d / "draft", d / "final"
        drafts = list(draft_dir.glob("*.png")) if draft_dir.is_dir() else []
        finals = list(final_dir.glob("*.png")) if final_dir.is_dir() else []
        if not docs and not drafts and not finals:
            continue
        n_d, n_f = len(drafts), len(finals)
        status = "done" if n_f > 0 else ("draft" if n_d > 0 else "failed")
        rows.append({"run_id": d.name, "reports": docs, "manifests": mans,
                     "n_draft": n_d, "n_final": n_f, "status": status})
    return rows


def batch_detail(run_id: str) -> dict | None:
    # 批次夹名 = 引擎生成的 run_id（YYYYMMDD_HHMMSS），纯 ASCII；其它一律拒绝
    if not (isinstance(run_id, str) and re.fullmatch(r"\d{8}_\d{6}", run_id)):
        return None
    d = OUT_ROOT / run_id
    if not d.is_dir():
        return None
    out = {"run_id": run_id, "reports": [], "manifests": [], "images": []}
    for f in sorted(d.glob("*.html")):
        out["reports"].append(f.name)
    man_file = None
    for f in sorted(d.glob("*.manifest.json")):
        out["manifests"].append(f.name)
        if man_file is None:
            man_file = f
    if man_file is not None:
        try:
            man = json.loads(man_file.read_text(encoding="utf-8"))
            out["manifest"] = man
            for img in man.get("images", []):
                rel = None
                raw = str(img.get("file", ""))
                p = Path(raw)
                if p.is_absolute():
                    try:
                        rel = str(p.resolve().relative_to(d.resolve()))
                    except ValueError:
                        rel = None
                elif (d / raw).exists():
                    rel = raw
                if rel:
                    out["images"].append({
                        "index": img.get("index"), "file": rel.replace("\\", "/"),
                        "step": img.get("step"), "seed": img.get("seed"),
                        "width": img.get("width"), "height": img.get("height"),
                        "prompt": str(img.get("prompt", ""))[:200]})
        except Exception:
            pass
    draft_dir, final_dir = d / "draft", d / "final"
    if draft_dir.is_dir():
        out["n_draft"] = len(list(draft_dir.glob("*.png")))
    if final_dir.is_dir():
        out["n_final"] = len(list(final_dir.glob("*.png")))
    return out


def _safe_out(path: str) -> Path | None:
    """把 /out/... 校验成 OUT_ROOT 内绝对路径；越界返回 None。"""
    p = (OUT_ROOT / path).resolve()
    if not p.is_relative_to(OUT_ROOT.resolve()):
        return None
    if not p.is_file():
        return None
    return p


# ---------------------------------------------------------------- 子进程管理
def _proc_alive() -> bool:
    with _proc_lock:
        p = _proc
        if p is None:
            return False
        poll = getattr(p, "poll", None)
        return poll is None or poll() is None


def start_run(workflow: str, params: dict) -> dict:
    global _proc
    if _proc_alive():
        return {"ok": False, "error": "已有运行在进行中，请先等待或停止"}
    cmd = [sys.executable, str(ROOT / "run.py"), workflow]
    for k, v in params.items():
        cmd += ["--set", f"{k}={v}"]
    logf = open(LOG_DIR / f"webui_{time.strftime('%Y%m%d_%H%M%S')}.log",
                "w", encoding="utf-8")
    env = dict(os.environ)
    settings = load_settings()
    # 无条件注入云端 key（cloud + dashscope），所有 LLM 步骤走云端兜底链
    cloud = settings.get("cloud") or {}
    if cloud.get("api_key"):
        env["AW_CLOUD_API_KEY"] = cloud["api_key"]
    dashscope = settings.get("dashscope") or {}
    if dashscope.get("api_key"):
        env["AW_DASHSCOPE_API_KEY"] = dashscope["api_key"]
    vl_model = ""
    for pp in ("cloud", "dashscope"):
        vl_model = (settings.get(pp) or {}).get("vl_model") or vl_model
    if vl_model:
        env["AW_VL_MODEL"] = vl_model
    _proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env,
        stdout=logf, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"ok": True, "cmd": " ".join(str(c) for c in cmd),
            "log": str(logf.name), "pid": _proc.pid}


def stop_run() -> dict:
    global _proc
    with _proc_lock:
        if _proc is None or _proc.poll() is not None:
            return {"ok": False, "error": "没有正在进行的运行"}
        pid = _proc.pid
        try:
            _proc.terminate()          # 引擎捕获 KeyboardInterrupt -> rc 130 -> status error
        except Exception as e:
            return {"ok": False, "error": f"停止失败: {e}"}
        return {"ok": True, "pid": pid}


def current_status() -> dict:
    data = {"proc": None, "status": None}
    with _proc_lock:
        if _proc is not None:
            rc = _proc.poll()
            data["proc"] = {"pid": _proc.pid,
                            "running": rc is None,
                            "rc": None if rc is None else int(rc)}
    if STATUS_FILE.exists():
        try:
            j = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            lr = j.get("last_run")
            proc_dead = (_proc is None) or (_proc.poll() is not None)
            if lr and lr.get("status") == "running" and proc_dead:
                lr["status"] = "error"
                lr["detail"] = ("工作流进程已退出但未更新状态（可能崩溃），已重置"
                                if _proc is not None else
                                "工作流被另一个 webui 实例拉起，当前实例无法跟踪（已重置状态）")
            data["status"] = lr
            data["history"] = j.get("history") or []
        except Exception:
            pass
    return data


# ---------------------------------------------------------------- HTTP 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "auto-workflow-webui/0.1"

    # ---- 基础 ----
    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        payload = body if isinstance(body, str) else json.dumps(
            body, ensure_ascii=False, indent=2)
        data = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, code: int, msg: str):
        self._send(code, {"error": msg})

    def log_message(self, *args):
        pass  # 不刷屏

    # ---- 路由 ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        q = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            return self._send(200, PAGE_HTML, "text/html; charset=utf-8")
        if path == "/api/workflows":
            return self._send(200, {
                "workflows": [workflow_meta(n) for n in all_workflows()]})
        if path == "/api/loras":
            return self._send(200, {"loras": comfyui_loras(), "defaults": {
                "flux\\Hanfu_Elegant_Flux.safetensors": 0.4,
                "flux\\Beauty_Enhancer_Flux.safetensors": 0.3,
                "flux\\Ancient_Palace_Flux.safetensors": 0.3}})
        if path == "/api/status":
            return self._send(200, current_status())
        if path == "/api/info":
            libs = []
            for c in MODEL_LIB_CANDIDATES:
                p = Path(c)
                if p.is_dir():
                    libs.append({"path": str(p), "exists": True})
                else:
                    libs.append({"path": str(p), "exists": False})
            return self._send(200, {"model_lib": libs,
                                    "out_root": str(OUT_ROOT),
                                    "engine_dir": str(WF_DIR.parent),
                                    # 画布入口地址跟着 config 走，别在页面里写死端口
                                    # （2026-09-22 修：按钮原本硬编码 8188，那是已退役的
                                    #   旧便携实例，点下去必然"拒绝连接"）
                                    "comfyui_base": (COMFYUI_CFG.get("base_url")
                                                     or "http://127.0.0.1:8189")})
        if path == "/api/cloud":
            # 返回已存云端设置（key 脱敏：只显示尾 4 位）；支持两个 profile：cloud / dashscope
            settings = load_settings()
            profiles = {}
            for p in ("cloud", "dashscope"):
                prof = settings.get(p) or {}
                mask = (prof.get("api_key") or "")
                shown = (mask[-4:]) if len(mask) > 4 else ("已设置" if mask else "")
                default_url = "https://dashscope.aliyuncs.com/compatible-mode" if p == "dashscope" else ""
                profiles[p] = {"base_url": prof.get("base_url") or default_url,
                               "model": prof.get("model", ""),
                               "vl_model": prof.get("vl_model", "qwen-vl-plus"),
                               "api_key_tail": shown, "has_key": bool(mask)}
            return self._send(200, {"profiles": profiles})
        if path == "/api/batches":
            return self._send(200, {"batches": out_batches()})
        if path == "/health":
            return self._send(200, {"ok": True})
        if path.startswith("/api/batch/"):
            rid = path[len("/api/batch/"):]
            bd = batch_detail(rid)
            if bd is None:
                return self._error(404, f"批次不存在: {rid}")
            return self._send(200, bd)
        if path == "/api/score":
            run_id = q.get("run", [""])[0]
            file = q.get("file", [""])[0]
            fp = _safe_out(f"{run_id}/{file}")
            if fp is None:
                return self._error(403, "图片路径越界或不存在")
            try:
                return self._send(200, score_image(str(fp)))
            except Exception as e:
                return self._error(400, str(e))
        if path.startswith("/out/"):
            inner = path[len("/out/"):]
            fp = _safe_out(inner)
            if fp is None:
                return self._error(403, "路径越界或不存在")
            try:
                raw = fp.read_bytes()
            except Exception as e:
                return self._error(404, f"读取失败: {e}")
            mt = {"text/html": "text/html; charset=utf-8",
                  "application/json": "application/json; charset=utf-8"}.get(
                fp.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", mt)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self._error(404, f"未知路径: {path}")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._error(400, "请求体不是合法 JSON")
        if path == "/api/run":
            return self._run(body)
        if path == "/api/stop":
            return self._send(200, stop_run())
        if path == "/api/cloud":
            return self._save_cloud(body)
        if path == "/api/cloud/test":
            return self._test_cloud(body)
        self._error(404, f"未知路径: {path}")

    def _save_cloud(self, body: dict):
        profile = str(body.get("profile") or "cloud").strip()
        if profile not in ("cloud", "dashscope"):
            return self._error(400, f"未知 profile: {profile}")
        settings = load_settings()
        prof = settings.get(profile) or {}
        for k in ("base_url", "model", "vl_model"):
            if k in body:
                prof[k] = str(body[k] or "").strip()
        if body.get("api_key"):            # 留空 = 保留旧的
            prof["api_key"] = str(body["api_key"]).strip()
        settings[profile] = prof
        save_settings(settings)
        return self._send(200, {"ok": True})

    def _test_cloud(self, body: dict):
        """用传入（或已存）的 key 实测一次 chat 调用，返回是否连通。"""
        profile = str(body.get("profile") or "cloud").strip()
        if profile not in ("cloud", "dashscope"):
            return self._error(400, f"未知 profile: {profile}")
        settings = load_settings()
        prof = settings.get(profile) or {}
        key = str(body.get("api_key") or prof.get("api_key") or "")
        base = str(body.get("base_url") or prof.get("base_url") or
                   ("https://dashscope.aliyuncs.com/compatible-mode" if profile == "dashscope"
                    else "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode")).rstrip("/")
        model = str(body.get("model") or prof.get("model") or
                    ("qwen-plus" if profile == "dashscope" else "qwen3.8-max"))
        if not key:
            return self._send(400, {"error": "先填入 API Key"})
        payload = json.dumps({"model": model,
                              "messages": [{"role": "user", "content": "ping"}],
                              "max_tokens": 4}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode("utf-8"))
                txt = d["choices"][0]["message"]["content"]
                return self._send(200, {"ok": True, "reply": str(txt)[:80]})
        except urllib.error.HTTPError as e:
            return self._send(400, {"error": f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:160]}"})
        except Exception as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})

    def _run(self, body: dict):
        wf = body.get("workflow")
        params = body.get("params") or {}
        meta = workflow_meta(wf)
        if meta is None:
            return self._error(404, f"工作流不存在: {wf}")
        fields = meta["fields"]
        unknown = [k for k in params if k not in fields]
        if unknown:
            return self._error(422, f"不允许的参数: {unknown}")
        # 空字符串视为默认（保留 YAML 默认/随机行为）
        cleaned = {k: v for k, v in params.items() if v not in ("", None)}
        r = start_run(wf, cleaned)
        if not r["ok"]:
            return self._error(409, r["error"])
        return self._send(200, r)


# ---------------------------------------------------------------- 页面（内嵌 HTML）
PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>auto-workflow · 可视化操作台</title>
<style>
:root{
  --bg:#fafaf9; --panel:#ffffff; --line:#e5e7eb; --brand:#0f172a;
  --brand-2:#374151; --brand-3:#6b7280; --text:#0a0a0a; --faint:#9ca3af;
  --ok:#16a34a; --warn:#d97706; --block:#dc2626; --skip:#9ca3af; --llm:#7c3aed;
  --radius:10px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;
     background:var(--bg);color:var(--text);font-size:14px;line-height:1.6}
.wrap{max-width:1080px;margin:0 auto;padding:20px 24px 60px}
/* 顶栏（TRAE 风：透明底 + 左 2px 竖线） */
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
       border-left:2px solid var(--brand);padding-left:14px;margin-bottom:18px}
header h1{font-size:20px;font-weight:650;letter-spacing:.2px}
header .sub{color:var(--faint);font-size:12px}
.eng{color:var(--faint);font-size:12px;margin-left:auto}
.eng b{color:var(--brand-2)}
.pill{display:inline-block;padding:1px 10px;border-radius:999px;
      background:var(--panel);border:1px solid var(--line);color:var(--brand-3);font-size:12px}
.pill.idle{color:var(--faint)} .pill.ok{color:var(--ok);border-color:var(--ok)}
.pill.run{color:var(--llm);border-color:var(--llm)}
.pill.err{color:var(--block);border-color:var(--block)}
section{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
        padding:16px 18px;margin-bottom:16px}
section h2{font-size:13px;color:var(--brand-2);margin-bottom:12px;font-weight:600}
label{display:block;color:var(--brand-3);font-size:12px;margin:10px 0 4px}
input[type=text],input[type=number],textarea,select{
  width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:8px;
  font-size:14px;background:#fff;color:var(--text)}
textarea{min-height:64px;resize:vertical;font-family:ui-monospace,Consolas,monospace;font-size:12px}
input:focus,textarea:focus,select:focus{outline:2px solid #c7d2fe;border-color:var(--brand)}
.row{display:flex;gap:12px;flex-wrap:wrap}
.row>div{flex:1;min-width:160px}
/* 工作流选择行：下拉框与 ComfyUI 按钮同行、按钮对齐 select 上沿 */
.wfrow{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}
.wfselect{flex:1;min-width:220px}
.wfcomfy{flex:0 0 auto;padding-top:32px}   /* label(约16px)+行距，按钮顶部对齐 select */
.hint{color:var(--faint);font-size:11px;margin-top:3px}
/* LoRA 点选控件 */
.lora-box{display:flex;flex-direction:column;gap:8px}
.lora-chips{display:flex;flex-wrap:wrap;gap:6px}
.lora-chip{display:inline-flex;align-items:center;gap:6px;background:#f1f5f9;
  border:1px solid var(--line);border-radius:999px;padding:3px 8px 3px 6px;font-size:12px}
.lora-chip b{color:var(--brand-2);font-weight:600}
.lora-chip .lora-str{width:64px;padding:2px 6px;border:1px solid var(--line);
  border-radius:6px;font-size:12px;background:#fff}
.lora-chip .lora-del{border:none;background:transparent;color:var(--faint);
  cursor:pointer;font-size:15px;line-height:1;padding:0 2px}
.lora-chip .lora-del:hover{color:var(--block)}
.hint2{color:var(--faint);font-size:12px}
button{border:1px solid var(--line);background:#fff;color:var(--brand-2);
  border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer;transition:.15s}
button:hover{border-color:var(--brand-3)}
button.primary{background:var(--brand);color:#fff;border-color:var(--brand)}
button.primary:hover{background:var(--brand-2)}
button.primary:disabled,button:disabled{opacity:.45;cursor:not-allowed}
button.danger{color:var(--block);border-color:var(--block)}
.actions{display:flex;gap:10px;margin-top:14px;align-items:center}
/* 高级折叠区 */
details{border:1px solid var(--line);border-radius:8px;margin-top:12px;background:#fff}
details summary{cursor:pointer;padding:9px 12px;color:var(--brand-3);font-size:13px;
  list-style:none;display:flex;align-items:center;gap:6px}
details summary::before{content:"▸";transition:.15s}
details[open] summary::before{transform:rotate(90deg)}
details .inner{padding:2px 14px 14px}
details .inner label:first-child{margin-top:4px}
#cloudBox{margin:0 0 16px;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius)}
#cloudBox summary{font-size:13px;color:var(--brand-3)}
/* 进度条 */
.steps{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.step{flex:1;min-width:120px;border:1px solid var(--line);border-left:4px solid var(--skip);
      border-radius:8px;padding:8px 10px;background:#fff}
.step .nm{font-size:13px;font-weight:600}
.step .st2{font-size:11px;color:var(--faint);margin-top:2px}
.step.running{border-left-color:var(--llm);background:#f5f3ff}
.step.done{border-left-color:var(--ok)} .step.failed{border-left-color:var(--block)}
.step .el{font-size:11px;color:var(--faint);margin-left:auto}
/* 错误 */
.errbox{background:#fdf2f2;border:1px solid #f5c2c2;border-radius:8px;
  padding:10px 12px;color:var(--block);font-size:13px;margin-top:10px;white-space:pre-wrap}
.raw{background:#14171c;color:#c9d1d9;border-radius:8px;padding:10px 12px;
  font-family:ui-monospace,Consolas,monospace;font-size:12px;margin-top:8px;
  white-space:pre-wrap;display:none;max-height:220px;overflow:auto}
/* 图片网格 */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:10px}
.cell{position:relative;border:2px solid var(--line);border-radius:8px;overflow:hidden;
      background:#fff;cursor:pointer}
.cell img{width:100%;display:block}
.cell .num{position:absolute;top:6px;left:6px;background:var(--brand);color:#fff;
           border-radius:5px;padding:0 7px;font-size:12px;z-index:2}
.cell.sel{border-color:var(--llm)}
.cell .meta{font-size:11px;color:var(--faint);padding:4px 6px}
.score-btn{display:inline-block;margin-top:4px;padding:2px 8px;border:1px solid var(--line);
  border-radius:6px;background:#fff;color:var(--brand-3);font-size:11px;cursor:pointer}
.score-btn:hover{border-color:var(--brand-3);color:var(--brand-2)}
.score-box{font-size:11px;color:var(--brand-2);padding:3px 6px 6px;line-height:1.5}
.score-box small{color:var(--faint)}
/* 历史 */
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--faint);font-weight:500;font-size:12px}
tr.p a{color:var(--llm);text-decoration:none}
tr.p a:hover{text-decoration:underline}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.tag{display:inline-block;padding:0 8px;border-radius:6px;font-size:11px}
.tag.success{color:var(--ok)} .tag.error{color:var(--block)}
.tag.running{color:var(--llm)} .tag:empty{display:none}
.tag.done{color:var(--ok)} .tag.draft{color:var(--warn)} .tag.failed{color:var(--block)}
footer{color:var(--faint);font-size:11px;margin-top:26px;text-align:center}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>auto-workflow 可视化操作台</h1>
  <span class="sub">云端生图 / 精修 · 只读操作，不碰配置</span>
  <span class="eng">引擎 <b id="engState">—</b> <span class="pill" id="engPill">—</span></span>
</header>

<!-- 运行区 -->
<section>
  <div class="wfrow">
    <div class="wfselect">
      <label>工作流</label>
      <select id="wfSel"></select>
      <div class="hint" id="wfDesc"></div>
    </div>
    <div class="wfcomfy">
      <button id="comfyBtn" title="打开 ComfyUI 原生节点画布（地址取自 config.yaml 的 comfyui.base_url）">打开 ComfyUI 原生页 ↗</button>
    </div>
  </div>
  <div id="commonFields"></div>
  <details id="advBox">
    <summary>高级参数</summary>
    <div class="inner" id="advFields"></div>
  </details>
  <div class="actions">
    <button id="runBtn" class="primary">开始出图</button>
    <button id="stopBtn" class="danger" style="display:none">停止本次运行</button>
    <span class="hint" id="runHint"></span>
  </div>
  <div id="stepsBox" style="display:none">
    <label>运行进度</label>
    <div class="steps" id="steps"></div>
    <div id="errBox"></div>
    <label><input type="checkbox" id="showRaw"> 显示原始信息 / 日志尾部</label>
    <div class="raw" id="rawBox"></div>
  </div>
</section>

<!-- 挑图 / 精修 -->
<section id="pickSec" style="display:none">
  <h2>这张批次选图 → 精修</h2>
  <div class="hint" id="pickHint"></div>
  <div class="grid" id="pickGrid"></div>
  <div class="actions">
    <button id="refineBtn" class="primary">精修选中的图</button>
    <span class="hint" id="refineHint"></span>
  </div>
</section>

<!-- 历史批次 -->
<section>
  <h2>历史批次</h2>
  <table><thead><tr><th>批次</th><th>草稿</th><th>成品</th><th>状态</th><th>报告 / 精修</th></tr></thead>
  <tbody id="histBody"></tbody></table>
</section>

<!-- 云端 API 设置 -->
<details id="cloudBox">
  <summary>云端 API 设置（LLM 润色走云，默认关）</summary>
  <div class="inner">
    <div class="row">
      <div>
        <label for="c_profile">云端服务</label>
        <select id="c_profile">
          <option value="cloud">百炼包月（token-plan，qwen3.8-max）</option>
          <option value="dashscope">百炼按量（DashScope，qwen-plus）</option>
        </select>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="c_base">Base URL（OpenAI 兼容，留空用默认）</label>
        <input type="text" id="c_base" placeholder="https://...">
      </div>
      <div>
        <label for="c_model">文本模型名</label>
        <select id="c_model"></select>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="c_vl_model">VL 判分模型名 <span class="hint2">(看图直改用)</span></label>
        <select id="c_vl_model"></select>
      </div>
    </div>
    <div class="row">
      <div>
        <label for="c_key">API Key <span id="c_keytip" class="hint2"></span></label>
        <input type="password" id="c_key" placeholder="sk-…（留空 = 保留已存的）">
      </div>
      <div style="display:flex;align-items:flex-end;gap:8px">
        <button id="cloudSave" class="primary">保存</button>
        <button id="cloudTest">测试连接</button>
      </div>
    </div>
    <div class="hint" id="cloudMsg"></div>
  </div>
</details>

<footer id="infoBar">引擎状态来自 status.json（只读插件口）· webui 只调 run.py 子进程 · 不写回任何配置</footer>
<div class="hint" id="modelLib" style="text-align:center;margin-top:6px"></div>
</div>

<script>
"use strict";
const $=id=>document.getElementById(id);
let WF={}, curWf=null, picked=new Set(), pollTimer=null;
const REFINE={manifest:"", pick:""};
let STEP_LABELS={}, lastStepsHtml="";   // 步骤中文名缓存 + 上次渲染的 HTML（防闪）
let LORA_LIST=[], LORA_DEFAULTS={};     // ComfyUI 已装 LoRA + 默认强度
const LORA_SEL={};                      // loras 字段名 -> [name:strength, ...]（下拉点选添加）

async function api(path, opts){
  const r=await fetch(path, opts);
  const j=await r.json().catch(()=>({error:"响应不是 JSON"}));
  if(!r.ok) throw new Error(j.error||("HTTP "+r.status));
  return j;
}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// ---- 错误人话化（映射到中文建议；原始信息另开关显示）----
const HUMANIZE=[
  [/显存|out of memory|cuda/i,"显存不够：先关掉别的占卡模型（桌面工具里点「停止所有模型」），或等当前生图跑完再试。"],
  [/命令失败|code=3/i,"该步骤触发了引擎的失败演示或异常命令（见下方原始信息）。若为 selftest 属设计如此。"],
  [/拒绝|refuse|时延|超时|timeout/i,"这一步超时了：单张耗时可能超过了引擎上限，或本机负载过高。可在高级参数里调小步数/数量后重试。"],
  [/找不到|FileNotFound|不存在/i,"文件/配置找不到：多半是批次被移动或手动删过。刷新历史看实际批次号。"],
  [/端口|拒绝连接|Connection|refused|拉不起|failed to start/i,"本机服务没起来或端口被占：引擎会自动拉起 ComfyUI，网络不佳时冷启动要几分钟，重试即可。"],
];
function humanize(detail){
  if(!detail) return "未知错误。打开「显示原始信息」看日志。";
  for(const [re,msg] of HUMANIZE){ if(re.test(detail)) return msg; }
  return "运行未完成，错误信息如下（打开「显示原始信息」可看完整日志）：";
}

// ---- 工作流表单 ----
async function loadWf(){
  const j=await api("/api/workflows");
  WF={}; STEP_LABELS={}; const sel=$("wfSel"); sel.innerHTML="";
  for(const w of j.workflows){
    WF[w.name]=w;
    for(const st of (w.steps||[])){ STEP_LABELS[st.id]=st.label||st.id; }
    const o=document.createElement("option");
    o.value=w.name; o.textContent=w.display_name||w.name; sel.appendChild(o);
  }
  sel.value="image_draft_batch"; switchWf();
}
function parseLoraValue(v){
  // "flux\\Hanfu_...:0.4,flux\\Beauty_...:0.3" -> [{name,strength}]
  if(!v) return [];
  return String(v).split(",").map(s=>s.trim()).filter(Boolean).map(s=>{
    const [name,str]=s.split(":");
    return {name, strength: str?parseFloat(str):1.0};
  });
}
function friendlyLora(n){
  // "flux\\Hanfu_Elegant_Flux.safetensors" -> "Hanfu_Elegant_Flux"
  return String(n).split(/[\\/]/).pop().replace(/\.safetensors$/i,"");
}
function fieldHtml(k,meta){
  const v=meta.value;
  const val=(v===undefined||v===null)?"":v;
  const base=`<label for="f_${k}">${esc(meta.label||k)}</label>`;
  let ctrl="";
  if(meta.type==="lora"){
    // LoRA：下拉点选添加；已选列表在下方；默认强度来自 ComfyUI 检测
    LORA_SEL[k]=LORA_SEL[k]||parseLoraValue(val);
    const addOpts=LORA_LIST.filter(n=>!LORA_SEL[k].some(x=>x.name===n))
      .map(n=>`<option value="${esc(n)}">${esc(friendlyLora(n))}</option>`).join("");
    const chips=LORA_SEL[k].map((x,i)=>`
      <span class="lora-chip" data-i="${i}">
        <input type="number" class="lora-str" value="${x.strength}" min="0" max="2" step="0.05" title="强度">
        <b>${esc(friendlyLora(x.name))}</b>
        <button class="lora-del" data-k="${k}" data-i="${i}">×</button></span>`).join("");
    ctrl=`<div class="lora-box" data-k="${k}">
        <select class="lora-add"><option value="">＋ 添加 LoRA…</option>${addOpts}</select>
        <div class="lora-chips">${chips||"<span class=hint2>未添加任何 LoRA</span>"}</div>
      </div>`;
  }else if(meta.type==="textarea"){
    ctrl=`<textarea id="f_${k}" placeholder="${esc(meta.hint||"")}">${esc(val)}</textarea>`;
  }else if(meta.type==="bool"){
    const ch=val===true||val===1||val==="true";
    ctrl=`<label class="chk"><input type="checkbox" id="f_${k}" ${ch?"checked":""}> ${esc(meta.hint||"")}</label>`;
  }else if(meta.type==="number"){
    ctrl=`<input type="number" id="f_${k}" value="${esc(val)}"
      ${meta.min!==undefined?`min="${meta.min}"`:""} ${meta.max!==undefined?`max="${meta.max}"`:""}
      ${meta.step!==undefined?`step="${meta.step}"`:""} step="any">`;
  }else if(meta.type==="select"){
    const opts=(meta.options||[]).map(o=>{
      const ov=Array.isArray(o)?o[0]:o, ol=Array.isArray(o)?o[1]:o;
      return `<option value="${esc(ov)}" ${String(val)===String(ov)?"selected":""}>${esc(ol)}</option>`;
    }).join("");
    ctrl=`<select id="f_${k}">${opts}</select>`;
  }else{
    ctrl=`<input type="text" id="f_${k}" value="${esc(val)}" placeholder="${esc(meta.hint||"")}">`;
  }
  const hint=meta.hint&&meta.type!=="bool"?`<div class="hint">${esc(meta.hint)}</div>`:"";
  return `<div>${base}${ctrl}${hint}</div>`;
}
function switchWf(){
  const w=WF[$("wfSel").value]; if(!w) return; curWf=w;
  $("wfDesc").textContent=w.description||"";
  $("commonFields").innerHTML=`<div class="row">${
    w.common.map(k=>fieldHtml(k,w.fields[k])).join("")||"<div class=hint>无需输入，直接开始</div>"}</div>`;
  $("advFields").innerHTML=`<div class="row">${
    w.advanced.map(k=>fieldHtml(k,w.fields[k])).join("")||"<div class=hint>无</div>"}</div>`;
  $("advBox").open=false;
  resetRunUI();
}
function gatherParams(fields){
  const p={};
  for(const k of fields){
    const el=$("f_"+k); if(!el) continue;
    const meta=curWf.fields[k];
    let v=el.value;
    if(meta.type==="bool"){ v=el.checked; }
    else if(meta.type==="lora"){
      v=(LORA_SEL[k]||[]).map(x=>`${x.name}:${x.strength}`).join(",");
    }
    else if(meta.type==="number"&&v!==""){ v=Number(v); }
    if(meta.type!=="bool"&&v==="") v="";
    p[k]=v;
  }
  return p;
}

// ---- 运行 / 轮询 ----
async function runWf(workflow){
  const w=WF[workflow]; if(!w) return;
  const params=gatherParams([...w.common,...w.advanced]);
  if(Object.prototype.hasOwnProperty.call(w.fields,'llm_backend')){
    params.llm_backend="cloud,dashscope";
  }
  $("runBtn").disabled=true; $("runHint").textContent="启动中…";
  try{
    await api("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({workflow,params})});
    $("runHint").textContent="已启动，正在轮询进度…";
    startPoll();
  }catch(e){
    $("runHint").textContent=""+e.message;
    $("runBtn").disabled=false;
  }
}
function startPoll(){
  if(pollTimer) clearInterval(pollTimer);
  pollTimer=setInterval(pollStatus,2000); pollStatus();
}
async function pollStatus(){
  try{
    const j=await api("/api/status");
    const s=j.status;
    const proc=j.proc;
    const procRunning=!!(proc&&proc.running);
    const statusRunning=!!(s&&s.status==="running");
    const running=procRunning||statusRunning;   // CLI 直跑时也能反映运行中
    const wfName=(s&&s.workflow)||curWf?.name;   // 引擎实际在跑的工作流优先
    if(running){
      $("engState").textContent="运行中";
      const pill=$("engPill");
      pill.className="pill run";
      pill.textContent="● "+wfName;
    }else if(s&&s.status==="success"){
      $("engState").textContent="空闲（上次：已完成）";
      const pill=$("engPill");
      pill.className="pill ok";
      pill.textContent="✔ 上次 "+wfName+" 完成";
    }else if(s&&s.status==="error"){
      $("engState").textContent="空闲（上次：失败）";
      const pill=$("engPill");
      pill.className="pill err";
      pill.textContent="✘ 上次 "+wfName+" 失败";
    }else{
      $("engState").textContent="空闲";
      const pill=$("engPill");
      pill.className="pill idle";
      pill.textContent="待命";
    }
    $("stopBtn").style.display=procRunning?"":"none";   // 只有 webui 拉起的进程才可停
    $("runBtn").disabled=running;
    if(s){
      if(running){
        renderSteps(s.steps||[],s.status);     // 运行中：显示实时步骤
      }else{
        hideSteps();                            // 空闲：收起步骤区，避免把历史当"正在跑"
      }
      if(s.status==="success"){ $("runHint").textContent="本次完成 ✔ 已刷新批次"; loadBatches(); }
      if(s.status==="error"){
        $("runHint").textContent="本次失败";
        showErr(s.detail||"");
      }
    }
    if(!running&&s&&["success","error"].includes(s.status)&&pollTimer){
      // 结束收尾：等一轮统一清理
      clearInterval(pollTimer); pollTimer=null;
    }
    if(!running&&s&&s.status==="running"&&pollTimer){ /* 引擎在跑但非本次拉起（如 CLI 直跑），继续轮询 */ }
  }catch(e){ /* 服务瞬断忽略 */ }
}
function renderSteps(steps,status){
  const box=$("stepsBox"); box.style.display="block";
  const ST_CN={pending:"等待",running:"进行中",done:"完成",failed:"失败",skipped:"跳过",success:"完成",error:"失败"};
  const html=steps.map(s=>{
    const st=s.status||"pending";
    const el=s.elapsed!=null?`${(+s.elapsed).toFixed(1)}s`:"…";
    const name=STEP_LABELS[s.id]||s.id;
    return `<div class="step ${esc(st)}"><div class="nm">${esc(name)}</div>
      <div class="st2">${esc(ST_CN[st]||st)} · ${el}</div></div>`;
  }).join("")||"<div class=hint>无步骤信息</div>";
  if(html!==lastStepsHtml){ $("steps").innerHTML=html; lastStepsHtml=html; }
}
function hideSteps(){
  // 空闲：收起步骤区，并清掉防闪缓存，下次运行重新铺开
  $("stepsBox").style.display="none";
  $("errBox").innerHTML=""; $("rawBox").textContent="";
  lastStepsHtml="";
}
function showErr(detail){
  const msg=humanize(detail);
  $("errBox").innerHTML=`<div class="errbox"><b>出错了：</b>${esc(msg)}</div>`;
  $("rawBox").textContent=detail||"（无原始信息）";
  $("rawBox").style.display=$("showRaw").checked?"block":"none";
}
function resetRunUI(){
  $("stepsBox").style.display="none"; $("errBox").innerHTML="";
  $("rawBox").textContent=""; $("pickSec").style.display="none";
}

// ---- 批次 / 挑图 ----
async function loadBatches(){
  try{
    const j=await api("/api/batches");
    const tb=$("histBody"); tb.innerHTML="";
    const all=[...(j.batches||[])].reverse();
    const STATUS_LABEL={done:"已完成",draft:"仅草稿",failed:"失败"};
    const SHOW_N=20;
    const showAll=window._batchesShowAll;
    const list=showAll?all:all.slice(0,SHOW_N);
    for(const b of list){
      const tr=document.createElement("tr");
      const rep=b.reports[0];
      const st=b.status||"failed";
      tr.innerHTML=`<td class="mono">${esc(b.run_id)}</td>
        <td>${b.n_draft??""}</td><td>${b.n_final??""}</td>
        <td><span class="tag ${st}">${esc(STATUS_LABEL[st]||st)}</span></td>
        <td>${rep?`<a href="/out/${b.run_id}/${esc(rep)}" target="_blank">报告</a>`:"—"}</td>`;
      tr.style.cursor="pointer";
      tr.onclick=()=>openPick(b.run_id);
      tb.appendChild(tr);
    }
    let btn=document.getElementById("batchesMoreBtn");
    if(all.length>SHOW_N){
      if(!btn){
        btn=document.createElement("div");
        btn.id="batchesMoreBtn";
        btn.style.cssText="text-align:center;margin:6px 0";
        tb.parentElement.after(btn);
      }
      btn.innerHTML=`<a href="#" onclick="window._batchesShowAll=!window._batchesShowAll;loadBatches();return false" class="mono" style="font-size:11px;color:var(--faint)">${showAll?"收起":"显示全部（"+all.length+"）"}</a>`;
      btn.style.display="block";
    }else if(btn){ btn.style.display="none"; }
  }catch(e){}
}
async function openPick(runId){
  const b=await api("/api/batch/"+runId).catch(()=>null);
  if(!b||!b.images||!b.images.length){ $("refineHint").textContent="该批次没有可挑的草稿"; return; }
  picked=new Set(); REFINE.manifest=runId; REFINE.pick="";
  $("pickSec").style.display="block";
  $("pickHint").textContent=`批次 ${runId}（草稿 ${b.images.length} 张）—— 点图选编号，右下“精修”放大 2 倍`;
  $("pickGrid").innerHTML=b.images.map(im=>{
    const idx=im.index!=null?im.index:0;
    return `<figure class="cell" data-i="${idx}" onclick="tg(${idx})">
      <span class="num">${idx}</span>
      <img loading="lazy" src="/out/${runId}/${esc(im.file)}">
      <div class="meta">${im.step||""}${im.width?` · ${im.width}×${im.height}`:""}
        <button class="score-btn" data-run="${runId}" data-file="${esc(im.file)}" title="云端 AI 看图判分">AI 评分</button></div>
      <div class="score-box"></div></figure>`;
  }).join("");
  $("refineHint").textContent="";
}
window.tg=function(i){
  if(picked.has(i)){ picked.delete(i); }
  else{ picked.add(i); }
  document.querySelectorAll("#pickGrid .cell").forEach(c=>{
    c.classList.toggle("sel",picked.has(+c.dataset.i)); });
  REFINE.pick=[...picked].sort((a,b)=>a-b).join(",");
};
// 精修直接走当前批次（无需切表单）
async function doRefine(){
  if(!REFINE.manifest||!REFINE.pick){ $("refineHint").textContent="先在网格里点选草稿编号"; return; }
  $("refineHint").textContent="精修已启动…（每张约 3 分钟）";
  try{
    await api("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({workflow:"image_refine",params:{manifest:REFINE.manifest,pick:REFINE.pick}})});
    // 切到精修工作流看进度
    $("wfSel").value="image_refine"; switchWf();
    startPoll();
  }catch(e){ $("refineHint").textContent=""+e.message; }
}

// ---- 事件 ----
// ---- 云端 API 设置 ----
const MODEL_GROUPS=[
  {g:"── 千问文本 ──",m:["qwen3.8-max","qwen3.7-plus","qwen3.8-flash","qwen-max","qwen-plus","qwen-turbo","qwen-long"]},
  {g:"── 第三方文本 ──",m:["deepseek-v4-pro","deepseek-v4-flash-0731","kimi-k3","glm-5.2","GLM-5.3","MiniMax-M3","mimo-v2.5-pro"]},
  {g:"── 代码生成 ──",m:["qwen-coder-plus"]}
];
const VL_MODELS=["qwen-vl-max","qwen-vl-plus","qwen3.5-omni-plus"];
function updateVlModelOptions(){
  const sel=$("c_vl_model");
  const cur=sel.value;
  sel.innerHTML="";
  VL_MODELS.forEach(m=>{const o=document.createElement("option");o.value=m;o.textContent=m;sel.appendChild(o);});
  if(cur&&VL_MODELS.includes(cur)) sel.value=cur;
}
function updateModelOptions(){
  const sel=$("c_model");
  const cur=sel.value;
  sel.innerHTML="";
  const all=[];
  MODEL_GROUPS.forEach(g=>{
    const og=document.createElement("optgroup");og.label=g.g;
    g.m.forEach(m=>{const o=document.createElement("option");o.value=m;o.textContent=m;og.appendChild(o);all.push(m);});
    sel.appendChild(og);
  });
  if(cur&&all.includes(cur)) sel.value=cur;
}
function loadCloudProfile(){
  const p=$("c_profile").value;
  updateModelOptions();
  updateVlModelOptions();
  (async()=>{ const j=await api("/api/cloud").catch(()=>null);
    if(j&&j.profiles&&j.profiles[p]){
      const prof=j.profiles[p];
      $("c_base").value=prof.base_url||"";
      if(prof.model){const sel=$("c_model");
        const opts=[...sel.options].map(o=>o.value);
        if(opts.includes(prof.model)) sel.value=prof.model;
        else{const o=document.createElement("option");o.value=prof.model;o.textContent=prof.model;sel.appendChild(o);sel.value=prof.model;}
      }
      if(prof.vl_model){const vsel=$("c_vl_model");
        const vopts=[...vsel.options].map(o=>o.value);
        if(vopts.includes(prof.vl_model)) vsel.value=prof.vl_model;
      }
      $("c_keytip").textContent=prof.has_key?`已设置（尾号 ${prof.api_key_tail||"…"}）`:"未设置";
    } })();
}

$("c_profile").onchange=()=>{updateModelOptions();loadCloudProfile();};
loadCloudProfile();
$("cloudSave").onclick=async()=>{
  const body={profile:$("c_profile").value, base_url:$("c_base").value.trim(), model:$("c_model").value.trim(), vl_model:$("c_vl_model").value.trim()};
  if($("c_key").value.trim()) body.api_key=$("c_key").value.trim();
  try{ await api("/api/cloud",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    $("cloudMsg").textContent=`已保存。${$("c_profile").selectedOptions[0].text} 的 key 已更新。`;
    $("c_key").value="";
    const j=await api("/api/cloud"); const prof=j.profiles[$("c_profile").value];
    $("c_keytip").textContent=prof.has_key?"已设置（尾号 "+prof.api_key_tail+"）":"未设置";
  }catch(e){ $("cloudMsg").textContent="保存失败："+e.message; }
};
$("cloudTest").onclick=async()=>{
  const body={profile:$("c_profile").value, base_url:$("c_base").value.trim(), model:$("c_model").value.trim(), vl_model:$("c_vl_model").value.trim()};
  if($("c_key").value.trim()) body.api_key=$("c_key").value.trim();
  $("cloudMsg").textContent="测试中…";
  try{ const j=await api("/api/cloud/test",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    $("cloudMsg").textContent="✅ 连接成功，回复："+j.reply;
  }catch(e){ $("cloudMsg").textContent="❌ "+e.message; }
};

$("wfSel").onchange=switchWf;
// 画布地址不再写死端口：默认 8189，随后由 /api/info 用 config.yaml 的值覆盖。
// （2026-09-22 前这里是 8188——已退役的旧便携实例，点下去只会"拒绝连接"）
var COMFY_BASE="http://127.0.0.1:8189";
$("comfyBtn").onclick=()=>window.open(COMFY_BASE,"_blank");
$("runBtn").onclick=()=>runWf(curWf.name);
$("stopBtn").onclick=async()=>{ await api("/api/stop",{method:"POST"}).catch(()=>{}); $("stopBtn").style.display="none"; };
$("showRaw").onchange=()=>{$("rawBox").style.display=$("showRaw").checked?"block":"none";};
$("refineBtn").onclick=doRefine;

// ---- LoRA 下拉点选添加（事件委托）----
document.addEventListener("change", (ev)=>{
  const add=ev.target.closest("select.lora-add");
  if(!add||!add.value) return;
  const box=add.closest(".lora-box"); const k=box.dataset.k;
  const str=LORA_DEFAULTS[add.value]!==undefined?LORA_DEFAULTS[add.value]:1.0;
  LORA_SEL[k]=LORA_SEL[k]||[];
  LORA_SEL[k].push({name:add.value, strength:str});
  add.value="";
  reflowLora(box,k);
});
document.addEventListener("click", (ev)=>{
  const btn=ev.target.closest("button.score-btn");
  if(btn){
    ev.stopPropagation();
    const cell=btn.closest(".cell"); const box=cell.querySelector(".score-box");
    box.textContent="评分中…（云端 VL，约 5-10s）";
    api(`/api/score?run=${encodeURIComponent(btn.dataset.run)}&file=${encodeURIComponent(btn.dataset.file)}`)
      .then(j=>{
        const dims=j.dims||{};
        box.innerHTML=`<b>${j.score!=null?j.score+" 分":"无法解析"}</b>`+
          (dims.face!=null?`　面 ${dims.face}/25 构 ${dims.compose}/25 质 ${dims.quality}/25 氛 ${dims.mood}/25`:"")+
          (j.reasons&&j.reasons.length?`<br><small>${esc(j.reasons.join("；"))}<br>${esc(j.suggestion||"")}</small>`:"");
      })
      .catch(e=>{ box.textContent="评分失败："+e.message; });
    return;
  }
  const del=ev.target.closest("button.lora-del");
  if(!del) return;
  const box=del.closest(".lora-box"); const k=box.dataset.k; const i=+del.dataset.i;
  LORA_SEL[k].splice(i,1);
  reflowLora(box,k);
});
document.addEventListener("input", (ev)=>{
  const inp=ev.target.closest("input.lora-str");
  if(!inp) return;
  const box=inp.closest(".lora-box"); const k=box.dataset.k; const i=+inp.closest(".lora-chip").dataset.i;
  LORA_SEL[k][i].strength=(+inp.value)||0;
});
function reflowLora(box,k){
  const addOpts=LORA_LIST.filter(n=>!LORA_SEL[k].some(x=>x.name===n))
    .map(n=>`<option value="${esc(n)}">${esc(friendlyLora(n))}</option>`).join("");
  box.querySelector("select.lora-add").innerHTML=`<option value="">＋ 添加 LoRA…</option>${addOpts}`;
  const chips=LORA_SEL[k].map((x,i)=>`
    <span class="lora-chip" data-i="${i}">
      <input type="number" class="lora-str" value="${x.strength}" min="0" max="2" step="0.05" title="强度">
      <b>${esc(friendlyLora(x.name))}</b>
      <button class="lora-del" data-k="${k}" data-i="${i}">×</button></span>`).join("");
  box.querySelector(".lora-chips").innerHTML=chips||"<span class=hint2>未添加任何 LoRA</span>";
}

loadWf(); loadBatches();
// 加载已装 LoRA（ComfyUI 自动检测），回来后若高级区已渲染则重绘
(async()=>{ const j=await api("/api/loras").catch(()=>null);
  if(j){ LORA_LIST=j.loras||[]; LORA_DEFAULTS=j.defaults||{};
    switchWf();   // 重新渲染表单，让 LoRA 下拉有选项
  } })();
// 打开页面即开始轮询一次：若引擎已在跑（本次会话或 CLI 直跑）立刻就能看到进度
(async()=>{ const j=await api("/api/status").catch(()=>null);
  if(j){ pollStatus(); } })();
// 显示实际模型库 / 产物 / 引擎目录（只展示，不涉路径修改）
(async()=>{ const i=await api("/api/info").catch(()=>null);
  if(i){
    const libs=(i.model_lib||[]).filter(x=>x.exists);
    const lib=libs.length?libs[0].path:"（未找到）";
    $("modelLib").textContent=`实际模型库: ${lib} · 产物: ${i.out_root}`;
    if(i.comfyui_base){ COMFY_BASE=i.comfyui_base;
      $("comfyBtn").title="打开 ComfyUI 原生节点画布（"+COMFY_BASE+"）"; }
  } })();
setInterval(loadBatches,10000);
</script>
</body>
</html>
"""

# ---------------------------------------------------------------- 启动
def pick_port():
    s = socket.socket()
    try:
        s.bind((HOST, DEFAULT_PORT))
        return DEFAULT_PORT
    except OSError:
        return None
    finally:
        s.close()


def main():
    port = pick_port()
    if port is None:
        print(f"[ERROR] 端口 {DEFAULT_PORT} 已被占用，请关掉占用程序（或改 webui.py DEFAULT_PORT）")
        sys.exit(1)
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}"
    print(f"auto-workflow WebUI: {url}")
    print(f"工作流目录: {WF_DIR}   产物: {OUT_ROOT}   状态: {STATUS_FILE}")
    _ok, _derived, _literal = config_literal_is_fresh(CFG)
    if not _ok:
        # config 里那行 output_root 字面量已经跟着 project 漂了。
        # 本进程不受影响（走 delivery_root），但**任何直接读字面量的代码会拿到上一个项目的落点**。
        print(f"⚠ config.yaml 的 output_root 字面量（{_literal}）与 project='{CFG.get('project')}' "
              f"派生值（{_derived}）不一致 —— 本面板已按派生值显示，"
              f"请把 config 那行改成派生值或清空，别留第二个事实源。")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()