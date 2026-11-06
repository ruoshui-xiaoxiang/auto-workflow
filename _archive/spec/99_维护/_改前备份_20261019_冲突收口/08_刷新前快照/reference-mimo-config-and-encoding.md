---
name: reference-mimo-config-and-encoding
description: MiMo（mimocode）本机配置与编码坑——PS 5.1 写 jsonc 带 BOM 会打死整份配置、读写中文都会错；open-websearch 实测用法；以及它家记忆注入的真实落点是 AGENTS.md
metadata:
  type: reference
---

# MiMo（小米 mimocode）配置与编码坑

10-17 实测。起因：另一个 agent 把 open-websearch 装进 MiMo 后，用户在 MiMo 里看不到自己配的自定义 API。

## 现象的真因＝BOM，不是数据丢失

- MiMo 配置文件 `~/.config/mimocode/mimocode.jsonc` 被 PowerShell 重写后头三字节变成 `EF BB BF`（PS 5.1 `-Encoding UTF8` 必带 BOM）+ CRLF + 冒号对齐缩进。
- MiMo 的 jsonc 解析器不吃 BOM，日志实证（`%APPDATA%\Xiaomi MiMo\logs\YYYY-MM-DD.log`）：
  `mimocode.jsonc 不是合法 JSON:第 1 行第 1 列附近(InvalidSymbol)……已中止写入以免覆盖你的配置`
- **一个 BOM 打死整个文件**：3 条 provider（含 apiKey）与全部 MCP（skillsmp / playwright / notion / 飞书 / 新装的）一起不加载。表现为"我配的都不见了"，其实盘上全在。
- 剥掉 BOM 后同一份文件 `JSON.parse` 直接通过。判"配置丢了"之前先 `head -c 3 | xxd`。

## 同一次重写附带第二处损伤：中文二次解码

PS 5.1 `Get-Content` 默认按 GBK 读 UTF-8 再写回 → `"千问"` 变成 `"鍗冮棶"`。
🔴 别心算码位：我按 hex `E9 8D 97` 手算成 U+9317，盘上实测是 **U+9357 U+51AE U+68F6**；匹配一律用实测 codepoint 转义。
干净原字可从同目录 `.bak_*` 里取。

## 修法（已做，可复用）

只动必要字节：剥 BOM → 还原名字 → 改一处路径；先备份 `mimocode.jsonc.bak_before_bomfix`；写前断言「目标串各出现 1 次」，写后断言「无 BOM + JSON.parse 过 + provider 3 条 & apiKey 3 把 & mcp 5 条」，任一不过即用备份还原。改完与备份做「忽略空白的逐行 diff」确认只有预期 2 行变化。
脚本在会话目录 `fix_mimo_config.mjs` / `verify_config.mjs`（一次性，逻辑就上面三条断言）。

## 读侧也是坏的：PS 5.1 连正确文件都读错（10-17 10:04 实测）

对**修好的无 BOM UTF-8 文件**取 `provider.alibaba-cn.name`：node 按 UTF-8 读到 `U+5343 U+95EE`（千问），
PS 5.1 `Get-Content -Raw`（默认 ANSI/936 码页）读到 `U+9357 U+51AE U+68F6`。
⇒ 乱码不是"写的时候编码选错"，是**读的那一刻就已经错了**，写回只是固化。规矩因此是 **读写都别用 Windows PowerShell 5.1**（PS 7 才把默认改对）。

## 🔴 假绿机制：它的自检尺子和消费方的尺子不是一把

肇事 agent 收尾自述里有一条「配置 JSON 校验通过 ✅」，用的命令是 `Get-Content -Raw | ConvertFrom-Json | Out-Null`。
实测：**同一份带 BOM 的文件，PS 5.1 `ConvertFrom-Json` 返回通过，MiMo 的 jsonc 解析器必失败**。
⇒ 验配置只能拿**真正读它的那个程序**验（本例＝重启 MiMo 看日志有没有 `InvalidSymbol`）；拿另一种解析器验＝没验。
同族见 [[feedback-evidence-loop-trap]]、手册 §五「验收闸要与判据同一把尺」。

## 取证做法（这次靠它把归因钉死）

会话全量在 sqlite：`~/.local/share/mimocode/mimocode.db`（`session` / `message` / `part` / `history_fts` 四张表够用；`message.data` 里有 `providerID`/`modelID`/`mode`/`agent`/`cost`/`tokens`）。用 `sqlite3.connect("file:...?mode=ro", uri=True)` 只读打开，576 MB 也不炸。
本次读出的事实：肇事那一步是 `ConvertTo-Json -Depth 10` ＋ `Set-Content -Encoding UTF8`，主 agent 模型 `xiaomi-token-plan-cn/mimo-v2.6-pro`（mode build），**同会话它手上有 `write`／`edit` 文件工具（本机历史计数 write 239／edit 297）却没用**，那一轮只调了 bash 11 次＋webfetch 10 次。
它 reasoning 里**已经怀疑过** `ConvertTo-Json` 会重排格式、会丢注释——唯独没往编码/BOM 这一维查＝"想到风险但没测"。
⚠ 另有两处未定论：`memory_fts` 表 0 行（不知道是记忆没索引还是注入不走 FTS）；`~/.local/share/mimocode/memory/**/MEMORY.md` 自身**也带 BOM**（markdown 无所谓，但同源）。
⚠ 控制台读中文会再叠一层 GBK 假象：PS 输出经管道回 bash 时"千问"能被渲染出来，看着像没坏——**判编码一律用码位/十六进制，别信终端渲染**。

## MiMo 盘上事实

