# -*- coding: utf-8 -*-
"""L6 来源与外观：Subject 定义里的外观词必须来自角色卡。"""
import re
from typing import Dict, List, Optional, Tuple

from ..model import Token
from .base import BaseLeg

SUB_RE = re.compile(r"<Subject (\d+)>")
ROLE_RE = re.compile(r"\bis (.+?) referenced from\b")
WORD_RE = re.compile(r"[a-z][a-z'\-]*")

STOP = set("""a an the of with and or in on at to for from by as is are was were be been
her his their its she he they it this that these those into along across over under
not no very slightly softly dark light""".split())

# 只判“同一件东西被换色”这种高置信冲突，不做语义级外观理解。
COLOR_WORDS = set("""black white red crimson scarlet blue navy green gold golden
silver grey gray brown purple violet pink orange yellow beige tan cream ivory
maroon burgundy teal cyan pale dark""".split())
GARMENT_NOUNS = set("""robe coat cape tunic dress shirt blouse skirt trousers
pants boots gloves hair eyes skin lining sash belt armor ornament pieces
embroidery collar sleeve sleeves hood cloak mask pendant necklace earrings""".split())


def _color_pairs(text):
    """从一段外观里抽 (名词, 颜色)，只认同一个小句内 4 词以内的颜色-名词邻接。"""
    pairs = []
    for clause in re.split(r"[,;.]", (text or "").lower()):
        words = WORD_RE.findall(clause)
        for i, w in enumerate(words):
            if w not in COLOR_WORDS:
                continue
            for j in range(i + 1, min(i + 5, len(words))):
                if words[j] in COLOR_WORDS:
                    break
                if words[j] in GARMENT_NOUNS:
                    pairs.append((words[j], w))
                    break
    return pairs


class L6SourceLeg(BaseLeg):
    id = "L6"
    check = "appearance-source"
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
                out[tokens[0].id] = ("error", "SRC-00", "缺 subject_definitions/summary 段")
            return out

        cards = (ctx or {}).get("cards") or {}
        for t in tokens:
            if not SUB_RE.fullmatch(t.text):
                continue
            if not (d0 <= t.start < d1):
                continue
            line_start = text.rfind("\n", 0, t.start) + 1
            line_end = text.find("\n", t.start)
            line = text[line_start:(line_end if line_end >= 0 else len(text))]
            m = ROLE_RE.search(line)
            if not m:
                out[t.id] = ("error", "SRC-02", "Subject 定义行认不出角色")
                continue
            role = m.group(1).strip()
            card = cards.get(role)
            if not card:
                out[t.id] = ("error", "SRC-02", "角色 %r 不在角色卡里" % role)
                continue
            if ":" not in line:
                out[t.id] = ("error", "SRC-02", "Subject 定义行缺外观段")
                continue
            app = line.split(":", 1)[1]
            card_pairs = _color_pairs(card)
            for noun, color in _color_pairs(app):
                card_colors = {c for n, c in card_pairs if n == noun}
                if card_colors and color not in card_colors:
                    out[t.id] = ("error", "SRC-03",
                                 "%s 是 %s，角色卡是 %s" % (
                                     noun, color, "/".join(sorted(card_colors))))
                    break
            if t.id in out:
                continue

            app_words = set(WORD_RE.findall(app.lower()))
            card_words = set(WORD_RE.findall(card.lower()))
            unknown = sorted(app_words - card_words - STOP)
            if unknown:
                out[t.id] = ("error", "SRC-01",
                             "外观词不在角色卡：%s" % ", ".join(unknown[:8]))
        return out
