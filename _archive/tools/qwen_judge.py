# -*- coding: utf-8 -*-
r"""千问多模态裁判 —— 用户 2026-09-16 授权：阶段审核由它替他打分。

背景：用户睡前说"我得先睡觉，做不了阶段审核，所以不用找我，你可以用千问的云端多模态
让它打分帮助审核"。所以本脚本承担「阶段质检员」的角色。

两种内置判据：
  identity  给一张参考脸 + 若干生成图，判断"是不是同一个人"，逐张 0-10 分
  quality   判断图像本身有没有崩坏（噪声/畸形/糊成一团），逐张 0-10 分

用法:
  py qwen_judge.py identity --ref 参考脸.png --test a.png b.png c.png
  py qwen_judge.py quality  --test a.png b.png
  py qwen_judge.py raw --images a.png --prompt "描述这张图"

⚠ 裁判的结论只是"参考意见"：按项目规矩，机器打分只能说 completed，人审过才 confirmed。
   所以本脚本的输出会标注「待用户确认」，不当作最终结论。
"""
import argparse
import base64
import json
import os
import re
import sys

from openai import OpenAI

KEYFILE = r"E:\密钥文件\阿里多模态.txt"
BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen3-vl-plus"

IDENTITY_RUBRIC = """你是严格的人脸一致性审核员。图1是参考人物，后面每张是生成结果。
请逐张判断：**生成图里的人脸和参考图是不是同一个人**。
只看身份（骨相、五官形状与比例、脸型、眼型、唇形、肤色气质），
不要因为发型、服装、背景、机位、光照、妆容不同就扣分——那些都是允许变化的。
评分标准（0-10）：
  9-10 明确是同一个人，换个角度/光也认得出
  6-8  大致像，但五官有可见偏移
  3-5  只有气质像，已经不是同一张脸
  0-2  完全不是一个人 / 图像崩坏无法判断
只输出 JSON，不要解释。格式：
{"scores":[{"image":2,"score":8,"reason":"20字内理由"}, ...]}
其中 image 从 2 开始编号（1 是参考图）。"""

QUALITY_RUBRIC = """你是图像质量审核员。逐张判断图像本身有没有崩坏。
检查：是否是噪声/雪花、人脸是否畸形或糊成一团、结构是否错乱、有无明显伪影。
评分（0-10）：10=干净正常，0=完全崩坏。
只输出 JSON：{"scores":[{"image":1,"score":9,"reason":"20字内理由"}, ...]}"""


def load_key():
    raw = open(KEYFILE, encoding="utf-8", errors="replace").read()
    keys = re.findall(r"(sk-[A-Za-z0-9._\-]+)", raw)
    if not keys:
        raise RuntimeError("密钥文件里没找到 key：%s" % KEYFILE)
    return keys[0]


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def data_url(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = "image/png" if ext == "png" else "image/jpeg"
    return "data:%s;base64,%s" % (mime, b64(path))


def ask(client, images, prompt, max_tokens=1500):
    content = [{"type": "text", "text": prompt}]
    for p in images:
        content.append({"type": "image_url", "image_url": {"url": data_url(p)}})
    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return r.choices[0].message.content


def parse_scores(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["identity", "quality", "raw"])
    ap.add_argument("--ref", default=None)
    ap.add_argument("--test", nargs="*", default=[])
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--prompt", default=None)
    a = ap.parse_args()

    client = OpenAI(api_key=load_key(), base_url=BASE)

    if a.mode == "raw":
        print(ask(client, a.images, a.prompt or "描述这些图"))
        return 0

    if a.mode == "identity":
        if not a.ref or not a.test:
            print("identity 需要 --ref 与至少一张 --test")
            return 2
        imgs = [a.ref] + a.test
        txt = ask(client, imgs, IDENTITY_RUBRIC)
        print("=== 千问裁判（身份一致性）===")
        print(txt)
        d = parse_scores(txt)
        if d:
            print("\n--- 解析 ---")
            for s in d.get("scores", []):
                idx = s.get("image", 0) - 2
                name = os.path.basename(a.test[idx]) if 0 <= idx < len(a.test) else "?"
                print("  %-40s %2s/10  %s" % (name, s.get("score"), s.get("reason", "")))
        print("\n⚠ 机器打分仅供参考，最终结论待用户确认。")
        return 0

    if a.mode == "quality":
        if not a.test:
            print("quality 需要 --test")
            return 2
        txt = ask(client, a.test, QUALITY_RUBRIC)
        print("=== 千问裁判（图像质量）===")
        print(txt)
        d = parse_scores(txt)
        if d:
            print("\n--- 解析 ---")
            for s in d.get("scores", []):
                idx = s.get("image", 0) - 1
                name = os.path.basename(a.test[idx]) if 0 <= idx < len(a.test) else "?"
                print("  %-40s %2s/10  %s" % (name, s.get("score"), s.get("reason", "")))
        print("\n⚠ 机器打分仅供参考，最终结论待用户确认。")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
