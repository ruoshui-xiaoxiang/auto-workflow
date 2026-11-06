---
name: reference-dreamina-canvas-cli
description: 即梦画布 CLI（dreamina-canvas.exe）安装位置、两段式设备流登录、画布/节点协议与实时模型目录；与老的 dreamina.exe 是两套东西（画布编排 vs 直接出图）
metadata:
  type: reference
---

即梦官方第二把 CLI：**画布编排**（2026-09-28 装好并登录验证）。与 [[reference-dreamina-cli]] 的 `dreamina.exe` **是两套独立二进制、两种用途**——老的负责直接出图/出视频，新的负责在即梦画布（canvas）里编排节点成片。**同一账号**（userId `110198628111`、vipLevel `artisan`，与老 CLI 一致）。

- **安装（2026-09-28）**：官方脚本 `https://jimeng.jianying.com/canvas-cli/install.{sh,ps1,bat}`。**别直接 `irm | iex` 管道执行**，先下载审一遍再跑本地副本——脚本本身质量不错（强制 HTTPS、tar 条目查路径穿越、替换二进制前先跑一次 `version` 验活、失败回滚），审过再用仍是更稳的习惯。
  - ⚠️ **git-bash 里跑 ps1 会因 PATH 污染失败**：脚本用 `Get-Command tar.exe`，git-bash 的 `usr/bin` 在里面时会同时抓到 git 的 tar 和 Windows 的，报 `CommandNotFoundException`。**修法**：给 PowerShell 一个干净 PATH 再调——
    `powershell -NoProfile -ExecutionPolicy Bypass -Command '[Console]::OutputEncoding=[Text.Encoding]::UTF8; $env:PATH=[Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User"); & "<install.ps1 绝对路径>"'`
