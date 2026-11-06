# -*- coding: utf-8 -*-
import io, os, sys, json
sys.path.insert(0, r"D:/AIWorkflow/tmp/jianlai_test")
sys.path.insert(0, r"D:/AIWorkflow/tmp/wzy")
import ark_img
from dz_prompts import FACEDESC, BODY, TWEAK
OUT = r"D:/AIWorkflow/tmp/wzy/dz0h"
os.makedirs(OUT, exist_ok=True)
res = {}
for i, k in enumerate(sorted(TWEAK)):
    prompt = FACEDESC + TWEAK[k] + BODY
    io.open(os.path.join(OUT, "%s.txt" % k), "w", encoding="utf-8").write(prompt)
    try:
        urls = ark_img.call(prompt, [], 2026100201 + i, 1536, 2688)
        p = ark_img.fetch(urls[0], os.path.join(OUT, "%s_raw.png" % k))
        res[k] = os.path.basename(p); print("OK", k, os.path.getsize(p)//1024, "KB")
    except Exception as e:
        res[k] = None; print("FAIL", k, str(e)[:200])
json.dump(res, io.open(os.path.join(OUT, "dz0h_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("done", sum(1 for v in res.values() if v), "/6")
