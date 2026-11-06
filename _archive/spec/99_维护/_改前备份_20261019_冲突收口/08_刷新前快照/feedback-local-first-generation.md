---
name: local-first-generation
description: 出图与出视频默认先走本地管线（ComfyUI FLUX/SDXL、本地 H3），云端只作补充——用户 2026-09-16 明确定的长期策略；⚠️写实人像/定妆优先本地 SDXL 而非 FLUX（FLUX-dev 偏卡通）
metadata:
  type: feedback
---

# 出图 / 出视频默认先走本地

接到任何出图或出视频任务，**先问"本地能不能做"**，本地能做就不要默认走云端。
云端通道（ARK/Seedream、可灵、即梦、海螺等）降为一等补充。

**Why:**
- **可控**：本地不受账户余额、SSO 过期、平台限流、内容审核拦阻影响。2026-09-13 和 09-16 两次 ARK 欠费卡住出图，就是这一类不可控。
- **不计次**：云端按张计费（Seedream 5.0 pro ≈ ¥1/张 + 参考图加收），本地只耗电和时间。批量铺训练集时这个差别很大。
- **分布对齐**：LoRA 将来在本地 FLUX/SDXL 上用，用本地模型生成的图训练，训练分布＝使用分布；混用云端会夹一层风格差。这是用户 2026-09-16 明确提出本地优先的直接触发点。
- **底线**：承重墙放本地可控手段是用户一贯原则（另见 [[low-expectation-external-capability]]）。

**How to apply:**
- 本地出图＝ComfyUI（D:\AIWorkflow\ComfyUI_H3，统一 8189 实例；引擎八工作流 FLUX/SDXL 出图 + H3 出视频）。本地身份迁移手段＝**FLUX + Redux**（`D:\Models\ComfyUI\style_models\flux1-redux-dev.safetensors`），能力待验。
- 云端仍该用的场合：① 本地缺该能力的模型（如 Seedream 的图像编辑去除物件、参考图编辑）② 需要一次性极致质量的定稿图 ③ 本地跑不动的规格。
- **不要**因为"云端更省事"就绕过本地；也**不要**反过来拒绝云端——是"先本地"，不是"只用本地"。
- 训练集/素材批量生产优先本地；训练前的 GPU 占用要清（ComfyUI、Godot 先关，见 [[reference-lora-training-infrastructure]]）。

## ⚠️ 但"本地"≠"本地 FLUX"——写实人像/定妆出图 FLUX 偏卡通（2026-09-20 复现+定位）

`flux1-dev-fp8` 底模先天是数字绘画/半 CG 美学，人脸尤其明显（《烬骨辞》定妆、早前脸A 都撞同一病，用户两次说"FLUX 出的图偏卡通"）。**实测细节量（拉普拉斯方差）：SDXL base 出图 270 vs FLUX 150 → 本地要写实，SDXL base 的先验比 FLUX 强。** 所以"先走本地"落地时要再分一层：**写实人像/定妆优先本地 SDXL，不是无脑上本地 FLUX。**

三条定位（不全是参数）：① **底模先天（最大、非旋钮）**：FLUX-dev 不是写实模型，只能靠写实 LoRA 或写实底模救；② **提示词自伤（算参数、易改）**：写"电影级 **CG** 写实 / 3D 渲染"里的"CG/render/3D/digital art"会把 FLUX 推向 CG 画风——要写实就删这些词，换"真实摄影/胶片/皮肤毛孔/85mm/RAW"；③ fp8 抹平皮肤微纹理，且只挂 `RealSkin`（管皮肤质感）不够，要挂管五官结构的写实人脸 LoRA。

本地写实通道现状（2026-09-20 查）：checkpoints **只有 `sd_xl_base_1.0`（无 RealVisXL 等纯写实底模）**；FLUX 侧有 `East_Face_Flux`(写实东方脸)/`RealSkin_Flux`；SDXL 侧有 `daxiushan_sdxl`(大秀山·写实人像)/`国风_明制SDXL_v1`/`SDXL清冷唐宋汉服`（SDXL 吃 tag＋负面词，`draft_sdxl_api.json` 自带负面）。

## ★★ 定妆级"好看的脸"本地两条路都做不到（2026-09-21 实测坐实）→ 直接走即梦

