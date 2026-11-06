# 繁星系统 — 3D 星图 · H3 质检 · 分层知识库 · 工作流与启动台

## 基础信息

- 项目名：fanxing-system
- 位置（代码根目录）：`D:\AIWorkflow\tools\fanxing\`（0.1.0）＋ `D:\AIWorkflow\tools\h3_spider\`（0.4.0-p15）；数据根 `E:\繁星\`；知识库 `E:\繁星\60_知识库\`
- 定位（一句话）：把 H3 出片工作流、八腿质检、agent 注册表、分层知识库和 3D 星图收成一个**人类导航层 + agent 入口层**；星图只导航，不替代工作台证据。
- 当前版本 / 里程碑：2026-11-02 对齐轮——7 星系（满配 63 节点）、5 个分层 collection（2,164 文件 / 16,132 chunks）、`fanxing workflow` 默认停在跑前闸、ComfyUI 画布同步已落地。
- 最新更新：2026-11-02 18:17
- 摘要：繁星系统现为「工作台 / 3D 星图 / 主序星 / 启动台」四个入口；agent 常规工作流走 `fanxing workflow`（默认到 gate，`--execute-run` 才提交 GPU）；知识库分 core/project/archive/skills/memory 五库，`all` 不含 archive；星图 7 星系、满配 63 节点，节点全部来自真实字段，没有占位。

## 当前状态（快照）

- 核心功能：
  - **质检内核**：`h3_spider` 八条腿 L1–L8，T/M/C 三类节点，影子副本注入；`selftest` 默认跑 8 腿＋卡片规则 S1/S2/S3。
  - **完整工作流**：`fanxing workflow` 五阶段 `precheck → build → qc → gate → run`；默认 `--through gate`，`run` 标 skipped；失败 BLOCK 后续 skipped，不伪装通过。
  - **知识库**：FAISS `IndexIDMap2(IndexFlatIP)` 512 维 + SQLite FTS5（jieba）+ hybrid RRF；5 个独立 collection；`kb audit/eval/neardup` 已落地。
  - **入口**：`/` 工作台、`/map3d` 唯一 3D 星图、`/starfield` 主序星、`/launch` 启动台（5 个白名单入口）；2D 星云已删除。
  - **画布同步**：`h3_run_project.py` 每镜写 `<tag>_workflow.json`，并原子写 `ComfyUI/user/default/workflows/_fanxing_latest.json`；ComfyUI 控制台粘贴 `h3_spider/canvas_sync.js` 自动加载。
- 主导航/主要模块路径：
  - 代码：`fanxing/{workflow,agents,kb,starfield}.py`、`fanxing/contract/fanxing-agent-v1.md`、`fanxing/registry/agents.json`
  - 质检：`h3_spider/{body,engine,recover,gate,batch,dashboard}.py`、`h3_spider/map3d.{html,js}`、`h3_spider/canvas_sync.js`
  - 工具：`h3_trace.py`、`h3_precheck.py`、`h3_prompt_builder.py`、`h3_run_project.py`、`selftest_card_standards.py`
  - 数据：`E:\繁星\{00_启动台,20_创作,30_素材库,40_公共记忆,50_存档,60_知识库}`
- 技术栈：Python 3.12（CPU）＋ FAISS 1.15 ＋ SQLite FTS5 ＋ jieba ＋ bge-small-zh-v1.5 512d；前端 three.js r170；本地 ComfyUI 8189；LocalAI 网关 8080。

## 入口与使用方式（2026-11-02）

| 入口 | 用途 | 启动 / 地址 |
|---|---|---|
| 工作台 | token 高亮、8 腿矩阵、异常清单、资产/场景、原始 JSON | `py -3.12 -m h3_spider.dashboard --batch <qc> --gate <gate.json> --workflow <workflow.json> --kb E:/繁星/60_知识库 --port 8777` |
| 3D 星图 | 7 星系导航；点节点回工作台 `/?sid=U05` | 同看板 `/map3d` |
| 主序星 | 按 agent registry + workflow runs 动态出星；只导航不路由 | `py -3.12 -m fanxing.starfield --runs C:/Temp/fanxing_runs --port 8788` |
| 启动台 | 5 个白名单：娱乐流、agent 出片引擎、素材库、规范手册、创作工作区 | 看板 `/launch`；配置 `E:/繁星/00_启动台/launchpad.json` |

**Agent 常规工作流（唯一常规入口）**：

```bash
cd D:/AIWorkflow/tools
py -3.12 -m fanxing workflow --agent h3-spider \
  --project "C:/Users/若水/Movies/Hub/Projects/未命名项目/h3" \
  --out "C:/Temp/fanxing_runs/h3-spider_001" \
  --shots U01 U02 --through gate