- **落盘位置**：二进制 `C:\Users\若水\bin\dreamina-canvas.exe`（v1.0.1，commit `09307bb`，构建 2026-09-16）；Skill `C:\Users\若水\.agents\skills\dreamina-canvas-cli\`（`SKILL.md` ＋ `references/` 五份：authentication / completion-and-validation / credits-and-hitl / identity-and-references / recovery-and-idempotency）。装完**要把 `~\bin` 写进用户 PATH**，但当前终端/宿主进程读不到新 PATH ⇒ **agent 侧一律用绝对路径调**，人重开终端后可直接敲 `dreamina-canvas`。
- **认证＝OAuth 设备流，两段式**（agent 可全程代跑）：① `auth login`（加 `--non-interactive`）**立刻返回** `status=authorization_required` ＋ `challenge.{deviceCode,userCode,verificationUri,verificationUriComplete}`（`expiresAt` 约 10 分钟）；② 把 `verificationUriComplete`（**已内嵌 user_code，页面不会再让手输**）给用户去浏览器点；③ `auth wait --device-code <deviceCode> --timeout 9m` 挂后台等，回来 `status=logged_in`。实测凭据 `expiresAt` ≈ **6 小时**（20:01 登 → 次日 02:01）。**授权链接约 10 分钟失效，递链接时要说明"先开链接再干别的，过期就说我重起"**（同 [[reference-ark-account]] 的 SSO 坑）。
- **凭据后端（Windows）**：`HKCU\Software\BytedAuthClient\keychain` 当前用户注册表＋DPAPI 加密；**不导出 token**、不迁进工作区。`environment: prod` / `region: cn` / `authMode: oauth`。`--profile` 可隔离多份本地登录态。
- **命令面（9 个一级命令）**：`canvas`(create/ls)、`node`(create/edit/upscale/show/find/quote/confirm/run)、`model`(list/find)、`voice`(list)、`resource`(get/upload/download)、`operation`(status/wait)、`auth`、`schema`、`version`／`completion`。**一切可执行事实以 `schema`（255KB）为准，不许猜 flag**。
- **协议要点**：报价≠授权——`node quote` 出价、`credit-token`/`credit-ceiling` 走人工批准，超 ceiling 必须停下问人；`node create/edit` 都有 `--dry-run`（本地校验、`sideEffects:[]`，但会诚实列出 `unverified:[authentication,project_access,authoritative_draft_state,model_specification]`）；引用优先 `--ref node:<node-id>`（保留画布上游连线），要绑定正文位置才用 `{{node:<id>}}`；批量 `node run` 必须**每个 node-id 配一个 submit-id**。
- **踩过两个必填坑**：`node create image` **必须给 `--title`**（否则 `CLI_INPUT_REQUIRED fieldPath=title`）；`node show` **必须给 `--node-id`**（帮助里写成可选，实际不给报 `CLI_INPUT_REQUIRED`）。错误是结构化的（`class`/`requiredAction`/`validation.reasonCode`），**按字段分支、别解析本地化 message**。

## 实时模型目录（2026-09-28 `model list`，9 图 / 9 视频 / 3 音频）

- ★ **prompt 长度硬上限（09-28 复核补测：`--prompt` 的 `maxLength`）**：**图片侧 9 个模型全部 2000 字**；
  视频侧 `seedance_2.5` / `seedance_2.5_draft` **15000**、`wan_3.0` 20000、`minimax_h3` 7000、`seedance_2.0_vip/_mini/_fast_vip` 4000、`happyhorse_1.1` 2500、`seedance_pro_fast` **2000**。
  ⇒ 写长稿前先算字数（现役服装/角色提示词 636–928 字，尚有余量但不多）。通道规则落在 `D:\AIWorkflow\ComfyUI_H3\即梦云端_工作流规则.md`（冲突表 C82）。

- **图**：`seedream_5.0_pro`(i2i 1–10 图；t2i 0–14)、`seedream_5.0_lite`、`seedream_4.7/4.6/4.5/4.1/4.0`（各 i2i 1–6）、`high_aes_general_v50_flash`、`jm_image_model_yc_mj82`(i2i 1–20)。**每个 image mode 都必须给 `--resolution`（1.5K/2K/4K），`--count` 上限 4**；`--ratio` 八档含 9:16。
- **视频**：`seedance_2.5`（m2v 1/50＝**30 图＋10 视频＋10 音频**，与 ARK 侧额度一致）、**`seedance_2.5_draft`（样片版，独立模型）**、`seedance_2.0_vip/fast_vip/mini`、`seedance_pro_fast`(别名 `seedance_1.0_fast`)、**`minimax_h3`**、**`happyhorse_1.1`**、**`wan_3.0`**。多数有 `t2v` / `m2v` / `first_last_frame`(1 图或 2 图两种规格)。
  - ⚠️ **与 ARK 的差别值得记**：ARK 侧记忆写"Seedance 2.x 不支持 draft 样片模式"，**画布侧确实有 `seedance_2.5_draft`**；且 `minimax_h3` / `happyhorse_1.1` 在画布目录里有，而 ARK 视频目录只有 seedance 2.5 一档（见 [[reference-ark-account]]）。
- **音频**：`legacy_tts`(mode `tts`，不传 `--model`、只传 `--voice-name`)、`seed_audio_v1`(mode `unified_edit`)、`seed_music_1.0`(mode `music`)。`voice list` 两个 TTS 模型**各 100 条音色**（`--count` 上限 100，翻页用返回的 nextOffset）。
- **用户已有画布**：`canvas ls` 返回 1 个 `视频创作`，projectId `ec58592b-8316-4334-af77-6aea2f85c6f7`，里面是**官方模板工作流**（节点：视频创作工作流说明 / 生成人物三视图 / 生成物品三视图 / 生成场景 / 生成场景俯视图 / 生成视频结果 / 视频编辑工作流说明…，多为 success）。⇒ 他之前在 Web UI 用过画布。

**How to apply:** 用户说"即梦画布 / canvas / 在画布里做"时走这把 CLI，用绝对路径 `C:\Users\若水\bin\dreamina-canvas.exe`；先 `auth status` 再 `model list --type X`，**不猜参数**。与老 `dreamina.exe`（积分制直接生图，见 [[reference-dreamina-cli]]）和 ARK（arkcli 按量）**三条通道别混着算账**。

## ★零花费探针：怎么问出单价/免费与否（2026-09-28 实测，可复用）

**问题**：画布 CLI **没有余额/积分查询命令**（顶层只有 `node quote`/`confirm`/`run`），且 `node quote` **只能对已保存节点报价**——不保存任何东西就问不出价。而 **CLI 没有删除节点/画布的命令**（`canvas` 只有 create/ls；`node` 只有 create/edit/find/show/quote/confirm/run/upscale），所以每次探针都会留痕，**删只能去网页版**。

**解法（一次调用既问价又不花钱）**：
```bash
dreamina-canvas --format json --non-interactive node create image \
  --project-id <pid> --title "价格探针·可删" \
  --mode t2i --model <canonical> --ratio 9:16 --resolution 2K --count 1 \
  --prompt "<探针提示词>" --run --credit-ceiling 0 --wait --timeout 5m
