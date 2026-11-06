# -*- coding: utf-8 -*-
"""S0 回归：把 2026-10-24 收尾语义反例（C01–C06）改写成**正确行为**断言。

来源：审计目录 本地视频工作流审计_20261023/证据/closeout_semantic_probes.py
     与 closeout_semantic_results.json（六条偏差复现，不是六条实现通过）。

本文件只写"应该怎样"，不复述 bug：
  · S0 阶段这些用例**预期为红**，代表已识别缺陷；不许 xfail/skip/放宽断言。
  · 修复归 S1/S2；修好后必须自然转绿，删用例或改期待值不算通过。
  · 全程隔离夹具：真实函数在内存/纯解析层执行，不触网、不起服务、不提交、不跑 GPU。
"""
import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

TESTS_DIR = Path(__file__).resolve().parent
ENGINE = TESTS_DIR.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TESTS_DIR))

import tasks as T                      # noqa: E402
import run_plan as RP                  # noqa: E402
import run as R                        # noqa: E402

# 1x1 PNG：真实可解码，避免"文件不存在/空夹具"盖住行为断言。
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
    "hQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture()
def media(tmp_path):
    first = tmp_path / "ref_first.png"
    second = tmp_path / "ref_second.png"
    first.write_bytes(_PNG)
    second.write_bytes(_PNG)
    return first, second


def _wf(name):
    return yaml.safe_load(
        (ENGINE / "workflows" / f"{name}.yaml").read_text(encoding="utf-8"))


def _plan(name, overrides):
    flow = _wf(name)
    args, sources = RP.merge_args(flow.get("args") or {}, {}, overrides)
    return RP.build_run_plan(ENGINE, name, flow, args, sources,
                             cfg={"project": "无音"}, tier="draft")


def _base_params():
    # 与收尾反例同一组纯建图参数；不代表真实生产档位。
    return {"prompt": "OFFLINE FIXTURE", "width": 736, "height": 416,
            "length": 124, "steps": 8,
            "lora": ("minimax_h3_fl2v_turbo_4step_v0.1_comfyui_alpha8-"
                     "T8-convert.safetensors"),
            "lora_strength": 1.0, "head_chunks": 4, "prefix": "OFFLINE",
            "two_pass": True, "two_pass_coarse_steps": 4,
            "two_pass_refine_steps": 4, "scale_by": 1.25}


# ============================================================ C01 取消归属
class _Resp:
    def __init__(self, data=None, status=200):
        self._data = data if data is not None else {}
        self.status_code = status

    def json(self):
        return self._data


