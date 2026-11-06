# -*- coding: utf-8 -*-
"""Agent 注册表：自助 join、共签哈希、scope、协议版本校验。"""
import hashlib
import json
import os
import re
import time
from typing import Dict, List, Optional

from . import CONTRACT_ID, CONTRACT_PATH, DEFAULT_REGISTRY

AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
KNOWN_SCOPES = {
    "workflow:read", "workflow:run",
    "knowledge:read", "knowledge:write",
    "memory:read:self", "memory:write:self",
    "skill:read", "skill:write",
    "agent:read", "agent:write",
}
DEFAULT_SCOPES = [
    "workflow:read", "workflow:run",
    "knowledge:read",
    "memory:read:self", "memory:write:self",
    "skill:read", "agent:read",
]


class AgentError(Exception):
    pass


class ContractStale(AgentError):
    pass


class AgentRevoked(AgentError):
    pass


def registry_path() -> str:
    return os.environ.get("FANXING_REGISTRY") or DEFAULT_REGISTRY


def contract_sha256() -> str:
    with open(CONTRACT_PATH, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _canonical(record: Dict) -> str:
    body = {k: v for k, v in record.items()
            if k not in ("agent_signature", "system_signature")}
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _sign(record: Dict, contract_sha: str) -> Dict:
    agent_sig = hashlib.sha256(
        ("agent|" + _canonical(record)).encode("utf-8")).hexdigest()
    system_sig = hashlib.sha256(
        ("system|" + contract_sha + "|" + agent_sig).encode("utf-8")).hexdigest()
    out = dict(record)
    out["agent_signature"] = agent_sig
    out["system_signature"] = system_sig
    return out


def _empty_registry() -> Dict:
    return {"version": 1, "contract": CONTRACT_ID,
            "contract_sha256": contract_sha256(), "updated_at": _now(),
            "agents": {}}


def load_registry() -> Dict:
    p = registry_path()
    if not os.path.isfile(p):
        reg = _empty_registry()
        save_registry(reg)
        return reg
    with open(p, encoding="utf-8") as f:
        reg = json.load(f)
    if not isinstance(reg.get("agents"), dict):
        raise AgentError("agents.json 结构不对：缺 agents 对象")
    return reg


def save_registry(reg: Dict) -> None:
    p = registry_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    reg["updated_at"] = _now()
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)


def verify_record(rec: Dict) -> None:
    if rec.get("agent_signature") != hashlib.sha256(
            ("agent|" + _canonical(rec)).encode("utf-8")).hexdigest():
        raise AgentError("agent 签名不匹配：记录被改过")
    expect = hashlib.sha256(
        ("system|" + rec.get("contract_sha256", "") + "|" +
         rec["agent_signature"]).encode("utf-8")).hexdigest()
    if rec.get("system_signature") != expect:
        raise AgentError("system 签名不匹配：记录被改过")
    if rec.get("contract_sha256") != contract_sha256():
        raise ContractStale("协议版本已变：请重新 agent join --accept-contract")


def join(agent_id: str, name: str, owner: str,
         scopes: Optional[List[str]] = None,
         accept_contract: bool = False,
         force: bool = False) -> Dict:
    if not AGENT_ID_RE.fullmatch(agent_id or ""):
        raise AgentError("agent_id 不合法：%r（小写字母/数字/_/-，2–32 位）" % agent_id)
    if not accept_contract:
        raise AgentError("必须 --accept-contract：先读协议再接入")
    chosen = list(scopes or DEFAULT_SCOPES)
    bad = [s for s in chosen if s not in KNOWN_SCOPES]
    if bad:
        raise AgentError("未知 scope：%s" % ", ".join(bad))

    reg = load_registry()
    if agent_id in reg["agents"] and not force:
        raise AgentError("agent 已存在：%s；要重签请加 --force" % agent_id)
    sha = contract_sha256()
    rec = {
        "agent_id": agent_id,
        "name": name or agent_id,
        "owner": owner or "",
        "status": "active",
        "scopes": chosen,
        "contract": CONTRACT_ID,
        "contract_sha256": sha,
        "joined_at": _now(),
        "last_seen": None,
    }
    rec = _sign(rec, sha)
    reg["agents"][agent_id] = rec
    reg["contract"] = CONTRACT_ID
    reg["contract_sha256"] = sha
    save_registry(reg)
    return rec


def get(agent_id: str, require_scope: Optional[str] = None) -> Dict:
    reg = load_registry()
    rec = (reg.get("agents") or {}).get(agent_id)
    if not rec:
        raise AgentError("未注册 agent：%s；先 agent join" % agent_id)
    verify_record(rec)
    if rec.get("status") != "active":
        raise AgentRevoked("agent 已停用：%s" % agent_id)
    if require_scope and require_scope not in (rec.get("scopes") or []):
        raise AgentError("缺少 scope：%s" % require_scope)
    return rec


def touch(agent_id: str) -> None:
    reg = load_registry()
    rec = (reg.get("agents") or {}).get(agent_id)
    if not rec:
        return
    rec["last_seen"] = _now()
    sha = rec.get("contract_sha256") or contract_sha256()
    reg["agents"][agent_id] = _sign(rec, sha)
    save_registry(reg)


def revoke(agent_id: str) -> Dict:
    reg = load_registry()
    rec = (reg.get("agents") or {}).get(agent_id)
    if not rec:
        raise AgentError("未注册 agent：%s" % agent_id)
    rec["status"] = "revoked"
    sha = rec.get("contract_sha256") or contract_sha256()
    reg["agents"][agent_id] = _sign(rec, sha)
    save_registry(reg)
    return reg["agents"][agent_id]


def list_agents() -> List[Dict]:
    reg = load_registry()
    out = []
    for rec in (reg.get("agents") or {}).values():
        item = dict(rec)
        try:
            verify_record(rec)
            item["valid"] = True
        except Exception as e:
            item["valid"] = False
            item["error"] = str(e)
        out.append(item)
    return sorted(out, key=lambda x: x.get("agent_id", ""))


def ensure_local(owner: str = "若水") -> Dict:
    reg = load_registry()
    if "local" in reg["agents"]:
        return get("local", require_scope="workflow:run")
    return join("local", "本地工作台", owner, accept_contract=True)
