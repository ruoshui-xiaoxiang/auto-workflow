# 繁星画布设计：星图里的可编辑分镜板

- 日期：2026-11-02
- 状态：设计已确认，待实施计划
- 代码根：`D:\AIWorkflow\tools`
- 目标项目示例：`C:\Users\若水\Movies\Hub\Projects\第二十三星区\h3`

## 1. 背景与目标

MiniMax Design 的画布能摆素材、做分镜，但它拒绝连接本机 8189（托管后端 18188 缺 T8/KJNodes，外部 MCP 的 plan/canvas/knowledge 又绑死 app 会话），所以跑不了我们的本地工作流。繁星已经有完整的生成、八腿质检、跑前闸和成片链路，缺的是一层能看、能改、能触发生成的画布。

本设计把现有 3D 星图里的「镜头」星系升级成可编辑分镜画布，不新建一套视觉，也不重写 ComfyUI 节点编辑器。

### 目标

1. 在星图里按镜号看到所有镜头节点，节点可拖动、可多选、可新增。
2. 三种连线：片序、首尾帧链、参考依赖，连线可创建、可删除、可改类型。
3. 点节点打开镜头卡，能改首帧、末帧、台词、动作、时长、cast，并看到生成后的完整提示词与质检状态。
4. 点「应用到项目」把内容写回 `shots.yaml`，保留注释与字段顺序，随后自动重跑建稿与八腿闸。
5. 单镜重跑与整批出片都能从画布触发，有确认、进度、取消，且不允许绕过闸门。
6. 每个镜头的历次 take 可看、可 A/B 对比、可标选用。
7. 多项目可切换，画布布局按项目独立保存。

### 非目标

- 不做 ComfyUI 节点级编辑；节点图仍在 8189 的 ComfyUI 里改。
- 不做云同步、多人协作、移动端。
- 不提供“跳过闸门”“静默重跑”“自动批准”。
- 不把 `scenes.yaml` 的场景状态时间线搬进画布编辑（首版只读展示）。
- 不重写星图渲染层；复用现有 Three.js 场景、Raycaster、OrbitControls、标签与镜头补间。

## 2. 已定决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 画布形态 | 直接长在现有 `map3d` 里，新增「分镜画布」模式 | 星图已有节点/连线/深空视觉，风格统一 |
| 真源 | `shots.yaml` 是唯一生成真源；画布布局存 `.fanxing/canvas.json` | 生成、质检、闸门只读 yaml，避免双真源 |
| 写回 | 用户点「应用到项目」才写；写前出差异，写后自动建稿+闸 | 不静默改文件 |
| 连线 | 实线=片序，虚线=首尾帧链，点线=参考依赖 | 三种关系都要表达 |
| 托管 | 接进现有 8777 繁星看板，同端口加 `/canvas` 与 API | 不新占端口，复用静态托管与鉴权边界 |
| 前端 | 原生 ES module + Three.js，不引入构建链 | map3d 已是 importmap + ES module；避免 npm 构建 |
| GPU 任务 | 单任务队列，全局锁，一次只跑一个 | 16GB 单卡，并发只会互相挤爆 |
| YAML 写回 | 新增 `ruamel.yaml` 依赖，保留注释与顺序 | PyYAML 会吃掉注释，不可接受 |

## 3. 总体架构

```
浏览器 /canvas
   └─ map3d.html + map3d.js（现有渲染）
        └─ storyboard.js（新：分镜模式、拖拽、连线、卡片）
             └─ storyboard_model.js（纯函数：布局、边、校验映射，可 node --test）
   HTTP 8777
        ├─ GET  /canvas                         → map3d.html?mode=canvas
        ├─ GET  /api/projects                   → 可用项目列表
        ├─ GET  /api/canvas                     → 镜头/资产/闸门/takes/canvas.json
        ├─ POST /api/canvas/save                → 只存布局/连线/批注/选用
        ├─ POST /api/canvas/apply               → 校验 + 写回 shots.yaml
        ├─ POST /api/canvas/run                 → 建任务（gate 或 run）
        ├─ GET  /api/canvas/jobs/<id>           → 任务快照
        ├─ GET  /api/canvas/jobs/<id>/events    → SSE 实时行
        ├─ POST /api/canvas/jobs/<id>/cancel    → 取消整棵进程树
        └─ GET  /api/canvas/asset               → 缩略图/首帧/成片 poster
   后端模块
        ├─ h3_spider/canvas_state.py            → 读项目、写 canvas.json、写回 yaml、校验
        ├─ h3_spider/canvas_jobs.py             → 单任务队列、子进程、日志环、SSE
        └─ h3_spider/canvas_api.py              → 路由与 JSON 编解码
```