class _FakeComfy:
    """内存服务：实现服务端已有的按 ID 取消语义（/api/jobs/{id}/cancel），
    外加旧路径会碰到的 /interrupt 与 /queue 删除，用来抓“迁怒别的任务”。

    未登记路由一律 404，不默认 200；每次调用都记实际返回码，这样“故障到底
    有没有送到被测函数”可以单独断言，不靠配置一个没被调用的接口冒充注入。"""

    def __init__(self, running=(), pending=(), history=(),
                 cancel_map=None, post_status=200, cancel_status=None,
                 remove_on_cancel=True):
        self.running = [[1, pid, {}, {}, []] for pid in running]
        self.pending = [[2, pid, {}, {}, []] for pid in pending]
        self.history = {pid: {"status": {"status_str": "success"}}
                        for pid in history}
        self.cancel_map = dict(cancel_map or {})
        self.post_status = post_status
        self.cancel_status = (post_status if cancel_status is None
                              else cancel_status)
        self.remove_on_cancel = remove_on_cancel
        self.calls = []

    def _record(self, method, url, status, **kw):
        self.calls.append({"method": method, "url": url, "status": status,
                           "json": kw.get("json")})

    def _status_for(self, url):
        return (self.cancel_status if "/api/jobs/" in url
                else self.post_status)

    def post(self, url, **kw):
        status = self._status_for(url)
        self._record("POST", url, status, **kw)
        if status != 200:
            return _Resp({"error": "injected failure"}, status)
        if url.endswith("/interrupt"):
            return _Resp({})
        if "/api/jobs/" in url and url.endswith("/cancel"):
            pid = url.rstrip("/").split("/")[-2]
            ok = bool(self.cancel_map.get(pid, False))
            if ok and self.remove_on_cancel:
                self.running = [x for x in self.running if x[1] != pid]
                self.pending = [x for x in self.pending if x[1] != pid]
            return _Resp({"cancelled": ok})
        if url.endswith("/queue"):
            delete = (kw.get("json") or {}).get("delete") or []
            if delete:
                self.pending = [x for x in self.pending if x[1] not in delete]
            return _Resp({})
        self.calls[-1]["status"] = 404
        return _Resp({"error": "unexpected route"}, 404)

    def get(self, url, **kw):
        self._record("GET", url, 200, **kw)
        if url.endswith("/queue"):
            return _Resp({"queue_running": self.running,
                          "queue_pending": self.pending})
        if "/history/" in url:
            pid = url.rstrip("/").split("/")[-1]
            return _Resp({pid: self.history[pid]} if pid in self.history else {})
        if url.endswith("/history"):
            return _Resp(self.history)
        if "/api/jobs/" in url:
            pid = url.rstrip("/").split("/")[-1]
            state = ("running" if any(x[1] == pid for x in self.running)
                     else "pending" if any(x[1] == pid for x in self.pending)
                     else "completed" if pid in self.history else None)
            if state:
                return _Resp({"id": pid, "status": state})
            self.calls[-1]["status"] = 404
            return _Resp({"error": "job not found"}, 404)
        self.calls[-1]["status"] = 404
        return _Resp({"error": "unexpected route"}, 404)

    def posts(self):
        return [c for c in self.calls if c["method"] == "POST"]

    def post_to(self, suffix):
        return [c for c in self.posts()
                if c["url"].rstrip("/").endswith(suffix)]

    def queue_posts(self):
        return self.post_to("/queue")

    def unexpected(self):
        return [c for c in self.calls if c["status"] == 404]


def _cancel(monkeypatch, fake, prompt_id, running, batch_dir=None):
    monkeypatch.setattr(T, "SESSION", fake)
    ctx = {"batch_dir": str(batch_dir)} if batch_dir else {}
    return T.cancel_submission(ctx, "http://offline.invalid", prompt_id,
                               running=running)


def _state(res):
    return str(res.get("state") or "").strip().lower()


_CANCELLED_STATES = {"cancelled", "cancel_dispatched", "canceled"}


def test_c01_finished_target_is_not_reported_cancelled(monkeypatch):
    """A 已结束、B 正在跑：取消 A 不得发无 ID 的全局中断，也不得确认已取消。"""
    fake = _FakeComfy(running=["OTHER_RUNNING"], history=["FINISHED_TARGET"],
                      cancel_map={"FINISHED_TARGET": False})
    res = _cancel(monkeypatch, fake, "FINISHED_TARGET", running=True)

    assert not any(c["url"].endswith("/interrupt") for c in fake.posts()), \
        "C01：目标已结束、别的任务在跑，取消却发了无 ID 的全局 /interrupt"
    assert not fake.queue_posts(), \
        "C01：已结束目标的取消仍在用 /queue 删除代替按 ID 语义"
    assert not fake.unexpected(), \
        f"C01：走到了未登记的 mock 路由：{fake.unexpected()}"
    assert res.get("confirmed") is False, \
        f"C01：A 已结束、B 仍在队列，却确认了取消：{res}"
    assert res.get("state") == "finished", \
        f"C01：已结束的任务没有单独表达为 finished：{res}"
    assert res.get("dispatched") is False, res
    assert _state(res) and _state(res) not in _CANCELLED_STATES, \
        f"C01：已结束的任务被表达成已取消：{res}"


def test_c01_pending_target_cancelled_without_touching_other(monkeypatch):
    """A 排队、B 正在跑：只按 ID 取消 A，不碰 B，也不用全局中断。"""
    fake = _FakeComfy(running=["OTHER_RUNNING"], pending=["TARGET"],
                      cancel_map={"TARGET": True})
    res = _cancel(monkeypatch, fake, "TARGET", running=False)

    assert res.get("confirmed") is True, f"C01：按 ID 取消成功却没确认：{res}"
    assert res.get("state") == "cancelled", f"C01：取消成功但终态不对：{res}"
    assert res.get("dispatched") is True, res
    assert _state(res) in _CANCELLED_STATES, f"C01：取消成功但状态不明确：{res}"
    assert [x[1] for x in fake.running] == ["OTHER_RUNNING"], \
        f"C01：取消 A 波及了正在跑的 B：{fake.running}"
    assert fake.post_to("/cancel"), \
        "C01：没有走服务端按 ID 取消端点 /api/jobs/{id}/cancel"
    assert not any(c["url"].endswith("/interrupt") for c in fake.posts()), \
        "C01：按 ID 取消仍发了无 ID 的全局 /interrupt"
    assert not fake.queue_posts(), \
        "C01：仍用 /queue 删除代替服务端按 ID 原子取消"
    assert not fake.unexpected(), \
        f"C01：走到了未登记的 mock 路由：{fake.unexpected()}"


