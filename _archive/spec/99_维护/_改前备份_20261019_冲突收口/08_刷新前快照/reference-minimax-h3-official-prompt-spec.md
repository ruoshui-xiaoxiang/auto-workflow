---
name: reference-minimax-h3-official-prompt-spec
description: MiniMax H3 官方提示词规范就在权重仓 skills/h3-prompt-writing（SKILL.md + base-en.txt + ref-en.txt，已镜像到 D:\AIWorkflow\ComfyUI_H3\prompts\official_h3）——基础三字段/全参考六段的真名与顺序、片内 [Shot N] At MM:SS.mmm 多镜头切点语法、运镜受控词表（Type+Amplitude+Speed）、只定义角色/服装/影调的图不占 <Picture N> 而内联进 <Subject N>、retention_analysis 四档标记、4–15s 时长与 350–500 词口径
metadata:
  type: reference
---

# H3 官方提示词规范（2026-09-21 找到，一手的）

**位置**：`github.com/MiniMax-AI/MiniMax-H3` → `skills/h3-prompt-writing/`，含 `SKILL.md`（2.6KB）＋ `references/base-en.txt`（15.8KB）＋ `references/ref-en.txt`（23.6KB）。**就在我们下载权重的那个仓里**，随权重一起发，兼容任何能读本地文件的 agent（不需要 MiniMax 工具或专有运行时）。
已镜像到本地：**`D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\{SKILL.md, base-en.txt, ref-en.txt}`**（用 `gh api repos/.../contents/<path> --jq .content | base64 -d` 拉的，raw.githubusercontent 直连不通时走这条）。
同仓 `skills/` 下还有 8 个配方型 skill：`3d-animation-short-generator`、`handdrawn-live-video-generator`、`paper-collage-explainer-generator`、`papercraft-stop-motion-explainer`、`brand-promo-video-generator`、`co-op-game-intro-generator`、`minimalist-product-ad-generator`、`music-video-subtitle-generator`——**都是给 H3 用的，不是给别的模型的**，做对应题材前先去看。
平台文档侧另有 `https://platform.minimax.cn/docs/guides/video-prompt`（中文亮点示例）与 `https://platform.minimax.io/docs/guides/video-generation`。

## ⚠️ 最重要的一条：我们那套中文十块是 **Seedance** 的语法，不是 H3 的

2026-09-13 起我们把 `sd25-pe`（火山方舟官方 Seedance 2.5 skill）的十块中文模板当成"通用提示词标准"，并原样套到本地 H3 上（见 [[reference-seedance-official-prompt-skill]]、[[feedback-r2v-prompt-camera]]）。**H3 官方规范里根本没有【场景与环境】【主体与关系】【事件脚本】【镜头】【风格与光影】【声音】【保持一致】这些字段。** 我们一直在用错的语言跟这个模型说话。⇒ 这也解释了为什么"运镜写了不生效""站位距离怎么写都锁不住"——词表和结构都不匹配。

## 基础模式（T2VA / I2VA / FL2VA / L2VA）：一行指令 + 三个字段

```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

- 字段名、顺序、大小写**必须原样**，不得增删调换。
- **图生视频要在最前面加一行对齐指令**（这是"Part One = 指令"，然后空一行再进三字段）：
  - I2VA：`For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
  - FL2VA：`How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.`（N＝实际末镜号，S.SS＝精确两位小数的有效时长）
  - L2VA：只有末帧那一行。
- 四种模式的正文分工：T2VA 自建整条音视频时间线；I2VA 从首帧**向前发展**；FL2VA 写**首尾之间那条连续路径**；L2VA 反推一个合理起姿**收敛到末帧**。
- **官方 FL2VA 范例里明确要求把首尾帧"怎么接进时间轴"写出来**：`begins in the position and framing established by Picture 1` … `settles into the pose, spacing, and composition established by Picture 2 at the end of the shot`。⇒ 我们夹尾帧从来没写过这种句式，所以端点像、中段乱（见 [[reference-minimax-h3-local]] 尾帧那条）。
- **`overall_soundscape`（环境＋物理动作声＋非语言人声）与 `non_diegetic_music`（角色听不到的配乐）必须分成两块**，我们一直混在【声音】里。无配乐就写 `N/A`。