`dashboard.py` 只增加路由转发，不把新逻辑塞进 67K 的 `dashboard.html`。`map3d.js` 只做最小改造：暴露 `window.__fanxingMap`（scene、camera、renderer、controls、raycaster、nodeMeshes、select、focus、tween），新交互全部放 `storyboard.js`。

数据入口：`map3d.js` 的 `loadData()` 在 `mode=canvas` 时改调 `/api/canvas?project=...`，用 `shots.yaml` 构建镜头节点（不再依赖 batch_verdict 才有镜头）；质检状态作为节点属性叠加，缺批次时显示「未检」。

服务只监听 `127.0.0.1`，不对外网开放；所有带路径的参数必须在允许根目录内解析（见第 10 节）。

## 4. 数据模型

### 4.1 项目与镜头

- 项目列表：扫描 `C:\Users\若水\Movies\Hub\Projects\*`，保留含 `h3\shots.yaml` 的目录；返回 `{name, path, mtime, shot_count}`。`path` 统一指 `...\<项目>\h3`，项目根 `project_root` 是它的上一级。
- 镜头来源：`<project>\shots.yaml` 的 `shots[]`，字段沿用现有：`id/mode/canvas/duration/image/last_image/images/cast/content/dialogue/soundscape/music`。
- 状态来源：
  - 闸门与八腿：按顺序找 `<project_root>\.fanxing\last_batch.json` 指向的 `batch_verdict.json`、当前画布任务输出、最近一次 `C:/Temp/fanxing_runs/*/workflow.json` 的 `batch_dir`；都读不到时显示 `未检`，不伪造 PASS。
  - take：扫描 `<project_root>\outputs\**`、`<project_root>\assets\*.mp4`、`<project_root>\work\**` 与画布任务输出，按文件名中的 shot id 归组。
  - 资产根（按优先级）：`<project>\assets\crops`、`shots.yaml` 的 `assets_dir`、`<project>\assets`、`<project_root>\assets`、`<project_root>\合并_第二十三星区\04_外部依赖快照`。

### 4.2 `.fanxing/canvas.json`

只存表达层，不存生成内容：

```json
{
  "version": 1,
  "project": "C:/Users/若水/Movies/Hub/Projects/第二十三星区/h3",
  "updated_at": "2026-11-02T20:00:00",
  "view": {
    "camera_preset": "top",
    "bookmarks": {"top": {"pos": [0, 26, 12], "target": [0, 0, 0]}}
  },
  "nodes": {
    "U01": {"pos": [4.3, 0.6, 2.1], "pinned": false, "note": "", "selected_take": "20261102_193333:U01"},
    "@cmdr": {"pos": [-6.0, 0.4, 5.0]}
  },
  "edges": [
    {"id": "e1", "from": "U01", "to": "U02", "type": "order"},
    {"id": "e2", "from": "U02", "to": "U03", "type": "chain", "binding": "U02_end"},
    {"id": "e3", "from": "U04", "to": "@cmdr", "type": "ref"}
  ],
  "annotations": {"U01": {"status": "ok", "text": "选用第 3 版"}}
}
```

- 节点位置以星系中心为原点，单位与星图一致；缺省按现有环形布局生成。
- 锚点节点来自 `characters.yaml` 的 roles 与 `scenes.yaml` 的 scenes，id 用 `@<name>`。
- `selected_take` 只影响画布标记，不改 `shots.yaml`。

### 4.3 连线到 yaml 的映射（apply 时）

| 线型 | 含义 | 写回规则 | 失败条件 |
|---|---|---|---|
| `order` | 片序 | 按 order 边拓扑排序重排 `shots[]`；若完全没有 order 边则保留原顺序 | 有环、多个父节点；一旦存在 order 边，所有节点必须连通，游离节点拒绝 |
| `chain` | A 末帧接 B 首帧 | B.`image` = A 的绑定末帧文件名；A 必须已绑定 `binding` | 未绑定末帧、文件不存在 |
| `ref` | B 引用 A 或锚点 | 把 A 的 `image`/锚点点名加入 B.`images`（去重） | 目标不是 ref2va/multiref、锚点不存在 |