def test_c01_unknown_id_is_not_reported_cancelled(monkeypatch):
    fake = _FakeComfy(running=["OTHER_RUNNING"], cancel_map={})
    res = _cancel(monkeypatch, fake, "GHOST_ID", running=True)

    assert res.get("confirmed") is False, \
        f"C01：未知 ID 不派发取消，却被确认成已取消：{res}"
    assert res.get("state") == "unknown", \
        f"C01：未知 ID 没有单独表达为 unknown：{res}"
    assert res.get("dispatched") is False, res
    assert _state(res) and _state(res) not in _CANCELLED_STATES, \
        f"C01：未知 ID 被表达成已取消：{res}"


def test_c01_cancel_api_failure_is_not_success(monkeypatch):
    """故障必须真实送达被测函数：所有已知 POST 都回 500，并断言回执里有 500。"""
    fake = _FakeComfy(running=["OTHER_RUNNING"],
                      cancel_map={"TARGET": True}, post_status=500)
    res = _cancel(monkeypatch, fake, "TARGET", running=True)

    delivered = [c for c in fake.posts() if c["status"] == 500]
    assert delivered, \
        f"C01：没有任何 500 真正送到取消函数：{fake.posts()}"
    assert res.get("confirmed") is False, \
        f"C01：取消路径实际收到 500，却仍确认已取消：{res}"
    assert res.get("state") == "api_error", \
        f"C01：API 失败没有单独表达为 api_error：{res}"
    assert _state(res) not in _CANCELLED_STATES and _state(res) != "", \
        f"C01：API 失败没有单独表达：{res}"
    assert any("500" in json.dumps(s, ensure_ascii=False) for s in res["steps"]), \
        f"C01：实际收到的 500 没落进回执：{res}"
    assert not fake.unexpected(), \
        f"C01：故障用例走到了未登记的 mock 路由：{fake.unexpected()}"


def test_c01_network_error_is_not_success(monkeypatch):
    """网络异常也必须单独落 api_error，不能因为“不在 queue”就确认取消。"""
    class Session:
        def __init__(self):
            self.calls = []
        def post(self, url, **kw):
            self.calls.append({"url": url, "error": "ConnectionError"})
            raise ConnectionError("injected network failure")
        def get(self, url, **kw):
            return _Resp({"queue_running": [["x", "OTHER", {}, {}, []]],
                          "queue_pending": []})

    fake = Session()
    monkeypatch.setattr(T, "SESSION", fake)
    res = T.cancel_submission({}, "http://offline.invalid", "TARGET",
                              running=True)
    assert res.get("state") == "api_error", res
    assert res.get("confirmed") is False, res
    assert "ConnectionError" in str(res.get("error")), res
    assert any("ConnectionError" in json.dumps(s, ensure_ascii=False)
               for s in res["steps"]), res


def test_c01_finished_and_unknown_states_are_distinct(monkeypatch):
    """“已完成/不存在/已取消/API 失败”必须分别表达，不能都靠 confirmed。"""
    finished = _cancel(
        monkeypatch,
        _FakeComfy(running=["OTHER"], history=["DONE"],
                   cancel_map={"DONE": False}),
        "DONE", running=True)
    unknown = _cancel(
        monkeypatch,
        _FakeComfy(running=["OTHER"], cancel_map={}),
        "GHOST", running=True)

    assert _state(finished) and _state(unknown), \
        f"C01：缺少可区分状态：finished={finished} unknown={unknown}"
    assert _state(finished) == "finished" and _state(unknown) == "unknown", \
        f"C01：已完成/未知 ID 的终态不对：{_state(finished)} / {_state(unknown)}"
    assert _state(finished) not in _CANCELLED_STATES
    assert _state(unknown) not in _CANCELLED_STATES


