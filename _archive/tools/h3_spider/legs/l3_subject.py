# -*- coding: utf-8 -*-
"""L3 Subject 指代：定义唯一、被使用、使用必有定义。"""
import re
from typing import Dict, List, Optional, Tuple

from ..model import Token
from .base import BaseLeg

SUB_RE = re.compile(r"<Subject (\d+)>")


class L3SubjectLeg(BaseLeg):
    id = "L3"
    check = "subject-referent"
    node_types = {"token"}

    def run(self, tokens: List[Token], text: str, variant: str, shot: str,
            ctx=None) -> Dict[int, Tuple[str, Optional[str], str]]:
        out = {}
        d0 = text.find("subject_definitions:")
        d1 = text.find("summary:")
        if d0 < 0 or d1 < 0:
            # base 模式（i2va/fl2va）本来就没有这两段，不算错误
            if (ctx or {}).get("mode") != "ref2va":
                return out
            if tokens:
                out[tokens[0].id] = ("error", "SUB-00", "缺 subject_definitions/summary 段")
            return out

        defs, uses = {}, []
        for t in tokens:
            m = SUB_RE.fullmatch(t.text)
            if not m:
                continue
            tag = t.text
            if d0 <= t.start < d1:
                defs.setdefault(tag, []).append(t)
            elif t.start >= d1:
                uses.append(t)

        for tag, ts in defs.items():
            if len(ts) > 1:
                out[ts[1].id] = ("error", "SUB-01", "%s 重复定义" % tag)
        used_tags = {t.text for t in uses}
        defined_tags = set(defs)
        for t in uses:
            if t.text not in defined_tags:
                out[t.id] = ("error", "SUB-02", "%s 未定义" % t.text)
        for tag, ts in defs.items():
            if tag not in used_tags:
                out[ts[0].id] = ("error", "SUB-03", "%s 定义了却没用" % tag)
        return out
