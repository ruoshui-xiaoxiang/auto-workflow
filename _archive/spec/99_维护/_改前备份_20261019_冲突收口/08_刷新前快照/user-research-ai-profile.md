---
name: user-research-ai-profile
description: 用户从事 AI / 形式化框架 / 游戏具身实验，自建本地 AI 栈（5060 Ti + ComfyUI/FLUX + 云端 LLM）；有 LoRA 训练经验；偏好中文协作、根因定位、用实测数据说话
metadata:
  type: user
---

用户正在推进一个将大型语言模型、游戏模组和形式化认知框架（CUF v7）结合的实验项目。对话显示其关注工程实现与理论验证的交叉点，习惯用中文进行技术讨论，并期望助手能直接定位根因、给出可执行的修复步骤。当用户明确说出"直接帮我…"或给出明确执行指令时，会授权助手执行包括向游戏目录写入文件、重启游戏进程、安装软件等重大外部操作。

用户同时使用 **Qoder 国际版**（主力，当前会话即此）与 Qoder CN IDE，二者并存安装、本地数据目录通过目录联接重定向到 E 盘，以免任务中断。**注意：Qoder 国际版和 Qoder CN 的移动端 App 不互通**，国际版用 Qoder Mobile（非 CN Mobile）。

**Qoder Mobile 远程控制（国际版，2026-09-06 确认）**：
- iOS: [App Store - Qoder](https://apps.apple.com/app/qoder/id6764005182)
- Android: [Google Play](https://play.google.com/store/apps/details?id=com.qoder.mobile)
- 功能：实时同步桌面端会话、审批操作、追加指令、锁屏通知
- Web 备选：手机浏览器打开 qoder.com 同账号登录也能操作

**Qoder CLI（国际版，2026-09-06 安装）**：
- 安装：PowerShell 跑 `irm https://qoder.com/install.ps1 | iex`
- 命令名 = **`qodercli`**（不是 `qoder`；`qoder` 是 IDE launcher stub，会报 "CLI is not installed"）
- 二进制：`C:\Users\若水\.qoder\bin\qodercli\qodercli.exe`（v1.1.45）
- 远程控制：`qodercli remote-control` 启动守护进程 → 手机 App 扫码连接
- 安装后需重开终端才能生效（PATH 更新）

GitHub 账号：**ruoshui-xiaoxiang**（auto-workflow 等项目的代码托管）。

用户也会**对外公开发布 Windows 免费软件**（QS Monitor、auto-workflow），挂在产品站 www.huahuayoueryuan.com 供下载（见 [[reference-user-website]]）。他是个人开发者、无营业执照，因此 EV 代码签名证书不可申请；个人唯一可选 Certum OV（约 1200–1500 元/年），目前决定暂缓购买。

## 不只是研究者：自建了完整本地 AI 基础设施

用户自己搭建并维护一套相当成熟的本地栈，不是只会跑脚本的使用者：

- 硬件：RTX 5060 Ti 16GB（Blackwell）、31.8 GB 内存、双盘（NVMe + SATA SSD）
- 生图：ComfyUI + FLUX.1-dev-fp8 + SDXL（底模 sd_xl_base 保留；RealVisXL/GuoFeng4.2XL 已于 2026-09-12 清理删除），自建有 LoRA 素材库
- 本地视频：**MiniMax H3**（2026-09-13 部署，独立 ComfyUI 实例 `D:\AIWorkflow\ComfyUI_H3`；pruned INT8，生产标准＝最低 8 步 + turbo LoRA + 原生音频；见 [[reference-minimax-h3-local]]）；HV1.5 为之前的本地视频管线
- 云端生图：ImageGen（Qoder 内置，质量最高）+ 百炼千问灵动 qwen-image-3.0（DashScope API 直调）
- LLM：已全面转云端（cloud + dashscope 兜底），本地 llama.cpp 多档已移除（2026-09-04，显存互斥）
- 编排：自研 YAML 驱动的工作流引擎、模型网关（OpenAI 兼容代理）、桌面 GUI
- 跨 agent 协作：维护一个「公共记忆库」，有索引构建脚本和更新纪律
- **语音本地化（2026-09-07 起）**：系统 Python312（`C:\Users\若水\AppData\Local\Programs\Python\Python312\python.exe`，不在 git-bash PATH——中文用户名在 PATH 里乱码成 ???，用绝对路径调用）带 **torch 2.11.0+cu128 + torchvision**，CUDA 在 5060 Ti 验证可用（**不许动 torch**）；faster-whisper 1.2.1、f5-tts（f5_tts import OK，阿里源缺包走官方 PyPI+代理）、yt-dlp 2026.08.19 均已装；F5-TTS 零样本声音克隆用于短剧配音（老药农音色），模型权重在 `E:\LocalAI\models\F5-TTS\`（方法见 [[reference-local-tts-f5]]）

**含义**：跟他讨论时可以假定他懂扩散模型、量化、显存预算、服务编排这些概念，不需要从头解释；但**他对自己系统的实际运行数据未必掌握**（例如单张出图 382 秒里有 89% 是 I/O 而非计算，这一点在实测前谁都不知道）。所以价值最高的贡献是**去测、去拆、给出他没见过的归因**，而不是复述架构常识。

## AI 视觉内容创作兴趣（2026-09-06 起）

用户除了技术研究，还在探索 **AI 生成视觉内容**（国漫短剧/角色设定）。审美偏好已明确标定：
- **风格**：3D CG 渲染质感（类似《斗罗大陆》《完美世界》游戏过场动画），**不要 2D 漫画风**（实测 v1 偏幼、v2 偏漫画，v3 3D CG 才通过）
- **偏好**：清冷 > 温柔；御姐 > 萝莉；冰蓝银白 > 暖色；凤眼寒眸 > 圆润大眼；成熟身材 > 少女体型
- **质量标杆**：游戏级 CG 渲染，PBR 材质 + 体积光 + 次表面散射
- **当前方向**：锁定 ImageGen 3D CG 清冷御姐角色 → 分镜短片 → 图生视频拼接

**How to apply:** 涉及生图/视频时，优先走云端（ImageGen 质量最高）；本地 SDXL 用于批量试风格/免费迭代。角色一致性是视频化的核心难点。提示词要强调 "3D CG render / Unreal Engine / PBR / subsurface scattering" 而非 "anime / manga"。

## AI 国漫短剧制作探索（2026-09-06 起）

用户正在评估用 AI 全流水线制作**国漫风格短剧**（1~2 分钟/集）的可行性。已完成成本调研（见 [[reference-ai-pricing]]），对质量和成本有清晰认知：
- **目标风格**：3D CG 国漫（斗破苍穹/凡人修仙传级别），清冷御姐角色
- **已认可的工作流**：剧本分镜 → 关键帧出图（Seedream/Seedream Pro）→ 图生视频（Seedance）→ 配音（CosyVoice）→ 剪辑拼接
- **已知的核心瓶颈**：角色一致性（跨镜头脸飘）→ 需要本地 LoRA 锁定（有 ComfyUI/FLUX 经验）
- **质量预期**：接受"有声漫画"PPT 动画风格，不要求真正番剧级动画
- **成本预期**：均衡方案 ~¥25/集，可接受
- **首个角色概念**：「沈无音」— 亡国公主、天生哑巴、三无性格（无口无表情无情绪）、清冷妩媚并存、27~28 岁御姐、3D CG 渲染。哑巴设定巧妙规避了 AI 视频口型同步短板
- **关键道具**：传国玉玺 — 拳头大，外表做旧成普通石头，一般人认不出。底部有极小"玺"字刻痕（被污垢覆盖）。用旧布包包裹，挂在腰间。后续剧情核心线索（谁在找它、为什么在她手里、她知不知道这是什么）
- **剧本阶段**（2026-09-06）：用户明确剧本创作原则——**从日常场景切入立人物，不靠旁白强行解释设定，背景故事慢慢解锁**。已否决多版剧本（太复杂/太单薄/旁白太多），当前方向是单人日常场景（集市买药→被小孩问路→买糖人凤凰→回茅屋糖人碎了→摩挲玉玺），通过动作细节展现执念。玉玺在镜头 3/5/7 三次出现但不解释，制造悬念
- **分镜阶段**（2026-09-06）：7 张分镜图已出（ImageGen），但用户指出三个问题：①分镜人物跟定稿 v3 不一致 ②画风偏 2D 不是写实 CG ③手部特写太粗糙。**下一步**：用定稿 v3 图做 I2V 参考图重新生成，避免手部大特写，试做 1~2 个镜头的视频 demo

**How to apply:** 涉及国漫短剧时，优先推荐 spark-video（全自动编排）+ Seedream/Seedance（方舟按量）组合；角色一致性建议走本地 LoRA。角色设计时注意：哑巴/三无角色 = 不需要口型同步 + 表情少 = 天然适合当前 AI 视频能力边界。**剧本创作见 [[feedback-script-writing-approach]]**。

## 商业级 AI 短剧制作管线兴趣（2026-09-11 起）

用户在评估海螺 AI 设计工具（E:\hailluoai\MiniMax Design\...）制作 20 集古风真人偶像剧风格短剧时，发现即使工作流专业（分镜板、镜头组执行计划、资产绑定、memory 反馈系统），生成的视频仍不理想。分析后理解：问题不在流程，而在 AI 视频模型能力边界（角色一致性、复杂动作执行、参考图有效性）。

用户随后表示对**商业级制作工作流**感兴趣——不是自动化现有本地管线，而是复刻商业工作室的实际流程：
- **Face-swap / Face-fix**：逐帧替换角色面部为标准脸（FaceFusion / Roop / InsightFace）
- **批量生成 + 筛选**：每镜生成 10-50 版，抽帧后人工/自动评分挑最好的
- **角色 LoRA 训练**：每个主角 50-100 张参考图 → 训练 → 生成时锁定
- **视频修复 VFX**：局部重绘修复手部/道具/物理错误
- **专业后期**：DaVinci Resolve 剪辑调色、专业配音/音效库、母带处理

用户认识到：网上能看的 AI 短剧要么风格化藏拙、要么重度后期修脸、要么超短镜头+大量筛选、要么混合真人素材、要么根本不是完整叙事。当前 AI 视频工具做不了"真人写实 + 连续剧"商业级质量，做"单集概念片"或"风格化短片"更现实。

**How to apply:** 涉及 AI 短剧制作时，区分"本地工具链自动化"vs"商业级制作管线"两个量级。前者是优化现有 HV1.5/H3 管线，后者是建小型 AI 短剧工作室（FaceFusion + 批量生成 + LoRA + DaVinci Resolve）。用户现在两者都感兴趣，但商业级是更长远的目标。

## 存储位置偏好（2026-09-03 已修正）

早先记录说用户「软件与本地数据倾向于放 E 盘」。**这条需要加限定**：E 盘是默认落点（容量大、习惯），但**不是绝对偏好**。当实测显示性能差异巨大时，用户会主动选择搬到 NVMe：2026-09-03 在测出 E 盘 SATA 与 D 盘 NVMe 读速差 33.6 倍后，用户明确选择「搬整个 46 GB 模型库」到 D 盘，而不是保守的「只搬热子集」。

**How to apply:** 不要因为「用户喜欢放 E 盘」就不提搬迁建议。把性能数据摆出来，让他自己选；他倾向于选彻底的那一项。反过来，软件安装目录、应用数据目录仍默认 E 盘。

## 本机 LoRA 训练管线：**已验证跑通，缺的从来不是能力**（2026-09-27 复查 `D:\AIWorkflow\training`）

`training_handoff.md` ＋ `脸A_LoRA训练日志_20260916.md` 实测结论：kohya `sd-scripts` 在 `E:\LocalAI`，**FLUX.1-dev-fp8 与 SDXL 两条训练路径都通了**。同一套 25 张图：

| 底模 | 速度 | 显存 | 产物相似度（vs 训练集中心） |
|---|---|---|---|
| FLUX fp8 | 慢 2.6× | 15.1 GB | 0.728 / 0.728 |
| SDXL | **1.76 s/步、全程约 12 分钟** | **9.7 GB** | 0.688 / 0.660 |

两者都达到"同一个人"的水平（基线 0.60）。**当时卡住的唯一一环是训练集身份不对**（学成了 Redux 那张脸），悬而未决的是"训练集用本地出还是花约 ¥30 用云端 Seedream 铺 50 张"。**⇒ 以后再遇"角色/道具锁不住"，不要说"没有成熟方案"：本机已有成熟方案的一半（训练管线），另一半是训练数据。** 相关：[[feedback-character-reference-image]]

## 环境与工具陷阱（本机实测，反复踩过）

这些不是通用知识，是这台机器 + 中文用户名 + Git Bash 组合下的具体行为，每条都真实导致过失败：

- **PowerShell 5.1 会把 UTF-8 无 BOM 的 `.ps1` 按 GBK 解析**——中文注释可能 ParserError，脚本能跑时中文输出/注释也会在（尤其提权）窗口里显示成乱码。**修复：`.ps1` 存成 UTF-8 with BOM**（`[System.IO.File]::WriteAllText($p,$c,(New-Object System.Text.UTF8Encoding($true)))`）即可保留中文正常显示；否则改用 Python 写脚本。2026-09-12 Defender 排除脚本重弹窗口时用户点名乱码问题，已用 BOM 修复。
- **PowerShell 的转义符是反引号，不是反斜杠**。在 Python 里拼 `-Filter \"Name like 'python%'\"` 会静默失效（过滤器不报错、直接返回空），导致「杀进程」看起来执行了其实没执行。改用 `Where-Object` + 单引号，全程不嵌套引号。
- **Git Bash 里多层嵌套 `cmd /c start /min "标题" cmd /c "..."` 会被 cmd 解析崩**（报「系统找不到文件」）。启动后台进程改用 Python `subprocess.Popen` 传参数列表，不经 shell。
- **删除 Windows junction 只能用非递归方式**：Python 的 `os.rmdir()` 或 `[IO.Directory]::Delete($p,$false)` 只删链接；`shutil.rmtree()` / `Remove-Item -Recurse` 会**顺着链接删掉目标目录的真实内容**。
- **本机跑 Python 脚本用 `py` 启动器**：`python` 不在 Git Bash PATH，猜的 `E:/LocalAI/python/python.exe` 也不存在（2026-09-06 实测 exit 127 浪费一次提交）；`py` 可用且带 PIL 等常用包。
- **ffmpeg 在 `E:/LocalAI/tools/ffmpeg.exe`**，不在 PATH（Git Bash 裸 `ffmpeg` 命令 exit 127）。
- **Git Bash 杀进程别用 taskkill**：`//F` 触发 UNC 路径拦截报错；`/F` 形式被 MSYS 参数改写后看似执行实则没杀（2026-09-06 实测进程存活）。可靠方式 = `powershell -Command "Stop-Process -Id <pid> -Force"`。
- 控制台输出中文常乱码（GBK 控制台）。脚本的诊断输出尽量用 ASCII，中文只放注释和文档。
- **npm 全局安装目录在 `AppData/Local/nodejs/node_modules`**（不是常见的 `AppData/Roaming/npm`）。`npm root -g` 确认。`qoder`/`arkcli` 等全局命令的二进制在 `$LOCALAPPDATA/nodejs/` 下，但 Git Bash 的 PATH 里中文用户名路径解析有问题，直接跑会 exit 127。可靠方式：`"$LOCALAPPDATA/nodejs/node.exe" "$LOCALAPPDATA/nodejs/node_modules/@qoder-ai/qodercli/bundle/qodercli.js" <args>`。
- **Qoder CLI 开机自启**：已在 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` 放了 `qoder-remote-control.vbs`，用 WshShell.Run 静默启动 node + qodercli.js remote-control。
- **Qoder 的 ImageGen 图片生成 API**：2026-09-04 曾返回 HTTP 403（需付费订阅），但 **2026-09-06 已恢复可用**（实测成功生成仙侠图）。若再次 403 再回退到 SVG/素材方案。
- **长时间满血跑 GPU 会诱发"黑屏"（2026-09-13 实测）**：H3 长镜把 GPU 拉满 100%、空闲内存只剩 1.8G 之后显示器黑屏。排查结论＝**机器没死**（命令照跑、GPU 0% 占用 48°C、ComfyUI 服务仍在响应），属**显示输出抽风**，用户重启即恢复。**给用户的话术顺序**：先 `Win + Ctrl + Shift + B`（重启显示驱动）→ 动鼠标 / 看显示器电源与输入源 → `Ctrl+Alt+Del` → 硬重启。本机常驻 **向日葵(Oray) 虚拟显示驱动**（`OrayIddDriver Device`）与 **6 个 NVIDIA Overlay 进程**，都是黑屏的可疑源；排查黑屏时主动查这两项。

## 隐私/安全意识强（2026-09-09）

用户会主动要求排查机器上的远程控制软件、监控软件和可疑进程。对向日葵（AweSun）等远控工具的存在敏感——不反对安装，但要求知情和控制权（"不用了就关掉、禁用自启"）。Defender 历史拦截记录会主动查看。

**How to apply:** 做系统维护/清理类任务时，主动报告远控类软件（向日葵/ToDesk/TeamViewer/AweSun/FRP 等）和遥测服务的存在与状态；不要默默跳过。用户倾向"不用就关"而非"留着以防万一"。

## AI 工具选型决策（2026-09-11）

用户评估 AI 编程/创作工具，核心需求：
1. **工作流编排和管理能力**（优先级最高）
2. **AI 图像/视频生成集成**（ComfyUI/Godot/ffmpeg 等）
3. **编程能力够用即可**（不需要顶级算法能力）

**决策**：继续用 Qoder + 优化配置，不换工具。

**配置方案**：
- Qoder + DeepSeek V4-Flash（日常，成本低）
- Qoder + GPT-5.5（复杂推理任务）
- 本地 ComfyUI/Godot/ffmpeg（生成和后期）

**理由**：Qoder 的 Skills 系统、MCP 工具扩展、自动化任务、记忆系统最适合创意生产工作流。Cursor/Copilot 纯编码强但工作流弱。

**How to apply:** 涉及工具选型时，优先推荐 Qoder 生态内的解决方案。用户重视工作流编排 > 纯编码能力。

用户会要求「量化这个任务的消耗」（曾让我从会话日志统计一次网页维护的 AI 成本），并比较「Qoder 积分 vs 自建 API 按 token」哪个划算。他同时持有多套云端计费（百炼按量曾欠费停摆、token-plan 包月额度耗尽等），对价格敏感、会算账。

**How to apply:** 成本问题按人民币给区间并诚实标注口径边界（例如「该段日志无 usage 记录，只能等效估算」）。给积分/API 对比时要把「复刻平台能力的工程成本」也计入，不能只比推理单价。用户认可「通用平台买智能、自建框架买边界」的分工——不自建 agent 去比肩 Qoder/Trae，auto-workflow 只做通用产品不覆盖的垂直闭环。定价权威来源见 [[reference-ai-pricing]]。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- **本机 LoRA 训练管线已验证跑通（FLUX 与 SDXL 两版、复现训练身份 0.66–0.73，SDXL 12 分钟/9.7GB
- 缺的只是训练集）**
- **Qoder 国际版主力**（非 CN）
- 含本机 PowerShell/cmd/junction 陷阱
