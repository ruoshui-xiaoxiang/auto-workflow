---
name: reference-bailian-tts
description: 百炼 TTS 双通道边界——token-plan 网关只有 qwen 系 TTS（无 cosyvoice、无 ASR）；**按量付费 dashscope key（E:\密钥文件\阿里多模态.txt）才有 cosyvoice-v2**；instruction/rate 变声实测+语速字数换算+变老天花板（→本地 F5-TTS 克隆）；混音 adelay 分号/alimiter 坑
metadata:
  type: reference
---

百炼 token-plan 账号 TTS 实测可用方法（2026-09-07，《无音》配音验证）。

**bl CLI 的 TTS 不可用**：`bl speech synthesize` 默认及所有模型名（cosyvoice-v2/v3-flash/v3-plus/v3.5-flash/qwen-tts）在 token-plan 网关全报 `Model not exist`；`--list-voices` 各模型清单与实际可用性不符。TTS 需直调 REST（文档：token-plan-guide/token-plan-best-practice/token-plan-multimodal-gen.md，本机 bailian-docs-llm-wiki skill 内）。

**token-plan 网关能力边界（2026-09-07 补测；⚠️ 2026-09-23 起该网关 key 已 401，见 [[project-cloud-channel-401]]）**：
- **只有 qwen 系模型**。cosyvoice-v3-flash（含 longshu_v2/longlaotie_v2/longyuan_v2 等音色）报 `Model not exist`——**token-plan 网关上**别再试 cosyvoice 音色库；但**按量付费 dashscope key 上 cosyvoice-v2 可用**（见文末 2026-09-23 段），两个网关能力不同，别混记。
- `longlaobo_v3` 在 qwen-audio-3.0-tts-plus 上**不存在**（最简 payload 也 411）。
- **网关没有任何 ASR**：bl speech recognize（fun-asr-flash）上传策略 401 InvalidApiKey；OpenAI 兼容 `/compatible-mode/v1/audio/transcriptions`（qwen3-asr-flash）也 `Model not exist`。要 ASR 用本地 faster-whisper（系统 Python312 已装 1.2.1）。

**调用配方**：
- `POST https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer`，Bearer key 在 `C:\Users\若水\.bailian\config.json` 的 `.["token-plan"].api_key`（勿回显）。
- Body：`{"model":"qwen-audio-3.0-tts-plus","input":{"text":"...","voice":"...","instruction":"...","format":"mp3","sample_rate":24000,"rate":1.05}}`
- **坑：中文 payload 必须写进 UTF-8 JSON 文件用 `--data-binary @file` 发**；curl -d 内联中文在 git-bash 会编码坏掉，报引擎 411/文字无效（曾误判为音色不存在）。
- 响应 JSON 含 `output.audio.url`（OSS 临时直链），再 curl 下载 mp3。
- 价格 ¥1.4/万字符（plus），本次 5 句几乎免费。

**qwen-audio-3.0-tts-plus 实测音色**（flash 模型 token-plan 上不存在）：
- 可用：`longanlufeng`（明亮男 25）、`longanlingxin`（知心温暖女 25）、`longanhuan_v3.6`（欢脱女，文档默认）。其余 long*_v3/_v3.6 族全报 411。
- **instruction 自由指令有效**（≤100 字符）：可指定年龄/性别/情感（如「用七十岁苍老沙哑的乡村老汉声音说话」「用五岁小女孩软糯童声」「清冷疏离的御姐音」），同一底色可变声。
- `rate` 加在 input 内有效（1.05→9.89s，1.2→8.66s）。
- **语速字数换算（排台词窗口用）**：longanlingxin+五岁童声指令 rate 1.05 ≈ **3.7 字/秒**（10字→2.73s、12字→3.09s、16字→4.48s）。排台词时先量窗口秒数，按 ~3.5 字/s 报"上限字数"给用户；超字数只能提前起点或提速（提速会显急）。
- **变老诀窍与其天花板（2026-09-07 老药农多轮被打回"太年轻"的教训）**：instruction 里的中性词（如「朴实」「随口应答」）会稀释老态——指令要全往老上压：「八十岁」「苍老沙哑」「气短」「牙齿漏风」「沙哑带痰」「干瘦佝偻」，rate 降到 0.8~0.85；文本插省略号（「姑娘……稍候」）可强制一字一顿。**但天花板实测**：指令全压老 + rate 0.8 + 顿点 + ffmpeg 降调 -18%（`asetrate=19680,aresample=24000,atempo=1.2195`，时长不变）四管齐下，用户仍判"压不住年轻感"——**老人声别再在 qwen TTS 上耗，直接本地 F5-TTS zero-shot 克隆真实老人参考音频**（安装走代理官方 PyPI，见 [[reference-cn-download-mirrors]]）。
- 无老人/童声系统音色，全靠 instruction 变身；qwen-audio-tts 音色表：help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list。
- **环境坑**：会话恢复后 git-bash 里 node 常不在 PATH → 用 `"$LOCALAPPDATA/nodejs/node.exe"`；`$TEMP` 可能解析错（变 C:/Temp）→ 用 `"$LOCALAPPDATA/Temp"`。

相关：[[reference-ai-pricing]]、[[reference-kling-cli]]、[[reference-cn-download-mirrors]]

### 按量付费 key 的 TTS 正确姿势（2026-09-23 实测，token-plan 401 后切换）
- key 在 `E:\密钥文件\阿里多模态.txt`（两把 `sk-ws-` 开头＋compatible-mode base URL）；chat（qwen-plus）200 有效。
- **TTS 只能用 cosyvoice-v2**：`POST https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer`，body `{"model":"cosyvoice-v2","input":{"text","voice","format":"mp3","sample_rate":24000}}`，响应 `output.audio.url` 再下载。**qwen-tts 在这把 key 下 native/compatible 两条路都 400/404，别再试**。
- 可用男声实测：longshu_v2（沉稳播音）、longcheng_v2（低沉）、longnan_v2（青年）、longze_v2。《仙女星系》用 旁白=longshu_v2／指挥=longcheng_v2／雷达=longnan_v2。
- 混音坑：多路 adelay 链在 `-filter_complex` 里必须**分号**连接（空格会静默失败）；amix normalize=0 后峰值会顶 0dB，**末尾加 alimiter=limit=0.94**。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- **双通道**：token-plan 网关只有 qwen 系且 key 已 401
- qwen-tts 在该 key 下 400/404 别试
- 中文 payload 走 JSON 文件
- 变老天花板→本地 F5-TTS
- 混音 adelay 须分号＋末尾 alimiter
