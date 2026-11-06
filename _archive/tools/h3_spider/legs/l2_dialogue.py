# -*- coding: utf-8 -*-
"""L2 台词边界：<d> 配对、语言标签、非空、标点与 voiceover 唇闭合。"""
import re
from typing import Dict, List, Optional, Tuple

from ..model import Token
from .base import BaseLeg

D_TAG = re.compile(r"<d>\s*\[([^\]]+)\]\s*([\s\S]*?)\s*</d>")
LIPS_CLOSED = re.compile(
    r"(lips?\s+(remain|stay|close)|closes?\s+(her|his|their)\s+lips?|"
    r"mouth\s+(closed|shut)|closes?\s+his\s+mouth)", re.I)


class L2DialogueLeg(BaseLeg):
    id = "L2"
    check = "dialogue-balance"
    node_types = {"token"}

    def run(self, tokens: List[Token], text: str, variant: str, shot: str,
            ctx=None) -> Dict[int, Tuple[str, Optional[str], str]]:
        out: Dict[int, Tuple[str, Optional[str], str]] = {}
        stack: List[Token] = []

        for t in tokens:
            if t.text == "<d>":
                stack.append(t)
            elif t.text == "</d>":
                if not stack:
                    out[t.id] = ("error", "DLG-02", "孤立的 </d>")
                else:
                    stack.pop()

        for t in stack:
            out.setdefault(t.id, ("error", "DLG-01", "未闭合的 <d>"))

        # 语言标签与非空：只在能找到闭合标签时判
        open_idx = None
        for i, t in enumerate(tokens):
            if t.text == "<d>":
                open_idx = i
                break
        if open_idx is not None:
            open_tok = tokens[open_idx]
            lang_ok = (open_idx + 3 < len(tokens)
                       and tokens[open_idx + 1].text == "["
                       and tokens[open_idx + 2].text in ("Chinese", "English")
                       and tokens[open_idx + 3].text == "]")
            if not lang_ok:
                out.setdefault(open_tok.id, ("error", "DLG-03", "<d> 后缺 [Chinese]/[English]"))

            close_idx = None
            for j in range(open_idx + 1, len(tokens)):
                if tokens[j].text == "</d>":
                    close_idx = j
                    break
            if close_idx is not None:
                body_tokens = [t for t in tokens[open_idx + 1:close_idx]
                               if t.text not in ("[", "]", "Chinese", "English")]
                if not body_tokens:
                    out.setdefault(open_tok.id, ("error", "DLG-04", "<d> 内没有台词"))

        # base-en §4.4 / ref-en §5.4：<d> 内只放语言标记与原文；标点规范；
        # voiceover 之后必须写嘴唇闭合。
        for m in D_TAG.finditer(text):
            body = m.group(2).strip()
            tok = next((t for t in tokens if t.start == m.start()), None)
            if tok is None:
                continue
            if "[" in body or "]" in body:
                out.setdefault(tok.id, ("error", "DLG-07",
                                        "<d> 内只放语言标记与原文，不能再有方括号"))
            if re.search(r"[!?~]{2,}", body):
                out.setdefault(tok.id, ("error", "DLG-06",
                                        "台词内重复标点：%r" % body[-24:]))
            elif body and body[-1] not in ".?!":
                out.setdefault(tok.id, ("error", "DLG-06",
                                        "完整台词在 </d> 前缺 . ? ! 终止符"))
            pre = text[max(0, m.start() - 160):m.start()]
            if "says in an off-screen voiceover" in pre:
                after = text[m.end():m.end() + 140]
                if not LIPS_CLOSED.search(after):
                    out.setdefault(tok.id, ("error", "DLG-05",
                                            "voiceover 的 <d> 后缺嘴唇闭合"))

        return out
