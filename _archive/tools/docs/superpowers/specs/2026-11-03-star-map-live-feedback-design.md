# 星图实时反馈：节点闪烁 + 数据流面板

日期：2026-11-03
状态：已实现并通过浏览器验证

## 1. 目标

在主星图 `/map3d` 上补两个运行时能力：

1. 流水线处理到某个分镜镜头时，该镜头节点自动闪烁，结束后留下完成/失败状态。
2. 右侧数据专区常驻一个可折叠的“数据流”面板，实时显示五阶段、当前镜头和最近日志。

不新增页面，不改 `shots.yaml` / 出片脚本 / ComfyUI 工作流。

## 2. 非目标

- 不做面板上的任务控制（暂停、取消、重跑），仍由现有工具栏按钮发起。
- 不做锚点、连线、质检腿节点的闪烁。
- 不做多任务队列展示；当前 JobManager 仍是单 GPU 单任务。
- 不改 ComfyUI 采样参数或分辨率。

## 3. 交互定义

### 3.1 节点闪烁

只作用于分镜镜头节点（`shot`），锚点和连线不参与。

| 时刻 | 表现 |
|---|---|
| 质检开始 | 本次提交的镜头一起青色呼吸 |
| 质检给出单镜结果 | PASS：白色短闪 1.2s 后转绿；BLOCK：转红慢闪 |
| 出片提交该镜 | 该镜青色呼吸 |
| 出片等待中 | 保持呼吸，面板显示已等时长 |
| 出片完成 | 白色短闪 1.2s 后转绿 |
| 出片失败 | 转红慢闪，直到下一次任务开始 |
| 新任务开始 | 清空上一轮所有闪光状态 |

呼吸和慢闪由 shader 的 `uFlash` 驱动；标签同步加 `flash-run` / `flash-done` / `flash-fail` 类，星点、光晕、文字标签状态一致。

### 3.2 数据流面板

- 位置：右侧数据专区，位于“批次星核”面板正下方，与它同宽（300px）、右边缘对齐，两个面板之间不留缝。
- 常驻显示；收起时整列贴右边缘收成 52px 竖条，只保留状态点和“数据流 · 阶段/镜头”简讯；点竖条展开。收起状态写入 `localStorage`，新任务开始时自动展开。
- 右侧只放数据：上方批次星核，下方数据流；镜头详情卡打开时盖在专区之上。
- 内容自上而下：
  1. 五个阶段灯：预检、建稿、质检、跑前闸、出片，带状态色和耗时。
  2. 当前镜头：`U05 · 已等 4.0 分钟`；没有单镜信息时显示 `整批 12 镜`。
  3. 最近 5 行日志，等宽小字，自动滚到最新。
- 没有任何任务时显示“待命”，阶段全部为灰色 pending。
- 页面刷新后恢复当前任务或最近一次任务的结果。

## 4. 事件模型

`/api/canvas/jobs/:id/events` 的 SSE 从纯文本升级为结构化 JSON。日志事件保留 `line` 字段，旧消费者仍可读。

| type | 字段 | 说明 |
|---|---|---|
| `job` | job_id, shots, stage, started_at | 任务上下文 |
| `stage` | stage, label, status, duration_s, summary | 五阶段状态 |
| `shot` | shot, state, elapsed_s, videos, source | 单镜状态，source=qc/run |
| `status` | status | queued/gating/running/done/failed/cancelled/gate_blocked |
| `log` | line | 原始日志行 |

每个事件追加 `at`（Unix 秒）。`shot.state` 取值：`running`、`waiting`、`done`、`failed`、`pass`、`block`。

### 4.1 后端事件来源

- `fanxing.workflow.run_workflow` 新增可选 `on_event` 回调；每个阶段开始发 `stage/running`，结束发最终状态；被跳过的阶段发 `stage/skipped`。
- `JobManager` 在任务进入 gating/running/终态时发 `status`。
- 质检阶段：`run_workflow` 结束后读取 `batch_verdict.json`，按镜头发 `shot/pass` 或 `shot/block`；结果里缺失的镜头按 `block` 处理。
- 出片阶段：逐行解析 `h3_run_project.py` 的输出：
  - `[U05] 提交 ...` → `shot/running`
  - `[U05] 已等 4.0 分钟...` → `shot/waiting` + `elapsed_s`
  - `[U05] ✓ 6.0 分钟, 2 个视频` → `shot/done` + `elapsed_s` + `videos`
  - `[U05] ❌ ...` → `shot/failed`
- 出片进程非零退出时，仍未结束的镜头补发 `shot/failed`。
- 任务结束、取消、异常时发最终 `status`。

### 4.2 缓存与恢复

- 每个 job 增加 `events` 环形缓存，最多 300 条，随 job JSON 持久化。
- `GET /api/canvas/jobs` 返回 `{active, recent}`；`recent` 最多 3 条，供刷新后重放。
- `JobManager._load_existing()` 只把 queued/gating/running 的任务标为 `interrupted`，已完成任务保留原状态。

## 5. 前端结构

### 5.1 新文件

- `h3_spider/live_panel_model.js`：纯状态归约，不碰 DOM，可直接 `node --test`。
- `h3_spider/live_panel.js`：面板 DOM、SSE、2 秒轮询兜底、折叠、事件广播。

### 5.2 职责边界

`live_panel.js` 是唯一持有 job SSE 的地方：

