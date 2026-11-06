# auto-workflow — 云端工作流框架

用云端 LLM（cloud + dashscope 兜底）与 ComfyUI 编排自动化任务。**一个 YAML = 一个工作流**，
引擎不动代码；任务类型（llm / comfyui / refine / files / shell）在 `tasks.py` 注册。

```
workflows\*.yaml  →  run.py 引擎  →  tasks.py 任务模块  →  云端 LLM + 本地 ComfyUI
     (定义)         (调度/占位符/     (能力插件)          cloud/dashscope + ComfyUI 8188
                    日志/报告/状态)
```

跑引擎用 Python 3.12（`C:\Users\若水\AppData\Local\Programs\Python\Python312`），
依赖 `requests` / `pyyaml` / `Pillow`（Pillow 用于产物校验）。

## 快速开始

```powershell
cd E:\LocalAI\workflows
python run.py --list                       # 列出可用工作流
python run.py selftest                     # 引擎自检，不碰显存
python run.py llm_fallback_test            # 验证 LLM 兜底链

# 两段式（推荐）：批量草稿 → 打开报告按编号挑 → 精修选中
python run.py image_draft_batch --set count=16
python run.py image_refine --set manifest=20260903_053620 --set pick=1,7,12

# 单段一次出成品（不要挑图时用）
python run.py image_batch_draft --set count=2
```

出图运行中会打印一行报告路径，**双击那个 HTML** 即看流程方框、进度和草稿网格；
点图选编号，页面底部给出可直接复制的精修命令。报告零依赖、不开服务、不占端口。

## 网页操作（webui，2026-09-03 新增）**⚠ 已废（2026-10-19）**

🔴 本节保留只为说明「这堆代码是干什么的」，**不是现役入口**。门面只留两个（用户 2026-10-19 裁定）：
**人用**＝桌面「娱乐流」图标 → `E:\LocalAI\娱乐流.bat`（只起 ComfyUI 8189 ＋ `/extensions/comfyui-entertainment-panel/index.html`）；
**agent 用**＝`python run.py <workflow> [--tier play|draft|final]`。真源：`D:\AIWorkflow\官方路径.json`。
8787（engine WebUI）与 8790（说话出片 UI）都登记在该文件 `deprecated` 段（状态「待归档」，
原文件一字未动，所以本节描述的行为仍然成立——只是别再当入口用）。

不想敲命令行时用网页版：双击 `start-webui.bat`（或 `python webui.py`）起本地服务
（`http://127.0.0.1:8787`），浏览器里点按钮操作 —— 输入主题/数量 → 出图 →
网格挑编号 → 精修 → 看历史批次。页面含「高级参数」折叠区（LoRA/尺寸/步数/种子）
与「显示原始信息」开关（错误翻成人话，想看原始日志再打开）。

