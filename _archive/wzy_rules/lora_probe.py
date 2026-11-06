# -*- coding: utf-8 -*-
"""LoRA 装机前探针：读 header，先看触发词与键前缀能不能对上底模。

为什么先读 header 再跑图：上一轮就是没带触发词，三张全出成照片级，
差点把"没触发"误报成"没生效"。跑一次图 6~16 秒，读一次 header 不到 1 秒。

用法：python lora_probe.py <lora.safetensors> [<lora2.safetensors> ...]
"""
import collections
import json
import os
import struct
import sys

BASE_KEYS = r"D:\Models\ComfyUI\diffusion_models\z_image_turbo_int8_convrot.safetensors"


def head(p):
    with open(p, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n).decode("utf-8"))


def base_module_keys():
    """底模里可被 LoRA 命中的模块名（去掉 .weight 后缀）。"""
    h = head(BASE_KEYS)
    return {k[:-7] for k in h if k.endswith(".weight")}


def probe(p, bkeys):
    h = head(p)
    keys = [k for k in h if k != "__metadata__"]
    meta = h.get("__metadata__") or {}
    print("=" * 74)
    print(os.path.basename(p), "｜%.1f MB" % (os.path.getsize(p) / 2**20))
    print("  张量数 %d｜dtype %s" % (len(keys),
          dict(collections.Counter(v.get("dtype") for v in h.values() if isinstance(v, dict)))))
    ranks = collections.Counter()
    for k in keys:
        if k.endswith("lora_A.weight"):
            ranks[h[k]["shape"][0]] += 1
    print("  rank 分布（lora_A 行数）:", dict(ranks))
    pref = sorted({k.split(".")[0] for k in keys})
    print("  顶层前缀:", pref)
    stripped = [k[len("diffusion_model."):] if k.startswith("diffusion_model.") else k for k in keys]
    mods = sorted({".".join(k.split(".")[:-3]) for k in stripped if "lora_" in k})
    print("  被改写的模块（前 6 个）:", mods[:6], "｜共 %d 组" % len(mods))
    if bkeys:
        hit = [m for m in mods if any(bk == m or bk.startswith(m + ".") or m in bk for bk in bkeys)]
        print("  与底模键名可对齐的模块组: %d/%d  %s"
              % (len(hit), len(mods), "✅" if len(hit) == len(mods) else "🔴 有对不上的"))
    print("  --- metadata ---")
    for k in ("format", "ss_base_model_version", "ss_training_flows", "version",
              "ss_epoch", "ss_steps", "ss_tag_frequency", "modelspec.architecture",
              "modelspec.title", "modelspec.usage"):
        if k in meta:
            v = str(meta[k])
            print("   %-26s %s" % (k, v[:220]))
    tf = meta.get("ss_tag_frequency")
    print("  🔴 触发词判读：", end="")
    if tf:
        try:
            tags = json.loads(tf)
            words = sorted({w for d in tags.values() for w in d if w})
            print("训练时绑定了 %s ⇒ **提示词必须带上原句**" % words)
        except Exception:
            print("ss_tag_frequency 解析失败，原文：%s" % str(tf)[:160])
    else:
        print("无 ss_tag_frequency ⇒ 大概不需要触发词（仍以实测为准）")


def main():
    bkeys = None
    try:
        bkeys = base_module_keys()
        print("底模可命中模块数:", len(bkeys))
    except Exception as e:
        print("🔴 读不到底模 header：", e)
    for p in sys.argv[1:]:
        if os.path.exists(p):
            probe(p, bkeys)
        else:
            print("缺文件:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
