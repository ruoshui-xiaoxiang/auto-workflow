# 《V1.1 实施手册》
## Skill-first AI 影视生产系统 —— 可照着搭的那一版

| 项 | 内容 |
|---|---|
| 版本 | V1.1.1（在你 V1.1 总设计之上做可施工化 + 平台核实修正） |
| 日期 | 2026-09-23 |
| 适用平台 | Qoder 国际版桌面端 0.3.4（本机实测） |
| 适用工程 | 本机本地 AI 栈：RTX 5060 Ti 16GB / 32GB RAM / ComfyUI 8189 / `D:\AIWorkflow\engine\run.py` |
| 读者 | 你（决策）+ 我（施工） |

---

## 0. 先说核实：这份手册的每一条来自哪里

你要求"逐步核实、不要有错误和漏洞"。所以先把证据分级，后面正文里用标记：

| 标记 | 含义 | 本手册里的例子 |
|---|---|---|
| **[实测]** | 我在你机器上跑过、看过输出的 | Agent frontmatter 字段表、hooks 事件与退出码、H3 帧长闸与速度 |
| **[官方]** | 装机自带的官方说明文档写的 | `agent-creator` / `skill-creator` / `hook-config` 三个内置 skill |
| **[约定]** | 我们项目自己定的规矩，平台不保证 | 文件命名、Asset ID、审片区流程 |
| **[待验]** | 你 V1.1 里假设了、我还没验或验不过的 | 见 §11 风险清单 |

### 0.1 对你 V1.1 原文的 5 处修正（重要，会直接影响能不能跑起来）

| # | 你原文写的 | 实际核实结果 | 影响 |
|---|---|---|---|
| 1 | Custom Agent frontmatter 支持 `name/description/model/tools/skills/mcpServers` | **[官方]+[实测]** 装机自带 `agent-creator` 的字段表是：必填 `name`、`description`；可选 `tools`、`disallowedTools`、`model`、`color`、`maxTurns`、`timeoutMins`、`effort`、`skills`。**没有 `mcpServers`** | Agent 不能自带 MCP 白名单。MCP 是 CLI 级配置（`~/.qoder/` 下），所有 Agent 共享。要"限制某个岗位能碰什么设备"，只能靠 `tools` + hooks + 命令层凭证隔离 |
| 2 | Model 层按岗位填 `Qwen3.8-Max` | **[官方]** `model` 只接受**档位**：`inherit`（默认）/ `lite` / `efficient` / `auto` / `performance` / `ultimate`，不是任意厂商模型名 | "换大脑"变成"换档位"，仍然是可插拔的，但粒度不同。要真换到某家模型，走 MCP/CLI 那条路（如 arkcli、bl、可灵 CLI），不是改 frontmatter |
| 3 | Skill 目录用 `REFERENCE.md` / `EXAMPLES.md` 平铺 | **[官方]** 官方约定是子目录：`scripts/`、`references/`、`assets/` | 平铺也能读，但自动发现与渐进加载按子目录走。本手册统一用子目录 |
| 4 | `rules/` 作为 Qoder 原生层 | **[实测]** 平台没有 `.qoder/rules/` 这个原生目录。可用的落地机制只有三种：① `AGENTS.md`（模型每次会话都读）；② `hooks`（`settings.json` 里的机械闸，`PreToolUse` 退出码 2 = 阻断并把 stderr 当理由）；③ 校验脚本（由 workflow 显式调用） | Rules 不能只写成 md 就以为生效了。**能机械判定的必须落到 hook 或脚本**，否则等于没写。这条是本手册 §5 的主线 |
| 5 | Director Agent 负责"任务分配 / 调度其他 Agent" | **[待验]** 子 Agent 在隔离上下文里运行、只回一条消息；它自己能不能再开子 Agent、能不能直接跟你对话，我还没测。你当前会话里可用的 subagent_type 只有 `Explore` / `Plan` / `general-purpose` | 所以本手册把 Director 设计成**"评审 + 派工单"**而不是"运行时调度器"：它产出 `dispatch.md`，由主会话（我）按单派工。Phase 4 第一件事就是测能不能嵌套，测出来再决定要不要升级成自动调度 |

> 这五处不是挑刺，是"照着搭会不会崩"的分水岭。第 1、4 条尤其承重。

---

## 1. 六层定型（谁能干什么、谁绝不能干什么）

```
MODEL   档位/算力      ← 每个 Agent 独立可换
AGENT   岗位+上下文    ← 只带自己那份 skills/tools
SKILL   专业能力       ← 共享库，不属于任何岗位
WORKFLOW 生产线        ← 什么时候做、谁接谁、卡在哪
RULE    制度           ← 能机械判的进 hook/脚本，判不了的进 AGENTS.md
TOOL/MCP 手和设备      ← CLI、ffmpeg、ComfyUI HTTP、云端 API
```

| 层 | 只回答这个问题 | 禁止越界 |
|---|---|---|
| Model | 用多强的脑子 | 不许在 Model 层写业务规则 |
| Agent | 谁负责、看哪些资料 | 不许把"怎么做"写死在 prompt 里（那是 Skill 的活） |
| Skill | 怎么专业地做一件事 | 不许规定"什么时候调用我"（那是 Workflow 的活） |
| Workflow | 顺序、并行、gate、返工 | 不许包含专业判断细节（引用 Skill） |
| Rule | 什么绝对不能发生 | 不许写成"建议""尽量"（不可判定的规则=没有规则） |
| Tool | 用什么执行 | 不许在 Tool 层做创意决策 |

**三条硬禁令（V1.1 的核心价值，也是最容易被自己破坏的）**

1. Skill 不归属 Agent。同一个 `shot-continuity` 被 5 个岗位共享，谁都不许复制一份改成本地版。改只改共享库。
2. Agent 不拥有全部工具。Director 拿不到 Bash；Video 拿不到删除文件的权限。
3. Rule 不塞进 Skill。Skill 里出现"必须/禁止"字样即视为写错层，要搬到 `rules/` + hook。

---

## 2. 目录结构（落地版）

