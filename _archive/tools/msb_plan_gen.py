# -*- coding: utf-8 -*-
"""msb_plan_gen.py — agent 侧 MSB plan 生成器(房规预埋 + 过官方契约闸)。

定位:把 agent 写好的分镜故事(story JSON)变成 MinimaxStoryBuilder 能直接吃的
两份产物 —— plan.json(粘进 MinimaxStoryPlanFromJSON)与 cast_bridge.json
(粘进 zd_msb_bridge 的 ZDStoryCastFromImages)。每镜的最终提示词由本机
h3_official_spec.fill() 按官方骨架强制拼出,并当场过 validate() 闸——
闸审什么,Director 的 prompt_override 就原样渲什么。

story JSON 格式(字段详见 README_MS PLAN.md):
{
  "project_id": "msb_demo",                 // 必须 ASCII
  "style": "Live-action, cinematic, ...",   // 全局风格句
  "mood": "tense, quiet",                    // 可选
  "characters": [{"name": "君仪", "sheet": "D:/.../S1_1.png",
                  "identity": "...", "appearance": "...", "voice": "...", "seen": true}],
  "locations": [{"name": "天台", "plate": "D:/.../plate.png"}],   // plate 可空
  "shots": [{
     "seconds": 5.17,                        // 4–15,吸附到 17n+5 帧格
     "location": "天台", "characters": ["君仪"],
     "text": "……",                           // 官方骨架英文正文([Shot 1] 后的内容)
     "camera": ["Static Shot", "with small amplitude", "at slow speed", "holding on her"],
     "house": {"axis": "...", "env": "...", "lock": "..."},          // R4-19:双实体镜必填 axis
     "ref2va": {"subject_definitions": "…{{君仪}}…", "summary": "...", "retention_analysis": "..."},
     "dialogue": [{"speaker": "君仪", "line": "十八字以内的台词", "delivery": "low, flat"}],
     "soundscape": "...", "music": "N/A"
  }]
}

用法: py -3.12 msb_plan_gen.py --story story.json --out out_dir
退出码: 0=全绿; 1=有 error。warn 不拦。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import h3_official_spec as spec  # noqa: E402

FPS = 24
GRID_LO, GRID_HI = 124, 362          # 17n+5 帧格(他们 T8 包实测口径)
MAX_DIALOGUE_CHARS = 18              # 房规:≤18 字 / 5.17 秒
NEGATIVE_RX = re.compile(r"\b(no|not|without|never|avoid|stop)\b", re.I)
MULTI_AXIS_RX = re.compile(r"SPATIAL ANCHOR:", re.I)


def snap_frames(seconds):
    n = int(round(float(seconds) * FPS))
    k = round((n - 5) / 17)
    k = max(0, k)
    frames = 17 * k + 5
    frames = max(GRID_LO, min(GRID_HI, frames))
    return frames, round(frames / FPS, 2)


class Qc(object):
    def __init__(self):
        self.errors, self.warns = [], []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warns.append(msg)


def build_shot(story, shot, idx, qc):
    name = "shot %d" % (idx + 1)
    seconds = shot.get("seconds")
    if seconds is None:
        qc.err("%s: 缺 seconds" % name)
        return None
    frames, seconds = snap_frames(seconds)
    if not (spec.DURATION_RANGE[0] <= seconds <= spec.DURATION_RANGE[1]):
        qc.err("%s: %.2fs 不在官方 4–15 秒" % (name, seconds))
        return None

    location = str(shot.get("location") or "").strip()
    known_locations = [c["name"] for c in story.get("locations") or []]
    if location not in known_locations:
        qc.err("%s: location %r 不在 cast.locations" % (name, location))

    chars = [str(c).strip() for c in shot.get("characters") or []]
    known_chars = [c["name"] for c in story.get("characters") or []]
    for c in chars:
        if c not in known_chars:
            qc.err("%s: 角色 %r 不在 cast.characters" % (name, c))

    dialogue = []
    for line in shot.get("dialogue") or []:
        speaker = str(line.get("speaker") or "").strip()
        line_text = str(line.get("line") or "").strip()
        if speaker not in chars:
            qc.err("%s: 台词说话人 %r 不在本镜 characters 里" % (name, speaker))
        n_chars = len(re.sub(r"\s", "", line_text))
        if n_chars > MAX_DIALOGUE_CHARS:
            qc.err("%s: 台词 %d 字超房规 %d 字(%r)"
                   % (name, n_chars, MAX_DIALOGUE_CHARS, line_text[:20]))
        dialogue.append({
            "speaker": speaker,
            "language": str(line.get("language") or "Chinese"),
            "line": line_text,
            "delivery": str(line.get("delivery") or "").strip(),
            "off_screen": bool(line.get("off_screen")),
        })

    # ---- 官方契约:fill() 强制拼稿 → validate() 当场过闸 ----
    mode = str(shot.get("mode") or "ref2va")
    spec_shot = {"no": 1, "text": str(shot.get("text") or "").strip()}
    cam = shot.get("camera")
    if cam:
        spec_shot["camera"] = cam
    spec_obj = {
        "mode": mode,
        "seconds": seconds,
        "style": str(shot.get("style") or story.get("style") or "").strip(),
        "shots": [spec_shot],
        "house": shot.get("house") or {},
        "soundscape": str(shot.get("soundscape") or "").strip(),
        "music": str(shot.get("music") or "N/A").strip(),
    }
    if mode == "ref2va":
        for field in ("subject_definitions", "summary", "retention_analysis"):
            v = str((shot.get("ref2va") or {}).get(field) or "").strip()
            if not v:
                qc.err("%s: ref2va 模式缺六段之一的 %s" % (name, field))
            spec_obj[field] = v

    # ---- 声线绑定(官方 §2.4/§4.2/§5.4):ref-audio 模式才写;native 模式按 EP1/EP2
    # 配方不挂音频参考、由正文人设描述驱动 H3 原生发音,此块必须整体跳过 —— 否则绑定句
    # 会指向没被渲染的样本名。(旧案:H3 收到音频参考也不会认人,EP3 实测三人同声。)----
    native = str(story.get("voice_mode") or "").strip().lower() == "native"
    if mode == "ref2va" and not native:
        people = {c["name"]: c for c in story.get("characters") or []}
        speakers = []
        for line in dialogue:
            if line["line"] and line["speaker"] not in speakers:
                speakers.append(line["speaker"])
        if speakers:
            by_line = {l["line"]: l for l in dialogue if l["line"]}
            extra_defs, extra_ret = [], []
            for i, speaker in enumerate(speakers):
                extra_defs.append(
                    "{{voice:%s}} is the voice-timbre reference for {{%s}} (S%d), "
                    "containing one spoken Chinese vocal line." % (speaker, speaker, i + 1))
                extra_ret.append(
                    "{{voice:%s}}: reference - the target speaker follows {{voice:%s}}'s "
                    "voice timbre and measured delivery without copying the original signal."
                    % (speaker, speaker))
            spec_obj["subject_definitions"] += "\n" + "\n".join(extra_defs)
            spec_obj["retention_analysis"] += "\n" + "\n".join(extra_ret)
            sx_of = {s: i + 1 for i, s in enumerate(speakers)}

            def _bind(match):
                lang, line = match.group(2), match.group(3).strip()
                entry = by_line.get(line)
                if not entry:
                    qc.warn("%s: 台词 %r 不在 dialogue 里,声线描述未挂" % (name, line[:16]))
                    return match.group(0)
                speaker = entry["speaker"]
                voice = str((people.get(speaker) or {}).get("voice") or "").strip().rstrip(".")
                if not voice:
                    qc.warn("%s: 说话人 %s 无 voice 字段,音色描述留白" % (name, speaker))
                    vphrase = "in its natural speaking voice"
                elif voice.lower().startswith("in "):
                    vphrase = voice
                else:
                    vphrase = "in a %s voice" % voice
                bits = "speaking %s" % vphrase
                delivery = str(entry.get("delivery") or "").strip()
                if delivery:
                    bits += " with %s delivery" % delivery
                bits += (", following the timbre referenced from {{voice:%s}}: "
                         "(S%d)" % (speaker, sx_of.get(speaker, 1)))
                return "%s<d>[%s]%s</d>" % (bits, lang, line)

            spec_shot["text"] = re.sub(
                r"\((S\d+)\)\s*<d>\[([^\]]+)\]([^<]*)</d>", _bind, spec_shot["text"])
    try:
        text = spec.fill(spec_obj)
    except Exception as error:
        qc.err("%s: fill() 拒绝 —— %s" % (name, error))
        return None
    report = spec.validate(text, mode=mode, seconds=seconds, frames=frames, house=True)
    if report.count("error"):
        qc.err("%s: 官方契约 %d 个 error:\n    %s"
               % (name, report.count("error"), "\n    ".join(report.render())))
    # ---- 房规软检查(只 warn)----
    if len(chars) >= 2 and not MULTI_AXIS_RX.search(text):
        qc.warn("%s: 双实体镜没带 SPATIAL ANCHOR(R4-19),确认是有意省略" % name)
    m = NEGATIVE_RX.search(spec_shot["text"])
    if m:
        qc.warn("%s: 正文出现否定词 %r —— H3 禁令即点名,确认是正向描述" % (name, m.group(0)))
    # 未带 sheet 的在场角色
    for c in story.get("characters") or []:
        if c["name"] in chars and not str(c.get("sheet") or "").strip():
            qc.warn("%s: 角色 %s 没有定妆照路径,将按描述渲染" % (name, c["name"]))

    beats = shot.get("beats") or [{
        "start": 0.0, "end": seconds, "action": spec_shot["text"][:160],
        "cut": False, "camera": "", "location": location,
        "time": str(shot.get("time") or "present"),
    }]
    return {
        "index": idx + 1,
        "seconds": seconds,
        "frames": frames,
        "characters": chars,
        "groups": [str(g).strip() for g in shot.get("groups") or []],
        "location": location,
        "pov": str(shot.get("pov") or ""),
        "time": str(shot.get("time") or "present"),
        "pace": str(shot.get("pace") or "normal"),
        "beats": beats,
        "camera": "",
        "action": "",
        "dialogue": dialogue,
        "vocals": str(shot.get("vocals") or ""),
        "soundscape": str(shot.get("soundscape") or "").strip(),
        "music": str(shot.get("music") or "N/A").strip(),
        "prompt_override": text,
    }


def main():
    ap = argparse.ArgumentParser(description="MSB plan 生成器(agent 侧)")
    ap.add_argument("--story", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-long-dialogue", action="store_true",
                    help="放开 ≤18 字房规(降级为 warn)")
    args = ap.parse_args()

    story = json.load(open(args.story, encoding="utf-8"))
    project_id = str(story.get("project_id") or "").strip()
    qc = Qc()
    if not re.match(r"^[A-Za-z0-9_\-]+$", project_id):
        qc.err("project_id %r 必须 ASCII([A-Za-z0-9_-])" % project_id)
    if str(story.get("voice_mode") or "").strip().lower() == "native":
        for c in story.get("characters") or []:
            if str(c.get("voice") or "").strip():
                qc.warn("native 模式下角色 %s 仍带 voice 字段——仍会渲声线样本并挂音频参考"
                        % c.get("name"))
    if args.allow_long_dialogue:
        global MAX_DIALOGUE_CHARS
        MAX_DIALOGUE_CHARS = 10 ** 9

    shots = []
    for i, shot in enumerate(story.get("shots") or []):
        built = build_shot(story, shot, i, qc)
        if built:
            shots.append(built)
    if not shots:
        qc.err("没有可用 shot,中止")

    plan = {
        "_project_id": project_id,
        "cast": {
            "style": str(story.get("style") or "").strip(),
            "mood": str(story.get("mood") or "").strip(),
            "characters": [{
                "name": c["name"],
                "identity": str(c.get("identity") or c.get("appearance") or ""),
                "appearance": str(c.get("appearance") or c.get("identity") or ""),
                "voice": str(c.get("voice") or ""),
                "seen": c.get("seen", True) is not False,
            } for c in story.get("characters") or []],
            "groups": [{"name": g.get("name"), "size": str(g.get("size") or "several people")}
                       for g in story.get("groups") or []],
            "locations": [{"name": c["name"], "look": str(c.get("look") or "")}
                          for c in story.get("locations") or []],
        },
        "shots": shots,
    }
    cast_bridge = {
        "characters": [{
            "name": c["name"],
            "sheet": str(c.get("sheet") or "").strip(),
            "identity": str(c.get("identity") or ""),
            "appearance": str(c.get("appearance") or ""),
            "voice": str(c.get("voice") or ""),
            "seen": c.get("seen", True) is not False,
        } for c in story.get("characters") or []],
        "groups": [{"name": g.get("name"), "size": str(g.get("size") or ""), "plate": ""}
                   for g in story.get("groups") or []],
        "locations": [{
            "name": c["name"],
            "plate": str(c.get("plate") or "").strip(),
        } for c in story.get("locations") or []],
    }
    for entry in cast_bridge["characters"] + cast_bridge["locations"]:
        path = entry.get("sheet") or entry.get("plate")
        if path and not os.path.isfile(path):
            qc.err("参考图不存在: %s (%s)" % (path, entry["name"]))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "cast_bridge.json"), "w", encoding="utf-8") as fh:
        json.dump(cast_bridge, fh, ensure_ascii=False, indent=1)

    lines = ["MSB plan QC — %s" % project_id,
             "shots: %d | frames: %s" % (len(shots), ",".join(str(s["frames"]) for s in shots)),
             ""]
    lines += ["ERROR: " + e for e in qc.errors] or []
    lines += ["WARN: " + w for w in qc.warns] or []
    lines += ["", "结论: %s" % ("FAIL(有 error,勿渲染)" if qc.errors else
                                "PASS(warn %d 条,见上)" % len(qc.warns))]
    report_text = "\n".join(lines)
    with open(os.path.join(args.out, "qc_report.txt"), "w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(report_text)
    return 1 if qc.errors else 0


if __name__ == "__main__":
    sys.exit(main())
