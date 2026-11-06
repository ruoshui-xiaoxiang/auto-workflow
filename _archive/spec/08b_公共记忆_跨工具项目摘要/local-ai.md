# 本地 AI 基础设施 — 模型资产与配置

## 基础信息

- 主题：本地模型/本地 AI 服务的管理定位与启动配置
- 代码/配置根：`E:\LocalAI\`（launchers、logs、模型服务）
- 模型权重仓库：`E:\Models\`（GGUF、Embedding、视觉/生成资产）
- 最新更新：2026-10-21 01:33
- 摘要：2026-10-21 H3 运行时升级到 **ComfyUI 0.42.1**（前端 1.55.18／模板 0.11.89／kitchen 0.2.39／aimdo 0.5.6），T8 1.101.0、KJNodes 1.5.3、Manager 3.42；xformers 0.0.35 已卸载（与 torch 2.13 不匹配）；模型补 taeh3＋Qwen VAE；9 个画布 0 红、A01 实跑通过、引擎 303 测试全绿。四通道与启动器口径不变（LM 1234 / OLL 11434 / agent 8080-8082 / 脚本化出片 8790+8787+8189）；PowerShell 7.6.6 默认、run-ps1.bat 统一。

## 重要改动记录

### 2026-10-21 ｜ H3 运行时升级（ComfyUI 0.42.1 ＋ 节点包）

- **摘要**：8189 运行时从 ComfyUI 0.39.0 升到 **0.42.1**；节点注册 2287→2323。同步升级 KJNodes 1.5.0→**1.5.3**（含 MiniMax H3 VRAM Attention／Preview Override 修复）、T8 1.100.0→**1.101.0**、controlnet_aux、Hawk、h3-attention、Manager 3.42。
- **环境**：卸载 **xformers 0.0.35**——它是为 torch 2.10+cu128／Python 3.10 编译的，当前 torch 2.13.0+cu130／Python 3.13，C++ 扩展本就加载不了；当前 attention 走 pytorch＋comfy-kitchen，未启用 xformers。
- **模型**：补 `vae_approx\taeh3.safetensors`（22M）、`vae\qwen_image_vae.safetensors`（243M，另在 `vae\Qwen\` 建硬链接供 C02 画布路径）。
- **工作流**：C01 清死链、启用 PreviewOverride（preview_frames 1024→1）；C01/C02 输出前缀拆分；C02 Krea2 缺件线归档到 `user\default\workflows_archive\`。
- **回归**：9 个活跃画布 `missing=0`／0 红；A01 实跑 736×416×124，110 秒出片；引擎 `pytest -q` 303 passed。
- **影响范围**：8189 上所有 H3 出片与图片工作流；引擎/画布/模板的 YAML/JSON 无需改参数，但升级后运行时版本以 `/system_stats` 为准。
- **相关文件/路径**：`D:\AIWorkflow\ComfyUI_H3\VERSION_LOG.md`（版本快照与历史）、`D:\AIWorkflow\ComfyUI_H3\ComfyUI\user\default\workflows_archive\MANIFEST.md`、备份 `D:\AIWorkflow\backups\20261021_upgrade\`（184M＋Manager）、升级详细记录 `C:\Users\若水\Documents\Qoder\2026-10-21\888fb2b8\upgrade_20261021.md`。
- ⚠ **回滚口径变了**：ComfyUI 工作树由 tarball 覆盖，`.git` 仍停在 v0.39.0；T8 工作树 1.101.0 而 `.git` 仍 1048066；KJ 工作树 1.5.3 而 `.git` 仍 3f20054。回滚请用备份树，不要用 git commit。

### 2026-10-12 ｜ PowerShell 7 默认 + 启动器加固 + 说话出片 UI

- **PS 5.1 坑**：`.ps1` 存 UTF-8 **无 BOM** 时，脚本里 `C:\Users\若水\...` 会被读坏，`Start-Process -FilePath $py` 报 null/empty。**对策**：① 所有 `.ps1` 用 **UTF-8 with BOM**；② 路径用 `$env:LOCALAPPDATA` / `$env:USERPROFILE` 拼接，少写死中文用户名；③ 启动器统一 `E:\LocalAI\launchers\run-ps1.bat`（优先 pwsh，失败回退 powershell.exe）。
- **PowerShell 7.6.6 已设默认**：User PATH 置顶 PS7 目录；`.ps1/.psm1/.psd1`→`pwsh7file`；App Paths `pwsh.exe`。Store 包真身在 `C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.6.0_*`。
- **说话出片 UI**：`D:\AIWorkflow\engine\nl_ui\`，端口 **8790**；自然语言+参考图 → 引擎工作流；G13 运行级槽（use_llm_polish / enable_audio / resolution_tier）必须 UI 显式选，空槽拦截。
- **环境修复**：`engine/channels_registry.json`（与 tools 副本）已恢复；G13 依赖它。
- **清理**：`E:\LocalAI\ComfyUI_windows_portable`（9GB）已删；训练用 `ai-toolkit\venv_train`；tasks.py input_dir 兜底改指 ComfyUI_H3。
- 相关：`local-ai-workflow-rules.md`、`E:\LocalAI\CHANNELS.md`、`run-ps1.bat`。


### 2026-10-12 ｜ 四启动通道定型 + 端口拆分 + 旁路清理

- 摘要：用户裁定「只保留 4 个启动通道」。端口：Ollama **11434** / LM Studio **1234** / agent出片引擎网关 **8080** + 后端 **8081 qwen3-14b、8082 agent档** / 本地脚本化出片流水线 **8787 WebUI + 8189 ComfyUI**。删除 LocalAI 控制台、出片引擎.lnk、8188 便携启动器、圣女一条龙、启动常驻ComfyUI、开始菜单重复 Ollama/LM 入口；占位空模型（face_landmark .part 分片）已清。
- **强制**：任何 agent 跑出图/出片/工作流/本地 LLM，必须默认从 `E:\LocalAI\LocalAI.bat`（agent出片引擎）启动或引用其服务；禁止另开端口。声明写入 `E:\LocalAI\AGENT_DEFAULT.md`、`CHANNELS.md`、`D:\AIWorkflow\AGENTS.md`。
- **IDE 不清**：DeepSeek Harness / Qoder / Trae / MiMo 等按 IDE 保留，不进四通道清理范围。
- 通道入口：桌面 LM Studio / Ollama / agent出片引擎 / 本地脚本化出片流水线（仅这 4 个）。
- 影响范围：所有本地模型调用与出片工作流启动；`start-qwen1234.ps1`→8081、`agent-launch.ps1` 默认 8082（8082-8084）、`gateway/config.json` 上游已改指。
- 相关文件：`E:\LocalAI\CHANNELS.md`、`AGENT_DEFAULT.md`、`LocalAI.ps1`、`本地脚本化出片流水线.bat`、`E:\公共记忆\projects\local-ai-workflow-rules.md`


### 2026-09-03 ｜ 衍生对外交付线（能力变现）

- 摘要：把本地部署能力打包成收费服务，三件套定稿并归档 `E:\文档\产品交付\本地AI部署服务\`（交付部署方案 / 客户模板×2 / 启用SSH客户端包 / 踩坑库与SOP语料）。执行模式 = SOP 语料喂客户机 Trae + 服务方远程兜底；远程主通道 ToDesk/向日葵（境外中转已论证负优化，禁用）；定价 A¥1200/B¥2500/C¥400 起（核实行情后维持）。详见 `projects\delivery-service.md`。

### 2026-09-03 ｜ 境外服务器部署 Codex CLI（云执行臂）

- **服务器**：47.250.138.158（阿里云·马来西亚吉隆坡，Ubuntu 24 x86_64），SSH 用户 **root**，本机私钥 `~\.ssh\server_deploy_key`（known_hosts 已留 ed25519/rsa/ecdsa 指纹）。
- **Codex CLI**：v0.152.1，位于 `/root/codex/codex`（软链 `/usr/local/bin/codex`）；登录凭据 `/root/.codex/auth.json`（ChatGPT OAuth，权限 600）。
- **命令执行宿主（关键坑）**：写文件/跑命令依赖 `/root/codex/codex-code-mode-host` + 沙箱运行时 `/usr/local/bin/bwrap`，两者缺失时 Codex fail-closed（"No such file...codex-code-mode-host"），**已补装并验证可跑 bash**。升级/换版本后如遇该报错，从官方 release 同名 asset 补回这两件。
- **无 TTY 调用口径（必须遵守）**：`codex exec` 在非 TTY 下会等 stdin 挂起；必须 `echo '<任务文本>' | codex exec --skip-git-repo-check --sandbox danger-full-access`；结构化输出加 `--json`。任务上下文用**纯文本经 stdin 喂**，不要让它去翻本机工程（服务器上看不到）。
- **额度硬约束**：ChatGPT 免费档 Codex 额度极不经用（2026-09-03 实测 1 个轻 exec ~7k tokens 即耗尽），限制恢复 **2026-10-01 12:14 PM**；Plus 可解锁。日常不依赖它跑大任务，仅临时借强模型；额度墙时退回本地五档。
- **合规边界（自用）**：仅自用研究/编码、数据干净不传个人信息；登录与调用节点保持境外一致（防 OpenAI 风控）；不做境内网穿透、不转卖、不对外提供 API。
- **验证记录**：冒烟 PONG 通过；生图方案设计任务因额度墙未完成（Codex 已能执行+写文件，模型答复能力正常）。

### 2026-09-02 ｜ 盘点修正：Qwen3-8B BF16 已入库；Ollama 端口冲突处置

- 摘要：实地盘点发现 ①`E:\Models\LLM\Qwen3-8B-Instruct`（16GB BF16 完整权重，9-01 晚下载完）——即 CUF-QS S31 换型的 W2 测量引擎，**其他服务勿挪用**；②本机装有 Ollama v0.33.1（仅 qwen2.5:0.5b），其默认端口 11434 与档1 gpt20 冲突，已停止其服务；若启用需设 `OLLAMA_HOST=127.0.0.1:11500`。另确认盘上无 Qwen3-30B-A3B（用户决定暂不下载）。
- 影响范围：11434 端口归属维持档1；Qwen3-8B 权重目录归 CUF-QS S31 计划专用
- 相关：新增 `projects\auto-workflow.md`（本地模型自动化编排框架，复用五档服务）

### 2026-09-01 ｜ 五档最优配置定型 / 整机文件迁移

- 摘要：三档 gpt-oss/Qwen 本地服务参数固化（start-agent-tier.ps1）；LocalAI 全量迁至 E 盘；Ollama 停用
- 详见英文正文下方"五档最优配置"

## 模型资产清单

### 聊天 GGUF（E:\Models\GGUF）

| 模型 | 大小 | 显存占用 | 定位 |
|---|---|---|---|
| gpt-oss-20b-MXFP4 | 12.11GB | 全显存 13.2GB / 专家卸载 2.3GB | 本地推理主力（编码） |
| Qwen3-14B-Instruct-Q4_K_M | 8.38GB | 视量化 | 独立聊天/翻译辅助（1234 端口） |
| Qwen2.5-7B-Instruct-Q4_K_M | ~4.7GB | 4.7GB | 轻量/批处理档 |
| Qwen2.5-0.5B-Instruct-Q4_K_M | 491MB | **0（纯 CPU）** | 极轻量；实测解码 84~113 tok/s。⚠**不在 `E:\Models` 下**，在 `E:\QODERCN\ai_agent_monitor\models\`（CUF-QS 自带），按 `E:\Models` 盘点会漏 |
| eagle3 草稿权重 | 921MB | +1119MB | **实测负收益，别开**：解码 115→67 tok/s，草稿接受率仅 15~27% |

### Embedding（仅语义检索/相似度，不承担对话）

- bge-small-zh-v1.5、paraphrase-MiniLM（在 `E:\Models\Embedding`）

### 视觉/生成（ComfyUI 调，不在对话服务内）

- Qwen2.5-VL-7B（视觉理解）、Flux/ControlNet、SDXL、HunyuVideo-1.5-720p

## 五档最优配置（2026-09-01 定型）

| 档位 | 模型 | 端口 | 用途 |
|---|---|---|---|
| 档1 | gpt-oss-20b 全显存（65K 上下文） | 8082（原11434） | 主力编码（Trae 内），唯一能撑 Trae ~23k token 提示词 |
| 档2 | gpt-oss-20b 专家卸载 | 8082 换档（原11435） | 显卡在跑别的时兼顾编码（慢约3倍） |
| 档3 | Qwen2.5-7B | 8082 换档（原11436） | 轻量/批处理，82 tok/s |
| 独立 | Qwen3-14B | 8081（原1234；1234 现归 LM Studio） | 长文档/翻译/聊天辅助 |
| 独立 | ComfyUI | - | 出图/出视频 |

启动入口：`E:\LocalAI\launchers\start-agent-tier.ps1` 等（三档参数已固化在脚本）。

> 磁盘上"聊天可对话"的模型是 **4 个**：gpt-oss-20b、Qwen3-14B、Qwen2.5-7B、Qwen2.5-0.5B；
> 上表是**服务档位**划分（0.5B 不占档，按需临时起），两者不是同一维度，别混。

## 定位结论（用户认可，避免反复纠结）

1. **本地 = 零成本兜底 + 隐私/离线 + 廉价批处理**；云端套餐（百炼/Codex/Trae/Qoder/豆包）才是主力。
2. **≤1B 小模型不补**：本机已有 Qwen2.5-7B 兜底；更小的（0.5B/0.8B/1B）价值低，随手问答直接放豆包（已购专业版）。
3. **16GB 显存是硬天花板**：Kimi K3 / GLM-5.3 / Laguna S 2.1 等开源旗舰权重大，本地不追。
4. **档3 唯一潜在升级**：Qwen3.6-8B（约 5GB，原生多模态+长上下文，比 7B 强），锦上添花非必做；未下载前维持现状。

## 关键路径速查

| 内容 | 路径 |
|---|---|
| launchers / 启动脚本 | `E:\LocalAI\launchers\` |
| 模型权重 | `E:\Models\GGUF\`、`E:\Models\Embedding\` |
| ComfyUI / 生成资产 | `E:\LocalAI\`（ComfyUI） |
| 境外 Codex（云执行臂） | 服务器 47.250.138.158 root；本机私钥 `~\.ssh\server_deploy_key`；CLI `/root/codex/codex` |

## 踩坑提醒

- 16GB 显存跑 20B 只能重度量化（MXFP4），别期望本地追平云端旗舰——定位是兜底不是主力。
- 大批量下载优先阿里云镜像 + 多线程（单线程 0.3-1.5MB/s）。
- Codex 无 TTY 必须 `echo prompt | codex exec`，直接传参数会挂起；没装 code-mode-host/bwrap 时写文件与跑命令 fail-closed。