- `chain` 只写 B 的首帧，不改 A；若要双向都锁，用户再画一条反向边。
- `ref` 不自动改 `cast`；发声者仍由卡片里的 speaker 决定。
- 所有映射先在内存生成新文档并校验，校验失败不落盘。

## 5. 3D 交互

### 5.1 模式与相机

- 顶部按钮「分镜画布」切换模式；切换时其他星系 `visible=false`，镜头星系与锚点保留。
- 默认相机预设 `top`：俯视偏 10°，正交感，看到整条片序；另一个预设 `orbit` 保留现有 3D 漫游。
- 进入模式时自动聚焦「镜头」星系，退出时恢复进入前相机。

### 5.2 节点

- 复用 `makeNode` 生成球体与 HTML 标签；`userData = {kind:'shot', shotId}`。
- 状态光环：PASS 绿、BLOCK 红、未检灰、运行中青蓝脉冲。
- 拖动：pointerdown 命中节点后暂停 OrbitControls；pointermove 用射线与节点所在水平面 `y=node.y` 求交，位置吸附 0.5；pointerup 恢复控制并写入内存状态。
- 多选：Shift+点击切换；空白处拖拽出屏幕空间选框，框内节点高亮。
- 新增：星系边缘一个「+」节点，点击后在中心附近生成新镜头卡；若现有 id 全是 `U<数字>`，新 id 取 `U<最大数字+1>`，否则取 `SH<序号>`；默认 `mode=i2va`、`duration=4.5`、`scene` 取项目默认。
- 删除：卡片面板里删除，需二次确认；不直接按 Del 删节点，避免误触。

### 5.3 连线

- 节点外侧一个小球作为出线口；从出线口拖到目标节点完成连线。
- 画布左上角线型调色板：1 片序 / 2 首尾帧链 / 3 参考依赖；也可按 1/2/3 切换当前线型。
- 渲染：
  - 片序：细实线，冷白；
  - 首尾帧链：虚线，金色，末端箭头；
  - 参考依赖：点线，青色，低透明度。
- 拾取：`Raycaster.params.Line.threshold = 0.35`；点中边弹出小菜单（改类型/删除/绑定末帧）。
- 布局变化时边端点每帧跟随节点；不在服务端存几何，只存关系。

### 5.4 收起与性能

- 距离超过 26 单位隐藏标签；超过 40 单位隐藏参考点线，只留片序与链。
- 59 镜时使用现有 LOD 逻辑；节点球体共享几何与材质，仅颜色分组。
- 失去焦点（浏览器切走）暂停动画循环，回来恢复，避免后台吃 GPU。
- 撤销/重做：布局与连线编辑维护 50 步命令栈（移动、增删节点、增删边、改线型）；`Ctrl+Z` / `Ctrl+Shift+Z`。写回 yaml 不进这个栈，靠 apply 前备份回滚。
- 批注：卡片底部可填 100 字批注并标 `ok/issue`；issue 在节点旁显示一个小红点，不改变质检光环颜色。

## 6. 镜头卡片（右侧面板）

宽度 420px，五个页签：

1. **内容**：id、mode/canvas、duration、cast、shot_line、after_all、soundscape、music。
2. **提示词**：读 `out/<id>.txt` 的生成稿（只读高亮）；下方可编辑源字段；「校验」按钮调用 `h3_prompt_builder` 的规则与官方 spec，错误按字段内联显示。
3. **资产**：首帧、末帧、参考图。点击打开素材抽屉，按 crops / assets_dir / 项目 assets / 合并快照 四组列出缩略图；选中后写回卡片草稿。
4. **版本**：该镜 take 列表（poster、时长、来源 run、时间）；「A/B」并排同步播放；「标选用」写 `canvas.json`。
5. **QC**：八腿逐条结果与异常码；「打开工作台」深链 `/?sid=U01`。

底部固定动作条：`应用到项目`、`重跑这一镜`、`关闭`。顶部另有 `批量应用`，只提交所有标脏的卡片，逐镜返回结果；任一镜失败不影响其他镜已成功的写入，但整体标红并列出失败项。

