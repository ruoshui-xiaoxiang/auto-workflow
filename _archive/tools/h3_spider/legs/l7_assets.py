# -*- coding: utf-8 -*-
"""L7 资产链：存在、crop→staged sha1、人脸数。"""
from typing import Dict, Optional, Tuple

from .base import BaseLeg


class L7AssetLeg(BaseLeg):
    id = "L7"
    check = "asset-chain"
    node_types = {"asset"}

    def run_assets(self, assets, variant: str, shot: str, ctx=None
                   ) -> Dict[str, Tuple[str, Optional[str], str]]:
        out = {}
        for a in assets:
            aid = a["asset_id"]
            if not a.get("exists"):
                out[aid] = ("error", "AST-01", "crop 或 staged 不存在")
                continue
            crop = a.get("crop")
            if crop is not None:
                ok = (isinstance(crop, (list, tuple)) and len(crop) == 4
                      and all(isinstance(x, (int, float)) for x in crop)
                      and 0 <= crop[0] < crop[2] <= 1
                      and 0 <= crop[1] < crop[3] <= 1)
                if not ok:
                    out[aid] = ("error", "AST-04",
                                "crop 非法：%r（需 0<=x0<x1<=1 且 0<=y0<y1<=1）"
                                % (crop,))
                    continue
            if not a.get("staged_sha1") or a.get("sha1") != a.get("staged_sha1"):
                out[aid] = ("error", "AST-02",
                            "crop sha1 != staged sha1（%s vs %s）"
                            % (str(a.get("sha1"))[:8], str(a.get("staged_sha1"))[:8]))
                continue
            exp = a.get("expected_faces")
            faces = a.get("faces")
            if exp is not None and faces is not None and faces != exp:
                out[aid] = ("error", "AST-03",
                            "人脸数 %s，期望 %s" % (faces, exp))
        return out
