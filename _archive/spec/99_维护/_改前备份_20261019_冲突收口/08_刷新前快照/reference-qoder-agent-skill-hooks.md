---
name: reference-qoder-agent-skill-hooks
description: Qoder 桌面端 Custom Agent / Skill / Hook 三层真实能力核实（字段表、路径、reload、退出码）＋**自定义模型供应商接法（settings.json providers / UI「自定义 Base URL」、视觉与上下文窗口开关）**，写多 Agent 架构或接外部模型前必读
metadata:
  type: reference
---

# Qoder 平台能力实测（Agent / Skill / Hook）

**Why**：2026-09-23 写《V1.1 实施手册》时逐条核对本机装机的官方内置说明，发现若干"看起来支持、实际没有"的地方。这些差别直接决定多 Agent 系统能不能跑起来，所以单独存档。

**How to apply**：任何"给 Qoder 搭 Agent/Skill/Rule"的工作，先按本表核对字段与路径，别照外部文章或上一版设计文档写。文档真源＝`E:\Qoder\.qoder-versions\0.3.4\resources\app.asar.unpacked\node_modules\@qoder-ai\qoder-agent-sdk\dist\_worker\builtin\{agent-creator,skill-creator,hook-config}\SKILL.md`。

## Custom Agent

- 路径：`<project>/.qoder/agents/<name>.md`（优先级高）与 `~/.qoder/agents/<name>.md`（用户级，跨项目）。
- 必填 frontmatter：`name`、`description`。
- 可选：`tools`、`disallowedTools`、`model`、`color`、`maxTurns`、`timeoutMins`、`effort`、`skills`。
- **没有 `mcpServers` 字段**。MCP 是 CLI 级配置（`~/.qoder/mcp-router.json` 一类），所有 Agent 共享，不能按岗位隔离。要限制"谁能碰什么设备"只能靠 `tools` + hook + 凭证文件权限。
- `model` 只接受**档位**：`inherit`(默认) / `lite` / `efficient` / `auto` / `performance` / `ultimate`。**不接受任意厂商模型名**（写 `Qwen3.8-Max` 无效）。真要用某家模型走 MCP/CLI（arkcli、bl、可灵 CLI），不是改 frontmatter。
- `effort`：`low/medium/high/max`。
- 生效方式：`/agents reload`，调用 `@agent-name <任务>`。
- 内置工具名（可写进 tools）：`Bash` `Read` `Write` `Edit` `Glob` `Grep` `WebSearch` `WebFetch`。不写 = 继承默认。
- **[待验]** 子 Agent 能否再开子 Agent、能否直接与用户对话——本会话可见的 subagent_type 只有 `Explore`/`Plan`/`general-purpose`。未测通之前，把"调度型 Director"设计成"评审 + 产出派工单"，由主会话执行派工。

## Skill

- 路径：`<project>/.qoder/skills/<skill-name>/SKILL.md` 与 `~/.qoder/skills/<skill-name>/SKILL.md`（用户级已验证可用：本机 `~/.qoder/skills/cinematic-video-production/` 正常被加载）。
- frontmatter：必填 `name`（kebab-case，须与目录同名）、`description`（**单行**、≤1024 字符、要同时说清"做什么"和"何时触发"）；可选 `model`、`tools`、`when_to_use`、`argument-hint`、`arguments`。
- **[待验]** 内置 skill 里还见到 `allowed-tools` 写法（agent-creator/hook-config 自己用了），与 skill-creator 文档写的 `tools` 并存，实际生效哪个未测。
- 官方约定的资源子目录是 `scripts/`、`references/`、`assets/`（**不是**平铺 `REFERENCE.md`/`EXAMPLES.md`）。大文件要在 SKILL.md 里写 grep 检索模式。
- 尺寸纪律：body 目标 400–1000 token、硬上限 1500；SKILL.md < 500 行；单任务最多加载 3 个 skill。
- 不要造多余文件（README/CHANGELOG 等）。
- 生效方式：`/skills reload`、`/skills list`、`/<skill-name>`。

