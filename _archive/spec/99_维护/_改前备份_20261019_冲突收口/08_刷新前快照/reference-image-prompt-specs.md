---
name: image-prompt-official-specs
description: 出图提示词规范在哪：🔴BFL 整套 prompting 文档绑 **FLUX.2／FLUX 3 Image**（顺序五段式／无负向词／photoreal 要显式要 pores／hex 色值），**本机 flux1-dev 官方零规范**（README 只说 minimal inference code）；FLUX.1 实务口径＝T5 512 token、40–50 词甜点；Seedream 官方指南正文 JS 渲染→**本机有 09-28 全文快照**（反对逗号堆词、简洁优于堆砌、画面不再泛白）；★机制层 CLIP-L 只读前 77 token／T5 不截⇒前约 70 词权重双份；🔴本地图片通道无成文写法规范（拟立，待点头）
metadata:
  type: reference
---

# 出图模型的提示词规范在哪里（10-04 现查）

问"出图模型有没有规范的提示词"时，**三条通道要分开答**，别拿一条的有无去推另一条
（[[feedback-per-channel-rules]]）。

## 一、本地 FLUX（BFL）——官方有，但很薄

**[FLUX Prompting Guide](https://docs.bfl.ml/guides/prompting_summary)**（`docs.bfl.ml/guides/prompting_summary`）。
10-04 现读，正文只给到这几条：

1. 描述要覆盖 **subject、setting、style、lighting、composition** 五要素（原文
   "Describe the image you want: the subject, setting, style, lighting, and composition"）。
2. 整句自然语言，**不是逗号 tag 堆叠**。
3. 挂参考图时**按位置称呼**（`image 1`／`image 2`），需要指定落在哪儿时**给 bounding box**；
   结构化布局用「**global caption ＋ bbox 表**」这种写法。
4. 画面内文字要 **legible typography**。
5. 官方明确说可以**在没有负向提示词的情况下工作**（"working without negative prompts"）。

⚠ **官方没写的部分要如实标"未核到"**：长度上限、tag vs 句的量化建议、avoid 清单、
guidance／步数口径——这些都只以**子页标题**出现，正文不在这一页，我没逐页核。
下次要用先补核，别把社区帖当官方（搜索结果里的 reddit／skywork／laprompt 那些都是二手）。

## 二、云端图片（Seedream／即梦）——官方有全文，且我们已经抄进规则层

- 官方页：**[Seedream 4.0-5.0 提示词指南](https://www.volcengine.com/docs/ark/seedream-4-0-5-0-prompt-guide)**
  （另有 [图片生成教程](https://www.volcengine.com/docs/ark/seedream-4-0-5-0)、
  [提示词工程](https://www.volcengine.com/docs/ark/prompt-engineering)）。
- 🔴 **取正文的坑**：这页（含 `docs.byteplus.com` 镜像）是 **JS 渲染**，`WebFetch` 只会拿到路由配置与埋点脚本，
  报"未收录正文"——**不是页面没内容，是取法不对**。要现取就走内置浏览器（[[reference-user-browser-shopping]]）。
- **已有快照**：09-28 抓过全文，落 `C:\Temp\jmcanvas\seedream_prompt_guide.md`（4,267 字；
  同目录还有 `seedance25_prompt_guide.md`，21,610 字）。⚠ 在 `C:\Temp` 下，**会被清**，要用先确认还在。
- **已成文的唯一真源**：`E:\本地工作流规范手册\03_使用规范与关口流程\即梦云端_工作流规则.md`
  §二（官方出处三条，逐条可查）＋ §四「图片侧写法（官方口径）」P 条 ＋ §四-补一「塑料感词表」
  （10-01 同档 A/B 实测）＋ §六「与本机现行写法的冲突点」。⇒ **云端图片侧不缺规范，别重复造。**

## 三、机制层：本机 ComfyUI 源码里可查，比官方更有用（10-04 现读）

判"某个词为什么不起作用"时，先看这一层，别直接归因"模型不行"：

- **CLIP-L 分支只吃前 77 个 token**：`ComfyUI/comfy/sd1_clip.py` 里 `SDTokenizer.__init__(... max_length=77 ...)`，
  截断实施在同文件 tokenize 分组处（`if len(t_group) + len(batch) > self.max_length - has_end_token`）。
- **FLUX 的 T5-XXL 分支不截**：`ComfyUI/comfy/text_encoders/flux.py` 的 `T5XXLTokenizer` 传
  `max_length=99999999, min_length=256`。
- **同一段文字两个编码器都吃**（`FluxTokenizer.tokenize_with_weights` 各调一次）。
  ⇒ **开头约 70 个词被读两遍，超出部分只有 T5 读到**——这就是 [[feedback-prompt-iteration-priors]]
  「句位定风险」的机制解释，也给出一个**尚未验的可检验假设**：
  10-04 那轮去饱和句是加在约 100 词提示词的**末尾**，它几乎无效（饱和只降 1.5–6 点）——
  **可能不是词不对，是位置太靠后**。下一轮只动句位、不动词，就能把两种解释分开。
- 我们这份 `engine/comfy/draft_flux_api.json` **没有 negative 节点**（第二个 `CLIPTextEncode` 是空串，
  且 `cfg=1.0`）⇒ 与官方"不用负向提示词"一致；**别再往本地 FLUX 提示词里写"不要 X"**
  （同 [[reference-h3-prompt-rules]] 里 H3 侧"禁令即在点名"的判法，但**结论各自记各通道的账**）。
- ⚠ 行号与常量会随 ComfyUI 升级漂移（本机 0.30.2），引用前现读一次，别当永久事实。

## 四、🔴 覆盖缺口：本地图片通道没有成文的提示词写法规范

`图片链_工作流规则.md` 九节全是**工具契约**（模板清单／占位符／掩膜语义／尺寸口径／LoRA／
实测数字／判据接口／做不到／已知缺口），**没有一节讲提示词怎么写**。
10-04 那三轮光影单变量实验就是在这个空白里摸的（结论见 [[reference-color-lighting-standards]]）。

**拟办（未动笔）**：立 `图片链_提示词规范.md`，与 H3 那份方案对等，三态分开标——
〔官方〕BFL 与 Seedream 原文引用（官方明写的赢，含"不用负向提示词"这条，见 [[feedback-collaboration-style]] §36）｜
〔机制〕77 token 这类带出处的｜〔本层自写·实测〕发光体＋雾是明度杠杆、曝光词只抬亮面、
档数语言不生效、发光体会把主体挤掉、脸必须完整受光、无锚锁不住题材。
**新建规则层条目属改规则，按元规则 M1 要他点头，我没擅自建。**

## 五、★04:40 深挖核实：BFL 那套文档**绑的是 FLUX.2／FLUX 3，不是本机这台**

逐页读了「适用模型」自述（这是最关键的一条纠偏——**上一版说"官方只有薄薄五条"不准确**）：

| BFL 文档页 | 页面自述适用模型 | 给了什么 |
|---|---|---|
| `prompting_summary` | 总览 | 五要素 `subject, setting, style, lighting, composition`；参考图按 `image 1` 称呼＋bbox；global caption＋bbox 表；`legible typography`；**明说不用负向词** |
| `prompting_unified_basics` | **FLUX 3 / FLUX 3 Image** | 顺序 `medium and style first → subjects and where they sit → light, color, background`；框架 `[Subject],[location],[style],[camera settings],[lighting],[colors],[effect]`；**用句子写关系（含"光从哪来"）**；`A short prompt works`／`Most images don't need a caption this long`／`Write more only for the details you want to control`；判据 **`Every phrase names something you could point to in the frame`**；`There is no negative_prompt`；bbox **放最后**；`There is no single correct format` |
| `usecases_t2i_photorealistic` | **FLUX.2** | 以「此刻实拍」心态写；指定 `lens, lighting, framing, texture`；温度词 `Warm golden tones from late-day sunlight`；相机串 `90mm f/2.8 macro lens, ISO 100, shutter 1/250`；⚠ **必须显式要表面缺陷** `real texture (pores, wrinkles, fabric wear, imperfections)` |
| `usecases_t2i_hex_color_prompting` | **FLUX.2** | 色值紧贴标签**绑到具体物件**（`an apple in color #0047AB…`）；`Check the rendered color when accuracy matters`；含糊引用不稳 |
| `prompting_unified_technical` | **FLUX 3 Image** | 15 档比例 `21:9`～`9:21` 或 `auto`；分辨率 `768sq/1k/2k/4k`；**不讲步数/guidance/seed/token/TE** |

1. 🔴 **本机这台是 `flux1-dev-fp8`——FLUX.1 时代 BFL 没有发布过字段级提示词规范**：
   [官方推理仓 README](https://github.com/black-forest-labs/flux) 自述只含 `minimal inference code`，
   格式／负向／CFG／步数／尺寸／token 边界**一概没写**。⇒ 上面那套细则**属另一代模型**，
   引用时必须标〔官方·FLUX.2/3，不含本机 flux1-dev〕，**不许整份照搬**（R2-16 第一态的适用面问题）。
2. **代际差异有实据**：FLUX.1 用 CLIP-L＋T5-XXL 双 TE；FLUX.2 换成 **Mistral／Qwen VLM 做 TE**，
   并新增 JSON prompting 与 hex 控色——**这两样 FLUX.1 没有**。本机
   `comfy/text_encoders/flux.py` 里 `t5xxl`(14 行) 与 `mistral3_24b`(86)／`qwen3_4b`(146/151) **并存＝两套模型的代码，不是一台模型的两个头**。
3. 〔外部实务·非 BFL 官方〕FLUX.1：**dev 512 token／schnell 256**；**40–50 词是甜点**，过长被内部压缩；
   schnell 1–4 步、dev 20–50 步、guidance 可调（例 3.5）；架构层拒绝负向词。
4. **Seedream 官方正文本机有全文快照**（`C:\Temp\jmcanvas\seedream_prompt_guide.md`，09-28 抓），
   官方原话要点：自然语言写**主体＋行为＋环境**，美学元素补**风格／色彩／光影／构图**；
   **明确反对逗号堆词**（给了「示例 vs 避免」对照）；写明**图像用途**；风格用精准词或参考图；
   画面文字放双引号；编辑指令**避免指代模糊的代词**＋写「保持××不变」；
   ⚠ 4.x 一代官方口径：**简洁精确优于堆叠华丽词**，且**「画面不再泛白」**——
   泛白这类老毛病在新版是模型侧已改的，别再靠堆词去治。
5. **冲突登记（不是矛盾）**：BFL 说「写短别堆长句」，我们靠**加句子**（发光体＋雾）才抬起明度——
   两者一致，判据就是那句 `Every phrase names something you could point to in the frame`：
   **加的是可指出的物理内容，不是形容词堆叠**。我们失败的正是后一类（`high-key`、`desaturated`）。
6. 想要 hex 精确控色／JSON 那套就得升 FLUX.2 系权重（大下载，成本另议）——**不建议**，
   本地控色已有 ΔE／示波器族这条自研路。

详版（带全部出处与行号）：`E:\创作\_待审文档\出图提示词规范_调研核实_20261004.md`