- CLI/引擎配置：`~/.config/mimocode/mimocode.jsonc`（provider + mcp，**明文 API key**）；同目录 `.config/mimocode\node_modules` 是 `@mimo-ai/plugin`。
- 桌面态：`%APPDATA%\Xiaomi MiMo\`（`logs\`、`engine-config\mimocode.json`、`model-catalog.json`＝云端账号目录、`preferences.json`）。
- `preferences.json` 里 `skillPathCompat.agents/claude/codex/opencode = true` ⇒ MiMo 读 `~/.agents/skills`，与 Qoder 共享同一份技能目录。
- 应用装在 `E:\mimo\Xiaomi MiMo\`（Electron，NSIS，会自动更新）。

## open-websearch 2.2.0 实况

- MCP stdio 实测通：`initialize` → 6 工具（search / fetchWebContent / fetchGithubReadme / fetchLinuxDoArticle / fetchCsdnArticle / fetchJuejinArticle）→ `search` 用 bing **直连出真实结果**，不需代理、不需起 daemon。
- 合法 env 见 `build/config.js`：`MODE / DEFAULT_SEARCH_ENGINE / ALLOWED_SEARCH_ENGINES / SEARCH_MODE / USE_PROXY / PROXY_URL / PORT / ENABLE_CORS / PLAYWRIGHT_* / OPEN_WEBSEARCH_QUIET_STARTUP`。`MODE=stdio` 只走 stdio，`http/both` 才开端口。
- 一次性 CLI 也通：`open-websearch status --json` / `open-websearch search "..." --json`（CLI 会先探本地 daemon）。daemon＝`open-websearch serve`。
- 🔴 **别 `npm install --prefix` 到 Electron 应用目录**：那次就是这么装的（`Xiaomi MiMo\node_modules` 里只有它一个包，应用真依赖在 `resources\app.asar.unpacked\node_modules`），MiMo 更新/重装/卸载会整目录重建 → 工具静默消失。正解＝装 npm 真全局前缀 `C:\Users\若水\AppData\Local\nodejs`，MCP 的 command 指 `<prefix>\node_modules\open-websearch\build\index.js`。
- 搬家后应用目录副本已删（删前 build+package.json 共 95 文件的 tree sha256 两边一致：`96b246c2556b8cfa`）。

## 口径

- ✅ **已验证（10-17 10:04 关掉）**：MiMo 于 09:51 自行起来（配置是 09:45 修的），桌面日志里 `InvalidSymbol` **最后一次仍是 09:31**、此后再没有；
  引擎日志 `~/.local/share/mimocode/log/*.active.log` 出现 `service=mcp clientName=open-websearch`——**它连上并握手了**
  （同行那条 `MCP error -32601 Method not found: failed to get prompts` 是它向所有 server 问 `prompts/list`，open-websearch 只暴露 tools，skillsmp 同样报，属正常）。
  ⇒ 剥 BOM 这一步是被消费方自己确认过的，不是我推定通过的。
- 🔴 **顺带挖出一条桌面端自己的缺陷**：引擎日志每次启动都 warn
  `service=memory.reconcile path=C:\Users\若水\.local\share\mimocode\memory\global\MEMORY.md path outside memory layout, skipping`（global / projects / sessions 三处全被跳），
  `memory_fts` 表 **0 行**。机制定位到 `app.asar: src/memory/paths.ts :: parsePath`，正则是
  `/\/memory\/(global|projects|sessions)(?:\/([^/]+))?\/(.+)\.md$/`——**只认正斜杠**；Windows 反斜杠路径实测不匹配（我把两种形式都跑过）。
  ⇒ 最合理解释＝**Windows 上它的记忆 FTS 整条不工作**，`memory` 工具搜不到他放进接入点的那些指针文件。
  🔴 **10-17 10:31 改判为"未生效"，并已找到正确落点**：新会话实测两道逐字暗号题（`默认只读，用户点名才写`／`过肩已废`，两者盘上唯一来源就是那两处 MEMORY.md），
  该会话 `tool_output` **0 条**（一次工具都没调，控制项成立），两问均答「没有」；把那轮真正注入的 system-reminder 抽出来看，
  只有 MCP 清单／Runtime context／deferred 工具名单／系统提示词，**没有任何 memory 段落**。
  机制更正：它的记忆不是每轮注入，而是 `memory` 工具"indexed search"**按需检索**——所以 FTS 一死，两头都落空。
  ✅ 真正的注入点＝`C:\Users\若水\.config\mimocode\AGENTS.md`（引擎 `globalFiles()` 读它；asar 内置模板原话「写在这里的内容会作为全局指令随每次对话注入引擎(对所有项目生效)」）。
  该文件 10-17 前**不存在**，已建（UTF-8 无 BOM，1362 B＝库指针＋回写规约＋本轮 BOM 三态硬规矩）。
  ⚠ 尚未复测：AGENTS.md 是否真进 prompt——再开一个全新会话问它"上下文里有没有一段讲 BOM 三态的规矩"，答得出才算闭环；
  旧的两处 MEMORY.md 按本库自己的原则属"没人读的死配置"，本轮**保留未删**，等用户裁。
- 🔴 明文 key 现在盘上有 3 份副本（现文件 + `.bak_search_mcp` + `.bak_before_bomfix`），别带进任何同步/提交目录。
- ★ 本条已同步进跨 agent 库：`E:\公共记忆\projects\workflow-tooling-and-gates.md` §七（10-17 10:16，含摘要 ⑥ 与 BOM 三态第 ④ 条）＋ `E:\公共记忆\README.md` 变更记录（10:16 立规／10:31 MiMo 接入改判）；
  Qoder 侧同族规矩落在 [[feedback-destructive-edit-boundaries]] 延伸五。