《烬骨辞》第 0 批定妆：FLUX（East_Face+RealSkin、删 CG 词、摄影语汇）和 SDXL（base+国风 LoRA）**两条本地路线各出 3 候选，用户一句"都好丑"全否**。→ **修正上面那条通道优先级：定妆（要惊艳人脸）不是"SDXL>FLUX"的量级差，是本地两个底模的美学先验都不够**。写实细节 SDXL 略胜，但"好看/有角色感"这一关本地过不了，跟脸A 那轮（本地 Redux 封顶 0.42、做不出选定脸）是同一堵墙。

**定妆的正确通道＝即梦/Seedream**（无音、对门定妆都是它出的，古风写实人脸先验强一档）。`daxiushan_sdxl` 元数据看不出是风格还是特定人脸，**有让两主角撞同脸的风险，慎当共享人像 LoRA 用**。

## ★ 定妆底模选型（2026-09-21 查证）——杠杆是"换特化底模"，不是调参数

**根因（讲透给用户，他"不甘心"时别只回"认命花钱"）**：「好看/惊艳」是模型先验（训练数据 + 人脸美学 RLHF）长在权重里的属性，**prompt / LoRA / CFG 只能在先验已覆盖的分布内采样，抬不了天花板**；看着"丑"往往是五官协调度崩（不是细节不够——细节 LoRA 能补，协调度补不了）。**要改只能换底模＝换先验，继续在现有 FLUX/SDXL 上堆 LoRA/改词是空转。**

**东方/古风定妆别照西方写实榜选**：2026 写实 SDXL 榜（Juggernaut XL #1 / RealVisXL #2 / CyberRealistic / EpiCRealism / Dreamshaper）比的全是光照氛围与皮肤质感、**脸都是西方面孔**，对东方定妆是错的轴；榜里唯一亚洲向是 DucHaiten Realistic（还偏日韩）。真正对口＝中文社区特化底模：
- **majicMIX realistic 麦橘写实**（亚洲写实人像标杆）＝本地首选。⚠️**2026-09-21 实测：HF `aasda111/SD_model_upload` 上那个"v7"其实是 SD1.5 版**（2.13GB，safetensors 头是 `cond_stage_model`+`first_stage_model`，不是 SDXL 的 `conditioner.embedders`+`vae`）；**SDXL 版主要在 Liblib（要登录、curl 拉不动）**。SD1.5 完整 ckpt 自带 CLIP+VAE、`CheckpointLoaderSimple` 直接加载、出图按 512×768（分辨率天花板低、后面上超分），但**已装的 `国风_明制SDXL_v1` 是 SDXL LoRA 挂不到 SD1.5 上**。**下 checkpoint 前先拉几 MB 看 safetensors 头验架构，别信文件名/仓库标题。**
- **且漫CN「国风|汉服|写实SDXL」**（古风+汉服烘进底模，Liblib 需登录）＝次选。

**How to apply（定妆/要好看的人脸时）**：先本地试 1 版即可；判"丑/卡通"后，**用户不甘心直接花钱、倾向先把本地特化底模这条试尽**（2026-09-21 明确）→ 下一步是**下 majicMIX 这类特化底模重出**（换先验），不是在现有 FLUX/SDXL 上死磕参数；特化底模仍不到位，才实锤先验差、上即梦（8 分/张，先出 4 张试水）。批量首帧/场景锚（锁已定妆脸的 i2i 派生）另说。

### ★★★ 特化写实底模的天花板：给得了"真人感"，给不了"偶像感"（2026-09-21 实测）

下 majicMIX（SD1.5）重出 6 张定妆，用户判**"稍微好点，但没有那种偶像感"**——确实比 FLUX/SDXL 强（坐实"换特化底模＝换先验"这招有效），但仍过不了他这一关。**机制**：写实模型（majicMIX 这类）优化方向是"真实自然的人"，而"偶像感"＝精修美颜，是**相反的美学轴**；写实模型给得了漂亮真人、给不了精修 idol。加 `beauty photoshoot / idol-grade / magazine cover` 这类词能推近一点（另跑了一版素版 vs 偶像版对比），但有天花板。**→ 定妆要"偶像级精修脸"，本地写实模型基本到顶，这就是即梦/Seedream 的地盘（字节美颜先验）。** 附带设计要点：短剧主角要**"明星脸演落魄"——脸锁顶配好看、处境惨交给服饰和光，两件事分开锁**（我一开始把囚徒写成憔悴素净，把脸压下去了）。

