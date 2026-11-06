import json
import os
import re

TPL = r"D:\AIWorkflow\engine\comfy"
for n in ("draft_flux_api.json", "draft_upscale_api.json",
          "image_draft_batch_sdxl_api.json", "draft_sdxl_api.json",
          "z_image_turbo_api.json"):
    p = os.path.join(TPL, n)
    if not os.path.exists(p):
        print("%-30s （文件不存在）" % n)
        continue
    t = open(p, encoding="utf-8").read()
    d = json.loads(t)
    cls = {}
    for k, v in d.items():
        cls[v.get("class_type")] = cls.get(v.get("class_type"), 0) + 1
    print("%-28s %2d节点  占位符: %s" % (n, len(d), ", ".join(sorted(set(re.findall(r"__[A-Z0-9_]+__", t))))))
    print("      类: %s" % ", ".join("%s×%d" % (a, b) for a, b in sorted(cls.items())))