- 时长必须落在允许集：`{4.5} ∪ {(17n+5)/24 | n=7..20}`（5.167–14.375 秒，即 H3 的 124–345 帧，17n+5 栅格）；不在集合就拦。
- 台词长度按 `h3_prompt_builder` 的 `speech_timing` 与容差 `max(0.8s, 20%)` 校验；超窗直接红。
- 所有编辑先写本地 draft，只有「应用到项目」才落盘。

## 7. 写回与校验流程

1. 卡片编辑产生 draft，前端标脏。
2. 点「应用到项目」→ `POST /api/canvas/apply`，payload 含项目、镜头 draft、边映射。
3. 服务端用 `ruamel.yaml` 读原文件，只改受影响字段，保注释与顺序；先生成新文档到临时文件。
4. 校验：
   - 结构：必填字段、17 帧档位、cast 名在角色卡、scene 在场景卡、资产文件存在且 sha1 可读；
   - 文本：调 `h3_prompt_builder` 的规则（timing/word/lexicon）与 `h3_official_spec`；
   - 边：按第 4.3 节做拓扑与引用检查。
5. 校验失败返回 422 与逐条错误，原文件不动。
6. 通过后原子替换 `shots.yaml`；立刻对该镜跑 `h3_prompt_builder build`，再跑 `h3_spider batch --shots`，最后 `check_batch_gate`；结果回传卡片。
7. 任一阶段失败：文件已改但不静默；卡片红，提示「已写入，质检未过」，提供一键回滚到 apply 前的备份（保存 `.fanxing/backup/shots.<时间戳>.yaml`）。

## 8. 生成编排

### 8.1 任务入口

`POST /api/canvas/run`：

```json
{"project": "...", "shots": ["U01"], "stage": "run", "confirm": true}
```

- `stage=gate` 只跑预检/建稿/质检/闸；`stage=run` 先跑闸，PASS 后才出片。
- 前端必须先弹确认框，展示：镜数、当前闸门状态、预计分钟数（`7 * 镜数`，来源为 U01 实测 7.0 分钟/8 秒镜）。
- 缺 `confirm:true` 直接 400。

### 8.2 任务执行

- 先调用 `fanxing.workflow.run_workflow(... --through gate --shots ...)`，输出目录固定为 `C:/Temp/fanxing_runs/canvas_<job_id>`，拿 `workflow.json` 与 `batch_dir`。
- 闸门 BLOCK：任务结束，状态 `gate_blocked`，把 reasons 回传。
- 闸门 PASS 且 `stage=run`：对同一批 `batch_dir` 调用
  `py -3.12 h3_run_project.py --project ... --out C:/Temp/fanxing_runs/canvas_<job_id>/run --spider-batch <batch_dir> --only <shots>`。
- 直接调 `h3_run_project.py` 是为了拿到逐镜 stdout 实时进度；它内部仍会再过一次闸，等价于 `--execute-run`。
- 出片前检查 `http://127.0.0.1:8189/system_stats`；不通直接拒绝，不排队。
- 全局锁：`.fanxing/jobs/active.lock` 存 `{job_id, pid, started_at}`；读取时若 PID 不存在或超过 12 小时，视为陈旧锁并清除；已有活锁时返回 409。

### 8.3 状态机与事件

`queued → gating → gate_blocked | running → done | failed | cancelled`

- `GET /api/canvas/jobs/<id>` 返回状态、镜列表、已用时、日志尾 200 行。
- `GET .../events` 用 SSE 推送 `{ts, line}`；前端把 `[U01] 已等 4.0 分钟` 之类的行挂到对应节点。
- 完成时扫描输出目录，生成 take 记录与 poster（`ffmpeg -ss 0.2 -frames:v 1`）；poster 失败时写静态占位图并在卡片标「无预览」，不影响 take 本身。
- 写 `canvas.json` 的 `takes` 时先重读磁盘再合并，只改自己的 shot 键，避免覆盖用户同时保存的布局。
- 取消：`taskkill /T /F /PID <pid>`；状态 `cancelled`；保留已有产物。
- 任务记录写 `.fanxing/jobs/<job_id>.json`，服务重启后只读展示，不自动续跑。

## 9. 多项目

