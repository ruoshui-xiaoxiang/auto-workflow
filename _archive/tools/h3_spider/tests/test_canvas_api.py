# -*- coding: utf-8 -*-
import json
import os
import subprocess
from urllib.parse import urlencode

import pytest

from h3_spider import canvas_api


class Fake:
    def __init__(self):
        self.code = None
        self.obj = None
        self.body = b""
        self.ctype = None

    def _json(self, obj, code=200):
        self.code, self.obj = code, obj

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.code, self.body, self.ctype = code, body, ctype


def test_projects_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "list_projects", lambda: [{"name": "X"}])
    h = Fake()
    canvas_api.handle(h, "GET", "/api/projects", "")
    assert h.code == 200
    assert h.obj["projects"][0]["name"] == "X"


def test_canvas_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "load_state", lambda p: {"shots": [{"id": "U01"}]})
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas", "project=P")
    assert h.obj["shots"][0]["id"] == "U01"


def test_save_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "save_canvas", lambda p, patch: {"ok": True, **patch})
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/save",
                      "", json.dumps({"project": "P", "nodes": {"U01": {}}}).encode())
    assert h.obj["ok"] is True


def test_apply_requires_shots(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/apply", "",
                      json.dumps({"project": "P", "shots": []}).encode())
    assert h.code == 400


def test_shot_add_route(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "add_shot", lambda p, t: "U13")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/shot", "",
                      json.dumps({"project": "P", "action": "add", "template": "U01"}).encode())
    assert h.obj["id"] == "U13"


# ------------------------------------------------------------ 追加用例
def test_delete_route(monkeypatch):
    calls = []
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "delete_shot", lambda p, sid: calls.append(sid))
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/shot", "",
                      json.dumps({"project": "P", "action": "delete", "id": "U02"}).encode())
    assert h.code == 200
    assert h.obj["ok"] is True
    assert calls == ["U02"]


def test_shot_bad_action_returns_400(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/shot", "",
                      json.dumps({"project": "P", "action": "nope"}).encode())
    assert h.code == 400


