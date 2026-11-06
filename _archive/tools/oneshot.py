#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""oneshot.py · 一句话 → 提示词 → 本地生图 → 目审闸 → 本地 H3 成片

全程只引用 MiMo 定下的四通道服务，**本脚本不起任何服务、不开任何端口**：
写稿走通道3 的网关 127.0.0.1:8080（后端 8081 那份 qwen3-14b），出图出片走通道4 的 ComfyUI 8189。
零联网、零云端积分、零外部 API。本脚本是**编排层**，不新增规则；要改规则请改真源。

三步用法（同一个 job 号串起来）：
  1) py oneshot.py --say "女剑客雪夜楼顶单挑一台重装机甲" --shots 4
       本地 LLM 写稿 → 官方骨架装配 → 全闸校验；出 prompts/ 与 分镜.md
  2) py oneshot.py --job <id> --stage frames [--anchor 定妆照.png | --chain]
       本地 Z-Image 出首帧 1344×768 → review/contact_sheet.png，**停在目审闸**
  3) py oneshot.py --job <id> --stage video --approve all
       人审放行后逐镜 D 档渲染；再 --stage stitch 拼 16:9 母版

改稿循环：手改 story.json 或 prompts_img/*_cn.txt 后
  py oneshot.py --job <id> --stage render     → 重装配＋重过闸（没过就作废放行记录）
  --llm off＝规则兜底（只保证能出过闸的稿，不保证戏好）

指针（真源在此，本文件只引用）：
  官方骨架常量 ......... D:\\AIWorkflow\\tools\\prompt_format.py  SKELETON_INSTRUCTION / BASE_FIELDS
  闸门 ................. check_h3_all.py · h3_rule_gate.py · check_fight_storyboard.py
  打戏写词卡 ........... E:\\本地工作流规范手册\\20_通用规范层\\R3f_银幕格斗提示词卡.md
  人审金样 ............. D:\\AIWorkflow\\tmp\\fight30v2\\v2_s1_R3f.txt（装配句式照它抄）
  本地出图 ............. D:\\AIWorkflow\\engine\\comfy\\z_style_S6T_textonly_api.json（纯文 6–9s/张）
  本地出片 D 档 ........ D:\\AIWorkflow\\tools\\run_tp_bunny.py（TwoPass 4+4＋Bunny@0.5，10-09 目审定稿）
  四通道规范（真源）.... E:\\LocalAI\\CHANNELS.md · AGENT_DEFAULT.md · D:\\AIWorkflow\\AGENTS.md
  写稿模型归属 ......... 通道3 agent出片引擎：网关 8080 /v1，后端 8081 qwen3-14b、8082 agent档

代码强制的三条：
  · 不起服务、不开端口：通道3 没在听就报错让你双击「agent出片引擎」，不自己补一个 llama-server。
  · 关键帧必须人审通过才渲染 ⇒ video/stitch 没有 --approve 直接退出（rc=2）。
  · 闸门没过 ⇒ 不出图、不出片，且在 gpu 阶段前**重新跑一次**闸（防止稿子被手改后失配）。
"""
from __future__ import print_function

import argparse
import importlib.util
import json
import os
import re
import shutil
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from PIL import Image, ImageDraw

# --------------------------------------------------------------- 路径与端点
D = Path(r"D:\AIWorkflow")
TOOLS = D / "tools"
COMFY_JSON = D / "engine" / "comfy" / "z_style_S6T_textonly_api.json"
COMFY_I2I = D / "engine" / "comfy" / "z_image_i2i_api.json"
H3_INPUT = D / "ComfyUI_H3" / "ComfyUI" / "input"
COMFY = "http://127.0.0.1:8189"
COMFY_OUT = D / "ComfyUI_H3" / "output"
H3_RUNNER = TOOLS / "run_tp_bunny.py"
GATE_ALL = TOOLS / "check_h3_all.py"
GATE_RULE = TOOLS / "h3_rule_gate.py"
GATE_BOARD = TOOLS / "check_fight_storyboard.py"
FFMPEG = TOOLS / "ffmpeg.exe"
JOBROOT = D / "tmp" / "oneshot"

# ---- 官方写稿契约：装配格式的唯一真源＝h3_official_spec.py（照抄 MiniMax-H3 官方 SKILL 的
#      base-en.txt / ref-en.txt）。oneshot 里不再自己拼首行、字段名、运镜句——要改格式改那份。
#      自测：py D:\AIWorkflow\tools\h3_official_spec.py check --selftest（5 份官方样例须全 0 error）
_spec_ms = importlib.util.spec_from_file_location("h3_official_spec", str(TOOLS / "h3_official_spec.py"))
SPEC = importlib.util.module_from_spec(_spec_ms)
_spec_ms.loader.exec_module(SPEC)
GATE_SPEC = TOOLS / "h3_official_spec.py"
# official＝官方自然句（§4.3：运镜写成句内动作，不堆句尾标签）
# house   ＝房内 80 份现役稿与 10-09 人审金样的标签式，只为兼容既有已审稿，不是推荐写法
CAMERA_STYLE = "official"

# ---- 通道3「agent出片引擎」＝本脚本唯一的 LLM 入口。本脚本不起任何服务、不开任何端口。
#      规范真源：E:\LocalAI\CHANNELS.md · AGENT_DEFAULT.md · D:\AIWorkflow\AGENTS.md（2026-10-12 四通道）
GATEWAY = "http://127.0.0.1:8080"
GW_HINT = ("🔴 通道3 网关没起来（8080 连不通）。本脚本按四通道规范**不自起 LLM 服务**，两条路："
           "① 无交互：py D:\\AIWorkflow\\tools\\agent_engine.py up（起网关＋8081 的 qwen3-14b，"
           "会先查净空显存，不够就拒绝而不是卡住）；② 有交互：双击桌面「agent出片引擎」选 1。"
           "显存被 ComfyUI 占着时改 --llm off 走规则兜底（纯 CPU、零端口）。")
CH4_HINT = ("🔴 通道4「本地脚本化出片流水线」的 ComfyUI 没在 127.0.0.1:8189。"
            "双击桌面「本地脚本化出片流水线」（起 8787＋8189），"
            "或看说话出片 UI http://127.0.0.1:8790/。本脚本不代你起服务。")

FRAME_W, FRAME_H = 1344, 768        # H3 原生 1.750；16:9 留到拼片时裁
TP_W, TP_H, TP_LEN = 736, 416, 124  # D 档实测档（736×416≈1.769，成片裁成 736×414 才是 16:9）
# 首行（I2VA/FL2VA/L2VA 的 verbatim 指令行）不在这儿写死，一律由 SPEC.first_line(mode,...) 生成，
# 免得两处各有一份、改一处另一处仍旧稿。

CAM_TYPES = list(SPEC.CAMERA_NAMES) + list(SPEC.CAMERA_ALIAS)   # 官方全称＋简写（简写只用于识别）
CAM_CANON = {k.lower(): v for k, v in SPEC.CAMERA_ALIAS.items()}  # 输出时换回官方全称（base-en §4.3）
# 与 check_h3_dialogue.py 的 D9/GEAR 同尺（大小写不敏感，'no' 也算）——闸怎么判我们就怎么自检
NEG_RE = re.compile(r"\b(NO|NOT|Never|none|no)\b|禁止|不要|不得|不许|避免|严禁|切勿|\bwithout\b|\bavoid\b", re.I)
GEAR_RE = SPEC.GEAR          # 官方 §4.3 只给运动类型，器材名词（dolly/gimbal…）不属受控词表
EYELINE_RE = re.compile(r"(three-quarter|profile|gaze|eyes (are )?fixed|looks toward|"
                        r"facing (left|right))", re.I)
SPEECHV_RE = re.compile(r"(says|said|exclaims|replies|answers|whispers|shouts|asks|mutters|"
                        r"calls|cries)\b", re.I)
INSTANT_RE = r"\b(at once|in the same (?:motion|beat|instant)|on the same beat|in one motion)\b"
CJK_RE = re.compile(u"[\u3400-\u9fff\uf900-\ufaff]")   # H3R23：重写段落必须英文
NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")   # 子进程中文报告别再按 gbk 吐


def log(*a):
    print(*a, flush=True)


def req(base, path, method="GET", payload=None, timeout=240):
    """唯一外呼出口：只允许 127.0.0.1，其余当场抛错——"不联网"就是这么实现的。"""
    if not base.startswith("http://127.0.0.1"):
        raise RuntimeError("🔴 本工具零联网，拒绝非本机端点：%s%s" % (base, path))
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(base + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        raw = x.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def sh(cmd, timeout=1200):
    r = subprocess.run(cmd, capture_output=True, env=ENV, timeout=timeout)
    txt = b"".join([r.stdout or b"", r.stderr or b""]).decode("utf-8", "replace")
    return r.returncode, txt


# --------------------------------------------------------------- 通道3 网关（唯一 LLM 入口）
def gw_model_ids():
    """问网关要模型清单。连不通＝通道3 没起，按规范报"该起通道3"，绝不自己补一个端口。"""
    try:
        d = req(GATEWAY, "/v1/models", timeout=6)
    except Exception:
        raise RuntimeError(GW_HINT)
    items = d.get("data") if isinstance(d, dict) else d
    ids = []
    for m in items or []:
        if isinstance(m, dict):
            ids.append(str(m.get("id") or m.get("name") or ""))
        elif isinstance(m, str):
            ids.append(m)
    return [i for i in ids if i]


def gw_candidates():
    """按"最可能活着且最强"排序的候选模型。
    网关的 /v1/models 与 /admin/status 只列**配置里**的后端，不报存活；死了的后端会在
    POST 时回 503 backend_unavailable，所以只能按顺序试（不绕过网关去戳后端端口）。"""
    ids = gw_model_ids()
    if not ids:
        return []
    default = None
    try:
        default = (req(GATEWAY, "/health", timeout=6) or {}).get("default_model")
    except Exception:
        pass
    ranked = []
    for key in (default, "qwen3-14b", "14b", "qwen3", "20b", "7b"):
        if not key:
            continue
        for i in ids:
            if key.lower() in i.lower() and i not in ranked:
                ranked.append(i)
    ranked += [i for i in ids if i not in ranked]
    return ranked


def gw_pick(prefer="14b"):
    c = gw_candidates()
    if not c:
        log("· 网关在线但 /v1/models 空，提交时不带 model 字段")
        return None
    return c[0]


def llm_chat(system, user, max_tokens=3000, temp=0.3, seed=20261012, wait=900):
    """经通道3 网关调用。两种 503 要分开处理（都是实测到的）：
       · `Loading model`      → 后端在装权重，等；
       · `backend_unavailable`→ 那个后端没起，换下一个候选模型。"""
    cands = gw_candidates()
    payload = {"messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
               "temperature": temp, "max_tokens": max_tokens, "seed": seed}
    t0, told, tried = time.time(), 0, []
    for mid in (cands or [None]):
        if mid:
            payload["model"] = mid
        while True:
            try:
                d = req(GATEWAY, "/v1/chat/completions", "POST", payload, timeout=1500)
                ch = (d.get("choices") or [{}])[0]
                txt = (ch.get("message") or {}).get("content") or ch.get("text") or ""
                if not txt.strip():
                    raise RuntimeError("网关返回空 content：%s" % json.dumps(d)[:240])
                if tried:
                    log("· 用 %s 写稿（前面这些没在服：%s）" % (mid, ", ".join(tried)))
                return txt
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                if e.code == 503 and "Loading model" in body and time.time() - t0 < wait:
                    if time.time() - told >= 60:
                        log("· %s 在加载权重（网关 503），已等 %ds…" % (mid, round(time.time() - t0)))
                        told = time.time()
                    time.sleep(15)
                    continue
                if e.code == 503 and "backend_unavailable" in body:
                    tried.append(str(mid))
                    log("· 后端 %s 没在服，换下一个候选" % mid)
                    break
                raise RuntimeError("网关 %s：%s" % (e.code, body[:200]))
    raise RuntimeError("网关在听，但所有候选后端都没在服（试过 %s）。"
                       "起后端：py D:\\AIWorkflow\\tools\\agent_engine.py up" % ", ".join(tried))


def quote_keys(t):
    """小模型常把键名的双引号丢了。按**整行**匹配才安全——别对全文做正则，会啃掉正文里的冒号。"""
    out = []
    for ln in t.split("\n"):
        m = re.match(r'^(\s*)([A-Za-z_][A-Za-z0-9_]{0,24})(\s*):(.*)$', ln)
        out.append(('%s"%s":%s' % (m.group(1), m.group(2), m.group(4))) if m else ln)
    return "\n".join(out)


def extract_json(text):
    """取第一个花括号平衡块——实测小模型会多吐一个 '}'，平衡匹配天然把它甩在外面。"""
    t = text
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1)
    i = t.find("{")
    if i < 0:
        raise ValueError("模型没吐 JSON：%s" % text[:180])
    depth, ins, esc, end = 0, False, False, -1
    for j in range(i, len(t)):
        c = t[j]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
        elif c == '"':
            ins = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j
                break
    if end < 0:
        raise ValueError("JSON 括号不平衡（多半是被 max_tokens 截断了）")
    cand = t[i:end + 1]
    for attempt in (cand, quote_keys(cand), re.sub(r",\s*([}\]])", r"\1", cand),
                    re.sub(r",\s*([}\]])", r"\1", quote_keys(cand))):
        try:
            return json.loads(attempt)
        except ValueError:
            continue
    raise ValueError("JSON 四种修法都没救通")


# --------------------------------------------------------------- 写稿（本机 LLM）
BRIEF = """你是分镜导演兼提示词装配工。把用户的一句话拆成镜头表，只输出一个**紧凑的** JSON 对象（不要缩进换行、不要注释、不要任何解释文字）。

结构（键名逐字照用）：
{"title":str,"kind":"fight|motion|scenery","style_en":str,"env_en":str,"scene_lock_cn":str,
 "entities":[{"name":"A","cn":str,"outfit_en":str,"outfit_cn":str,"weapon_en":str,"weapon_form_cn":str}],
 "axis_en":str,
 "shots":[{"id":"S01","len":124,"framing":"wide|medium|close-up","camera_en":str,
           "beats_en":[str,str,str],"end_en":str,"sound_en":str,"img_cn":str,
           "role_cn":str,"turn_cn":str,"end_visible_cn":str}]}

镜头写法（本机 H3 实测结论；违反就会变慢或像跳舞）：
1. 一镜只走**一股力**：一个单方向的步进/横扫/推离。不要招式列表。
2. 一次接触事件 + 一段位移。beats_en 只给 2–3 个英文短句，每句一个身体动作。
3. end_en 把收势几何写死：结束时谁在画面哪侧、什么姿态、兵器高位还是低位、留下什么可见损伤。
4. 剧烈镜 2–3 拍封顶，任何镜不超过 4 拍。
5. beats_en 里至少一处含同拍完成词：in the same motion / at once / on the same beat / in one motion。
6. camera_en 从官方类型里选**一个**再补幅度与速度：Zoom In/Out, Push In, Pull Out,
   Pan Left/Right, Tilt Up/Down, Truck Left/Right, Pedestal Up/Down, Arc Shot, Tracking Shot,
   Static Shot, Shake Slightly/Strongly, POV。并写明跟着哪股力，例：
   "Tracking Shot at fast speed, following the shove along the roof"。
7. 正文只能正向描述。H3 没有负面通道，写"不要/没有"等于给它点名那个概念。
   这些子串一个都不许出现（不分大小写）：no / not / none / never / without / avoid。
   另：不要自己写 UNIQUENESS LOCK／SPATIAL ANCHOR／ENVIRONMENT 这三个标签——装配层会加。
7b. env_en 用一句英文写清可见环境与光的方向与它在表面上留下什么（不带灯的名字）。
    sound_en 只列**贯穿全片**的名词性声音（风、脚步、金属撞击、布料撕裂、短促呼吸），不要写说话动词；
    只与某一镜同步的声音事件（例如某块屏幕亮起的电子音、一句话之后的观众笑声）要写进该镜的
    beats_en，不要放进 sound_en。
8. 两个以上实体时 axis_en 逐字锁住"谁在画面左或右、谁背对镜头、谁正面朝向镜头、隔多远"，
   并写明视线落在对方身上而不是镜头。所有镜共用同一句 axis_en，不许某镜换侧。
9. 画幅固定 16:9 横屏。每镜 len=124（≈5.17 秒）；要更长就加镜，别拉长单镜拍数。
10b. outfit_cn 用中文写剪裁＋材质＋颜色三层（本地生图吃中文），outfit_en 用英文同义写一遍。
10. weapon_en 写数量＋形态的英文（"single-edge tang dao with a round guard"），不要写中文；
    角色空手就留空字符串 ""，别写 none／no weapon 这类词（装配层会把它带进正文而被闸拦掉）。
    所有 *_en 字段必须是英文。
11. img_cn 是本地生图（Z-Image）用的中文首帧句：
    · 器物只写名字会被画成玩具，必须补形态（刃长、护手、柄）；
    · 人数或物件计数不超过 3，超了改成描述布局；
    · 光源只写方向和它在表面留下什么，不写灯的名字；
    · 不写"禁止/不要/没有"，Z-Image 同样没有负面通道。
12. scene_lock_cn 只有一句话，只锁方位与既有物件（例：栏杆在画面左、悬浮车在右上），
    各镜逐字复用；img_cn 里别再重复描写场景，否则和它打架。
13. kind=fight 时 role_cn/turn_cn/end_visible_cn 是分镜三必填（本场作用／优势易手点／
    终结如何被看见），必须写成看得见的几何或姿态，别写"他输了"这种结论。
14. 本工具当前不出对白镜：beats_en 里别写 says／replies／shouts 这类说话结构。
    要说话只写"短促呼吸""闷哼"这类非语言人声。"""


def normalize(st, say, shots):
    lab = re.compile(r"^\s*(UNIQUENESS\s+LOCK|SPATIAL\s+ANCHOR|ENVIRONMENT)\s*[:：]\s*", re.I)
    clean = lambda x: lab.sub("", (x or u"").strip())
    st["title"] = st.get("title") or say[:24]
    st["kind"] = st.get("kind") or "fight"
    st["style_en"] = clean(st.get("style_en")) or "Photorealistic cinematic shot, fine film grain"
    st["env_en"] = clean(st.get("env_en"))
    st["scene_lock_cn"] = st.get("scene_lock_cn") or say
    st["axis_en"] = clean(st.get("axis_en"))
    if not st.get("entities"):
        st["entities"] = [{"name": "A", "cn": say[:12], "outfit_en": "dark fitted combat gear",
                           "weapon_en": "single-edge saber", "weapon_form_cn": ""}]
    for e in st["entities"]:
        e.setdefault("name", "A")
        e.setdefault("cn", e["name"])
        e.setdefault("outfit_en", "")
        e.setdefault("outfit_cn", "")
        e.setdefault("weapon_en", "")
        e.setdefault("weapon_form_cn", "")
    ss = st.get("shots") or []
    if not ss:
        raise ValueError("shots 为空")
    for i, s in enumerate(ss):
        s["id"] = (s.get("id") or "S%02d" % (i + 1)).upper()
        s["len"] = int(s.get("len") or TP_LEN)
        s.setdefault("framing", "medium")
        s["beats_en"] = [clean(b) for b in (s.get("beats_en") or []) if clean(b)][:4]
        if len(s["beats_en"]) < 2:
            raise ValueError("%s beats 不足 2 句" % s["id"])
        s["end_en"] = clean(s.get("end_en")) or s["beats_en"][-1]
        s["sound_en"] = clean(s.get("sound_en")) or "Wind and footsteps"
        s["camera_en"] = clean(s.get("camera_en")) or "Tracking Shot at fast speed"
        s.setdefault("img_cn", say)
        s["camera_en"] = cam_norm(s["camera_en"])
        for k in ("role_cn", "turn_cn", "end_visible_cn"):
            s.setdefault(k, "")
    st["shots"] = ss[:max(1, shots)]
    return st


DRIFT_KEYS = ["机甲", "机器人", "雪", "夜", "楼顶", "天台", "屋顶", "唐刀", "剑", "女", "男",
              "巷", "雨", "雾", "林", "寺", "车", "猫", "虎"]


def drift(st, say):
    """一句话里的硬要素在稿子（含中文场景句）里彻底消失 ⇒ 算漂移，进回炉问题。"""
    blob = json.dumps(st, ensure_ascii=False)
    miss = [k for k in DRIFT_KEYS if k in (say or "") and k not in blob]
    return ["剧情要素在稿子里丢了：%s（请保留）" % "、".join(miss)] if miss else []


def lint(st, say=None):
    """闸前先自查：与 check_h3_dialogue.py 的 D7/D8/D9 同尺，问题在出稿阶段就说出来。"""
    bad = []
    if say:
        bad += drift(st, say)
        for k in ["机甲", "机器人", "悬浮车", "兽", "士兵", "猫", "虎", "鹤"]:
            in_ents = any(k in (e.get("cn", "") + (e.get("outfit_cn") or "") +
                                (e.get("weapon_form_cn") or "")) for e in st["entities"])
            if k in say and not in_ents:
                bad.append("一句话里的「%s」没进 entities 表 ⇒ 人数与器物锁会漏掉它，请为它单列一个实体" % k)
    if not (st.get("env_en") or "").strip():
        bad.append("缺 env_en（D7 的 ENVIRONMENT 句没有料）")
    if len(st["entities"]) >= 2 and not (st.get("axis_en") or "").strip():
        bad.append("多实体但 axis_en 为空（R4-19：空间关系与视线必须锁）")
    m = NEG_RE.search(st.get("style_en", "") + " " + st.get("env_en", "") + " " + st.get("axis_en", ""))
    if m:
        bad.append("style_en/env_en/axis_en 含禁用词 %r（D9）" % m.group(0))
    if CJK_RE.search(st.get("style_en", "") + " " + st.get("env_en", "") + " " + st.get("axis_en", "")):
        bad.append("style/env/axis 的英文字段里混进中文（H3R23 error）")
    for e in st["entities"]:
        m = NEG_RE.search((e.get("weapon_en") or "") + " " + (e.get("outfit_en") or ""))
        if m:
            bad.append("%s 的实体字段含禁用词 %r（会被装配进正文）" % (e.get("name", "?"), m.group(0)))
    for s in st["shots"]:
        body = " ".join(s["beats_en"]) + " " + s["end_en"] + " " + s["sound_en"]
        m = NEG_RE.search(body)
        if m:
            bad.append("%s 正文含禁用词 %r（D9：H3 无负面通道，禁令即在点名）" % (s["id"], m.group(0)))
        g = GEAR_RE.search(s["camera_en"])
        if g:
            bad.append("%s 运镜写了器材名 %r（R2-05 禁器材词）" % (s["id"], g.group(0)))
        if len(s["beats_en"]) > 4:
            bad.append("%s 拍数 %d 超容量" % (s["id"], len(s["beats_en"])))
        if not cam_ok(s["camera_en"]):
            bad.append("%s 运镜 %r 不在官方 12 行里" % (s["id"], s["camera_en"]))
        if st["kind"] == "fight" and not (s.get("role_cn") and s.get("turn_cn")
                                          and s.get("end_visible_cn")):
            bad.append("%s 分镜三必填没填齐（R3c：缺任一＝分镜未完成）" % s["id"])
        if SPEECHV_RE.search(s["sound_en"]):
            bad.append("%s sound_en 含说话动词（D2 会判台词漏进 soundscape）" % s["id"])
    return bad


def llm_story(say, shots):
    user = ("一句话：%s\n要求：%d 个镜头，节奏为 建立 → 接触 → 变势 → 收势。"
            "每镜 len=124。只输出紧凑 JSON。" % (say, shots))
    st, best, problems = None, None, ["（还没出过稿）"]
    for rnd in range(3):
        msg = user if rnd == 0 else (
            "上一稿有这些问题，逐条改正后**只输出改正后的完整 JSON**（键名带双引号、无注释、"
            "无多余逗号、不要缩进换行）：\n%s\n原稿：\n%s"
            % ("\n".join(problems), json.dumps(st, ensure_ascii=False) if st else "（没解析出来）"))
        out = llm_chat(BRIEF, msg, max_tokens=3000, temp=0.3 + 0.2 * rnd)
        try:
            st = normalize(extract_json(out), say, shots)
        except Exception as e:
            log("· 第 %d 轮 JSON 没读通（%s）" % (rnd + 1, str(e)[:70]))
            problems = ["JSON 语法不合法：%s" % str(e)[:80]]
            continue
        problems = lint(st, say)
        if len(st["shots"]) < shots:
            problems.append("镜头数只有 %d，要求 %d：保留已有镜头的设定，补齐到 %d 镜"
                            % (len(st["shots"]), shots, shots))
        if best is None or len(st["shots"]) > len(best["shots"]):
            best = st
        if not problems:
            return st
        log("· 第 %d 轮自查命中 %d 条：%s" % (rnd + 1, len(problems), "; ".join(problems[:2])))
    if best is None:
        raise RuntimeError("本地 LLM 三轮都没给出可用 JSON")
    if len(best["shots"]) < shots:
        log("⚠ 模型只给到 %d/%d 镜。要么重跑一次，要么手改 story.json 后 --stage render，"
            "要么 --llm off 让规则兜底补齐" % (len(best["shots"]), shots))
    best["_lint_left"] = problems
    return best


def mech_fix(st):
    """机械兜底：削掉禁用词、削掉 *_en 里的中文、补上缺的锁句。
    削词可能削坏语法——所以 lint 的问题优先交给 LLM 回炉，这里只保证结构能过闸。"""
    def scrub(x):
        x = NEG_RE.sub(" ", x or "")
        x = CJK_RE.sub(" ", x)
        return re.sub(r"\s+", " ", x).strip(" ,.;：:")
    st["style_en"] = scrub(st.get("style_en")) or "Photorealistic cinematic shot, fine film grain"
    st["env_en"] = scrub(st.get("env_en")) or \
        "Cold night air with snow drifting across the open roof, hard light raking from the upper " \
        "left and leaving bright edges on the wet tiles"
    for e in st["entities"]:
        e["weapon_en"] = "" if NULLW.match(scrub(e.get("weapon_en")) or "x") else scrub(e.get("weapon_en"))
        e["outfit_en"] = scrub(e.get("outfit_en"))
    if len(st["entities"]) >= 2 and not scrub(st.get("axis_en")):
        st["axis_en"] = ("A stays left of centre facing right, B stays right of centre facing A, "
                         "one and a half arm lengths apart, her gaze locked on its chest light")
    else:
        st["axis_en"] = scrub(st.get("axis_en"))
    for s in st["shots"]:
        s["beats_en"] = [b for b in (scrub(x) for x in s["beats_en"][:4]) if b] or \
                        ["she holds the line steady"]
        s["end_en"] = scrub(s["end_en"]) or "they hold still facing each other"
        s["camera_en"] = scrub(s["camera_en"])
        if GEAR_RE.search(s["camera_en"]) or not cam_ok(s["camera_en"]):
            s["camera_en"] = "Tracking Shot at fast speed, following the main action"
        s["sound_en"] = scrub(s["sound_en"]) or "Wind, boots, one hard metal clash"
        s["sound_en"] = SPEECHV_RE.sub(" ", s["sound_en"]).strip() or "Wind and footsteps"
    return st


# --------------------------------------------------------------- 写稿（规则兜底）
def rules_story(say, shots, _len=TP_LEN):
    """--llm off：确定性兜底。只保证出**过闸**的稿，不保证戏好——这点别当创作用。"""
    fight = any(k in say for k in ["打", "斗", "战", "砍", "劈", "击", "冲", "追", "搏",
                                   "单挑", "对峙", "兵刃", "交手", "厮杀"])
    dao = any(k in say for k in ["刀", "剑"])
    mech = ("mech" in say.lower()) or ("机甲" in say)
    ents = [{"name": "A", "cn": "她", "outfit_en": "dark fitted combat gear",
             "outfit_cn": "深色修身武服，粗织麻面哑光，袖口与腰封磨白，束腕皮绳",
             "weapon_en": "single-edge tang dao with a round guard" if dao else "short steel staff",
             "weapon_form_cn": "刀身笔直单刃、圆盘护手、柄缠深色绳" if dao else "一根短钢杆，两端包铜"}]
    if mech:
        ents.append({"name": "B", "cn": "机甲",
                     "outfit_en": "layered armour plates with a cold-white chest light strip",
                     "outfit_cn": "两米半人高重装机甲，层叠哑光装甲板，胸口一道冷白光带横贯",
                     "weapon_en": "", "weapon_form_cn": "右肩多管转轮机炮，胸口横条冷白光带"})
    axis = ("she stays in the right foreground with her back to camera and the mech stays in the "
            "left middle distance facing the camera, about fifteen metres of open roof between "
            "them, her gaze locked on its chest light") if mech else \
           ("A stays left of centre facing right, B stays right of centre facing A, "
            "one and a half arm lengths apart, eyes locked on each other")
    A = ents[0]["name"]
    beats = [
        ["%s steps in and drives one diagonal cut downward" % A,
         "steel clashes once and dust bursts from their boots",
         "In the same motion %s presses along the guard and shoves" % A],
        ["%s slides back half a metre on the wet tiles" % A,
         "At once she turns into the slide and closes the gap again",
         "In the same motion the cut lands and the opponent's arm knocks wide"],
        ["%s drops low under the swinging arm and drives one shoulder into the plate" % A,
         "The impact rings once and she rebounds upright",
         "At once she sets the blade against the chest light and holds"],
        ["They brake facing each other across the drifting steam",
         "In the same motion she recovers her stance",
         "the opponent sinks to one knee and the blade stays high"],
    ]
    cams = ["Push In at slow speed, closing on the two figures",
            "Tracking Shot at fast speed, following the shove along the roof",
            "Tracking Shot at fast speed, following the shoulder impact",
            "Static Shot, holding the final geometry"]
    ss = []
    for i in range(min(shots, 4)):
        ss.append({"id": "S%02d" % (i + 1), "len": _len,
                   "framing": "wide" if i == 0 else "medium",
                   "camera_en": cams[i], "beats_en": beats[i],
                   "end_en": "They hold still facing each other, %s on the right with the blade high "
                             "and a torn sleeve, the opponent sunk to one knee on the left" % A,
                   "sound_en": "Cold wind, boots on wet tiles, one hard metal clash, cloth tear",
                   "img_cn": "横屏 16:9：%s；她背对镜头在画面右下近景，刀斜举在右手" % say,
                   "role_cn": "为下一镜的反击攒势" if i else "建立敌我距离与出口",
                   "turn_cn": "本镜中段兵刃被格开，主动权暂时到对方" if i else "开场即劣势",
                   "end_visible_cn": "末帧：她刀高位、对方单膝落地"})
    return normalize({"title": say[:24], "kind": "fight" if fight else "motion",
                      "style_en": "Photorealistic cinematic shot, falling snow, "
                                  "warm reactor glow, fine film grain",
                      "env_en": "Open rooftop at night under drifting snow, wet tiles reflecting "
                                "a cold horizontal light band, a low railing running along the left "
                                "side and a hovering gunship parked at the upper right",
                      "scene_lock_cn": "栏杆在画面左，悬浮车停在右上方，湿滑屋面反着冷白光",
                      "axis_en": axis, "entities": ents, "shots": ss}, say, shots)


# --------------------------------------------------------------- 装配（决定性，不看模型心情）
def cam_norm(cam):
    """官方档位只有幅度 small/large 与速度 slow/fast；medium/moderate 这类中档按规范整段省掉。
    顺带把 Roll CW/CCW 简写换成官方全称（base-en §4.3）。"""
    for k, v in CAM_CANON.items():
        if k in (cam or "").lower():
            cam = re.sub(re.escape(k), v, cam, flags=re.I)
    c = re.sub(r"\s*(?:at\s+)?(?:moderate|medium|normal|steady)\s+speed\s*", " ", cam or "", flags=re.I)
    c = re.sub(r"\s*with\s+(?:moderate|medium|normal)\s+amplitude\s*", " ", c, flags=re.I)
    return re.sub(r"\s+,", ",", re.sub(r"\s+", " ", c)).strip(" .,")


def cam_ok(cam):
    """认两种写法：官方类型名（Tracking Shot / Roll Clockwise…）与官方例句里的屈折自然句
    （the camera tracks… / pans right…）。词表与正则都取自 h3_official_spec，别在这儿另抄一份。"""
    c = cam or ""
    low = c.lower()
    return any(t.lower() in low for t in CAM_TYPES) or bool(SPEC.CAMERA_RE.search(c))


def strip_count(w):
    return re.sub(r"^(one|two|three|a|an)\s+", "", (w or "").strip(), flags=re.I)


NULLW = re.compile(r"^(none|nothing|n/?a|null|empty|no weapon|bare[- ]?handed|unarmed"
                   u"|无|没有|空手|徒手|赤手)$", re.I)


def make_lock(ents):
    # 模型很爱给空手角色写 weapon_en="none"，那会把禁词 none 直接装进正文（实测踩过）
    raw = [(e.get("weapon_en") or "").strip() for e in ents]
    wp = [strip_count(w) for w in raw if w and not NULLW.match(w)]
    n = NUM.get(max(1, len(ents)), "one")
    names = ", ".join((e.get("name") or "?") for e in ents)
    fig = ("Exactly %s figures in the whole clip (%s). " % (n, names)
           if len(ents) > 1 else
           "Exactly one figure in the whole clip (%s). " % names)
    if wp:
        joined = " and exactly one ".join(wp)
        return re.sub(r"\s+", " ",
                      "Exactly one %s across the whole clip; each stays intact and keeps its shape "
                      "throughout this shot. %sAny second copy of the weapon or the figure is "
                      "out of place." % (joined, fig))
    return fig + "Any second copy of a figure is out of place."


def render_h3(st, shot):
    """装配成官方骨架——**填充走 h3_official_spec.fill()**，所以首行、字段名与顺序、
    运镜词表、切镜白名单、时长区间都由官方契约强制，写不出不合规的结构。
    SPATIAL ANCHOR / ENVIRONMENT / UNIQUENESS LOCK 三个标签是房内加严（check_h3_dialogue D7），
    官方没有；由装配层统一加，LLM 不许自己写。"""
    who = " and ".join(("%s in %s" % (e["name"], e["outfit_en"])).strip("; ").strip()
                        for e in st["entities"] if e.get("outfit_en") or e.get("name"))
    axis = (shot.get("axis_en") or st.get("axis_en") or "").strip().rstrip(".")
    if axis and not EYELINE_RE.search(axis):
        axis += ", her gaze fixed on the opponent"
    beats = []
    for b in shot["beats_en"]:
        b = b.strip().rstrip(". ")
        b = (b[0].upper() + b[1:]) if b else b
        beats.append(b + ".")
    if not re.search(INSTANT_RE, " ".join(beats), re.I):
        b = beats[-1]
        beats[-1] = "At once " + b[0].lower() + b[1:]
    text = ["%s hold their ground." % who]
    if shot.get("framing", "").lower().startswith("close"):
        text.append("Visible skin pores, fine stubble and damp hair strands catch the light, "
                    "shallow depth of field, film grain across the frame.")
    text += beats + [shot["end_en"].strip().rstrip(".") + "."]
    cam = shot["camera_en"] if cam_ok(shot["camera_en"]) else \
        "Tracking Shot at fast speed, following the main action"
    try:
        camq = SPEC.parse_camera(cam)      # 拆成官方四元组；类型认不出就抛，不静默产坏句
    except ValueError as e:
        log("· ⚠ 运镜 %r 拆不出官方类型（%s）⇒ 回落到 Tracking Shot" % (cam[:40], e))
        camq = SPEC.parse_camera("Tracking Shot at fast speed, following the main action")
    spec = {
        "mode": "i2va",                                   # 只吃首帧；FL2VA 要换首行与模板，见审计件
        "seconds": round(int(shot.get("len") or TP_LEN) / 24.0, 2),
        "style": st["style_en"],
        "house": {"axis": axis, "env": st["env_en"], "lock": make_lock(st["entities"])},
        "shots": [{"no": 1, "text": re.sub(r"\s+", " ", " ".join(text)).strip(),
                   "camera": camq}],
        "soundscape": shot["sound_en"].strip().rstrip("."),
        "music": "N/A",
    }
    return SPEC.fill(spec, camera_style=CAMERA_STYLE)


def render_img(st, shot):
    bits = [shot["img_cn"], st["scene_lock_cn"]]
    look = "；".join("%s的外观：%s" % (e["cn"], e.get("outfit_cn") or e.get("outfit_en"))
                     for e in st["entities"] if (e.get("outfit_cn") or e.get("outfit_en")))
    forms = "；".join(e["weapon_form_cn"] for e in st["entities"]
                      if (e.get("weapon_form_cn") or "").strip() not in ("", "无", "没有", "/"))
    axis_cn = shot.get("axis_cn") or ""
    bits += [b for b in (look, forms, axis_cn) if b]
    if "16:9" not in (shot["img_cn"] + st["scene_lock_cn"]):
        bits.insert(0, "16:9 横屏")
    bits.append("写实半实拍 CG 质感，细胶片颗粒，硬接触阴影")
    return "。".join(re.sub(r"[.。；;，,]+$", "", b.strip()) for b in bits if b and b.strip()) + "。"


def render_board(st):
    violent = "是" if st["kind"] == "fight" else "否"
    rows = ["| 镜号 | 秒 | 本场作用 | 优势易手点 | 终结如何被看见 | 步数 | 剧烈? |",
            "|---|---|---|---|---|---|---|"]
    for s in st["shots"]:
        rows.append("| %s | %.2f | %s | %s | %s | %d | %s |" %
                    (s["id"], s["len"] / 24.0, s["role_cn"] or "（待填）",
                     s["turn_cn"] or "（待填）", s["end_visible_cn"] or "（待填）",
                     len(s["beats_en"]), violent))
    return "# %s · 分镜（oneshot 生成）\n\n三必填：本场作用 / 优势易手点 / 终结如何被看见\n\n%s\n" % (
        st["title"], "\n".join(rows))


# --------------------------------------------------------------- 闸门
def run_gates(job):
    pf = job / "prompts"
    out, ok = [], True
    for cmd in ([sys.executable, str(GATE_ALL), "--dir", str(pf)],
                [sys.executable, str(GATE_RULE), "--dir", str(pf)]):
        rc, txt = sh(cmd, timeout=600)
        out.append("===== %s (rc=%s) =====\n%s" % (Path(cmd[1]).name, rc, txt))
        ok = ok and rc == 0

    # ---- 官方契约闸（h3_official_spec.validate，进程内跑，好把每镜真实秒数喂进去）
    #      判的是官方硬格式：verbatim 首行 / 三字段名与顺序 / 英文正文 / [Shot 1] 无时码 /
    #      时长 4–15s / 运镜受控词表 / (Sx)+<d> / 声景与配乐写法。
    #      house=True ⇒ 房内 D7 三标签也算硬要求（官方无此标签，但内容官方都要写）。
    mode = load_ledger(job).get("mode", "i2va")
    secs = {}
    sp = job / "story.json"
    if sp.is_file():
        try:
            for s in json.loads(sp.read_text(encoding="utf-8")).get("shots", []):
                secs[str(s.get("id"))] = round(int(s.get("len") or TP_LEN) / 24.0, 2)
        except Exception as e:                                  # 读不动就退回不传秒数（F6 跳过）
            log("· ⚠ story.json 没读出每镜秒数（%s），官方闸这轮不核 4–15s" % e)
    files = sorted(pf.glob("*.txt"))
    rows, bad = [], 0
    for f in files:
        rp = SPEC.validate(f.read_text(encoding="utf-8"), mode=mode,
                           seconds=secs.get(f.stem), house=True)
        e, w = rp.count("error"), rp.count("warn")
        bad += 1 if e else 0
        rows.append("----- %s ｜模式 %s ｜error=%d warn=%d info=%d"
                    % (f.name, mode, e, w, rp.count("info")))
        rows += ["  " + x for x in rp.render() if not x.startswith("INFO")]
    if not files:
        rows.append("🔴 prompts 目录里没有 .txt，没稿可检（不算过）")
        bad = 1
    out.append("===== h3_official_spec 官方契约（实检 %d 份，house=True）=====\n%s\n官方契约：%s"
               % (len(files), "\n".join(rows) or "（无问题）",
                  "全过" if not bad else "%d 份有 error" % bad))
    ok = ok and not bad

    board = job / "分镜.md"
    if board.is_file():
        rc, txt = sh([sys.executable, str(GATE_BOARD), str(board)])
        out.append("===== check_fight_storyboard (rc=%s) =====\n%s" % (rc, txt))
        ok = ok and rc == 0
    (job / "gate_report.txt").write_text("\n".join(out), encoding="utf-8")
    return ok, "\n".join(out)


def load_ledger(job):
    p = job / "job.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def save_ledger(job, led):
    (job / "job.json").write_text(json.dumps(led, ensure_ascii=False, indent=2), encoding="utf-8")


def emit_and_gate(job, st, ledger_extra=None):
    for sub in ("prompts", "prompts_img"):
        (job / sub).mkdir(parents=True, exist_ok=True)
    for s in st["shots"]:
        (job / "prompts" / ("%s.txt" % s["id"])).write_text(render_h3(st, s), encoding="utf-8")
        (job / "prompts_img" / ("%s_cn.txt" % s["id"])).write_text(render_img(st, s), encoding="utf-8")
    (job / "分镜.md").write_text(render_board(st), encoding="utf-8")
    (job / "story.json").write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    ok, rep = run_gates(job)
    log("\n".join(rep.splitlines()[-25:]))
    led = {"job": job.name, "title": st["title"], "shots": [s["id"] for s in st["shots"]],
           "len": st["shots"][0]["len"], "llm": st.get("_source", "?"), "gate_pass": ok,
           "stage": "compile", "frames": {}, "approved": [],
           "mode": "i2va", "camera_style": CAMERA_STYLE,
           "spec": str(GATE_SPEC.name)}          # 装配格式的真源，回头对账用
    led.update(ledger_extra or {})
    if (job / "job.json").is_file():                       # 保留已出的帧与放行记录
        old = json.loads((job / "job.json").read_text(encoding="utf-8"))
        led["frames"] = old.get("frames", led["frames"])
        if old.get("gate_pass") is False:
            led["approved"] = []
        else:
            led["approved"] = old.get("approved", [])
    save_ledger(job, led)
    log("【稿】%s" % job)
    log("· 提示词 %d 份｜闸门 %s" % (len(st["shots"]), "全过" if ok else "🔴 没过"))
    if not ok:
        log("🔴 闸门没过 ⇒ 不出图不出片。逐条看 gate_report.txt（放行记录已作废）")
        return 1
    log("下一步：py oneshot.py --job %s --stage frames" % job.name)
    return 0


def render_stage(a):
    """改完 story.json（或 prompts_img）后重装配＋过闸，不重新写稿。"""
    job = JOBROOT / a.job
    st = json.loads((job / "story.json").read_text(encoding="utf-8"))
    say = load_ledger(job).get("say", "")
    problems = lint(st, say)
    if problems:
        log("· 自查命中 %d 条：%s" % (len(problems), "; ".join(problems[:3])))
        st = mech_fix(st)
    return emit_and_gate(job, st)


# --------------------------------------------------------------- 阶段 1：出稿
def compile_stage(a):
    job = JOBROOT / a.job
    for sub in ("prompts", "prompts_img", "frames", "video", "review"):
        (job / sub).mkdir(parents=True, exist_ok=True)
    st = None
    if a.llm != "off":
        try:
            ids = gw_model_ids()
            log("· 通道3 网关在听（8080），模型清单 %s ⇒ 写稿用 %s" % (ids or "（空）", gw_pick()))
            st = llm_story(a.say, a.shots)
        except Exception as e:
            log("🔴 通道3 这条路不通：%s ⇒ 改走规则兜底（纯 CPU）" % str(e)[:200])
            st = None
    if st is None:
        st = rules_story(a.say, a.shots)
    st["_source"] = a.llm if a.llm != "off" else "rules"
    problems = lint(st, a.say)
    if problems:
        st = mech_fix(st)
        left = lint(st, a.say)
        if left:
            log("· 机械修正后仍需人看（闸不卡这类，是稿面漂移/措辞）：%s" % "; ".join(left[:3]))

    return emit_and_gate(job, st, {"say": a.say})


# --------------------------------------------------------------- 阶段 2：本地出首帧
def comfy_up():
    try:
        req(COMFY, "/system_stats", timeout=5)
        return True
    except Exception:
        return False


def comfy_wait(pid, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        try:
            h = req(COMFY, "/history/%s" % pid, timeout=60)
        except Exception:
            continue
        if pid not in h:
            continue
        rec = h[pid]
        stt = rec.get("status") or {}
        if (stt.get("status_str") or "") == "error":
            for m in stt.get("messages") or []:
                if isinstance(m, list) and m and m[0] == "execution_error":
                    e = m[1]
                    raise RuntimeError("ComfyUI node %s(%s)：%s"
                                       % (e.get("node_id"), e.get("node_type"),
                                          str(e.get("exception_message"))[:220]))
            raise RuntimeError("ComfyUI 执行失败（查 /system_stats 的 vram_free）")
        got = []
        for nid in (rec.get("outputs") or {}):
            for im in (rec["outputs"][nid].get("images") or []):
                sub = im.get("subfolder") or ""
                got.append(COMFY_OUT / sub / im["filename"])
        if got:
            return got
        raise RuntimeError("执行成功但无产物")
    raise RuntimeError("出图超时 %ds" % timeout)


def crop_to(src, dst, w=FRAME_W, h=FRAME_H):
    """先裁到 w:h 再缩——直接 resize 会竖向拉伸 1.6%（实测踩过）。"""
    im = Image.open(str(src)).convert("RGB")
    iw, ih = im.size
    target = w / float(h)
    if iw / float(ih) > target:
        nw = int(ih * target)
        x0 = (iw - nw) // 2
        im = im.crop((x0, 0, x0 + nw, ih))
    else:
        nh = int(iw / target)
        y0 = (ih - nh) // 2
        im = im.crop((0, y0, iw, y0 + nh))
    im.resize((w, h), Image.LANCZOS).save(str(dst))


def build_wf(tpl, rep):
    wf = json.loads(json.dumps(tpl))
    for n in wf.values():
        for k, v in list(n["inputs"].items()):
            if isinstance(v, str) and v in rep:
                n["inputs"][k] = rep[v]
    return wf


def submit(wf, timeout=900):
    pid = req(COMFY, "/prompt", "POST", {"prompt": wf})["prompt_id"]
    return comfy_wait(pid, timeout=timeout)


def put_input(img_path, name):
    """LoadImage 只认 ComfyUI/input 里的文件名——顺手把非 ASCII 路径问题挡在这一步。"""
    H3_INPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(img_path), str(H3_INPUT / name))
    return name


def frames_stage(a):
    job = JOBROOT / a.job
    if not (job / "story.json").is_file():
        log("🔴 没有稿，先跑 --stage compile --say ...")
        return 1
    st = json.loads((job / "story.json").read_text(encoding="utf-8"))
    if not comfy_up():
        log(CH4_HINT)
        return 1
    stats = req(COMFY, "/system_stats")
    vf = [dv.get("vram_free") for dv in stats.get("devices", []) if dv.get("vram_free")]
    log("· 显存空闲 %s GB（判据看这里，别看 nvidia-smi）"
        % (round(max(vf) / 1024.0 ** 3, 2) if vf else "?"))
    try:
        req(COMFY, "/free", "POST", {"unload_models": True, "free_memory": True}, timeout=30)
    except Exception:
        pass
    tpl = json.loads(COMFY_JSON.read_text(encoding="utf-8"))
    tpl_i2i = json.loads(COMFY_I2I.read_text(encoding="utf-8")) if (a.anchor or a.chain) else None
    if tpl_i2i is not None:
        log("· 造型锚：%s（i2i denoise=%s steps=%s，这两个默认值本脚本没标定过，按需要拧）"
            % (a.anchor or "上一镜首帧（链式）", a.denoise, a.steps))
    anchor_name = put_input(a.anchor, "oneshot_%s_anchor.png" % a.job) if a.anchor else None
    led = load_ledger(job)
    prev_name = None
    for s in st["shots"]:
        prompt = (job / "prompts_img" / ("%s_cn.txt" % s["id"])).read_text(encoding="utf-8").strip()
        for k in range(min(a.seeds, 4)):
            tag = string.ascii_lowercase[k]
            seed = a.seed + k
            prefix = "%s_%s_%s" % (a.job, s["id"], tag)
            ctrl = anchor_name or prev_name
            t0 = time.time()
            if tpl_i2i is not None and ctrl:
                rep = {"__PROMPT__": prompt, "__CTRL_IMAGE__": ctrl, "__DENOISE__": a.denoise,
                       "__STEPS__": a.steps, "__SEED__": seed, "__PREFIX__": prefix}
                files = submit(build_wf(tpl_i2i, rep))
                mode = "i2i←" + ctrl
            else:
                rep = {"__PROMPT__": prompt, "__W__": FRAME_W, "__H__": FRAME_H,
                       "__SEED__": seed, "__PREFIX__": prefix}
                files = submit(build_wf(tpl, rep))
                mode = "text"
            dst = job / "frames" / ("%s_%s.png" % (s["id"], tag))
            crop_to(files[0], dst)
            if a.chain:
                prev_name = put_input(dst, "oneshot_%s.png" % prefix)
            led.setdefault("frames", {})["%s_%s" % (s["id"], tag)] = {
                "src": str(files[0]), "png": str(dst), "seed": seed, "mode": mode,
                "secs": round(time.time() - t0, 1), "prompt_cn": prompt}
            led["stage"] = "frames"
            log("· %s 首帧 [%s]（%.1fs）%s" % (s["id"], mode, time.time() - t0, dst))
    save_ledger(job, led)
    contact_sheet(job, st)
    review_md(job, st)
    log("\n【目审闸】首帧已出，渲染不会自动开始。")
    log("  看：%s" % (job / "review" / "contact_sheet.png"))
    log("  审：%s" % (job / "review" / "REVIEW.md"))
    log("通过后再放行：py oneshot.py --job %s --stage video --approve all" % a.job)
    return 0


def contact_sheet(job, st):
    (job / "review").mkdir(exist_ok=True)
    ids = [s["id"] for s in st["shots"]]
    cols, tw, th = 2, 672, 384
    rows = (len(ids) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 30)), (14, 14, 16))
    dr = ImageDraw.Draw(sheet)
    for i, sid in enumerate(ids):
        cand = sorted((job / "frames").glob("%s_*.png" % sid))
        if not cand:
            continue
        im = Image.open(str(cand[0])).convert("RGB").resize((tw, th), Image.LANCZOS)
        x, y = (i % cols) * tw, (i // cols) * (th + 30)
        sheet.paste(im, (x, y))
        dr.text((x + 8, y + th + 6), "%s ｜ %s" % (cand[0].name, st["shots"][i]["camera_en"][:60]),
                fill=(225, 225, 225))
    sheet.save(job / "review" / "contact_sheet.png")


def review_md(job, st):
    ln = ["# %s · 关键帧目审单\n" % st["title"],
          "看四件事：**站位对不对（谁左谁右）、兵器在不在该在的手上、视线是否指向对手、"
          "背景与本镜动作是否矛盾**。指错就删掉那张 png 重跑 frames，别放行。\n"]
    for s in st["shots"]:
        ln.append("## %s（%.2fs｜%s）" % (s["id"], s["len"] / 24.0, s["framing"]))
        for p in sorted((job / "frames").glob("%s_*.png" % s["id"])):
            ln.append("- 首帧：%s" % p)
        ln.append("- 出词（中文）：%s" % (job / "prompts_img" / ("%s_cn.txt" % s["id"])))
        ln.append("- 动作：%s" % " / ".join(s["beats_en"]))
        ln.append("- 收几何：%s" % s["end_en"])
        ln.append("- 运镜：%s" % s["camera_en"])
        ln.append("- 三必填：%s ｜ %s ｜ %s\n" % (s["role_cn"], s["turn_cn"], s["end_visible_cn"]))
    ln.append("---\n放行：`py oneshot.py --job %s --stage video --approve all`" % job.name)
    ln.append("只放某几镜：`--approve S01,S03`。不认某镜：重跑 frames 或直接改 prompts_img 后重出。")
    (job / "review" / "REVIEW.md").write_text("\n".join(ln), encoding="utf-8")


# --------------------------------------------------------------- 阶段 3：D 档出片
def video_stage(a):
    job = JOBROOT / a.job
    st = json.loads((job / "story.json").read_text(encoding="utf-8"))
    led = load_ledger(job)
    if not a.approve:
        log("🔴 目审闸：关键帧必须人审通过才允许渲染。")
        log("   审这个：%s" % (job / "review" / "REVIEW.md"))
        log("   通过后再来：py oneshot.py --job %s --stage video --approve all" % a.job)
        return 2
    order = [s["id"] for s in st["shots"]]
    want = order if a.approve.strip().lower() == "all" else \
           [x.strip().upper() for x in a.approve.split(",") if x.strip()]
    bad = [w for w in want if w not in order]
    if bad:
        log("🔴 --approve 里有不认识的镜号：%s（可选 %s）" % (",".join(bad), ",".join(order)))
        return 1
    if st.get("kind") == "fight":
        holes = [s["id"] for s in st["shots"] if s["id"] in want
                 and not (s.get("role_cn") and s.get("turn_cn") and s.get("end_visible_cn"))]
        if holes and not a.dry_run:
            log("🔴 R3c：这些镜的三必填（本场作用／优势易手点／终结如何被看见）没填齐：%s"
                " ⇒ 分镜未完成，不得开渲。补 story.json 后跑 --stage render" % ",".join(holes))
            return 1
    ok, rep = run_gates(job)
    if not ok:
        log("🔴 闸门现在没过（稿子被改过？）：\n%s" % "\n".join(rep.splitlines()[-20:]))
        return 1
    led["approved"] = ([] if a.dry_run else want) or led.get("approved", [])
    led["stage"] = "video"
    if not a.dry_run:
        save_ledger(job, led)
        if not comfy_up():
            log(CH4_HINT)
            return 1
    for sid in want:
        shot = next(s for s in st["shots"] if s["id"] == sid)
        fr = sorted((job / "frames").glob("%s_*.png" % sid))
        if not fr:
            if not a.dry_run:
                log("🔴 %s 没有首帧，先跑 --stage frames" % sid)
                return 1
            fr = [Path("<%s_首帧.png>" % sid)]
        if len(fr) > 1:
            log("· %s 有 %d 张候选，用 %s（要换别的：把不用的那张挪走再跑）" % (sid, len(fr), fr[0].name))
        cmd = [sys.executable, str(H3_RUNNER), "--image", str(fr[0]),
               "--prompt-file", str(job / "prompts" / ("%s.txt" % sid)),
               "--w", str(a.tp_w), "--h", str(a.tp_h), "--len", str(shot["len"]),
               "--seed", str(a.seed), "--out", "%s_%s" % (a.job, sid),
               "--strength", str(a.strength)]
        log("$ " + " ".join(cmd))
        if a.dry_run:
            continue
        t0 = time.time()
        rc, txt = sh(cmd, timeout=2400)
        log(txt[-700:])
        m = re.findall(r"['\"]([^'\"]+\.mp4)['\"]", txt)
        dst = job / "video" / ("%s.mp4" % sid)
        if m and Path(m[-1]).is_file():
            shutil.copy2(m[-1], dst)
            led.setdefault("videos", {})[sid] = {"mp4": str(dst), "secs": round(time.time() - t0, 1),
                                                 "seed": a.seed, "tp": [a.tp_w, a.tp_h, shot["len"]],
                                                 "cmd": " ".join(cmd)}
            log("✔ %s 成片 %s（%.1f 分钟）" % (sid, dst, (time.time() - t0) / 60.0))
        else:
            (job / "video" / ("%s.log" % sid)).write_text(txt, encoding="utf-8")
            log("🔴 %s 没拿到 mp4，日志：%s" % (sid, job / "video" / ("%s.log" % sid)))
            save_ledger(job, led)
            return 1
        save_ledger(job, led)
    log("\n拼 16:9 母版：py oneshot.py --job %s --stage stitch" % a.job)
    return 0


def stitch_stage(a):
    job = JOBROOT / a.job
    st = json.loads((job / "story.json").read_text(encoding="utf-8"))
    vids = [job / "video" / ("%s.mp4" % s["id"]) for s in st["shots"]]
    vids = [v for v in vids if v.is_file()]
    if not vids:
        log("🔴 没成片可拼")
        return 1
    if not FFMPEG.is_file():
        log("🔴 找不到 %s" % FFMPEG)
        return 1
    lst = job / "video" / "concat.txt"
    lst.write_text("\n".join("file '%s'" % str(v).replace("\\", "/") for v in vids), encoding="ascii")
    raw = job / "master_raw.mp4"
    rc, txt = sh([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                  "-c", "copy", str(raw)], timeout=600)
    src = raw if raw.is_file() else vids[0]
    if src is vids[0]:
        log("· concat -c copy 没成（%s），改成只裁最后一段" % txt[-160:])
    w, h = a.tp_w, a.tp_h
    th = int(round(w * 9 / 16.0))
    th -= th % 2
    out = job / "master_16x9.mp4"
    vf = "crop=%d:%d:0:%d" % (w, th, (h - th) // 2) if th != h else "crop=%d:%d:0:0" % (w, h)
    rc, txt = sh([str(FFMPEG), "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264",
                  "-crf", "18", "-preset", "slow", "-c:a", "aac", "-b:a", "160k", str(out)],
                 timeout=1800)
    if out.is_file():
        log("✔ 母版 %s｜%d×%d｜%d 段｜素材共 %.2fs"
            % (out, w, th, len(vids), sum(s["len"] for s in st["shots"]) / 24.0))
        return 0
    log("🔴 拼片失败：%s" % txt[-400:])
    return 1


# --------------------------------------------------------------- 入口
def main():
    global CAMERA_STYLE
    ap = argparse.ArgumentParser(
        description="一句话→提示词→本地生图→目审闸→本地 H3 成片（全程 127.0.0.1，零联网）")
    ap.add_argument("--say", help="一句话")
    ap.add_argument("--job", default=None, help="作业号；缺省由 --say 生成")
    ap.add_argument("--stage", default="all",
                    choices=["compile", "render", "frames", "video", "stitch", "all"])
    ap.add_argument("--shots", type=int, default=4, help="镜头数（每镜 124 帧≈5.17 秒）")
    ap.add_argument("--llm", default="gateway", choices=["gateway", "off"],
                    help="写稿走通道3 网关 8080（后端 8081 那份 qwen3-14b）；off＝规则兜底，零端口")
    ap.add_argument("--seeds", type=int, default=1, help="每镜出几张首帧（远跳落地建议 2–3 择优）")
    ap.add_argument("--anchor", default=None,
                    help="本地造型锚图（定妆照）：各镜首帧从它 i2i 派生，锁服装与脸")
    ap.add_argument("--chain", action="store_true",
                    help="链式出帧：每镜首帧从上一镜首帧 i2i 派生（背景更稳，地理会慢慢漂）")
    ap.add_argument("--denoise", type=float, default=0.65, help="i2i 重绘强度（本脚本未标定）")
    ap.add_argument("--steps", type=int, default=6, help="Z-Image 步数")
    ap.add_argument("--approve", default=None, help="目审通过的镜号：all 或 S01,S03")
    ap.add_argument("--tp-w", dest="tp_w", type=int, default=TP_W)
    ap.add_argument("--tp-h", dest="tp_h", type=int, default=TP_H)
    ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--strength", type=float, default=0.5, help="Bunny 打斗 LoRA 强度")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="只打印将要执行的渲染命令，不提交、不碰显存")
    ap.add_argument("--camera-style", dest="camera_style", choices=["official", "house"],
                    default=None,
                    help="运镜句写法。official＝官方自然句（默认，base-en §4.3：写成镜内动作，"
                         "不堆句尾标签）；house＝房内 80 份现役稿与 10-09 人审金样用的标签式"
                         "「Camera: Tracking Shot at fast speed, ...」，只为对齐既有已审稿。"
                         "不给时沿用该作业台账里记的写法。")
    a = ap.parse_args()
    if a.camera_style is None:                       # 续跑老作业时沿用原写法，别悄悄换格式
        CAMERA_STYLE = (load_ledger(JOBROOT / a.job).get("camera_style")
                        if a.job else None) or CAMERA_STYLE
    else:
        CAMERA_STYLE = a.camera_style
    log("· 装配格式：h3_official_spec（官方契约）｜运镜写法 %s" % CAMERA_STYLE)

    if a.say:
        if not a.job:
            slug = re.sub(r"[^0-9A-Za-z]", "", a.say[:10]) or "job"
            a.job = "%s_%s" % (slug, time.strftime("%m%d_%H%M%S"))
        if a.stage in ("render", "video", "stitch", "frames"):
            ap.error("--say 只配 --stage compile|all（继续某个作业请用 --job）")
        rc = compile_stage(a)
        if rc or a.stage == "compile":
            return rc
        return frames_stage(a)
    if not a.job:
        ap.error("需要 --say（出新稿）或 --job（继续某个作业）")
    job = JOBROOT / a.job
    if not (job / "story.json").is_file():
        log("🔴 作业 %s 不存在或没出过稿。可选作业：%s"
            % (a.job, sorted(p.name for p in JOBROOT.glob("*")) if JOBROOT.is_dir() else "（空）"))
        return 1
    if a.stage == "compile":
        log("· 没给 --say，--stage compile 当作 render（照现有 story.json 重装配＋过闸）")
        a.stage = "render"
    return {"compile": compile_stage, "render": render_stage, "frames": frames_stage,
            "video": video_stage, "stitch": stitch_stage}[a.stage](a)


if __name__ == "__main__":
    sys.exit(main())