- 顶部项目选择器，列出 `Hub\Projects` 下所有含 shots.yaml 的项目；当前项目高亮。
- 切换项目时：有运行中任务则拒绝；无任务则重载星图数据与 `canvas.json`，相机回到 `top`。
- 每个项目的布局互不影响；同一镜头在不同项目里 id 可重复。
- 归档目录（`Hub\_archive`）不在列表里；需要时通过「打开其他路径」手动加，路径记入全局 `C:\Users\若水\.fanxing\canvas_recent.json`（最多 10 条），不写进项目内的 `canvas.json`。

## 10. 错误处理

| 情况 | 行为 |
|---|---|
| shots.yaml 解析失败 | 画布只读，顶部横幅报错；禁止 apply/run |
| canvas.json 损坏 | 备份为 `.bak`，按自动环形布局重建，提示用户 |
| 资产缺失 | 卡片红标，apply 拒绝；run 也拒绝 |
| 8189 不通 | run 返回 503，提示先启动 LocalAI/8189 |
| 任务进程异常退出 | 状态 failed，保留日志与已出 take；不自动重试 |
| SSE 断开 | 前端每 4 秒轮询 `/jobs/<id>` 兜底 |
| 写回后闸门失败 | 文件保留，卡片红，提供回滚备份 |
| 非法路径参数 | `project` 必须解析到 `Hub\Projects` 或 `C:\Users\若水\.fanxing\canvas_recent.json` 里登记的路径；`asset` 必须落在该项目的资产根或允许的资产根内；不满足返回 403 |
| 任务与保存并发 | `canvas.json` 一律原子写（临时文件 + `os.replace`），写前重读合并 |
| 服务重启后旧任务 | 只读取 `.fanxing/jobs/*.json` 展示为「中断」，不自动续跑、不占锁 |

## 11. 测试策略

- **Python 单测**（pytest，加入现有 112 条）：
  - `canvas_state`：YAML 往返保留注释与顺序；三线型 apply 规则；拓扑环/多父/游离节点拒绝；17 帧档位与 timing 边界。
  - `canvas_jobs`：状态机；用假进程模拟 gate_blocked/running/cancelled；锁冲突 409；SSE 订阅与日志环。
  - `canvas_api`：临时项目 fixture 的 200/400/409/422/503 分支。
- **Node 单测**（`node --test`）：`storyboard_model.js` 的吸附、屏幕选框、边类型切换、布局重排、撤销栈纯函数。
- **端到端手工清单**：
  1. 打开 `/canvas`，12 镜与三线型渲染；
  2. 拖动 U01 后刷新，位置保持；`Ctrl+Z` 能撤销；
  3. 改 U02 时长越档被拦，改到 5.875 通过；
  4. apply 后 yaml 注释仍在、diff 只动该字段；
  5. 单镜 gate→run 全流程，take 出现在版本页；
  6. 8189 关闭时 run 被拒；
  7. 取消任务后进程树消失、状态 cancelled；
  8. A/B 同步播放与标选用；
  9. 切项目后布局互不串；
  10. 越界 `asset` 路径返回 403。
- **回归**：`py -3.12 -m pytest h3_spider/tests -q` 必须保持 112 passed。

## 12. 实施分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| M1 | map3d 模式开关、镜头/锚点节点、三线型只读渲染、布局持久化、只读卡片 | 12 镜可看可拖，刷新保持 |
| M2 | 卡片编辑、ruamel 写回、差异预览、建稿+闸自动重跑 | 改一镜时长并 apply，注释不丢 |
| M3 | 单镜/整批任务、SSE 进度、取消、8189 健康检查 | 单镜出片与取消都可用 |
| M4 | takes/A-B、标选用、多项目、自动排版、性能与打磨 | 全量验收清单通过 |

分期只决定实现顺序，不缩减已确认范围。

## 13. 风险与应对

| 风险 | 应对 |
|---|---|
| 3D 拖拽与框选精度差 | 默认 `top` 相机 + 0.5 吸附；保留自动排版一键复位 |
| `map3d.js` 已有 64K，继续膨胀难维护 | 只暴露 `window.__fanxingMap`，新逻辑独立 `storyboard.js` |
| ruamel 改动 YAML 风格 | 只在原 AST 上改值；测试覆盖注释/顺序/引号风格 |
| 长任务阻塞 HTTP | 任务在独立线程 + 子进程，不占用请求线程 |
| 59 镜性能 | 共享几何/材质、LOD 隐藏标签与参考线、后台暂停渲染 |
| 画布 JSON 与 yaml 漂移 | 每次打开以 yaml 为准，只保留布局；apply 前做结构校验 |

