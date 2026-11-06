# -*- coding: utf-8 -*-
# 〔为什么没人调用但**必须保留** · 2026-10-19 治理批〕
#   🔴 它不是死码，是 **R4-20 三条纪律的执行者**（2026-10-14 定妆换版事故后定的）：
#   story.json 里每处 sheet 路径必须在位、`{{Name}}` 模板引用必须同源。
#   那次事故的形状：文字描述与代词都换了，`characters[].sheet` 还指旧图
#   ⇒ 渲染端拿到“新文字＋旧参考图”，产出鱼头人身。
#   为什么被扫成孤儿：它**只报不拦、exit 恒 0**，所以没有任何链路“依赖”它——
#   这是设计，不是遗漏。归档它等于把那条事故的防线拆掉。
#   用法：`py tools\check_asset_refs.py`（改完 story.json / 换版定妆图后手动跑一次）。
#   ⚠ 待办（用户 2026-10-19 选“全留只加头注”，暂未接闸门）：将来若要接进日常自检，
#     接法＝在 `check_official_path.py` 里加一项调它并把 warn 透出来，别改它的 exit 码。
r"""资产引用一致性检查（check_asset_refs.py）· R4-20 执行者，只报不拦，exit 恒 0。

## 它为什么长这样
2026-10-14 定妆换版事故：story.json 的文字描述与代词都换了，`characters[].sheet`
仍指旧图 ⇒ 渲染端拿到"新文字+旧参考图"，产出鱼头人身。事后复盘（msb-agent-director-line）
定下的三条纪律，本脚本把机器能判的两条固化：
1. **在位**：story.json 里每一处 sheet 路径，文件必须存在；
2. **同源**：所有 `{{Name}}` 模板引用必须对得上已声明的 character/location 名字；
3. **新鲜**：sheet 文件比渲染产物新 ⇒ 缓存可能混旧版（shot 缓存键不含参考图内容，实测坑）。
判不了的第三件事——"图挂得对不对、像不像"——仍归 H2 人审，本脚本不虚报。

## 用法
    python check_asset_refs.py <story.json> [--rendered DIR]
--rendered 传渲染缓存目录时才做"新鲜度"检查（sheet mtime 晚于产物 ⇒ warn）。
输出行前缀 `R4-20`，级别 ok/warn/error；**恒 exit 0**（alarm_only，与 motion 阈值同规矩）。

## 对照（自造尺规矩）
阳性对照：把一个 sheet 改成不存在的路径 ⇒ 必须报 error。
阴性对照：现役 story.json（tmp\ai_money）⇒ 0 error。
"""
import argparse
import json
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def walk_sheets(node, json_path=""):
    """递归收集所有 key=='sheet' 的字符串路径。"""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{json_path}.{k}" if json_path else k
            if k == "sheet" and isinstance(v, str):
                out.append((p, v))
            else:
                out.extend(walk_sheets(v, p))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(walk_sheets(v, f"{json_path}[{i}]"))
    return out


def walk_tokens(node, found):
    if isinstance(node, dict):
        for v in node.values():
            walk_tokens(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_tokens(v, found)
    elif isinstance(node, str):
        for m in TOKEN_RE.finditer(node):
            found.add(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("story")
    ap.add_argument("--rendered", default=None, help="渲染缓存目录（可选，做新鲜度检查）")
    args = ap.parse_args()

    story_path = Path(args.story)
    ok = warn = err = 0
    print(f"R4-20 资产引用一致性检查 ｜ story={story_path}")
    if not story_path.is_file():
        print(f"  ✗ error  story.json 不存在：{story_path}")
        print("结论：error=1 warn=0 ok=0（只报不拦，exit 0）")
        return 0
    data = json.loads(story_path.read_text(encoding="utf-8"))

    # 1. sheet 在位
    sheets = walk_sheets(data)
    for json_path, ref in sheets:
        p = Path(ref)
        if p.is_file():
            print(f"  ✓ ok    sheet 在位  {json_path} -> {ref}")
            ok += 1
        else:
            print(f"  ✗ error sheet 缺失  {json_path} -> {ref}")
            err += 1

    # 2. {{Name}} 模板引用对得上声明
    declared = {c.get("name", "") for c in data.get("characters", [])}
    declared |= {loc.get("name", "") for loc in data.get("locations", [])}
    tokens = set()
    walk_tokens(data, tokens)
    for t in sorted(tokens):
        if t in declared:
            print(f"  ✓ ok    模板引用有主  {{{{{t}}}}}")
            ok += 1
        else:
            print(f"  ! warn  模板引用无对应声明（character/location）: {{{{{t}}}}}")
            warn += 1

    # 3. 新鲜度（仅在给了渲染目录时）
    if args.rendered:
        rdir = Path(args.rendered)
        if not rdir.is_dir():
            print(f"  ! warn  渲染目录不存在，跳过新鲜度检查：{rdir}")
            warn += 1
        else:
            products = [p for p in rdir.rglob("*") if p.is_file()]
            sheet_paths = [(jp, Path(ref)) for jp, ref in sheets if Path(ref).is_file()]
            stale_sheets = []
            for jp, sp in sheet_paths:
                sm = sp.stat().st_mtime
                newer = sum(1 for pr in products if pr.stat().st_mtime < sm)
                if newer:
                    stale_sheets.append((sp.name, newer))
            if stale_sheets:
                for name, n in stale_sheets:
                    print(f"  ! warn  sheet「{name}」比 {n} 个渲染产物新 —— "
                          f"缓存键不含参考图内容，旧渲染可能被复用（挪走缓存再渲）")
                    warn += 1
            else:
                print(f"  ✓ ok    新鲜度：{len(products)} 个渲染产物都不比任何 sheet 新")
                ok += 1

    print(f"结论：error={err} warn={warn} ok={ok}（只报不拦，exit 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
