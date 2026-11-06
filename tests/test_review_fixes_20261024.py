# -*- coding: utf-8 -*-
"""10-24 第三方复查（监督方独立复跑）的验收：措辞降级两条 ＋ 可见性一条（裁定后转正向）。

B：`tech_sample: true` 的历史样片出自**旧 4 图模板**；10-24 起现役 9 图入口已有真跑
   （P6′ 9图+1视频+1音频；极值 6图+3视频+3音频），但仍须写明“不是任意组合都已跑”。
三-③：音频「≤3」我们按节点口径拆成每类各 3，属**对官方逐字行的解释**，
   要求把出处行号挂上（registry risk／代码注释／报错文案），让"是解释"这件事可 grep。

这两条都是"行文即证据"的验收，不测行为逻辑。
"""
import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
TOOLS = ENGINE.parent / "tools"
PANEL = Path(r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\custom_nodes\comfyui-entertainment-panel")
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(TOOLS))

import run_plan                                # noqa: E402
import h3_audio_policy as AP                   # noqa: E402
SNAPSHOT = Path(r"C:/Users/若水/AppData/Roaming/com.qoder.app.stable/remote-control/"
                r"sessions/1c3c6bad5acff498e47b73def0cc7b69/08df8cae259c995aae5e8ddf/"
                r"本地视频工作流审计_20261023/证据/官方_README.zh-CN.txt")

CITE = "README.zh-CN:85"


def _reg():
    return json.loads((ENGINE / "channels_registry.json").read_text(encoding="utf-8"))


def test_cited_official_line_actually_says_that():
    """先证行号不是编的：第 85 行确实是 Ref2VA 的输入规格，且音频写成**一类 ≤3 段**。"""
    assert SNAPSHOT.is_file(), "官方快照不在盘上，行号引用无从核对"
    line = SNAPSHOT.read_text(encoding="utf-8").splitlines()[84]
    assert "H3-Base-Ref2VA" in line
    assert "音频：** ≤ 3 段" in line, line[:160]
    assert "文件总数最多为 12" in line
    assert "每段 2–15 秒" in line


def test_audio_reading_citation_is_greppable_everywhere_it_matters():
    """解释必须挂出处：四处都得出现同一个可 grep 的行号标记。"""
    places = {
        "tasks._REF_CAPS 注释": (ENGINE / "tasks.py").read_text(encoding="utf-8"),
        "check_preflight 常数与文案": (TOOLS / "check_preflight.py").read_text(encoding="utf-8"),
        "registry ref2va.audio_cap_reading": json.dumps(
            _reg()["input_modes"]["modes"]["ref2va"], ensure_ascii=False),
        "registry official_unvalidated": json.dumps(
            _reg()["official_unvalidated"], ensure_ascii=False),
    }
    for name, txt in places.items():
        assert CITE in txt, f"{name} 里没挂 {CITE}"
    # 并且明写"这是解释不是逐字"，不许只留一个数字
    reg_ref = _reg()["input_modes"]["modes"]["ref2va"]["audio_cap_reading"]
    assert "不是逐字" in reg_ref, reg_ref
    assert "AW_H3_AUDIO_STRICT" in reg_ref


def test_ref2va_tech_sample_states_which_entry_was_actually_run():
    """B：边界必须写清——历史样片来自旧 4 图模板；9/3/3/12 入口 10-24 已真跑，但仍不是任意组合。"""
    ref = _reg()["input_modes"]["modes"]["ref2va"]
    assert ref["capability"]["tech_sample"] is True          # 历史样片这件事不抹掉
    basis = ref.get("tech_sample_basis") or ""
    assert "4 图" in basis, basis                           # 历史样片来自哪套入口
    assert "h3_i2v_ref2va9_api.json" in basis or "ref2va9" in basis, basis
    assert "2026-10-24" in basis and ("已真跑" in basis or "真跑" in basis), basis
    assert "任意组合" in basis or "不代表" in basis, basis