```
- `--credit-ceiling 0` 的语义是"只在报价 ≤ 0 时继续，**服务端免确认也不解除该上界**"⇒ **免费就真出图（花 0），不免费就停在报价、退出码 10、绝不扣费**。两个方向都拿到确定答案。
- 退出码 **`10` 不是失败**：`error.code=cli.generation_credit_ceiling_too_low`、`requiredAction=confirm`，`creditConfirmation.minimumCreditCeiling` **就是单价**，`partialData.items[]` 给出 `nodeId`＋`submitId`。
- **续跑要复用那两个身份**：复用同一 `submitId` 是重放首次运行**不会二次扣费**；换新 submitId ＝ 第二次运行、再扣一次。复用同一 `nodeId` 才不会留孤立节点。
- ⚠️ `--credit-ceiling` 若被当成"未提供"，非 TTY 下同样停在报价（退出码 10），**依然不扣费** ⇒ 探针在这个 CLI 上无论如何不会误花钱。

**★实测单价全表（2026-09-28，`node quote` 权威报价，单位＝积分/张，9:16 / --count 1）**

| 模型 | 1K | 1.5K | 2K | 4K |
|---|---|---|---|---|
| `seedream_5.0_pro` | — | 5 | **8** | 12 |
| `seedream_5.0_lite` | — | — | **3** | 4 |
| `seedream_4.7` | **1** | — | **1** | 2 |
| `seedream_4.6` | — | — | **1** | 2 |
| `seedream_4.5` | — | — | **3** | 4 |
| `seedream_4.1` | — | — | **1** | 2 |
| `seedream_4.0` | — | — | **1** | 2 |

- **一档都不免费**（用户以为 5.0lite 免费，实测 3 积分/张）。**挂参考图（i2i）与纯文生（t2i）同价** —— 每档报出来的数完全一样（ARK 侧"多图输入 ¥0.02/张"那条**不适用于即梦**）。
- **反直觉点：`4.5` 是 3 积分，反而比 `4.6`/`4.7` 的 1 积分贵三倍**；`4.0/4.1/4.6/4.7` 全是 1 积分/张（4.7 还支持 1K，同样 1 积分）⇒ **要省钱用 4.x，别用 4.5**。
- 4K 约为 2K 的 1.33–1.5 倍（不是翻倍）；`5.0_pro` 的 1.5K＝5 比 2K＝8 便宜。
- **跨通道互证**：`5.0_pro` 2K＝8 积分，与老 `dreamina.exe` 侧 2026-09-15 实测的"5.0Pro 2K 一张扣 8"**完全吻合** ⇒ 两个 CLI 共用同一套积分价目，可互相校验。
- ⇒ 用户问"是不是免费的"时，**别引用早期"artisan 生图 credit_count=0"那条**（早已不成立），也别引"画像类免费"。整档只有 1 积分的低频价，但**没有免费档**。
- **分辨率/参考图上限（同批实测）**：4.7 是唯一支持 **1K** 的；只有 `5.0_pro` 支持 **1.5K**；其余最低 2K。i2i 参考图上限：`5.0_pro` **1–10 张**，其余各档 **1–6 张**；`--count` 上限 `5.0_pro` 是 **4**、其余 **8**。所有档 `vipResolutions: ["4K"]`（`5.0_pro` 是 1K/1.5K/2K/4K **全档要 VIP**，他是 artisan 不受限）。

**省留痕的扫描手法（比一档一节点省得多）**：`node create`（**不带 `--run`**，只保存不生成）建 **1 个**探针节点 → 每档 `node edit image --node-id X --model <m> --resolution <r> ...` 改配置 → `node quote --node-id X` 读 `data.totalMaxCredits`。**quote 是只读、永不签发 token**，所以整轮零花费、只留 **1 个**节点。本次 23 次报价全免费。

**⚠️ 两个新踩的契约坑**：
1. **`--ref` 必须写成 `node:<node-id>`**，只传裸 node id 会报 `cli.invalid_generation_reference`（"Invalid generation reference"）。第一轮 7 个 i2i 报价全因此失败，加前缀后 7/7 通过。文档里 `--ref node:<node-id>` 的写法是字面要求，不是占位符。
2. **`--clear-generation` 不能和设置值的 flag 同传**（如 `--model`/`--prompt`），报 `CLI_INPUT_FLAGS_CONFLICT`（"Choose either setting a value or clearing it"）⇒ 要改档就**只传新值**（引用会自动被新配置覆盖），要清空才单传 `--clear-generation`。

**How to apply:** 被问"某模型多少钱/免费吗"就走上面那条 ceiling=0 命令，**不要**先擅自真跑；拿到 `minimumCreditCeiling` 再报价给用户。探针节点删不掉，所以**先问用户放哪个画布**（本次放进了他现有的「视频创作」，节点 `node_kcpx69kqwx` 标题带"可删"，另留了未消费的 submitId `361144db-8e8f-4474-b7a8-17a35ccede99`）。

## ★把画布产物取回本地（2026-09-28 端到端实测，这是本 CLI 最好用的一面）

`resource download <resource-id> --project-id <pid> -o <目录|文件>` **是官方认证下载，不用跟签名 URL 打交道**，而且**服务端回传 `sha256`**（直接接锚点登记的哈希流程）。三种资源实测全通：

| 资源 | `source` | 实测结果 |
|---|---|---|
| 画布里的上传图 | `uploaded` | 1,433,209 B ＋ sha256 |
| **生成的图** | `generated` | 1,639,960 B ＋ sha256 |
| **生成的视频** | `generated` | 53,986,275 B（54MB mp4）＋ sha256 |

⇒ **帮助文字写的是"下载成功的图片素材"，实际视频照样下**，别被那句劝退。

**"能不能取回"取决于产物在不在画布里，不取决于谁跑**：
- 用户在**网页版画布**里手跑的 → 画布 CLI 全看得到（`canvas ls` / `node find` / `node show` 都能读到，他那个「视频创作」和里面节点本来就是网页版建的）⇒ **能整批取回**。
- 在**普通「生图」页**跑的 → 不在任何画布里，**取不回**（`resource` 只有 get/upload/download 按 id 取，**没有"列账号资产库"的命令**）。
- ⇒ 想省事又免费，就让他跑**画布页**而不是生图页；一句话的差别，结果差一整条通道。

**★网页免费 vs CLI 收积分（两条口径，别混）**：用户说"即梦手动选 lite 2K 出图是免费的"，**实测为真**——网页画布出的一批资源 `resource get` 回 **`creditsAmount: 0`**；而同模型同档 **CLI 报价 3 积分/张**（见上表）。⇒ **生成留给用户手跑（免费），agent 只负责取回+机检**，这是当前最省的协作形态。

**取回循环怎么写**：`node find --project-id <pid>` → 逐个 `node show --node-id <id>`（返回是 **`data.nodes[]` 批量壳**，取 `nodes[0].node.resources[].{resourceId,source,status}`）→ 逐个 `resource download`；用 `source=generated` 区分"生成"与"上传"。

- ⚠️ **`node find` 单页最多 50 条，必须用 `--offset` 翻页翻到底（2026-09-28 实测差点漏掉一半）。** 参数：`--limit` 范围 1–50（给 80 直接 `cli.invalid_node_find_input`）、`--offset` 0–1000；循环判 `data.hasMore`，下一页 `offset += 本页条数`。**判据：先看 `data.total`，它跟你拿到的条数不一样就说明得翻页。** 我当时只调了一次 `--limit 50`，画布实际有 138 个节点，第一次"取回完成"其实只覆盖了 50 个。CLI 自己也声明**分页不绑定同一草稿快照、画布在动时可能重复或漏项、不能宣称完整快照**——所以要么等用户停手再扫，要么多扫几遍取并集。
- **`resource get` 的 `status: failed` 不是"下载失败"，是"生成失败"**：`resource download` 会回一个**看着像权限/路径错误**的 `cli.invalid_download_output`（"Invalid download output path"）或 `service.7`（"conflicts with the current state. Refresh the canvas"），**两种都是误导**。正解是拿 resourceId 去问 `resource get`：`status=failed` + `errorCode=20103` + `creditsAmount=0` ⇒ 该槽本来就空、无需取回、未扣费。**别把它当下载问题反复重试。**（`errorCode 20103` 疑似生成/审核失败，具体含义未证实。）
- **命名要防两种撞名**：① 画布里**多个节点可能同名**（同一次批量建的节点都叫「生成物品三视图」）⇒ 给重复标题加 `__<nodeId尾>` 后缀；② 同一节点的产物**没有 `index` 字段**（resources 里只有 resourceId/type/status/size），按遍历顺序自己编 1..n。**写脚本时如果拿运行计数器当序号，文件名会出现 `图片94_184.png` 这种跨节点的乱编号**，事后要按节点重编一遍。

- **CLI 没有删除节点/画布的命令**（`canvas` 只有 create/ls）⇒ **每批次开一个画布**：取回是按 projectId 整批扫的，一批一画布最干净、也不会与别的批次混。


## 真跑一条图的命令链（2026-09-29 实测，5.0_lite t2i）

`node create image` **不带** `--run` 时只建节点不扣分；要真跑得走三步，**flag 分散在三个子命令上，别乱塞**：

1. `node confirm --node-id X --credit-ceiling 12` → 回 `creditConfirmationToken`（**约 10 分钟过期**，所以 confirm 和 run 必须连着做，别批量先 confirm）。`--credit-ceiling` **只在这里**，`node run` 没有这个 flag。
2. `node run --node-id X --credit-token T` → 回 `submitId`。`node run` 只有 `--node-id/--submit-id/--credit-token/--project-id`，**没有 `--wait/--timeout/--interval/--credit-ceiling`**（塞进去直接 `cli.invalid_flag`，一个节点都不会跑）。
3. `operation wait <submitId> --project-id P --timeout 15m --interval 10s` → 终态字符串是 **`succeeded`**（节点 `status` 是 `success`，两边不同词，判完成要都收）。

- **★submitId 拿到后要立刻落盘，再开始等**。我第一版是等完再写 JSON，会话一断就丢了 submitId，恢复时只能重新 run ⇒ **同一提示词被提交两次、多花一倍出图**（T4/T5 各 8 张而非 4 张）。恢复逻辑应当是先查旧 submitId 并 `operation wait` 它，查不到才 confirm+run。
- **服务端每张产物回传 `creditsAmount: 0`**（CLI 跑也一样），`node quote` 报的是 `maxCredits 12/节点`＝**上限报价，不是实扣**。所以"这次花了多少积分"从 CLI 看不出来，要核只能去网页账单。
- 一次跑 5 条提示词的耗时：**每批 4 张约 51–61 秒**，串行 5 条约 5 分钟。
- `node find --name <标题>` 可用来在"建节点时没接住返回值"的情况下把 nodeId 找回来（响应体是 `data.node.nodeId`，**不是** `data.nodes[0].node.node_id`）。

## ★10-01 三坑三得（即梦图片侧）

**1. "塑料感"是用词问题，不是模型问题——同档 A/B 坐实。**
`seedream_4.5`／16:9／2K／同起手姿势，只换词：「华丽梦幻＋半透明披纱＋冷色光尘＋金线刺绣」出 CG 感；
换成「柯达 5219 胶片颗粒／35mm 定焦／**唯一光源是低角度冷色侧逆月光**／硬阴影／毛孔＋颊侧细绒毛＋干纹＋鼻翼泛油＋没有磨皮／甲面划痕＋指纹＋氧化暗斑＋磕碰凹点＋接缝积沙／织物经纬＋褶皱投影＋被沙磨脏的下摆／钢面拉丝＋旧崩口」，并**删掉漂浮光尘** ⇒ 四张全成实拍。
尺子：**标准差 46–55 → 64–68、近黑 0.9–1.9% → 3.7–9.9%**。⚠ **标准差不能跨构图比**（改全身镜后掉回 50–54，是匀质沙地摊平分布，不是塑料回来；看高频能量 212–237 仍升）。
⇒ **与 H3 侧 R19 方向相反**（H3 特写磨皮属模型层、词不加分）——两条通道不共用，见 [[feedback-per-channel-rules]]。词表全文在 `D:\AIWorkflow\ComfyUI_H3\即梦云端_工作流规则.md` §四-补一。

**2. 🔴 `creditsAmount` 不能当"没扣"的证据。** CLI 跑出来的产物**每张都回传 0**，是个不带信息的字段。
**唯一可依赖的花费信号是 `node quote` 的 `maxCredits`**（10-01 现查：`4.5` 2K count=4 报 **0**、`5.0_pro` 2K 报 **8**）。
我 10-01 一度把两者并列为"零花费双证"，那是**过度声称**，已在待审文档与通道真源里改口。⇒ 报"花了多少"只能引 quote，或去网页账单核。

**3. ⚠ Windows 文件名大小写不敏感＝缩略图覆盖原图。** 拼图脚本把 760px 小图写成 `m1.jpg`，
把同目录 3.4 MB 的 `M1.jpg` **原地覆盖**了（Windows 视为同名），四张原图一度只剩 37 KB。
⇒ 原图与派生小图**必须换字母前缀**（原图 `M1`／小图 `q1`），或分目录。
救回办法＝按登记过的 `resourceId` 重新 `resource download`，sha256 与首次下载值逐位相同＝服务端产物稳定。
（`resource download` **不覆盖已存在文件**，所以恢复要写进新目录。）

**4. 通道状态实际上已越过"人工执行"这条线。** 10-01 agent 侧用 CLI 连跑 4 批 t2i／24 张，
但 §八-1 那七步清单（`channel_of()` 分支等）没走。要不要正式改成 agent 代跑＝**用户裁定项**，已在真源 §一 挂了"未裁只记事实"的块。

### 10-01 15:41 「为什么出图不要积分」＝这个号是即梦 VIP，不是报价器坏了

- `dreamina-canvas auth account` → **`isVip: true, vipLevel: "artisan"`（匠人档）**。这是本 CLI 唯一能读到账号身份的命令（`auth status` 只回 loggedIn/过期时间）。
- **`node quote` 的 maxCredits 会随模型变**：`seedream_4.5 / 2K / count4` → **0**；`seedream_5.0_pro / 2K` → **8**。同一个报价器给两个不同数 ⇒ 它算的是"这一次扣不扣积分"，**会员权益内的档位就是 0，不是恒 0**。⇒ 之前那条"`creditsAmount` 恒回 0 不带信息，只有 `node quote maxCredits` 可信"继续成立，且现在有了正例支撑。
- `model list --type image` 里每个 model 的 mode 带 **`vipResolutions`**（4.5 是 `['1.5K','2K']`，更高档单独标 `['4K']`）——**4K 那档才是要额外付费的**。判"这次会不会花钱"看 `quote`，判"哪一档收费"看 `vipResolutions`。
- 🔴 **坑：`dreamina.exe user_credit` 在未登录时回 `total_credit: 0, user_id: 0, user_name: ""`——那是未鉴权的空返回，不能读成"余额为 0"。** 本机 `dreamina.exe`（与 `dreamina-canvas.exe` 是两个二进制、两套登录态）**10-01 仍未登录**；要读真余额得先 `dreamina relogin`，那步是 OAuth 扫码，归他本人，不代做。
- `dreamina-canvas` **没有** credit／余额命令（只有 auth／canvas／model／node／operation／resource／schema／voice）；想知道"还剩多少积分"只能走 `dreamina.exe user_credit` 那条，或去网页端看。

## 多参考 i2i 改单个物件的正确用法（10-01 实装，三批 0 积分）

`resource upload --file <path> --name <n>` 逐张登记 → `node create image --mode i2i --model seedream_4.5 --ratio 16:9 --resolution 2K --count 4 --ref res:<id> --ref res:<id> --ref res:<id> --prompt "$P"`；
**提示词里用 `{{res:<id>}}` 内联指代**，CLI 会把它拆成 `promptParts`（reference/text 交替）——这是"给每张参考图派一个职责"的唯一可靠写法。三批实测 4 张 2560×1440，`node quote` 全回 `maxCredits: 0`。

🔴 **`node create image` 现在必须带 `--title`**（不带 → `CLI_INPUT_REQUIRED / fieldPath:title`）；`--node-id` 仍省略。
🔴 **服务端会随机回 `service.1 / retryable_failure`**（10-01 首试即中一次、连失三次）⇒ 直接原参数重试 2–3 次即可，别改任何东西、别当成命令写错。

**为什么走挂图而不是写词**：V 批（纯写词）出的剑他判"太朴素"；挂真博物馆设计图（Wikimedia Commons `File:Swords GIM Gold.jpg`，CC0，英国王权剑＝金十字护手四臂末端圆盘＋深蓝珐琅人物浮雕）一批就把设计语言搬进来了。详见 [[reference-h3-prompt-rules]] 同族的 ⑫ 延伸与 `E:\本地工作流规范手册_使用规范与关口流程\即梦云端_工作流规则.md` §四-补四（P13）。

⚠ **参考图本身会漏东西进画面**：那张照片里有并排的第二把剑和一根金鞘，X/Y/Z 三批每条都有 1–3 张把鞘／第二把剑搬进画面，禁令句"别的剑、剑鞘不要进入画面"**没压住**。⇒ 挂图前把参考**裁到只剩目标物件**，比在提示词里加禁令有效。

## 🔴 `node create image` 没有 `--seed`（10-01 实读 `--help` 全参数确认）

完整参数只有：count / credit-ceiling / credit-token / dry-run / import-kind / interval / mode / model / node-id / project-id / prompt / ratio / ref / resolution / resource-id / run / submit-id / tag / timeout / title / update-id / wait / x / y。**没有 seed。**
⇒ 外部教程里"控制一致性可配合种子值"那类建议在**这个通道上无从执行**（与已记的 `Seedance 不支持 seed` 同族，别互借也别假设）。
⇒ 本通道能用的只有两条：**固定描述逐字复用** ＋ **挂参考图**（`--ref res:<id>`，i2i 支持 1–10 张）。

## ★10-01 晚：批量对照跑（12 节点 48 张 t2i）摸清的响应契约与成本闸

**三段式（本批用的就是这个，可整份复用）**：`node create image`（只保存不生成）→ `node quote --node-id X`（**成本闸：只在全 0 时才继续 submit**）→ `node run --node-id X --yes` → `operation wait <submitId> --timeout 8m` → `resource download <id> -o <绝对路径>`（绝对路径实测可用）。

**响应字段路径（别再猜）**：
- `node create image` → **`data.node.nodeId`**（与 09-29 那条"响应体是 data.node.nodeId"一致）。
- `node quote` → **`data.totalMaxCredits`**（另有 `data.items[].{nodeId,maxCredits}`、`confirmable`、`confirmationRequired`）。
- `node run` → **`data.items[].{nodeId,submitId,state,resources[].resourceId}`** ⇒ 🔴 **resourceId 在 run 的返回里就有，不必等 `operation wait` 再去解析**；先把 submitId＋resourceIds 落盘再等，会话断了不重复提交（与 09-29 那条"submitId 要立刻落盘"同因）。
- `operation wait` 的 `data` 结构本批没用到（下载靠 resourceId），别再依赖它取产物。

**★成本闸的真实边界（补 09-29 那条）**：09-29 记的是"`node confirm` 拿 `credit-token` → `node run --credit-token T`"。**那是收费档的路径。** 10-01 晚 **12 个节点 `seedream_4.5 / t2i / 16:9 / 2K / count 4` 全部 `quote=0`，此时 `node run --node-id X --yes` 不带 credit-token 直接跑通**（`confirmationRequired:false`）。⇒ **判"要不要 token"看 quote 报的数，不看命令模板**；quote>0 才回去走 confirm＋token＋ceiling。

**产物规格**：2K／16:9 出的是 **2560×1440 JPG，每张 3.2–3.6 MB**；48 张约 160 MB。
**幂等写法（一次跑 12 节点不重不漏）**：把 `title → {node_id, quote, submit_id, resources, downloaded}` 存进 `_nodes.json`，create/submit/harvest 三个子命令各自 `if 已有就跳过`；`downloaded` 要单独记（**不能用"有没有 resources"当已下载**——run 之后它就有了）。
**造提示词的自证模式值得复用**：臂＝基稿＋恰好一段追加，用 `arm.startswith(base+"，")` 且"去掉追加段后逐字等于基稿"来断言单变量；删词臂则"逐词 count==1 后 replace 重建期望串再逐字相等"，并配一条**与最长追加段逐字同长的零信息追加臂**＋一条**同长的删除对照臂**（否则测的是字数，见 [[feedback-prompt-iteration-priors]] ㉑㉒）。


## 出图数上限与可选底模（10-01 现查 `model list --type image`）

`--count` 上限**不是 4，是 8**（seedream_4.0 / 4.1 / 4.5 / 4.6 / 4.7 / 5.0_lite 全部 min 1 max 8；**5.0_pro 才是 max 4**）。
当晚所有对照批都用的 count 4 ⇒ **同一 prompt 一次可以拿 8 张候选，纯靠数量筛脸，不额外花积分**（quote 要逐节点确认）。
广场可选：4.0 / 4.1 / 4.5 / **4.6 / 4.7**（1K/2K/4K）/ **5.0_lite / 5.0_pro**（pro 的 i2i 参考图上限 10 张，其余 6 张；4K 属 vipResolutions）。
⇒ 换底模是"脸长什么样"这一层唯一真正的杠杆之一（另一条是挂真脸锚 i2i）；提示词改不动它——见 [[feedback-prompt-iteration-priors]] ㉒"磨皮不吃词"，以及 [[feedback-i-am-not-the-beauty-judge]]。
