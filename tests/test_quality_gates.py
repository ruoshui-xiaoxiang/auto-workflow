# -*- coding: utf-8 -*-
"""阶段①（质量闸门）的离线单测。不碰显存、不起 ComfyUI。"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tasks import poll_history  # noqa: E402


def test_poll_history_timeout_returns_new_staging_files(tmp_path):
    """超时但暂存区有新文件 → 按成功处理，返回新文件列表。"""
    staging = tmp_path / "staging"
    staging.mkdir()
    # 提交前快照：staging 里已有一个旧文件
    old_file = staging / "old.png"
    old_file.write_bytes(b"old")
    pre_snapshot = {old_file}

    # 模拟超时期间出现了新文件
    new_file = staging / "ComfyUI_00001_.png"
    new_file.write_bytes(b"new")

    logged = []
    ctx = {
        "cfg": {"comfyui": {"output_dir": str(staging)}},
        "log": lambda msg: logged.append(msg),
    }

    # mock requests.get 永远返回 404（history 查不到）→ 触发超时
    with patch("tasks.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404)
        with patch("tasks.time.sleep"):
            # timeout=0 让 while 循环立即退出
            result = poll_history(ctx, "http://fake:8188", "prompt-123", 0,
                                  pre_snapshot=pre_snapshot)

    assert len(result) == 1
    assert Path(result[0]).name == "ComfyUI_00001_.png"
    assert any("按成功处理" in m for m in logged)


def test_poll_history_timeout_no_new_files_raises(tmp_path):
    """超时且暂存区无新文件 → 抛 RuntimeError 含 timeout 信息。"""
    staging = tmp_path / "staging"
    staging.mkdir()
    pre_snapshot = set()

    ctx = {
        "cfg": {"comfyui": {"output_dir": str(staging)}},
        "log": lambda msg: None,
    }

    with patch("tasks.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404)
        with patch("tasks.time.sleep"):
            with pytest.raises(RuntimeError, match="超时"):
                poll_history(ctx, "http://fake:8188", "prompt-456", 0,
                             pre_snapshot=pre_snapshot)


from tasks import t_comfyui  # noqa: E402


def test_comfyui_zero_product_raises_with_prompt_id(tmp_path):
    """poll_history 返回 [] → RuntimeError 含 prompt_id，不是裸 IndexError。"""
    staging = tmp_path / "staging"
    staging.mkdir()
    batch = tmp_path / "batch"
    batch.mkdir()

    ctx = {
        "cfg": {"comfyui": {"output_dir": str(staging), "base_url": "http://fake:8188",
                            "root": str(tmp_path), "startup_timeout": 1,
                            "kill_ports_before_start": []}},
        "log": lambda msg: None,
        "wf_root": tmp_path,
        "batch_dir": batch,
        "run_id": "test_001",
    }

    # 最小工作流模板（build_graph 需要恰好 1 个 KSampler）
    fake_tpl = {
        "1": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "seed": "__SEED__", "steps": "__STEPS__",
            "cfg": "__GUIDANCE__", "sampler_name": "euler",
            "scheduler": "normal", "denoise": 1.0,
            "positive": ["3", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
        "2": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "test.safetensors"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "__PROMPT__", "clip": ["2", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": "__W__", "height": "__H__", "batch_size": 1}},
    }
    wf_file = tmp_path / "test_wf.json"
    wf_file.write_text(json.dumps(fake_tpl), encoding="utf-8")

    p = {"workflow": str(wf_file), "prompt": "a cat", "count": 1,
         "width": 64, "height": 64, "steps": 1, "guidance": 1.0,
         "timeout": 1, "stage": "draft"}

    with patch("tasks.ensure_comfyui", return_value="http://fake:8188"), \
         patch("tasks.requests.post") as mock_post, \
         patch("tasks.poll_history", return_value=[]):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"prompt_id": "pid-abc-123"})
        with pytest.raises(RuntimeError, match="pid-abc-123"):
            t_comfyui(p, ctx)


from tasks import t_refine  # noqa: E402


def test_refine_zero_product_raises_with_prompt_id(tmp_path):
    """t_refine: poll_history 返回 [] → RuntimeError 含 prompt_id。"""
    import struct, zlib

    staging = tmp_path / "staging"
    staging.mkdir()
    batch = tmp_path / "batch"
    batch.mkdir()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    # 最小合法 PNG（64x64，img_size 能读）
    def minimal_png(w=64, h=64):
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
        ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
        raw = b''
        for _ in range(h):
            raw += b'\x00' + b'\xff' * (w * 3)
        idat_data = zlib.compress(raw)
        idat_crc = zlib.crc32(b'IDAT' + idat_data) & 0xffffffff
        idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + struct.pack('>I', idat_crc)
        iend_crc = zlib.crc32(b'IEND') & 0xffffffff
        iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return sig + ihdr + idat + iend

    draft = tmp_path / "draft.png"
    draft.write_bytes(minimal_png())

    # 在 tmp_path 下创建假模板（避免 mock Path.read_text）
    tpl_dir = tmp_path / "comfy"
    tpl_dir.mkdir()
    fake_tpl = {"1": {"class_type": "LoadImage", "inputs": {"image": "__IMAGE__"}}}
    (tpl_dir / "refine_usdu_api.json").write_text(json.dumps(fake_tpl), encoding="utf-8")

    ctx = {
        "cfg": {"comfyui": {"output_dir": str(staging), "base_url": "http://fake:8188",
                            "root": str(tmp_path), "startup_timeout": 1,
                            "kill_ports_before_start": [],
                            "input_dir": str(input_dir)}},
        "log": lambda msg: None,
        "wf_root": tmp_path,
        "batch_dir": batch,
        "run_id": "test_002",
    }

    p = {"files": [str(draft)], "prompt": "enhance", "template": "comfy/refine_usdu_api.json",
         "tile": 512, "upscale_by": 2.0, "steps": 12, "denoise": 0.35,
         "guidance": 3.5, "timeout": 1, "max_tiles": 64}

    with patch("tasks.ensure_comfyui", return_value="http://fake:8188"), \
         patch("tasks.requests.post") as mock_post, \
         patch("tasks.poll_history", return_value=[]):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"prompt_id": "pid-refine-789"})
        with pytest.raises(RuntimeError, match="pid-refine-789"):
            t_refine(p, ctx)
