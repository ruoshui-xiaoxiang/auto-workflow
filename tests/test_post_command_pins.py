# -*- coding: utf-8 -*-
"""R8「写法类」三条的防回归钉（2026-10-03 用户裁：只接写法类，绝对量级不接）。

为什么这几条可以**今天就钉**、而响度那类不行：钉的是**我们自己拼出来的 ffmpeg 命令**，
是硬事实（挂没挂 fps filter、有没有用 `-c copy`、`amix` 带没带 `normalize`），
不存在"换项目就失效"。而 10-03 实测现役命令**零违例**（`fps=` 0 处、`-c copy` 0 处、
`amix` 0 处＝混音链还没进引擎），所以这批**不新增任何拦停**——它只保证"以后有人改坏了会被抓"。

量过的对照（写在这里，别把测试读成"已经在拦东西"）：
  R8-05 拼片重编码／不许 `-shortest`  → 现役命令里 0 处违例 ⇒ 钉成用例
  R8-06 不挂 fps filter（挂上 124→123）→ 同上
  R8-03 `amix` 必须显式 `normalize`   → 引擎里根本没有 `amix`（能力未固化）⇒ 钉成 lint，
                                        将来写混音链那天自动生效
  R8-05 收尾逐帧计数                  → 代码原本**只解码不数帧**（`frames` 取自容器 `nb_frames`，
                                        正是"容器会撒谎"那个东西）⇒ 本轮补上从解码趟收 `frame=`，
                                        但**只留痕不拦**（没标定过容差就没资格 error）。
"""
import ast
import io
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # engine/
sys.path.insert(0, str(ROOT))
import tasks as T                                      # noqa: E402

FFMPEG = r"D:/fake/ffmpeg.exe"
FFPROBE = r"D:/fake/ffprobe.exe"
# 10-03 裁定之后，尺寸**没有代码兜底**：调拼命令的函数必须自己给。
# 这里给的是测试用尺寸，故意**不**和项目里的任何生产尺寸相同——
# 免得哪天有人把测试值当"事实"抄回配置里。
SIZE = {"width": 720, "height": 1280}


class Rec:
    """把 `_run_media` 换成记录器：命令照拼、进程不起。"""

    def __init__(self, stderr=""):
        self.cmds = []
        self.stderr = stderr

    def __call__(self, cmd, timeout=1800):
        self.cmds.append([str(x) for x in cmd])

        class P:
            returncode = 0
            stdout = "{}"

            def __init__(self, err):
                self.stderr = err

        return P(self.stderr)

    def flat(self):
        return [" ".join(c) for c in self.cmds]


def _ctx(tmp_path):
    return {"cfg": {"media_tools": {"ffmpeg": FFMPEG, "ffprobe": FFPROBE}},
            "log": lambda m: None}


@pytest.fixture
def media(monkeypatch):
    rec = Rec()
    monkeypatch.setattr(T, "_media_tools", lambda ctx: (FFMPEG, FFPROBE))
    monkeypatch.setattr(T, "_run_media", rec)
    return rec


# ── R8-06：不挂 fps filter ───────────────────────────────────────
def test_normalize_does_not_mount_fps_filter(media, tmp_path):
    T._normalize_clip("a.mp4", tmp_path / "b.mp4", _ctx(tmp_path), **SIZE)
    assert media.cmds, "根本没拼出命令 ⇒ 这条测试是空跑的"
    cmd = media.flat()[0]
    assert "fps=" not in cmd, "fps filter 又挂回去了：124→123 掉帧那条老坑（R8-06）"
    assert "-r " not in cmd and "-r" not in [t for t in media.cmds[0] if t == "-r"], \
        "归一化命令里出现了 -r（等价于重设帧率，同 R8-06）"


def test_normalize_refuses_to_invent_a_size(media, tmp_path):
    """10-03 裁定「删除硬编码，全部强制要求显式配置」：没给尺寸必须**报错**，
       不许悄悄出一个 1920x1080 —— 那种"没配置"和"配成那个数"长得一样的产物最难查。"""
    with pytest.raises(RuntimeError) as e:
        T._normalize_clip("a.mp4", tmp_path / "b.mp4", _ctx(tmp_path))
    assert "显式" in str(e.value)
    assert not media.cmds, "报错了还照样拼命令 ⇒ 兜底没删干净"


def test_normalize_pins_the_ruling_of_2026_10_03(media, tmp_path):
    """钉住「编码参数以代码为 authority」那次裁定的现役值（10-03 逐题）。

    记忆里曾写 `-crf 16 -ar 44100`，那已被裁为**旧写法**；这里把现役值钉死，
    下次谁照旧记忆去改代码，测试会红——而不是两份文档各说各话。
    """
    T._normalize_clip("a.mp4", tmp_path / "b.mp4", _ctx(tmp_path), **SIZE)
    cmd = media.flat()[0]
    assert "-crf 18" in cmd, cmd
    assert "-ar 48000" in cmd, cmd
    assert "-crf 16" not in cmd and "44100" not in cmd, "照旧记忆改回去了？裁定是代码为准"


# ── R8-05：拼片重编码、不许 -c copy、不许 -shortest ───────────────
def test_concat_reencodes_and_never_stream_copies(media, tmp_path):
    T._concat_clips([tmp_path / "c1.mp4", tmp_path / "c2.mp4"], tmp_path / "all.mp4",
                    _ctx(tmp_path))
    cmd = media.flat()[-1]
    assert "copy" not in cmd, "拼片用了 -c copy（R8-05：时间戳会漂，ffprobe 会报 23.6fps 那种假值）"
    assert "libx264" in cmd, cmd
    assert "-shortest" not in cmd, \
        "等长拼接挂 -shortest 会削掉末尾一帧（R8-05）；真要截断必须显式按长度差决定"