## Hook（Rule 层唯一的机械强制手段）

- 配置文件三档：项目 `.qoder/settings.json`、本地 `.qoder/settings.local.json`、用户 `~/.qoder/settings.json`。**改之前先确认哪一档赢**——同类坑在他服务器上见过（sysctl drop-in 被 `99-sysctl` 符号链接静默覆盖，见 [[reference-user-website]]）。
- 结构：`{"hooks":{"<Event>":[{"matcher":"<regex 匹配工具名>","hooks":[{"type":"command","command":"...","name":"...","timeout":N}]}]}}`。
- 事件：`PreToolUse` `PostToolUse` `PostToolUseFailure` `SessionStart` `Stop` `StopFailure` `PreCompact` `Notification`（另有 `TeammateIdle` 用于多 Agent 团队）。
- **退出码语义：`0` 通过／`2` 阻断（stderr 作为理由回灌给模型）／其他 = 警告不阻断**。JSON 输出里 `decision:"deny"` 或 `continue:false` 同样阻断。
- `async:true` = 后台不阻塞；`asyncRewake` + 退出 2 可唤醒模型（配 `rewakeMessage`/`rewakeSummary`）。
- 适用：guardrail（保护源文件、拦 `rm`/`del`）、命名规范闸、记账日志。**hook 里只做确定性判定**（路径正则、命令黑名单、secret 特征），别指望它做语义判断。

## 自定义模型接入（2026-09-25 实测 + 官方文档核对）

**结论：Qoder 有一个平台级的自定义供应商机制，与 agent frontmatter 的 `model` 档位是两套东西，别混。** frontmatter 的 `model` 仍只收档位；外部厂商模型是加在**模型选择器**这一层的。

- **落盘位置＝`~/.qoder/settings.json` 的 `providers` 对象**（本机已存在 3 个 DeepSeek 条目，可作 schema 参照）：
  `"qoder-custom-<uuid>": { "baseUrl": "...", "apiKey": "...", "type": "openai-compatible", "protocol": "openai", "authType": "bearer", "model": "<默认模型>", "models": [ { "model", "displayName", "contextWindow", "maxOutputTokens", "capabilities": { "vision": bool, "thinking": { "modes", "supportsEffort", "supportedEffortLevels" } } } ], "displayName": "..." }`
- **UI 路径（官方文档）**：Qoder 设置 → 左侧「模型」→「+ 添加」→ 两条路：①**预置供应商**（含 MiniMax / DeepSeek / 阿里云百炼 / 智谱 / Kimi / OpenAI / Google / OpenRouter 等，只填 API Key）；②**自定义 Base URL** →「供应商」→「自定义」组 → **OpenAI Compatible**（再选 Chat Completions API 或 Responses API）或 **Anthropic Compatible**。填「接口地址（Base URL）」+ API Key + 至少一个 Model ID（可加多个）→ 下一步填「显示名称」「支持的上下文窗口/默认上下文窗口」「**视觉**」开关、「思考模式/思考强度」→「**校验并添加模型**」（会当场发请求验证，失败即不保存）。
- **自定义模型不消耗 Qoder Credits**，费用由厂商 API 账户直接结算。例外：Repo Wiki 永远用固定模型、消耗 Credits。
- **踩坑提醒**：预置供应商的 host 是写死的，**厂商在不同区域用不同域名时（如 MiniMax 的 `.cn` vs `.io`），预置那条会指错 host** → 用「自定义 Base URL」才可控。
- **[待验]** 自定义 provider 的模型能否写进 agent frontmatter 的 `model`——未测，别假设可以。

## Rule 的三种归宿（写不出归宿的规则＝没有规则）

1. **hook 机械阻断**（PreToolUse 退出 2）——可确定性判定的禁令。
2. **阶段闸脚本**（workflow 显式调用）——参数范围、字段完整性、文件存在性。
3. **`AGENTS.md` 自觉层**——只有语义/审美判断做不到的那部分。

