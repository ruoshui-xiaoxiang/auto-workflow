# -*- coding: utf-8 -*-
import io, os, sys, json
sys.path.insert(0, r"D:/AIWorkflow/tmp/jianlai_test")
sys.path.insert(0, r"D:/AIWorkflow/tmp/wzy")
import ark_img
from dz_prompts import BASE, FACES

OUT = os.environ.get("DZOUT", r"D:/AIWorkflow/tmp/wzy/dz0a")
os.makedirs(OUT, exist_ok=True)
SEEDS = {"F1": 2026093001, "F2": 2026093002, "F3": 2026093003,
         "F4": 2026093004, "F5": 2026093005, "F6": 2026093006}
res = {}
for k in sorted(FACES):
    pf = os.path.join(OUT, "%s.txt" % k)
    io.open(pf, "w", encoding="utf-8").write(BASE.replace("{FACE}", FACES[k]))
    prompt = io.open(pf, encoding="utf-8").read().strip()
    try:
        urls = ark_img.call(prompt, [], SEEDS[k], 1536, 2688)
        p = ark_img.fetch(urls[0], os.path.join(OUT, "%s_raw.png" % k))
        res[k] = os.path.basename(p)
        print("OK", k, os.path.getsize(p)//1024, "KB")
    except Exception as e:
        res[k] = None
        print("FAIL", k, str(e)[:220])
json.dump(res, io.open(os.path.join(OUT, "dz0a_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("done", sum(1 for v in res.values() if v), "/6")
