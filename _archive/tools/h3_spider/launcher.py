# -*- coding: utf-8 -*-
"""P0 发射器：在 U05 的影子副本上注入 T/M/C。

- T：正常 token，证明腿走到了
- M：已知违规 token，证明腿真的在判
- C：payload hash，证明节点没被改
干净稿与变异稿分开；生产稿永远不注入。
"""
import copy
import hashlib
import json
import os
from typing import Dict, Tuple

from .model import Node
from .lexer import tokenize, TOKENIZER_VERSION
from .recover import diff_edits
from .legs import validate_capability


def sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _find(tokens, text):
    for t in tokens:
        if t.text == text:
            return t
    return None


def build_case(clean_text: str, shot: str, run_id: str, out_dir: str
               ) -> Tuple[Dict[str, str], dict]:
    tokens = tokenize(clean_text)
    d_open = _find(tokens, "<d>")
    d_close = _find(tokens, "</d>")
    s1 = _find(tokens, "(S1)")
    if not (d_open and d_close and s1):
        raise ValueError("U05 影子稿缺少 <d>/</d>/(S1)，无法注入 P0 节点")

    # 变异 1：去掉 </d>（长度变化只在 d_close 之后）
    # 变异 2：(S1) -> (S2)（等长，d_close 偏移不变）
    mutant = clean_text[:s1.start] + "(S2)" + clean_text[s1.end:]
    mutant = mutant[:d_close.start] + mutant[d_close.end:]

    nodes = [
        Node("T-L2", "T", "L2", "dialogue-balance", "token", shot, "clean",
             d_open.start, d_open.end, "<d>", "<d>", "ok", None).to_dict(),
        Node("T-L5", "T", "L5", "speaker-order", "token", shot, "clean",
             s1.start, s1.end, "(S1)", "(S1)", "ok", None).to_dict(),
        Node("M-L2", "M", "L2", "dialogue-balance", "token", shot, "mutant",
             d_open.start, d_open.end, "<d>", "<d>（未闭合）", "error", "DLG-01",
             note="删除了 </d> @%d" % d_close.start,
             edit_start=d_close.start, edit_end=d_close.end,
             edit_original="</d>", edit_mutated="").to_dict(),
        Node("M-L5", "M", "L5", "speaker-order", "token", shot, "mutant",
             s1.start, s1.end, "(S1)", "(S2)", "error", "SPK-02",
             note="(S1) 改成 (S2)",
             edit_start=s1.start, edit_end=s1.end,
             edit_original="(S1)", edit_mutated="(S2)").to_dict(),
        Node("C-L2", "C", "L2", "dialogue-balance", "token", shot, "clean",
             d_open.start, d_close.end, "<d>…</d>", "<d>…</d>", "ok", None,
             payload_sha1=sha1_text(clean_text[d_open.start:d_close.end])).to_dict(),
        Node("C-L5", "C", "L5", "speaker-order", "token", shot, "clean",
             s1.start, s1.end, "(S1)", "(S1)", "ok", None,
             payload_sha1=sha1_text(clean_text[s1.start:s1.end])).to_dict(),
    ]

    cap_skips = validate_capability(nodes)
    bad_ids = {x.get("node_id") for x in cap_skips}
    nodes = [n for n in nodes if n.get("node_id") not in bad_ids]
    manifest = {
        "run_id": run_id,
        "shot": shot,
        "tokenizer": TOKENIZER_VERSION,
        "edits": diff_edits(clean_text, mutant),
        "not_applicable": [],
        "capability_skips": cap_skips,
        "variants": {"clean": "clean.txt", "mutant": "mutant.txt"},
        "nodes": nodes,
    }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "clean.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(clean_text)
    with open(os.path.join(out_dir, "mutant.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(mutant)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    return {"clean": clean_text, "mutant": mutant}, manifest


def build_full_case(clean_text: str, shot: str, run_id: str, out_dir: str,
                    project_dir: str, input_dir: str) -> Tuple[dict, dict]:
    """P1：U05 全 8 腿。文本变异 + 资产/场景记录变异。"""
    from .project import build_context

    ctx = build_context(project_dir, shot, input_dir)

    # ---- 文本变异 -----------------------------------------------------
    mut = clean_text
    if "a tall woman" not in mut:
        raise ValueError("U05 稿里找不到角色卡外观锚 'a tall woman'，无法构造 L6 变异")
    mut = mut.replace("a tall woman", "a tall woman in a plain grey tunic", 1)

    i = mut.find("(S1)")
    if i < 0:
        raise ValueError("U05 稿里找不到 (S1)，无法构造 L5 变异")
    mut = mut[:i] + "(S2)" + mut[i + 4:]

    i = mut.find("</d>")
    if i < 0:
        raise ValueError("U05 稿里找不到 </d>，无法构造 L2 变异")
    mut = mut[:i] + mut[i + 4:]

    mut += ("\n\noverall_soundscape: Duplicate soundscape for P1.\n"
            " <Subject 9>\n <Picture 9>\n")

    clean_tokens = tokenize(clean_text)
    mut_tokens = tokenize(mut)

    def first(tokens, s):
        for t in tokens:
            if t.text == s:
                return t
        raise ValueError("找不到 token %r" % s)

    def last(tokens, s):
        found = [t for t in tokens if t.text == s]
        if not found:
            raise ValueError("找不到 token %r" % s)
        return found[-1]

    d_open = first(clean_tokens, "<d>")
    d_close = first(clean_tokens, "</d>")
    s1 = first(clean_tokens, "(S1)")
    sub1 = first(clean_tokens, "<Subject 1>")
    pic1 = first(clean_tokens, "<Picture 1>")
    field0 = first(clean_tokens, "subject_definitions")
    d0 = clean_text.find("subject_definitions:")
    d1 = clean_text.find("summary:")
    if d0 < 0 or d1 < 0:
        raise ValueError("U05 稿缺 subject_definitions/summary")

    m_l1 = last(mut_tokens, "overall_soundscape")
    m_l2 = first(mut_tokens, "<d>")
    m_l3 = first(mut_tokens, "<Subject 9>")
    m_l4 = first(mut_tokens, "<Picture 9>")
    m_l5 = first(mut_tokens, "(S2)")
    m_l6 = first(mut_tokens, "<Subject 1>")

    # ---- 资产/场景变异 ------------------------------------------------
    clean_assets = ctx["assets"]
    clean_scenes = ctx["scenes"]
    mut_assets = copy.deepcopy(clean_assets)
    mut_scenes = copy.deepcopy(clean_scenes)

    target_asset = next((a for a in mut_assets if a["asset_id"] == "cmdr"),
                        mut_assets[0])
    target_asset["staged_sha1"] = "bad"
    target_asset_id = target_asset["asset_id"]

    target_scene = mut_scenes[0]
    target_scene["base_outside"] = "A shattered planet fills the window."
    target_scene_id = target_scene["scene_id"]

    clean_asset = next(a for a in clean_assets if a["asset_id"] == target_asset_id)
    clean_scene = clean_scenes[0]

    def nd(node_id, kind, leg, check, node_type, variant, start, end,
           original, mutated, status, code, target_id=None, payload=None, note=""):
        return Node(node_id, kind, leg, check, node_type, shot, variant,
                    start, end, original, mutated, status, code,
                    payload_sha1=payload, note=note, target_id=target_id).to_dict()

    nodes = [
        nd("T-L1", "T", "L1", "field-structure", "token", "clean",
           field0.start, field0.end, "subject_definitions", "subject_definitions", "ok", None),
        nd("M-L1", "M", "L1", "field-structure", "token", "mutant",
           m_l1.start, m_l1.end, "overall_soundscape", "overall_soundscape", "error", "FMT-02"),
        nd("C-L1", "C", "L1", "field-structure", "token", "clean",
           0, len(clean_text), "whole prompt", "whole prompt", "ok", None,
           payload=sha1_text(clean_text)),
        nd("T-L2", "T", "L2", "dialogue-balance", "token", "clean",
           d_open.start, d_open.end, "<d>", "<d>", "ok", None),
        nd("M-L2", "M", "L2", "dialogue-balance", "token", "mutant",
           m_l2.start, m_l2.end, "<d>", "<d>（未闭合）", "error", "DLG-01",
           note="删除了 </d>"),
        nd("C-L2", "C", "L2", "dialogue-balance", "token", "clean",
           d_open.start, d_close.end, "<d>…</d>", "<d>…</d>", "ok", None,
           payload=sha1_text(clean_text[d_open.start:d_close.end])),
        nd("T-L3", "T", "L3", "subject-referent", "token", "clean",
           sub1.start, sub1.end, "<Subject 1>", "<Subject 1>", "ok", None),
        nd("M-L3", "M", "L3", "subject-referent", "token", "mutant",
           m_l3.start, m_l3.end, "<Subject 9>", "<Subject 9>", "error", "SUB-02"),
        nd("C-L3", "C", "L3", "subject-referent", "token", "clean",
           d0, d1, "defs", "defs", "ok", None, payload=sha1_text(clean_text[d0:d1])),
        nd("T-L4", "T", "L4", "picture-slot", "token", "clean",
           pic1.start, pic1.end, "<Picture 1>", "<Picture 1>", "ok", None),
        nd("M-L4", "M", "L4", "picture-slot", "token", "mutant",
           m_l4.start, m_l4.end, "<Picture 9>", "<Picture 9>", "error", "PIC-02"),
        nd("C-L4", "C", "L4", "picture-slot", "token", "clean",
           d0, d1, "defs", "defs", "ok", None, payload=sha1_text(clean_text[d0:d1])),
        nd("T-L5", "T", "L5", "speaker-order", "token", "clean",
           s1.start, s1.end, "(S1)", "(S1)", "ok", None),
        nd("M-L5", "M", "L5", "speaker-order", "token", "mutant",
           m_l5.start, m_l5.end, "(S1)", "(S2)", "error", "SPK-02"),
        nd("C-L5", "C", "L5", "speaker-order", "token", "clean",
           s1.start, s1.end, "(S1)", "(S1)", "ok", None,
           payload=sha1_text(clean_text[s1.start:s1.end])),
        nd("T-L6", "T", "L6", "appearance-source", "token", "clean",
           sub1.start, sub1.end, "<Subject 1>", "<Subject 1>", "ok", None),
        nd("M-L6", "M", "L6", "appearance-source", "token", "mutant",
           m_l6.start, m_l6.end, "<Subject 1>", "<Subject 1>", "error", "SRC-01"),
        nd("C-L6", "C", "L6", "appearance-source", "token", "clean",
           d0, d1, "defs", "defs", "ok", None, payload=sha1_text(clean_text[d0:d1])),
        nd("T-L7", "T", "L7", "asset-chain", "asset", "clean",
           0, 0, clean_asset["asset_id"], clean_asset["asset_id"], "ok", None,
           target_id=clean_asset["asset_id"]),
        nd("M-L7", "M", "L7", "asset-chain", "asset", "mutant",
           0, 0, clean_asset["asset_id"], clean_asset["asset_id"], "error", "AST-02",
           target_id=target_asset_id),
        nd("C-L7", "C", "L7", "asset-chain", "asset", "clean",
           0, 0, clean_asset["asset_id"], clean_asset["asset_id"], "ok", None,
           target_id=clean_asset["asset_id"], payload=clean_asset.get("sha1")),
        nd("T-L8", "T", "L8", "scene-state", "scene", "clean",
           0, 0, clean_scene["scene_id"], clean_scene["scene_id"], "ok", None,
           target_id=clean_scene["scene_id"]),
        nd("M-L8", "M", "L8", "scene-state", "scene", "mutant",
           0, 0, clean_scene["scene_id"], clean_scene["scene_id"], "error", "SCN-01",
           target_id=target_scene_id),
        nd("C-L8", "C", "L8", "scene-state", "scene", "clean",
           0, 0, clean_scene["scene_id"], clean_scene["scene_id"], "ok", None,
           target_id=clean_scene["scene_id"],
           payload=sha1_text((clean_scene.get("state_text") or "") + "|" +
                             (clean_scene.get("state_source") or ""))),
    ]

    cap_skips = validate_capability(nodes)
    bad_ids = {x.get("node_id") for x in cap_skips}
    nodes = [n for n in nodes if n.get("node_id") not in bad_ids]
    manifest = {
        "run_id": run_id,
        "shot": shot,
        "tokenizer": TOKENIZER_VERSION,
        "edits": diff_edits(clean_text, mut),
        "not_applicable": [],
        "capability_skips": cap_skips,
        "variants": {
            "clean": {"text": "clean.txt", "assets": "assets_clean.json",
                      "scenes": "scenes_clean.json"},
            "mutant": {"text": "mutant.txt", "assets": "assets_mutant.json",
                       "scenes": "scenes_mutant.json"},
        },
        "nodes": nodes,
    }

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "clean.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(clean_text)
    with open(os.path.join(out_dir, "mutant.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(mut)
    with open(os.path.join(out_dir, "assets_clean.json"), "w", encoding="utf-8") as f:
        json.dump(clean_assets, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "assets_mutant.json"), "w", encoding="utf-8") as f:
        json.dump(mut_assets, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "scenes_clean.json"), "w", encoding="utf-8") as f:
        json.dump(clean_scenes, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "scenes_mutant.json"), "w", encoding="utf-8") as f:
        json.dump(mut_scenes, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    variants = {
        "clean": {"text": clean_text, "assets": clean_assets,
                  "scenes": clean_scenes, "meta": ctx["meta"]},
        "mutant": {"text": mut, "assets": mut_assets,
                   "scenes": mut_scenes, "meta": ctx["meta"]},
    }
    return variants, manifest