平台**没有** `.qoder/rules/` 原生目录，`rules/*.md` 只是我们自己读的制度全文。

相关：[[reference-shortdrama-skill-blueprint]]、[[feedback-review-production-prompts]]、[[project-production-pipeline]]


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- 地基核实：agent frontmatter **没有 mcpServers**、model 只收档位、rules 无原生目录、hook 退出码 2＝阻断
- **★自定义模型＝settings.json providers(openai-compatible) / UI「自定义 Base URL」＋视觉开关**


## skill 的随装随卸（2026-09-30 实测）

- 读取位置**至少四处**（09-30 逐个核过）：① 用户级 `C:\Users\若水\.qoder\skills\<name>\SKILL.md`（现 57 个）；
  ② **别的厂商 CLI 根**——`C:\Users\若水\.bailian\skills\`（现 15 个：`bailian-*`／`spark-video`／`vox-video-director`／
  `dreamina-canvas-cli`／`happyhorse-prompt-studio`／`financial-expert`／`novel-game`），这些**不在 .qoder 下但照样进列表**；
  ③ 插件根（`Presentations`／`sites`／`browser-use`／`qoder-*`，在 `.qoder\plugins\`）；④ 项目级 `<工作目录>\.qoder\skills\`。
  **目录名必须 == frontmatter `name`**，否则不认。
- ★**新开会话不等于干净状态**：技能是**目录级全局**的，跟会话无关，任何新会话都会把这四个根重聚一遍（起手 80＋条）。
  想按通道隔离要靠**分工作目录**而不是分会话——09-30 用一次性探针实测：只往本会话工作目录
  `.qoder\skills\scope-canary-jiemeng\SKILL.md` 放一份（用户级没有），**下一轮列表里就出现了它**
  ⇒ 项目级独立生效，`E:\创作\即梦工作区` 与 `D:\AIWorkflow\H3工作区` 各放各的即可并行不串台。
  ⚠ 但项目级是**加法不是减法**：用户级那 57 条仍会出现在每个会话里，要真隔离得把它们从用户级摘走（需用户点头）。
  ⚠ 反过来说明为什么不能用装卸做并行隔离：`pack.py` 动的是用户级全局目录，A 会话一卸，B 会话下一轮就看不见。
- **装卸＝复制／搬移目录**，我用普通文件工具就能做：装＝copytree 进去；卸＝`shutil.move` 到别处（**只搬不删**）。
- **刷新时机＝按轮**：本轮复制进去的 skill，本轮的可用列表里就能看到（09-30 一次装 14 个当场生效）；
  本轮卸掉／装回的，要到**下一轮**的列表里才反映出来。所以"卸了立刻验证"要看盘上目录，别看列表。
- 官方工具 `mcp__builtin__skill_manage`（action=create/patch/edit/delete）：create 不覆盖已有、
  patch 要唯一命中、edit 自动留备份、**delete 进系统回收站且永不永久删**；内置与插件 skill 改不了。
  写单个 SKILL.md 优先用它；批量装卸用文件工具。
- 现成的分支机制：`E:\创作\即梦技能包\pack.py`（status／which／use／install／uninstall／restore／prompts／doc），
  整树 sha256 比对判「在装／未装／漂移」，漂移要 `--fix` 显式覆盖且覆盖前现场进 `removed\`。

## 09-30 用户对"要不要按通道重排技能"的裁定：**先不动**

我把"分工作目录隔离（即梦工作区／H3 工作区）＋把创作类从用户级摘走"两个方案摆出来请他选，他回**「那先不动嘛」**，
接着直接改去做四臂实跑。⇒ **现行态保持**：14 个即梦 skill 仍在用户级 `~/.qoder\skills`，分支包只当母本与随装随卸的工具，
**没有**建工作区级 `.qoder\skills`，也**没有**从用户级摘走任何创作类技能。
**How to apply**：以后别再主动提议"要不要把技能拆到各项目"——这条他已经看过并选择不动；真要动，得是他先提场景（并发跑两条通道且互相干扰）再谈。