def test_c01_still_queued_after_dispatch_is_not_confirmed(monkeypatch):
    """服务端说 cancelled=true，但回读队列仍在（竞争/未落地）⇒ 不得确认。"""
    fake = _FakeComfy(running=["TARGET"], cancel_map={"TARGET": True},
                      remove_on_cancel=False)
    res = _cancel(monkeypatch, fake, "TARGET", running=True)
    assert res.get("dispatched") is True, res
    assert res.get("state") == "still_queued", res
    assert res.get("confirmed") is False, res
    assert res.get("still_queued") is True, res


def test_c01_not_dispatched_and_still_queued_are_separate(monkeypatch):
    """服务端明确 cancelled=false 且目标仍在队列 ⇒ not_dispatched，不是已取消。"""
    fake = _FakeComfy(pending=["TARGET"], cancel_map={"TARGET": False})
    res = _cancel(monkeypatch, fake, "TARGET", running=False)
    assert res.get("dispatched") is False, res
    assert res.get("state") == "not_dispatched", res
    assert res.get("still_queued") is True, res
    assert res.get("confirmed") is False, res


def test_c01_cancel_intent_is_written_for_running_run(monkeypatch, tmp_path):
    fake = _FakeComfy(running=["TARGET"], cancel_map={"TARGET": True})
    monkeypatch.setattr(T, "SESSION", fake)
    res = T.cancel_submission({"batch_dir": str(tmp_path), "run_id": "RUN-X"},
                              "http://offline.invalid", "TARGET", running=True)
    intent = json.loads((tmp_path / "cancel_intent.json").read_text(encoding="utf-8"))
    assert intent["prompt_id"] == "TARGET", intent
    assert intent["run_id"] == "RUN-X", intent
    assert res.get("state") == "cancelled"


