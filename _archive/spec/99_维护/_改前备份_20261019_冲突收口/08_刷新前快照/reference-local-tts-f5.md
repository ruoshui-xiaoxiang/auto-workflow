---
name: reference-local-tts-f5
description: 本地 F5-TTS 零样本声音克隆——安装/模型位置/调用配方/ref_text 要求；云端 TTS 变老天花板被实测否决后的定案方案
metadata:
  type: reference
---

本地 F5-TTS 零样本声音克隆（2026-09-07 为《无音》老药农配音搭建，可复用）。

- **定位**：云端 TTS（[[reference-bailian-tts]]）音色库只有 3 个底色、instruction 变老+降调均被用户否决后的定案——给 5~12s 真人参考音频 + 其逐字文本，克隆该音色念任意台词，年龄感/颗粒感由参考音频本身保证。
- **环境**：系统 Python312（绝对路径调用，见 [[user-research-ai-profile]]）。f5-tts 阿里 PyPI 源缺包 → `pip install f5-tts --proxy http://127.0.0.1:7890`（官方源）；**装前必须 `pip install --dry-run` 确认不动 torch**（torch 2.11.0+cu128 不许动），f5-tts 实测 torch already satisfied，只附装 torchaudio 2.11.0 CPU 轮（音频 IO 用，无冲突）。
- **模型**：`E:\LocalAI\models\F5-TTS\model_1250000.safetensors`（1.35GB）+ `vocab.txt`（13.8KB），2026-09-07 已下完验证（官方 `SWivid/F5-TTS` 的 `F5TTS_v1_Base/`，经 hf-mirror resolve 直拉；下完 ls 验证 >1GB，防 15 字节 "Entry not found" 占位，坑见 [[reference-cn-download-mirrors]]）。
- **调用**：`from f5_tts.api import F5TTS; f5 = F5TTS(model="F5TTS_v1_Base", ckpt_file="<ckpt路径>", vocab_file="<vocab路径>")` → `f5.infer(ref_audio, ref_text, gen_text, ...)`。**ref_text 必须与参考音频逐字一致**，用已装的 faster-whisper 1.2.1 自动转写再人工校。
- **一键脚本（已备好）**：`E:\LocalAI\models\F5-TTS\infer_line.py` —— `python infer_line.py --ref <参考音频> --ref-text "<逐字文本>" --text "<台词>" --out out.wav --speed 1.0`；ckpt/vocab 路径已硬编码；`--ref-text` 留空则自动跑 faster-whisper small 转写（内部设 HF_ENDPOINT=hf-mirror），转写为空会报错退出要求手填。
- **参考音源挑选法**：真人录音按 0.5s 窗 RMS 能量峰值定位突出人声段，ffmpeg 切 8s 候选给用户试听选定（市集录音挖老汉吆喝=最贴古装人设；Pixabay 真人 clip 兜底）。5060 Ti 上生成 3s 台词为秒级。

相关：[[reference-bailian-tts]]、[[reference-cn-download-mirrors]]

## 2026-09-30 补：改 AI 片台词＝后期配音这条路（本机已跑通，零成本）

- **AI 视频里的人声是生成时就烧进音轨的，改词只能重跑**；不重跑的替代＝在台词窗内**压低原声＋叠 TTS**。
- **时间窗别估**：`faster-whisper 1.2.1`（`small`／cpu／int8，几秒音频秒出）带 `word_timestamps=True` 逐字量。
  实测同一条分镜两条片子台词位置不同：云端 13.28–14.94 s、本地 H3 12.84–14.80 s。
- **edge-tts 7.2.8 本机可用**（免密钥、走网络）：`zh-CN-YunjianNeural` 出粗嗓男声正常；
  `zh-CN-YunxiNeural` 直接 `NoAudioReceived`（别指望它）。参数 `--rate="-12%" --pitch="-6Hz"`，
  出片后用 `silenceremove` 两头掐静音（"我还会回来的" 2.57s → 1.315s），再 `atempo=0.9` 放慢半档更像放狠话。
- **做法**：numpy 里把原声在台词窗（含 0.35s 余量）线性压到 **0.22**（60ms 斜坡），TTS 归一化到峰值 0.62 叠在窗口起点。
- 🔴 **硬限制**：人声与打击音效在同一条轨上，**没有分离就没法只去掉人声** ⇒ 被压低的原台词仍会漏出尾字（实测本地条结尾"碰我"约 −13 dB 可闻）。要干净只能重跑生成。
