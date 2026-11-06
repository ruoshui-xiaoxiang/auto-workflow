# -*- coding: utf-8 -*-
"""L4 Picture 槽位：使用必有定义、定义必有真实槽位、定义应被使用。"""
import re
from typing import Dict, List, Optional, Tuple

from ..model import Token
from .base import BaseLeg

PIC_RE = re.compile(r"<Picture (\d+)>")

# base-en §2.1：官方首行逐字
I2VA_FIRST_LINE = ("For the target video, at 0.00 seconds into the target video, "
                   "<Picture 1> (from [Shot 1]) is fully referenced.")
FL2VA_PREFIX = "How the reference pictures align with the target video — "
L2VA_PREFIX = "How the reference pictures align with the target video — "


class L4PictureLeg(BaseLeg):
    id = "L4"
    check = "picture-slot"
    node_types = {"token"}

    def run(self, tokens: List[Token], text: str, variant: str, shot: str,
            ctx=None) -> Dict[int, Tuple[str, Optional[str], str]]:
        out = {}
        mode = (ctx or {}).get("mode") or ""
        pictures = int((ctx or {}).get("pictures") or 0)
        first = text.split("\n", 1)[0].strip()
        tok0 = tokens[0] if tokens else None

        # base-en §2.1：i2va/fl2va/l2va 的首行是硬声明，必须逐字/逐槽对。
        if mode == "i2va":
            if first != I2VA_FIRST_LINE and tok0:
                out.setdefault(tok0.id, ("error", "PIC-05",
                                         "I2VA 首行不是官方首帧声明"))
            if pictures != 1 and tok0:
                out.setdefault(tok0.id, ("error", "PIC-06",
                                         "I2VA 应有 1 个 Picture，实际 %d" % pictures))
        elif mode == "fl2va":
            duration = float((ctx or {}).get("duration") or 0)
            mark = "%.2f-second mark" % duration
            if (not first.startswith(FL2VA_PREFIX)
                    or "Picture 1" not in first
                    or "0.00-second mark" not in first):
                if tok0:
                    out.setdefault(tok0.id, ("error", "PIC-05",
                                             "FL2VA 首行缺首帧对齐声明"))
            elif "Picture 2" not in first or mark not in first:
                if tok0:
                    out.setdefault(tok0.id, ("error", "PIC-06",
                                             "FL2VA 首行缺末帧 Picture 2 / %.2f 秒声明"
                                             % duration))
            if pictures < 2 and tok0:
                out.setdefault(tok0.id, ("error", "PIC-06",
                                         "FL2VA 应有首末 2 个 Picture，实际 %d" % pictures))
        elif mode == "l2va":
            duration = float((ctx or {}).get("duration") or 0)
            mark = "%.2f-second mark" % duration
            if (not first.startswith(L2VA_PREFIX)
                    or "<Picture 1>" not in first or mark not in first):
                if tok0:
                    out.setdefault(tok0.id, ("error", "PIC-05",
                                             "L2VA 首行缺末帧对齐声明"))
            if pictures != 1 and tok0:
                out.setdefault(tok0.id, ("error", "PIC-06",
                                         "L2VA 应有 1 个末帧 Picture，实际 %d" % pictures))

        d0 = text.find("subject_definitions:")
        d1 = text.find("summary:")
        if d0 < 0 or d1 < 0:
            # base 模式（i2va/fl2va）本来就没有这两段，不算错误
            if (ctx or {}).get("mode") != "ref2va":
                return out
            if tokens:
                out[tokens[0].id] = ("error", "PIC-00", "缺 subject_definitions/summary 段")
            return out

        slots = pictures
        defs, uses = {}, []
        for t in tokens:
            m = PIC_RE.fullmatch(t.text)
            if not m:
                continue
            tag = t.text
            if d0 <= t.start < d1:
                defs.setdefault(tag, []).append(t)
            elif t.start >= d1:
                uses.append(t)

        used_tags = {t.text for t in uses}
        for t in uses:
            if t.text not in defs:
                out[t.id] = ("error", "PIC-02", "%s 未定义/无槽" % t.text)
        for tag, ts in defs.items():
            if len(ts) > 1:
                out.setdefault(ts[1].id, ("error", "PIC-07",
                                          "%s 重复定义" % tag))
            n = int(PIC_RE.fullmatch(tag).group(1))
            if n > slots:
                out[ts[0].id] = ("error", "PIC-03",
                                 "%s 超出本镜资产槽数 %d" % (tag, slots))
            elif tag not in used_tags:
                out[ts[0].id] = ("error", "PIC-04", "%s 定义了却没用" % tag)
        return out
