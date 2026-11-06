# -*- coding: utf-8 -*-
"""三线型规则：order / chain / ref。

边方向约定（与画布画线方向一致）：
- ``order`` 与 ``chain``：由上游指向下游，``from``=A，``to``=B。
- ``ref``：由消费方指向参考源，``from``=B（引用者），``to``=A 或 ``@锚点``。

``apply_edges`` 会**就地修改**传入的镜头字典（chain 写入 ``image``，
ref 追加到 ``images``），并按片序返回同一批字典的引用；调用方手里的
``shots`` 也会同步变化，不做深拷贝。
"""
from .canvas_paths import CanvasError


class EdgeError(CanvasError):
    def __init__(self, message):
        super().__init__(message, 422)


def _is_ref_value(value):
    """参考值必须是去空白后非空的字符串。"""
    return isinstance(value, str) and bool(value.strip())


def auto_edges(shots):
    ids = [s["id"] for s in shots]
    return [
        {"id": "auto-%d" % i, "from": ids[i], "to": ids[i + 1], "type": "order"}
        for i in range(len(ids) - 1)
    ]


def topo_order(ids, edges):
    orders = [e for e in edges if e.get("type") == "order"]
    if not orders:
        return list(ids)
    known = set(ids)
    nxt = {}
    indeg = {i: 0 for i in ids}
    for e in orders:
        a, b = e.get("from"), e.get("to")
        if a not in known or b not in known:
            raise EdgeError("片序边引用了不存在的镜头：%s -> %s" % (a, b))
        if b in indeg and indeg[b] > 0:
            raise EdgeError("镜头 %s 有多个片序父节点" % b)
        indeg[b] += 1
        nxt[a] = b
    roots = [i for i in ids if indeg[i] == 0]
    if not roots:
        raise EdgeError("片序没有起点（可能存在环）")
    if len(roots) > 1:
        raise EdgeError("片序有多个起点")
    if len(orders) != len(ids) - 1:
        raise EdgeError("片序边没有把所有镜头串成一条链")
    out, cur, seen = [], roots[0], set()
    while cur is not None:
        if cur in seen:
            raise EdgeError("片序存在环")
        seen.add(cur)
        out.append(cur)
        cur = nxt.get(cur)
    if len(out) != len(ids):
        raise EdgeError("片序有游离节点")
    return out


def apply_edges(shots, edges, anchors=None):
    """应用 order / chain / ref 三类边，返回按片序排列的镜头列表。

    **就地修改**：chain 把 ``binding`` 写进下游镜头的 ``image``；ref 把参考值
    追加进引用者镜头的 ``images``（必要时新建该列表）。函数不复制镜头，
    返回值就是传入 ``shots`` 里同一批字典的引用，顺序为 ``topo_order`` 的片序。

    应用分两趟，因此结果与边在 JSON 里的先后顺序无关：先应用全部 chain，
    再应用全部 ref（ref 因而能看到 chain 刚写入的 ``image``）；order 只参与
    片序计算。

    参数：
    - ``shots``：镜头字典列表，每项至少有 ``id``。
    - ``edges``：边列表；``order``/``chain`` 方向 from=上游 to=下游，
      ``ref`` 方向 from=引用者 to=参考源（镜头 id 或 ``@锚点``）。
    - ``anchors``：锚点名到参考值的映射（值必须是字符串）；``None`` 视作空表，
      只有真的引用到锚点时才会报错。
    """
    if anchors is None:
        anchors = {}
    by_id = {s["id"]: s for s in shots}
    chains, refs = [], []
    for e in edges:
        kind = e.get("type")
        if kind == "order":
            continue
        if kind == "chain":
            chains.append(e)
        elif kind == "ref":
            refs.append(e)
        else:
            raise EdgeError("未知线型：%s" % kind)
    order = topo_order([s["id"] for s in shots], edges)
    for e in chains:
        source_id, target_id = e.get("from"), e.get("to")
        target = by_id.get(target_id)
        if target is None:
            raise EdgeError("边指向不存在的镜头：%s" % target_id)
        if source_id not in by_id:
            raise EdgeError("首尾帧链上游镜头不存在：%s" % source_id)
        if source_id == target_id:
            raise EdgeError("首尾帧链不能连到自己：%s" % target_id)
        binding = e.get("binding")
        if not isinstance(binding, str) or not binding.strip():
            raise EdgeError("首尾帧链 %s -> %s 未绑定有效末帧" % (source_id, target_id))
        target["image"] = binding
    for e in refs:
        source_id, target_id = e.get("to"), e.get("from")
        target = by_id.get(target_id)
        if target is None:
            raise EdgeError("边指向不存在的镜头：%s" % target_id)
        if target.get("mode") not in ("ref2va", "multiref"):
            raise EdgeError("参考依赖只能连到 ref2va/multiref 镜头：%s" % target_id)
        if not _is_ref_value(source_id):
            raise EdgeError("参考边缺少有效来源：%s" % target_id)
        if source_id.startswith("@"):
            name = source_id[1:]
            if name not in anchors:
                raise EdgeError("锚点不存在：%s" % source_id)
            value = anchors[name]
            if not _is_ref_value(value):
                raise EdgeError("锚点 %s 没有有效的参考值" % source_id)
        else:
            if source_id == target_id:
                raise EdgeError("参考边不能引用自己：%s" % target_id)
            src = by_id.get(source_id)
            if src is None:
                raise EdgeError("参考边引用了不存在的镜头：%s" % source_id)
            value = src.get("image")
            if not _is_ref_value(value):
                raise EdgeError("参考源镜头没有 image：%s" % source_id)
        imgs = target.get("images")
        if imgs is None:
            imgs = []
            target["images"] = imgs
        elif not isinstance(imgs, list):
            raise EdgeError("参考镜头的 images 不是列表：%s" % target_id)
        if value not in imgs:
            imgs.append(value)
    return [by_id[i] for i in order]