def test_audio_reading_policy_now_visible_everywhere_it_matters():
    """监督方终局那条可见性风险：用户 10-24 08:15 裁定「现在就接」⇒ 这条从"登记欠账"翻成正向验收。

    真源只有一份（tools/h3_audio_policy.py）；摘要／inspect／面板三处都必须是**转接**，
    任何一处自己再读一次环境变量就是第二真源，正是我们这几批一直在灭的东西。
    """
    default = AP.audio_reading_policy({})
    strict = AP.audio_reading_policy({"AW_H3_AUDIO_STRICT": "1"})
    assert default["reading"] == "node_per_kind_max3" and default["strict"] is False
    assert strict["reading"] == "official_one_class_max3" and strict["strict"] is True
    assert default["official_source"] == "README.zh-CN:85"

    # ① CLI/面板共用的那份计划与摘要里都要看得见
    policy = run_plan.audio_reading()
    assert policy["reading"] == default["reading"], policy
    plan = {"schema_version": 9, "identity": {"workflow": "h3_ref2va9_daily", "project": "无音"},
            "inputs": {"input_mode": "ref2va", "mode_basis": "explicit", "materials":
                       {"first_frame": None, "last_frame": None, "references": [], "ref_videos": []},
                       "template_capabilities": {"first_frame": False, "last_frame": False,
                                                 "ref_image_slots": 9}},
            "recipe": {"recipe_id": "clean20", "steps": 20, "lora": "", "lora_strength": 1.0,
                       "bunny": None, "matrix": {}},
            "geometry": {"base_width": 736, "base_height": 416, "requested_frames": 124,
                         "fps": 24, "scale": 1.0},
            "flow": {"orchestration": "single", "execution_tier": "draft", "degrade_allowed": False},
            "text": {"prompt_kind": "h3_ref2va", "source_prompt": {"sha256": "0" * 64},
                     "compile_mode": "auto"},
            "registry": {"state": "available"},
            "versions": {"template": {"path": "comfy/h3_i2v_ref2va9_nolora_api.json"}},
            "audio": policy}
    summary = run_plan.render_summary(plan)
    assert "音频" in summary and policy["label_cn"][:10] in summary, summary
    assert policy["switch"] in summary, summary          # 开关名也要在同一行里，便于日后 grep 日志

    # ② 三处都只是转接，不许自己再读 env
    src = (ENGINE / "run_plan.py").read_text(encoding="utf-8")
    for name, txt in (("run_plan.py", src),
                      ("check_preflight.py", (TOOLS / "check_preflight.py").read_text(encoding="utf-8")),
                      ("面板 __init__.py", (PANEL / "__init__.py").read_text(encoding="utf-8"))):
        assert "h3_audio_policy" in txt, name
        assert 'getenv("AW_H3_AUDIO_STRICT"' not in txt, name
        assert '.environ.get("AW_H3_AUDIO_STRICT"' not in txt, name

    # ③ 面板 spec 带下来，前端有徽标
    html = (PANEL / "web" / "index.html").read_text(encoding="utf-8")
    assert "audioBadge" in html and "s.audio_reading" in html

    # ④ registry 里那条不能再写成"欠着"
    gap = _reg()["official_unvalidated"]["items"]["audio_total_3_across_kinds"]["visibility_gap"]
    assert "已接" in gap, gap


def test_audio_reading_flows_through_the_real_inspect_path(tmp_path, monkeypatch):
    """真起一次 `run.py --inspect`：摘要那行是用户实际会看到的，不是拼给测试看的。

    两个我自己踩过的坑写在这儿，免得下次又当成引擎的问题：
    ① workflow 是**位置参数**，写成 `--workflow X` 会退 2；
    ② `text=True` 不带 `encoding="utf8"` 时，中文摘要在 gbk 解码下会被读空（rc 仍是 0），
       看着像"没输出"，其实是测试自己的解码错。
    """
    import subprocess
    prompt = tmp_path / "p.txt"
    prompt.write_text("subject_definitions: <Subject 1> a woman.\n\n"
                      "summary: [reference generation] <Subject 1> walks.\n\n"
                      "retention_analysis: <Subject 1> fully_preserved from <Picture 1>\n\n"
                      "detailed_description: [Shot 1] She turns; the camera Push In slowly.\n\n"
                      "overall_soundscape: Wind.\n\nnon_diegetic_music: N/A", encoding="utf-8")
    img = tmp_path / "r.png"
    img.write_bytes(b"\x89PNG\r\n")
    r = subprocess.run([sys.executable, "-B", "run.py", "h3_ref2va9_clean", "--inspect",
                        "--set", "prompt_file=%s" % prompt,
                        "--set", "ref_images=%s" % img],
                       capture_output=True, text=True, encoding="utf8", errors="replace",
                       cwd=str(ENGINE), timeout=240)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out[-900:]

    def _audio_line(text):
        """只取摘要里那一行「音频 …」来断言。

        整段输出里还转抄了 registry 的 decided_by 文案（含"默认节点口径"字样），
        拿整段做"不含某词"的断言必然假红——我第一版就是这么写错的。
        """
        hits = [l for l in text.splitlines() if l.strip().startswith("音频")]
        assert hits, text[-900:]
        return hits[0]

    a1 = _audio_line(out)
    assert "节点口径" in a1 and "AW_H3_AUDIO_STRICT" in a1, a1       # 默认读法一眼读得出来
    assert "README.zh-CN:85" in a1, a1
    assert "clean20" in out and "available" in out, out[-900:]      # 新建的干净档格子真走通了
    assert "h3_i2v_ref2va9_nolora_api.json" in out, out[-900:]
    # 开关拨上去，同一命令的输出必须跟着变（证明显示的不是硬编码文案）。
    # 用 monkeypatch 改父进程环境让子进程继承——比自己拼 env= 稳：拼 env 时漏掉某个系统变量
    # 会让子进程静默空输出（我在这儿踩过一次，rc 还是 0，看着像"引擎没打印"）。
    monkeypatch.setenv("AW_H3_AUDIO_STRICT", "1")
    r2 = subprocess.run([sys.executable, "-B", "run.py", "h3_ref2va9_clean", "--inspect",
                         "--set", "prompt_file=%s" % prompt,
                         "--set", "ref_images=%s" % img],
                        capture_output=True, text=True, encoding="utf8", errors="replace",
                        cwd=str(ENGINE), timeout=240)
    out2 = (r2.stdout or "") + (r2.stderr or "")
    assert r2.returncode == 0, out2[-900:]
    a2 = _audio_line(out2)
    assert "一类合计" in a2 and "节点口径" not in a2, a2            # 开关一拨，那一行跟着变
    assert "AW_H3_AUDIO_STRICT=1" in a2, a2
