# 迁移 MANIFEST（2026-09-11 工作流中心化整理）

> 本次整理：工作流模型/资产 → D:\AIWorkflow（NVMe 生产层）；成品/素材 → E:\图像影音资源池（交付层）。
> 迁移方式：跨盘=复制→校验（文件数+字节数一致）→删源；同盘=改名移动。

## D 盘热数据迁移（复制校验通过）

| 源（已删除） | 目标 |
|---|---|
| E:\LocalAI\workflows | D:\AIWorkflow\engine |
| E:\LocalAI\models\F5-TTS | D:\AIWorkflow\models\tts |
| E:\LocalAI\models\face_detection | D:\AIWorkflow\models\face |
| E:\LocalAI\sd-scripts | D:\AIWorkflow\training\toolkits\sd-scripts |
| E:\LocalAI\ai-toolkit | D:\AIWorkflow\training\toolkits\ai-toolkit |
| E:\LocalAI\lora_output\wuyin_face_v1 | D:\AIWorkflow\training\output\无音\wuyin_face_v1 |
| E:\LocalAI\wuyin_lora_faces | D:\AIWorkflow\training\datasets\无音\wuyin_lora_faces |
| E:\LocalAI\wuyin_lora_candidates | D:\AIWorkflow\training\datasets\无音\wuyin_lora_candidates |
| E:\LocalAI\wuyin_lora_faces_video_deduped | D:\AIWorkflow\training\datasets\无音\wuyin_lora_faces_video_deduped |
| E:\LocalAI\tools | D:\AIWorkflow\tools |
| E:\LocalAI\logs | D:\AIWorkflow\logs |
| E:\LocalAI\configs | D:\AIWorkflow\training\configs |
| E:\LocalAI\docs | D:\AIWorkflow\training\docs |
| E:\LocalAI\tokenizers | D:\AIWorkflow\training\tokenizers |

## E 盘成品/冷数据归档（同盘移动）

| 源 | 目标 |
|---|---|
| E:\FLUX_Workflow\out\*（106 批次，765M） | E:\图像影音资源池\无音\批次 |
| E:\FLUX_Workflow\ComfyUI_output\*（169M） | E:\图像影音资源池\无音\图像 |
| E:\LocalAI\wuyin\*.mp4 + cover | E:\图像影音资源池\无音\视频 |
| E:\LocalAI\wuyin\audio\* | E:\图像影音资源池\无音\音频 |
| E:\LocalAI\wuyin\{check,sr_test,concat_draft.txt} | E:\图像影音资源池\无音\素材\wuyin_work |
| E:\LocalAI\wuyin_videos | E:\图像影音资源池\无音\素材\wuyin_videos |
| E:\LocalAI\wuyin_lora_from_video | E:\图像影音资源池\无音\素材\wuyin_lora_from_video |
| E:\LocalAI\wuyin_lora_faces_video | E:\图像影音资源池\无音\素材\wuyin_lora_faces_video |
| E:\LocalAI\fight_src | E:\图像影音资源池\无音\素材\fight_src |
| E:\LocalAI\wuyin_frames | E:\图像影音资源池\无音\素材\wuyin_frames |
| E:\LocalAI\wuyin3 | E:\图像影音资源池\无音\素材\wuyin3 |
| E:\LocalAI\temp_frames | E:\图像影音资源池\无音\素材\temp_frames |

## 关键配置/入口已同步更新

- `D:\AIWorkflow\engine\config.yaml`：output_root → `E:\图像影音资源池\无音\批次`；output_dir/log → `D:\AIWorkflow\tmp\staging`、`D:\AIWorkflow\logs`
- `E:\LocalAI\launchers\comfyui.bat`：LOG + `--output-directory` → `D:\AIWorkflow\tmp\staging`
- `D:\AIWorkflow\training\configs\wuyin_face_lora.toml` / `asian_face_lora.toml`：output/train_data/logging 路径 → D
- `D:\AIWorkflow\tools\run_training.py` / `run_wuyin_training.py`：sd-scripts/configs/tokenizers → D
- `D:\AIWorkflow\tools\crop_faces_wuyin.py` / `dedup_faces.py` / `analyze_face_diversity.py` / `final_lora_validation.py` / `test_lora_checkpoints.py`：数据/模型/输出路径 → D/E 资源池
- `D:\AIWorkflow\models\tts\infer_line.py`：ffmpeg/ckpt/vocab → D
- `E:\LocalAI\LocalAI.ps1`：菜单 2 → `D:\AIWorkflow\engine\start-webui.bat`
- `E:\LocalAI\launchers\圣女出图一条龙.bat`：python → `D:\AIWorkflow\training\toolkits\ai-toolkit\venv_train\Scripts\python.exe`

## 未动（保持原样）

- `E:\LocalAI\ComfyUI_windows_portable`（ComfyUI 应用本体，模型经符号链接指向 D:\Models\ComfyUI）
- `D:\Models\ComfyUI`（117G 模型本体，原符号链接指向此处，新增 junction：D:\AIWorkflow\models\comfyui）
- `E:\LocalAI\backends`（llama.cpp）、`gateway`、`dev`、`workflows_backup_20260903_pre_tile_fix`（LLM/网关/备份，非出图工作流，未动）

## 已知遗留（未在本次范围，需后续处理）

- ~~圣女 pipeline（TRAE 目录）失效路径~~ → **已于 2026-09-11 修复**，详见下方「圣女 pipeline 修复记录」。

## 圣女 pipeline 修复记录（2026-09-11）

原遗留：pipeline 入口用 `ai-toolkit\venv_train`（torch 2.9.1+cpu 无 CUDA、torchvision cu128 失配、transformers 混载系统 site-packages，环境已废），yaml 引用失效 `D:\LocalAI\...`。

| 项 | 修复 |
|---|---|
| `saintess_workflow.yaml` | `style_lora`/`face_lora`(注释) → `E:\创作\训练素材\LoRA产物\saintess_*_lora_v1\`；`output_root` → `E:\图像影音资源池\圣女\批次` |
| `圣女出图一条龙.bat` | python → `C:\Users\若水\AppData\Local\Programs\Python\Python312\python.exe` |
| 系统 Python312 | 补装 `torchao 0.18.0`；`transformers 5.16.1 → 4.54.1`（匹配 diffusers 0.32.1） |
| `pipeline.py` | torchao API 适配：`float8_weight_only` → `Float8WeightOnlyConfig`（3 处） |

**验证**：`status` 跑通、依赖 import 全通（torch 2.11.0+cu128 cuda=True / torchao / transformers 4.54.1 / diffusers 0.32.1）。

**遗留 2 点**：① 系统 Python312 上 gradio 6.22.0 要求 huggingface_hub≥1.16（现 0.36.2），潜在冲突（跑 gradio 才触发）；② `lark-cli` 不在 PATH，`all` 命令发飞书环节会 FileNotFoundError（`gen`/`sheet` 不受影响），lark-cli 完整路径 `C:\Users\若水\.local\share\qoder\lark-cli\node_modules\@larksuite\cli\bin\lark-cli.exe`。
