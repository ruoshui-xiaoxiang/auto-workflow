#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vl_judge.py — VL 语义闸（第四条裁判）：让 DeepSeek V4.1 Flash 看图回答固定问题清单

定位：量化裁判（边缘闸/骨架闸/深度闸）只能量"结构锁没锁住"；语义层（有没有人、
道具在不在、糊不糊、像不像未渲染的灰模）没有可微 loss，只能用判别器替代 ——
这个脚本就是那个判别器。

⚠️ 只做初筛，不做终审：VL 会幻觉；"好不好看/像不像角色"仍要人看。
⚠️ key 从环境变量读，**绝不打印**。

用法:
  py -3.12 vl_judge.py --images "<图通配>" --out <目录>
"""

import os, sys, json, base64, io, time, argparse, glob, csv, urllib.request

from PIL import Image

API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
KEY_ENV = "DEEPSEEK_API_KEY"

QUESTIONS = """你是画面质检员。看这张图，只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。
字段与取值：
{
 "has_person": true/false  // 画面里有没有清晰可辨的人形（不是方块/占位体块）
 "person_count": 0  // 人形数量，整数
 "person_pose": "一句话描述人物姿态；没有就写 none",
 "looks_like_placeholder": true/false  // 是否明显像"未渲染完成的灰模/占位体块/低模"，而非成品画面
 "blurry": true/false  // 是否整体明显模糊
 "artifacts": ["列出可见的伪影"]  // 如 水印/文字乱码/肢体变形/多指/闪烁块；没有就 []
 "props": ["画面里认得出的道具"]  // 如 伞/书/石桌/树
 "notes": "一句话补充，或 none"
}"""


def data_url(path, max_side=1024, quality=88):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def judge(key, path, retry=2):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": QUESTIONS},
            {"type": "image_url", "image_url": {"url": data_url(path), "detail": "high"}},
        ]}],
        "temperature": 0,
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for i in range(retry + 1):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=120).read())
            txt = r["choices"][0]["message"]["content"].strip()
            if txt.startswith("```"):
                txt = txt.split("```")[1].lstrip("json").strip()
            d = json.loads(txt)
            d["_model_used"] = r.get("model", "")
            return d
        except Exception as e:
            if i == retry:
                return {"_error": str(e)[:200]}
            time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        print(f"环境里没有 {KEY_ENV}（Qoder 需重启才能继承新设的变量）"); sys.exit(2)

    files = sorted(glob.glob(a.images))
    if not files:
        print("没匹配到图:", a.images); sys.exit(2)
    os.makedirs(a.out, exist_ok=True)

    rows = []
    for i, p in enumerate(files, 1):
        t0 = time.time()
        d = judge(key, p)
        name = os.path.basename(p)
        if "_error" in d:
            print(f"[{i}/{len(files)}] {name}  失败: {d['_error']}")
            rows.append({"image": name, "error": d["_error"]})
            continue
        print(f"[{i}/{len(files)}] {name}  人={d.get('has_person')}×{d.get('person_count')} "
              f"占位感={d.get('looks_like_placeholder')} 糊={d.get('blurry')} "
              f"伪影={len(d.get('artifacts') or [])}  ({time.time()-t0:.0f}s)")
        rows.append({
            "image": name,
            "has_person": d.get("has_person"),
            "person_count": d.get("person_count"),
            "person_pose": d.get("person_pose"),
            "looks_like_placeholder": d.get("looks_like_placeholder"),
            "blurry": d.get("blurry"),
            "artifacts": ";".join(d.get("artifacts") or []),
            "props": ";".join(d.get("props") or []),
            "notes": d.get("notes"),
            "model_used": d.get("_model_used", ""),
        })

    cols = ["image", "has_person", "person_count", "person_pose", "looks_like_placeholder",
            "blurry", "artifacts", "props", "notes", "model_used", "error"]
    out = os.path.join(a.out, "vl_judge.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n[VL] {len(rows)} 张 → {out}")


if __name__ == "__main__":
    main()
