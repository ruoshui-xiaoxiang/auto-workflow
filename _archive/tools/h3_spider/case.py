# -*- coding: utf-8 -*-
"""通用单镜 case 构建：按模式/是否有台词/是否有 Subject 段决定注入哪些节点。"""
import copy
import json
import os
from typing import Dict, Tuple

from .launcher import Node, sha1_text
from .project import build_context
from .recover import diff_edits
from .legs import validate_capability
from .lexer import tokenize, TOKENIZER_VERSION


def _first(tokens, text):
    for t in tokens:
        if t.text == text:
            return t
    raise ValueError("找不到 token %r" % text)


def _first_re(tokens, pred, start=0, end=1 << 60):
    for t in tokens:
        if start <= t.start < end and pred(t.text):
            return t
    return None


def _last(tokens, text):
    found = [t for t in tokens if t.text == text]
    if not found:
        raise ValueError("找不到 token %r" % text)
    return found[-1]


def build_shot_case(clean_text: str, shot: str, run_id: str, out_dir: str,
                    project_dir: str, input_dir: str) -> Tuple[dict, dict]:
    ctx = build_context(project_dir, shot, input_dir)
    mode = (ctx.get("meta") or {}).get("mode") or ""
    has_defs = "subject_definitions:" in clean_text
    has_dialogue = "<d>" in clean_text and "</d>" in clean_text
    has_s1 = "(S1)" in clean_text

    clean_tokens = tokenize(clean_text)
    d0 = clean_text.find("subject_definitions:")
    d1 = clean_text.find("summary:")

    # ---- 文本变异 -----------------------------------------------------
    mut = clean_text

    # L6：在第一个 Subject 定义行的外观末尾插一个卡外词
    if has_defs:
        sub0 = _first_re(clean_tokens, lambda s: s.startswith("<Subject"), d0, d1)
        if sub0 is None:
            raise ValueError("有 subject_definitions 但找不到 <Subject N>")
        line_start = clean_text.rfind("\n", 0, sub0.start) + 1
        line_end = clean_text.find("\n", sub0.start)
        if line_end < 0:
            line_end = len(clean_text)
        line = clean_text[line_start:line_end]
        dot = line.rfind(".")
        insert_at = line_start + dot if dot >= 0 else line_end
        mut = mut[:insert_at] + " and a plain grey tunic" + mut[insert_at:]

    # L5：把所有 (S1) -> (S2)（同一镜可能有两句同一说话人；只改第一句会级联出 SPK-03）
    if has_s1:
        if mut.find("(S1)") < 0:
            raise ValueError("找不到 (S1)")
        mut = mut.replace("(S1)", "(S2)")

    # L2：删掉第一个 </d>
    if has_dialogue:
        i = mut.find("</d>")
        if i < 0:
            raise ValueError("找不到 </d>")
        mut = mut[:i] + mut[i + 4:]

    # L1 重复字段；L3/L4 未定义标签
    mut += "\n\noverall_soundscape: Duplicate soundscape for P1.\n"
    if has_defs:
        mut += " <Subject 9>\n <Picture 9>\n"

    mut_tokens = tokenize(mut)
    edits = diff_edits(clean_text, mut)
    not_applicable = []
    if not has_dialogue:
        not_applicable.append({"leg": "L2", "reason": "base mode: no <d>"})
    if not has_defs:
        for leg in ("L3", "L4", "L6"):
            not_applicable.append({"leg": leg, "reason": "base mode: no subject_definitions"})
    if not has_s1:
        not_applicable.append({"leg": "L5", "reason": "no (S1) speaker"})

    nodes = []

    def nd(node_id, kind, leg, check, node_type, variant, start, end,
           original, mutated, status, code, target_id=None, payload=None):
        nodes.append(Node(node_id, kind, leg, check, node_type, shot, variant,
                          start, end, original, mutated, status, code,
                          payload_sha1=payload, target_id=target_id).to_dict())

    # L1
    field_label = "subject_definitions" if has_defs else "integrated_multimodal_description"
    f0 = _first(clean_tokens, field_label)
    nd("T-L1", "T", "L1", "field-structure", "token", "clean",
       f0.start, f0.end, field_label, field_label, "ok", None)
    m1 = _last(mut_tokens, "overall_soundscape")
    nd("M-L1", "M", "L1", "field-structure", "token", "mutant",
       m1.start, m1.end, "overall_soundscape", "overall_soundscape", "error", "FMT-02")
    nd("C-L1", "C", "L1", "field-structure", "token", "clean",
       0, len(clean_text), "whole", "whole", "ok", None, payload=sha1_text(clean_text))

    # L2
    if has_dialogue:
        d_open = _first(clean_tokens, "<d>")
        d_close = _first(clean_tokens, "</d>")
        nd("T-L2", "T", "L2", "dialogue-balance", "token", "clean",
           d_open.start, d_open.end, "<d>", "<d>", "ok", None)
        m2 = _first(mut_tokens, "<d>")
        nd("M-L2", "M", "L2", "dialogue-balance", "token", "mutant",
           m2.start, m2.end, "<d>", "<d>（未闭合）", "error", "DLG-01")
        nd("C-L2", "C", "L2", "dialogue-balance", "token", "clean",
           d_open.start, d_close.end, "<d>…</d>", "<d>…</d>", "ok", None,
           payload=sha1_text(clean_text[d_open.start:d_close.end]))

    if has_defs:
        sub1 = _first_re(clean_tokens, lambda s: s == "<Subject 1>", d0, d1)
        pic1 = _first_re(clean_tokens, lambda s: s == "<Picture 1>", d0, d1)
        # L3
        nd("T-L3", "T", "L3", "subject-referent", "token", "clean",
           sub1.start, sub1.end, "<Subject 1>", "<Subject 1>", "ok", None)
        m3 = _first(mut_tokens, "<Subject 9>")
        nd("M-L3", "M", "L3", "subject-referent", "token", "mutant",
           m3.start, m3.end, "<Subject 9>", "<Subject 9>", "error", "SUB-02")
        nd("C-L3", "C", "L3", "subject-referent", "token", "clean",
           d0, d1, "defs", "defs", "ok", None, payload=sha1_text(clean_text[d0:d1]))
        # L4
        nd("T-L4", "T", "L4", "picture-slot", "token", "clean",
           pic1.start, pic1.end, "<Picture 1>", "<Picture 1>", "ok", None)
        m4 = _first(mut_tokens, "<Picture 9>")
        nd("M-L4", "M", "L4", "picture-slot", "token", "mutant",
           m4.start, m4.end, "<Picture 9>", "<Picture 9>", "error", "PIC-02")
        nd("C-L4", "C", "L4", "picture-slot", "token", "clean",
           d0, d1, "defs", "defs", "ok", None, payload=sha1_text(clean_text[d0:d1]))
        # L6
        nd("T-L6", "T", "L6", "appearance-source", "token", "clean",
           sub1.start, sub1.end, "<Subject 1>", "<Subject 1>", "ok", None)
        m6 = _first(mut_tokens, "<Subject 1>")
        nd("M-L6", "M", "L6", "appearance-source", "token", "mutant",
           m6.start, m6.end, "<Subject 1>", "<Subject 1>", "error", "SRC-01")
        nd("C-L6", "C", "L6", "appearance-source", "token", "clean",
           d0, d1, "defs", "defs", "ok", None, payload=sha1_text(clean_text[d0:d1]))

    # L5
    if has_s1:
        s1 = _first(clean_tokens, "(S1)")
        nd("T-L5", "T", "L5", "speaker-order", "token", "clean",
           s1.start, s1.end, "(S1)", "(S1)", "ok", None)
        m5 = _first(mut_tokens, "(S2)")
        nd("M-L5", "M", "L5", "speaker-order", "token", "mutant",
           m5.start, m5.end, "(S1)", "(S2)", "error", "SPK-02")
        nd("C-L5", "C", "L5", "speaker-order", "token", "clean",
           s1.start, s1.end, "(S1)", "(S1)", "ok", None,
           payload=sha1_text(clean_text[s1.start:s1.end]))

    # ---- 资产/场景 ----------------------------------------------------
    clean_assets = ctx["assets"]
    clean_scenes = ctx["scenes"]
    mut_assets = copy.deepcopy(clean_assets)
    mut_scenes = copy.deepcopy(clean_scenes)

    if clean_assets:
        target = next((a for a in mut_assets if a.get("sha1")), mut_assets[0])
        target["staged_sha1"] = "bad"
        target_id = target["asset_id"]
        clean_asset = next(a for a in clean_assets if a["asset_id"] == target_id)
        nd("T-L7", "T", "L7", "asset-chain", "asset", "clean",
           0, 0, clean_asset["asset_id"], clean_asset["asset_id"], "ok", None,
           target_id=clean_asset["asset_id"])
        nd("M-L7", "M", "L7", "asset-chain", "asset", "mutant",
           0, 0, target_id, target_id, "error", "AST-02", target_id=target_id)
        nd("C-L7", "C", "L7", "asset-chain", "asset", "clean",
           0, 0, clean_asset["asset_id"], clean_asset["asset_id"], "ok", None,
           target_id=clean_asset["asset_id"], payload=clean_asset.get("sha1"))

    if clean_scenes:
        sc = clean_scenes[0]
        mut_scenes[0]["base_outside"] = "A shattered planet fills the window."
        nd("T-L8", "T", "L8", "scene-state", "scene", "clean",
           0, 0, sc["scene_id"], sc["scene_id"], "ok", None, target_id=sc["scene_id"])
        nd("M-L8", "M", "L8", "scene-state", "scene", "mutant",
           0, 0, sc["scene_id"], sc["scene_id"], "error", "SCN-01",
           target_id=sc["scene_id"])
        nd("C-L8", "C", "L8", "scene-state", "scene", "clean",
           0, 0, sc["scene_id"], sc["scene_id"], "ok", None,
           target_id=sc["scene_id"],
           payload=sha1_text((sc.get("state_text") or "") + "|" +
                             (sc.get("state_source") or "")))

    cap_skips = validate_capability(nodes)
    bad_ids = {x.get("node_id") for x in cap_skips}
    nodes = [n for n in nodes if n.get("node_id") not in bad_ids]
    manifest = {
        "run_id": run_id,
        "shot": shot,
        "mode": mode,
        "tokenizer": TOKENIZER_VERSION,
        "edits": edits,
        "not_applicable": not_applicable,
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
