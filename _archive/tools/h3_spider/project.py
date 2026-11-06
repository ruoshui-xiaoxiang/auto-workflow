# -*- coding: utf-8 -*-
"""从 H3 项目卡构建 P1 上下文：渲染稿、资产链、场景状态、卡外观。只读。"""
import hashlib
import os
from typing import Dict, List

import h3_prompt_builder as B
import h3_precheck as P


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _asset_record(proj: str, input_dir: str, name: str, kind: str,
                  cards, assets_dir: str) -> Dict:
    chars = cards["characters"].get("roles") or {}
    scenes = cards["scenes"].get("scenes") or {}
    if name in chars:
        role = "character"
        ref = chars[name].get("reference") or {}
        source = ref.get("file") or ""
        crop = ref.get("crop")
    elif name in scenes:
        role = "scene"
        ref = scenes[name].get("reference") or {}
        source = ref.get("file") or ""
        crop = ref.get("crop")
    else:
        role = "other"
        source = os.path.join(assets_dir, name) if assets_dir else ""
        crop = None

    # 卡名走 crops/<name>.png；首帧/末帧这类非卡资产直接拿 assets_dir 的原图当源
    if role in ("character", "scene"):
        crop_path = os.path.join(proj, "assets", "crops", name + ".png")
    else:
        crop_path = source
    staged_name = name if os.path.splitext(name)[1] else (name + ".png")
    staged = os.path.join(input_dir, os.path.basename(staged_name))
    exists = os.path.isfile(crop_path) and os.path.isfile(staged)
    sha1 = sha1_file(crop_path) if os.path.isfile(crop_path) else None
    staged_sha1 = sha1_file(staged) if os.path.isfile(staged) else None
    faces = None
    expected_faces = 1 if role == "character" else (0 if role == "scene" else None)
    if role in ("character", "scene") and os.path.isfile(crop_path):
        try:
            faces = P.count_faces(crop_path, kind=role)
            if faces == -1:
                faces = None
        except Exception:
            faces = None
    return {
        "asset_id": name,
        "kind": role,
        "source": source,
        "crop": crop,
        "crop_path": crop_path,
        "staged": staged,
        "exists": exists,
        "sha1": sha1,
        "staged_sha1": staged_sha1,
        "faces": faces,
        "expected_faces": expected_faces,
    }


def build_context(proj: str, shot_id: str, input_dir: str) -> Dict:
    cards = B.load_project(proj)
    defaults = cards["shots"].get("defaults") or {}
    raw = [s for s in cards["shots"]["shots"] if s["id"] == shot_id][0]
    shot = B.normalize_shot(raw, defaults, cards)

    names: List[str] = []
    if shot.get("images"):
        names = list(shot["images"])
    else:
        if shot.get("image"):
            names.append(shot["image"])
        if shot.get("last_image"):
            names.append(shot["last_image"])

    assets_dir = defaults.get("assets_dir") or ""
    assets = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        assets.append(_asset_record(proj, input_dir, name, "", cards, assets_dir))

    sc = shot.get("_scene") or {}
    state = sc.get("_state") or {}
    scene_id = "%s:%s" % (shot_id, shot.get("scene") or "none")
    scenes = [{
        "scene_id": scene_id,
        "shot": shot_id,
        "name": shot.get("scene"),
        "base_outside": sc.get("outside") or "",
        "state_text": state.get("planet") or "",
        "state_source": sc.get("_state_source"),
    }]

    scene_cfg = (cards["scenes"].get("scenes") or {}).get(shot.get("scene")) or {}
    timeline = {x.get("at"): x.get("planet") or ""
                for x in (scene_cfg.get("state_timeline") or [])}
    shot_ids = [s["id"] for s in cards["shots"]["shots"]]
    meta = {
        "mode": shot["mode"],
        "canvas": shot["canvas"],
        "duration": shot["duration"],
        "pictures": len(names),
        "cards": {c["role"]: c.get("appearance") or ""
                  for c in (cards["characters"].get("roles") or {}).values()},
        "state_timeline": timeline,
        "shot_ids": shot_ids,
    }
    return {"assets": assets, "scenes": scenes, "meta": meta}
