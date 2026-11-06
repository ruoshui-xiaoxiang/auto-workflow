# MiniMax H3 本地出片环境 · 版本记录

> 最后更新：2026-10-26
> 维护约定：每次升级更新「当前快照」，并在「历史」追加一条。数字以 `/system_stats`、各包 `pyproject.toml`、盘上文件为准，不写推断值。
> 注意：本文件是**版本状态的记录**，不是使用规范；**入口与授权规则以 `AGENTS.md` / `官方路径.json` 为准**。
> `使用规范_用前必读.md` 已于 2026-10-24 按现行环境全面修订（0.42.1／`--use-ck-attention`／T8 1.101.0／kitchen 0.2.39；正式入口 `engine/run.py`）。
> 历史 09-13 版本只作存档；配方/参数解释以该文为准，入口与授权以上一行两处真源为准。

---

## 当前快照（2026-10-21）

### 运行时

| 项 | 值 |
|---|---|
| ComfyUI | **0.42.1** |
| comfyui-frontend-package | 1.55.18 |
| comfyui-workflow-templates | 0.11.89 |
| comfyui-embedded-docs | 0.5.14 |
| comfy-kitchen | 0.2.39 |
| comfy-aimdo | 0.5.6 |
| Python | 3.13.14 |
| PyTorch | 2.13.0+cu130 |
| 运行时注册节点数 | 2323 |
| xformers | 已卸载（原 0.0.35 与 torch 2.13/Py3.13 不匹配） |

### 启动方式

```
D:\AIWorkflow\ComfyUI_H3\run_H3_ComfyUI.bat
python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build \
  --use-ck-attention --port 8189 \
  --output-directory D:\AIWorkflow\ComfyUI_H3\output --reserve-vram 6.0
```