根目录建议就用你现在的 `D:\AIWorkflow\`（NVMe、生产层）旁边新建一个 `D:\AI-Film-Studio\`，交付物仍走 `E:\图像影音资源池\<项目>\`（现有约定不变）。

```
D:\AI-Film-Studio\
├── AGENTS.md                      # ← Rule 的"自觉层"：每次会话必读，只放可判定条款的摘要
├── .qoder\
│   ├── settings.json              # ← hooks（PreToolUse 闸、PostToolUse 记账）[实测支持]
│   ├── agents\                    # ← 6 个岗位 [实测路径]
│   │   ├── director.md
│   │   ├── script.md
│   │   ├── storyboard.md
│   │   ├── visual.md
│   │   ├── video.md
│   │   └── qa.md
│   ├── skills\                    # ← 20 个专业能力 [实测路径]
│   │   └── <skill-name>\
│   │       ├── SKILL.md           #   必填：frontmatter(name,description) + body
│   │       ├── references\*.md    #   按需加载的专业细则
│   │       ├── templates\*        #   产出物骨架（json/md/yaml）
│   │       └── scripts\*.py       #   机械校验/转换，可执行不进上下文
│   └── hooks\                     # ← hook 脚本本体（被 settings.json 引用）
│       ├── check_file_naming.py
│       ├── protect_sources.py
│       └── log_asset_touch.py
├── rules\                         # ← 制度全文（人读 + AGENTS.md 引用 + 脚本实现）
│   ├── global.md
│   ├── continuity.md
│   ├── video.md
│   ├── file-naming.md
│   └── qa.md
├── workflows\                     # ← 生产线定义（我们自己的约定，平台不解析，由我执行）
│   ├── 01-script-to-bible.md
│   ├── 02-bible-to-storyboard.md
│   ├── 03-storyboard-to-image.md
│   ├── 04-storyboard-to-video.md
│   ├── 05-video-to-edit.md
│   ├── 06-final-qa.md
│   └── state_schema.md            # ← run_state.json 的唯一真源定义
├── tools\                         # ← 执行器封装（薄壳，不含创意）
│   ├── comfy.py                   #   8189 /prompt /history /free
│   ├── ff.py                      #   D:\AIWorkflow\tools\ffmpeg.exe 薄壳
│   ├── probe_media.py             #   时长/分辨率/fps/码率（无 ffprobe，用 cv2）
│   └── render_log.py              #   批次归档 + manifest
└── project\                       # ← 每部片子一个子目录（下例为仙女星系）
    └── xianlv\
        ├── 00_script\             #   剧本真源（你的 docx，只读）
        ├── 01_bible\              #   Project/Scene/Character Bible
        ├── 02_assets\             #   ASSET-*.json + 锚点图 + .anchor.json sidecar
        ├── 03_storyboard\         #   SHOT-*.json + 镜头表
        ├── 04_images\             #   首帧/尾帧
        ├── 05_videos\             #   单镜成片（批次目录）
        ├── 06_edit\               #   拼片/字幕/混音中间产物
        ├── 07_final\              #   成片 + 版本
        └── run_state.json         #   断点续跑状态（见 §6.3）
```

**[约定]** 与现有资产的关系：`E:\图像影音资源池\<项目>\` 仍是**交付层**（成片、批次归档），`D:\AI-Film-Studio\project\` 是**工程层**（结构化资料）。两边不重复存素材，工程层只存"能被引用和校验"的小文件 + 指向交付层的绝对路径。

---

## 3. Agent 层：6 个岗位完整定义

以下 6 份**可直接落盘**。每份 = frontmatter + 系统提示词。`skills` 字段引用共享库，不在 Agent 里复述专业内容。

### 3.1 `.qoder/agents/director.md`

```markdown
---
name: director
description: 总导演/制片总控。当需要判断项目当前处于哪个阶段、拆解任务、审核别
  的岗位产出、决定 PASS 还是 REWORK 时使用。不生成图片视频，不写代码。
model: performance
color: orange
effort: high
maxTurns: 12
tools: Read, Glob, Grep, Write
skills: cinematic-planning, shot-continuity, final-qa
---

你是总导演。你唯一的产出是**判断**和**派工单**，不是素材。

## 输入
被调用时你会拿到：项目目录路径 + 本次要评审的对象（阶段名或文件路径）。

## 你必须做的
1. 读 `project/<片>/run_state.json`，确认项目当前阶段与上一阶段产物清单。
2. 按 `workflows/` 对应阶段的 PASS 判据逐条核对产物，**每条给出 通过/不通过 + 证据路径**。
3. 判据不过时，写 REWORK 单：谁返工、返工到什么文件、重跑哪条 workflow。
4. 判据全过时，写 PASS，并产出下一步派工单 `0X_dispatch.md`。

## 派工单格式（必须机器可读）
| 任务ID | 交给 | 调用skill | 输入文件 | 期望产出 | 截止阶段 |

## 禁止
- 禁止亲自写分镜、提示词、代码、剪辑命令（那是别的岗位的活）。
- 禁止在没有证据的情况下说"看起来没问题"。
- 禁止修改 `00_script\`（剧本真源）与任何已 PASS 的产物。
- 禁止把"我建了个工具"当成进度（判据：这一阶段有没有产出可交付物）。

## 输出契约
返回一段文本，含：阶段名、逐条判据结果、PASS/REWORK 结论、派工单文件绝对路径。
```

> **[待验]** Director 的 `tools` 里没有 `Agent`，所以它**不能**自己开子 Agent。派工单由主会话执行。Phase 4 会测"子 Agent 能不能再开子 Agent"，若能，再把调度写进 prompt。

### 3.2 `.qoder/agents/script.md`

```markdown
---
name: script
description: 编剧/剧本分析师。当需要把剧本、小说、大纲转成结构化生产资料
  （Bible、场景表、人物表、时间线、冲突与伏笔）时使用。不做视觉设计。
model: inherit
color: blue
tools: Read, Glob, Grep, Write, Edit
skills: screenplay-analysis, character-bible, world-building, timeline-management
---

你是剧本分析师。输入是文字，输出是**结构化文件**，不是散文。

## 工作顺序
1. `screenplay-analysis` 拆场：每场一个记录（地点/时间/在场人物/事件/冲突/视觉元素）。
2. `character-bible` 建人物卡（身份/外貌/服装/年龄/性格/行为习惯/视觉锚/关系）。
3. `world-building` 补世界观与体系（只在剧本已隐含时归纳，不许自行发明设定）。
4. `timeline-management` 排时间线与伏笔回收点。

## 禁止
- 禁止改剧本真源（`00_script\` 只读）。
- 禁止为"更合理"而新增设定；发现矛盾就登记到 `01_bible\open_questions.md` 交导演判。
- 禁止写图片/视频提示词。

## 输出契约
`01_bible\project_bible.md`、`scene_table.json`、`character_table.json`、`timeline.md`。
每条设定必须标注出处（剧本第几场/第几段），无出处的一律进 open_questions。
```

### 3.3 `.qoder/agents/storyboard.md`