# 真正提交 GPU 才加： --through run --execute-run
```

- 直接调用 `h3_spider batch` / `h3_run_project.py` 只算调试/逃生门，不带 `agent_id`，不算接入。
- 跑前闸要求：8 腿齐全、spider verdict PASS、`trace_sha1` 匹配、卡文件在 spider 之后未被改；缺腿或改卡 → BLOCK。
- **改过 `shots.yaml` 必须重跑 spider**，否则 gate 报「卡文件在 spider 之后改过」拒跑；这是闸在正常工作，不是坏件。

## 知识库（2026-11-02）

| collection | 文件 | chunks | 用途 |
|---|---:|---:|---|
| core | 415 | 5,717 | 规范手册/官方规则（排除 99/10/04b；含 08_Qoder 记忆副本） |
| project | 51 | 316 | KB23 + 若水AI电影 |
| archive | 1,408 | 6,139 | 50_存档；排除运行时/密钥/重复 |
| skills | 238 | 3,205 | 04b + shuohao + 即梦 skills + AI视觉 .qoder |
| memory | 52 | 755 | 40_公共记忆静态文档（不等于 agent 私有记忆） |
| **合计** | **2,164** | **16,132** | legacy 根索引 483/5,969 保留对照 |

- 默认 hybrid（dense + BM25 + RRF），跨库等权；`--collection all` 只查 core/project/skills/memory，archive 必须显式指定。
- 30+10 定稿集：分库 dev 29/30（MRR 0.8428）、holdout 9/10（MRR 0.90）；**support@5 holdout 只有 6/10**，文件级 recall 会高估可答性。
- 2026-11-02 复索引后 core 对应 10 题 Recall@8 **8/10**（11-01 为 9/10）；原因是 08_Qoder 记忆副本同步进 core 后同主题竞争，不是索引损坏；memory 仍 8/8、support 6/8，audit PASS。
- 近似重复 182 簇（core 29 / project 17 / archive 125 / skills 11 / memory 0），只报告未合并；`--apply` 需单独授权。
- `E:\密钥文件` 从未进入源；archive 里 34 个含密钥特征的文件已列入 `exclude_files`，未删除原文件。
- 仍非全盘：白名单外约 8,500 个 `.md/.txt` 候选（20_创作 6,771、30_素材库 1,048、50_存档 679）。

## 星图口径

- **7 星系**：检查腿 8、镜头 12、扩展槽 4、质检节点 24、工作流 5、主序星（按 registry）、知识库（按 collections）。
- **满配 63 节点** = 8 + 12 + 4 + 24 + 5 + 5（主序星）+ 5（知识库）；节点数随批次/agent/KB 命中动态变化，不造空节点。
- 质检节点 N/A-aware：base/i2va 模式没有对应段时按 `not_applicable` 扣减，显示 `9/9`、`11/11`；旧「15 待补」已作废，本次 0 待补。
- 星图只是导航层，不替代工作台的 token/资产证据；节点点开只定位，不展示 token 快照。
- 当前主序星按 registry/runs 动态：本次 5 颗 active + 2 个无数据隐藏（local/doubao）；agent 有 workflow 才出星，没数据不造星。

## 画布同步（2026-11-02）

- `h3_run_project.py` 提交前过 `verdict.json`；`PASS` 且 `trace_sha1` 匹配才允许。
- 每镜写 `<out>/<tag>_workflow.json`（已 patch 的 UI 格式，图片/提示词/时长/输出前缀是真实值），并原子写 `ComfyUI/user/default/workflows/_fanxing_latest.json`。
- ComfyUI 页面 DevTools Console 粘贴 `D:\AIWorkflow\tools\h3_spider\canvas_sync.js`；它轮询 `_fanxing_latest.json`，版本变化才 `app.loadGraphData`。
- `FANXING_CANVAS_SYNC=0` 只关 latest 自动加载，per-shot 文件仍写。
- 已验证 U05（31 节点，0 error，`adjutant.png/cmdr.png/bridge.png`）与 U08（33 节点，0 error，`U08_start/end`）。
- 同步只改画布显示，不绕过闸，也不代表 GPU 出片质量。

## 验证与当前边界

- 2026-11-01 全量：**112 passed**；12 镜批 12/12 PASS；builder trace 12/12、0 unattributed；precheck 资产链 3/3；selftest 卡片 19/19。
- 2026-11-02 复跑：**108 passed / 4 failed**，4 条全在 `test_gate.py`，原因是测试项目的 `shots.yaml` 在 spider 批跑后被改过，gate 正确拒跑（`卡文件在 spider 之后改过`）。**这是闸在工作，不是代码回归**；重跑 spider 批即可恢复。
- 星图/看板：1440 与 390 无横向溢出、console 0 error；390 下 inspector 底部抽屉。
- 100+ 镜/节点必须上 InstancedMesh + 聚类，不能继续硬塞。
- 长会话/外部模型仍可能「看起来空转」：MiniMax Design 的空转监测见下；繁星本身不负责模型调用延迟。

## 相邻本地应用：MiniMax Design（2026-11-02 配置）

- 外接模型 `deepseek-flash`，reasoning 从 high 调为 **medium**；`media-agent.steps` 400→**100**；`mcp_timeout` 60min→**15min**；`todowrite` 开启。
- 已重启生效；**旧会话仍绑定 high**，新会话才用 medium；当前会话要在模型菜单切换或开新会话。
- 只读空转监测：`C:\Temp\opencode\agent_progress_guard.py`（180s 无输出 / 600s 长工具 / 3 次重复调用才提醒；`question` 等待不提醒）；启动 `start_agent_guard.bat`，停止 `stop_agent_guard.bat`。
- 配置备份：`hub-config.json.bak_20261102_1730`、`.config-v3/base.json.bak_20261102_1730`、安装模板 `base.json.bak_20261102_1730`。

## 当前待办 / 阻塞

- [ ] 主序星/知识库节点在 100+ 规模前需要 InstancedMesh + 聚类（当前 7/63 不需要）。
- [ ] `kb neardup --apply` 未执行，是否合并需单独授权。
- [ ] 白名单外 8,500 个候选未入索引，需先定源策略。
- [ ] `test_gate.py` 的 4 条失败是测试项目卡文件漂移；要么重跑 spider 批，要么把测试项目冻结，别改 gate 判据。

## 关键路径速查

| 内容 | 路径 |
|---|---|
| 工作流编排 | `D:\AIWorkflow\tools\fanxing\workflow.py` |
| Agent 契约 | `D:\AIWorkflow\tools\fanxing\contract\fanxing-agent-v1.md` |
| 质检内核 | `D:\AIWorkflow\tools\h3_spider\` |
| 3D 星图 | `D:\AIWorkflow\tools\h3_spider\map3d.js` / `map3d.html` |
| 画布同步 | `D:\AIWorkflow\tools\h3_spider\canvas_sync.js` |
| 看板 | `D:\AIWorkflow\tools\h3_spider\dashboard.py` |
| 主序星 | `D:\AIWorkflow\tools\fanxing\starfield.py` |
| 知识库 | `E:\繁星\60_知识库\` |
| 启动台 | `E:\繁星\00_启动台\launchpad.json` |
| 公共记忆 | `E:\繁星\40_公共记忆\`（`E:\公共记忆` junction） |
| 实现方案 | `C:\Users\若水\Documents\Qoder\2026-10-31\6f9b84e6\蜘蛛质检系统_实现方案_20261101.md` §32–§37 |

## 注意事项 / 踩坑提醒

- **别把星图当证据**：星图只导航；token/资产/场景证据在工作台和 `verdict.json`。
- **别跳过 gate**：`h3_run_project.py` 的 `--skip-spider` 是显式逃生门；常规工作流走 `fanxing workflow`。
- **改了卡/稿/资产就重跑 spider**：gate 会比对 `project_hashes` 与卡文件 mtime，改后不重跑必拒。
- **KB 不是全盘索引**：`E:\密钥文件`、图片/视频、模型、`.git`、缓存、`_统一备份` 都不进；archive 也不进 `all`。
- **公共记忆 `index.json` 是派生物**：只改 `projects/*.md` 再跑 `build_index.py`，不要手改索引。