def test_bad_json_returns_400(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/save", "", b"{broken")
    assert h.code == 400
    assert "error" in h.obj


def test_json_non_object_returns_400(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/save", "", b"[1, 2]")
    assert h.code == 400


def test_apply_per_shot_reports_each(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")

    def fake_apply(project, drafts, edges, anchors, dry_run=False):
        sid = drafts[0]["id"]
        if sid == "U02":
            raise canvas_api.CanvasError("时长不在档位", 422)
        return {"ok": True, "shots": [sid]}

    monkeypatch.setattr(canvas_api, "apply_draft", fake_apply)
    h = Fake()
    body = json.dumps({"project": "P", "per_shot": True,
                       "shots": [{"id": "U01"}, {"id": "U02"}]}).encode()
    canvas_api.handle(h, "POST", "/api/canvas/apply", "", body)
    assert h.code == 422
    assert h.obj["ok"] is False
    assert [x["id"] for x in h.obj["results"]] == ["U01", "U02"]
    assert h.obj["results"][0]["ok"] is True
    assert h.obj["results"][1]["ok"] is False
    assert "时长" in h.obj["results"][1]["error"]


def test_state_error_becomes_500(monkeypatch):
    def boom(p):
        raise ValueError("坏 shots.yaml")

    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "load_state", boom)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas", "project=P")
    assert h.code == 500
    assert "error" in h.obj


def test_unknown_route_returns_false():
    h = Fake()
    assert canvas_api.handle(h, "GET", "/api/kb", "") is False
    assert canvas_api.handle(h, "POST", "/api/launch", "", b"{}") is False


def test_jobs_recent_route(monkeypatch):
    class M:
        def recent(self):
            return {"active": {"job_id": "j1"}, "recent": [{"job_id": "j0"}]}

    monkeypatch.setattr(canvas_api, "_manager", lambda: M())
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/jobs", "")
    assert h.code == 200
    assert h.obj["active"]["job_id"] == "j1"
    assert h.obj["recent"][0]["job_id"] == "j0"


def test_dashboard_wires_canvas_routes(monkeypatch):
    """真 Handler 走一遍：GET 分发、静态 /canvas、POST body 由画布路由读。"""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    import h3_spider.dashboard as D

    monkeypatch.setattr(canvas_api, "list_projects", lambda: [{"name": "Wired"}])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        got = json.loads(urllib.request.urlopen(base + "/api/projects").read())
        assert got["projects"][0]["name"] == "Wired"
        html = urllib.request.urlopen(base + "/canvas").read().decode("utf-8")
        assert "/map3d.js" in html
        req = urllib.request.Request(base + "/api/canvas/save", data=b"{broken",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            assert False, "expected 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()


def test_dashboard_serves_storyboard_modules():
    """真 Handler 取画布模块：/storyboard_model.js 必须在；/storyboard.js 未落地时 404 不崩。"""
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    import h3_spider.dashboard as D

    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        r = urllib.request.urlopen(base + "/storyboard_model.js")
        js = r.read().decode("utf-8")
        assert r.status == 200
        assert (r.headers.get("Content-Type") or "").startswith("text/javascript")
        assert (r.headers.get("Cache-Control") or "") == "no-store"
        assert "export function buildStoryboardModel" in js

        # storyboard.js 到 Task 10 才建：缺席时 404，落地后必须同款 js 响应
        storyboard = os.path.join(D.HERE, "storyboard.js")
        try:
            r = urllib.request.urlopen(base + "/storyboard.js")
            r.read()
            assert os.path.isfile(storyboard), "路由回 200 但文件不存在"
            assert r.status == 200
            assert (r.headers.get("Content-Type") or "").startswith("text/javascript")
        except urllib.error.HTTPError as e:
            assert e.code == 404
            assert not os.path.isfile(storyboard), "文件已在却 404"
            assert b"missing" in e.read()
    finally:
        srv.shutdown()


# ------------------------------------------------------------ 资源白名单
def test_dashboard_serves_live_panel_modules():
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import h3_spider.dashboard as D

    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        for name in ("/live_panel_model.js", "/live_panel.js"):
            r = urllib.request.urlopen(base + name)
            js = r.read().decode("utf-8")
            assert r.status == 200
            assert (r.headers.get("Content-Type") or "").startswith("text/javascript")
            assert (r.headers.get("Cache-Control") or "") == "no-store"
            assert "function" in js or "export" in js
    finally:
        srv.shutdown()


def _state(tmp_path):
    """临时项目：h3/ 是项目目录，h3 的父是项目根，frames/ 是素材根。"""
    proj = tmp_path / "proj" / "h3"
    proj.mkdir(parents=True)
    root = tmp_path / "proj"
    frames = tmp_path / "frames"
    frames.mkdir()
    return {"project": str(proj), "project_root": str(root),
            "asset_roots": [str(frames)]}, frames


def test_asset_allows_assets_dir(tmp_path, monkeypatch):
    state, frames = _state(tmp_path)
    img = frames / "U01.png"
    img.write_bytes(b"PNGDATA")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(img)}))
    assert h.code == 200
    assert h.body == b"PNGDATA"
    assert h.ctype.startswith("image/")


def test_asset_allows_project_dir(tmp_path, monkeypatch):
    state, _ = _state(tmp_path)
    doc = tmp_path / "proj" / "shots.yaml"
    doc.write_text("shots: []\n", encoding="utf-8")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(doc)}))
    assert h.code == 200
    assert "shots: []" in h.body.decode("utf-8")


def test_asset_rejects_outside(tmp_path, monkeypatch):
    state, _ = _state(tmp_path)
    secret = tmp_path / "elsewhere" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("nope", encoding="utf-8")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    with pytest.raises(canvas_api.CanvasError) as e:
        canvas_api._asset(Fake(), {"project": ["P"], "path": [str(secret)]})
    assert e.value.code == 403


def test_asset_rejects_traversal(tmp_path, monkeypatch):
    """`..` 穿越：先拼接再判定，不能靠字符串前缀。"""
    state, frames = _state(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    sneaky = os.path.join(str(frames), "..", "..", "secret.txt")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": sneaky}))
    assert h.code == 403


def test_asset_rejects_sibling_prefix(tmp_path, monkeypatch):
    """`frames_evil` 与 `frames` 共享前缀，但不是子目录。"""
    state, frames = _state(tmp_path)
    evil = tmp_path / "frames_evil"
    evil.mkdir()
    bad = evil / "x.png"
    bad.write_bytes(b"X")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(bad)}))
    assert h.code == 403


