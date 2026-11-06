# -*- coding: utf-8 -*-
"""字幕词级时间轴对齐器（A3，2026-10-15 用户裁定并入 P0 直接入册）。

思想来源：m-bain/whisperX（24.5k★）＝ faster-whisper 转写 + wav2vec2 逐词强制对齐，
把"字幕每句卡在第几秒"从人工/峰值法升级成词级时间戳。落册条目：R8-10（20_通用规范层）。

跑法与环境（两条硬边界）：
  · 只装在**系统 Python 3.12**，不碰 ComfyUI embedded 生产环境；
  · device 固定 **cpu**（compute_type=int8）——16GB 卡常被 ComfyUI 占着，
    这里去抢显存等于给生产批次埋 OOM。

口径（R8-10）：
  · 输出 word 级 JSON（词/起止/置信度）＋可选 SRT；**只报数不做裁决**，
    最终哪句怎么卡在人审；
  · 时间戳是"对齐到音素边界"的估计值：底座是 whisper 转写＋wav2vec2 对齐模型，
    音乐垫底/多声叠话时置信度会掉，读词时先看 score；
  · 本工具不烧字幕（烧字幕是 R8-08 的事），只供字幕时间轴取数。

用法：
  python subtitle_align.py <媒体文件或wav> [--model small] [--srt out.srt] [--json out.json]
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = r"D:\AIWorkflow\tools\ffmpeg.exe"


def _extract_wav16k(media: Path) -> Path:
    """统一抽成 16k 单声道 wav（whisperX 的输入口径）。已是 wav 也重编码，避免采样率错配。"""
    out = Path(tempfile.mkdtemp(prefix="subalign_")) / "audio16k.wav"
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(media),
           "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"抽音频失败 code={r.returncode}: {(r.stderr or '')[-400:]}")
    return out


def _fmt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_to_srt(words, path: Path, group_gap=0.6, max_chars=20):
    """词→行的朴素成组：间隔>0.6s 或累计超20字符就切一行。字幕行最终怎么分由人审定。"""
    lines, cur, t0 = [], [], None
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > group_gap
                    or sum(len(x["word"].strip()) for x in cur) + len(w["word"]) > max_chars):
            lines.append((t0, cur[-1]["end"], "".join(x["word"] for x in cur)))
            cur, t0 = [], None
        if t0 is None:
            t0 = w["start"]
        cur.append(w)
    if cur:
        lines.append((t0, cur[-1]["end"], "".join(x["word"] for x in cur)))
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(lines, 1):
            f.write(f"{i}\n{_fmt_ts(a)} --> {_fmt_ts(b)}\n{text.strip()}\n\n")


def main():
    ap = argparse.ArgumentParser(description="whisperX 词级字幕时间轴（R8-10，只报数不裁决）")
    ap.add_argument("media", help="音频或视频文件")
    ap.add_argument("--model", default="small", help="whisper 转写模型（tiny/base/small/medium）")
    ap.add_argument("--json", dest="json_out", default=None, help="词级结果 JSON 输出路径")
    ap.add_argument("--srt", dest="srt_out", default=None, help="SRT 输出路径（可选）")
    ap.add_argument("--language", default=None, help="强制语言（默认自动检测）")
    args = ap.parse_args()

    media = Path(args.media)
    if not media.is_file():
        print(f"[error] 文件不存在: {media}")
        return 2
    if not Path(FFMPEG).is_file():
        print(f"[error] ffmpeg 不存在: {FFMPEG}")
        return 2

    print("R8-10 词级字幕时间轴 ｜ 口径：whisperX(faster-whisper+wav2vec2) / cpu int8 / 只报数不裁决")
    wav = _extract_wav16k(media)

    try:
        import torch
        # whisperx.load_audio 内部裸调 ffmpeg 子进程（不吃本脚本的 FFMPEG 常量），
        # PATH 里没有 ffmpeg 会 WinError 2 —— 把 tools\ffmpeg.exe 所在目录顶到 PATH 前面。
        import os
        os.environ["PATH"] = str(Path(FFMPEG).parent) + os.pathsep + os.environ.get("PATH", "")
        import whisperx
    except ImportError:
        print("[error] whisperx 未安装（只装在系统 3.12；pip install whisperx，见 R8-10）")
        return 2

    device = "cpu"
    try:
        audio = whisperx.load_audio(str(wav))
        asr = whisperx.load_model(args.model, device, compute_type="int8",
                                  language=args.language)
        result = asr.transcribe(audio, batch_size=16)
        lang = result.get("language") or "zh"
        print(f"[asr] 语言={lang}  假设句数={len(result.get('segments') or [])}")
        align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
        result = whisperx.align(result["segments"], align_model, meta, audio,
                                device=device, return_char_alignments=False)
    except Exception as e:
        print(f"[error] 对齐失败: {type(e).__name__}: {str(e)[:400]}")
        return 2

    words = []
    for seg in result.get("segments") or []:
        for w in seg.get("words") or []:
            words.append({"start": round(float(w["start"]), 3),
                          "end": round(float(w["end"]), 3),
                          "word": str(w["word"]),
                          "score": round(float(w.get("score") or 0), 3)})
    words.sort(key=lambda x: x["start"])

    payload = {
        "tool": "subtitle_align.py", "rule": "R8-10", "media": str(media),
        "asr_model": args.model, "language": lang, "device": device,
        "word_count": len(words), "words": words,
        "口径": "词级时间戳＝转写+wav2vec2强制对齐的估计值；低score处先怀疑音乐垫底/叠话；只报数，卡点人审",
    }
    json_out = Path(args.json_out) if args.json_out else media.with_suffix(media.suffix + ".words.json")
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {len(words)} 词 -> {json_out}")

    if args.srt_out:
        _words_to_srt(words, Path(args.srt_out))
        print(f"[out] SRT -> {args.srt_out}")

    if words:
        lo = min(w["score"] for w in words)
        avg = sum(w["score"] for w in words) / len(words)
        print(f"[score] min={lo:.2f} avg={avg:.2f}（音乐垫底段的词分会掉，读时间轴先看它）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
