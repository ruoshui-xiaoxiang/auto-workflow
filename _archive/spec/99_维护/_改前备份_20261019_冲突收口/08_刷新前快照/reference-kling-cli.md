---
name: reference-kling-cli
description: 可灵官方 CLI 本机调用方式与账户信息——2026-09-22 升到 0.2.0（motion_control／动作库／element 仍未实测），git-bash shim 坏需 node 直调 dist/cli.js；★v3_0_turbo 实测 100 灵感值/10s/1080p＝10 分/秒、154 秒出片、无 enable_audio 参数但自带音轨；余额 3036→1796 且 CLI 不回到期时间与单价
metadata:
  type: reference
---

可灵官方 CLI（`@klingai/cli-cn`，中国区 klingai.com）已安装并登录（OAuth 凭据在 `~/.kling/.credentials`，勿读取勿展示）。**2026-09-22 从 0.1.3 升到 0.2.0**（`npm i -g @klingai/cli-cn@latest --registry=https://registry.npmjs.org`，4 秒完成，登录态不丢——凭据存在 `~/.kling/` 与包目录无关）。

**0.2.0 新增（0.1.3 里 `who_am_i` 已声明但无子命令，敲了会回落到总帮助）**：`motion_control`（`--image <角色图>` + `--video <动作参考视频>` 或 `--motionId`，模型 `kling-video-v2_6`／`kling-video-v3_0`，720p/1080p）＝**把一段视频的动作搬到一张角色图上**；`motion_library_list`＝官方动作库（不用自备参考视频）；`element_*`＝多主体元素（同框锁多个角色那条路）。⚠️ 这三条**本机均未实测**，2026-09-22 只跑到"命令存在、能拿 inputSchema"。

**调用方式（git-bash 下 npm shim 损坏，`kling` 命令会把模块路径拼到 git 安装目录导致 MODULE_NOT_FOUND）**：
```bash
KL="$LOCALAPPDATA/nodejs/node_modules/@klingai/cli-cn/dist/cli.js"; node "$KL" <command> ...
```
node/npm/npx 都在 `$LOCALAPPDATA/nodejs`（本会话 shell 里 `node` 直接可用）。遥测 flag 随版本走：`--skill-name kling-cli --skill-version 0.2.0`。

**账户**：userId 4794178341，SVIP 铂金会员。**余额在掉：2026-09-22 上午 3036 → 当晚 1896 → 提交一条样片后 1796**。⚠️ **`account` 只回总数，不回到期时间、不回到期分批**——用户说"有积分快到期"时无法从 CLI 核实，只能引导他去官网/App 的灵感值流水看。who_am_i 里也**没有单价字段**（`availableModels` 只有 model/alias/description/arguments/inputs，全表 grep 不到 credit/cost/price），单价只能提交一条后对比前后 `availableRemainCredits`。

**★2026-09-22 实测 `kling-video-v3_0_turbo` 图生视频（太空战样片）**：
- **10 秒 / 1080p ＝ 100 灵感值**（1896→1796 当场核出来），合 **10 分/秒**，是 v2_5（25 分/5s＝5 分/秒）的**两倍**。⇒ 227 秒整片 ≈ **2300 分 ＞ 当时余额 1796**，报价前一定先算这一步。
- **154 秒出片**（本地同题材一条 1344×768/192 帧要 634 秒）。
- 参数表只有 `prompt / duration(3–15) / resolution(720p|1080p) / imageCount`，**没有 `enable_audio`**（v3_0 才有）——但**产物仍自带一条 aac 128kbps 44.1kHz 立体声音轨**，别以为没开声音。
- **喂 1344×768（7:4）首帧 → 输出 1904×1088**：它自己升到 1080p 级、保住原比例，不会强掰 16:9。
- 用法：`node dist/cli.js image_to_video --image "<本地绝对路径>" --model kling-video-v3_0_turbo --duration 10 --resolution 1080p --poll 900 "<中文提示词>"`；`--image` 自动 file_upload，`--poll N` 会一直等到出结果（日志行 `[kling] <id>: RUNNING (+Ns)` 在前、JSON 在尾）。
- ⚠️ 结果 JSON 里的 `urlWithoutWatermark` 是带签名长直链，**含 `&`/`+`/`=`，curl 必须整条用单引号包住**，否则被 shell 拆开；下载完立刻 `cv2` 验帧数/尺寸/sha256 再报成功（链接有保留期）。

**首尾帧**：`image_to_video` 支持 `--tailImage <url|path>`（首尾帧双图）；duration 5|10、resolution 720p|1080p；单图模型只有 first_image，双图参考需 o1/v3_0_omni。

**2026-09-22 重核 `who_am_i` 的档位**：i2v 有 v2_5／v2_6／o1／v3_0／v3_0_omni／v3_0_turbo。**v3_0 与 v3_0_omni 支持 3–15 秒、720p/1080p/4k、一次最多 4 条候选（`imageCount`）**；`kling-video-o1`/`v3_0_omni` 吃 `image_1…image_7` 多参考图（＝我们本地 ref2va 的对应物）。⚠️ 除 v2_5 外**全部单价未实测**。
**⚠️ 产物链接有保留期，提交完必须立刻下载**（同日 ARK 那条签名 URL 是 24h 失效）；`--quiet` 的输出**前面有 `[kling]` 日志行，JSON 在最后一行**，解析要 `startswith('{')` 取尾行，直接 `json.loads` 整个文件会炸。