def test_asset_missing_file_404(tmp_path, monkeypatch):
    state, frames = _state(tmp_path)
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(frames / "gone.png")}))
    assert h.code == 404


def test_asset_allows_remembered_run(tmp_path, monkeypatch):
    state, _ = _state(tmp_path)
    run = tmp_path / "runs" / "canvas_apply_x"
    run.mkdir(parents=True)
    clip = run / "U01.mp4"
    clip.write_bytes(b"MP4")
    proj = state["project"]
    (tmp_path / "proj" / "h3" / ".fanxing").mkdir()
    (tmp_path / "proj" / "h3" / ".fanxing" / "runs.json").write_text(
        json.dumps({"runs": [str(run)]}), encoding="utf-8")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: proj)
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(clip)}))
    assert h.code == 200
    assert h.body == b"MP4"


# ------------------------------------------------------------ 联接/白名单
def _make_junction(link, target):
    """建目录联接（``mklink /J`` 不需要管理员）；成功返回空串，失败返回原因。"""
    if os.name != "nt":
        return "只有 Windows 支持目录联接"
    try:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return "mklink 起不来：%s" % e
    if r.returncode != 0 or not os.path.isdir(str(link)):
        return (r.stderr or r.stdout or "mklink 失败").strip()
    return ""


def _drop_junction(link):
    try:
        os.rmdir(str(link))
    except OSError:
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


def test_asset_rejects_junction_escape(tmp_path, monkeypatch):
    """根内挂一个指向根外的目录联接：必须按解析后的真实路径拒绝。"""
    state, frames = _state(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope", encoding="utf-8")
    link = frames / "escape"
    reason = _make_junction(link, outside)
    if reason:
        pytest.skip("建不了目录联接：%s" % reason)
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    try:
        h = Fake()
        canvas_api.handle(h, "GET", "/api/canvas/asset",
                          urlencode({"project": "P", "path": str(link / "secret.txt")}))
        assert h.code == 403
        assert "error" in h.obj
    finally:
        _drop_junction(link)


def test_asset_containment_uses_is_within(tmp_path, monkeypatch):
    """越界判定走 canvas_paths.is_within（解析 junction），不是字符串前缀。"""
    state, frames = _state(tmp_path)
    img = frames / "U01.png"
    img.write_bytes(b"PNGDATA")
    seen = []

    def spy(child, root):
        seen.append((str(child), str(root)))
        return False

    monkeypatch.setattr(canvas_api, "is_within", spy)
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(img)}))
    assert h.code == 403
    assert seen, "没调 is_within，白名单还停在字符串比对"


def test_within_skips_missing_root(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    assert canvas_api._within(str(target), [str(tmp_path / "missing"), str(tmp_path)])
    assert not canvas_api._within(str(target), [str(tmp_path / "missing")])


def test_within_cross_drive_is_outside(tmp_path):
    here = os.path.splitdrive(str(tmp_path))[0].upper()
    other = next((d + ":" for d in "DEFGH" if os.path.isdir(d + ":\\")), "")
    if not other or other.upper() == here:
        pytest.skip("没有另一个盘符可用")
    assert not canvas_api._within(other + "\\Windows", [str(tmp_path)])


def test_allowed_roots_skip_drive_root_and_missing(tmp_path):
    state = {"project": str(tmp_path / "gone"), "project_root": "",
             "asset_roots": ["C:\\", str(tmp_path / "nope"), "   ", str(tmp_path)]}
    roots = canvas_api._allowed_roots("P", state)
    assert roots == [str(tmp_path)]


# ------------------------------------------------------------ 输入类型
def test_asset_missing_path_is_400_before_state(monkeypatch):
    def boom(p):
        raise AssertionError("缺 path 时不该读 state")

    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "load_state", boom)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/asset", urlencode({"project": "P"}))
    assert h.code == 400
    assert "path" in h.obj["error"]


def test_apply_rejects_non_list_shots(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "apply_draft",
                        lambda *a, **kw: pytest.fail("非数组 shots 不该进 apply"))
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/apply", "",
                      json.dumps({"project": "P", "shots": {"U01": {}}}).encode())
    assert h.code == 400
    assert "数组" in h.obj["error"]