## 14. 验收标准（总）

1. `/canvas` 能打开当前项目，镜头节点、锚点、三类边全部可见且可操作。
2. 布局、连线、批注、选用 take 刷新后不丢；不污染 `shots.yaml`。
3. 编辑必须经「应用到项目」写回；写回保留注释与字段顺序；失败不静默。
4. 写回后自动建稿+八腿闸，结果回到卡片。
5. 单镜与整批出片都有确认、进度、取消；闸门未过、8189 不通、并发任务三种情况均被拒。
6. A/B 对比与 take 选用可用。
7. 多项目切换布局隔离。
8. 现有 `pytest` 112 条不回归，新增 Python/Node 测试全绿。

## 15. 实施与验收记录（2026-11-02）

已落地：

- 后端：`canvas_store.py`、`canvas_paths.py`、`canvas_edges.py`、`canvas_state.py`、`canvas_apply.py`、`canvas_jobs.py`、`canvas_api.py`；8777 已挂 `/canvas`、`/api/projects`、`/api/canvas*`、`/storyboard_model.js`、`/storyboard.js`。
- 前端：`map3d.js` 分镜模式与 `window.__fanxingMap`/`window.__fanxingStoryboard`；`storyboard_model.js`；`storyboard.js`（拖拽、框选、三线型、撤销、卡片五页签、批注红点、单镜应用、整批应用/跑闸/出片、A/B、项目切换）。
- 写回：`shots.yaml` 保留注释与 2 空格序列缩进；apply 前临时项目预演，失败不落盘；备份名带时间戳+uuid。

实测：

- `py -3.12 -m pytest h3_spider/tests -q`：**257 passed**（含 12 镜真实项目 fixture 的 apply、重复 id、脏 JSON、路径越界、任务状态机）。
- `node --test h3_spider/tests_js/storyboard_model.test.mjs`：**19 passed**。
- 浏览器（Chromium/Playwright，临时项目副本）：12 镜/3 锚点/11 条自动片序边；拖拽刷新保持、Ctrl+Z/Ctrl+Shift+Z、框选、Shift 多选、三线型创建、撤销/重做、双击删边、右键换线型、卡片五页签、资产点选、批注与红点、单镜 dry-run→apply（时长 6.0 被拦，5.875 写回且注释保留）、整批应用、+镜头/删镜头、整批跑闸提交与 `gate_blocked` 回显。
- 真实项目 U01 早前实跑：8.00s / 192 帧 / 992×544 / 24fps / 32kHz 立体声，7.0 分钟；画布任务复用同一 `h3_run_project.py` 链路。

尚未做（不伪装通过）：

- 未从画布真正提交整批 12 镜出片（会占用 GPU 约 100 分钟）；任务队列只用假 runner 与 `stage=gate` 验证。
- A/B 弹窗只做了结构/按钮验证，未逐帧目视同步；留待目视调整清单一起过。
- 整批跑闸在临时副本上因缺 `assets/crops` 返回 `gate_blocked`，这是预检正确拦截；真实项目已有 crops，但未在画布里再跑一次整批绿闸。

## 16. 入口收敛（2026-11-02 晚）

分镜画布与主序星不再单开页面：

- `/canvas` → 302 `/map3d?project=…`；`/starfield` → 302 `/map3d`。
- 主入口只有 `/map3d`：镜头星系直接可编辑，主序星仍是星图里的一个星系；不再有「分镜画布 / 质检视图」切换。
- 8788 独立 starfield 进程不再需要，已停止；`/api/starfield` 仍由 8777 提供。

## 17. 星系显示名（2026-11-02）

星图短名 / 面板全名：

| id | 短名 | 全名 |
|---|---|---|
| storyboard | 分镜带 | 分镜星带 |
| legs | 八验环 | 八验星环 |
| slots | 扩展区 | 扩展星区 |
| evidence | 证据云 | 证据星云 |
| workflow | 工序轨 | 工序星轨 |
| agents | 主序群 | 主序星群 |
| knowledge | 知识云 | 知识星云 |
| 核心 | 星核 | 批次星核 |

id 和数据字段不变，只改显示名。
