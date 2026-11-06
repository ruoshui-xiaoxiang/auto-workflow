# -*- coding: utf-8 -*-
from .l1_format import L1FormatLeg
from .l2_dialogue import L2DialogueLeg
from .l3_subject import L3SubjectLeg
from .l4_picture import L4PictureLeg
from .l5_speaker import L5SpeakerLeg
from .l6_source import L6SourceLeg
from .l7_assets import L7AssetLeg
from .l8_scene import L8SceneLeg

LEGS = {
    "L1": L1FormatLeg,
    "L2": L2DialogueLeg,
    "L3": L3SubjectLeg,
    "L4": L4PictureLeg,
    "L5": L5SpeakerLeg,
    "L6": L6SourceLeg,
    "L7": L7AssetLeg,
    "L8": L8SceneLeg,
}

CAPABILITY = {
    "L1": {"token", "card"},
    "L2": {"token"},
    "L3": {"token", "card"},
    "L4": {"token", "card", "asset"},
    "L5": {"token"},
    "L6": {"token", "card"},
    "L7": {"asset", "shot"},
    "L8": {"scene", "token", "asset"},
}


def get_legs(ids=None):
    ids = ids or list(LEGS)
    return [LEGS[i]() for i in ids]


def validate_capability(nodes):
    """返回不支持节点类型的注入拒绝记录；调用方必须写进 manifest。"""
    skips = []
    for n in nodes:
        leg = n.get("leg")
        nt = n.get("node_type") or "token"
        if nt not in CAPABILITY.get(leg, set()):
            skips.append({
                "node_id": n.get("node_id"),
                "leg": leg,
                "node_type": nt,
                "reason": "skipped_by_capability",
            })
    return skips