**实测价格**（2026-09-07）：image_to_video `kling-video-v2_5`（性价比款）5s 1080p 无音频 = **25 灵感值/条**，单条约 60s 出片；批量 6 条（3 条并行提交）约 75s 轮询一轮全部完成。omni/3.0 系（多图参考）更贵，未实测。图生视频单图模型只有 first_image（首帧即角色锚）；双图参考需上 `kling-video-o1` / `kling-video-v3_0_omni`（prompt 必填、用 图片1/图片2 引用，o3 支持 4k）。

**批量生产经验**：并行提交无冲突；`--quiet` 输出单行 JSON，用 `grep -o '"urlWithoutWatermark":"[^"]*"'` 提取直链后 curl 直接下载。v2.5 参数：duration 5|10、resolution 720p|1080p（默认 1080p）、enable_audio 默认 true（无音频片必须显式 false）、audio_prompt/music_prompt 可指定环境音/配乐（仅 enable_audio=true 时生效）。**2026-09-09 实测：enable_audio=true 不加价（仍 25 灵感值/5s/1080p），enable_audio=false 出无音轨 mp4（mp4 无 soun box 验证）**；"带配音一步到位"＝v2_5＋audio_prompt（接导演表声音列），全静镜 enable_audio=false。本地图片路径由 CLI 自动 file_upload，无需手动上传。

**教训（2026-09-09）**：提交命令的输出**勿用 tail/截断**——generationId 只在提交回执里返回一次，CLI 无任务列表、`http.log` 也不记提交回执，丢了该条就白扣费（丢过 S42 试点一条 25 灵感值）。提交后立刻把 generationId 落盘再轮询。

**批量管线（2026-09-09 E1 54 镜实测）**：并发 6 一波提交+轮询下载，54 镜端到端约 4 分钟；并发 6 上传触发过一次 400 限流（"too many requests"，提交未发生不扣费，单条补投即过）。可复用模式：spec 生成（导演表声音列→audio_prompt、全静镜 enable_audio=false、对白剥离留后期 TTS）→ bash 驱动并发提交+ledger 落盘 → 轮询轮脚本下载无水印 mp4。**v2_5 音频只出环境音/配乐，出不清字句对白**——台词镜的 audio_prompt 只写去对白后的环境声。

**可灵提示词公式（2026-09-22 从《「可灵 AI」驯服指南 V2.0》取，托管在轻雀文档、留下 `kling@kuaishou.com` 与 `klingai.kuaishou.com`、**有快手团队特征但无署名认证**，按中等可信度用）**：

```text
提示词 = 主体（主体描述）+ 运动 + 场景（场景描述）+（镜头语言 + 光影 + 氛围）
```

括号内可选。纪律：主体描述写外貌细节与肢体姿态、可用多个短句列举；**运动不宜过于复杂、要符合 5 秒视频能展现的画面**；场景含前景背景、同样按 5 秒的量控制；**镜头语言要"与运镜控制作区分"**（镜头语言写进描述，运镜走控制面板/参数）；文生视频支持 5s/10s 与 16:9/9:16/1:1，"高性能"更快、"高表现"画质更好。

⚠️ **服务端声明里 prompt 是可选的**："Optional motion/scene prompt; **the input image is the primary driver**"——**图主驱动、文字辅助**，跟 H3/Seedance"文字为主"相反。所以可灵这边优先用**短、正、点名可见变化**的写法；我们的同帧实测也印证：长禁止句墙 1.09 → 短句正向 2.34（flow_mean）。三家规范的对照表与编译映射见技能里的 `cinematic-video-production/references/prompt-specs-by-engine.md`。

相关：[[wuyin-demo-pipeline]]（本项目用它做《无音》视频测试）。


## 2026-09-23 实测补记（末四镜对照）
- **CLI 真身路径**：`C:\Users\若水\AppData\Local\nodejs\node_modules\@klingai\cli-cn\dist\cli.js`（`~/AppData/Local/nodejs/kling` 那个 sh 包装在 git-bash 下不可靠）→ `cd` 到包目录跑 `node dist/cli.js <cmd>`。
- **i2v 单价实测**：`kling-video-v3_0_turbo` / **720p / 3s = 24 分**（＝8 分/秒；1080p 才是 10 分/秒）。`duration` 支持 3–15 逐秒取，**按成片实际秒数提，不要多要再裁**。
- **`query_tasks` 同时返回带水印与无水印两条链**：JSON 里有 `url` / `url_without_watermark`（驼峰版 `urlWithoutWatermark`）。**抓 `.mp4` 的第一条命中往往是带水印的**——必须显式取 `url_without_watermark`，否则右下角有"可灵AI"logo。取无水印链**不重复扣分**（同一条 generation，链 24h 有效）。
- `who_am_i` 的 `availableModels` 按族列（image_to_video / text_to_video / image_to_image / text_to_image / motion_control），每族给 model＋arguments allowedValues＋inputs；**没有默认 model，必须先 who_am_i 再选**。
- 账号态：SVIP 铂金，`account` → `availableRemainCredits`（本次 1672→1552，四镜 120 分）。
- **可灵 i2v 忠实保留首帧构图**（镜32 红色舰桥＋盘坐背影原样保留，不是漂移），运动有层次；但**首帧本身的缺陷会被一并保留放大**。