def test_apply_rejects_string_shots(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/apply", "",
                      json.dumps({"project": "P", "shots": "U01"}).encode())
    assert h.code == 400


# ------------------------------------------------------------ body 上限
def test_body_over_1mb_returns_413(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/save", "",
                      b"{" + b" " * (canvas_api.MAX_BODY + 1))
    assert h.code == 413
    assert "1MB" in h.obj["error"]


# ------------------------------------------------------------ Origin/Host
def _post_with(path, payload, headers):
    h = Fake()
    h.headers = headers
    canvas_api.handle(h, "POST", path, "", json.dumps(payload).encode("utf-8"))
    return h


def _save_ok(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "save_canvas", lambda p, patch: {"ok": True})


@pytest.mark.parametrize("origin", ["http://evil.example", "http://evil.example:8777",
                                    "https://127.0.0.1.evil.example", "null"])
def test_write_rejects_foreign_origin(monkeypatch, origin):
    _save_ok(monkeypatch)
    h = _post_with("/api/canvas/save", {"project": "P"}, {"Origin": origin})
    assert h.code == 403
    assert "Origin" in h.obj["error"]


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8777",
                                  "127.0.0.1.evil.example"])
def test_write_rejects_foreign_host(monkeypatch, host):
    """DNS rebinding：Host 不是本机就拒。"""
    _save_ok(monkeypatch)
    h = _post_with("/api/canvas/save", {"project": "P"}, {"Host": host})
    assert h.code == 403
    assert "Host" in h.obj["error"]


def test_write_allows_local_headers(monkeypatch):
    _save_ok(monkeypatch)
    for headers in ({"Origin": "http://127.0.0.1:8777", "Host": "127.0.0.1:8777"},
                    {"Origin": "http://localhost:8777", "Host": "localhost:8777"}):
        h = _post_with("/api/canvas/save", {"project": "P"}, headers)
        assert h.code == 200, headers


def test_write_allows_missing_headers(monkeypatch):
    _save_ok(monkeypatch)
    h = _post_with("/api/canvas/save", {"project": "P"}, {})
    assert h.code == 200


def test_guard_runs_before_body_parse(monkeypatch):
    _save_ok(monkeypatch)
    h = Fake()
    h.headers = {"Origin": "http://evil.example"}
    canvas_api.handle(h, "POST", "/api/canvas/save", "", b"{broken")
    assert h.code == 403


def test_get_ignores_foreign_origin(monkeypatch):
    """只读接口不设 Origin 门（比如从 file:// 打开页面）。"""
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "load_state", lambda p: {"shots": []})
    h = Fake()
    h.headers = {"Origin": "http://evil.example"}
    canvas_api.handle(h, "GET", "/api/canvas", "project=P")
    assert h.code == 200


# ------------------------------------------------------------ 500 不泄漏
def test_500_does_not_leak_detail(monkeypatch, capsys):
    def boom(p):
        raise ValueError("SECRET-TOKEN-123")

    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "load_state", boom)
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas", "project=P")
    assert h.code == 500
    assert h.obj == {"error": "画布接口失败"}
    assert "SECRET-TOKEN-123" not in json.dumps(h.obj, ensure_ascii=False)
    assert "SECRET-TOKEN-123" in capsys.readouterr().err


# ------------------------------------------------------------ 流式发文件
def test_asset_streams_via_send_file(tmp_path, monkeypatch):
    state, frames = _state(tmp_path)
    clip = frames / "U01.mp4"
    clip.write_bytes(b"MP4" * 100)

    class Streaming(Fake):
        def __init__(self):
            super().__init__()
            self.sent = []

        def _send_file(self, path, ctype="application/octet-stream"):
            self.sent.append((path, ctype))

    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Streaming()
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(clip)}))
    assert h.sent == [(str(clip), "video/mp4")]
    assert h.body == b""
    assert h.code is None


def test_asset_falls_back_without_send_file(tmp_path, monkeypatch):
    state, frames = _state(tmp_path)
    clip = frames / "U01.mp4"
    clip.write_bytes(b"MP4DATA")
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    h = Fake()
    assert not hasattr(h, "_send_file")
    canvas_api.handle(h, "GET", "/api/canvas/asset",
                      urlencode({"project": "P", "path": str(clip)}))
    assert h.code == 200
    assert h.body == b"MP4DATA"