def test_no_shortest_or_fps_anywhere_in_post_command_builders():
    """整段函数体的字符串常量都扫——**不看注释**（注释里出现 `fps=` 不算违例，
    本项目有过"探针被我写的说明文字污染"的账，所以走 ast 不走全文 grep）。"""
    # 2026-10-19 修：tasks.py 带 UTF-8 BOM，用 encoding="utf-8" 读会把 U+FEFF 当正文字符，
    # 后面 compile/解析当场 SyntaxError ⇒ 本条其实**一直没真扫到 tasks.py**（假绿比假红坏）。
    src = io.open(ROOT / "tasks.py", encoding="utf-8-sig").read()
    tree = ast.parse(src)
    want = {"_normalize_clip", "_concat_clips"}
    found = 0
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in want:
            found += 1
            strs = [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            # 丢掉 docstring（如果第一句是裸字符串）：说明文字里出现 `fps=` 不算违例
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str) and strs and strs[0] == first.value.value:
                strs = strs[1:]
            blob = " | ".join(strs)
            for bad in ("fps=", "-shortest", "copy"):
                assert bad not in blob, "%s 的字符串里出现了 %r" % (node.name, bad)
    assert found == 2, "两个拼命令的函数只找到 %d 个 ⇒ 函数改名了，这条测试已经空跑" % found


# ── R8-03：将来写混音链时，amix 必须显式 normalize ────────────────
def _amix_violations(text):
    """纯函数：给一段源码文本，返回「出现 amix 却没带 normalize」的字符串常量。"""
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "amix" in node.value and "normalize" not in node.value:
                out.append(node.value[:60])
    return out


def test_amix_lint_is_clean_today_and_would_catch_tomorrow():
    roots = [ROOT, ROOT.parent / "tools"]
    scanned, hits = 0, []
    for r in roots:
        for p in sorted(r.glob("*.py")):
            scanned += 1
            hits += _amix_violations(io.open(p, encoding="utf-8-sig").read())
    assert scanned > 10, "只扫到 %d 个文件 ⇒ 目录写错了，别信这张绿" % scanned
    assert not hits, "混音链写进引擎却忘了显式 normalize：%s" % hits[:3]
    # 反向验证：这条 lint 不是永远绿的摆设
    bad = 'x = ["-filter_complex", "amix=inputs=2:duration=longest"]'
    assert _amix_violations(bad) == ["amix=inputs=2:duration=longest"], "lint 失效"
    good = 'x = ["amix=inputs=2:normalize=0"]'
    assert not _amix_violations(good), "lint 误伤写法正确的"


# ── R8-05 后半：逐帧计数，只留痕不拦 ─────────────────────────────
def _fake_probe(monkeypatch, nb_frames, decoded, duration="5.17"):
    streams = {"codec_type": "video", "width": 720, "height": 1280,
               "r_frame_rate": "24/1", "avg_frame_rate": "24/1",
               "codec_name": "h264", "duration": duration}
    if nb_frames is not None:
        streams["nb_frames"] = str(nb_frames)
    info = {"streams": [streams, {"codec_type": "audio", "codec_name": "aac",
                                  "sample_rate": "48000", "channels": 2}],
            "format": {"duration": duration}}

    def runner(cmd, timeout=1800):
        class P:
            returncode = 0
            stdout = json.dumps(info)
            stderr = "frame=%5d fps=  0 q=0.0 size=N/A time=00:00:05.17" % decoded
        return P()

    monkeypatch.setattr(T, "_media_tools", lambda ctx: (FFMPEG, FFPROBE))
    monkeypatch.setattr(T, "_run_media", runner)


def test_frame_count_comes_from_decode_not_container(monkeypatch, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"0" * 2048)
    # 容器压根没给 nb_frames（真实世界常见）：以前这条就报 frames=0，现在解码实数补上
    _fake_probe(monkeypatch, None, 124)
    meta = T.probe_video(f, _ctx(tmp_path), decode=True)
    assert meta["frames_decoded"] == 124, meta
    assert meta.get("frames", 0) == 0, "容器本来就没数，别把它当有"


def test_container_lie_is_recorded_but_does_not_block(monkeypatch, tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"0" * 2048)
    _fake_probe(monkeypatch, 123, 124)          # 容器说 123，解码实数 124
    meta = T.probe_video(f, _ctx(tmp_path), decode=True)
    dis = meta.get("frames_container_disagrees")
    assert dis == {"container": 123, "decoded": 124}, meta
    # 关键是**不抛**：容差没标定过，没资格拦（与"绝对带只报不拦"同一条口径）
    lines = []
    ctx = _ctx(tmp_path)
    ctx["log"] = lines.append
    monkeypatch.setattr(T, "_media_tools", lambda c: (FFMPEG, FFPROBE))
    out = T._video_qc(f, ctx, require_audio=True, expected_fps=24.0)
    assert out["qc_passed"] is True, "留痕项把批拦住了——不该"
    assert any("R8-05" in l and "不拦" in l for l in lines), lines


def test_video_qc_still_hard_fails_on_real_defects(monkeypatch, tmp_path):
    """反向自证：上面那条"不拦"没把原有硬门一起放松（没音轨仍必须停）。"""
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"0" * 2048)
    _fake_probe(monkeypatch, 124, 124)
    ctx = _ctx(tmp_path)
    ctx["log"] = lambda m: None
    # 把音频流抹掉 ⇒ 应该抛
    real = T.probe_video
    monkeypatch.setattr(T, "probe_video", lambda p, c, decode=False: dict(
        real(p, c, decode=decode), has_audio=False))
    with pytest.raises(RuntimeError):
        T._video_qc(f, ctx)
