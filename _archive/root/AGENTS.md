# AGENTS.md · 本机 AI 出片流水线的 agent 契约（薄壳）

> **这份文件刻意写得很短。** 它只干一件事：让你在读到任何其它文档之前，先知道
> **谁是真源、从哪进、什么绝对不许做**。
>
> **唯一机器可读真源 ＝ [`D:\AIWorkflow\官方路径.json`](./官方路径.json)**
> 里面登记了：两个入口、13 类信息各自的真源住哪、哪些线冻结了、哪些入口废了（废了的原处有路障桩）、
> 9 条禁令、4 项已知坏件及其处置。
> **自检命令：`py D:\AIWorkflow\tools\check_official_path.py`**（六项，默认只报不拦，`--strict` 才返回 1）。
>
> 下面第 2、3 节是那份 json 的**指针快照**——为了让你不点链接也能看到最要命的部分而抄在这里。
> 快照由 `[P7]` 逐条对账：**改真源请改 json，改完跑一次自检**。只手改本文不改 json ＝ 制造第二份漂移真源。

---

## 1. 一句话说清这台机器

ComfyUI（`D:\AIWorkflow\ComfyUI_H3\ComfyUI`，端口 **8189**）是**唯一后端进程**，它自己不是入口。
出片链路是：**即梦画布 5.0 lite 免费档**出首帧/关键帧/资产 → **H3** 出视频。所有 agent 都走这条。

---

## 2. 只有两个入口（快照）

<!-- SNAPSHOT:entries BEGIN —— 以下每条的命令/入口字符串必须与 官方路径.json 的 entries 段逐字相同 -->

**入口一 · agent（所有 agent 软件 ＋ 人工命令行）**

```
cd D:/AIWorkflow/engine && python run.py <workflow> [--set k=v ...] [--tier play|draft|final]
```

唯一执行核。即梦出图与 H3 渲染都在这条链里，**你不需要知道即梦 CLI 怎么调**。
常用开关：`--list`（列工作流） / `--gates`（列待批关口） / `--approve RUN_ID GATE` /
`--approve-and-resume` / `--resume RUN_ID|last` / `--porcelain`

**入口二 · 娱乐流（用户本人：玩、试参数、快速出图出片）**

```
桌面「娱乐流」图标 → 起 8189 → 开 http://127.0.0.1:8189/extensions/comfyui-entertainment-panel/index.html
```

面板控件由 `channels_registry.json` 派生：视频侧 5 个输入模式页签、3 个配方页签、帧数/宽高/tier/编排；
素材含图、参考视频、视频原声、独立音频，**四类素材与图生图源图均支持上传**（落 `ComfyUI_H3/output/娱乐流/_上传素材/`，
仍走 run.py；保留手动路径兜底）；提示词可粘贴落文件。图片侧 文生图（`image_draft_batch`）/
图生图（`image_i2i`）两个入口，参数不写死在模板里。
档位 `tier` 可选 `play|draft|final`：play＝闸门 warn 不拦、产物落娱乐流预览区、不进资源池、不做 QC、不交付；
draft/final 按正常落点。档位由用户选择，不再固定 play。
捞回来靠**参数重跑**（批次目录里的 `怎么捞回来.md` 存了可直接复制的 run.py 命令，把 `--tier play` 改成 `draft`），不靠文件提升。
🟡 状态（2026-10-26）：视频侧已在 10-24 多次重启加载过；图片侧已接面板并通过离线参数构造/前端语法检查
（engine 584 passed），**01:24／01:36:56／01:51:27／01:56:55 四次按授权重启**（首版图片后端、G13 槽修复、素材上传路由；
spec image_modes 两项、面板 200、队列 0/0、G13 离线 error 0/warn 0；上传 image/video/audio HTTP 200、坏后缀 400）；
**t2i 已出多批（用户 + A/B/C/D 4 张）**；i2i 未真跑，画质/身份未验收。
面板不接接力（manifest 驱动、需无 sage、64 对齐），会明确拒绝 —— 接力走 `run.py h3_relay_movie --set manifest=...`。
重启后自检：`GET http://127.0.0.1:8189/extensions/comfyui-entertainment-panel/index.html` 返 200 即生效，404 ＝ 没加载；
`GET /entertainment/spec` 应含 `image_modes` 两项（image_t2i / image_i2i）。
🔴 `--tier play` 与盘上已有的 `h3_fl2va_*_play` 那批**不是一回事**：后者是**参数预设**（20 步／不挂 LoRA／
两头夹），前者是**落点＋降级**。两件事共用一个词，`run.py` 会显式提示一次，别把 draft 档的产物以为在预览区。

<!-- SNAPSHOT:entries END -->

