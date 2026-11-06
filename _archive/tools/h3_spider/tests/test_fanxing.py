# -*- coding: utf-8 -*-
import json
import os

import pytest

import h3_spider
from fanxing import agents
from fanxing.workflow import run_workflow

PROJ = r"C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3"
INPUT = r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/input"


def _registry(tmp_path, monkeypatch):
    p = tmp_path / "agents.json"
    monkeypatch.setenv("FANXING_REGISTRY", str(p))
    return p


def test_agent_join_signature_and_tamper(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    rec = agents.join("alice", "Alice", "owner", accept_contract=True)
    got = agents.get("alice", require_scope="workflow:run")
    assert got["agent_id"] == "alice"
    assert got["contract"] == "fanxing-agent-v1"

    bad = dict(got)
    bad["name"] = "Eve"
    with pytest.raises(agents.AgentError):
        agents.verify_record(bad)

    with pytest.raises(agents.AgentError):
        agents.join("alice", "Alice", "owner", accept_contract=True)
    rec2 = agents.join("alice", "Alice2", "owner", accept_contract=True, force=True)
    assert rec2["name"] == "Alice2"


def test_agent_requires_contract(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    with pytest.raises(agents.AgentError):
        agents.join("bob", "Bob", "owner", accept_contract=False)


def test_contract_stale_blocks_agent(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    agents.join("carol", "Carol", "owner", accept_contract=True)
    monkeypatch.setattr(agents, "contract_sha256", lambda: "stale-sha")
    with pytest.raises(agents.ContractStale):
        agents.get("carol")


def test_starfield_counts_batch_shots(tmp_path):
    from fanxing.starfield import scan_runs
    run_dir = tmp_path / "runs" / "r1"
    batch_dir = run_dir / "qc"
    batch_dir.mkdir(parents=True)
    (batch_dir / "batch_verdict.json").write_text(
        json.dumps({"overall": "PASS", "shots": {"U05": {}, "U06": {}}}),
        encoding="utf-8")
    wf = {"agent_id": "local", "overall": "PASS", "run_id": "r1",
          "shots": None, "batch_dir": str(batch_dir)}
    (run_dir / "workflow.json").write_text(json.dumps(wf), encoding="utf-8")
    agg = scan_runs(str(tmp_path / "runs"))
    assert agg["local"]["shots"] == 2
    assert agg["local"]["last_run"]["shots"] == 2


def test_workflow_gate_pass(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    out = tmp_path / "run"
    wf = run_workflow(PROJ, str(out), agent_id="local", shots=["U05"],
                      input_dir=INPUT, through="gate",
                      skip_precheck=True, skip_build=True)
    assert wf["overall"] == "PASS"
    assert wf["agent_id"] == "local"
    assert wf["spider_version"] == h3_spider.__version__
    stages = {s["id"]: s for s in wf["stages"]}
    assert stages["precheck"]["status"] == "skipped"
    assert stages["build"]["status"] == "skipped"
    assert stages["qc"]["status"] == "ok"
    assert stages["gate"]["status"] == "ok"
    assert stages["run"]["status"] == "skipped"
    assert os.path.isfile(out / "workflow.json")
    assert os.path.isfile(out / "qc" / "batch_verdict.json")


def test_workflow_run_requires_execute(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    wf = run_workflow(PROJ, str(tmp_path / "run2"), agent_id="local",
                      shots=["U05"], input_dir=INPUT, through="run",
                      skip_precheck=True, skip_build=True, execute_run=False)
    run = next(s for s in wf["stages"] if s["id"] == "run")
    assert run["status"] == "skipped"
    assert "execute-run" in run["reason"]


def test_readonly_agent_can_join_but_not_workflow(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    agents.join("reader", "Reader", "owner", scopes=["knowledge:read"],
                accept_contract=True)
    assert agents.get("reader")["agent_id"] == "reader"
    with pytest.raises(agents.AgentError):
        run_workflow(PROJ, str(tmp_path / "run4"), agent_id="reader",
                     shots=["U05"], through="gate",
                     skip_precheck=True, skip_build=True)


def test_workflow_rejects_unregistered_agent(tmp_path, monkeypatch):
    _registry(tmp_path, monkeypatch)
    with pytest.raises(agents.AgentError):
        run_workflow(PROJ, str(tmp_path / "run3"), agent_id="ghost",
                     shots=["U05"], through="gate",
                     skip_precheck=True, skip_build=True)
