# -*- coding: utf-8 -*-
"""「尺寸不留代码兜底」的防回归钉（2026-10-03 用户裁：删除硬编码，全部强制要求显式配置）。

这条裁定本身是**行为变更**，但它最容易以一种很隐蔽的方式被悄悄回退：
以后某个地方又写了一个 `p.get("width", 640)`，测试全绿、流程照跑，
只是"没配置"又变回了"代码替人配"。所以这里钉两层：

  A. 写法层 lint：`tasks.py / run.py / webui.py` 里**不允许**出现
     `get("<尺寸键>", <数字>)` —— 走 ast，不吃注释和文档字符串
     （本项目有过「探针被我写的说明文字污染」的账）。
  B. 行为层：缺尺寸必须**报错**，报错文本必须把两条补法说清楚；
     有尺寸必须精确注入模板（含 scale_by 折算）。

反向自证在 A 里：给一段故意写坏的样本，lint 必须抓到它——
否则这条 lint 是永远绿的摆设（假阴比假阳更坏）。
"""
import ast
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent        # engine/
sys.path.insert(0, str(ROOT))
import tasks as T                                    # noqa: E402

SIZE_KEYS = {"width", "height", "output_width", "output_height"}
SCANNED = ("tasks.py", "run.py", "webui.py")


# ── A. 写法层：不许再有尺寸默认值 ────────────────────────────────
def _is_num(d):
    return (isinstance(d, ast.Constant) and isinstance(d.value, (int, float))
            and not isinstance(d.value, bool))


def size_default_hits(text):
    """源码文本里「尺寸带数字默认值」的三种长相，一种都不能漏。

    走 ast 不走全文 grep：注释和文档字符串里出现 `width = 1920` 不算违例，
    全文 grep 会把它算进去（本项目真有过「探针被我写的说明污染」那笔账）。
      1) `p.get("width", 640)`       —— 取值时替人凑一个数
      2) `def f(width=1920)`         —— 签名默认值（同一个坏，只是换了个数位）
      3) `width = width or 1920`     —— 空值兜底（_normalize_clip 历史上就这么写）
    """
    hits = []
    for node in ast.walk(ast.parse(text)):
        # 1) dict.get(尺寸键, 数字)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) >= 2):
            key = node.args[0]
            if isinstance(key, ast.Constant) and key.value in SIZE_KEYS and _is_num(node.args[1]):
                hits.append((node.lineno, key.value, node.args[1].value))
        # 2) 函数签名的数字默认值（普通参数 + 仅位置 + 关键字三种都覆盖）
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pairs = list(zip(reversed(a.args or []), reversed(a.defaults or [])))
            pairs += list(zip(reversed(a.posonlyargs or []), reversed(a.defaults or [])))
            pairs += list(zip(a.kwonlyargs or [], a.kw_defaults or []))
            for arg, dflt in pairs:
                if arg.arg in SIZE_KEYS and _is_num(dflt):
                    hits.append((dflt.lineno, arg.arg, dflt.value))
        # 3) `尺寸名 or 数字`
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            names = [v.id for v in node.values if isinstance(v, ast.Name) and v.id in SIZE_KEYS]
            nums = [v for v in node.values if _is_num(v)]
            for nm in names:
                for nu in nums:
                    hits.append((node.lineno, nm, nu.value))
    return hits


def test_no_size_default_left_in_the_code():
    for name in SCANNED:
        p = ROOT / name
        assert p.is_file(), "扫描对象 %s 不在——这条测试已经空跑" % p
        # 2026-10-19 修：原来 encoding="utf-8"，带 BOM 的文件会把 U+FEFF 读成正文字符，
        # 后面 compile/解析当场 SyntaxError ⇒ 该文件其实没被扫到（假绿比假红坏）。
        # utf-8-sig 对有/无 BOM 都正确。
        hits = size_default_hits(io.open(p, encoding="utf-8-sig").read())
        assert not hits, "%s 又长出尺寸兜底：%s" % (name, hits)