```markdown
---
name: storyboard
description: 电影分镜导演。当需要把场景转成镜头表（镜号/目的/景别/机位/构图/运镜/
  主体动作/环境变化/时长/转场/可生成性评估）时使用。
model: inherit
color: cyan
tools: Read, Glob, Grep, Write, Edit
skills: cinematic-storyboard, camera-language, shot-continuity, h3-video
---

你是分镜导演。你的产物必须**能被引擎直接消费**，不能只是一份好看的文档。

## 每个镜头必填字段（缺一即不合格）
id, scene, purpose, shot_size, camera, movement(type+amplitude+speed), subject_action,
environment_change, duration_sec, frames_at_24fps, transition, gen_feasibility,
assets_referenced(ASSET-ID 列表), depends_on(前一镜 id 或 null)

## 硬约束（来自 rules/video.md，不许违反）
- 单镜默认 5–10 秒；本地 H3 帧长必须在 124–362 帧之间，且自设上限 243 帧。
- 一个镜头只承载一个戏剧节拍；复杂动作先拆镜。
- 相邻镜的动作**相位不重叠**即可，不要求末态硬接。
- 每镜必须引用 ASSET-ID，禁止重新用文字描述已有资产。

## 禁止
- 禁止用"电影感""震撼"这类不可执行形容词替代具体机位与动作。
- 禁止设计"引擎做不到"的镜头（同框极远距离、一镜内多次主体互换）而不如实标注。

## 输出契约
`03_storyboard\shot_table.json`（机器读）+ `shot_table.md`（人读，由脚本从 json 生成，
两份不许手工分别维护）。
```

### 3.4 `.qoder/agents/visual.md`

```markdown
---
name: visual
description: 视觉设计/资产主管。当需要设计角色、舰体、载具、环境、道具、色彩基调、
  风格基线，并把它们固化为可复用 Asset（含锚点图与 sidecar）时使用。
model: inherit
color: purple
tools: Read, Glob, Grep, Write, Edit, Bash
skills: character-consistency, vehicle-consistency, environment-consistency, image-prompt
---

你是资产主管。你的核心动作是**把一次性的设计变成可引用的资产**，之后所有镜头只引用 ID。

## 每个 Asset 必须产出
- `02_assets\ASSET-<类>-<序号>.json`：id/kind/desc/ref_images/palette/lighting/banned_variants
- 锚点图本体 + `<图>.anchor.json` sidecar（character/role/裁切范围/可锁维度）
- 一句话"设计语言"（供 image-prompt 引用，替代长描述）

## 工作顺序
1. 先出**灰模/剪影/参数化**造型锚（构图靠锚，不靠文字——已实测文字控不住剪影）。
2. Canny/ControlNet 锁构图 → 出正式图。
3. 量一次结构能量（Laplacian 方差）与参考对比，写进 asset 记录。

## 禁止
- 禁止把"厚重感"理解成"堆细节"（细节是尺度的敌人）。
- 禁止用第三方素材的**脸**，只可借设计语言。
- 禁止覆盖已 PASS 的锚点图；要改就新建版本并在 state 里记 superseded_by。

## 输出契约
asset json + 锚点图 + `02_assets\asset_index.md`。
```

### 3.5 `.qoder/agents/video.md`

```markdown
---
name: video
description: AI 视频制作执行员。当需要把已确定的镜头表+资产变成实际视频（写视频
  提示词、调 H3/ComfyUI/云端引擎、轮询、抽帧自检、失败重试）时使用。
model: efficient
color: green
tools: Read, Glob, Grep, Write, Edit, Bash
skills: h3-video, video-prompt, video-continuity, video-qa
---

你是执行员。**镜头拍什么不由你决定**；你决定的是怎么让它稳定地做出来。

## 每个镜头的固定动作
1. 读 SHOT json + 引用的 asset，用 `video-prompt` 编译到目标引擎的原生格式
   （H3 用 integrated_multimodal_description/overall_soundscape/non_diegetic_music；
    Seedance 用官方分块；可灵图主驱动——三家语法不同，禁止互相套用）。
2. 提交前跑机械闸：帧长、分辨率、锚点存在性、md5 查重、逐槽身份核对。
3. 提交 → 轮询 → 落盘归档（批次目录 + manifest，参数必须进日志）。
4. 抽帧自检（首/中/末 + 动作关键点），按 `video-qa` 判 可用/重跑，重跑最多 2 次后升级给 QA。

## 禁止
- 禁止改分镜的镜头目的、时长、主体。
- 禁止裸脚本出片（不走引擎 = 无 args 日志、不进批次归档）。
- 禁止把同一张图挂进多个参考槽（曾因此四条全废）。
- 禁止用"首尾吻合"当动作正确的证据。

## 输出契约
`05_videos\` 批次产物 + 更新 `run_state.json` + 每镜一份 `review.md`（帧证据路径 + 判定）。
```

### 3.6 `.qoder/agents/qa.md`

```markdown
---
name: qa
description: 审片委员会。当需要对剧本/分镜/视觉/视频/成片做独立质检并给出可复核
  证据链时使用。默认只读，不修文件。
model: performance
color: red
effort: high
tools: Read, Glob, Grep, Write, Bash
skills: video-qa, final-qa, shot-continuity
---

你是质检员，立场是**怀疑一切已完成的声明**。你不接受"看起来没问题"。

## 判据分档（必须区分，混用即失职）
- completed：机器跑完了、文件存在、参数合法。
- confirmed：人审认可。**你无权给 confirmed**。
- 未查项必须显式列出，不许沉默。

## 四层检查
1. 工艺层：时长/分辨率/fps/码率/削顶/黑帧/字卡时间码。
2. 连续性层：跨镜主体位置、光位、道具形态、动作相位。
3. 叙事层：镜头是否服务场景目的、信息镜之间是否有呼吸镜。
4. 制度层：违反 `rules\*.md` 的条目（点名规则 ID）。

## 允许写
只允许写 `0X_qa.md`（报告）与 `open_issues.md`。要改产物必须开返工单，不自己动手。

## 输出契约
报告含：结论(PASS/REWORK)、逐条证据路径、未查项清单、返工建议。
```

### 3.7 工具权限矩阵（照抄即可，别放宽）

| Agent | Read | Grep/Glob | Write/Edit | Bash | 说明 |
|---|---|---|---|---|---|
| director | ✓ | ✓ | ✓ | ✗ | 只判断不执行 |
| script | ✓ | ✓ | ✓ | ✗ | 只写 bible |
| storyboard | ✓ | ✓ | ✓ | ✗ | 只写 shot_table |
| visual | ✓ | ✓ | ✓ | ✓ | 要跑生成/量测脚本 |
| video | ✓ | ✓ | ✓ | ✓ | 要提交渲染 |
| qa | ✓ | ✓ | ✓(仅报告) | ✓ | 只读+跑校验 |

> 放宽 `Bash` 就等于放弃"岗位不拥有全部工具"这条原则。若某岗确实需要新工具，改矩阵要写进 `rules/global.md` 的变更日志。

---

## 4. Skill 层：20 个专业能力

### 4.1 统一模板（每个 skill 都按这个写）

```markdown
---
name: <kebab-case 名，与目录名一致>
description: <一句话做什么 + 什么情况下必须用它（触发词/文件类型/阶段）。单行，≤1024 字符>
when_to_use: <可选，更短的自动匹配提示>
---

# <标题>

## When to Use
<1–2 句，具体到"拿到什么文件、在哪个阶段">

## Inputs / Output Contract
输入：<文件/字段>  输出：<文件/字段，机器可读>

## Patterns
<2–3 条可执行做法，每条带来源或实测依据>

## Anti-Patterns
<做过但被证伪的做法 + 为什么>

## Verification
<本 skill 产物怎么算合格；能机械判的指向 scripts/，不能判的写清人审点>

## Resources
<按需加载：references/*.md、scripts/*.py、templates/*>
```