## 2026-10-02 实测补记（t2v 参数契约到手，但余额耗尽）

零成本探针（`kling who_am_i` ＋ `text_to_video --help`，均只读）拿到的**服务端实时声明**，别抄成长期事实：

- 接入活着：`status 200`、`mcpVersion 1.3.3`、userId 4794178341、`authMode` 有值。
- 能力族 **6 个**：`text_to_image`／`image_to_image`／`text_to_video`／`image_to_video`／
  `motion_control`／`omni_ref_video`。
- **t2v 模型**：`kling-video-v2_5`（别名 v2.5Turbo）／`v2_6`／`o1`。
  `duration`：v2_5／v2_6 **只有 5｜10**（默认 5）；`o1` 支持 **3–10** ⇒ 想要 3–4 秒短片只能选 o1。
  `aspect_ratio`：**16:9｜9:16｜1:1，默认 16:9** ⇒ 做竖屏必须显式写 `--aspect_ratio 9:16`，吃默认＝废件。
  `resolution`：720p＝`std`／1080p＝`pro`，**默认 1080p（高计费档）**。
  `imageCount`：1–4，含义是**一次出几条候选**，⚠ 不是"挂几张参考图"，两者别混读。
  `enable_audio`：**默认 true**（音画同步直出）；`enable_asmr` 默认 false；`audio_prompt`／`music_prompt`
  都**依赖 `enable_audio=true`**，关音频时一并失效。⚠ 用户 10-02 明确：这一条**不设硬规则**，按每次需要调。
  **声明里没有 `seed` 参数** ⇒ 已证：可灵 t2v 不支持 seed，跨镜一致性只能靠锚点＋逐镜点名。
- 提交契约（照抄服务端，别自己发挥）：**`Every job is charged; do not submit trial jobs`**＋
  参数或意图不确定**必须先问用户**；不许自动重投、不许静默改参数；返回 `generation_id` 后用 `query_tasks` 轮询终态。
- 🔴 **本次提交被挡回：400 `Insufficient credits`**（充值入口在报错原文里）。⇒ 与 09-23 记的 1552 分相比余额已耗尽；
  且 `who_am_i` **没有任何 credits/单价字段**，报价只能靠提交前后对比。下一步三条通道实测全部**卡在等充值**。
- CLI 提示有新版 **0.2.1**（当前 0.2.0），`npm i -g @klingai/cli-cn@latest`；升级与否归用户定。

## 可灵容易出卡通感（2026-09-23 用户点名＋同批实证）
同一批四条：**镜30 没跑偏、镜31 跑偏**。差别不在提示词，在**首帧有没有硬几何**——30 的锚图弧面自带板块接缝网格，模型照着长；31 的锚图表面是软噪声，模型填成"月球岩石＋等亮度一排路灯点"＝游戏 CG 感。
- **结论：卡通感一半由锚图决定**，硬表面锚图必须自带直线／直角／接缝网格，不能靠灰噪纹理；提示词是第二道。
- 可灵**没有负面词参数**，只能正向加码：写"轧制钢板／焊接缝／铆接边／笔直接缝网格与阴影凹槽／单一低角度冷白硬光＋明确明暗交界线／IMAX 65mm 胶片观感／轻微颗粒与真实色散"。
- **诱发卡通的词别写**：发光带、能量流光、梦幻、唯美、史诗奇幻、外星地表、尘埃弥漫、磨砂、霓虹；器材名会被实体化渲进画面（同 [[feedback-r2v-prompt-camera]]）。
- 判"卡通没卡通"三条：①表面有没有笔直接缝与硬阴影凹槽；②灯光是不是随透视衰减的工业灯列而非等亮一排亮点；③明暗交界线是否单一硬光可解释。
- 约束段全文见 `C:\Users\若水\Desktop\仙女星系战争项目\即梦_末四镜_提示词.md` §可灵专用·写实约束段。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- git-bash shim 坏→`node dist/cli.js`
- **2026-09-22 实测 v3_0_turbo 10s/1080p＝100 分（10 分/秒，是 v2.5 的两倍）、154 秒出片、无 enable_audio 参数但自带 aac、喂 1344×768 出 1904×1088**
- 余额 3036→1896→**1796**（account 不回到期时间、who_am_i 无单价，只能提交前后对比）
- motion_control/动作库/element 仍未实测
- **产物签名链有保留期，curl 要整条单引号包住并立刻下载**
