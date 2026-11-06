---
name: reference-hailuo-design-tool
description: 海螺 AI 设计工具（MiniMax Design）项目路径与能力边界——Electron 桌面 GUI 黑盒无公开 API/CLI，云端 AI 视频，有分镜/资产/记忆系统，角色一致性弱；output_files 已导出小Q/无音定妆图喂主线管线
metadata:
  type: reference
---

**海螺 AI 设计工具（MiniMax Design）**

- **项目路径**：`E:\hailluoai\MiniMax Design\current Data\Projects\`
- **当前项目**：《我想制作一部 20 集的古风真人偶像剧风格短剧》（2026-09-10 起）
- **定位**：云端 AI 视频生成平台，提供分镜管理、资产绑定、迭代记忆系统
- **输出规格**：768×1344（9:16 竖屏），15 秒/镜
- **工作流**：分镜图 → 镜头组执行计划 → 批量生成 → 筛选 → 组装

**能力边界（2026-09-10 实测）**：
- ✅ 分镜驱动（有 storyboard panels + 执行计划）
- ✅ 资产绑定（characters/scenes/props）
- ✅ 迭代记忆（memory 系统记录反馈）
- ❌ 角色一致性弱（跨镜脸飘，需 face-swap 弥补）
-  动作精度有限（AI 不理解剧本，只匹配提示词）
- ❌ 无首尾帧控制（本地 HV1.5/H3 才有）
- ❌ 无原生音频（需事后混音）

**形态与接入（2026-09-13 实测）**：Electron 桌面 App（`MiniMax Design.exe` + `current/` Chromium 运行时），后端走 MiniMax 云端，**无公开 API/CLI，程序化接入不可行**。但它已在「资产级」喂主线管线：`current Data\output_files\` 导出过 `xiaoQ_char_01.png`（小Q定妆）与 `阿音-避世代笔期-基础形象.jpg`（无音候选脸）——即它当前实际角色＝角色图生成器，产出手动/半自动进 Godot+Seedance 当 reference_image。想程序化接 MiniMax 视频能力只能走官方 API（Hailuo-02/MiniMax-H3，api.minimax.cn），但 key 仍死（见 [[reference-minimax-api]]）。

**参考图入库工具（2026-09-13 建）**：`D:\AIWorkflow\tools\mmd_ingest.py` + 双击 `参考图入库.bat`。把 `output_files\` 的图**复制**进 `E:\创作\无音项目\图\<定妆|场景|道具>\minimax_design\`（候选层，与定妆根目录的已定稿图隔离），sha256 去重、MANIFEST（`E:\创作\无音项目\图\minimax_design_manifest.json`）登记版本。**只复制不删源文件**（output_files 是 App 自有目录，见 [[feedback-copy-not-move]]）。注意 `output_files\xiaoQ_char_01.png` 与 `定妆\xiaoQ_char_01.png` 字节相同（已定稿，无需重复入库）；`阿音-避世代笔期-基础形象.jpg` 是待定的无音候选脸（与 char_e01 二选一，未定）。

**★它是聚合器，不是 MiniMax 自家的图像/视频模型（2026-09-16 读 `current\resources\conf\external_api_conf.yaml` 得到）**：App 通过本地 Node gateway 调它自有的 **cloud_gateway**（base_url 由 `@hilo/protocol` 定义、可用 `CLOUD_GATEWAY_BASE_URL` 环境变量覆盖），后端是一批第三方模型的代理：

- **图像**：nano_banana / openai / kontext / qwen / **seedream** / kling / midjourney
- **视频**：minimax / minimax-v3 / kling / veo3 / wan / seedance / jimeng
- **音频**：minimax TTS / voice_clone / voice_design；minimax 音乐与歌词
- 另有 `super_resolution`、`media analyze`

→ 所以**在 App 里充的"积分"买的是这批第三方的额度，跟 `E:\密钥文件\海螺ai.txt` 那把 `sk-api-` key 是两套账**（后者 2026-09-16 实测出图直接 `1008 insufficient balance`，见 [[reference-minimax-api]]）。**它里面能调 Seedream——跟我们 ARK 通道是同一个模型**，出图质量不会有额外优势，唯一优势是那边的钱已经充了。它真正互补的地方在**视频后端**（veo3 / seedance / kling / jimeng 都在里面）。

**架构与可接入性（2026-09-16 实测）**：Electron（`MiniMax Design.exe` + `current/` + Velopack 更新器）→ 本地 Node gateway（`current\resources\gateway`）→ 私有 cloud_gateway。**没有对外文档化的 API/CLI**，程序化接入要靠逆向它的私有接口与 App 会话凭证——不稳、会被更新打断，**不做**。但 App 自带 `current\resources\mcp-tools`（MCP 工具层）、`opencode\opencode.exe`、`bundled-plugins\{3d-director-stage, clip-studio, comfyui}`——**若它启动时对外开 MCP，那是正规可接的口；开不开由用户在 App 设置里定（未验证）**。App 未运行时本机没有它开的监听端口。

**桌面快捷方式**：`C:\Users\若水\Desktop\MiniMax Design.lnk` → 真实目标 `E:\hailluoai\MiniMax Design\current\MiniMax Design.exe`（有效）。

**与本地管线对比**：
- 海螺 = 云端黑盒，不可控，付费
- 本地 HV1.5/H3 = 完全可控，免费，但需手动搭建

**用户判断（2026-09-10）**：流程专业但视频不理想，根因是 AI 视频生成天花板（不是流程问题）。考虑转向"逐帧动画"路线（高质量图片 + 程序化动画）。

**How to apply:** 用户提到"海螺设计工具"或路径 `E:\hailluoai\` 时，知道这是云端 AI 视频平台，**程序化接入不可行、不能当视频引擎**（只出 9:16 竖屏而主线要 16:9 横屏 r2v；无首尾帧；角色一致性弱）。唯一可用角色＝角色/场景参考图生产站（output_files 已喂小Q/无音定妆图进 Seedance reference_image）。想程序化视频只能走官方 API（Hailuo-02/H3）但 key 仍死。本地管线仍是主通道。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- 云端 AI 视频平台 `E:\hailluoai\MiniMax Design\`
- **无 API/CLI，仅作角色/场景参考图生产站**（9:16 竖屏+无首尾帧当不了主线视频引擎，官方 key 死）