**尺寸纪律 [官方]**：SKILL.md body 目标 400–1000 token，硬上限 1500；细则进 `references/`，>10k 字的文件要在 SKILL.md 里写 grep 检索模式。

### 4.2 20 个 skill 逐个定义

下表就是"20 个 SKILL.md 模板"的骨架清单：`name` 与 `description` 可直接抄进 frontmatter；`细则去处` 指 references 文件名（避免把专业内容堆进 SKILL.md）。

| # | skill | 级别 | 主要调用者 | 输入 → 输出 | description（frontmatter 直接抄） | 细则去处 |
|---|---|---|---|---|---|---|
| 01 | screenplay-analysis | L2 | script, director | 剧本文本 → scene_table.json | 把剧本/小说/大纲拆成结构化生产资料（场景、人物、事件、地点、时间、冲突、视觉元素）。当需要把文字剧本变成可被分镜消费的表格时使用。 | references/scene-granularity.md |
| 02 | character-bible | L2 | script, visual | 剧本 → character_table.json | 建立与维护角色圣经：身份、外貌、服装、年龄、性格、行为习惯、视觉锚、关系。当角色需要跨镜一致或需要定妆时先用它。 | templates/character.schema.json |
| 03 | world-building | L3 | script | 设定散点 → world.md | 归纳世界观、科技/军事/政治体系、地理与历史，并标注每条设定的出处。当项目需要自洽背景或发现设定冲突时使用。 | references/provenance-rules.md |
| 04 | timeline-management | L1 | script, qa | 场景表 → timeline.md | 维护剧情时间线、伏笔埋点与回收点、跨集因果。当需要检查时间顺序矛盾或伏笔未回收时使用。 | scripts/check_timeline.py |
| 05 | cinematic-planning | L4 | director, storyboard | Bible → 拍摄方案 | 判断一个场景应该怎么拍：幕的节奏、信息密度、呼吸镜位置、全景缺口。当分镜前需要定拍摄策略或分镜后诊断节奏时使用。 | references/pacing.md |
| 06 | cinematic-storyboard | L3 | storyboard | 场景 → shot_table.json | 把场景转成镜头表（目的/景别/机位/运镜/动作/时长/转场/可生成性）。当需要从剧本或 Bible 产出可执行分镜时使用。 | references/shot-grammar.md, scripts/validate_shot.py |
| 07 | camera-language | L3 | storyboard, video | 镜头意图 → 机位方案 | 选择并描述景别与运镜（wide/medium/close-up/POV/tracking/dolly/crane/orbit/push-in/pull-out），含幅度与速度。当镜头需要运镜但不知怎么描述时使用。 | references/movement-vocab.md |
| 08 | shot-continuity | L3 | storyboard, visual, video, qa | 相邻镜 → 接续表 | 检查并保证镜头之间的连续性：主体位置、光位、道具形态、动作相位、空间方向。当出现跳戏、方向错位、物体变形时使用。 | references/cut-point-table.md |
| 09 | character-consistency | L3 | visual, video | 角色卡 → 锚点方案 | 保证同一角色始终是同一人：脸锚/造型锚拆分、裁切范围、画风与身份分离、阈值实测。当角色跨镜变脸或换装时用它。 | references/anchor-rules.md |
| 10 | vehicle-consistency | L3 | visual, video | 载具卡 → ASSET-SHIP | 保持舰体/载具跨镜一致：结构、比例、主炮、舰桥、装甲、标识、灰模锚与剪影锚策略。当载具"越拍越不像"时使用。 | references/hard-surface.md |
| 11 | environment-consistency | L2 | visual, video | 场景卡 → ASSET-ENV | 保持环境跨镜一致：星球、基地、战场、天气、分层光影与雾度。当背景漂移、光照互斥时使用。 | references/scene-anchor.md |
| 12 | image-prompt | L2 | visual | Asset+构图 → 生图提示词 | 把视觉设计转成生图提示词并按引擎建适配器（FLUX/SDXL/Seedream/可灵/即梦）。当需要出首帧、定妆、设定表时使用。 | references/adapters-image.md |
| 13 | h3-video | L3 | video, storyboard | 镜头 → H3 任务 | 本地 MiniMax-H3 出片的能力边界与参数：帧长 124–362、默认 5–10 秒、步数/分辨率/显存、参考图槽位、失败类型。当用 H3 生成视频前必读。 | references/h3-limits.md |
| 14 | video-prompt | L2 | video | SHOT → 引擎原生提示词 | 把镜头编译为目标引擎原生提示词格式（H3 三字段/Seedance 分块/可灵图主驱动），含禁忌与互不套用原则。当要写视频提示词时使用。 | references/specs-by-engine.md |
| 15 | video-continuity | L3 | video, qa | 前后镜成片 → 接续判定 | 用实际成片（不是设计稿）检查跨段接续：末态/首态抽帧对比、光流方向、主体相位。当分段视频拼起来"不接"时使用。 | scripts/edge_diff.py |
| 16 | video-qa | L4 | video, qa | 单镜视频 → 可用/重跑 | 判断生成的视频能不能用：动作是否完成、主体是否崩坏、是否合分镜、是否糊/慢动作/闪烁。当每条视频出片后使用。 | references/failure-taxonomy.md |
| 17 | ffmpeg-editing | L2 | video, qa | 片段 → 成片 | 用本地 ffmpeg 做拼接、裁切、转码、调色、字幕、混音；含中文路径、filter 分号、limiter、fps 漂移等实测坑。当需要后期与拼片时使用。 | references/ffmpeg-gotchas.md |
| 18 | audio-planning | L2 | director, video | 镜头表 → 音轨方案 | 规划环境音/战斗音/机械音/音乐/对白层次与优先级，含"是否要 BGM"的决策规则。当处理声音设计时使用。 | references/mix-loudness.md |
| 19 | subtitle | L1 | video | 卡点表 → srt | 生成与维护字幕：场景卡 vs 对白、时间码计算、版式、烧录与外挂选择。当需要字幕或校对时间码时使用。 | scripts/gen_srt.py |
| 20 | final-qa | L4 | qa, director | 成片 → 验收报告 | 成片级验收：画面/声音/字幕/节奏/连续性/文件规范全查，输出证据链与未查项。当片子准备交付时使用。 | references/acceptance-checklist.md |

> 级别含义见 §8。**先建 8 个**（01/02/03/06/12/13/16/20），其余按需补 —— 一次建 20 个必然建出一堆空壳。

### 4.3 两份完整参考实现（照着这个水准写剩下的）

#### `.qoder/skills/h3-video/SKILL.md`

