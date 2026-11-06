# -*- coding: utf-8 -*-
"""L5 说话人编号：按本镜第一次发声顺序；同一 Subject 不得多号。"""
import re
from typing import Dict, List, Optional, Tuple

from ..model import Token
from .base import BaseLeg

D_TAG = re.compile(r"<d>\s*\[([^\]]+)\]\s*([\s\S]*?)\s*</d>")
SPEAKER_ID = re.compile(r"\(S\d+(?:,S\d+)*\)")


class L5SpeakerLeg(BaseLeg):
    id = "L5"
    check = "speaker-order"
    node_types = {"token"}

    def run(self, tokens: List[Token], text: str, variant: str, shot: str,
            ctx=None) -> Dict[int, Tuple[str, Optional[str], str]]:
        out: Dict[int, Tuple[str, Optional[str], str]] = {}
        order: Dict[int, int] = {}
        subject_ids: Dict[str, int] = {}
        ret0 = text.find("retention_analysis:")
        ret1 = text.find("detailed_description:", ret0) if ret0 >= 0 else -1

        # base-en §4.4：每个 <d> 前 160 字内必须有 (Sx) 说话人 ID。
        for m in D_TAG.finditer(text):
            pre = text[max(0, m.start() - 160):m.start()]
            if not SPEAKER_ID.search(pre):
                tok = next((t for t in tokens if t.start == m.start()), None)
                if tok is not None:
                    out.setdefault(tok.id, ("error", "SPK-04",
                                            "<d> 前 160 字内没有 (Sx) 说话人 ID"))

        # ref-en §5.4：retention_analysis 里不写 (Sx)。
        if ret0 >= 0:
            ret = text[ret0:(ret1 if ret1 >= 0 else len(text))]
            for m in SPEAKER_ID.finditer(ret):
                tok = next((t for t in tokens if t.start == ret0 + m.start()), None)
                if tok is not None:
                    out.setdefault(tok.id, ("error", "SPK-05",
                                            "retention_analysis 里不写 (Sx)"))

        for t in tokens:
            m = re.fullmatch(r"\(S(\d+)\)", t.text)
            if not m:
                continue
            # retention 的 (Sx) 已由 SPK-05 处理，不参与发声顺序。
            if ret0 >= 0 and ret0 <= t.start < (ret1 if ret1 >= 0 else len(text)):
                continue

            line_start = text.rfind("\n", 0, t.start) + 1
            prefix = text[line_start:t.start]
            subs = re.findall(r"<Subject (\d+)>", prefix)
            if not subs:
                out[t.id] = ("error", "SPK-01", "(Sx) 同句没有 <Subject N>")
                continue

            sid = int(m.group(1))
            key = subs[-1]
            if key in subject_ids and subject_ids[key] != sid:
                out[t.id] = ("error", "SPK-03",
                             "同一 <Subject %s> 出现了不同编号" % key)
                continue
            subject_ids[key] = sid

            if sid not in order:
                order[sid] = len(order) + 1
                if sid != order[sid]:
                    out[t.id] = ("error", "SPK-02",
                                 "编号未按第一次发声顺序：期望 S%d，实际 S%d"
                                 % (order[sid], sid))
        return out