def test_the_lint_itself_would_catch_a_regression():
    """反向验证：lint 不是永远绿的摆设。"""
    bad = 'w = p.get("width", 640)\nh = p.get("height", 960)'
    assert size_default_hits(bad) == [(1, "width", 640), (2, "height", 960)], bad
    # 写法不同也必须抓到（int() 包一层、别的键名）
    assert size_default_hits('x = int(p.get("output_width", 1920))'), "包一层就漏 ⇒ 假阴"
    # 签名默认值／空值兜底这两种新长相也必须抓到（以前只抓 .get(k, 数字)，是假阴）
    assert size_default_hits("def _norm(src, width=1920):\n    return src"), "签名默认漏了"
    assert size_default_hits("def _norm(src, *, height=1080):\n    return src"), "关键字默认漏了"
    assert size_default_hits("width = width or 1920"), "`or` 兜底漏了"
    # 不该抓的别乱抓：没默认值、默认值不是数字、键不是尺寸
    assert not size_default_hits('x = p.get("width")')
    assert not size_default_hits('x = p.get("steps", 28)')
    assert not size_default_hits('x = p.get("width", None)')
    assert not size_default_hits("def f(width=None):\n    return width"), "None 默认不算硬编码"
    assert not size_default_hits('w = p.get("width") or p.get("fallback")'), "两个非数值兜底"


# ── B. 行为层：_need_explicit_int 的四种情形 ─────────────────────
def test_params_value_wins_and_string_is_accepted():
    # --set 传进来的就是字符串；渲染后的 args 也可能是字符串，都要认
    assert T._need_explicit_int({"width": "832"}, {}, "width", "测试") == 832
    assert T._need_explicit_int({"width": 1024}, {}, "width", "测试") == 1024


def test_falls_back_to_workflow_args_not_to_code():
    """第二层只允许是**人写的 args**（yaml 顶层 args ＋ --set 都汇到这里）。"""
    ctx = {"args": {"height": 1216}}
    assert T._need_explicit_int({}, ctx, "height", "测试") == 1216


def test_missing_size_raises_and_tells_how_to_fix():
    with pytest.raises(RuntimeError) as e:
        T._need_explicit_int({"prompt": "x"}, {"args": {}}, "width", "comfyui 出图")
    msg = str(e.value)
    assert "没有显式配置" in msg, msg
    # 报错必须给**可执行的补法**，否则人只能回来读代码
    assert "params" in msg and "--set width=" in msg, msg
    # 并且不许把决定权悄悄转交给"取向"：aspect_ratio 不造像素
    assert "aspect_ratio" in msg, msg


def test_empty_string_is_not_a_value():
    """`width: ""` 在 yaml 里很常见（占位没填），不能当成"配置过了"。"""
    with pytest.raises(RuntimeError):
        T._need_explicit_int({"width": "  "}, {"args": {}}, "width", "测试")


def test_non_numeric_and_fractional_are_both_rejected():
    with pytest.raises(RuntimeError, match="不是数字"):
        T._need_explicit_int({"width": "1024*2"}, {}, "width", "测试")
    # 像素没有小数；四舍五入就是机器替人改尺寸
    with pytest.raises(RuntimeError, match="整数"):
        T._need_explicit_int({"width": 832.5}, {}, "width", "测试")


def test_explicit_size_returns_plain_ints_not_tuples():
    """曾经返回过 (值, 来源标签)：调用方把元组当尺寸塞进图里，比硬编码更隐蔽。"""
    w, h = T._explicit_size({"width": 768, "height": 1024}, {}, "测试")
    assert (w, h) == (768, 1024)
    assert isinstance(w, int) and isinstance(h, int), type(w)


# ── B2. 真模板：尺寸必须精确落进 KSampler／EmptyLatentImage ────────
TPL = {
    "pos": {"class_type": "CLIPTextEncode", "inputs": {"text": "__PROMPT__"}},
    "lat": {"class_type": "EmptyLatentImage",
            "inputs": {"width": "__W__", "height": "__H__", "batch_size": 1}},
    "ks": {"class_type": "KSampler",
           "inputs": {"model": ["m", 0], "seed": "__SEED__", "steps": "__STEPS__",
                      "width": "__W__", "height": "__H__"}},
}


def test_build_graph_injects_exact_size():
    g = T.build_graph(TPL, {"prompt": "p", "width": 896, "height": 1152}, 1)
    assert g["ks"]["inputs"]["width"] == 896
    assert g["lat"]["inputs"]["height"] == 1152


def test_build_graph_scale_by_folds_final_to_base():
    """一步式出成品：YAML 写成品尺寸，KSampler 用基图尺寸（4x 放大模板）。"""
    g = T.build_graph(TPL, {"prompt": "p", "width": 2560, "height": 3840,
                            "scale_by": 4}, 1)
    assert (g["ks"]["inputs"]["width"], g["ks"]["inputs"]["height"]) == (640, 960)