```markdown
---
name: h3-video
description: 本地 MiniMax-H3 视频生成的能力边界与参数手册。当要用 H3（fl2va/ref2va/
  参考视频）出片、估时长、排查失败、决定拆段或降分辨率时使用。
when_to_use: 提交任何 H3 渲染任务之前
---

# H3 本地出片

## When to Use
镜头已定、要把"能不能用 H3 拍出来"变成确定答案时。

## Inputs / Output Contract
输入：SHOT json（时长/主体数/动作/参考资产）
输出：可直接提交的引擎参数集 + 预计耗时 + 风险标注

## Patterns
1. **帧长**：124–362 帧硬闸；默认 5–10 秒；自设上限 243 帧，别顶格。
2. **速度**：1344×768/8步/4图实测 3.636 s/帧；864×1536 竖屏 124 帧 ≈4.5 s/帧。
   长序列有速度悬崖：226 帧 = 13.1 s/帧（16G 开始换页）→ 300 帧级必须拆段或降分辨率。
3. **模式**：fl2va=首帧(+尾帧夹)；ref2va=三锚点+8步+turbo LoRA+真实摄影画风锚。
   谁在画里就让谁说（对白归属跟随画面主体）。
4. **参考视频**：ref_videos 吃 IMAGE 帧序列，24fps/48–360 帧；代价 5s 镜约 15 分钟/条。
5. **超分在前，修脸永远最后**；CodeFormer 逐帧修脸是清晰度阶梯的中间层。

## Anti-Patterns
- 把同图塞进多个参考槽（md5 全等 = 四条全废过）。
- 只挂首帧却用六段全参考格式（基础三字段才是 fl2va 的格式）。
- 用电影/剧集成片当 reference_video（真人检测 + 版权 + 翻新判定）。
- 把客户端 FAIL 当渲染失败：先查 /queue，GET 超时会假失败而 GPU 仍在渲。
- 裸脚本出片：不进批次归档、不留 args，参数只活在对话里。

## Verification
提交前机械闸（scripts/preflight.py）：帧长∈[124,243]、锚点存在、槽位身份核对、
参考图 md5 互不相同。产物落盘后必须能在 manifest 里查到完整参数。

## Resources
references/h3-limits.md（显存/竖屏/音频/字幕烤入细节）、scripts/preflight.py
```

#### `.qoder/skills/shot-continuity/SKILL.md`

```markdown
---
name: shot-continuity
description: 检查并保证镜头之间的连续性（主体位置、光位、道具形态、动作相位、
  空间方向）。当出现跳戏、方向错位、物体换形、前后镜接不上时使用。
---

# 镜头间连续性

## When to Use
写完相邻两镜、或拿到两镜实际成片要判断能不能接时。

## Inputs / Output Contract
输入：相邻镜的 SHOT json 或**实际成片**（优先成片）
输出：切点表（前段实际末态｜后段实际首态｜方向/速度/支撑是否接续）+ 判定

## Patterns
1. **判据是"相位不重叠"**，不是"末态硬接"：同主体在相邻镜落在动作轨迹的不同段即可。
2. 场景抽成"场景锚定段"逐镜一字带上；光影分层写（近暗/中亮/远雾化）。
3. 跨镜道具从上一镜**成片抽帧**当 reference，提示词跟成片实际样子走，不跟设计稿走。
4. 接镜优先抽上一镜收尾帧当空间锚，且锚点"职责句"要写窄（只锁位置/形态）。
5. 方向错位诊断：先确认画框内谁是主体、光束起点在画内还是画外，再改提示词。

## Anti-Patterns
- 把九宫格当逐帧控制、把首尾吻合当动作正确、把光流上升当连贯。
- 拿"极远距离同框"当可行方案（模型做不到）。
- 抽帧含写实人脸当锚（会被真人检测拦）→ 换无人脸图或裁掉脸。
- 同一镜内混用两种画风。

## Verification
逐条填切点表；每条不接续要指出是"位置/方向/速度/支撑/形态"哪一维失败。

## Resources
references/cut-point-table.md、scripts/edge_diff.py（末帧/首帧像素与光流对比）
```

---

## 5. Rule 层：制度 + 强制机制

**核心原则：一条规则只有三种归宿 —— ① hook 机械阻断；② 脚本校验（阶段闸）；③ AGENTS.md 自觉。写不出归宿的规则就是装饰。**

### 5.1 `rules/global.md`

