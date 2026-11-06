# -*- coding: utf-8 -*-
"""h3_trace.py — 渲染来源 trace 与资产链 trace。

设计原则
--------
- **确定性**：同一个 shot/卡/渲染稿，trace 结果不变；只做字符串与 YAML 行号取证。
- **不猜**：能对上卡值的记 `card` + 文件 + 行号；对不上但来自已知模板的记 `template`；
  两者都没有的句子记 `unattributed`，不编造来源。
- **不参与渲染**：本模块只读 shot/text/cards，不改变生产稿。

schema:
  h3-trace-v1            每个镜头的字段/句子/tag/speaker/归一化
  h3-precheck-trace-v1   资产链 source→crop→staged→sha1、faces、state_source
"""
import hashlib
import os
import re

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SCHEMA = "h3-trace-v1"
PRECHECK_SCHEMA = "h3-precheck-trace-v1"

TAG_RE = re.compile(r"<([A-Za-z]+)\s+(\d+)>")
SPEAKER_RE = re.compile(
    r"(<Subject\s+\d+>)\s+\((S\d+)\)\s+says[^:]*:", re.I)
D_TAG_RE = re.compile(r"<d>.*?</d>", re.S)

SKIP_VALUES = {
    "n/a", "none", "null", "true", "false", "chinese", "female", "male",
    "object", "group", "shot 1", "reference generation",
}

TEMPLATES = (
    (re.compile(r"\[Shot 1\]"), "template:shot_line_prefix"),
    (re.compile(r"\bis\b.*\breferenced from\b"), "template:subject_definition"),
    (re.compile(r"environment and composition anchor", re.I),
     "template:scene_anchor_definition"),
    (re.compile(r"appears in \[Shot 1\]"), "template:retention_appears"),
    (re.compile(r"voice-timbre reference"), "template:audio_definition"),
    (re.compile(r"reference\s+—\s+its vocal timbre"), "template:audio_retention"),
    (re.compile(r"\bsays\b"), "template:dialogue_lead"),
    (re.compile(r"closes?\s+\w+\s+lips", re.I), "template:lip_close"),
    (re.compile(r"^N/A\.?$"), "template:music_na"),
)