### 最终定妆通道（2026-09-21）：火山 Seedream，不是即梦；本地超分被否

majicMIX 素版 / 偶像版 / 官方推荐词式 / 社区加权美颜 tag（`beautiful detailed face:1.3` 等）**四档提示词全试过**：官方/惊艳加权"稍微好点"，但用户最终判**"质感差点点、脸其实能看"**——即 SD1.5 的 512 分辨率纹理天花板（脸对了、皮/细节不够）。**用户否掉"本地出图＋超分补质感"（原话"超分成本反而划不来"），定妆出图直接走火山 ARK Seedream 5.0 pro**（即梦只剩 50 分、8 分/张不够铺，故弃即梦用火山按量）。→ **定妆/要"惊艳偶像级"人脸的出图，本地写实模型（含特化 majicMIX）到顶，走火山 Seedream；别指望本地超分救质感。**

相关：[[feedback-collaboration-style]]、[[reference-localai-console-engine]]、[[reference-lora-training-infrastructure]]、[[reference-local-face-identity-transfer]]、[[project-jinguci-shortdrama]]、[[reference-ark-account]]

## ★ 题材要分通道：硬表面太空战舰 **FLUX 赢 SDXL**，跟写实人像那条结论相反（2026-09-23 实测）

上面"写实人像优先 SDXL（270 vs 150）"那条**只管人像**。同一把尺子量太空战舰（统一到 1344 观看宽度的拉普拉斯方差）：SDXL 改词后 **352–482**，FLUX **875 / 1066 / 1057**，参照物可灵图 1719、战舰设定表 1946。⇒ **硬表面/机械/科幻大船走 FLUX，别用 SDXL base**；SDXL 在这条路上还更脆（见下两个词级跑偏）。

**SDXL base 的海事先验陷阱（可复现，下次直接照改）**：提示词里出现 `warship / armour planes / bridge superstructure / turret bases / battle-worn gunmetal / oxidised plating / chipped paint / soot streaks` → **三张全出"二战航母浮在海面上"**（桅楼、飞行甲板、防波堤、拖船、云天），而且亮度 87–114 完全不近黑。换成太空词即修好：`warship→starship`、`armour planes→hull plating panels`、`bridge superstructure→command spire`、`turret bases→weapon emplacements`、`oxidised/chipped paint→scorch marks and abrasion`，并前置 `deep outer space / starfield on every side / pure vacuum`。
⚠️ 另一个词级跑偏：`recessed craft bays with lit interiors` 被 SDXL 读成**内舱走廊**。写"机库/舱室内有灯光"这类词要防它钻进船里。

**判"够不够大片"要拆四件事，别笼统说"质感"**：① 细节密度（可量，见上）② **光影有没有方向性**——逆光＋自发光主导会把起伏抹成剪影，再密的结构也读不出金属（可灵那张 1719 就栽在这）③ **结构尺度层级**——真实硬表面有"大平面→分块→细部→微细节"3–4 级台阶，AI 常只在一个尺度上重复，于是"糊成一团"而不是"巨大"④ 边缘与接触阴影（超分后熔化＝塑料感）。**⚠️拉普拉斯奖励高频，超分锐化能把这个数刷上去——别把曲线读成"上超分就行"，补高频不等于补设计。**

**同批附带**：FLUX 一张右下角漏出数字 `1075` ⇒ "no text" 在 FLUX 上只是减弱、不是消除。

### ★★ FLUX 的"太空主力舰"先验＝星战帝国级，**纯文字压不回来**（2026-09-23 四方向实测）

用户判"战舰设计跟电影里太像"。为拿原创剪影，写了四条互不相同的设计语汇各出一张（A 重工业粗野／B 东方青铜礼器比例／C 单体几何方尖碑／D 硬航天工程桁架），**四张全部仍然帝国级**：楔形舰体＋顶部塔楼舰桥。其中 A 和 B 我明写了 `There is no tower and no bridge superstructure` / `No tower, no mast, no saucer`，模型照样建塔；C 要"绝对无窗无greeble的光滑多面体"，出来是带表面细节的箭头舰。

