# AIWorkflow — 工作流生产层（D 盘 NVMe 快盘）

> **必读规范**：任何 agent / AI 在操作本目录前，先读 **[AGENTS.md](./AGENTS.md)** —— 里面有「保存规范铁律、目录地图、具体怎么存、使用入口、扩展约定、关键坑」。本文仅作结构概览，详细约束以 AGENTS.md 为准。

本目录统一存放「生成时高频读写的」工作流资产：引擎、模型、训练、临时中间产物。
成品（图像/视频/素材）不落这里，统一交付到 **E:\图像影音资源池\**（按项目分）。

## 目录约定

```
engine\      auto-workflow 引擎（run.py / tasks.py / webui.py / config.yaml / workflows\*.yaml）
models\      模型资产（插件式：新增一类模型 = 新建一个子目录）
  ├─ comfyui\   → junction 指向 D:\Models\ComfyUI（ComfyUI 全类型模型本体，勿移动）
  ├─ tts\       语音模型（F5-TTS 等）
  └─ face\      人脸检测等
training\    训练域（插件式：按项目分）
  ├─ toolkits\  训练工具链（sd-scripts / ai-toolkit）
  ├─ datasets\<项目>\   热训练数据（当前在训的数据集）
  └─ output\<项目>\     LoRA 训练产物
tools\       辅助脚本（测试/校验/发送）
logs\        运行日志
tmp\         临时中间产物（帧/参考图缓存/ComfyUI 原始输出中转）——NVMe 保出图速度
```

## 扩展约定（新增时只做这些）

1. **新增模型类别**：`models\` 下新建子目录（如 `models\asr\`），放权重即可。
2. **新增训练项目**：`training\datasets\<项目>\` + `training\output\<项目>\` 各建一个目录。
3. **新增出图/出视频项目**：在 `E:\图像影音资源池\<项目>\` 下建 `图像/视频/素材/音频` 四子目录。
4. **ComfyUI 模型**：一律放 `D:\Models\ComfyUI\<类型>\`（junction 已接通），ComfyUI 侧符号链接会自动识别。

## 迁移留痕

本目录由 2026-09-11 工作流整理建立，来源映射见 `E:\LocalAI\_迁移MANIFEST_20260911.md`。
