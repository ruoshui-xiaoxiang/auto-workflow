import json, sys, os

BASE = os.path.join("D:", os.sep + "AIWorkflow", "engine", "comfy")

def dump(name):
    p = os.path.join(BASE, name)
    d = json.load(open(p, encoding="utf-8"))
    print("===== %s (%d nodes) =====" % (name, len(d)))
    for k, v in sorted(d.items(), key=lambda x: int(x[0])):
        ins = v.get("inputs", {})
        print("  %-3s %-28s %s" % (k, v.get("class_type"),
              json.dumps(ins, ensure_ascii=False)))

for n in sys.argv[1:]:
    dump(n)
