# -*- coding: utf-8 -*-
"""L1 字段结构：官方字段齐全、唯一、顺序正确。"""
import re
from typing import Dict, List, Optional, Tuple

from ..model import Token
from .base import BaseLeg

REF_FIELDS = ["subject_definitions:", "summary:", "retention_analysis:",
              "detailed_description:", "overall_soundscape:", "non_diegetic_music:"]
BASE_FIELDS = ["integrated_multimodal_description:", "overall_soundscape:",
               "non_diegetic_music:"]
# 与 h3_official_spec.TASK_TYPES 同步（ref-en §3 的 6 个官方面值）
TASK_TYPES = ("keyframe completion", "reference generation", "video editing",
              "video continuation", "audio reuse", "audio reference")


class L1FormatLeg(BaseLeg):
    id = "L1"
    check = "field-structure"
    node_types = {"token"}

    def run(self, tokens: List[Token], text: str, variant: str, shot: str,
            ctx=None) -> Dict[int, Tuple[str, Optional[str], str]]:
        out = {}
        mode = (ctx or {}).get("mode") or ""
        fields = REF_FIELDS if (mode == "ref2va" or "subject_definitions:" in text) else BASE_FIELDS

        def tok_at(pos):
            for t in tokens:
                if t.start == pos:
                    return t
            return tokens[0] if tokens else None

        positions = {}
        for f in fields:
            ps = []
            i = text.find(f)
            while i >= 0:
                ps.append(i)
                i = text.find(f, i + len(f))
            positions[f] = ps

        for f in fields:
            ps = positions[f]
            if not ps:
                t = tokens[0] if tokens else None
                if t:
                    out[t.id] = ("error", "FMT-01", "缺少字段 %s" % f)
            elif len(ps) > 1:
                t = tok_at(ps[1])
                if t:
                    out.setdefault(t.id, ("error", "FMT-02", "字段重复 %s" % f))

        if all(len(positions[f]) == 1 for f in fields):
            seq = [positions[f][0] for f in fields]
            for i in range(1, len(seq)):
                if seq[i] < seq[i - 1]:
                    t = tok_at(seq[i])
                    if t:
                        out.setdefault(t.id, ("error", "FMT-03", "字段顺序错误"))
                    break

        # ref-en §3：summary 必须以方括号任务类型前缀开头，类型只能取官方 6 值。
        # 只在 Ref2VA 六段稿上判；骨架模式没有 summary 段。
        if "summary:" in text:
            s0 = text.find("summary:") + len("summary:")
            s1 = text.find("retention_analysis:", s0)
            summ = text[s0:(s1 if s1 >= 0 else len(text))].strip()
            t = tok_at(text.find("summary:"))
            m = re.match(r"\[([^\]]+)\]", summ)
            if not m:
                if t:
                    out.setdefault(t.id, ("error", "FMT-04",
                                          "summary 缺方括号任务类型前缀"))
            else:
                bad = [x.strip() for x in m.group(1).split("+")
                       if x.strip() not in TASK_TYPES]
                if bad and t:
                    out.setdefault(t.id, ("error", "FMT-04",
                                          "summary 任务类型不在官方 6 值：%s"
                                          % ", ".join(bad)))
        return out