- `window.__fanxingLive.watch(jobId)`：拉一次 job 快照，重放事件；活动任务再连 SSE。
- `window.__fanxingLive.snapshot()`：返回当前镜头状态，供星图启动时补状态。
- 每个事件都向 `window` 派发 `CustomEvent('fanxing:job', {detail: event})`。

`storyboard.js` 删除自己的 EventSource 和 4 秒轮询，改为调用 `__fanxingLive.watch()`；监听 `fanxing:job` 的 `status` 事件刷新状态栏、结束时刷新画布。

`map3d.js` 监听 `fanxing:job`：

- `job` 事件清空上一轮闪光。
- `shot` 事件设置对应节点状态。
- 启动完成后用 `snapshot()` 恢复一次状态。
- 使用独立的 `nodeFlash` Map 和 shader uniform，不占用 `frameHooks`，避免 storyboard 重建时被清空。

## 6. 视觉实现

### 6.1 节点 shader

`NODE_FS` 增加：

- `uniform float uFlash`
- `uniform vec3 uFlashColor`

在原有 core/ring/glow 之上叠加 `flashGlow` 和 `flashRing`，颜色向 `uFlashColor` 混合；`uFlash=0` 时与现状完全一致。

### 6.2 时序

- 呼吸：`0.28 + 0.22 * (0.5 + 0.5*sin(t*3.2))`，青色。
- 完成：1.2 秒内衰减白闪，`flash = (1-age/1.2) * (0.55+0.45*abs(sin(age*16)))`，随后归零，标签保持绿色。
- 失败：`0.22 + 0.18 * (0.5 + 0.5*sin(t*2.0))`，红色，持续到下一轮。

### 6.3 标签

- `.flash-run`：青色描边 + 呼吸阴影。
- `.flash-done`：绿色描边。
- `.flash-fail`：红色描边 + 慢速闪烁动画。

## 7. 面板状态机

阶段固定为 `precheck/build/qc/gate/run`，每个阶段状态：`pending / running / ok / block / error / skipped`。

- `job`：重置为 pending，记录 shots、stage、job_id。
- `stage`：更新对应阶段；`skipped` 不覆盖已有的 `ok/block`。
- `shot`：更新当前镜头与逐镜状态。
- `log`：保留最后 5 行。
- `status`：更新整体状态；终态关闭 SSE/轮询并停止计时。

面板顶部状态文案：

- idle：`待命`
- queued/gating/running：`预检中` / `质检中` / `出片中`，附已用时间
- done：`完成 · 6分02秒`
- gate_blocked：`已阻断 · 质检`
- failed：`失败`
- cancelled：`已取消`

## 8. 错误处理

- SSE 断开：退到 2 秒轮询 `/api/canvas/jobs/:id`；终态停止。
- SSE 收到坏 JSON：忽略该条，不影响后续事件。
- 未知日志行：只写日志区，不改变阶段。
- 事件回调异常不能中断生产：`run_workflow` 的 `on_event` 抛错时吞掉并继续。
- 任务 JSON 写入失败：沿用现有日志/状态，不阻断出片。
- 刷新时任务已结束：从 `recent` 重放事件，显示最终结果，不连 SSE。

## 9. 测试

### 9.1 Python

- `run_workflow`：用假的阶段命令，断言 stage/running 与最终事件顺序；跳过阶段发 skipped。
- `JobManager`：
  - 事件进入 `events` 环形缓存并持久化；
  - `status` 依次为 gating/running/done；
  - 出片行解析四种状态；
  - QC verdict 的 PASS/BLOCK 映射到 shot 事件；
  - 取消与异常发终态；
  - 重启只打断活动任务，已完成任务保留。
- `canvas_api`：
  - SSE 返回 `application/json` 结构；
  - `GET /api/canvas/jobs` 返回 active/recent；
  - 路径/权限守卫不回归。

### 9.2 Node

- `live_panel_model.js`：job/stage/shot/status/log 的归约、终态、跳过阶段不覆盖、日志只留 5 行。

### 9.3 浏览器

用 Playwright 打开 `/map3d`：

- 面板常驻、可折叠；
- 提交一次 gate 任务（短项目），观察阶段灯依次亮起、日志滚动、镜头节点呼吸与结果色；
- 断开 SSE（路由拦截）后仍能通过轮询更新；
- 刷新页面后恢复最近任务。

## 10. 涉及文件

后端：

- `fanxing/workflow.py`
- `h3_spider/canvas_jobs.py`
- `h3_spider/canvas_api.py`
- `h3_spider/dashboard.py`（新增两条静态路由）

前端：

- `h3_spider/map3d.js`
- `h3_spider/map3d.html`
- `h3_spider/live_panel.js`（新增）
- `h3_spider/live_panel_model.js`（新增）
- `h3_spider/storyboard.js`

测试：

- `h3_spider/tests/test_canvas_jobs.py`
- `h3_spider/tests/test_canvas_api.py`
- `h3_spider/tests/test_workflow_events.py`（新增）
- `h3_spider/tests_js/live_panel_model.test.mjs`（新增）

## 11. 验收

- 提交一次出片任务：对应镜头按顺序呼吸，完成转绿、失败转红；锚点不动。
- 面板阶段灯与实际 workflow 阶段一致，耗时与实际相符。
- 面板断开 SSE 后仍能更新；刷新后能看到最近任务。
- 现有画布编辑、拖动、连线、应用、A-B 对比不回归。
- 实现后：262 个 Python 测试通过；7 个既有 gate/p1 用例因真实批次与 shots.yaml 漂移失败，与本功能无关；JS 28 个测试全绿。