# ============================================================ C02 模式切换
PANEL_INIT = (Path(r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/custom_nodes")
              / "comfyui-entertainment-panel" / "__init__.py")


def _panel_module():
    """载入真实面板后端；只调纯构造器 build_sets，不碰 build_spec/生产 config。"""
    assert PANEL_INIT.is_file(), f"面板后端不存在：{PANEL_INIT}"
    spec = importlib.util.spec_from_file_location(
        "entertainment_panel_selection_under_test", PANEL_INIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _registry_doc():
    return json.loads(
        (ENGINE / "channels_registry.json").read_text(encoding="utf-8"))


def _route_for(mode, recipe):
    """用面板自己的真源（registry.panel + recipe_matrix）解析实际工作流。"""
    reg = _registry_doc()
    assert mode in (reg["panel"].get("mode_tabs") or []), mode
    assert recipe in (reg["panel"].get("recipe_tabs") or []), recipe
    cell = (((reg["recipe_matrix"].get("cells") or {}).get(mode) or {})
            .get(recipe) or {})
    assert cell.get("state") == "available", f"{mode}×{recipe} 不可提交：{cell}"
    return cell["workflow"]


def _selection_plan(mode, recipe, prompt_file, materials, length=124):
    """真实面板选择构造器 build_sets → 真实 RunPlan；测试不手拼几何/配方。"""
    raw = _panel_module().build_sets(
        mode, recipe, str(prompt_file), materials, length=length)
    cli = RP.parse_sets(raw)
    wf_name = _route_for(mode, recipe)
    wf = _wf(wf_name)
    args, sources = RP.merge_args(wf.get("args") or {}, {}, cli)
    plan = RP.build_run_plan(ENGINE, wf_name, wf, args, sources,
                             cfg={"project": "无音"}, tier="draft")
    return {"workflow": wf_name, "wf": wf, "cli": cli,
            "raw": raw, "plan": plan}


def _compile_duties(wf):
    """按职责判编译链，不把完整 step id 相等当语义等价。"""
    steps = wf.get("steps") or []
    gen_pos = next((i for i, s in enumerate(steps)
                    if str(s.get("task") or "") == "video"), None)
    assert gen_pos is not None, "工作流没有 video 出片步"
    before = " ".join(str(s.get("command") or "") for s in steps[:gen_pos])
    return {
        "source_snapshot": ("prompt_compile.py" in before
                            and " snapshot " in f" {before} "),
        "pre_submit_verify": ("prompt_compile.py" in before
                              and " verify " in f" {before} "),
        "gen_reads_compiled": ("compiled_"
                               in str(steps[gen_pos].get("prompt_file") or "")),
    }


def _new_selection_pair(media, tmp_path):
    first, second = media
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("OFFLINE FIXTURE\n", encoding="utf-8")
    pi = _selection_plan("i2va", "single8", prompt,
                         {"ref_images": [str(first)]})
    pf = _selection_plan("fl2va", "single8", prompt,
                         {"ref_images": [str(first), str(second)]})
    return pi, pf


def test_c02_new_selection_only_changes_mode_and_required_images(media, tmp_path):
    """同一面板选择状态只切模式/必需图数；其余 CLI 选择项不得漂。"""
    pi, pf = _new_selection_pair(media, tmp_path)
    cli_i, cli_f = pi["cli"], pf["cli"]
    assert cli_i["input_mode"] == "i2va" and cli_f["input_mode"] == "fl2va"
    assert len(cli_i["ref_images"]) == 1
    assert len(cli_f["ref_images"]) == 2
    for key in (set(cli_i) | set(cli_f)) - {"input_mode", "ref_images"}:
        assert cli_i.get(key) == cli_f.get(key), \
            f"C02：面板选择除模式/图数外还改了 {key}：" \
            f"{cli_i.get(key)!r} -> {cli_f.get(key)!r}"


def test_c02_new_selection_keeps_geometry_and_recipe_axes(media, tmp_path):
    """新选择切模式不得连带换几何/LoRA/步数/倍率/编排。"""
    pi, pf = _new_selection_pair(media, tmp_path)
    a, b = pi["plan"], pf["plan"]
    assert (a["geometry"]["base_width"], a["geometry"]["base_height"]) == \
           (b["geometry"]["base_width"], b["geometry"]["base_height"]), \
        "C02：新选择只切模式，画布尺寸却变了：" \
        f"{a['geometry']['base_width']}x{a['geometry']['base_height']} -> " \
        f"{b['geometry']['base_width']}x{b['geometry']['base_height']}"
    for key in ("lora", "lora_strength", "steps", "scale", "second_pass"):
        assert a["recipe"].get(key) == b["recipe"].get(key), \
            f"C02：新选择只切模式，配方轴 {key} 变了：" \
            f"{a['recipe'].get(key)!r} -> {b['recipe'].get(key)!r}"
    assert a["flow"].get("orchestration") == b["flow"].get("orchestration"), \
        "C02：新选择只切模式，编排键变了"


def test_c02_new_selection_keeps_compile_duties(media, tmp_path):
    """编译职责：原稿快照、提交前校验、下游读编译稿，切模式不得丢。"""
    pi, pf = _new_selection_pair(media, tmp_path)
    duties_i = _compile_duties(pi["wf"])
    duties_f = _compile_duties(pf["wf"])
    assert all(duties_i.values()), \
        f"C02：主机型 {pi['workflow']} 编译职责不全：{duties_i}"
    assert duties_f == duties_i, \
        f"C02：只切模式，编译职责变了：{pi['workflow']}={duties_i} -> " \
        f"{pf['workflow']}={duties_f}"


def test_c02_legacy_preset_direct_call_keeps_defaults(media, tmp_path):
    """旧预设直调是兼容面：不得为了新选择去改它的默认几何/强度/步骤。"""
    first, second = media
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("OFFLINE FIXTURE\n", encoding="utf-8")
    wf_name = "h3_fl2va_dual_play"
    wf = _wf(wf_name)
    args, sources = RP.merge_args(
        wf.get("args") or {}, {},
        {"prompt_file": str(prompt), "ref_images": [str(first), str(second)]})
    plan = RP.build_run_plan(ENGINE, wf_name, wf, args, sources,
                             cfg={"project": "无音"}, tier="draft")
    g = plan["geometry"]
    assert (g["base_width"], g["base_height"]) == (864, 1536), \
        f"C02：旧预设直调默认尺寸被改了：{g['base_width']}x{g['base_height']}"
    assert plan["recipe"]["lora_strength"] == 0.7, \
        f"C02：旧预设直调默认强度被改了：{plan['recipe']['lora_strength']}"
    assert plan["recipe"]["steps"] == 8
    assert [s.get("id") for s in wf["steps"]] == ["pre", "gen"], \
        "C02：旧预设直调的步骤链被改了"
    assert not any(_compile_duties(wf).values()), \
        "C02：旧预设直调被强行接上编译链，兼容面被破坏"


# ============================================================ C03 Bunny 零强度
def test_c03_explicit_zero_strength_stays_zero(tmp_path):
    """lora2 已指定、两个强度都显式给 0：建图必须仍为 0，不能回落 0.5。"""
    img = tmp_path / "ref.png"
    img.write_bytes(_PNG)
    tpl = json.loads((ENGINE / "comfy" / "h3_two_pass_api.json")
                     .read_text(encoding="utf-8"))
    params = _base_params()
    params.update(lora2="Bunny_weapon_combatV1.safetensors",
                  bunny_strength=0.0, lora2_strength=0.0)
    graph = T.build_graph_video(tpl, params, 42,
                                extra_rep={"__REF1__": "ref.png"})
    bunny = [n for n in graph.values()
             if n.get("class_type") == "LoraLoaderModelOnly"
             and "bunny" in str(n.get("inputs", {}).get("lora_name", "")).lower()]
    assert len(bunny) == 1, f"C03：Bunny 增强节点数不对：{len(bunny)}"
    assert bunny[0]["inputs"]["strength_model"] == 0.0, \
        f"C03：显式 0 被改写：strength_model=" \
        f"{bunny[0]['inputs']['strength_model']!r}（应为 0.0）"


# ============================================================ C04 2.0 确认边界
def _plan_two_pass(media, length, scale, confirm):
    return _plan("h3_two_pass_daily", {
        "ref_images": [str(media[0])], "prompt": "OFFLINE FIXTURE",
        "length": length, "scale_by": scale, "confirm_big_scale": confirm})


def _graph_two_pass(length, scale, confirm):
    tpl = json.loads((ENGINE / "comfy" / "h3_two_pass_api.json")
                     .read_text(encoding="utf-8"))
    return T.build_graph_video(
        tpl, dict(_base_params(), length=length, scale_by=scale,
                  confirm_big_scale=confirm),
        42, extra_rep={"__REF1__": "ref.png"})


def test_c04_124f_2x_is_not_blocked_by_plan(media):
    """124 帧×2.0 不在已知崩溃档（≥264 帧）；计划与 builder 应同样放行。"""
    plan = _plan_two_pass(media, 124, 2.0, False)
    assert plan["geometry"]["requested_frames"] == 124
    assert plan["geometry"]["scale"] == 2.0
    graph = _graph_two_pass(124, 2.0, False)
    assert graph["13"]["inputs"]["scale_by"] == 2.0, \
        "C04：builder 没把 2.0 落进放大节点"


def test_c04_264f_2x_still_requires_confirmation(media):
    """≥264 帧×2.0 是已知崩溃边界：计划与 builder 都必须要求显式确认。"""
    with pytest.raises(RP.PlanError) as plan_err:
        _plan_two_pass(media, 264, 2.0, False)
    assert "confirm_big_scale" in str(plan_err.value), \
        f"C04：≥264 档拒绝原因没说清要确认：{plan_err.value}"
    with pytest.raises(ValueError) as build_err:
        _graph_two_pass(264, 2.0, False)
    assert "confirm_big_scale" in str(build_err.value), \
        f"C04：builder 在 ≥264 档的拒绝原因不一致：{build_err.value}"


def test_c04_264f_2x_with_confirmation_passes_both(media):
    plan = _plan_two_pass(media, 264, 2.0, True)
    assert plan["geometry"]["requested_frames"] == 264
    graph = _graph_two_pass(264, 2.0, True)
    assert graph["13"]["inputs"]["scale_by"] == 2.0


# ============================================================ C05 Ref2VA×R3
def test_c05_ref2va_r3_plan_and_two_pass_graph_agree(media):
    """登记 available 的 Ref2VA×R3：计划不得拒绝，两遍条件化必须同一套参考槽。"""
    img = media[0]
    plan = _plan("h3_two_pass_modes", {
        "input_mode": "ref2va", "ref_images": [str(img)],
        "prompt": "OFFLINE FIXTURE"})
    assert plan["recipe"]["matrix"]["state"] == "available", \
        f"C05：登记状态变了：{plan['recipe']['matrix']}"
    mat = plan["inputs"]["materials"]
    assert mat["first_frame"] is None, \
        f"C05：Ref2VA 没有首帧语义，计划却给了 first_frame={mat['first_frame']}"
    assert mat["last_frame"] is None, \
        f"C05：Ref2VA 没有尾帧语义，计划却给了 last_frame={mat['last_frame']}"
    assert mat["references"] == [str(img)], \
        f"C05：参考图没进 references：{mat['references']}"

    tpl = json.loads((ENGINE / "comfy" / "h3_two_pass_modes_api.json")
                     .read_text(encoding="utf-8"))
    graph = T.build_graph_video(
        tpl, dict(_base_params(), input_mode="ref2va"), 42,
        extra_rep={"__REF1__": "ref.png"},
        ref_materials={"images": [str(img)], "videos": [],
                       "video_audios": [], "audios": []})
    hosts = [(nid, n) for nid, n in graph.items()
             if n.get("class_type") == "MiniMaxH3AudioConditioningT8"]
    assert len(hosts) == 2, f"C05：R3 两遍条件化节点数={len(hosts)}"
    ref_links = []
    for nid, node in hosts:
        ins = node.get("inputs") or {}
        assert "first_frame" not in ins and "last_frame" not in ins, \
            f"C05：Ref2VA 条件化节点 {nid} 仍接了帧图：{sorted(ins)}"
        assert "ref_images.ref_image_0" in ins, \
            f"C05：条件化节点 {nid} 没接第一张参考图"
        ref_links.append(tuple(ins["ref_images.ref_image_0"]))
    assert ref_links[0] == ref_links[1], \
        f"C05：两遍条件化没有共用同一套参考图：{ref_links}"
    src = graph[str(ref_links[0][0])]
    assert src.get("class_type") == "LoadImage", \
        f"C05：参考图链接指向的不是 LoadImage：{src}"
    assert src["inputs"]["image"] == str(img), \
        f"C05：参考图文件不一致：{src['inputs']['image']}"


# ============================================================ S2 参数名静默失效
def test_s2_misspelled_two_pass_params_are_rejected(media):
    """`coarse_steps` 这类近似错名会被 YAML 默认值静默顶上——必须停在计划阶段。"""
    for bad, want in (("coarse_steps", "two_pass_coarse_steps"),
                      ("refine_steps", "two_pass_refine_steps"),
                      ("base_steps", "steps")):
        with pytest.raises(RP.PlanError) as ei:
            _plan("h3_two_pass_daily", {
                "ref_images": [str(media[0])], "prompt": "OFFLINE FIXTURE",
                "length": 124, "scale_by": 1.25, bad: 3})
        assert want in str(ei.value), (bad, str(ei.value))


# ============================================================ S2 预览/执行同源
def test_s2_execution_plan_gate_blocks_before_batch_dir(tmp_path):
    """真实执行路径也必须先过同一份 RunPlan：FL2VA 只给一张图 ⇒ 停在建批次夹之前。

    --inspect 能拦住不算数——这条真起 `run.py`（隔离 config、play 落点在 tmp），
    证明执行分支在**建批次夹/提交之前**就用了同一个计划构造器。
    """
    import os
    import subprocess
    png = tmp_path / "only_first.png"
    png.write_bytes(_PNG)
    prompt = tmp_path / "p.txt"
    prompt.write_text("x\n", encoding="utf-8")
    play_root = Path(os.environ.get("AW_ISO_PLAY_ROOT") or
                     (Path(os.environ["AW_CONFIG_PATH"]).parent / "comfy_play"))
    import yaml as _yaml
    cfg = _yaml.safe_load(Path(os.environ["AW_CONFIG_PATH"]).read_text(encoding="utf-8"))
    play_root = Path(cfg["play_output_root"])
    before = {p.name for p in play_root.iterdir()} if play_root.is_dir() else set()
    cmd = [sys.executable, "-B", "run.py", "h3_keyframe_modes", "--tier", "play",
           "--set", "input_mode=fl2va", "--set", f"ref_images={png}",
           "--set", f"prompt_file={prompt}", "--set", "width=736", "--set",
           "height=416", "--set", "length=124", "--set", "use_llm_polish=false"]
    r = subprocess.run(cmd, cwd=str(ENGINE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    assert r.returncode == 2, out[-800:]
    assert "缺尾帧" in out or "FL2VA" in out, out[-800:]
    after = {p.name for p in play_root.iterdir()} if play_root.is_dir() else set()
    assert after == before, f"计划校验失败却建了批次夹：{after - before}"
    assert "启动 ComfyUI" not in out, "计划校验前就碰了服务"


# ============================================================ S5 CRLF 误判
def test_s5_crlf_prompt_is_not_misjudged_as_missing_blank_line():
    """CRLF 稿首行后的空行是 `\\r\\n`，不能因为 `rest[:1] == '\\r'` 被判成缺空行。"""
    tools = ENGINE.parent / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    from h3_official_spec import validate
    text = ("For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced.\r\n\r\n"
            "integrated_multimodal_description: [Shot 1] She turns.\r\n\r\n"
            "overall_soundscape: Wind.\r\n\r\nnon_diegetic_music: N/A\r\n")
    rep = validate(text, mode="i2va", frames=107)
    f0_err = [r for r in rep.rows if r["id"] == "F0" and r["sev"] == "error"]
    assert not f0_err, rep.render()


# ============================================================ S5 模板必填
def test_s5_ref2va9_templates_keep_required_ref_image_size():
    """9 图模板漏 `ref_image_size` 会在提交时被 ComfyUI 判 required_input_missing。"""
    for rel in ("comfy/h3_i2v_ref2va9_api.json",
                "comfy/h3_i2v_ref2va9_nolora_api.json"):
        g = json.loads((ENGINE / rel).read_text(encoding="utf-8"))
        hosts = [n for n in g.values()
                 if n.get("class_type") == "MiniMaxH3ReferenceToVideo"]
        assert hosts, rel
        for h in hosts:
            assert "ref_image_size" in h["inputs"], (rel, h.get("inputs", {}).keys())


def test_s5_dynamic_ref_builder_keeps_ref_image_size():
    """动态注入不能把 `ref_image_size` 当成素材槽一起清掉（P6′ 提交失败的直接原因）。"""
    tpl = json.loads((ENGINE / "comfy/h3_i2v_ref2va9_api.json")
                     .read_text(encoding="utf-8"))
    g = T.build_graph_video(tpl, {"prompt": "P", "width": 576, "height": 1024,
                                  "length": 124, "input_mode": "ref2va"}, 42,
                            extra_rep={},
                            ref_materials={"images": ["a.png"], "videos": [],
                                           "video_audios": [], "audios": []})
    host = next(n for n in g.values()
                if n.get("class_type") == "MiniMaxH3ReferenceToVideo")
    assert host["inputs"].get("ref_image_size") == "max", host["inputs"]
    assert "ref_images.ref_image_0" in host["inputs"], host["inputs"]


# ============================================================ C06 来源保留
def test_c06_legacy_manifest_args_are_not_promoted_to_explicit():
    """旧 manifest 只有 args（无来源证据）；不能把它们全当人工显式。"""
    saved_args = _wf("h3_fl2va_dual_play")["args"]
    legacy = {"args": saved_args}
    assert R.resolve_explicit_args({}, saved_args, legacy) == [], \
        "C06：旧 manifest 无来源字段，却把 YAML 默认全升成人工显式"
    assert R.resolve_explicit_args({"width": 1024}, saved_args, legacy) == ["width"], \
        "C06：本次 CLI 显式给的键必须保留"


def test_c06_new_manifest_inherits_only_evidenced_human_values():
    saved_args = _wf("h3_fl2va_dual_play")["args"]
    new = {"args": saved_args, "explicit_args": ["seed", "width"]}
    assert R.resolve_explicit_args({}, saved_args, new) == ["seed", "width"]
    assert R.resolve_explicit_args({"height": 1024}, saved_args, new) == \
        ["height", "seed", "width"]
    by_source = {"args": saved_args,
                 "arg_sources": {"seed": "cli_explicit",
                                 "width": "yaml_default"}}
    assert R.resolve_explicit_args({}, saved_args, by_source) == ["seed"], \
        "C06：arg_sources 只有 cli_explicit/human 才算人工显式"
