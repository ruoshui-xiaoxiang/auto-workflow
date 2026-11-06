# -*- coding: utf-8 -*-
"""逐帧人脸修复（CodeFormer）后处理：拆帧 -> 修脸 -> 重编码（保留原音轨）。

用法:
  py face_restore.py <源视频> [--fidelity 0.5] [--facedet retinaface_resnet50] [--out 输出名]
流程: 复制源片到 ComfyUI input -> LoadVideo -> GetVideoComponents -> FaceRestoreCFWithModel -> CreateVideo -> SaveVideo
"""
import sys, time, json, shutil, os, argparse, urllib.request, uuid

HOST = "http://127.0.0.1:8189"
INPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\input"
OUTPUT_DIR = r"D:\AIWorkflow\ComfyUI_H3\output"
FACE_MODEL = "codeformer-v0.1.0.pth"


def http_json(method, url, data=None):
    req = urllib.request.Request(url, method=method)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, body, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def build_wf(video_name, fidelity, facedet):
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "FaceRestoreModelLoader", "inputs": {"model_name": FACE_MODEL}},
        "4": {"class_type": "FaceRestoreCFWithModel",
              "inputs": {"facerestore_model": ["3", 0], "image": ["2", 0],
                         "facedetection": facedet, "codeformer_fidelity": fidelity}},
        "5": {"class_type": "CreateVideo",
              "inputs": {"images": ["4", 0], "fps": ["2", 2], "audio": ["2", 1]}},
        "6": {"class_type": "SaveVideo",
              "inputs": {"video": ["5", 0], "filename_prefix": "facefix",
                         "format": "mp4", "codec": "h264"}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--fidelity", type=float, default=0.5)
    ap.add_argument("--facedet", default="retinaface_resnet50")
    ap.add_argument("--out", default="facefix")
    a = ap.parse_args()

    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base = os.path.basename(a.src)
    stem, ext = os.path.splitext(base)
    vname = f"fr_{stem}_{uuid.uuid4().hex[:6]}{ext}"
    shutil.copy2(a.src, os.path.join(INPUT_DIR, vname))

    wf = build_wf(vname, a.fidelity, a.facedet)
    print(f"[face_restore] 提交: {base}  fidelity={a.fidelity} det={a.facedet}", flush=True)
    t0 = time.time()
    resp = http_json("POST", HOST + "/prompt", {"prompt": wf, "client_id": "face_restore"})
    pid = resp.get("prompt_id")
    print(f"[face_restore] prompt_id={pid}", flush=True)

    h = {}
    last = ""
    while True:
        time.sleep(5)
        hist = http_json("GET", HOST + f"/history/{pid}")
        if pid not in hist:
            continue
        h = hist[pid]
        st = (h.get("status") or {}).get("status_str", "")
        if st != last:
            print(f"[face_restore] 状态: {st}  已用 {time.time()-t0:.0f}s", flush=True)
            last = st
        if (h.get("status") or {}).get("completed") or st == "error":
            break

    outputs = h.get("outputs", {})
    for key in ("images", "animated", "videos", "gifs"):
        for nid, out in outputs.items():
            items = out.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                fn = item.get("filename")
                if fn and fn.lower().endswith((".mp4", ".webm", ".mov")):
                    src = os.path.join(OUTPUT_DIR, fn)
                    if os.path.exists(src):
                        dst = os.path.join(OUTPUT_DIR, a.out + os.path.splitext(fn)[1])
                        shutil.copy2(src, dst)
                        print(f"[face_restore] 完成: {dst}  耗时 {time.time()-t0:.0f}s", flush=True)
                        return
    print(f"[face_restore] 无输出. history keys={list(outputs.keys())}", flush=True)


if __name__ == "__main__":
    main()
