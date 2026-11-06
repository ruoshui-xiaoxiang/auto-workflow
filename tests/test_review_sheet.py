# -*- coding: utf-8 -*-
"""呈审包工具的冒烟测试：编号必须连续且与文件名对得上，短片必须真能生成。

这个工具是 H4/H2 人工关口的呈审面（关口默认不走飞书后，素材就在会话里审），
编号错一位就等于让他挑错一条，所以值得有个测试钉住。
"""
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

TOOL = Path(r"D:\AIWorkflow\tools\make_review_sheet.py")


def _clip(path: Path, color, seconds=0.5, shift=False):
    fps, n = 24, int(0.5 * 24)
    path.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (240, 160))
    assert vw.isOpened()
    for i in range(n):
        fr = np.full((160, 240, 3), color, np.uint8)
        x = (i * (6 if shift else 2)) % 200
        cv2.rectangle(fr, (x, 40), (x + 40, 120), (255, 255, 255), -1)
        vw.write(fr)
    vw.release()


def test_review_sheet_numbers_and_outputs(tmp_path):
    a, b = tmp_path / "cand_A.mp4", tmp_path / "cand_B.mp4"
    _clip(a, (30, 30, 30))
    _clip(b, (90, 90, 90), shift=True)
    out = f"t_{tmp_path.name.replace('-', '_')}"
    r = subprocess.run([sys.executable, str(TOOL), "--files", f"{a},{b}",
                        "--labels", "甲,乙", "--clip", "0.4", "--height", "200",
                        "--out-name", out],
                       capture_output=True, text=True, encoding="utf8", errors="replace")
    assert r.returncode == 0, r.stdout + (r.stderr or "")
    o = Path(r"D:\AIWorkflow\tmp\review") / out
    grid = o / "grid.png"
    clip = o / "clip.mp4"
    assert grid.is_file() and clip.is_file()
    img = cv2.imdecode(np.fromfile(str(grid), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape[0] >= 200, "静帧表没拼出来"

    nums = [int(x) for x in
            re.findall(r"^\s*(\d+) = cand_[AB]\.mp4", r.stdout, re.M)]
    assert nums == [1, 2, 3, 4, 5, 6], f"编号不连续/不对：{nums}"
    assert "甲" in r.stdout and "乙" in r.stdout and "取帧" in r.stdout
    cap = cv2.VideoCapture(str(clip))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    cap.release()
    assert frames >= 6, f"并排短片太短：{frames} 帧"
    cell_w = int(200 * 9 / 16)                 # 工具按 --height 9:16 折算每列宽
    assert w == cell_w * 2, f"并排短片应是两条同高并排：期望 {cell_w*2}，实得 {w}"