**已废的入口**（🔴 说清现状，别信「已经拦住了」）：`8790` 说话出片 UI、`8787` engine WebUI、
`tools/oneshot.py` 独立编排链。三者登记在 `官方路径.json` 的 `deprecated` 段，**状态＝「待归档」**：
原脚本仍在盘上、仍跑得起来，**路障桩还没立**（立桩＝原位换成打印替代命令 + `exit 78` 的桩，
模板在 `tools/_路障桩模板.py`，归档那一批一起做）。所以**别去撞它们试试**——直接按上面的现役入口走。
⚠ 旧文档里那张「四通道总表」把 8787 当现役、且一份都没提 8790 ⇒ **以
[`E:\LocalAI\CHANNELS.md`](file:///E:/LocalAI/CHANNELS.md) 为通道与端口的唯一真源**，别信任何抄本。
（2026-10-19 桌面快捷方式轮：`本地脚本化出片流水线.lnk` 已撤到 backups，桌面换成「娱乐流」；
`LocalAI.ps1` 菜单 2 不再起 8787，改成腾卡＋保证 8189。**同一轮上午还把菜单收成两项**：
1 起模型服务 / 2 停服务腾卡 / 0 退出，状态不再占按键（每次进菜单自动打屏上，含端口＋进程名）。
⇒ 别在菜单里找「出片」这一项，它不该有；`-Action status`／`-Action stop` 仍然单独可用。）

---

## 3. 九条禁令（快照）

<!-- SNAPSHOT:forbidden BEGIN —— 以下每条必须与 官方路径.json 的 forbidden 数组逐字相同 -->

1. 另开端口。agent 一律走 8080 网关（8081=qwen3-14b），ComfyUI 只有 8189 一个实例。
2. 绕过 run.py 直连 8189 提交 /prompt。（10-19 收口补边界：本禁令管的是**出片入口**。`tools/comfy_run.py`（09-16 建的通用出图执行器）确实直连提交，它是**排障／手工测量件、不是入口**——agent 出片一律走 run.py，拿 comfy_run 出片即破本禁令；它在 README 与手册里出现只作排障用法）
3. 手改派生件：E:/公共记忆/index.json（build_index.py 派生）、E:/创作/_资产总索引/（build_asset_registry.py 派生）。手改＝制造第二个漂移真源。
4. 把任何真源放进 tmp/。tmp 是实验区，随时会被清。
5. 在同一批里混用两个出图源（即梦 + 本地 Z-Image）。理由不是『出不出得来』而是**画风不能混**——两个源的画风有差异，混在一条片子里就是画风跳变。切换本地出图必须用户先同意，且授权是**批级**。
6. 让娱乐流产物直接进资源池正身。它是预览；捞回来靠参数重跑，不靠文件提升。
7. 自动回落。即梦走不通必须停下报明确原因（登录失效/模型被关停/积分不足/网络），等用户修复，不许自己想办法。
8. 把归档目录放在 custom_nodes/ 下。会被当第二个节点包导入 —— 10-06 踩过：『升级后节点还在』其实是备份在供货，判读全错。
9. 删素材。授权删除≠可以直接删：先盘构成，认不出名字的当有人在用，一律 move 归档不 rm。

<!-- SNAPSHOT:forbidden END -->

**另外四道硬闸门**（用户 2026-10-19 亲定，不在 json 的 forbidden 数组里，但同样不可越）：

- **首帧图必须先发飞书给用户目审、通过后才准进下一环。** 一镜 7 分钟且多镜串行，错一帧浪费整条链。
  ⚠ 10-19 收口（R5-17）：这道闸**不因超时自动放行**——「30 分钟未回复即继续」只管非关口的一般等待，
  人工关口（H3／H4／G13 需人落单的槽）一律等明确点头；付费与不可逆动作同此。
- **第一镜出片后也必须发飞书**（不必等目审，但第一镜要发）。
- **出片终审由用户做三分类归档**：通过（可当标准样片）／瑕疵（还要重修）／废片（问题重大、修复价值不大）。审片站不做终审。
- **G13 运行决定单的项目级 6 槽只能人落单**（`--set` 会被拒）。agent 不许代填、不许 `preflight:off` 绕过。

---

## 4. 保存规范（铁律）

所有文件按类别落位，**禁止散落**：

| 文件类型 | 只放这里 | 说明 |
|---|---|---|
| 成品图像 | `E:\图像影音资源池\<项目>\图像\` | 出图最终成品 |
| 成品视频 | `E:\图像影音资源池\<项目>\视频\` | 出视频最终成品 |
| 素材/源文件 | `E:\图像影音资源池\<项目>\素材\` | 源视频、抽帧、参考图、冷数据 |
| 音频 | `E:\图像影音资源池\<项目>\音频\` | 配音、BGM、音效 |
| 批次交付 | `E:\图像影音资源池\<项目>\批次\` | 引擎产出的自包含批次文件夹 |
| 模型权重 | `D:\AIWorkflow\models\<类别>\` | 如 `tts\`、`face\`；ComfyUI 模型在 `D:\Models\ComfyUI\<类型>\`（经符号链接） |
| 训练数据集 | `D:\AIWorkflow\training\datasets\<项目>\` | 格式：父目录下 `N_名字` 子目录 |
| 训练产物/LoRA | `D:\AIWorkflow\training\output\<项目>\` | sd-scripts 原始 .safetensors |
| 临时中间产物 | `D:\AIWorkflow\tmp\` | ⚠ 见下面那条更正 |
| 日志 | `D:\AIWorkflow\logs\` | 排障用 |

**🔴 对上一版铁律的更正（2026-10-19）**：旧文写 `tmp\` =「用完即清，不留垃圾」。
**那句话当时就是假的**——`tmp\wzy\` 住着 preflight 闸的运行时真源
（`check_preflight.py:79-82` 的 `PF_SEARCH_DIRS` 只查那里）。照它清 tmp，闸门不会报错，
只会 warn 一句然后**静默落到兜底镜像词表 `_BAN_MIRROR`**：闸还是绿的，判据已经漂了。
现已由 `tools/check_official_path.py [P5]` 把「真源不许住 tmp」变成机器可检；Phase 4 会把真源上移到 `tools\`。
**在上移完成前，`tmp\wzy\` 不许清。**

**禁止写入**（会立即造成散落）：

- `E:\LocalAI\`（只保留应用本体 + 入口脚本，见迁移 MANIFEST）
- 桌面、下载目录、`C:\Users\...` 任意临时目录
- 直接把成品/模型写到工作流外的地方

⚠ `E:\创作\` 从「禁止写入」名单里**移出**：它是资产台账与技能包 SOP 的现役落点
（`E:\创作\人物角色库\_meta\characters.csv`、`E:\创作\技能包转H3_SOP\`）。旧文那条与现实不符。

**具体怎么存**：

1. **出图/出视频走引擎**：成品自动落 `E:\图像影音资源池\<项目>\批次\`，由 `engine\config.yaml` 的
   `output_root`（第 72 行）控制。⚠ 不再是「切换项目＝改这一处」——现在 `projects_registry.json`
   是项目声明源，`output_root` 会被校验含不含当前 project（旧行为导致 9-18 仙戮四条产物串进无音批次夹）。
2. **ComfyUI 原始输出**：先落 `D:\AIWorkflow\tmp\staging`（comfyui.bat 的 `--output-directory`），
   引擎 `tasks.relocate()`（`tasks.py:563`）再搬进资源池。
3. **训练 LoRA**：输出到 `training\output\<项目>\<run名>\`；训练完直接用原始 `.safetensors`。
4. **搬文件规则**：跨盘一律「复制 → 校验（文件数+字节数）→ 删源」；同盘用 rename。禁止跨盘直接 move。
5. **归档规则**：一律 `mv` 到 `D:\AIWorkflow\backups\_治理_<日期>\`，**绝不 `rm`**；每批配 `RESTORE.md`。

---

## 5. 目录地图

```
D:\AIWorkflow\                    # 生产层（NVMe 快盘，热路径）
├─ 官方路径.json                  # ★ 唯一机器可读真源清单（先读这个）
├─ AGENTS.md                      # 本文（薄壳）
├─ README.md                      # 结构概览
├─ engine\                        # auto-workflow 引擎（run.py / tasks.py / config.yaml / workflows\*.yaml）
├─ tools\                         # 闸门与 QC 脚本（check_*.py 三件套 + h3_official_spec.py + h3_rule_gate.py）
├─ models\{comfyui,tts,face}\     # 模型资产（comfyui 是 junction → D:\Models\ComfyUI）
├─ training\{toolkits,datasets,output,configs,docs,tokenizers}\
├─ ComfyUI_H3\ComfyUI\            # 运行时本体（端口 8189）
├─ backups\_治理_<日期>\          # 归档落点（含 RESTORE.md）
├─ logs\                          # 运行日志
└─ tmp\                           # 实验区 ⚠ 现存 tmp\wzy\ 是运行时真源，未上移前不许清

E:\图像影音资源池\                # 交付层（SATA 大盘，成品池）
├─ _公共素材\  _归档_MANIFEST\  _待归类_20260928\  _验证\
└─ <项目>\{图像,视频,素材,音频,批次}\

E:\LocalAI\                       # 通道与端口真源（CHANNELS.md）+ 本地模型运行时
E:\创作\                          # 资产台账 + 技能包 SOP
E:\公共记忆\                      # 跨 agent 交接入口（index.json 是派生件，不许手改）
```

---

## 6. 仍然有效的关键坑

- **显存互斥**：本地 14B（8081）与 ComfyUI（8189）**不能同驻** 16GB。训练/推理前必须关掉另一边，
  否则速度 11s/it → 1000s/it（约 90 倍降速）。端口与通道口径见 `E:\LocalAI\CHANNELS.md`。
- **H3 提示词必须过闸**：改稿 → 重跑官方契约 + 房内闸 → 贴 `0 error` 与 sha1 → 才准渲。
  闸红按词法改，**不许绕 preflight**。⚠ 闸绿 ≠ 内容不变，改写必做原稿 vs 改稿 A/B。
- **H3 无负面通道**：禁令句即在点名。别把即梦那套提示词语法搬过来。
- **别静默替换用户选中的图**：修局部缺陷走 inpaint（实测保脸 0.986）；整张重掷必换脸（0.275）。
  要重掷先声明并保留原图。
- **Windows 路径编码**：`.py` 里引用路径优先用正斜杠或 raw 字符串；无 BOM 的中文 `.ps1` 必坏；
  git bash 会吞 `$_`；cv2 读不了中文路径；heredoc 会吞反斜杠导致 `str.replace` 静默不改（改完必 grep 回看）。
  这两类病由 `engine/tests/test_run_decisions.py::test_no_silent_backslash_escape_in_engine_and_tools` 把关。

**已作废、别再信的旧坑**：

- ~~ComfyUI FLUX 只认 sd-scripts 格式 LoRA~~ ⇒ **FLUX 线整条已裁**（主模型 `flux1-dev-fp8.safetensors`
  盘上缺失，10 个模板现在就是坏的）。现役图像线是 **Z-Image**，视频线是 **H3**。
  ⚠ `tasks.py` docstring 里那些 denoise/掩膜实测数字是 **FLUX 时代**口径，Z-Image 档未重新标定，别当判据用。
- ~~圣女 pipeline 已退役~~ ⇒ 历史记录，能力早已并入 `engine\workflows\character_sheet.yaml`。
- ~~迁移留痕见 `_迁移MANIFEST_20260911.md`~~ ⇒ 仍在，但那是 9 月的旧映射，只作历史查。

---

## 7. 这份文件的历史（为什么要重写）

上一版 `AGENTS.md`（7079 字节，最后修改 2026-10-12）有两个致命问题，2026-10-19 治理批查实：

1. **正文一半是乱码**。文件本体是合法 UTF-8 with BOM，但内容里有 51 行是「UTF-8 字节被按 GBK 解码后
   又存回 UTF-8」的产物——`# 宸ヤ綔娴佷娇鐢ㄨ鑼冧笌璇存槑锛堝繀璇伙級` 这种。
   **讽刺的是：能读的那一半恰好是过时的通道表，读不了的那一半恰好是保存规范铁律。**
   还原办法是 `s.encode('gb18030').decode('utf-8')`（必须 gb18030，不能用 gbk/cp936：乱码文本含 U+E749
   这类私有区字符，gbk 编码器直接 UnicodeEncodeError，86 行里只能还原 3 行）。
   **但这次还原是有损的**：当初那次错误解码把无法表示的字节替换成了字面 `?`，原文信息已不在盘上。
   ⇒ 我**没有**把推断出来的内容直接当规范发布。乱码原文的可读转写放在
   [`backups\_治理_20261019\_乱码原文_可读转写_供比对.md`](./backups/_治理_20261019/_乱码原文_可读转写_供比对.md)，
   里面逐处标注了哪 3 个字符是**我的推断**而非机械还原（`8189` 的首位数字、`90 倍` 的十位、`颠簸` 一词），
   以及各自的旁证与置信度。原样字节备份在同目录 `原样保存_AGENTS_乱码原文.md`
   （md5 `fd38e2d6b9ae11bcc0d849f4f11b7a19`）。**那 3 处若要当规范用，请人工复核。**
   规范文件里「自信地写错」比「看得见是乱码」更坏。

2. **它自己就互相矛盾**：「四、使用入口」出现两次（一份乱码版说 ComfyUI 8188、一份干净版说 8189），
   四通道总表也出现两次，且都列已废的 8787、都不提 8790。

本文替换它。旧文没有删，两份备份都在 `backups\_治理_20261019\`。

---

*最后更新：2026-10-19（治理批 Phase 3）。改动请同时改 `官方路径.json`，然后跑
`py D:\AIWorkflow\tools\check_official_path.py` 确认 `[P7]` 不红。*
