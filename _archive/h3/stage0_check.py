# -*- coding: utf-8 -*-
"""阶段0验证：同一个 ComfyUI 实例(8189) 跨模型跑两条
  ① FLUX 出图（用引擎的 draft_flux_api.json 图，替换占位符）
  ② 混元 HV1.5 出视频（用 hv15_draft480_12s.json 图）
"""
import json, os, time, shutil, uuid, urllib.request

HOST = "http://127.0.0.1:8189"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUTPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"
FLUX_TPL = r"D:\AIWorkflow\engine\comfy\draft_flux_api.json"
HV15_WF = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\user\default\workflows\hv15_draft480_12s.json"


def http_json(method, url, data=None):
    req = urllib.request.Request(url, method=method)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, body, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def submit_and_wait(wf, label, timeout_s=1800):
    pid = http_json("POST", HOST + "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})["prompt_id"]
    print(f"[{label}] prompt_id={pid}", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(5)
        h = http_json("GET", HOST + f"/history/{pid}")
        if pid not in h:
            continue
        e = h[pid]
        st = (e.get("status") or {}).get("status_str", "")
        if (e.get("status") or {}).get("completed") or st == "error":
            if st == "error":
                print(f"[{label}] ERROR {json.dumps(e, ensure_ascii=False)[:600]}", flush=True)
                return None
            for _ in range(8):
                outs = e.get("outputs", {})
                if any(v.get(k) for v in outs.values() if isinstance(v, dict) for k in ("images", "animated", "gifs")):
                    break
                time.sleep(2)
                h2 = http_json("GET", HOST + f"/history/{pid}")
                if pid in h2:
                    e = h2[pid]
            print(f"[{label}] DONE {time.time()-t0:.0f}s", flush=True)
            return e.get("outputs", {})
    print(f"[{label}] TIMEOUT", flush=True)
    return None


def collect(outputs, exts, dst_name):
    for key in ("images", "animated", "gifs", "videos"):
        for out in outputs.values():
            items = out.get(key, [])
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and str(it.get("filename", "")).lower().endswith(exts):
                    src = os.path.join(OUTPUT_DIR, it["filename"])
                    if os.path.exists(src):
                        dst = os.path.join(OUTPUT_DIR, dst_name)
                        shutil.copy2(src, dst)
                        return dst
    return None


def main():
    # 拿一张自己的成片帧当混元 i2v 的起始图
    src_img = os.path.join(OUTPUT_DIR, "prev_shot06", "s_01.png")
    assert os.path.exists(src_img), f"缺测试输入图: {src_img}"
    img_name = "stage0_src.png"
    shutil.copy2(src_img, os.path.join(INPUT_DIR, img_name))

    # ---------- ① FLUX 出图 ----------
    tpl = json.loads(open(FLUX_TPL, encoding="utf-8").read())
    wf = json.loads(json.dumps(tpl))
    wf["3"]["inputs"]["text"] = ("a serene ancient-Chinese woman in a pale hanfu standing in a barren wasteland, "
                                 "cinematic realism, natural light, shallow depth of field")
    wf["5"]["inputs"]["guidance"] = 3.5
    wf["6"]["inputs"]["width"] = 832
    wf["6"]["inputs"]["height"] = 1216
    wf["7"]["inputs"]["seed"] = 42
    wf["7"]["inputs"]["steps"] = 12
    wf["12"]["inputs"]["filename_prefix"] = "stage0_flux"
    outs = submit_and_wait(wf, "FLUX", timeout_s=900)
    if outs:
        p = collect(outs, (".png", ".jpg", ".jpeg", ".webp"), "stage0_flux_test.png")
        print(f"[FLUX] 产物: {p}", flush=True)

    # ---------- ② 混元 HV1.5 出视频 ----------
    hv = json.loads(open(HV15_WF, encoding="utf-8").read())
    hv["5"]["inputs"]["image"] = img_name
    hv["7"]["inputs"]["text"] = ("Camera slowly pushes in on the dusty wasteland, thin haze drifts, "
                                 "subtle wind moves the debris, no people, smooth steady motion")
    hv["9"]["inputs"]["width"] = 720
    hv["9"]["inputs"]["height"] = 480
    hv["18"]["inputs"]["filename_prefix"] = "video/stage0_hv15"
    outs = submit_and_wait(hv, "混元HV1.5", timeout_s=1800)
    if outs:
        p = collect(outs, (".mp4", ".webm"), "stage0_hv15_test.mp4")
        print(f"[混元] 产物: {p}", flush=True)


if __name__ == "__main__":
    main()
