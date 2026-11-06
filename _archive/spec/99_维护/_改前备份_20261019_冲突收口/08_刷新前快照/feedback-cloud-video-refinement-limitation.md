---
name: feedback-cloud-video-refinement-limitation
description: 云端 AI 视频平台没有成熟的视频精修/风格化功能，video-to-video 只能本地 ComfyUI AnimateDiff
metadata:
  type: feedback
---

**云端 AI 视频平台（2026-09 实测）只有文生图/图生图/图生视频，没有视频精修/风格化功能。**

**Why:** 用户问能否"本地粗片 + 云端精修"，实测发现即梦/可灵/海螺/Vidu 都只有 T2I/I2I/I2V/T2V，没有 video-to-video 风格化。计算成本高 + 时序一致性难保证 + 商业模式不划算。

**How to apply:** 
- 视频风格化（video-to-video）只能走本地 ComfyUI + AnimateDiff
- 云端只做：超分（Topaz/Real-ESRGAN）、调色（DaVinci）、字幕
- 用户偏好：本地 3D 保证一致性（承重墙），云端只做后处理
- 选型时别被发布会宣传词误导，实测为准

**相关**：[[reference-ark-account]]（火山方舟 Seedance 状态）、[[reference-dreamina-cli]]（即梦能力边界）
