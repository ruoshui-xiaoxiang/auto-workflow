# -*- coding: utf-8 -*-
"""腿基类：每条腿只读 token，不认识节点；节点标注由 engine 完成。"""
from typing import Dict, List, Optional, Tuple

from ..model import Token


class BaseLeg:
    id = ""
    check = ""
    node_types = set()

    def run(self, tokens: List[Token], text: str, variant: str, shot: str,
            ctx=None) -> Dict[int, Tuple[str, Optional[str], str]]:
        """返回 token_id -> (status, code, message)；未列出的 token 默认 ok。"""
        raise NotImplementedError

    def run_assets(self, assets, variant: str, shot: str, ctx=None):
        """返回 asset_id -> (status, code, message)；没有资产就不覆盖。"""
        return {}

    def run_scenes(self, scenes, variant: str, shot: str, ctx=None):
        """返回 scene_id -> (status, code, message)；没有场景就不覆盖。"""
        return {}