| ID | 规则 | 归宿 | 实现 |
|---|---|---|---|
| G-01 | 剧本真源与已 PASS 产物不可覆盖 | hook | `PreToolUse(Edit\|Write)` → 命中 `00_script\`、`locked\` 退出 2 |
| G-02 | 原始素材只复制不删除；删除前需人圈范围 | hook | `PreToolUse(Bash)` 匹配 `del \|rm \|Remove-Item` → 退出 2 |
| G-03 | Asset ID 不得擅自修改 | 脚本 | `tools/probe_media.py --check-index` 比对 `asset_index.md` |
| G-04 | 最终素材必须版本化（v1/v2…，旧版记 superseded_by） | 脚本 | 阶段闸校验文件名含版本段 |
| G-05 | 生成/外部调用优先走稳定 API，浏览器自动化仅兜底且需同意 | AGENTS.md | 自觉 |
| G-06 | 生产阶段提示词必须先给人过目；实验/对照阶段豁免 | AGENTS.md | 自觉（+ 阶段闸检查 `prompt_review.md` 存在） |

### 5.2 `rules/continuity.md`

| ID | 规则 | 归宿 |
|---|---|---|
| C-01 | 角色身份不可无依据改变（脸/发型；服装默认不锁死，点名"符合人设"才逐字锁） | 脚本（ArcFace 相似度 ≥0.5 门槛） |
| C-02 | 载具结构/比例/主炮位置不可无依据改变 | 人审 + 结构能量量测留痕 |
| C-03 | 空间关系与方向不可无依据改变（谁在画框哪一侧、光束起点） | 人审（切点表必填方向列） |
| C-04 | 时间线与因果不可无依据改变 | 脚本 `check_timeline.py` |
| C-05 | 同一镜内画风必须统一；画风+光影作为全片基线 | AGENTS.md + 阶段闸比对基线段 |

### 5.3 `rules/video.md`

| ID | 规则 | 归宿 |
|---|---|---|
| V-01 | 单镜默认 5–10 秒；H3 帧长 ∈[124,362]，自设上限 243 | 脚本 preflight（硬阻断） |
| V-02 | 复杂动作拆镜头；一镜一个戏剧节拍 | 人审（分镜闸） |
| V-03 | 禁止把 A 引擎提示词语法套到 B 引擎 | 脚本（按 prompt_kind 分派，格式不符即拒） |
| V-04 | 出片一律走引擎（留 args + manifest），禁止裸脚本 | hook `PreToolUse(Bash)` 匹配 `run_h3.py` 无 `--project` → 退出 2 |
| V-05 | 每镜重跑不超过 2 次，超过升级 QA | 脚本（state 计数） |
| V-06 | 运镜禁写器材名词（会被实体化渲进画面） | AGENTS.md + 提示词 lint |

### 5.4 `rules/file-naming.md`

```
PROJECT_SCENE_SHOT_VERSION[_KIND]
例：XNLV_S03_SH23_v7_first.png / XNLV_S03_SH23_v7.mp4
交付层批次目录：E:\图像影音资源池\<项目>\批次\<YYYYMMDD_HHMMSS>\
```
| ID | 规则 | 归宿 |
|---|---|---|
| N-01 | 新文件名必须匹配上面正则 | hook `PreToolUse(Write\|Edit)` → 不匹配退出 2 |
| N-02 | 镜号一律用生产编号（"镜N"= 生产编号，不是原片镜号） | AGENTS.md |
| N-03 | 判废/被取代素材搬进资源池并写 MANIFEST，保原相对路径 | 脚本 pool_reorg |

### 5.5 `rules/qa.md`

| ID | 规则 | 归宿 |
|---|---|---|
| Q-01 | 机器跑完只能记 completed，人审认可才记 confirmed | 脚本（state 字段枚举） |
| Q-02 | 未查项必须显式列出 | 报告模板强制列 |
| Q-03 | 交付必须给可打开的文件路径 | 阶段闸（文件存在 + 时长/分辨率合法） |
| Q-04 | 同族陷阱自查：买素材≠能力、枚举组合≠判断、连通≠双向可用、建机器≠成果 | AGENTS.md |

### 5.6 hook 落地示例（`.qoder/settings.json`）

```jsonc
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Edit|Write",
        "hooks": [{ "type": "command",
                    "command": "D:/AI-Film-Studio/.qoder/hooks/protect_sources.py",
                    "name": "protect-sources", "timeout": 20 }] },
      { "matcher": "Write",
        "hooks": [{ "type": "command",
                    "command": "D:/AI-Film-Studio/.qoder/hooks/check_file_naming.py",
                    "name": "file-naming", "timeout": 20 }] }
    ],
    "PostToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command",
                    "command": "D:/AI-Film-Studio/.qoder/hooks/log_asset_touch.py",
                    "name": "touch-log", "async": true }] }
    ]
  }
}
```

**[实测]** 事件名可用：`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`SessionStart`、`Stop`、`StopFailure`、`PreCompact`、`Notification`。退出码：`0` 通过、`2` 阻断（stderr 作为理由回灌给模型）、其他 = 警告不阻断。配置文件三档：项目 `.qoder/settings.json`、本地 `.qoder/settings.local.json`、用户 `~/.qoder/settings.json`。

---

## 6. Workflow 层：生产线

### 6.1 六条流水线的统一结构

每条 workflow 文件（`workflows/0X-*.md`）必须含这 6 节，缺一不可：

```
## 触发条件        什么时候允许进入（上一阶段必须 PASS）
## 输入            必须存在的文件/字段
## 步骤            谁(Agent) → 调哪个 skill → 产出什么（含并行段）
## 闸(Gate)        机械闸（脚本，硬阻断）+ 人审闸（谁看什么）
## PASS 判据       逐条可核对的断言
## REWORK 路由     不通过时退回哪一步、带什么信息
```

### 6.2 六条线一览

| 线 | 步骤（岗位·skill） | 机械闸 | 人审闸 | PASS 判据要点 |
|---|---|---|---|---|
| 01 script→bible | script·screenplay-analysis → script·character-bible/world-building/timeline → director·cinematic-planning | `check_timeline.py`、字段完整性 | 导演看设定自洽、矛盾清单 | 每场有 purpose+visual_elements；每条设定有出处；open_questions 全部有归属 |
| 02 bible→storyboard | storyboard·cinematic-storyboard(+camera-language/shot-continuity/h3-video) → qa·shot-continuity | `validate_shot.py`（字段+帧长+资产引用存在） | 导演审节奏 | 全镜字段齐；总时长∈目标±5%；无"做不到"的镜头未标注；全景/呼吸镜分布达标 |
| 03 storyboard→image | visual·image-prompt(+三个 consistency) → qa | 锚点存在性、分辨率合法、md5 查重 | 人审首帧（构图/画风/接触关系） | 每镜首帧存在且引用 asset；画风与基线一致；锚点 sidecar 完整 |
| 04 storyboard→video | video·video-prompt → h3-video 提交 → video-qa(+video-continuity) | `preflight.py`（V-01/V-03/V-04） | 抽帧 sheet 人审 | 每条有 manifest+args；端点差、动作完成度、主体不崩；重跑≤2 次 |
| 05 video→edit | video·ffmpeg-editing(+audio-planning/subtitle) → qa | `probe_media.py`（时长/fps/削顶/黑帧） | 人审整片 | 成片时长=Σ镜+黑场；音轨 mean/peak 达标；字幕时间码由脚本实算非手写 |
| 06 final-qa | qa·final-qa → director 终审 | 验收清单脚本 | 人审（审片区） | 四层检查全过；未查项为 0 或已声明；交付路径可打开 |

### 6.3 状态机（断点续跑的唯一真源）

`project/<片>/run_state.json`：

```jsonc
{
  "project": "XNLV", "stage": "04-storyboard-to-video",
  "shots": {
    "SH23": {
      "storyboard": {"status": "confirmed", "sec": 7, "frames": 175},
      "first":  {"status": "confirmed", "file": "E:\\...\\previzctrl_...png", "anchor": "ASSET-SHIP-001"},
      "video":  {"status": "completed", "file": "E:\\...\\xn_..._00001_.mp4",
                 "version": "v7", "seed": 12, "engine": "h3_fl2va", "retries": 2},
      "qa":     {"verdict": "PASS", "evidence": ["...sheet.jpg"], "unchecked": ["声音"]}
    }
  },
  "gates": {"01": "PASS", "02": "PASS", "03": "PASS", "04": "IN_PROGRESS"}
}
```

规则：**status 只有 `pending/completed/confirmed/rejected` 四值**（Q-01）；任何脚本只读它、只写自己那一格；重跑不删旧版本，写 `superseded_by`。

---

## 7. Tool / MCP 层（本机实测在册的执行器）

