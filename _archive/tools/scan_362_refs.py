# -*- coding: utf-8 -*-
"""W5c：全仓 362 帧引用扫描（只读，出清单，不自动改）。

裁定依据（B1／D3，2026-10-23）：官方 4–15s 为准 ⇒ 引擎放行区间收 107–345；
**旧 362 批次只重排/标注，不篡改历史产物**。本脚本产出的清单交给人工逐条处置：

  · 已验收的历史产物 → 保留，不重跑（哈希必须不变，见 --verify）
  · 未完成／未验收 → 需按新版 G6（≤345）重排；重排要重算台词时长/动作容量/切点，
    不是把数字 362 改成 345 就完事（所以这里**绝不写回任何文件**）

扫描范围（全部只读）：
  1) D:\\AIWorkflow\\engine\\workflows\\*.yaml
  2) D:\\AIWorkflow\\engine\\comfy\\*.json
  3) E:\\图像影音资源池\\<项目>\\批次\\<run>\\*.manifest.json / h3_movie_plan.json / h3_movie_state.json
  4) D:\\AIWorkflow\\ComfyUI_H3\\ComfyUI\\user\\default\\workflows\\**.json（命名活画布）
  5) D:\\AIWorkflow\\ComfyUI_H3\\prompts*、engine\\prompts 里的 .txt/.md 提示词

输出：
  D:\\AIWorkflow\\evidence\\W5c\\scan_362.json      机器清单（含每个命中文件的 sha256）
  D:\\AIWorkflow\\evidence\\W5c\\需重排清单.md       人读处置表

用法：
  py -3.12 -B tools\\scan_362_refs.py            # 扫描并写清单
  py -3.12 -B tools\\scan_362_refs.py --verify   # 只比对已存清单里的哈希（V5c-2：历史产物未被改动）
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ENGINE = Path(r"D:\AIWorkflow\engine")
POOL = Path(r"E:\图像影音资源池")
CANVAS = Path(r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\user\default\workflows")
PROMPT_DIRS = [Path(r"D:\AIWorkflow\ComfyUI_H3\prompts"),
               Path(r"D:\AIWorkflow\ComfyUI_H3\prompts_H3官方骨架"),
               Path(r"D:\AIWorkflow\ComfyUI_H3\prompts_官方三段式"),
               ENGINE / "prompts"]
OUT_DIR = Path(r"D:\AIWorkflow\evidence\W5c")
JSON_OUT = OUT_DIR / "scan_362.json"
MD_OUT = OUT_DIR / "需重排清单.md"

NEWH3 = 345          # 新版 G6 上限
OLD = 362            # 要清理的旧值
# 只认**参数位**上的 362（length/frames/帧数 近旁），不认注释里"旧 362 已停用"这种说明文字，
# 否则清单会被自己写的解释灌满假报。
FRAME_RE = re.compile(r"(?i)(length|frames|帧数|frame_count)[^\n]{0,14}?%s" % OLD)


def _sha(p: Path):
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return None


def _hits_in_text(p: Path):
    """返回该文件里 362 的出现处（行号＋片段）。"""
    out = []
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    for i, line in enumerate(txt.splitlines(), 1):
        if FRAME_RE.search(line):
            out.append({"line": i, "text": line.strip()[:160]})
    return out


def _iter_manifests():
    if not POOL.is_dir():
        return
    for proj in sorted(POOL.iterdir()):
        if not proj.is_dir() or proj.name.startswith(("_", "云端素材", "娱乐流")):
            continue
        for run in sorted(proj.glob("批次/*")):
            if not run.is_dir():
                continue
            for f in run.glob("*.manifest.json"):
                yield proj.name, run.name, f
            for name in ("h3_movie_plan.json", "h3_movie_state.json"):
                f = run / name
                if f.is_file():
                    yield proj.name, run.name, f


def _manifest_362(f: Path):
    """从台账里判断这次批次是否真的按 362 帧跑过，以及产物是否已在盘。"""
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    hits = []
    args = data.get("args") or {}
    if str(args.get("length")) == str(OLD):
        hits.append("args.length")
    for sp in (data.get("step_params") or {}).values():
        if isinstance(sp, dict) and str(sp.get("length")) == str(OLD):
            hits.append("step_params.length")
    for s in (data.get("shots") or []):
        if not isinstance(s, dict):
            continue
        gen = s.get("generation") or {}
        if isinstance(gen, dict) and str(gen.get("length")) == str(OLD):
            hits.append("shot:%s" % s.get("id"))
    if isinstance(data.get("shots"), dict):
        for sid, rec in data["shots"].items():
            if str((rec or {}).get("generation", {}).get("length")) == str(OLD):
                hits.append("state:%s" % sid)
            if str((rec or {}).get("status") or "") in ("qc_failed", "failed", "pending"):
                hits.append("status:%s=%s" % (sid, rec.get("status")))
    return {"hits": sorted(set(hits)), "run_id": data.get("run_id") or f.parent.name,
            "workflow": data.get("workflow") or "", "status": data.get("status") or ""}


def _produced(batch_dir: Path):
    """这一批是否真出过片 ＋ 产物清单与哈希（只读）。

    返回 (bool, {相对路径: sha256})。**成片本体必须进哈希**：
    10-24 质量核查指出旧版只哈希 manifest JSON ⇒ "历史产物哈希不变"只有半证。
    """
    if not batch_dir.is_dir():
        return False, {}
    found, hashes = False, {}
    try:
        for p in batch_dir.rglob("*.mp4"):
            if len(p.relative_to(batch_dir).parts) > 4:
                continue
            found = True
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            hashes[str(p.relative_to(batch_dir))] = h.hexdigest()
    except Exception:
        pass
    return found, hashes


def _status_index():
    """真实台账里每个 run_id 的最终状态；读不到就返回空表，不猜。"""
    sf = Path(r"D:\AIWorkflow\logs\workflows\status.json")
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(h.get("run_id")): str(h.get("status"))
            for h in (data.get("history") or []) if h.get("run_id")}


def scan():
    run_status = _status_index()
    rows = []
    for label, base, pattern in (("workflow_yaml", ENGINE / "workflows", "*.yaml"),
                                 ("comfy_template", ENGINE / "comfy", "*.json"),
                                 ("canvas", CANVAS, "**/*.json")):
        if not base.is_dir():
            continue
        for p in sorted(base.glob(pattern)):
            h = _hits_in_text(p)
            if h:
                rows.append({"scope": label, "path": str(p), "kind": "文本命中 362",
                             "detail": h[:6], "sha256": _sha(p),
                             "disposal": "需人工确认：改模板/画布/流会影响在跑批次，本批不动"})
    for proj, run, f in _iter_manifests():
        info = _manifest_362(f)
        if not info or not info["hits"]:
            continue
        produced, media_hashes = _produced(f.parent)
        state = run_status.get(run) or info.get("status") or "台账无记录"
        rows.append({"scope": "batch_manifest", "path": str(f), "project": proj, "run_id": run,
                     "kind": "台账 length=362", "detail": info["hits"][:8],
                     "run_status": state, "produced_mp4": produced,
                     "media_sha256": media_hashes, "sha256": _sha(f),
                     "disposal": ("已出片：历史保留、不重跑（哈希必须不变）"
                                  if produced else
                                  "未出片/未完成：需按新版 G6（≤345）重排（要重算台词时长/"
                                  "动作容量/切点，不是只改数字）")})
    for d in PROMPT_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".txt", ".md"):
                h = _hits_in_text(p)
                if h:
                    rows.append({"scope": "prompt_text", "path": str(p), "kind": "提示词写了 362",
                                 "detail": h[:4], "sha256": _sha(p),
                                 "disposal": "需重排：提示词里的帧数/切点要按 ≤345 重算，不能只改数字"})
    return rows


def write_out(rows):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "old_frames": OLD, "new_max_frames": NEWH3,
               "note": "本清单只登记，不自动改任何文件；处置列给人逐条签字",
               "limits": {
                   "self_proving": (
                       "produced_mp4（是否已出片）与 media_sha256 读的是同一批 mp4 文件："
                       "--verify 只能证明『扫描器看到的东西没被改动』，"
                       "不能独立证明『已出片/未出片』这个分类判据本身对不对。"
                       "判据是否合理需人工复核清单，不要拿 0 变化当处置正确的证据。"),
                   "match_scope": (
                       "文本命中只认 length/frames/帧数 近旁的 362（参数位）；"
                       "注释或说明文字里的 362 不计，故本清单不是『全仓 362 字符串』的穷举。")},
               "total": len(rows),
               "by_scope": {s: sum(1 for r in rows if r["scope"] == s)
                            for s in sorted({r["scope"] for r in rows})},
               "rows": rows}
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 旧 362 帧引用清单（W5c，只登记不篡改）", "",
             "生成：%s｜命中 %d 处｜旧值 362 帧 → 新版 G6 上限 %d 帧" % (
                 payload["generated_at"], len(rows), NEWH3),
             "",
             "处置统计：已出片保留 %d 条／需重排 %d 条／配置类待人工确认 %d 条" % (
                 sum(1 for r in rows if r["disposal"].startswith("已出片")),
                 sum(1 for r in rows if r["disposal"].startswith("未出片")),
                 sum(1 for r in rows if r["disposal"].startswith("需"))), "",
             "| 范围 | 项目 | run_id | 文件 | 判据 | 运行状态 | 出片 | 处置 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | `%s` | %s | %s | %s | %s |" % (
            r["scope"], r.get("project", "-"), r.get("run_id", "-"),
            Path(r["path"]).name, r["kind"], r.get("run_status", "-"),
            "有" if r.get("produced_mp4") else ("—" if r["scope"] != "batch_manifest" else "无"),
            r["disposal"]))
    lines += ["", "> **口径限制**：本清单的「出片」判定与 mp4 哈希读同一批文件，"
              "`--verify` 的 0 变化只证明历史产物未被改动，**不能自证上面的处置分类是对的**；"
              "分类是否合理请人工复核。文本命中只认参数位（length/frames/帧数 近旁）的 362。",
              "", "完整字段（行号/命中项/哈希）见 `scan_362.json`。"]
    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def verify():
    """V5c-2：清单登记过的文件（**含成片本体**）哈希必须与当前盘上一致。"""
    if not JSON_OUT.is_file():
        print("没有清单，先跑扫描")
        return 2
    data = json.loads(JSON_OUT.read_text(encoding="utf-8"))
    bad = []
    checked = 0
    for r in data["rows"]:
        now = _sha(Path(r["path"]))
        checked += 1
        if r.get("sha256") and now != r["sha256"]:
            bad.append((r["path"], r["sha256"][:12], (now or "")[:12]))
        for rel, want in (r.get("media_sha256") or {}).items():
            checked += 1
            mp = Path(r["path"]).parent / rel
            got = _sha(mp)
            if want and got != want:
                bad.append((str(mp), want[:12], (got or "gone")[:12]))
    print("核对 %d 个文件（台账＋成片）｜变化 %d 个" % (checked, len(bad)))
    print("口径：%s" % (data.get("limits") or {}).get(
        "self_proving", "旧清单未记录口径说明，重跑扫描可补"))
    for p, a, b in bad:
        print("  变了：", p, a, "→", b)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="只核对清单里的哈希是否变化")
    a = ap.parse_args()
    if a.verify:
        return verify()
    rows = scan()
    payload = write_out(rows)
    print("命中 %d 处；分布 %s" % (payload["total"], payload["by_scope"]))
    print("清单 →", JSON_OUT, "/", MD_OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