端口 8189；输出目录 `D:\AIWorkflow\ComfyUI_H3\output\`；模型根 `D:\Models\ComfyUI\`（ComfyUI/models 下全部为 junction）。

### 自定义节点

| 包 | 版本 | 备注 |
|---|---|---|
| ComfyUI-KJNodes | **1.5.3** | 含 MiniMax H3 VRAM Attention / Preview Override 修复 |
| comfyui-minimax-h3-audio-T8 | **1.101.0** | 工作树版本；其 `.git` 仍停在 1.94，不要用 git 判断版本 |
| comfyui_controlnet_aux | 1.1.6 | 上游 main 2026-10-11 |
| Hawk-Minimax-H3-Directory | 0.1.0 | 上游 main 2026-10-16 |
| h3-attention | 0.1.0 | 上游 main 2026-10-20；**当前无画布使用其节点** |
| MinimaxStoryBuilder | 0.1.0 | 装于 2026-10-14，无上游仓库记录 |
| ComfyUI-Manager | 3.42 | 上游已迁至 Comfy-Org/ComfyUI-Manager |
| ComfyUI-Impact-Pack | 8.28.3 | 上游最新；其 JS 仍用旧前端 API，启动有 legacy 警告 |
| 其余（IPAdapter、SAM、facerestore、UltimateSDUpscale、Impact-Subpack） | — | 本地已与上游最新一致 |

### 关键模型（`D:\Models\ComfyUI`）

| 文件 | 位置 | 大小 |
|---|---|---|
| minimax_h3_ref2va_pruned_int8_convrot.safetensors | diffusion_models | 20G |
| qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors | text_encoders | 15G |
| minimax_h3_video_vae_fp16.safetensors | vae | 4.9G |
| minimax_h3_audio_vae_fp32.safetensors | vae | 578M |
| qwen_image_vae.safetensors（含 `vae/Qwen/` 硬链接） | vae | 243M |
| taeh3.safetensors | vae_approx | 22M |

### 工作流画布（`user/default/workflows`）

A01（单镜 FL2VA）、B01–B05（Hawk 多段）、C01（MSB 逐镜主用）、D01/D02（R11 接力），共 **9 个 H3 画布**。2026-10-21 复验：全部 `missing=0`、红节点 0。
2026-10-26 新增 **生图/E01_文生图_ZImageTurbo_1MP.json** 与 **生图/E02_图生图_ZImageTurbo.json**（Z-Image-Turbo UI 画布，11/12 节点；结构校验 0 错，**未做 UI 实际打开验收**；图生图的源图在 E02 的 LoadImage 节点里点「选择文件上传」；正式批量仍走 `run.py image_draft_batch` / `image_i2i`）。

另有 6 个 API 格式 JSON 放在 `娱乐流/API格式_非画布_先看这个说明/`，不是画布。

归档：`user/default/workflows_archive/`（C02 Krea2 缺件线、C01 旧备份；见该目录 `MANIFEST.md`）。

---

## 2026-10-21 升级记录

### 版本变化

| 组件 | 升级前 | 升级后 |
|---|---|---|
| ComfyUI | 0.39.0 | 0.42.1 |
| frontend | 1.53.10 | 1.55.18 |
| workflow-templates | 0.11.76 | 0.11.89 |
| comfy-kitchen | 0.2.37 | 0.2.39 |
| comfy-aimdo | 0.5.5 | 0.5.6 |
| embedded-docs | 0.5.13 | 0.5.14 |
| KJNodes | 1.5.0 | 1.5.3 |
| T8 H3 | 1.100.0 | 1.101.0 |
| controlnet_aux | 2026-08-28 | 2026-10-11 |
| Hawk | 装于 10-14 | 10-16 main |
| h3-attention | 装于 10-15 | 10-20 main |
| Manager | 8-19 | 3.42 |
| xformers | 0.0.35（不可用） | 已卸载 |

### 同日变更

- 模型补齐：`taeh3.safetensors`（22M）、`qwen_image_vae.safetensors`（243M，含 `Qwen/` 硬链接）
- C01：清除死链 `link 65`；`ModelPreviewOverrideKJ` 取消 bypass，`preview_frames` 1024→1
- C01/C02：输出前缀拆分为 `video/Story_C01` / `video/Story_C02`
- D01/D02：画布 `LoadImage` 占位符改为真实图 `wfref_1_T1.png`（引擎 API 模板仍用占位符）
- `engine/comfy/h3_relay_cont_api.json`：清理 Progressive 节点旧键 `filename_prefix` / `image`
- C02 归档（Krea2 UNET 13.5G 未下载、角色表 LoRA 无来源）

### 回归证据

- 启动日志无 `IMPORT FAILED` / `Traceback`
- `/object_info` 2323 节点；关键节点全部存在
- 9 个活跃画布加载 `missing=0`、红节点 0
- A01 实跑：736×416×124，110 秒，输出 `output/upgrade_regress/A01_042_00001_.mp4`
- 引擎 `pytest -q`：303 passed

### 备份 / 回滚

`D:\AIWorkflow\backups\20261021_upgrade\`（184M + Manager）：旧节点包、旧画布、旧模板、旧 yaml、`ComfyUI_AGENTS.md`、`VERSIONS.txt`。

- ComfyUI 本体：`.git` 仍是 0.39 历史，但工作树被 tarball 覆盖；回滚建议重新下载 v0.39.0 tarball 覆盖，而不是只 `git checkout`。
- 节点包：复制备份目录回 `custom_nodes/`。
- pip：前端 `1.53.10`、templates `0.11.76`、kitchen `0.2.37`、aimdo `0.5.5`、embedded-docs `0.5.13`。

---

## 已知漂移 / 待办

1. ✅ **已修（2026-10-24）**：`使用规范_用前必读.md` 已按现行环境全面修订——§1 改为 ComfyUI 0.42.1／`--use-ck-attention`（无 sage）／T8 1.101.0／kitchen 0.2.39；§3 正式入口改为 `engine/run.py`，`run_h3.py` 标为旧排障、不得交付；§2/§10 的配方按 single8／clean20／ref2v4／R3 分列（ref2v4 必须 4 步）；§6/§7 的旧版本坑、端口与输入源按现行改写。**不再作为漂移项。**
2. **ComfyUI 的 `.git` 不代表工作树版本**：tarball 覆盖后 `git describe` 仍是 v0.39.0，版本看 `comfyui_version.py` 或 `/system_stats`。
3. **T8 的 `.git` 停在 1.94**（1048066），工作树是 1.101.0。
4. **Impact Pack JS 旧前端 API**：启动有 `scripts/ui.js` 等弃用警告；上游 4 月后未更新，当前 UI 可用。
5. **C02 归档**：Krea2 选角线缺 UNET（13.5G）与角色表 LoRA（无来源），恢复见 `workflows_archive/MANIFEST.md`。
6. 0.42 资产库迁移丢弃了旧手动标签/元数据，旧库在 `user/comfyui.db.bkp`。

---

## 历史

- **2026-10-26（面板生图＋素材上传）**：娱乐流面板新增图片链——文生图 `image_draft_batch`（1–8 张，1MP 草稿）/ 图生图 `image_i2i`（源图+denoise 0.45–0.70）；参数由 `channels_registry.panel.extra_entries` 派生，仍只调 `engine/run.py`，不另开端口。G13 三个运行级槽显式给：`use_llm_polish`／`resolution_tier`／`enable_audio=false`。四类 H3 素材（图/视频/视频原声/独立音频）与图生图源图改为**上传控件**：`POST /entertainment/upload-material`，落 `output/娱乐流/_上传素材/<kind>/`，白名单后缀、image/audio 50MB、video 90MB；上传≠提交。离线：engine **584 passed**、前端 JS `node --check` 通过；01:24／01:36:56／01:51:27／01:56:55 四次按授权重启（首版图片后端、G13 槽修复、上传路由；spec `image_modes` 两项、面板 200、队列 0/0；G13 离线 error 0/warn 0；上传 HTTP 200/坏后缀 400）；**t2i 已出多批（用户 + A/B/C/D 4 张）**；i2i 未真跑。
- **2026-10-24（使用规范）**：`使用规范_用前必读.md` 全面修订到现行环境与入口（0.42.1／无 sage／T8 1.101.0／`engine/run.py`；five modes＋four recipes；107–345 帧；Ref2VA 额度；G6/G7/G13 与旧脚本边界）。同步 `channels_registry` 的 T2VA/L2VA/Ref2VA 真跑状态、R3 与面板描述；手册 445/0/0，`check_official_path` error 0。
- **2026-10-24（H3 引擎整改 S0–S6）**：`engine` 全量 **577 passed**；真跑 10 条（I2VA 107／R3 1.25／Ref2VA 9图满图／FL2VA／T2VA／L2VA／Ref2VA 3+3 极值／B 批次／C 单镜成片／D 接力）。新增 `h3_relay_movie` 薄流（复用 h3_movie relay_pairs，需无 sage、64 对齐，只接 CLI）；修掉 CRLF 首行空行误判与动态注入误清 `ref_image_size`；S4 两份 `build_manual.py` 收敛为 E 单源（D 薄委托，445 同步/0 落后）。超时/取消、RP1–RP4 逐点、2.0 长镜按用户裁定不测。
- **2026-10-21（规则）**：H3 官方对齐修复——G7 支持 I2VA/FL2VA/L2VA/T2VA 四模式；真首尾帧链切 `h3_fl2va`；G4 补 H3 9 图/3 视频/12 文件/15s 上限；batch 链加 `translate`；帧数与模板命名口径统一。全量 `313 passed`。详见 `H3官方对齐复核_20261021.md`。
- **2026-10-21**：升级 ComfyUI 0.39.0→0.42.1 与全部可升节点包；卸载 xformers；补齐 taeh3/Qwen VAE；画布修复；C02 归档。
- **2026-10-15**：启动切通用模式——无 sage + `--use-ck-attention` + `--reserve-vram 6.0`（用户确认可用于生产）；旧命令备份为 `run_H3_ComfyUI.bat.bak-20261015_通用模式`。
- **2026-09-13**：`使用规范_用前必读.md` 定稿并验收。
