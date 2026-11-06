# -*- coding: utf-8 -*-
"""把跑通配置重新发射成画布(前端工作流), 放进 ComfyUI 侧栏: user/default/workflows/D_接力_R11/
2026-10-15 二版: 引擎模板已升级(TE=GPU + VRAM_Debug 卸 TE + euler + ck 启动旗)。
两张画布均与引擎模板 front→API 往返验证逐字一致才落盘。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from build_workflows import frontend_to_api  # 往返验证器

ENG = Path(r"D:/AIWorkflow/engine/comfy")
OUT = Path(r"D:/AIWorkflow/ComfyUI_H3/ComfyUI/user/default/workflows/D_接力_R11")
OBJ = json.loads((HERE / "object_info.json").read_text(encoding="utf-8"))

R11_NOTE = (
    "R11 段间接力·续段 v2（EP1v2 s7→s8 跑通配置, 2026-10-15 二版）。\n"
    "跑前必读 R11_段间接续生成.md。本画布＝镜2(续段)臂；父段入链用同目录画布1。\n"
    "提速后的启动条件：① 服务器【不带】--use-sage-attention, 带 --reserve-vram 6.0 "
    "--use-ck-attention；② 文本编码走 GPU（device=default, 已设），两个条件节点之后、"
    "采样之前用 VRAM_Debug（unload_all_models=true）卸掉 TE——不卸会顶穿 LOW 守卫；\n"
    "③ 画布 64 对齐(768×448/low 384×224, 已设)；④ 采样器 native euler(已设)；"
    "⑤ first_frame_reuse=persistent_identity_reference(已设)。\n"
    "实测（2026-10-15）：全配置单镜 222~248s（CPU TE 版本 498s，最初 654.7s）。\n"
    "换镜对要改：Source(链名/父candidate_id/sha=父片sampling_summary)·两处 prompt·"
    "三处 seed·Plan/EmptyLatent 的 length(22+新段帧)·SaveVideo 前缀·KF 图。\n"
    "产物含 21 帧上下文前缀, 测量用 tools\\post\\seam_check.py 剥离；"
    "接力产物不自动入链, 续下一段前先把本段 CandidateSave→Accept。")


def declared_inputs(ct):
    sp = OBJ[ct].get("input", {})
    names = set()
    for sec in ("required", "optional"):
        names.update((sp.get(sec) or {}).keys())
    return names


def is_widget_input(isp):
    typ = isp[0]
    if isinstance(typ, str):
        if not (typ in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO")
                or typ.startswith("COMFY_DYNAMICCOMBO")):
            return False
    opts = isp[1] if len(isp) > 1 and isinstance(isp[1], dict) else {}
    return not opts.get("forceInput")


def depth_of(api):
    depth = {}

    def d(nid):
        if nid in depth:
            return depth[nid]
        depth[nid] = 0
        best = 0
        for v in api[nid]["inputs"].values():
            if isinstance(v, list) and v and isinstance(v[0], str):
                best = max(best, d(v[0]) + 1)
        depth[nid] = best
        return best

    for nid in api:
        d(nid)
    return depth


def emit_canvas(api, stem, extra_note=None):
    depth = depth_of(api)
    cols = {}
    for nid, dp in sorted(depth.items(), key=lambda x: int(x[0])):
        cols.setdefault(dp, []).append(nid)
    links, front_nodes, lid = [], [], 0
    for dp, ids in cols.items():
        for row, nid in enumerate(ids):
            ct = api[nid]["class_type"]
            spec = OBJ[ct]
            ins_spec = {}
            for sec in ("required", "optional"):
                ins_spec.update(spec.get("input", {}).get(sec) or {})
            out_types = spec.get("output", [])
            out_names = spec.get("output_name", out_types)
            inputs, wv, used = [], [], {}
            for name, isp in ins_spec.items():
                val = api[nid]["inputs"].get(name)
                if is_widget_input(isp):
                    if not isinstance(val, list):
                        wv.append(val)
                        if (isinstance(isp[0], str) and isp[0] == "INT"
                                and "seed" in name):
                            wv.append("fixed")
                    elif val is not None:
                        wv.append(val)  # 被 link 覆盖的 widget 位
                    continue
                if isinstance(val, list):
                    used[name] = val
            for name, (src, sslot) in used.items():
                lid += 1
                stype = OBJ[api[str(src)]["class_type"]]["output"][sslot]
                links.append([lid, int(src), sslot, int(nid),
                              list(used).index(name), stype])
                inputs.append({"name": name, "type": stype, "link": lid})
            outputs = [{"name": out_names[i], "type": out_types[i], "links": [],
                        "slot_index": i} for i in range(len(out_types))]
            front_nodes.append({"id": int(nid), "type": ct,
                "pos": [80 + dp * 380, 80 + row * 300],
                "size": [315, 200], "flags": {}, "order": int(nid), "mode": 0,
                "inputs": inputs, "outputs": outputs,
                "properties": {"Node name for S&R": ct},
                "widgets_values": wv})
    for lk in links:
        for n in front_nodes:
            if n["id"] == lk[1]:
                n["outputs"][lk[2]]["links"].append(lk[0])
    if extra_note:
        nid = max(int(n) for n in api) + 1
        front_nodes.append({"id": nid, "type": "MarkdownNote",
            "pos": [80, 80 + max(len(v) for v in cols.values()) * 300 + 40],
            "size": [560, 320], "flags": {}, "order": nid, "mode": 0,
            "inputs": [], "outputs": [], "title": "读我",
            "properties": {}, "widgets_values": [extra_note]})
    return {"id": stem, "revision": 0,
            "last_node_id": max(int(n) for n in api),
            "last_link_id": max(lid, 1),
            "nodes": front_nodes, "links": links, "groups": [],
            "config": {}, "extra": {}, "version": 0.4}


def roundtrip(g, ref_api, tag):
    api, dropped = frontend_to_api(g, OBJ)
    dropped = [(i, t) for i, t in dropped if t != "MarkdownNote"]
    assert not dropped, (tag, "unknown nodes", dropped)
    bad = []
    for nid, ref in ref_api.items():
        got = api.get(nid)
        decl = declared_inputs(ref["class_type"])
        ref_in = {k: v for k, v in ref["inputs"].items() if k in decl}
        got_in = (got or {}).get("inputs", {})
        if ref_in != got_in:
            for k in set(ref_in) | set(got_in):
                if ref_in.get(k) != got_in.get(k):
                    bad.append((nid, k, ref_in.get(k), got_in.get(k)))
    extra = set(api) - set(ref_api)
    print(f"[{tag}] nodes={len(api)} mismatched={len(bad)} extra={sorted(extra)}")
    for b in bad[:10]:
        print("   ", b)
    return not bad and not extra


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    api_p = json.loads((ENG / "h3_relay_parent_api.json").read_text(encoding="utf-8"))
    api_c = json.loads((ENG / "h3_relay_cont_api.json").read_text(encoding="utf-8"))
    gp = emit_canvas(api_p, "R11-parent-768x448")
    gc = emit_canvas(api_c, "R11-cont-768x448", extra_note=R11_NOTE)
    okp, okc = roundtrip(gp, api_p, "A_父段入链"), roundtrip(gc, api_c, "B_续段接力")
    if not (okp and okc):
        print("!! 往返验证未过, 不落盘")
        return 1
    (OUT / "D01_接力_R11_父段_768x448.json").write_text(
        json.dumps(gp, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "D02_接力_R11_续段_768x448.json").write_text(
        json.dumps(gc, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "读我_R11跑通配置.md").write_text(
        "# D_接力_R11（2026-10-15 二版·提速配置）\n\n"
        "- 规则真源：`E:\\本地工作流规范手册\\20_通用规范层\\R11_段间接续生成.md`\n"
        "- 画布1 父段入链 ＝ 768×448 重渲镜N并 CandidateSave→Accept（dual_clock，TE=GPU）；\n"
        "- 画布2 续段接力 ＝ EXPT8 续段（euler＋turbo LoRA＋KF 身份参考＋TE=GPU＋VRAM_Debug 卸 TE）。\n"
        "- **启动参数（画布带不进去，必须人工保证）**：不带 `--use-sage-attention`；带 "
        "`--reserve-vram 6.0 --use-ck-attention`。\n"
        "- 实测单镜 222~248s（CPU TE 版 498s，最初 654.7s）。\n"
        "- 两画布均与引擎模板往返验证逐字一致（engine\\comfy\\h3_relay_{parent,cont}_api.json）。\n",
        encoding="utf-8")
    print("SAVED to", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
