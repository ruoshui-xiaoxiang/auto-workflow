# -*- coding: utf-8 -*-
r"""通用 ComfyUI 出图执行器 —— 加载 API 格式工作流、替换占位符、注入 LoRA、批量出图。

⚠ **定位（2026-10-19 规则收口 A3 明写）：这是排障／手工测量件，不是出片入口。**
它直连 8189 提交 `/prompt`，按 `AGENTS.md` 禁令 2 的口径，**agent 拿它出片就是破禁令**；
正式出片一律 `cd D:\AIWorkflow\engine && python run.py <workflow>`（批次归档、参数留痕、关口链都在那边）。
可以用它的场景只有一个：人主动要绕开编排单独量一张模板／一条接线（比如风格标定、节点排错）。

为什么写它（2026-09-16）：训练 LoRA 是「出图先走本地」的第一块承重墙，但评估、验证、
铺训练集三件事都要反复调 ComfyUI。与其每次写一次性脚本，不如做一个通用件。

能力：
  - 加载任意 API 格式工作流 JSON，替换 __XXX__ 占位符
  - --set KEY=VALUE     任意占位符（可重复）
  - --ref 本地图片       自动拷进 ComfyUI input 目录，把 __REF__ 设成它的文件名
  - --lora 名字:强度     动态插入 LoraLoaderModelOnly 节点，串到采样器的 model 链上
  - --n N               出 N 张（每张不同 seed）
  - --out 目录          把产物从 ComfyUI output 拷到指定位置

用法:
  py comfy_run.py --workflow D:\AIWorkflow\engine\comfy\draft_sdxl_api.json ^
      --set PROMPT="1girl, portrait" --set W=832 --set H=1216 --set STEPS=12 ^
      --n 4 --out D:\AIWorkflow\tmp\test --prefix mytest

  # 挂 LoRA
  py comfy_run.py --workflow ... --lora "A_old_params_dim32_lr2e4.safetensors:1.0" ...

  # 挂参考图（Z-Image i2i 两档；2026-10-19 第⑫条(b) 起 FLUX/Redux 那两档已退役，
  # 原示例里的 draft_flux_api.json / flux_redux_ref_api.json 现在只是路障桩，
  # 见 engine/comfy/_已退役_FLUX_20261019.md）
  py comfy_run.py --workflow D:\AIWorkflow\engine\comfy\z_style_S9_i2i_d45_api.json ^
      --set SRC_IMAGE="A1_脸·文字靶·正面.png" --set PROMPT="..." ...
"""
import argparse
import json
import os
import random
import shutil
import sys
import time
import urllib.request
import uuid

HOST = "http://127.0.0.1:8189"
COMFY = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI"
INPUT_DIR = os.path.join(COMFY, "input")
OUTPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"


def http_json(method, url, data=None, timeout=120):
    req = urllib.request.Request(url, method=method)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, body, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def server_alive():
    try:
        http_json("GET", HOST + "/system_stats", timeout=8)
        return True
    except Exception:
        return False


def wait_server(limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        if server_alive():
            return True
        time.sleep(5)
    return False


def find_sampler_model_src(wf):
    """找到采样器节点的 model 输入源，返回 (sampler_id, src_id, src_slot)。"""
    for nid, node in wf.items():
        if node.get("class_type") in ("KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced"):
            inp = node.get("inputs", {})
            for key in ("model",):
                v = inp.get(key)
                if isinstance(v, list) and len(v) == 2:
                    return nid, key, str(v[0]), v[1]
    return None, None, None, None


def inject_lora(wf, lora_name, strength, model_strength=None):
    """在采样器与它的 model 源之间插入 LoraLoaderModelOnly。"""
    nid, key, src, slot = find_sampler_model_src(wf)
    if nid is None:
        raise RuntimeError("工作流里找不到采样器，无法注入 LoRA")
    new_id = "9001"
    while new_id in wf:
        new_id = str(int(new_id) + 1)
    wf[new_id] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "lora_name": lora_name.replace("/", "\\"),
            "strength_model": float(model_strength if model_strength is not None else strength),
            "model": [src, slot],
        },
    }
    wf[nid]["inputs"][key] = [new_id, 0]
    return wf


def substitute(wf, mapping):
    """递归替换 __XXX__ 占位符。数值型会被识别成 int/float，其余按字符串。"""
    def conv(v):
        if not isinstance(v, str):
            return v
        s = v.strip()
        if s.startswith("__") and s.endswith("__") and s.upper() == s:
            return v
        return v

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            out = o
            for k, v in mapping.items():
                ph = "__%s__" % k
                if out == ph:
                    return v          # 整值替换，保留类型
                out = out.replace(ph, str(v))
            return out
        return o
    return walk(wf)