def sha1_text(s):
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def sha1_file(path):
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def one_line(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def ensure_period(s):
    s = (s or "").strip()
    if not s:
        return s
    return s if s[-1] in ".!?\"')" else s + "."


def _fmt_path(parts):
    out = ""
    for p in parts:
        if isinstance(p, int):
            out += "[%d]" % p
        else:
            out += ("." if out else "") + str(p)
    return out


def card_leaves(path):
    """YAML 标量叶子：{pointer, value, line}。行号 1-based。"""
    if yaml is None or not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            root = yaml.compose(f)
    except Exception:
        return []
    out = []

    def walk(node, parts):
        if isinstance(node, yaml.ScalarNode):
            out.append({"pointer": _fmt_path(parts),
                        "value": "" if node.value is None else str(node.value),
                        "line": node.start_mark.line + 1})
        elif isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                walk(v, parts + [str(k.value)])
        elif isinstance(node, yaml.SequenceNode):
            for i, v in enumerate(node.value):
                walk(v, parts + [i])

    walk(root, [])
    return out


def source_leaves(project_dir, sid):
    """某镜可用的卡来源：本镜 + defaults + 角色卡 + 场景卡。"""
    proj = os.path.abspath(project_dir)
    shot_path = os.path.join(proj, "shots.yaml")
    shots = list(card_leaves(shot_path))
    idx = None
    for leaf in shots:
        if (leaf["pointer"].startswith("shots[")
                and leaf["pointer"].endswith(".id")
                and leaf["value"] == sid):
            m = re.match(r"shots\[(\d+)\]", leaf["pointer"])
            if m:
                idx = int(m.group(1))
            break
    out = []
    if idx is not None:
        pref = "shots[%d]." % idx
        out += [dict(x, file="shots.yaml", kind="shot_card")
                for x in shots if x["pointer"].startswith(pref)]
    out += [dict(x, file="shots.yaml", kind="shot_defaults")
            for x in shots if x["pointer"].startswith("defaults.")]
    for fname, kind, pref in (
            ("characters.yaml", "character_card", "roles."),
            ("scenes.yaml", "scene_card", "scenes.")):
        out += [dict(x, file=fname, kind=kind)
                for x in card_leaves(os.path.join(proj, fname))
                if x["pointer"].startswith(pref)]
    return out


def _aliases(value, aliases_fn):
    if aliases_fn:
        try:
            vals = aliases_fn(value)
            if vals:
                return vals
        except Exception:
            pass
    return [one_line(value), ensure_period(one_line(value))]


def match_sources(text, leaves, aliases_fn=None, limit=4, min_len=4):
    """在 text 中找卡值；返回最长匹配优先的来源。"""
    hay = one_line(text).lower()
    if not hay:
        return []
    found = []
    for leaf in leaves:
        raw = leaf.get("value") or ""
        if len(raw.strip()) < min_len or raw.strip().lower() in SKIP_VALUES:
            continue
        best = None
        best_score = 0
        for a in _aliases(raw, aliases_fn):
            a = one_line(a)
            if len(a) < min_len or a.lower() in SKIP_VALUES:
                continue
            if a.lower() in hay:
                score = len(a)
            elif len(hay) >= min_len and hay in a.lower():
                # 卡值是一整段、输出句子只是其中一句：仍是同一来源。
                score = len(hay)
            else:
                continue
            if score > best_score:
                best, best_score = a, score
        if best:
            found.append({
                "kind": "card",
                "card_kind": leaf.get("kind") or "card",
                "file": leaf.get("file"),
                "pointer": leaf.get("pointer"),
                "line": leaf.get("line"),
                "value": raw,
                "match": best[:120],
                "match_len": best_score,
                "confidence": "exact",
            })
    found.sort(key=lambda x: (-x["match_len"], x.get("file") or "", x.get("line") or 0))
    out, seen = [], set()
    for x in found:
        key = (x.get("file"), x.get("line"), x.get("pointer"))
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
        if len(out) >= limit:
            break
    return out


def sentence_spans(text, start, end):
    seg = text[start:end]
    out, last = [], 0
    for m in re.finditer(r"[.!?](?=\s|$)", seg):
        e = m.end()
        part = seg[last:e]
        if part.strip():
            lead = len(part) - len(part.lstrip())
            out.append((start + last + lead, start + e, part.strip()))
        last = e
    tail = seg[last:]
    if tail.strip():
        lead = len(tail) - len(tail.lstrip())
        out.append((start + last + lead, end, tail.strip()))
    return out


def split_fields(text, labels):
    hits, pos = [], 0
    for i, label in enumerate(labels or []):
        j = text.find(label, pos)
        if j < 0:
            continue
        hits.append((i, label, j))
        pos = j + len(label)
    if not hits:
        return [{"index": 0, "label": "", "template": "output",
                 "start": 0, "end": len(text),
                 "body_start": 0, "body_end": len(text)}]
    out = []
    if hits[0][2] > 0:
        out.append({"index": -1, "label": "__preamble__", "template": "template:first_line",
                    "start": 0, "end": hits[0][2],
                    "body_start": 0, "body_end": hits[0][2]})
    for k, (i, label, j) in enumerate(hits):
        end = hits[k + 1][2] if k + 1 < len(hits) else len(text)
        out.append({"index": i, "label": label,
                    "template": "h3_official_spec.MODES[%d].fields" % i,
                    "start": j, "end": end,
                    "body_start": j + len(label), "body_end": end})
    return out


def field_at(fields, pos):
    for f in fields:
        if f["start"] <= pos < f["end"]:
            return f
    return None


def template_sources(sentence):
    out = []
    for pat, tid in TEMPLATES:
        if pat.search(sentence or ""):
            out.append({"kind": "template", "id": tid,
                        "confidence": "template"})
    return out


def normalizers_for(sentence, sources, normalizers, field):
    steps = set()
    for src in sources:
        if src.get("card_kind") not in ("shot_card", "shot_defaults",
                                        "character_card", "scene_card"):
            continue
        raw = src.get("value") or ""
        if "\n" in raw:
            steps.add("one_line")
        for name, fn in (normalizers or {}).items():
            try:
                if fn(raw) != raw and one_line(fn(raw)).lower() in one_line(sentence).lower():
                    steps.add(name)
            except Exception:
                continue
    if (sentence or "").rstrip().endswith(".") and any(
            not (s.get("value") or "").strip().endswith((".", "!", "?"))
            for s in sources if s.get("kind") == "card"):
        steps.add("ensure_period")
    if "(from <Subject" in sentence:
        steps.add("cite_subjects")
    if "appears in [Shot 1]" in sentence:
        steps.add("retention_template")
    if "<d>" in sentence:
        steps.add("dialogue_normalize")
    if field and src_is_scene(sources) and field.get("label") in (
            "detailed_description:", "integrated_multimodal_description:"):
        steps.add("insert_scene")
    return sorted(steps)


def src_is_scene(sources):
    return any(s.get("card_kind") == "scene_card" for s in sources)


def scan_tags(text, shot, fields, leaves):
    out = []
    first_label = next((f["label"] for f in fields if f["label"] != "__preamble__"),
                       "")
    for m in TAG_RE.finditer(text):
        tag = m.group(0)
        f = field_at(fields, m.start())
        after = text[m.end():m.end() + 180]
        role = ("definition"
                if f and f["label"] == first_label
                and re.search(r"\b(is|are)\b|\breferenced\b", after, re.I)
                else "use")
        src = []
        for sub in shot.get("subjects") or []:
            if sub.get("tag") != tag:
                continue
            rec = {"kind": "cast", "speaker": sub.get("speaker"),
                   "role": sub.get("role"), "card": sub.get("card"),
                   "picture": sub.get("picture")}
            for leaf in leaves:
                if (leaf.get("kind") == "shot_card"
                        and ".cast." in leaf["pointer"]
                        and leaf["value"] == sub.get("card")):
                    rec["card_file"] = leaf.get("file")
                    rec["card_line"] = leaf.get("line")
                    rec["card_pointer"] = leaf.get("pointer")
                    break
            src.append(rec)
        out.append({
            "tag": tag,
            "role": role,
            "field": (f or {}).get("label"),
            "line": text.count("\n", 0, m.start()) + 1,
            "start": m.start(),
            "end": m.end(),
            "sources": src,
        })
    return out


def scan_speakers(text, leaves, aliases_fn=None):
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        matches = list(SPEAKER_RE.finditer(line))
        for i, m in enumerate(matches):
            tail = line[m.end():matches[i + 1].start() if i + 1 < len(matches)
                        else len(line)]
            dm = D_TAG_RE.search(tail)
            dialogue = dm.group(0) if dm else ""
            src = match_sources(dialogue, [x for x in leaves
                                           if x.get("kind") == "shot_card"],
                                aliases_fn, limit=2)
            out.append({
                "order": len(out) + 1,
                "line": ln,
                "speaker": m.group(2),
                "subject_tag": m.group(1),
                "dialogue": dialogue,
                "sources": src,
            })
    return out


def build_shot_trace(shot, text, cards, aliases_fn=None, normalizers=None,
                     field_labels=None):
    proj = os.path.abspath(cards.get("dir") or ".")
    fields = split_fields(text, field_labels or [])
    leaves = source_leaves(proj, shot.get("id"))
    field_out, sentence_out = [], []
    step_counts = {}
    for f in fields:
        body = text[f["body_start"]:f["body_end"]]
        srcs = match_sources(body, leaves, aliases_fn, limit=5)
        field_steps = set()
        for idx, (a, b, sent) in enumerate(
                sentence_spans(text, f["body_start"], f["body_end"])):
            ssrc = match_sources(sent, leaves, aliases_fn, limit=4)
            tmpl = template_sources(sent)
            steps = normalizers_for(sent, ssrc, normalizers, f)
            field_steps.update(steps)
            for s in steps:
                step_counts[s] = step_counts.get(s, 0) + 1
            sentence_out.append({
                "field": f["label"],
                "index": idx,
                "line": text.count("\n", 0, a) + 1,
                "start": a,
                "end": b,
                "text": sent,
                "sources": ssrc + tmpl,
                "normalizers": steps,
                "confidence": "exact" if ssrc else ("template" if tmpl else "unattributed"),
            })
        field_out.append({
            "label": f["label"],
            "template": f["template"],
            "line": text.count("\n", 0, f["start"]) + 1,
            "start": f["start"],
            "end": f["end"],
            "text_sha1": sha1_text(body.strip()),
            "sources": srcs,
            "normalizers": sorted(field_steps),
        })
    tags = scan_tags(text, shot, fields, leaves)
    speakers = scan_speakers(text, leaves, aliases_fn)
    cast = [{"speaker": s.get("speaker"), "subject_tag": s.get("tag"),
             "role": s.get("role"), "picture": s.get("picture"),
             "card": s.get("card")} for s in (shot.get("subjects") or [])]
    card_files = {}
    for name in ("shots.yaml", "characters.yaml", "scenes.yaml", "lexicon.yaml"):
        p = os.path.join(proj, name)
        if os.path.isfile(p):
            card_files[name] = {"path": p, "sha1": sha1_file(p),
                               "lines": len(card_leaves(p))}
    for name in ("shots.yaml", "characters.yaml", "scenes.yaml"):
        if name in card_files and card_files[name]["lines"] == 0:
            raise ValueError("trace 无法读取 %s 的 YAML 标量（文件损坏或编码不对）" % name)
    return {
        "schema": SCHEMA,
        "shot": shot.get("id"),
        "mode": shot.get("mode"),
        "output_sha1": sha1_text(text),
        "fields": field_out,
        "sentences": sentence_out,
        "tags": tags,
        "speakers": speakers,
        "cast": cast,
        "normalization": {
            "steps": sorted(step_counts),
            "counts": step_counts,
        },
        "card_files": card_files,
    }


def _line_of(leaves, pointer_end=None, value=None, prefix=None):
    for leaf in leaves:
        if pointer_end and not leaf["pointer"].endswith(pointer_end):
            continue
        if prefix and not leaf["pointer"].startswith(prefix):
            continue
        if value is not None and leaf["value"] != value:
            continue
        return leaf["line"]
    return None


def _timeline(cards):
    out = {}
    for name, sc in (cards.get("scenes", {}).get("scenes") or {}).items():
        items = []
        for i, st in enumerate(sc.get("state_timeline") or []):
            items.append({"at": st.get("at"), "fields": st,
                          "line": _line_of(
                              card_leaves(os.path.join(os.path.abspath(cards.get("dir") or "."),
                                                       "scenes.yaml")),
                              prefix="scenes.%s.state_timeline[%d]." % (name, i))})
        out[name] = items
    return out


def build_precheck_trace(cards, project_dir, comfy_input, face_counter,
                         scene_for_shot, resolve_fn=None):
    proj = os.path.abspath(project_dir)
    comfy = os.path.abspath(comfy_input) if comfy_input else None
    char_leaves = card_leaves(os.path.join(proj, "characters.yaml"))
    scene_leaves = card_leaves(os.path.join(proj, "scenes.yaml"))
    scene_timeline = _timeline(cards)

    def resolve(p):
        if resolve_fn:
            return resolve_fn(proj, p, cards)
        if not p:
            return None
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(proj, p))

    def chain_record(name, kind, ref, expected_faces):
        source = ref.get("file")
        source_path = resolve(source) if source else None
        crop = ref.get("crop")
        crop_path = os.path.join(proj, "assets", "crops", name + ".png")
        staged = os.path.join(comfy, name + ".png") if comfy else None
        source_ok = bool(source_path and os.path.isfile(source_path))
        crop_ok = bool(crop and len(crop) == 4)
        crop_file_ok = os.path.isfile(crop_path)
        faces = None
        if source_ok:
            try:
                faces = face_counter(source_path, crop, kind)
            except Exception:
                faces = None
        if kind == "character":
            faces_ok = faces == 1
            face_rule = "character: exactly 1"
        else:
            faces_ok = faces == 0
            face_rule = "scene: 0"
        src_sha = sha1_file(source_path) if source_ok else None
        crop_sha = sha1_file(crop_path) if crop_file_ok else None
        staged_ok = None
        staged_sha = None
        if staged:
            staged_ok = os.path.isfile(staged)
            if staged_ok:
                staged_sha = sha1_file(staged)
                if crop_sha and staged_sha != crop_sha:
                    staged_ok = False
        chain_ok = bool(source_ok and crop_ok and crop_file_ok and faces_ok)
        if staged is not None:
            chain_ok = bool(chain_ok and staged_ok)
        return {
            "name": name,
            "kind": kind,
            "source": source_path,
            "source_line": _line_of(char_leaves if kind == "character" else scene_leaves,
                                    value=source or ""),
            "crop": crop,
            "crop_path": crop_path,
            "staged": staged,
            "source_sha1": src_sha,
            "crop_sha1": crop_sha,
            "staged_sha1": staged_sha,
            "faces": faces,
            "face_rule": face_rule,
            "faces_ok": faces_ok,
            "staged_ok": staged_ok,
            "chain_ok": chain_ok,
            "picture_tag": ref.get("picture_tag"),
        }

    assets, scenes = [], []
    for name, c in (cards.get("characters", {}).get("roles") or {}).items():
        rec = chain_record(name, "character", c.get("reference") or {}, 1)
        rec["role"] = c.get("role")
        rec["gender"] = c.get("gender")
        assets.append(rec)
    for name, sc in (cards.get("scenes", {}).get("scenes") or {}).items():
        rec = chain_record(name, "scene", sc.get("reference") or {}, 0)
        rec["geometry"] = sc.get("geometry")
        rec["lighting"] = sc.get("lighting")
        rec["outside"] = sc.get("outside")
        rec["state_timeline"] = scene_timeline.get(name, [])
        scenes.append(rec)

    defaults = cards.get("shots", {}).get("defaults") or {}
    shots = []
    for raw in (cards.get("shots", {}).get("shots") or []):
        shot = dict(defaults)
        shot.update(raw)
        scene = None
        try:
            scene = scene_for_shot(shot, cards)
        except Exception:
            scene = None
        state = (scene or {}).get("_state") or {}
        state_text = " ".join(
            str(state[k]) for k in ("planet", "fleet", "light", "note")
            if state.get(k))
        state_vals = {str(state[k]) for k in ("planet", "fleet", "light", "note")
                      if state.get(k)}
        state_line = None
        for leaf in scene_leaves:
            if (leaf["pointer"].startswith(
                    "scenes.%s.state_timeline[" % (shot.get("scene") or ""))
                    and leaf["value"] in state_vals):
                state_line = leaf["line"]
                break
        need = []
        for k in ("image", "last_image"):
            if shot.get(k):
                need.append((k, shot[k]))
        for img in shot.get("images") or []:
            need.append(("images", img))
        images = [{"field": k, "value": p, "path": resolve(p),
                   "exists": bool(resolve(p) and os.path.isfile(resolve(p)))}
                  for k, p in need]
        shots.append({
            "id": shot.get("id"),
            "mode": shot.get("mode"),
            "scene": shot.get("scene"),
            "state_source": (scene or {}).get("_state_source"),
            "state_text": state_text or None,
            "state_source_line": state_line,
            "images": images,
            "image_ok": all(x["exists"] for x in images) if images else None,
        })

    return {
        "schema": PRECHECK_SCHEMA,
        "project": proj,
        "comfy_input": comfy,
        "assets": assets,
        "scenes": scenes,
        "shots": shots,
        "summary": {
            "assets": len(assets),
            "scenes": len(scenes),
            "shots": len(shots),
            "chain_ok": sum(1 for x in assets + scenes if x["chain_ok"]),
            "chain_bad": sum(1 for x in assets + scenes if not x["chain_ok"]),
        },
    }