| 执行器 | 入口 | 用途 | 注意 |
|---|---|---|---|
| ComfyUI | `http://127.0.0.1:8189`（0.35.1）+ `D:\AIWorkflow\engine\run.py --project <片>` | FLUX/SDXL 出图、H3 出视频 | 跑完要 `POST /free`，否则常驻 11GB 显存；`--set ref_images=` 必须裸路径 |
| ffmpeg | `D:\AIWorkflow\tools\ffmpeg.exe`（带 scdet/mestimate/vidstab） | 后期/量测 | 无 ffprobe → 时长用 cv2；中文路径要 cd 相对路径；filter 链用 `;` |
| arkcli | 火山方舟：Seedream 出图、`+gen --input @路径` 挂参考 | 定妆/首帧（"偶像感"本地做不到） | SSO 挂不代表通道废，先探针；落盘固定名要逐张改名 |
| 可灵 CLI | `node dist/cli.js`（git-bash shim 坏） | 图主驱动视频、i2i human_fidelity | 只走官方 CLI，禁止直连端点 |
| 即梦 CLI | `~/bin/dreamina.exe` | i2i（按张扣积分） | 只回 URL 需自行下载；无负面词参数 |
| bl（百炼） | `bl image/video/speech/vision` | TTS、图/视频、检索 | token-plan key 已 401；TTS 用按量付费 dashscope key |
| 本机 TTS | cosyvoice-v2（按量 key）/ F5-TTS（本地克隆） | 配音 | 中文 payload 走 JSON 文件 |
| MCP | 会话内 `mcp_list/mcp_get/mcp_call` | 浏览器、sites、computer-use、qmind 等 | **[实测]** Agent frontmatter 无 `mcpServers`，MCP 是 CLI 级共享，不能按岗位隔离 |

---

## 8. Skill 分级 L1–L4（决定写多细、要不要脚本）

| 级 | 类型 | 判据 | 必须有什么 | 例 |
|---|---|---|---|---|
| L1 | 规则型 | 能一句话说清、可完全机械判定 | `scripts/` 校验器 | file-naming、subtitle、timeline-management |
| L2 | 流程型 | 步骤固定、参数可变 | `templates/` + 步骤清单 | image-prompt、video-prompt、ffmpeg-editing、audio-planning、world-building |
| L3 | 专业型 | 需要领域知识、经验决定选型 | `references/` 细则 + 反例 | cinematic-storyboard、三个 consistency、camera-language、shot-continuity、video-continuity、h3-video |
| L4 | 决策型 | 输出是判断，无法自动判定 | 判据清单 + 强制"未查项"栏 | cinematic-planning、video-qa、final-qa |

**升级/降级规则**：L3/L4 里出现"可稳定判定"的部分，就下沉到 L2 + 脚本；L1 脚本误报率高就升 L2 并加人审点。**降级方向永远优先**（能机械判的别留给人）。

---

## 9. Phase 0–9 施工步骤与验收标准

每个 Phase 都有：**动作 / 产物 / 怎么测（命令级）/ PASS 判据 / REWORK 触发**。任何一条不满足就停在本阶段，不许"先往下搭再说"。

### Phase 0 — 基础环境验证
- 动作：核对驱动、显存、Python、ffmpeg、ComfyUI 8189、Qoder 版本、各 CLI 登录态。
- 产物：`env_report.md`（每项一行：值 + 采集命令）。
- 测：`nvidia-smi --query-gpu=...`；`py -V`；`ffmpeg -version`；`curl http://127.0.0.1:8189/system_stats`；`arkcli auth status`；可灵 `node dist/cli.js who_am_i`；`bl auth status`。
- **PASS**：全部有真实输出；每项标注"可用/降级/不可用"；不可用项写明兜底方案。
- REWORK：任何"我估计能用"而未实测的项 → 不合格，补测。

### Phase 1 — Agent 机制可行性验证（先验证平台，再建资产）
- 动作：只建**一个** `director.md`（内容照 §3.1），跑 `/agents reload`。
- 测：① `@director 报告你的 skills 与 tools`；② 让它读一个不存在的文件，看是否被工具限制拦住；③ 在子 Agent 里要求它调用另一个 Agent，记录是否可能。
- **PASS**：① 岗位被识别且能调用；② 未声明的工具确实不可用；③ 嵌套调度能力有明确结论（能/不能，附证据）。
- REWORK：`@director` 不可用 → 检查路径/frontmatter 语法；若平台不加载项目级 agents，改用户级 `~/.qoder/agents/` 再测，并把结论写进本手册 §0.1。

### Phase 2 — 项目文件体系 + 命名规则
- 动作：建 §2 目录树（空目录 + README 占位），写 `rules/file-naming.md`，落 `check_file_naming.py`。
- 测：故意写三个非法文件名（无版本段、错镜号、覆盖 locked），看 hook 是否退出 2 阻断。
- **PASS**：三个非法用例全部被拦且 stderr 理由可读；合法用例全部通过；`run_state.json` 按 §6.3 schema 能被脚本读回。
- REWORK：hook 不生效 → 检查 `settings.json` 是否被更高优先级文件覆盖（**[实测坑]** 你服务器上 sysctl drop-in 被符号链接静默覆盖过，同类问题本地也会犯：项目/本地/用户三档要看谁赢）。

### Phase 3 — 第一批 8 个 Skill
- 动作：01/02/03/06/12/13/16/20 各建 `SKILL.md`（§4.1 模板），L3/L4 至少各带一份 `references/`。
- 测：`/skills list` 出现 8 个；逐个 `/skill-name` 手动调用一次；每个 skill 的 token 量估算（≤1500）；跑 `validate_shot.py`、`preflight.py`。
- **PASS**：8 个都能被调用并返回**契约形状**的输出；无 TODO 残留；目录名==name 字段；无 README/CHANGELOG 之类冗余文件；SKILL.md body ≤500 行。
- REWORK：输出不成形状 → 补 templates/；把细则堆进 SKILL.md 超限 → 拆 references/。

### Phase 4 — Director 上线（只调已验证 skill）
- 动作：Director 挂上 Phase 3 的 8 个 skill，喂一个**真实小样**（仙女星系第 3 幕 3 个镜头）。
- 测：让它出一份 `dispatch.md`；再故意喂一份"字段缺失的 shot_table"，看是否判 REWORK。
- **PASS**：正常样 → 派工单每行含任务ID/交给/skill/输入/期望产出；异常样 → 明确指出缺哪几项并给 REWORK 路由，**没有**顺手替别人补写。
- REWORK：Director 开始自己写分镜/跑命令 → 收紧 prompt 与 tools，重测。

### Phase 5 — 剧本 → 分镜 打通
- 动作：script + storyboard 上岗，跑 01、02 两条 workflow 于一个真实场景（≤6 镜）。
- 测：`validate_shot.py` 全绿；人工对比"镜头是否服务场景目的"；总时长与目标偏差。
- **PASS**：机械闸 0 报错；每镜 purpose 非空且互不重复；无未标注的"引擎做不到"镜头；人审一次通过。
- REWORK：出现"枚举海量分镜代替判断"（一次给几十镜）→ 判废，回到 cinematic-planning 先定策略。

### Phase 6 — 分镜 → 图片/Asset 打通
- 动作：visual 上岗，跑 03 线；每个被引用 ASSET 建 json + 锚点 + sidecar。
- 测：首帧出图后跑量测（结构能量、构图与锚点一致性）；文字描述与锚点各出一版对照，确认构图来自锚不是文字。
- **PASS**：每镜首帧存在且可追溯到 ASSET-ID；画风与全片基线段一致；锚点 sidecar 完整（character/role/裁切/可锁维度）；对照实验证明"改锚有效、改文字无效"。
- REWORK：脸锚人脸 <300px（启发式，需带限定词）→ 重拍拉近而非提分辨率；锚点画风≠目标画风 → 补"仅锁人物、画风按 X 渲染"声明。