- **只读外壳**：webui 只调 `run.py` 子进程、读 status.json 与 `out\`，绝不写回
  YAML / config，也不提供删除；未知参数整体拒绝（422）。status.json 是稳定插件口，
  其它消费方（如 QS 监控器）后续可直接接入，互不约束。
- 离线测试：`python -m pytest tests -q`（含 `tests/test_webui.py`：字段分组、
  白名单、路径穿越与批次边界）。

产物统一在 `E:\FLUX_Workflow\out\<批次号>\`：`draft\` 草稿、`final\` 精修成品、
同夹内的报告与 manifest。整个文件夹自包含，可整体拷给别人，双击报告照样显图。
精修产物写进**草稿那一批**的文件夹，不另起新夹。`ComfyUI_output\` 只是暂存区，正常应保持空。

## 实测参数（RTX 5060 Ti 16GB，2026-09-03）

| 配置 | 单张耗时 |
|---|---|
| 草稿 832×1216 / 12 步 / 不放大 | 24.1 s |
| 同上 + 挂 2 个 LoRA | 25.5 s（LoRA 成本 +1.4 s） |
| 精修 USDU tile=512 / 12 步 / 2x → 1664×2432 | 183.5 s（20 块 ≈ 9 s/块） |

模型加载在 NVMe 搬迁后约 6 s（页缓存热）。**精修必须走 USDU**：FLUX 的 seed 不跨分辨率，
直接高分辨率重画保不住草稿构图，选图就白选了。所以草稿与成品**同分辨率、同 seed，只降步数、
不放大** —— 这是整个两段式的前提。

## 核心机制

- **LLM 兜底链**：`backend: cloud,dashscope` 按 `config.yaml` 的 `fallback_chain`（默认 `[cloud, dashscope]`）
  依次尝试；云端不可用时自动降级到按量付费。
  `enabled: false` 时不调模型，直接把 `static` 当结果返回 ——
  接口留着但不接上，下游 `{{polish.text}}` 照常可用。
- **ComfyUI 任务**：出图与精修共用 `ensure_comfyui()`；服务未运行时自动拉起。
  启动命令默认硬编码，写 `config.yaml` 的 `comfyui.launch_cmd`
  即成为唯一来源。
- **产物闸门**：坏产物不再静默入库，四条都在提交/收尾处 fail-loud ——
  ① 空提示词或字面量 `"None"` 拒绝提交；② 产物尺寸 ≠ 请求尺寸（模板里有多余放大节点）报错；
  ③ 整幅近乎纯色的废图报错；④ 精修按 tile 网格估算分块数，超 `max_tiles`（默认 64 ≈ 9 分钟）
  直接拒绝并说明怎么办，不等超时才发现。
- **manifest 与编号选图**：每次出图写 `{workflow}_{run_id}.manifest.json`，逐张记
  `index/seed/file/prompt/width/height/steps`。精修用 `--set manifest=<run_id> --set pick=3,7`
  按编号取，不说 seed、不用剪贴板。manifest 里的尺寸是产物**实测**尺寸。
- **状态与日志**：每次运行的 `.log` 在 `E:\LocalAI\logs\workflows\`（只放日志），报告与
  manifest 在 `E:\FLUX_Workflow\out\<批次号>\`；
  `status.json` 的 `last_run` 含 `status`(running|success|error) / `report` / `manifest` /
  `steps` / `parent_run` / `picked`，`history` 按 run_id 去重（一次运行只占一条）。Ctrl-C 会被记为
  error 而非留下永久 running，且下次开跑会把上次遗留的 running 自愈成 error。
  **监控器契约**：三态不可扩；`parent_run` 是精修指回上游草稿的父指针、`picked` 是那次挑的编号；
  `running` 条目在**每个步骤边界**重写，所以运行中就能读到实时步骤进度（原来只在头尾写，
  十几分钟的运行全程显示 pending）。监控器只读这个文件。

## 新增一个工作流

在 `workflows\` 下新建 YAML（复制现有文件改），步骤字段 `task/id/label/hint` 之外都是任务参数：

| 任务 | 参数 |
|---|---|
| `llm` | `backend`(auto/名字/逗号列表)、`system`、`prompt`、`max_tokens`、`temperature`、`enabled`、`static`、`timeout` |
| `comfyui` | `workflow`(模板路径)、`prompt`、`count`、`width/height`、`steps`、`guidance`、`seed`(空=随机)、`prefix`、`loras`、`timeout` |
| `refine` | `files`(草稿路径列表)、`prompt`、`template`、`tile`、`steps`、`upscale_by`、`denoise`、`guidance`、`prefix`、`max_tiles`、`timeout` |
| `files` | `action: copy_new`(`src/pattern/dst`) 或 `clean_old`(`dir/pattern/days`) |
| `shell` | `command`、`timeout`（扩展逃生口） |

`loras` 两种写法：YAML 里 `[{name, strength}]`，或命令行
`--set "loras=flux/Hanfu_Elegant_Flux.safetensors:0.8,flux/Ancient_Palace_Flux.safetensors:0.7"`
（`--set` 传不了列表）。名字用正斜杠或反斜杠都行，Windows 版 ComfyUI 的枚举要反斜杠，已自动归一。

占位符：`{{args.参数名}}`、`{{步骤id.返回字段}}`、`{{run_id}}`、`{{cfg.*}}`。
解析为空会直接报错并列出问题所在，不会把字符串 `"None"` 当内容喂给模型。
ComfyUI 模板放 `comfy\`，用哨兵值 `__PROMPT__ / __SEED__ / __W__ / __H__ / __STEPS__ /
__GUIDANCE__ / __PREFIX__`（精修另有 `__IMAGE__ / __TILE__ / __DENOISE__ / __UPSCALE_BY__`）
标记可替换处。

## 定时触发（任务计划程序）

```powershell
schtasks /Create /TN "AutoWF 图纸日报" /SC DAILY /ST 08:00 /TR ^
 "cmd /c cd /d E:\LocalAI\workflows && python run.py image_draft_batch --set count=2"
```

## 约束与提醒

- 脚本引用路径必须 ASCII（命名铁律）；本框架代码/配置在 `E:\LocalAI\workflows\`，符合。
- `E:\Models\LLM\Qwen3-8B-Instruct`（BF16）是 CUF-QS S31 的 W2 测量引擎权重，**禁止**挪作兜底服务。
- Ollama 已安装但默认端口 11434 与档1冲突：若要用 Ollama，先设 `OLLAMA_HOST=127.0.0.1:11500`。
- 云端兜底：后续可在 `config.yaml` 加云端条目（OpenAI 兼容 base_url + 密钥从环境变量读，
  密钥不入库，指针见 `E:\密钥文件\密钥清单.md`）。
- 工作流跑图期间不要用桌面工具的「启动选中模型」抢显存（`start-qwen1234.ps1` 那条路径没有显存闸门）。
