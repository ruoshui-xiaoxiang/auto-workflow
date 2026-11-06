# -*- coding: utf-8 -*-
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import h3_spider.dashboard as D

BATCH = r"C:/Temp/h3_spider/batch_p15"


def _serve(workflow_path="", launchpad_path=""):
    D.Handler.batch_dir = BATCH
    D.Handler.gate_path = ""
    D.Handler.workflow_path = workflow_path
    D.Handler.launchpad_path = launchpad_path
    D.Handler.kb_path = r"E:/繁星/60_知识库"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), D.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def test_dashboard_html():
    srv = _serve()
    try:
        port = srv.server_address[1]
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port).read().decode("utf-8")
        assert "繁星系统" in html
        assert "蜘蛛" not in html
        assert "/api/batch" in html
        assert 'id="issues"' in html
        assert 'id="work-view"' in html
        assert 'id="nebula-view"' not in html
        assert "deepspace" not in html
        assert 'id="view-toggle"' not in html
        assert 'href="/map3d"' in html
        assert 'href="/launch"' in html
    finally:
        srv.shutdown()


def test_dashboard_apis():
    srv = _serve()
    try:
        port = srv.server_address[1]
        b = json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/batch" % port))
        assert b["batch"]["overall"] == "PASS"
        assert b["gate_path"] == ""
        assert len(b["shots"]) == 12
        assert len(b["legs"]) == 8
        l7 = next(x for x in b["legs"] if x["id"] == "L7")
        assert l7["check"] == "asset-chain"
        assert "asset" in l7["node_types"]
        assert len(b["shots"]["U05"]["assets_clean.json"]) == 3
        s = json.load(urllib.request.urlopen(
            "http://127.0.0.1:%d/api/shot?sid=U05" % port))
        assert s["sid"] == "U05"
        assert len(s["snapshots"]) > 0
        assert len(s["manifest.json"]["nodes"]) == 24
        assert s["recovered.json"]["all_nodes_ok"] is True
        assert len(s["recovered.json"]["nodes"]) == 8
    finally:
        srv.shutdown()


def test_dashboard_asset():
    srv = _serve()
    try:
        port = srv.server_address[1]
        r = urllib.request.urlopen(
            "http://127.0.0.1:%d/api/asset?sid=U05&asset=cmdr" % port)
        data = r.read()
        assert r.status == 200
        assert len(data) > 1000
        assert (r.headers.get("Content-Type") or "").startswith("image/")
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:%d/api/asset?sid=U05&asset=nope" % port)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_dashboard_launchpad_api(tmp_path, monkeypatch):
    target = tmp_path / "folder"
    target.mkdir()
    cfg = {"entries": [{"id": "demo", "name": "Demo", "kind": "folder",
                        "target": str(target), "note": "test"}]}
    p = tmp_path / "launchpad.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    srv = _serve(launchpad_path=str(p))
    try:
        port = srv.server_address[1]
        base = "http://127.0.0.1:%d" % port
        html = urllib.request.urlopen(base + "/launch").read().decode("utf-8")
        assert "启动台" in html
        entries = json.loads(urllib.request.urlopen(base + "/api/launchpad")
                             .read().decode("utf-8"))["entries"]
        assert entries[0]["id"] == "demo"

        req = urllib.request.Request(
            base + "/api/launch",
            data=json.dumps({"id": "demo"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            assert False, "expected 403 without launch header"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        req = urllib.request.Request(
            base + "/api/launch",
            data=json.dumps({"id": "nope"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Fanxing-Launch": "1"})
        try:
            urllib.request.urlopen(req)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404

        calls = []
        monkeypatch.setattr(D.os, "startfile", lambda path: calls.append(path),
                            raising=False)
        req = urllib.request.Request(
            base + "/api/launch",
            data=json.dumps({"id": "demo"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Fanxing-Launch": "1"})
        got = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
        assert got["ok"] and got["id"] == "demo"
        assert calls == [str(target)]
    finally:
        srv.shutdown()


def test_dashboard_workflow_api(tmp_path):
    wf = {"overall": "PASS", "stages": [{"id": "gate", "status": "ok"}]}
    p = tmp_path / "workflow.json"
    p.write_text(json.dumps(wf, ensure_ascii=False), encoding="utf-8")
    srv = _serve(workflow_path=str(p))
    try:
        port = srv.server_address[1]
        got = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/api/workflow" % port).read().decode("utf-8"))
        assert got["overall"] == "PASS"
    finally:
        srv.shutdown()

    srv = _serve()
    try:
        port = srv.server_address[1]
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/workflow" % port)
            assert False, "expected 404"
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        srv.shutdown()


def test_dashboard_kb_api():
    srv = _serve()
    try:
        port = srv.server_address[1]
        got = json.load(urllib.request.urlopen(
            "http://127.0.0.1:%d/api/kb" % port))
        assert got["index"].endswith("60_知识库")
        assert len(got["collections"]) == 5
        core = next(x for x in got["collections"] if x["name"] == "core")
        assert core["chunks"] > 0
        assert core["files"] > 0
        assert core["audit"] in ("PASS", "BLOCK", "missing")
        assert got["totals"]["chunks"] > 0
    finally:
        srv.shutdown()


def test_dashboard_3d_routes():
    srv = _serve()
    try:
        port = srv.server_address[1]
        base = "http://127.0.0.1:%d" % port
        r = urllib.request.urlopen(base + "/map3d")
        html = r.read().decode("utf-8")
        assert r.status == 200
        assert "繁星系统" in html
        assert "蜘蛛" not in html
        assert "/map3d.js" in html
        r = urllib.request.urlopen(base + "/map3d.js")
        js = r.read().decode("utf-8")
        assert r.status == 200
        assert "import * as THREE" in js
        assert "/api/workflow" in js
        assert "/api/kb" in js
        assert "知识云" in js
        assert "loadWorkflow" in js
        r = urllib.request.urlopen(base + "/vendor/three/three.module.js")
        assert r.status == 200
        assert len(r.read()) > 100000

        r = urllib.request.urlopen(base + "/sky/deepspace_2020_4k.jpg")
        assert r.status == 200
        assert (r.headers.get("Content-Type") or "").startswith("image/")
        assert len(r.read()) > 1000000

        from http.client import HTTPConnection
        for bad in ("/vendor/three/../../dashboard.py", "/vendor/nope/x.js", "/vendor/three/x.json"):
            conn = HTTPConnection("127.0.0.1", port)
            conn.request("GET", bad)
            resp = conn.getresponse()
            resp.read()
            conn.close()
            assert resp.status == 404, bad
    finally:
        srv.shutdown()


def test_dashboard_live_route():
    srv = _serve()
    try:
        port = srv.server_address[1]
        base = "http://127.0.0.1:%d" % port
        html = urllib.request.urlopen(base + "/live").read().decode("utf-8")
        assert "实时审查" in html
        assert "CLEAN ERR" in html
        assert "MUT ERR" in html
        assert "recovered" in html
        from http.client import HTTPConnection
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/live?sid=U05")
        resp = conn.getresponse()
        assert resp.status == 200
        assert "text/event-stream" in resp.getheader("Content-Type", "")
        chunk = resp.read(256)
        assert b"event:" in chunk
        conn.close()
    finally:
        srv.shutdown()
