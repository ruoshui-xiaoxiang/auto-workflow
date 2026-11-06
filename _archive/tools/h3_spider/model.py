# -*- coding: utf-8 -*-
"""蜘蛛质检 P0 · 数据模型（只做编译期：格式/指代/资产）。"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class Token:
    id: int
    text: str
    start: int
    end: int


@dataclass
class Node:
    node_id: str
    kind: str                 # T | M | C
    leg: str                  # L2 / L5 / ...
    check: str
    node_type: str            # token / asset / scene / card
    shot: str
    variant: str              # clean / mutant
    start: int
    end: int
    original: str
    mutated: str
    expected_status: str      # ok | error
    expected_code: Optional[str]
    payload_sha1: Optional[str] = None
    note: str = ""
    target_id: Optional[str] = None
    edit_start: Optional[int] = None
    edit_end: Optional[int] = None
    edit_original: str = ""
    edit_mutated: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Snapshot:
    run_id: str
    variant: str
    shot: str
    leg: str
    check: str
    token_id: int
    start: int
    end: int
    text: str
    status: str               # ok | error | skip
    code: Optional[str]
    node_type: str = "token"
    target_id: Optional[str] = None
    node_ids: List[str] = field(default_factory=list)
    seq: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Verdict:
    run_id: str
    overall: str              # PASS | BLOCK
    legs: Dict[str, Any]
    nodes: List[Dict[str, Any]]
    unexpected_errors: List[Dict[str, Any]]
    canary: Dict[str, Any] = field(default_factory=dict)
    trace_sha1: str = ""
    manifest_sha1: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