def test_build_graph_refuses_to_invent_a_size():
    with pytest.raises(RuntimeError, match="没有显式配置"):
        T.build_graph(TPL, {"prompt": "p"}, 1)


def test_video_graph_builder_also_requires_explicit_size():
    """`build_graph_video` / `build_graph_control` 签名里没有 ctx，
       所以它们只吃这一步的 params——这是有意的：模板步的尺寸不该被远处 args 顶掉。"""
    with pytest.raises(RuntimeError):
        T._size_from_params({"prompt": "p"}, "width", "出片模板")
    assert T._size_from_params({"width": 720}, "width", "出片模板") == 720


# ── C. 现役 workflow 侧：每条产尺寸的流都必须自己把尺寸写全 ─────────
# 这条不是"测今天的账"，是**以后新增一条流忘了配尺寸就会被抓**——
# 代码兜底删了以后，那种遗漏的表现是跑到那一步才 RuntimeError，
# 而跑一半才炸是最贵的（前面的 GPU 时间白花），所以把它钉在提交前。
CONSUMERS = {"comfyui": ("width", "height"), "auto": ("width", "height"),
             "video": ("width", "height"), "control": ("width", "height"),
             "h3_movie": ("output_width", "output_height")}


def _declared(step, keys, args):
    """按 run.py 的两层口径判：步骤 params 有，或顶层 args 有（--set 也汇到 args）。"""
    from run import render, CONTROL_KEYS
    ctx = {"cfg": {}, "args": args, "run_id": "R", "outputs": {}}
    params = {k: v for k, v in step.items() if k not in CONTROL_KEYS}
    bad = []
    for k in keys:
        raw = params.get(k, args.get(k))
        if isinstance(raw, str) and "{{" in raw:
            raw = render(raw, ctx, strict=False)
        if isinstance(raw, str) and raw.strip().startswith("{{"):
            raw = None                       # 引了个 args 里根本没有的键
        try:
            v = int(float(str(raw).strip())) if raw not in (None, "") else 0
        except ValueError:
            v = 0
        if v <= 0:
            bad.append(k)
    return bad


def test_every_live_workflow_declares_its_size():
    from run import CONTROL_KEYS                          # noqa: F401
    import yaml
    wf_dir = ROOT / "workflows"
    checked, offenders = 0, []
    for f in sorted(wf_dir.glob("*.yaml")):
        doc = yaml.safe_load(io.open(f, encoding="utf-8")) or {}
        args = doc.get("args") or {}
        for st in doc.get("steps") or []:
            task = str(st.get("task") or "")
            if task not in CONSUMERS:
                continue
            checked += 1
            miss = _declared(st, CONSUMERS[task], args)
            if miss:
                offenders.append("%s[%s] 缺 %s" % (f.name, st.get("id") or task, miss))
    assert checked >= 10, "只量到 %d 步 ⇒ task 名单过期了，这条测试是空跑的" % checked
    assert not offenders, "这些现役步骤没显式配尺寸，跑到那儿会当场报错：%s" % offenders

# ── D. 失败时机：缺尺寸必须在**碰服务之前**停，别先把 GPU 时间烧完 ──────
def test_missing_size_fails_before_touching_comfyui(monkeypatch, tmp_path):
    """以前尺寸闸门在出完图之后才读——人忘配尺寸要先把 count 张烧完才报错，
       连 ComfyUI 都会被顺手拉起来。这条钉住"先检查、再碰服务"。"""
    called = {"ensure": 0, "post": 0}

    def boom(ctx):
        called["ensure"] += 1
        return "http://127.0.0.1:1"

    class NoPost:
        def post(self, *a, **k):
            called["post"] += 1
            raise AssertionError("没尺寸却已经把任务提交给 ComfyUI 了")

    monkeypatch.setattr(T, "ensure_comfyui", boom)
    monkeypatch.setattr(T, "SESSION", NoPost())
    with pytest.raises(RuntimeError, match="没有显式配置"):
        T.t_comfyui({"workflow": "comfy/draft_sdxl_api.json", "prompt": "p", "count": 1},
                    {"cfg": {"comfyui": {"output_dir": str(tmp_path)}},
                     "wf_root": str(tmp_path), "batch_dir": str(tmp_path),
                     "args": {}, "log": lambda m: None})
    assert called["ensure"] == 0, "尺寸还没检查就去拉服务了"
    assert called["post"] == 0