### Phase 7 — 分镜 → 视频 打通
- 动作：video 上岗，跑 04 线；先探针（1 镜）测速，再按批次开跑。
- 测：`preflight.py` 阻断一条超长/一槽位重复的任务；探针实测 s/帧 与预估偏差 <20%；每条产物 manifest 里有完整 args。
- **PASS**：探针通过才允许整批；批次内每条有 review sheet（首/中/末+关键点帧）；重跑计数生效；**开炮/落点这类"动作完成"必须在镜内可见**（本次 v5 的教训：上一镜充能、下一镜光束已扫完=错位）。
- REWORK：客户端 FAIL 先查 `/queue` 再判真假失败；长序列速度悬崖 → 拆段或降分辨率，不许硬顶。

### Phase 8 — QA 独立跑起来
- 动作：qa 上岗，对 Phase 7 的产物做盲检（不给结论提示）。
- 测：**注入三个已知缺陷**（错时间码字幕、一条 240 帧超限、一张重复锚点），看 QA 是否各自抓到并点名规则 ID；再给一条完全正常的，看是否误报。
- **PASS**：三缺陷全中（100% 召回）、正常样零误报、报告含 completed/confirmed 区分与未查项栏。
- REWORK：漏检 → 补 `scripts/` 机械闸（能机械判的不许依赖模型自觉）。

### Phase 9 — 完整 Workflow 串联 + 回归
- 动作：05、06 两条线补齐，端到端跑一部**短片样片**（≤5 镜，从零到成片）。
- 测：`run_state.json` 全程可断点续跑（中途 kill 再 resume）；成片时长=Σ镜+黑场；音轨 mean/peak 达标且**无人声**（对齐相减残差回到编码底噪）；字幕时间码由脚本实算；交付路径可打开。
- **PASS**：端到端一次跑通 + 一次断点续跑成功 + 上述四项机器核对全绿 + 人审在审片区给 confirmed。
- REWORK：任何"手工补一次才通过"的环节 → 记为漏洞，回 Phase 2/8 补闸，不许靠人肉兜底交付。

### 9.1 一页验收总表（打印贴墙）

| Phase | 一句话 PASS |
|---|---|
| 0 | 每个执行器都有真实输出，没有"估计能用" |
| 1 | `@director` 能调用、工具限制真生效、嵌套调度有结论 |
| 2 | 三个非法命名用例全被 hook 拦下 |
| 3 | 8 个 skill 全可调用且输出成契约形状 |
| 4 | Director 只派工不代做，异常样能判 REWORK |
| 5 | 分镜机械闸 0 报错 + 人审一次通过 |
| 6 | 构图来自锚不是文字（有对照证据） |
| 7 | 探针过才开批；动作完成在镜内可见 |
| 8 | 三注入缺陷全中、正常样零误报 |
| 9 | 端到端 + 断点续跑 + 音画字幕机器核对全绿 |

---

## 10. 与你现有资产的对接（不推倒重来）

| 现有 | 迁到 | 做法 |
|---|---|---|
| user-level skill `cinematic-video-production` + 19 份 references | 拆进 §4 的 20 个 skill | references 按主题归口（`prompt-specs-by-engine.md`→video-prompt；`combat-motion-continuity.md`→shot-continuity；`keyframe-pairing.md`→video-continuity；`local-render-budget.md`→h3-video；`script-and-qc.md`→video-qa/final-qa）。原 skill 保留为"总则/入口"，不重复内容 |
| `D:\AIWorkflow\engine\workflows\*.yaml`（previz_control / h3_i2va_batch） | Tool 层（不是 Workflow 层） | 引擎 yaml 是"怎么执行"，属设备；`workflows/0X-*.md` 是"什么时候执行"，属流程。两层不许混 |
| 项目脚本 `run_all.py` / `post.py` / `gen_*.py` | 逐步抽成 skill 的 `scripts/` | 抽的时候把"一次性硬编码"换成 SHOT/ASSET 输入；`gen_review.py`（时间码由脚本实算）就是标准范式 |
| 审片区（你网站 `/review/<token>/`，nginx Range） | Phase 9 的人审闸载体 | 保持：成片放网站看、他回对话写镜号、我按镜号单镜重渲 |
| `偏差台账.md` / `open_questions.md` | Rule 层与 QA 报告的数据源 | completed/confirmed 判定与未查项都从这里取 |

---

## 11. 风险与未决（诚实清单）

| # | 风险 | 现状 | 处置 |
|---|---|---|---|
| R1 | 子 Agent 能否再开子 Agent、能否直接与人对话 | **[待验]**，Phase 1 测 | 测不过就永久采用"派工单 + 主会话执行"模式，Director 不做运行时调度 |
| R2 | Agent frontmatter 无 `mcpServers` | **[实测]** 装机文档无此字段 | MCP 只能 CLI 级共享；岗位隔离靠 tools + hook + 凭证文件权限 |
| R3 | skill 的 `tools` / `allowed-tools` 是否真生效 | 官方 skill-creator 写 `tools`，内置 skill 里见到 `allowed-tools`；行为未测 | Phase 3 加一条测：带受限 tools 的 skill 调用被禁工具，看是否真拦 |
| R4 | 20 个 skill 一起建 = 空壳风险 | 你原文也提醒了 | 严格按 Phase 3 只建 8 个，其余按需 |
| R5 | Rules 写成 md 就以为生效 | 常见失败模式 | §5 每条必须填"归宿"列，空归宿的规则当场删 |
| R6 | L4 决策型 skill 的判定不可自动验证 | 本质如此 | 强制"未查项"栏 + 人审 confirmed；不许用 completed 冒充 |
| R7 | 本地 H3 长序列速度悬崖 / 显存常驻 | **[实测]** | V-01 硬闸 + 探针先行 + `POST /free` |
| R8 | 云端通道凭证漂移（token-plan 401、SSO 需续期） | **[实测]** | Phase 0 每项标"可用/降级/不可用"+兜底；凭证闸门交还你本人 |

---

## 12. 施工顺序建议（给你拍板用）

1. 先只做 **Phase 0 + Phase 1**（半天内，零风险，不动现有片子）。产出：平台能力结论 + 第一个能用的 `@director`。
2. 通过后再做 Phase 2 + 3（制度与 8 个 skill）。
3. Phase 4–8 用仙女星系现成的 32 镜当回归样本，不新起片子。
4. Phase 9 才谈"端到端自动跑一部新片"。

> 一句话：**先证明平台能撑起岗位，再往岗位里灌专业能力，最后才连成线。** 顺序颠倒就是 V1.0 的老毛病。