**Why:** 扩散先验里 "capital starship" 这个语义槽被好莱坞剧照占满，文字只能在槽内采样，改不了槽；**否定句不仅无效，还可能把被否的概念当提示植入**（写 `no bridge` 里的 bridge 本身就是海军/星战舰桥词，`command spire` 更是直接召唤塔楼——我上一版就是这么自伤的）。这跟"可灵守得住禁止句、H3 守不住"是**另一类问题**：那是对行为指令的服从度，这是对**形状先验**的服从度，两家模型都压不动。

**How to apply:** 要原创剪影就**别在文字上继续加码**，把剪影所有权从模型手里拿回来＝**自定轮廓 → ControlNet → 模型只补表面**。本机资产已齐、零成本可走：`D:\Models\ComfyUI\controlnet\FLUX.1-dev-ControlNet-Union-Pro-fp8.safetensors` ＋ `custom_nodes\comfyui_controlnet_aux`（canny/depth/tile 预处理器）＋ FLUX 底模与 clip_vision 都在。**先画剪影（纯几何、不烧 GPU）交用户圈定，再接 ControlNet 出图**，别先建链路再找形状。写剪影类提示词时**避开 `bridge / tower / spire / superstructure / saucer / wedge` 这些自带模板的词**，连否定式都不要用。

### ★ SDXL 中文提示词陷阱（2026-09-23 实测）

SDXL base 对中文提示词理解极差，**出结构锚点必须用英文**：
- `硬表面科幻战舰编队...` → 出**机场停机坪上的民航客机**（把 warship 读成 airplane）
- `星系级战星表面特写...` → 出**工程蓝图线稿**（把 surface closeup 读成 technical drawing）

**Why:** SDXL 的 CLIP 文本编码器主要训练语料是英文，中文 token 映射到语义空间时严重失真，尤其专业术语（战舰/装甲/焊接缝）完全没有对应先验。

**How to apply:** ① SDXL 出图一律用英文提示词；② 需要中文描述时先翻译成英文再喂给 SDXL；③ FLUX 的 CLIP 对中文支持较好，中文提示词可用（但硬表面题材 FLUX 先验更强，见上条）。



## ★★★ 首帧图一律走云端，不走本地（2026-09-24 用户明确，覆盖上面"先本地"在首帧这一环）

用户原话：**"以后首帧图都走云端，不用本地。"**

**适用范围**：所有**进片的视频首帧／关键帧**（含剪影空景、spectacle 首帧、身份镜首帧）。
**不适用范围**：视频本体仍走本地 H3（他没改这条）；训练集批量铺图、LoRA 数据、纯对照实验小样仍可本地（那些不是"首帧"）。

**Why（推断，他没说理由）**：① 本地 FLUX 出图带 CG／数字绘画先验，与"真人实景"目标画风有系统性差距，而首帧的质感＝整段视频质感的上限（H3 只忠实执行首帧）；② 云端 Seedream 的古风写实先验更强，一张几毛钱、30 秒，比本地挑 3 张再判废便宜；③ 上面几条实测已经反复把定妆／惊艳脸推向火山 Seedream，首帧是同一堵墙。

**How to apply:**
- 默认通道＝**火山 ARK Seedream**（`arkcli +gen --modality image`，已开通、按量计费稳）；即梦只在他点名时用（积分少，8 分/张不够铺）。
- 身份镜仍按已坐实的正解：**豆包/Seedream 参考图裁 9:16 去水印直接当首帧**（本机 Redux 对指定真人脸 sim 0.03–0.16 做不出），这本来就是云端产物，与新规矩一致。
- 首帧出图**手填提示词、关 LLM 润色**（`--optimize-prompt` 不要开），保可控对照。
- 别再默认起 `draft_flux_api.json` 出首帧；本地 FLUX 退回它擅长的位置（硬表面/战舰设定锚、造型探索），见上面"题材要分通道"那条。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- 2026-09-16 定：默认先问本地能否做（可控/不计次/分布对齐）
- **★★2026-09-24 覆盖：进片的视频首帧一律走云端（火山 Seedream），别再用本地 FLUX 出首帧
- 视频本体仍本地 H3**
- 写实人像本地 FLUX 偏卡通、定妆要"偶像感"本地到顶→火山 Seedream