## ★片内多镜头：`[Shot N] At MM:SS.mmm, the camera cuts to ...`

**H3 原生支持在一次生成里切多个镜头**，切点精确到毫秒：`[Shot 1]` 不加时间码，后续每镜用**严格递增、且落在请求时长内**的切点时刻开头。官方给的切镜措辞白名单：`the camera cuts to` / `the shot cuts to` / `the shot transitions to` / `the shot changes to` / `the shot switches to`；**只有用户明确要求时**才用 cross-dissolve / fade / wipe。

**取舍规则原文口径**：一次切镜必须带来主体／空间／状态／视角／时间的**新信息**；如果只是改距离或轻微角度，**别切，用运镜**。

⇒ 这条直接动摇我们"一镜一拍 + 五镜分拍再 ffmpeg 拼"的方案。如果片内切镜可用，**跨段状态重置这个病根就不存在了**（一次生成、一个时间线）。

三条同参 A/B/C 实测（`E:\创作\仙戮\实验\豆包同参对跑_20260921\`，均为 1344×768／243帧／8步／4图max／ref2v LoRA／带音频，除 A 外都 `--skip-preflight`）：

| 条 | 提示词 | 产物 | flow_mean | p90 | body | 切点（请求 3.200／6.000／8.400） |
|---|---|---|---|---|---|---|
| A | 中文十块，**单镜连续不切** | `xianlu_doubaoAB.mp4` | **4.441** | 7.87 | 3.647 | 无 |
| B | 官方六段，4 镜 | `xianlu_officialAB.mp4` | 3.024 | 5.36 | 2.737 | 3.167／5.833／8.083 |
| C | 官方六段，4 镜，动作密度写回 | `xianlu_officialC.mp4` | 3.005 | 6.20 | 2.561 | 3.167／**6.000**／8.083 |
| D | 官方六段，**单镜连续不切** | `xianlu_officialD.mp4` | 3.592 | 6.41 | 3.101 | 无（`scene>0.15` 零检出） |

四张锚点、1344×768／243帧／8步／4图max／ref2v LoRA／带音频全同；`detailed_description` 词数 B 418／C 427／D 410（控住了）；耗时 960／961／1008／973 秒。对照四宫格 `D:\AIWorkflow\ComfyUI_H3\output\ABCD_grid.mp4`。

**机制成立**：H3 确实按毫秒时间码在**一次生成内**切镜（`[Shot N] At MM:SS.mmm`），误差 −0.033／0／−0.317 秒。⇒ 片内切镜可用，"跨段状态重置"这个病根有正规解法。C 的中镜切点比 B 更准（正落 6.000），但跳变更软（帧差 36.8 vs 44.6，`scene>0.20` 检不到、要靠逐帧帧差才认出）——那镜写的是"同机位改景别"，正撞在官方"只改距离就别切镜"那条取舍规则上，**是我违反规则，不是模型不执行**。

**运动量差距分解（2026-09-21 D 条给出，两个假设各对一半）**：
- **最干净的一步是 C→D 单变量**（同骨架同动作内容，只差切不切镜）：不切镜把 flow_mean 3.005→3.592（+19%）、body 2.561→3.101（+21%）。⇒ **片内切镜确实吃运动量，但只吃掉 A/C 差距 1.436 里的 0.587 ≈ 41%。**
- 剩下 0.849 ≈ 59% 落在 A vs D（两边都不切镜）。⇒ **"官方格式本身让画面更稳"是真的，且比切镜的影响更大。** ⚠️ 但这一步不是单变量：A 的中文十块与 D 沿用的 C 措辞本身也不同，那 59% 里混着措辞，不能全算到格式头上。
- **下一步（未跑）＝E 条**：官方骨架但把 `retention_analysis` 整段删掉或压到一行——它通篇讲"要保留什么"，是当前嫌疑最大的一项。
- **对做片子的含义**：切镜比我以为的便宜（只亏 0.59，后期变速补得回来），真正贵的是六段格式那 0.85。"要切镜就得放弃动劲"这个取舍比 09-21 早先的判断轻得多。

**★ 我此前给 B 条运动量低找的原因是错的，已收回**：原写"疑因＝六段写到 888 词、超出官方 `detailed_description` 350–500 词"。实拉：**888 是整个六段文件的词数，B 的 `detailed_description` 本身只有 418 词，早就在区间内**；C 是 427 词——**两条长度基本相同，C 根本不是"压词数"实验，只是换动作措辞**。结果 flow 3.024→3.005 纹丝不动（只有 p90 5.36→6.20 说明峰值回来了、平均没回来）。⇒ **官方格式压住运动量与词数无关。**

（**人审观感四条都还没判定，目前全是机器 completed。**）

## ⚠️ 时间码是 H3 专属，别搬到 Seedance（用户 2026-09-21 提醒、已查官方 skill 证实）

`sd25-pe`（官方 Seedance 2.5 提示词 skill，本机在项目级 `.qoder/skills/sd25-pe/SKILL.md`）明确禁止自造数字时间段：

- §76 参数分离：画幅／总时长／分辨率／帧率／声音开关**不写进 Prompt**；**"不得仅根据页面或接口的目标时长反向生成新的数字时间段"**。
- §526：仅由页面或 API 给出目标时长时，**用不带数字的"阶段"组织**；"不得为了对齐该参数而在 Prompt 中新建 `0-8 秒`、`8-18 秒` 等数字时间段"。
- §532：**只有用户已提供数字时间段、或明确要求按时间段控制**时才用**连续整数段**（格式 `0-5秒：<开始状态>；<主要事件>；结束时<可观察状态>`）。

⇒ 所以"火山云端写死时间反而不好用"不是玄学，是两家模板训练口径不同：H3 要毫秒切点，Seedance 要粗粒度无数字阶段（即便给数字也是整数段、且只在用户先写了之后）。
**推论（改我们那条"没有时间码概念是最大缺口"的判断）**：时间码**不该进上游分镜单**，它是模型专属输出。上游存"节拍顺序＋相对时长"，编译器按模型展开——H3 出 `At MM:SS.mmm`，Seedance 出不带数字的阶段。

## 运镜受控词表（Motion Type + Amplitude + Speed）

必须写成**当前镜头内的自然英文动作句**，不许在句尾堆标签。medium amplitude / normal speed 通常省略。

| 维度 | 可用表达 |
|---|---|
| 类型 | `Zoom In/Out`（焦距变、机身不动）／`Push In`／`Pull Out`（机身前后）／`Pan Left/Right`（原地水平转镜）／`Truck Left/Right`（机身水平平移）／`Tilt Up/Down`（原地垂直转镜）／`Pedestal Up/Down`（机身升降）／`Arc Shot`（绕主体弧形）／`Tracking Shot`（跟随移动主体）／`Static Shot`／`Shake Slightly`／`Shake Strongly`／`POV`／`Roll Clockwise/Counterclockwise` |
| 幅度 | `with small amplitude`／`with large amplitude` |
| 速度 | `at slow speed`／`at fast speed` |

范例：`The camera trucks right with large amplitude at fast speed, revealing the open doorway.`／`The camera holds a static shot as the runner exits the frame.`
⇒ **中文自造运镜词（"向画面右快速横移跟随"）不在这套词表里**，这很可能就是运镜不生效的直接原因。另注意：官方词表**承认器材无关的光学/机身动作分类**，与 Seedance 那条"运镜禁用器材名词"（[[feedback-r2v-prompt-camera]]）不冲突——两边都别写"用 35mm 镜头"这种，但 H3 这边要写 `Push In` 而不是中文描述。

## 全参考模式（Ref2VA）：六段，顺序锁死

```text
subject_definitions:
summary:
retention_analysis:
detailed_description:
overall_soundscape:
non_diegetic_music:
```

- **四类标签**：`<Subject N>`（从参考素材抽出来、可复用/可改的可见内容）、`<Picture N>`（当作某镜首帧/关键帧/末帧/构图锚的具体图）、`<Video N>`（提供剪辑源、续写起点或整片时间结构的参考视频）、`<Audio N>`（被复制或参考的音频）。**一旦分配，六段里含义必须始终一致**，不得在 `summary` 里引入新标签。
- **★关键规则（我们之前完全没照做）**：**如果一张图只是用来定义角色、场景、服装或风格，不要给它单独开 `<Picture N>` 条目——把图源写进对应的 `<Subject N>` 定义里。** 只有当这张图真的充当某一镜的首帧/关键帧/末帧/构图锚时才单开 `<Picture N>`。
  - 写法示例：`<Subject 2> is the winged woman, her face referenced from <Picture 2> and her outfit and weapon referenced from <Picture 3>: ...`
  - 分镜/故事板类的图要写清"映射到哪几镜、提供什么规划信息"：`<Picture 3> is a storyboard reference for [Shot 1] and [Shot 2], defining their viewpoint, subject placement, and shot order.`
- **`summary` 必须以方括号任务类型前缀开头**，多个类型用 ` + ` 连接、不重复：`[reference generation]`／`[keyframe completion]`（图当具体帧锚）／`[video editing]`（直接改现有源视频）／`[video continuation]`（从源视频往后接）／`[audio reuse]`（音频信号整体或部分照搬）／`[audio reference]`（只参考音色/风格/节奏/音效质感，不搬信号）。
  - ⚠️ 边界：**参考视频只提供运镜/切点/节奏时仍算 `reference generation`，不算 `video editing`/`continuation`**；图之间插值不算 video editing。
- **`retention_analysis` 每个标签一行，用固定英文标记**：可见内容用 `fully_preserved`／`partially_preserved`／`attribute_transfer`（特征转移到别的可辨主体）／`weak_reference`（只保留风格/类别/构图/氛围的大致相似）；音频用 `fully_copy`／`partially_copy`／`reference`／`weak_reference`。
  - ⇒ **这正是治"参考图把姿态、背景、杂物一起继承进来"的官方字段**。我们过去只能靠职责句里写"不采用其构图/背景"求模型自觉，这里是结构化声明。写"影调锚"就明确 `weak_reference - 只保留冷灰蓝调与高对比，构图/人物/山石形状不复用`。
  - 官方还提醒：**别把目标视频里新增的动作、背景、剧情事件当成"参考保真度损失"**——那是内容，不是漂移。
- **`detailed_description`**：正文英文，台词/歌词/画面可见文字保留原语言；风格用一两句英文**写在 `[Shot 1]` 之前**（基础模式是把风格塞在 `[Shot 1]` 之后——这是两模式唯一的结构差异之一）；生成任务的正文长度口径 **350–500 英文词**，多镜按信息量分配细节，单镜不自动等于可以写短。
- **说话人与台词**：`(S1)`/`(S2)` 稳定编号；台词写 `<d>[中文] …</d>`；跨切口的对白/被结尾截断的说话/跨镜连续音频用 `<scenetrans>`、`<cutoff>`。角色本人开口时同时保留视觉标签和说话人号。

## 输出规则与一处自相矛盾

- **总时长必须匹配请求时长，区间 4–15 秒**；描述里铺的时间也要对得上。
- 禁止：剧情梗概、没落地的引用代号、与请求时长不符的时间编排。
- **"避免 `cinematic` / `beautiful` 这类主观词"——但官方自己两个范例正文都写 `Live-action, cinematic`。** ⇒ 这条别教条执行；真正有用的推论是"把风格落到可观察特征上"（与我们已有的"具体特征 + 不得…"三件套一致，见 [[feedback-video-quality-standards]]）。

## How to apply

写 H3 提示词时：**先按目标模式选 base-en / ref-en 的骨架，逐字段填，不要拿中文十块改改就交**。中文十块继续当**上游 IR 与可审规格**用（用户 2026-09-21 定位，见 [[reference-seedance-official-prompt-skill]] 末段），下面挂编译器映射到各模型原生格式：`参考素材职责`→`subject_definitions`＋`retention_analysis`，`镜头`→受控运镜词表，`事件脚本`→`detailed_description` 的分镜时间线，`声音`→拆成 `overall_soundscape`＋`non_diegetic_music`。

⚠️ **中文闸与英文格式的冲突已解决，别再一律 `--skip-preflight`（2026-09-22 更新）**：`tools/check_preflight.py` 原先只编码中文十块（G7 要求【声音】等），英文提示词被整批 error 拦死，所以当时只能整条跳过预检。**现在闸按 `prompt_kind` 分派**：`image`（纯文生图，只查器材词/字面化词）、`video`（中文十块）、**`h3_i2va`（新增：校验官方首帧指令行＋三字段顺序＋正文从 `[Shot 1]` 起＋拦未挂素材的六段残留＋仍拦运镜器材词）**。⇒ 首帧路线的英文三字段可以**带着预检跑**，不需要绕闸；只有 ref2va 英文六段仍无专用口径（那条路目前仍要 skip，或补一个 `h3_ref2va` kind）。
**另两条实操口径（2026-09-22 太空战实测）**：① **只挂首帧＝基础模式（I2VA 指令行＋三字段），不要写 `subject_definitions`/`retention_analysis` 六段**——那是 Ref2VA 专属；② **每份独立视频的正文都从 `[Shot 1]` 开始**，`[Shot N] At MM:SS.mmm` 是"一次生成内的片内切镜"编号，**不是跨文件的镜号**（把生产镜号 T2–T6 写成 [Shot 2]–[Shot 6] 是误用）。
另：G3 会拿 `<图>.anchor.json` sidecar 里登记的**真名**核对提示词中的 `<Picture N> 是X`；**提示词里写描述性别称（"蒙眼者""展翅者"）会报"槽位冲突/机器判不了"**，必须用 sidecar 里那个名字（[[feedback-character-reference-image]]）。

相关：[[reference-minimax-h3-local]]、[[reference-seedance-official-prompt-skill]]、[[feedback-combat-shot-grammar]]、[[feedback-r2v-prompt-camera]]、[[feedback-review-production-prompts]]


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- 在 `MiniMax-AI/MiniMax-H3/skills/h3-prompt-writing/`（已镜像 `D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\`）
- 基础三字段 vs 全参考六段
- **★片内多镜 `[Shot N] At MM:SS.mmm`（毫秒切点，可能让"分镜再拼"退役）**
- 运镜受控词表写成句内英文
- ⚠️只挂首帧＝基础三字段

---

## ★ 2026-10-03 逐字重读官方三模板后的五条更正（旧会话按印象写的口径以此为准）

现读 `base-en.txt`／`ref-en.txt`／`SKILL.md`（机器每次重读对账，见 `E:\本地工作流规范手册\99_维护\check_official_contract.py`，
抽出 45 项固定值：运镜 12 行／幅度 2／速度 2／风格 token 7／切镜短语 5／任务类型 6／关系标记 4+4／§2.1 第一行 3 形）：

1. **§2.1 第一行是"按模式四形"，不是只有一句**：T2VA **无**对齐指令直接三字段；I2VA ＝ 上面那句
   （**我们库与 G7 闸与官方逐字一致**，不是缺口）；FL2VA／L2VA 两句另给逐字模板，
   **规则层从没转写过这两句**（10-03 已纯登记，未动 G7）。`N`＝实际末镜号，`S.SS`＝两位小数有效时长，
   且官方明写「**这句必须是最终提示词的第一行，其后空一行再写核心字段**」。
2. **`Throughout:` 不是官方写法**——三份官方文件里出现 **0 次**。它是本机 12 份 `prompts_H3官方骨架\*.txt`
   的自创惯例；官方只要求"每处细节对应可见或可闻的东西"（§4.1）。以前判据层把它挂在"官方骨架落点"名下＝误挂。
3. **运镜句的官方位置是 `[Shot 1]` 第二句**（风格＋构图之后、动作与 `(S1)` 之前），四条官方示例
   （base-en:175/189/203/217）一致；**"写在正文末尾"同样是本机惯例**。官方 §4.3 的硬性要求只有
   "写成镜内自然英文动作句、句尾不堆标签"。
4. **幅度与速度是按需写，不是必填**：§4.3 原文「Add amplitude and speed only when they are meaningful;
   **medium amplitude and normal speed are usually omitted**」，`ref-en` §5.1 也说「when they need to be expressed」。
   ⇒ 我们旧的"三件齐全"比官方严，10-03 起降为补充档（只在用户明确要求逐镜写全三件时才判）。
5. **质感层位置按模式两态**：基础四模式写在 `[Shot 1]` **之后**第一句（§4.1「At the beginning of `[Shot 1]`」＋
   §5.2 表「Written after `[Shot 1]`」）；全参考模式写在 `[Shot 1]` **之前**（一两句英文）。
   另外「首句写画幅／秒数／一镜到底」官方**没有**规定＝本机惯例。
6. 字数口径再钉一次：官方唯一规范性字数是 `detailed_description` **350–500 英文词**，且**只适用于全参考 generation**；
   官方四例正文实测 78–93 词、全参考示例 291 词；对白密集时优先说完整语音时间轴而非凑字数。
   ⇒ 库里曾写的"官方示例约 300–700 词"**没有官方出处**，已作废。

**通则**：引用"官方规定"时必须能指回三份模板里的**原句**；指不出原句的一律标〔本层自写·官方未规定〕。
撞名提醒：`engine\comfy\h3_i2v_fl2va_api.json` 名字带 fl2va，实为**首帧 I2VA** 通道。


## ★10-03 批 13 执行后的**现役口径**（写 H3 提示词前按这几条来）

1. **台词只用 `<d>[语言] 原句</d>`**——「出乱码就换引号重试」那句退路已删（用户裁「以官方为准」）。
   实现侧本来就是这样：`prompt_format.py` 的 `DLG_RE` 只认 `<d>`；英文双引号只用于**画面里真实可见的文字**
   （招牌／字幕／标签，官方 `base-en:146`），两者别混。
2. **重写段落用英文**（官方三处硬性：`ref-en:5`、`ref-en:217`、`SKILL.md:33`），保留原语言的只有三处：
   `<d>` 内台词／歌词、画面可见文字、官方点名的引用原文。**「中英混写放行」旧口径自 10-03 起作废**。
   ⚠ 机器侧**目前没有语言检查**（`prompt_lint`／`check_preflight`／`h3_rule_gate` 全无）⇒ 这条现在靠 `[人]`；
   建闸与否待裁。
3. 幅度／速度：官方是 `with small amplitude`／`with large amplitude`／`at slow speed`／`at fast speed`，
   **按需写**（中档与常速官方明示可省）；H3 侧照官方**英文形**写，中文形（「中幅度慢速 Push In」）
   只承认在存量稿里。
4. **存量事实**（别据此反推「英文已是现行做法」）：H3 侧 29 份提示词＝中文正文 17 份（09-27～09-30，
   最新是 `dance_woman_v1／v2／v3_手势舞`）＋英文正文 12 份（全部 09-27）。两批**都出过片**。
5. `<d>` 不是"会乱码"的标签：10-01 探针 `<d>[Japanese] 其は、約束された勝利の剣！</d>` 直接生效
   （124 帧＝5.18s，faster-whisper 逐字对上）。


## ★10-03 批 14：正文语言已有机器闸（写 H3 稿前必读这一条）

`G7` 现在判 **H3R23 正文语言**（10-03 批 14，用户裁「要建闸」）：**重写段落出现中日韩字符＝error**。
- 豁免只有官方那三处：`<d>` 内台词／歌词、**英文双引号内**的画面可见文字（招牌／字幕／标签，
  官方 `base-en:146`）、逐字首行与字段名行。
- **`overall_soundscape`／`non_diegetic_music`／`retention_analysis`／`summary` 全算重写段落**，
  中文一样拦；六段（ref2va）与骨架（i2va）两条分支都接。
- 只锁本地 H3 通道：云端中文十块／图片链／即梦的中文正文不吃这条。
- 判据二值、不带阈值。现成唯一的绕法是全关 `config.yaml` 的 `preflight: off`
  （代价：连 G7 其它判据一起关；台账 `bypassed` 会留字据）⇒ 别当常态。
- **未裁**：正文里的中文**角色专名**（薇拉／白玖璃这类）严格按官方就是违规，放宽需要项目白名单——
  在他裁之前，**新写的稿子角色名用拉丁形或纯描述形**（官方示例：`the young woman with long blonde hair`）。
- 对照表：`官方英文词表_中文对照_人审版.md`（桌面那份与手册 `00_读我` 那份同由
  `99_维护\build_official_lexicon_cn.py` 现读官方生成；照抄左列英文原形，中文列别写进稿子）。


## ★10-03 批 15：英译落盘时的四条口径（那三件他一条一问裁完）

1. **中文角色专名＝算违规（严格）**，不加项目白名单、不改闸 ⇒ 名字取**拉丁形**（`Wu-junyi`／`Wei-la`／
   `Bai-jiuli`）或纯描述形（官方示例本就不写名字：`the young woman with long blonde hair`）。
2. **武器一律 `long staff`／`the shaft`／`staff head`**，绝不写 `spear`／`gun`／`rifle`／`pistol`／`bullet`——
   这是接他自己那条 A 线"画面区零「枪」字⇒改长杆"的裁定（本机实测「枪」会被渲成火器）。
3. **否定清单改正面写法**，但**范围只限那两条清单**（`不得卡通化…`、`画面不得出现任何文字…`）；
   句内那些「不躲不退／不跳切」仍照原语义直译——**不趁机把 C49 那整堆未裁的否定式一次清完**。
   正面范例：`Rendering stays photoreal: skin with subsurface scattering, fabric with a visible weave,
   metal with worn specular falloff, highlights rolling off without clipping to white.`
4. **不加 `[Shot N] At MM:SS.mmm` 切点**——官方 §4.2 那句明写「Do not add a timestamp to the **first** shot」，
   该格式是给**第 2 镜起**的切点用的；H3 侧这 20 份真源实测**全是单镜**，加了就是凭空造切镜（改片子不是改措辞）。
   镜内节拍时钟写成 `0.0-1.2s:`（只删中文字），属〔本层自写·官方未规定〕；
   "官方毫秒切点 vs 本机区间写法"仍是**未裁**项（速查表已登记），别借翻译替它做决定。
5. **幅度／速度不许冒第三档**：官方只有 `with small/large amplitude`、`at slow/fast speed`，
   且「medium amplitude and normal speed are usually omitted」⇒ 中文「中幅度／中速」**直接省略不写**，
   别译成 `with medium amplitude`（那是替厂商造值）。


**批 15 补（10-03）**：① 角色名一律**拉丁形**（`Wu-junyi`／`Wei-la`／`Bai-jiuli`）——中文专名算违规，不加白名单。
② 武器写 **`long staff`**（接 A 线「长杆」那套），绝不写 `spear`／`gun`／`rifle`。
③ **单镜正文不要加 `[Shot N] At MM:SS.mmm`**：官方那句只管第 2 镜起（"Do not add a timestamp to the **first** shot"），
本机 beat 写 `0.0-1.2s:`（属本机写法）。④ 20 份 H3 真源正文已英译落盘（**未重跑**，英文形在本机效果未经实测）。
⑤ 已知代价：H3 侧**中文词形法条词表 25/40 张命中归零**（`FIGHT_V`／`LIGHT_NOUN`／`SKIN_SUBJECT`／`DOMAIN_WORDS`／
`prompt_lint.NEG`／`RENDER_TOXIC` 等）——这些守卫暂时看不见东西，待裁-16 未决。
