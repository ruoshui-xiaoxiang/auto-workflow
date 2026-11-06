# 本地 AI 工作流规范与通道规则 — 五条通道分治 ＋ 手册副本集 ＋ 备份验收

## 基础信息

- 项目名：local-ai-workflow-rules（本地 AI 工作流规范 / 通道规则 / 手册副本集 / 统一备份）
- 位置（代码根目录）：规则真源 `D:\AIWorkflow\ComfyUI_H3\`（提示词与通道规则）＋ `D:\AIWorkflow\tools\`（机检与备份脚本）＋ `D:\AIWorkflow\engine\`（跑批与关口）；跨盘副本集 `E:\本地工作流规范手册\`（276 份，只读参考）；唯一备份树 `E:\_统一备份\`
- 定位（一句话）：本机出图／出片「走哪条通道、按哪套规则、谁验收」的**唯一记录中心**——本库是参考信息源，**不是**强制纪律源（纪律以真源文件为准）
- 当前版本 / 里程碑：**通道规则分治 v1.1**（2026-09-28）——手册冲突表编号到 **C86**、结构性风险到 **30**；**2026-11-02 繁星系统成为常规入口**（不新增通道）
- 最新更新：2026-11-02 18:01
- 摘要：2026-10-21 H3 官方对齐修复（G7 四模式 I2VA/FL2VA/L2VA/T2VA、真首尾帧链切 h3_fl2va、G4 补 9 图/3 视频/12 文件/15s、batch 加 translate、313 tests 全绿）；此前 10-12 MiMo 总则最高裁决 + 说话出片 UI(8790) + 四通道强制 agent 默认入口；启动器走 PS7/run-ps1.bat；G13 必填槽显式给值。**10-24 S4 手册单源**：D 版 `build_manual.py` 改薄委托，E 维护版为唯一实现与清单；两入口 `--check --strict` 均 0 缺源／0 落后／445 同步（旧 349 只是 D 清单口径）。

## 当前状态（快照）

- 核心功能：规则真源 → 机检判据 → 关口拦截 → 副本集（`build_manual.py` 单源生成）→ 统一备份（`backup_now.py`）→ 冲突裁定表（`版本裁定与冲突表.md`）
- 主导航/主要模块路径：`E:\本地工作流规范手册\00_读我\`（读我总览／硬参数速查表／版本裁定与冲突表）；`E:\本地工作流规范手册\20_通用规范层\`（通用条 G2/G4 ＋ 作用域与例外登记表）；`D:\AIWorkflow\tools\check_preflight.py`（G1–G12 跑前自审）；`D:\AIWorkflow\tmp\wzy\h3_rule_gate.py`（H3 规则机检）
- 技术栈：Python 3.12 ＋ 本地 ComfyUI/MiniMax H3 ＋ 云端 Seedance/Seedream/可灵/千问 CLI；文档即真源，脚本即判据

## 重要改动记录

### 2026-11-02 18:01 ｜ 繁星系统成为常规入口（不新增通道）

- **摘要**：agent 常规工作流改走 `fanxing workflow`（precheck→build→qc→gate→run，默认停在 gate，`--execute-run` 才提交 GPU）；`h3_spider batch`／`h3_run_project.py` 降为调试/逃生门。星图 7 星系/满配 63 节点；KB 5 个 collection（2,129 文件/15,644 chunks）；`h3_run_project.py` 增加 ComfyUI 画布同步。**不新增模型通道**，五条通道分治不变。
- **影响范围**：入口层、工作流编排、知识库检索、画布显示；不改 H3/云端通道判据，不改 `channel_of()`。
- **相关文件**：`projects\fanxing-system.md`、`D:\AIWorkflow\tools\fanxing\workflow.py`、`h3_spider\gate.py`、`h3_spider\canvas_sync.js`、`E:\繁星\60_知识库\README.md`。
- **决策/结论**：常规入口统一到繁星；直接调用质检/runner 不算 agent 接入；跑前闸始终生效，画布同步不绕过闸。

### 2026-10-24 15:44 ｜ 手册生成器收敛为单源（S4）

- **摘要**：两份同名 `build_manual.py` 写同一个手册根的问题解决——E 维护版是唯一实现与清单，D 工具版改成 `runpy` 薄委托（参数/退出码透传）。比对清单后，D 独有的 4 个启动器（`启动常驻ComfyUI.bat`＋3 个 launchers）与两个工具真源（`check_official_contract.py`／`build_official_lexicon_cn.py`，从“手册自副本”改回 `D:\AIWorkflow\tools\`）已并入 E；E 独有的 100 条保留；顺带删掉 E 里 `scan_system.py`、`00_架构总纲.md` 的重复登记（同源同落点写两次，检查数虚增 2）。
- **影响范围**：`刷新副本.bat` 仍只调 E；D 路径保留为兼容入口，不再有第二份清单。手册派生副本刷新 28 个，未删除任何源文件。
- **验收**：`E/…/build_manual.py --check --strict` 与 `D:/AIWorkflow/tools/build_manual.py --check --strict` 均 **源缺失 0／落后 0／已同步 445**，退出码 0。证据 `D:\AIWorkflow\backups\_优化_20261023\生产修复_S4_20261024_132525\`。
- **相关文件**：`E:\本地工作流规范手册\99_维护\build_manual.py`、`D:\AIWorkflow\tools\build_manual.py`、`E:\本地工作流规范手册\99_来源清单\{manifest.json,MANIFEST.md}`。

### 2026-10-21 01:49 ｜ H3 官方对齐修复（G7 四模式 / G4 上限 / batch translate）

- **摘要**：G7 此前只认 I2VA 首行并禁止 `<Picture 2>`，官方 FL2VA 稿会被误拦、真首尾帧链只能写 I2VA 口径。现按首行识别 I2VA/FL2VA/L2VA/T2VA；具体 `prompt_kind` 必须与首行一致（泛称才按内容识别）。
- **改动**：`tools/check_preflight.py`；`engine/channels_registry.json` 增 `h3_fl2va/h3_l2va/h3_t2va`；`h3_fl2va_dual_play` / `h3_fl2va_dual_clean_play` 切 `h3_fl2va`；G4 仅对 h3 通道加 9 图/3 视频/12 文件/15s；`h3_i2va_batch` 加 translate（默认开、可关）；G6 帧数口径注释统一（官方 4–15s / 本机 124–362 / 107–123 未实测）。
- **未改**：`h3_shots.compile_video` 仍只产 I2VA 单首帧；`_dual_lora` 是双 LoRA 单首帧，保持 I2VA。
- **回归**：`pytest -q` 313 passed；FL2VA 正例通过、I2VA 稿塞 FL2VA 链报"模式不一致"。
- **相关**：`D:\AIWorkflow\ComfyUI_H3\H3官方对齐复核_20261021.md`、`engine\comfy\_读我_模板命名.md`、备份 `D:\AIWorkflow\backups\20261021_h3_align_fix\`。

### 2026-10-12 ｜ 说话出片 UI 与启动器规范（补记）

- 摘要：**说话出片**（`engine/nl_ui`，8790）替代手点 ComfyUI 画布：自然语言+参考图 →image_draft_batch / h3_* 引擎流；仍走 preflight/G13/人工关口。桌面「本地脚本化出片流水线」→ `run-ps1.bat` → `start-nl-pipeline.ps1`（UTF-8 BOM）。
- **编码铁律**：PowerShell 5.1 无 BOM UTF-8 + 中文路径=启动闪退/空 FilePath。新脚本优先 **PS7**；兼容 5.1 时必须 BOM + 环境变量路径。
- 影响范围：所有 bat/ps1 启动入口；`run-ps1.bat`/`run-pwsh-cmd.bat` 为唯一 shell 封装。
- 相关：`projects/local-ai.md`、`E:\LocalAI\CHANNELS.md`、MiMo 总则。


### 2026-10-12 ｜ 四启动通道强制生效（agent 默认入口）

- 摘要：启动方式收敛为四通道，**任何 agent 跑出图/出片/工作流/本地 LLM 必须默认从 `E:\LocalAI\LocalAI.bat`（agent出片引擎）启动**，禁止绕过网关另开端口。脚本化出片走 `E:\LocalAI\本地脚本化出片流水线.bat`（8787/8189）；LM Studio 调试走 1234；Ollama 走 11434。
- 影响范围：agent 工具链、引擎/ComfyUI 拉起、LLM 后端调用；已删 8188 便携、LocalAI 控制台、圣女一条龙、启动常驻ComfyUI 等旁路。IDE（DeepSeek Harness 等）不在清理范围。
- 相关：`E:\LocalAI\CHANNELS.md`、`AGENT_DEFAULT.md`、`D:\AIWorkflow\AGENTS.md`、`projects\local-ai.md`（2026-10-12 同日）。


### 2026-09-28 ｜ 即梦云端立为第五条通道；官方提示词规范落地（冲突表 C82–C84／风险 30）
- 摘要：用户发话「先查一下即梦提示词规范，然后再增加一个即梦提示词规范再写」。新真源 `D:\AIWorkflow\ComfyUI_H3\即梦云端_工作流规则.md`，并登记进 `build_manual.py` 文件地图 → 手册 `03_使用规范与关口流程\`。**本通道形态＝用户手跑即梦网页画布出图/出视频，agent 只用 `dreamina-canvas.exe` 取回＋机检**（不是 agent 代跑）。
- 影响范围：**即梦通道的所有出图/出视频提示词写法**，以及"拿外部文档当规范"时的采信顺序。官方出处三条：火山方舟《Seedream 4.0-5.0 提示词指南》（图片侧）、《Doubao Seedance 2.5 提示词指南》（视频侧）、即梦官方资源页。⚠ 前两个是 **JS 壳**，WebFetch 只拿到 bootstrap（会误判"页面没内容"）⇒ 须走内置 `browser-use` 的 `navigate_page` ＋ `evaluate_script("()=>document.body.innerText")` 落盘；`user-browser-use` 那套 `evaluate_script` 对任何函数都返回 `{}`，不可用。
- 相关文件：`D:\AIWorkflow\ComfyUI_H3\即梦云端_工作流规则.md`（真源）、`C:\Users\若水\bin\dreamina-canvas.exe`（v1.0.1）、抓捕件 `C:\Temp\jmcanvas\seedream_prompt_guide.md`／`seedance25_prompt_guide.md`、`E:\创作\_待审文档\漫剧服装造型_提示词案例调研_20260928.md`；同批登记 5 处：`00_读我\读我_总览与导航.md`（必读第 8 行＋目录表＋快速上手第 3 步）、`00_读我\硬参数速查表.md`（§1.7 通道分工表第五行）、`20_通用规范层\R2_提示词结构与接口契约.md`、`20_通用规范层\R_作用域与例外登记表.md`（两行）、`00_读我\版本裁定与冲突表.md`（新增 §〇⁷ ＋ 风险 30）
- 决策/结论：**★外部文档要按"它是哪一层的口径"分层采信——工具契约 > 官方文档 > 社区经验**。本通道上三层直接打架：官方指南说「简洁精确的提示通常优于重复堆叠华丽复杂的词汇」／即梦产品页说「无字数限制」／社区说「关键词控制在 20–40 字」。硬事实只有 `model list` 给的 **图片 prompt `maxLength`＝2000**（9 个模型全部；视频侧 `seedance_2.5` 15000、`wan_3.0` 20000、`minimax_h3` 7000、`seedance_2.0_*` 4000、`happyhorse_1.1` 2500、`seedance_pro_fast` 2000）。⇒ ①社区「20–40 字」**不采信**（与官方页直接矛盾）；②官方「简洁优于堆叠」读作**针对 tag 罗列＋冗余画质词**（官方反例正是 `一个女孩，撑伞，林荫街道` 这种并列），**不是**「结构描述要短」⇒ 本机口径收敛为**「结构写细、形容词写少」**，与 09-27 那条"华丽＝装饰密度逐项点名（名词＋计数）"**独立收敛到同一处**；③**负面词只文档化「字幕／音频」两类** ⇒ 图片侧一律把禁令改写成**正向句**（C83 结案）。
- ⚠️ **给下一个工具提醒（三条）**：① **即梦稿不进任何机检**——它是人工执行通道、没有引擎调用会把稿子送进 `channel_of()`，所以**不需要**新增分支，也**不存在**被误判拦死的风险；别把"第五条通道也没进 `channel_of()`"读成第二个 风险 28。② **`seedance_2.5` 是云端 SD（中文十块）与即梦（官方三段式）共用的同一个模型、两套契约**（**C84，未裁**）⇒ 裁之前两通道**不许互证**——"分治"的前提是"模型族不同"，同模型跨通道时这条规矩要另找理由。③ **动即梦写法必须同批留旧写法对照臂**（风险 30）：官方口径与本机现役 76＋18 条 800–900 字长稿相左，而支撑现役写法的只有用户一句人审，没有同帧同 seed 对照；照官方整批改写有把"已经还行"的那批一起改坏的可能。

### 2026-09-28 ｜ 千问云端立为第四条通道，各通道规则分治（冲突表 C79／风险 28）
- 摘要：用户裁定「这个单独作为千问云端工作流规则，以后各路径都切换自己的规则，不跟别的路径共用」。新真源 `D:\AIWorkflow\ComfyUI_H3\千问云端_工作流规则.md`，并登记进 `build_manual.py` 文件地图 → 手册 `03_使用规范与关口流程\`（**手册里那份是生成副本，改它＝下次刷新被覆盖**）。
- 影响范围：**所有通道的提示词判据与关口流程**。分治的是"格式契约／机检判据／关口流程／工具链"；任何一条通道上实测出的坑（元叙述句被 H3 当台词念出、器材名词被实体化画进画面、否定式在 H3 压不住命名先验）**不得**当成另一通道的既定结论。已同步登记 4 处：`00_读我\读我_总览与导航.md`（必读第 7 行）、`00_读我\硬参数速查表.md`（§1.7 通道分工表第四行）、`20_通用规范层\R2_提示词结构与接口契约.md`、`20_通用规范层\R_作用域与例外登记表.md`（"整段不适用"行）。
- 相关文件：`D:\AIWorkflow\ComfyUI_H3\千问云端_工作流规则.md`（真源）、`C:\Users\若水\.qoder\skills\qianwen-find-skills\`、`@qianwenai/qianwen-cli` 1.9.0（全局，出版方 `qianwenai-dev <…@alibaba-inc.com>`，发布包无 install 钩子）、`E:\_统一备份\`；**09-28 12:12 补装 `qianwen-forge-pack` 六个技能**＝`qianwen-{model-selector,text,image-generation,video-generation,audio-tts,vision}`（均 v0.0.2，skills 目录 37→43）；核验件 `disk_org\verify_forge_pack.py`／`scan_pack_scripts.py`／`skills_装forge-pack前_名单.txt`；真源 §4.1 记了凭证只读 env/`.env`（`DASHSCOPE_API_KEY`／`QIANWEN_API_KEY`，**键值不入库**）、外联只有 `dashscope.aliyuncs.com`／`platform.qianwenai.com` 等官方域、无 `eval/exec/pickle/ctypes`
- 决策/结论：**★只共用机制层**——作用域与例外登记／冲突编号裁定／**未实测一律默认关（记 `on=[]`）**／真源→副本单源生成／copy→逐份 sha256→才删源／回归四件套。把"分治"做成"每条规则抄四份"就是手册 风险 22 与 C69 记的同一个病。**代码侧暂不加第四通道**：`check_preflight.py:558` 的 `channel_of()` 只出 `h3/cloud/image`，加分支前必须先有**可判的格式契约**，而千问通道本机实测为零。现行口径＝**千问稿不过 G7**，人工过一遍并留痕。
- ⚠️ **给下一个工具提醒（本条初稿写错过因果，读实现才改对，留痕在 风险 28）**：千问稿**不是**被判 `cloud` 继承十块判据——`channel_of()` 的兜底是 `else "h3"`（`:573`，只有 `provider ∈ {ark,cloud}` 或 `kind ∈ {cloud,sd,seedance,ark,kling,vidu,hailuo}` 才归 cloud），所以千问稿**默认落 h3 通道、被 G7 error 拦死**：普通文本命中 `:674`「认不出格式」，写成中文十块命中 `:668`「混用」。只有**显式** `--channel cloud` 才会真的跨通道套用云端判据（缺核心五块 error、器材名词按 `cloud` 降 warn）。

### 2026-09-28 ｜ 备份验收器报假绿，已修；验收口径改为「缺 0 且 陈旧 0」（C80／风险 29）
- 摘要：`D:\AIWorkflow\tools\backup_now.py --check` 修前只数"备份里缺的文件"，**文件在但 sha256 ≠ 活区**那一类既不落 skipped 也不落 new、被 `continue` 静默丢掉 ⇒ 备份明明落后仍报「0 个文件需要处理」。而备份模式每次都写**全新时间戳目录做全量拷贝**（根本没有"增量跳过"），所以"活区比最新快照新"只有 `--check` 能发现——恰好又看不见。
- 影响范围：`E:\_统一备份\` 四类（手册／记忆／引擎配置／自产脚本）的**验收语义**。实测抓到的一次：活区 100,194 B / `16ca6c04…` vs 快照 99,607 B / `6d8d41…`，旧版报 0。修后加 `stale` 计数，输出改 `缺 N ｜陈旧 N`，`需要处理＝缺＋陈旧`；立刻报出 5 处陈旧，跑一次备份归零。措辞同批改过三处入口文档：`00_读我\读我_总览与导航.md`、`E:\_统一备份\备份位置索引.md`、`D:\AIWorkflow\tools\一键备份.bat`。
- 相关文件：`D:\AIWorkflow\tools\backup_now.py`（改）、`D:\AIWorkflow\tools\一键备份.bat`、`E:\_统一备份\备份位置索引.md`
- 决策/结论：**T3「所有备份集中在 `E:\_统一备份\`」的验收从今往后＝「缺 0 且 陈旧 0」两个数一起看**。通用教训（风险 29）：**凡是"一个数字代表合格"的验收判据，先问它漏掉了哪一类失败**。明文凭证仍**不做第二份副本**（`E:\密钥文件` 只在索引里记位置）。

### 2026-09-28 ｜ 复核补漏：入口文档层 5 处旧口径与死文件名指针（C81）
- 摘要：复核本轮改动时，在"必读导航"里查出**前几轮改判据时漏掉的读者入口**——`读我_总览与导航.md` §3「快速上手」第 3 步还写着「写词按十块模板…中文十块是给**出首帧的图片提示词**用的」（C58/C59 已推翻，照这句写会被 G7 判混用 error）；同文件「五层文档」表三个文件名指针全死（`H3提示词工程规则方案_v2.1_真源.md`／`H3提示词规则_现行合并版_20260927.md`／`H3本地出片_使用规范_用前必读_20260913.md`，这三个 09-28 都按"去掉过期日期戳"改过名）。
- 影响范围：手册入口层（人类/agent 最先读的那一节），不参与机检 ⇒ 回归全绿也发现不了。已全部改成四通道分治版，并补 `--prompt-kind`／`--channel` 提示；速查表一条死锚（`check_preflight.py:458` 已漂到 G5 尺寸判定）改成关键词锚 `if ch == "image":`。
- 相关文件：`E:\本地工作流规范手册\00_读我\读我_总览与导航.md`、`00_读我\硬参数速查表.md`、`disk_org\audit_c79_claim.py`（新留的错因果扫描器）
- 决策/结论：**改判据时必须回头核"教人怎么开工"的那一节**（快速上手／目录导航／备份索引／bat 提示行）；做法＝grep 旧措辞再逐条改、改完复扫。导航文档内 57 个文件名指针已用脚本逐个 `exists` 复测＝**可解析 57、死指针 0**。

## 当前待办 / 阻塞

- [x] `qianwen-forge-pack` **已装**（09-28 12:12，6 个 skill 全 `installed` v0.0.2）：`model-selector`／`text`／`image-generation`／`video-generation`／`audio-tts`／`vision`；做法即下面这条＝先快照 skills 目录名单（37 个）→ 装 → diff＝正好新增 6 个、无越界写入
- [ ] 千问通道**本机实测仍为零**：上面 6 个 skill 一次都没真跑过生成 ⇒ 规则一律按 `[未实测]` 处理；且 ⚠ **`gossamer.py` 会往 stderr 打 `[ACTION_REQUIRED]` 提示 agent 去装 `qianwen-update-check`，本通道禁止据此自动安装或升级，只能报给用户**
- [ ] `check_preflight.py` 加 `qianwen` 通道分支 —— **阻塞原因**：缺可判的格式契约 ＋ 本机零实测件（手册 风险 28）
- [ ] 批 4：`check_layers.py` ＋两层对照总表＋开工 checklist（checklist 应含"新通道先实测再动代码"）
- [ ] 手册欠项：C11/C49 否定式待清、C1（武昭君仪走 H3 还是 Seedance）、真源版本戳 v2.2、批 3 通用层余 7 项
- [ ] 本库 `projects\local-file-organization.md` 仍停在 **2026-09-01**，未记 09-28 全盘整理（桌面清空为只留快捷方式、工作文件搬 `E:\创作\`、备份集中 `E:\_统一备份\`、清掉 5.46 GB）——**待回填**

## 关键路径速查

| 内容 | 路径 |
|---|---|
| 千问云端通道规则（真源，唯一可改处） | `D:\AIWorkflow\ComfyUI_H3\千问云端_工作流规则.md` |
| 云端 SD 中文十块（真源） | `D:\AIWorkflow\ComfyUI_H3\云端SD提示词模板_十块.md` |
| H3 提示词规则（真源） | `D:\AIWorkflow\ComfyUI_H3\H3提示词工程规则方案.md` |
| 跑前自审 G1–G12（通道派发在 `:558`／G7 在 `:652-690`） | `D:\AIWorkflow\tools\check_preflight.py` |
| H3 规则机检（期望 ok=214／info=32／warn=0／error=0） | `D:\AIWorkflow\tmp\wzy\h3_rule_gate.py` |
| 引擎回归（期望 108 passed） | `D:\AIWorkflow\engine\tests\` |
| 统一备份器（验收＝缺 0 且 陈旧 0） | `D:\AIWorkflow\tools\backup_now.py` ／ `一键备份.bat` |
| 手册副本生成器与自检 | `E:\本地工作流规范手册\99_维护\build_manual.py`／`check_tables.py` |
| 冲突裁定与结构风险（81 条／29 条） | `E:\本地工作流规范手册\00_读我\版本裁定与冲突表.md` |
| 唯一备份树 | `E:\_统一备份\`（＋ `备份位置索引.md`、`清理记录_20260928.md`） |
| 千问 CLI 与 SkillHub 技能目录 | `C:\Users\若水\AppData\Local\nodejs\qianwen` ／ `C:\Users\若水\.qoder\skills\` |
| 明文凭证（**不复制、不入本库**） | 见 `E:\密钥文件` |

## 注意事项 / 踩坑提醒

- **四条通道的规则不互借**：本地 H3 视频＝官方 I2VA 骨架（Ref2VA 走官方六段）；中文十块只属**云端 SD**；**图片口径无格式要求、只查共性坑**；千问云端另走自己的真源。写词前先认通道，跨通道跑必须显式声明 `--prompt-kind`／`--channel`。
- **千问稿现在不过 G7**：机器还没认这条通道，送进去会被 H3 判据 error 拦死（不是静默放行）。要人工过一遍并留痕。
- **别用 `--channel image`／`--channel cloud` 凑**千问稿——两种都是误标。
- **`E:\_统一备份\` 验收看两个数**（缺／陈旧）。只盯"0 个文件需要处理"会重蹈这次的假绿。
- **手册 `02_/03_/08_` 下是生成副本**：改内容一律回真源，再跑 `build_manual.py`；`--check` 报「源缺失 0／落后 0」才算同步。
- **行号属易碎指针**：改过判据链后行号会漂（本轮就抓到一条指向 G5 的"图片分支"死锚）。引用规则用「节名＋关键词」。
- **`qianwen skills` 的 `verified: true` 只是平台标记**，不是独立安全审计、也不是官方出身证明；实测 `@bailian/*` 若干条 `publisher` 字段为空。那条 `sha256` 是**包/载荷摘要**，不等于 `SKILL.md` 单文件哈希，别拿它判篡改。
- SkillHub 里带**规则性**的 skill（提示词生成类）本机一律按 `[未实测]` 参考资料用，**不得**写进 H3／云端 SD 那两份真源；要升级成判据，先有同帧实测件＋人审标签。
- `qianwen` 的 preflight 用 `command -v qianwen`——Git Bash 可用，**PowerShell 要换 `Get-Command qianwen`**。
- 历史运行记录（`cfg_*.json` 的 `prompt_file`、`.anchor.json` 的 `source`）**故意不改写**，改了＝伪造记录；代价是复跑先撞"文件不存在"，这是想要的失败方式。

### 2026-10-08 ｜ 打戏多镜正向经验固化（空间轴/空拍/命中）
- 摘要：15s 双人打戏（05横刀×06长剑）迭代 v1–v9 后由用户确认「节奏就很好」。固化四条：①**镜间空间连续**＝上一镜末帧抽帧作下一镜 H3 首帧锚 + 提示词写死开场区域与禁止回起点（用户抓过：第一镜打到甲板边缘第二镜回起点）；②**空拍≠倍速**——动作间隙停顿用 ZERO DEAD AIR／动作搭接，不是 setpts；③**每一挥必须打实**（2 帧内反应）；④**顺镜可测**＝大位移+环境反馈，帧差 mean~12 vs 慢镜~3（ffmpeg 小图帧差）。H3 每镜 5.17s 写 4–7 微动作。
- 影响范围：H3/云侧多镜动作类提示词与拼片流程；与既有「一镜一事件」并行不悖（一镜内多拍、镜间空间连续）。
- 相关文件：`D:\AIWorkflow\tmp\fight30d\*.txt`（提示词样本）、`E:\创作\人物角色库\fight30\双人打戏_高密度15s_v9.mp4`。
