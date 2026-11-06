# -*- coding: utf-8 -*-
"""给 ComfyUI 工作流 JSON 自动排版：按数据流分层，节点从左到右、层内垂直展开。

ComfyUI 画布里每个节点的位置存在节点自己的 `pos: [x, y]` 字段。API 格式的
工作流（引擎直接提交 /prompt 的那类）通常不带 pos，一打开所有节点叠在原点，
显得乱。本脚本只补/改 pos，其余字段原样保留；对 /prompt 执行无副作用
（ComfyUI 执行时忽略 pos）。

用法:
    python layout_workflow.py <file.json> [file.json ...]
    python layout_workflow.py --dir <目录>          # 目录下所有 .json

支持两种结构：
    API 格式: {node_id: {class_type, inputs: {..: ["src_id", slot]}}}
    UI 格式:  {nodes: [{id, type, ...}], links: [[lid, from, fs, to, ts, type]]}
"""
import json
import os
import sys
from collections import defaultdict, deque

X_STEP = 380     # 列间距（节点宽约 300 + 留白）
Y_STEP = 200     # 行间距（多数节点高约 110~160）
X_TOP = 20
Y_TOP = 60


def _numkey(x):
    try:
        return (0, int(x))
    except (ValueError, TypeError):
        return (1, str(x))


def detect(d):
    return "ui" if (isinstance(d, dict) and isinstance(d.get("nodes"), list)) else "api"


def build_graph(d, fmt):
    """返回 (edges[(from_id, to_id)], ids集合)。"""
    edges, ids = [], set()
    if fmt == "api":
        ids = {k for k, v in d.items() if isinstance(v, dict) and "class_type" in v}
        for k, v in d.items():
            if not isinstance(v, dict):
                continue
            for val in v.get("inputs", {}).values():
                if (isinstance(val, list) and len(val) >= 2
                        and isinstance(val[0], str) and val[0] in ids):
                    edges.append((val[0], k))
    else:
        ids = {n["id"] for n in d["nodes"]}
        for lk in d.get("links", []):
            if len(lk) >= 4 and lk[1] in ids and lk[3] in ids:
                edges.append((lk[1], lk[3]))
    return edges, ids


def layout(d, fmt):
    edges, ids = build_graph(d, fmt)
    indeg = {i: 0 for i in ids}
    adj = defaultdict(list)
    parents = defaultdict(list)
    for f, t in edges:
        indeg[t] += 1
        adj[f].append(t)
        parents[t].append(f)

    # 最长路径分层（Kahn 拓扑）：level = 最长前驱链
    level = {i: 0 for i in ids}
    q = deque(i for i in ids if indeg[i] == 0)
    while q:
        f = q.popleft()
        for t in adj[f]:
            if level[f] + 1 > level[t]:
                level[t] = level[f] + 1
            indeg[t] -= 1
            if indeg[t] == 0:
                q.append(t)

    cols = defaultdict(list)
    for i in ids:
        cols[level[i]].append(i)

    # 层内用重心法排序（按前驱在上一层里的平均位置），减少连线交叉
    order = {}
    for lv in sorted(cols):
        if lv == 0:
            seq = sorted(cols[lv], key=_numkey)
        else:
            def bary(n):
                ps = parents.get(n) or []
                if not ps:
                    return float("inf")
                return sum(order.get(p, 0) for p in ps) / len(ps)
            seq = sorted(cols[lv], key=lambda n: (bary(n), _numkey(n)))
        for row, n in enumerate(seq):
            order[n] = row

    pos = {}
    for n in ids:
        pos[n] = [X_TOP + level[n] * X_STEP, Y_TOP + order[n] * Y_STEP]
    return pos


def apply(d, fmt, pos):
    if fmt == "api":
        for k, v in d.items():
            if isinstance(v, dict) and k in pos:
                v["pos"] = pos[k]
    else:
        for n in d["nodes"]:
            if n["id"] in pos:
                n["pos"] = pos[n["id"]]
    return d


def main(argv):
    files = []
    if argv and argv[0] == "--dir":
        for root, _, fs in os.walk(argv[1]):
            for f in fs:
                if f.lower().endswith(".json"):
                    files.append(os.path.join(root, f))
    else:
        files = argv
    if not files:
        print(__doc__)
        return 2
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            d = json.load(fh)
        fmt = detect(d)
        pos = layout(d, fmt)
        apply(d, fmt, pos)
        with open(fp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        print(f"{os.path.basename(fp):32s} {len(pos):2d} 节点已排版 ({fmt})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