def test_asset_streams_exact_bytes_from_server(tmp_path, monkeypatch):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    import h3_spider.dashboard as D

    state, frames = _state(tmp_path)
    blob = bytes(range(256)) * 600  # ~150KB，跨多个 64KB 块
    clip = frames / "U01.mp4"
    clip.write_bytes(blob)
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: state["project"])
    monkeypatch.setattr(canvas_api, "load_state", lambda p: state)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        r = urllib.request.urlopen(
            base + "/api/canvas/asset?" + urlencode({"project": "P", "path": str(clip)}))
        assert r.read() == blob
        assert int(r.headers["Content-Length"]) == len(blob)
        assert r.headers["Cache-Control"] == "no-store"
        assert r.headers["Accept-Ranges"] == "none"
        assert (r.headers["Content-Type"] or "").startswith("video/")
    finally:
        srv.shutdown()


# ------------------------------------------------------------ 看板 body 上限
def test_dashboard_rejects_huge_content_length_without_reading():
    """声明 8MB 却不发一个字节：必须立刻 413，不能等 body 把线程挂住。"""
    import threading
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer

    import h3_spider.dashboard as D

    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
        conn.putrequest("POST", "/api/canvas/save", skip_accept_encoding=True)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(8 * 1024 * 1024))
        conn.endheaders()  # 故意不发 body
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 413
        assert "1MB" in payload["error"]
        conn.close()
    finally:
        srv.shutdown()


def test_dashboard_caps_body_without_content_length():
    """没有 Content-Length 时最多读 1MB+1：超了回 413，别无限等。"""
    import socket
    import threading
    from http.server import ThreadingHTTPServer

    import h3_spider.dashboard as D

    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    sock = None
    try:
        sock = socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=10)
        sock.sendall(b"POST /api/canvas/save HTTP/1.0\r\n"
                     b"Content-Type: application/json\r\n\r\n")
        sock.sendall(b"{" + b" " * (canvas_api.MAX_BODY + 1))
        sock.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        assert b" 413 " in data.split(b"\r\n", 1)[0]
    finally:
        if sock is not None:
            sock.close()
        srv.shutdown()


def test_run_requires_confirm(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/run", "",
                      json.dumps({"project": "P", "shots": ["U01"]}).encode())
    assert h.code == 400


def test_run_health_blocked(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "health_ok", lambda: False)
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/run", "",
                      json.dumps({"project": "P", "shots": ["U01"], "confirm": True}).encode())
    assert h.code == 503


def test_run_returns_job(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "health_ok", lambda: True)

    class M:
        def start(self, project, shots, stage):
            return {"job_id": "j1", "status": "queued", "stage": stage}

    monkeypatch.setattr(canvas_api, "_manager", lambda: M())
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/run", "",
                      json.dumps({"project": "P", "shots": ["U01"], "confirm": True}).encode())
    assert h.obj["job_id"] == "j1"


def test_gate_run_skips_health(monkeypatch):
    monkeypatch.setattr(canvas_api, "resolve_project", lambda p: "P")
    monkeypatch.setattr(canvas_api, "health_ok", lambda: False)

    class M:
        def start(self, project, shots, stage):
            return {"job_id": "j2", "status": "queued", "stage": stage}

    monkeypatch.setattr(canvas_api, "_manager", lambda: M())
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/run", "",
                      json.dumps({"project": "P", "shots": ["U01"], "stage": "gate",
                                  "confirm": True}).encode())
    assert h.obj["job_id"] == "j2"


def test_job_get_and_cancel(monkeypatch):
    class M:
        def get(self, job_id):
            return {"job_id": job_id, "status": "running"} if job_id == "j1" else {}

        def cancel(self, job_id):
            return {"job_id": job_id, "status": "cancelled"}

    monkeypatch.setattr(canvas_api, "_manager", lambda: M())
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/jobs/j1", "")
    assert h.obj["status"] == "running"
    h = Fake()
    canvas_api.handle(h, "POST", "/api/canvas/jobs/j1/cancel", "")
    assert h.obj["status"] == "cancelled"
    h = Fake()
    canvas_api.handle(h, "GET", "/api/canvas/jobs/nope", "")
    assert h.code == 404
