# -*- coding: utf-8 -*-
"""lex-v2 tokenizer：标签、说话人 ID、ASCII 词、数字、CJK/标点单字符。

固定版本，offset 全部用 Python 字符下标。注入必须发生在本 tokenizer 之后；
版本变化必须让旧 manifest 失效，不能悄悄换。
"""
import re
from typing import List

from .model import Token

TOKENIZER_VERSION = "lex-v2"

TOKEN_RE = re.compile(
    r"<[^>]*>"          # 标签：<d> </d> <Subject 2> <Picture 3>
    r"|\(S\d+\)"        # 说话人： (S1)
    r"|[A-Za-z_][A-Za-z0-9_'\-]*"  # 英文词/字段名（含下划线）
    r"|\d+"             # 数字
    r"|[^\s]"           # CJK / 标点 / 其它单字符
)


def tokenize(text: str) -> List[Token]:
    tokens = []
    for i, m in enumerate(TOKEN_RE.finditer(text)):
        s = m.group(0)
        if not s.strip():
            continue
        tokens.append(Token(id=len(tokens), text=s, start=m.start(), end=m.end()))
    return tokens


def tokens_between(tokens: List[Token], start: int, end: int) -> List[Token]:
    return [t for t in tokens if t.start >= start and t.end <= end]
