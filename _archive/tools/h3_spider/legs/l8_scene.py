# -*- coding: utf-8 -*-
"""L8 场景状态：基础描述必须中性、状态必须有锚。"""
from typing import Dict, Optional, Tuple

from .base import BaseLeg

STATE_WORDS = ("shattered", "intact", "fragments", "fissures", "debris",
               "broken", "crumbling", "decayed")


def _norm(s):
    return " ".join((s or "").lower().split())


class L8SceneLeg(BaseLeg):
    id = "L8"
    check = "scene-state"
    node_types = {"scene"}

    def run_scenes(self, scenes, variant: str, shot: str, ctx=None
                   ) -> Dict[str, Tuple[str, Optional[str], str]]:
        out = {}
        meta = ctx or {}
        timeline = meta.get("state_timeline") or {}
        shot_ids = meta.get("shot_ids") or []
        for sc in scenes:
            sid = sc["scene_id"]
            base = (sc.get("base_outside") or "").lower()
            found = [w for w in STATE_WORDS if w in base]
            if found:
                out[sid] = ("error", "SCN-01",
                            "基础 outside 含状态词：%s" % ", ".join(found))
                continue

            state_text = sc.get("state_text") or ""
            source = sc.get("state_source")
            if not state_text and not source:
                out[sid] = ("error", "SCN-02", "没有状态锚，也没有就近沿用")
                continue

            if source:
                src_shot = str(source).split(":", 1)[0]
                if shot_ids and src_shot not in shot_ids:
                    out[sid] = ("error", "SCN-03",
                                "state_source 指向未知镜头：%s" % source)
                    continue
                if (shot_ids and shot in shot_ids
                        and src_shot in shot_ids
                        and shot_ids.index(src_shot) > shot_ids.index(shot)):
                    out[sid] = ("error", "SCN-03",
                                "state_source 指向本镜之后的镜头：%s" % source)
                    continue
                expected = timeline.get(src_shot)
                if expected is None:
                    out[sid] = ("error", "SCN-03",
                                "state_source 在 state_timeline 里没有登记：%s"
                                % source)
                    continue
                if _norm(state_text) != _norm(expected):
                    out[sid] = ("error", "SCN-04",
                                "state_text 与 %s 的登记状态不一致" % source)
                continue

            # 没有 state_source 但写了 state_text：必须与本镜登记状态一致。
            expected = timeline.get(shot)
            if expected is not None and _norm(state_text) != _norm(expected):
                out[sid] = ("error", "SCN-04",
                            "state_text 与本镜 state_timeline 登记状态不一致")
        return out