def run_once(wf, prefix, client_id):
    payload = {"prompt": wf, "client_id": client_id}
    try:
        resp = http_json("POST", HOST + "/prompt", payload)
    except urllib.error.HTTPError as e:
        # ComfyUI 把校验失败放在响应体里，只看状态码排不了障
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError("HTTP %s: %s" % (e.code, detail[:900]))
    pid = resp.get("prompt_id")
    if not pid:
        raise RuntimeError("提交失败：%s" % json.dumps(resp, ensure_ascii=False)[:400])
    while True:
        time.sleep(4)
        hist = http_json("GET", HOST + f"/history/{pid}")
        if pid not in hist:
            continue
        h = hist[pid]
        status = h.get("status", {})
        st = status.get("status_str", "")
        if status.get("completed") or st == "error":
            if st == "error":
                msgs = status.get("messages", [])
                raise RuntimeError("出图报错：%s" % json.dumps(msgs, ensure_ascii=False)[:500])
            for _ in range(6):
                if any(isinstance(v, dict) and v.get("images")
                       for v in h.get("outputs", {}).values()):
                    break
                time.sleep(2)
                hist2 = http_json("GET", HOST + f"/history/{pid}")
                if pid in hist2:
                    h = hist2[pid]
            break
    files = []
    for _, out in h.get("outputs", {}).items():
        for item in out.get("images", []) or []:
            if isinstance(item, dict) and item.get("filename"):
                files.append(item)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--ref", default=None, help="参考图本地路径（→ __REF__）")
    ap.add_argument("--lora", action="append", default=None,
                    help="名字.safetensors:强度（可重复，按给出顺序串联）")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--prefix", default="run")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()

    if not server_alive():
        print("ComfyUI 没在 %s 上跑。先启动它再回来。" % HOST)
        return 3
    print("ComfyUI 在线 ✓")

    wf = json.load(open(a.workflow, encoding="utf-8"))
    mapping = {}
    for kv in a.set:
        if "=" not in kv:
            print("--set 需要 KEY=VALUE：%s" % kv)
            return 2
        k, v = kv.split("=", 1)
        try:
            v2 = int(v)
        except ValueError:
            try:
                v2 = float(v)
            except ValueError:
                v2 = v
        mapping[k.upper()] = v2

    if a.ref:
        if not os.path.exists(a.ref):
            print("参考图不存在：%s" % a.ref)
            return 2
        os.makedirs(INPUT_DIR, exist_ok=True)
        base = os.path.basename(a.ref)
        dst = os.path.join(INPUT_DIR, base)
        if os.path.abspath(a.ref) != os.path.abspath(dst):
            shutil.copy2(a.ref, dst)
        mapping["REF"] = base
        print("参考图 → %s" % dst)

    mapping.setdefault("W", 832)
    mapping.setdefault("H", 1216)
    mapping.setdefault("STEPS", 12)
    mapping.setdefault("GUIDANCE", 3.5)
    mapping.setdefault("REDUX_STRENGTH", 1.0)

    os.makedirs(a.out or OUTPUT_DIR, exist_ok=True)
    client_id = str(uuid.uuid4())
    ok = 0
    for i in range(a.n):
        seed = a.seed if (a.seed is not None and a.n == 1) else random.randint(1, 2**31 - 1)
        prefix = "%s_%03d" % (a.prefix, i + 1)
        m = dict(mapping)
        m["SEED"] = seed
        m["PREFIX"] = prefix
        w = substitute(json.loads(json.dumps(wf)), m)
        for spec in (a.lora or []):
            name, _, st = spec.rpartition(":")
            if not name:
                name, st = spec, "1.0"
            w = inject_lora(w, name, st)
        print("[%d/%d] seed=%d prefix=%s" % (i + 1, a.n, seed, prefix), flush=True)
        try:
            files = run_once(w, prefix, client_id)
        except Exception as e:
            print("  失败：%s" % str(e)[:400])
            continue
        for f in files:
            src = os.path.join(OUTPUT_DIR, f.get("subfolder", ""), f["filename"])
            if a.out:
                shutil.copy2(src, os.path.join(a.out, f["filename"]))
            print("  → %s" % (os.path.join(a.out or OUTPUT_DIR, f["filename"])))
            ok += 1
    print("\n成 %d 张，落 %s" % (ok, a.out or OUTPUT_DIR))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
