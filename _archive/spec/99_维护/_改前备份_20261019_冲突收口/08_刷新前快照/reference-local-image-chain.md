---
name: local-image-chain-boundary
description: 本机图片生成链（engine/comfy）能做什么、缺什么——★2026-09-28 补齐 i2i/inpaint/outpaint 三个模板并**接进引擎**（零下载，四条 yaml 实跑可用）；做不到的：深度锁几何、同场景多机位一致、严格三视图、锁人物身份。含 denoise 档位、掩膜语义、VAE 往返地板等硬数字oise 档位、掩膜语义、VAE 往返地板等硬数字
metadata:
  type: reference
---

# 本机图片链能力边界（`D:\AIWorkflow\engine\comfy\`）

## ★2026-09-28 更正：不是「没有」，是「没写模板」

上一版这条写的是「**没有 img2img / inpaint / outpaint**」——只对了一半。真相是：
**模板**从来没写过（`engine/comfy/` 里只有文生图那几张），而 ComfyUI 侧的核心节点
（`VAEEncode` / `VAEEncodeForInpaint` / `SetLatentNoiseMask` / `ImagePadForOutpaint` / `InpaintModelConditioning`）
和深度预处理器权重（`ckpts/depth-anything/Depth-Anything-V2-Large`、`yzd-v/DWPose`）**本地早就装好了**。
补模板即可，**零下载**。

## 现成工作流
- 纯文生图：`draft_flux_api.json` / `draft_sdxl_api.json` / `draft_sd15_api.json`
- 文生图 + Redux 参考图：`flux_redux_ref_api.json`（`__REF__`）
- 文生图 + ControlNet：`flux_controlnet_lineart_api.json`（Canny，`__CTRL_IMAGE__`/`__CTRL_STRENGTH__`，**已验证可锁剪影**）／`flux_cn_redux_api.json`
- **新增（2026-09-28 实跑验证）**：
  - `flux_i2i_api.json` 图生图（`__DENOISE__`）
  - `flux_inpaint_api.json` 局部重绘（**掩膜＝输入 PNG 的 alpha 通道，透明处＝待重画区**）
  - `flux_outpaint_api.json` 扩画布（`__PAD_L__/__PAD_T__/__PAD_R__/__PAD_B__`/`__FEATHER__`）
  - `flux_controlnet_depth_api.json` 深度 ControlNet（**跑得通但出不了可用图，见下**）
- **已接进引擎（同日）**：`engine/workflows/` 下 `image_i2i.yaml` / `image_inpaint.yaml` / `image_outpaint.yaml` / `image_depth.yaml`，各＝`gate 关口`（`prompt_kind: image`＋`auto_gates [G5,G7,G11]`＋`characters: none`）＋`control 步`，产物落批次夹同名 stage 子目录。
  `tasks.py` 的 `build_graph_control` 补了 `__GUIDANCE__/__DENOISE__/__GROW__/__PAD_L,T,R,B__/__FEATHER__/__DEPTH_RES__`（只加键，既有模板零影响；`walk` 只替换"整值恰好等于占位符"的字符串），并新增 `_pnum/_pint` —— **取数值参数别用 `or` 吃默认**（`pad_l=0` 会被 `or` 变成默认值）。
  ⚠️ 坑：`__GUIDANCE__` 原先不在 control 的 rep 里（既有 lineart 模板把 guidance 写死 3.5 所以没暴露），不补会报 `Failed to convert an input value to a FLOAT value: guidance`。
  实测耗时：i2i 33s / inpaint 18s / outpaint 24s / depth 42s（服务预热后）；`pytest tests/ -q` **108 passed**。
  命令：`python run.py image_i2i --project <项目> --output-root <含项目名的根> --set src_image=<图> --set prompt=… --set denoise=0.3`
- 放大/精修：`draft_upscale_api.json`、`refine_usdu_api.json`；换脸向：`sdxl_faceid_ref_api.json`
- 驱动：`python D:\AIWorkflow\tools\comfy_run.py --workflow <json> --set KEY=VALUE … --ref <图> --n 3 --out <目录> --prefix p`
  （`--set` 映射到 `__KEY__`；⚠️ **`--set` 不会把文件拷进 input，只有 `--ref` 会**——要喂 `CTRL_IMAGE=xxx.png` 得**成对用**：`--ref <路径> --set CTRL_IMAGE=<同一个文件名>`；⚠️ `--set SEED=` 会被随机种子覆盖，**锁种子要用 `--seed`**）

## 实测硬数字（源：`E:\创作\武昭君仪` 的 P3A 736×416 帧，2026-09-28）
| 项 | 数字 | 用法 |
|---|---|---|
| **VAE 往返地板**（空掩膜控制组：采样器一次不重画） | 均值 **10.6**、最大 188、仅 15.9% 像素 ≤2 | **任何「输出应与输入一致」的判断都必须先扣这个地板**；图片链输出与原图**不是**逐像素等同 |
| i2i `denoise=0.30` | 构图相关 **0.833** | 保构图档（换画风/换材质/补细节） |
| i2i `denoise=0.60` | 构图相关 **0.571** | **实测直接换成另一个场景**——0.6 对 FLUX 来说等于重画 |
| inpaint 掩膜外 | 均值 **11.09**（≈地板） | ⇒ **掩膜确实被遵守**，掩膜外只有 VAE 损耗 |
| outpaint 原始区 | 均值 16.3（>地板 10.6） | 差额来自羽化带（原始区四周 40 行 mask>0 会被重画）；**本次底部边界带出现硬边黑块＝接缝风险** |

## 仍然做不到的
1. **depth/几何锁定不可用**：`DepthAnythingV2-L` 对**风格化 CG 帧**只给出糊团（权重是在真实照片上训的）；换成手搓高对比深度块后输出**仍是图案不是场景** ⇒ 问题不只在预处理器，**union 模式号有没有真被切成 depth 尚未证实**。未决判因实验：同一张已知好用的控制图，A/B 比「自定义节点 `FluxUnionControlNetMode` 传 2」与「核心节点 `SetUnionControlNetType` 传 depth(=1)」——注意**两套编号不同**（官方 FLUX-Union-Pro：canny0/tile1/depth2/…；ComfyUI 核心：openpose0/depth1/hed2/canny3/…）。**证实前锁构图继续走 Canny(mode 0) 那条已验证的链。**
2. 没有真·inpaint 模型（FLUX dev 不是 inpaint 专用）⇒ 大区域替换仍偏弱；要更好得下 `flux1-fill-dev` fp8（≈11.9 GB，hf-mirror）。
3. 「保持这张图的场景，只把某个主体挪远／挪位」**现在可以做了**（走 inpaint：把主体 alpha 挖空，提示词描述远处的小主体）——这正是上一轮三试均败时缺的那一环，当时误判成「本机图片链不行」。
4. **同一场景的多机位／多角度一致**（"这个巷子的另一个角度"）——**做不了**：i2i 只保同一构图、inpaint 只改掩膜内、depth 那条又不通；云端 Seedream 侧也有同样的实测（"i2i 锁不住机位"）。目前只能靠 Redux 挂场景参考给"像同一个世界的另一个角度"，或干脆每张单独出、一致性靠人工挑。
5. **严格三视图／正交多视图**（同一角色正/侧/背严丝合缝）——纯扩散模型做不到，要 3D 或专门的多视图模型。**"多套造型并排/转身图"这类（如资产包里即梦出的双造型并排）能做，但那是"一张图里画几个样子"，不是几何一致的三视图**，别混为一谈。

## ★Z-Image-Turbo 已装上本机（10-04，int8，实测可用）

`engine/comfy/z_image_turbo_api.json` ＋ 三个权重落在 `ComfyUI_H3/ComfyUI/models/`
（`diffusion_models/z_image_turbo_int8_convrot.safetensors`、`text_encoders/qwen_3_4b_fp8_mixed.safetensors`、
`vae/ae.safetensors`）。**不用升 ComfyUI**（0.30.2 已内置 `comfy/text_encoders/z_image.py`）。

1. 🔴 **仓名坑**：要 `Comfy-Org/z_image_turbo`，**不是** `Comfy-Org/z_image`（后者是基座模型，
   文件名只差 `turbo` 三字）。10-04 下错一次，停在 1.5GB 时核官方模板的模型清单才发现。
2. **源选 ModelScope**：hf-mirror 掉到 0.56 MB/s（4.9GB 要 2.4 小时），ModelScope 实测 **38.9 MB/s（70×）**，
   且支持 Range。⇒ 大权重先各下一份做**跨源 sha256 对比**（两份独立来源同哈希才算验过；
   注意 HF API 的 `blobId` 是 LFS 指针的 git blob id，**不是内容 sha256**，别拿它对）。
3. **官方接法三处与 FLUX 习惯不同**（凭经验猜必错）：`CLIPLoader type=lumina2`（选项表里没有 z_image）、
   UNet 后挂 `ModelSamplingAuraFlow shift=3`、负向走 `CLIPTextEncode("")→ConditioningZeroOut`；
   8 步／cfg 1.0／`res_multistep`／`simple`／`EmptySD3LatentImage`。
4. **速度**：768×1344／8 步 **5.1 秒一张**（冷启动首张 36.7s 含加载）；现役 flux1-dev-fp8 同尺寸 20 步约 60s ⇒ **约 12×**。
5. ★**冒烟结论（三张，手填提示词、无润色）**：一行中文提示词就把范例影调**几乎白送**——
   p1 7.2–9.8（范例 5.0–12.8 ✓ 阴影底天然对）、对比档 5.4–5.9（范例柔光镜 5.2–6.5 ✓）、
   肤色角 −46.5～−49.0（范例 −45～−51 ✓）、亮面≥70 9.7–15.4%（范例 7.7–27.0 ✓）、塌黑 0；
   只有 p50 32.6–35.4 比范例高调镜低 3–11 IRE、饱和 R 26.9–27.6 仍高于范例 19.8–22.6（但只差 4–7 点，
   FLUX.1 是差 17–30 点）。⇒ **我们在 FLUX.1 上攒的那套杠杆词表（发光体＋雾）在这台模型上基本不需要**
   ——又一次印证 [[feedback-per-channel-rules]]：换模型＝换账本，旧实测不跨通道套。
6. ★**中文提示词在这台模型上能锁住中式题材**：同一场景，中文一行出到汉服＋金饰＋发簪全对；
   英文那句 `white and pale-gold robes` 出成希腊垂坠长袍。⇒ 中式角色/场景设定图**优先写中文**
   （与官方"支持中英文＋双语文字渲染"口径一致，但这是我们的对照观察，样本＝各 1 张，待多跑确认）。
7. **10-04 裁定并执行：FLUX.1 退役＋权重已删**。上午 `/free` 后显存 13.2→2.1 GB、可用内存 4.9→15.2 GB；
   下午补齐 Z-Image 侧四条模板（i2i／inpaint／outpaint／upscale）＋七条流改指过去之后，删
   `flux1-dev-fp8.safetensors`（11,901,525,888 B，SHA256 `1be96134…dfce`），**D 盘实释放 11.08 GB**。
   ⚠ **删之前先查 junction**：`ComfyUI_H3\ComfyUI\models\` 下十九个模型目录**全是 junction → `D:\Models\ComfyUI\*`**，
   所以"H3 那份"与"D 盘池那份"是同一个文件；独立第二份在 **`E:\Models\ComfyUI\diffusion_models\`**（逐字节哈希实比一致，留着）。
   恢复＝从 E 盘拷回，**别重下**。详见 [[feedback-copy-not-move]] 延伸四。
   🔴 **当场断两条**：`image_depth`、`previz_control` 仍绑 FLUX ControlNet（Z-Image 侧无对应权重），
   实测删后提交即 **HTTP 400 `value_not_in_list`**——响亮失败，不是静默出坏图。
   ⚠ 依赖账差点算错：第一版只在 yaml 里搜权重文件名 ⇒ 得到"0 条流依赖"，而 yaml 根本不写权重名只写模板路径；
   改成「yaml → comfy/*.json → 权重名」两级对账（`tmp\wzy\dep_graph.py`）才量出**七条流**曾指向 FLUX。
8. **C-4 四镜对照（同种子配对）**：这台**认"方向词"远好于 FLUX.1**——镜4 要正面平光量到 0.36 档
   （范例 0.13–0.32 ✓）、镜5 要两档侧光量到 2.20 档（范例 2.01–2.31 ✓）、饱和 R 21.9–31.9（FLUX.1 是 39–55）、
   镜5 的"满殿烛海"真出来了（亮面 4.0 % vs FLUX 0.2 %）。
   **但绝对明度仍不受控**：该亮的镜3 写"画面明亮通透"只给到 p50 23.5（范例 45.7–47.0）。
   ⇒ 与 FLUX.1 同病、程度轻：**相对方向词可控，绝对明度词不可控**。
   ⚠ 同时抓到自己一个提示词缺陷：C-4 把「汉服／金绣／女子」等名词省了，模型就出希腊白裙／古装男子
   ——**"中文锁题材"的前提是名词写全**，别把这条记成模型偏见。

9. ★**Z-Image 自己的 denoise 梯子（10-04，768×1344 同 seed 5 点，逐像素对源图）**：
   0.30→MAD 5.29／亮度相关 0.986；0.45→6.81／0.977；**0.60→9.35／0.956 ←保构图换画风甜点区**；
   0.75→23.97／0.768（构图开始漂）；0.90→106.81／0.020（等于重画）。
   ⇒ **与 FLUX 通道正好错位**：FLUX 在 0.60 就已经"换成另一个场景"（构图相关 0.571），Z-Image 要到 0.75~0.90 才崩。
   `image_i2i.yaml` 默认档因此从 0.3 提到 **0.6**，旧 FLUX 刻度在 yaml 里降级为历史留档并标明不可跨通道借。
   掩膜侧：inpaint 洞内／洞外 MAD 46.92 vs **1.83**（25.7×），越过 grow 带 20 像素回落到 1.19× 平台 ⇒ 无越界接缝；
   outpaint feather=40 吃进原始区约 **40 列**（14.3× 平台，40~80 列 1.2×）＝与 FLUX 同机制；768×1344 左右各垫 256→1280×1344 成立。
   ⚠ **别把 1.83 当 VAE 地板**：那是"掩膜外差异"，本机没为 Z-Image 单独量过空掩膜控制组地板（FLUX 那条 10.6 不适用）。
   尺子：`tmp\wzy\z_i2i_ladder.py`／`verify_edit_smoke.py`／`seam_decay.py`。
10. **IMAGE 侧 LoRA 供给（10-04 核，回答"有没有 LoRA"）**：
    官方 `Comfy-Org/z_image_turbo` 带 `split_files/loras/z_image_turbo_distill_patch_lora_bf16.safetensors`
    （158,826,336 B），但那是给**基座** z_image 加速用的蒸馏补丁 ⇒ **我们下的是 turbo 本体，这个补丁无用**，别当必装件。
    社区确有一条 Z-Image-Turbo LoRA 线（去 JPEG 压痕 `wcde/Z-Image-Turbo-DeJPEG-Lora`、像素风 `tarn59/…`、
    写实 `suayptalha/…`、负向 `DoctorDiffusion/…PNTE-Negative-…`）；⚠ **下载量≠许可**，要哪个当场读 license；
    `nphSi/Z-Image-Lora`（317,921 dl，比第二名高两个数量级、名字无指向）先当可疑。
    机制上工具链齐（`comfy_run.py --lora` 在；ComfyUI 0.35.1 有专为量化权重写的旁路
    `comfy/weight_adapter/bypass.py`，`model_patcher.py:968` 显式处理 `QuantizedTensor`）。
11. ★**LoRA 挂 int8-convrot 底模：✅ 实测生效（10-04 夜，此前记的是"未验"）**。
    测试件 `tarn59/pixel_art_style_z_image_turbo`（**Apache-2.0**，170,128,328 B，
    sha256 `09b1b45c…43577f`，rank32／240 对／BF16，metadata `ss_base_model_version: zimage`）。
    同 seed 三臂：**强度 0.0 与不挂逐像素完全相同**（最大差 0）；0.3／0.6／1.0 对基线均差
    6.56／13.46／23.54；带触发词跑满 1.0 **出图是无可争议的像素风**。键名也对得上
    （LoRA `diffusion_model.layers.N.…` ↔ 底模 `layers.N.…`，ComfyUI 剥前缀）。**不需要旁路节点。**
    🔴 **挂 LoRA 第一件事是读触发词、不是调强度**：该件 `ss_tag_frequency` 里触发词是整句
    `Pixel art style.`；我第一轮没带，三张都还是照片级，**差点误报成"风格还原度弱"**——
    那测的是"没触发"不是"没生效"。⇒ 下载后先读 header 的 `ss_tag_frequency`／`trainedWords` 再测。
    ⚠ 同轮又作废一把尺子：拿"唯一颜色数下降"当像素风签名是错的（带触发词那张反而 62,298→**79,151**，
    像素风是色板限量但分散）；对的是**硬边占比** 0.02 %→0.89 %（44 倍）。
    另：**"差异像素占比"在强度 0.3 就饱和到 98 %，不能分档**，分档只能用平均差。
12. **MJ 风格 LoRA for Z-Image：有，三件，但许可全空**（10-04 经代理查 civitai；HF 搜不到，
    我上一轮"Z-Image LoRA 生态很小"是**只搜 HF 造成的误判**）：
    `Midjourney Luneva Cinematic Lora`（作者 luneva，**16,008 dl**／1471👍，648.8 MB R128，
    base ZImageTurbo，`licensing: null`，**说明里要求 fp32 UNet**：`--fp32-unet`，
    该开关本机 0.35.1 有（`cli_args.py:89`）但会牵连同实例的 H3）；
    `MIDJOURNEY_V1_Z-image_Turbo`（SPOON_IA，5,115 dl，162.2 MB，`licensing: null`，无触发词，推荐权重 0.7~1.0，**无 fp32 要求**）；
    `MIDJOURNEY_ ZIB`（ZImageBase，1,228 dl）。
    🔴 **HF 上那个 `mkczer/Midjourney_Luneva_Cinematic_Lora` 的 `license: apache-2.0` 不算数**——
    是第三方转帖者自己标的，原作者没授权，而且那仓库是**空壳**（只有 .gitattributes＋README，无权重）。
    ⇒ 非权利人贴的许可≠许可；商用风险归用户裁。
    ✅ **两件已下载并实测（10-04 夜）：都挂上了，效果质变、方向不同。**
    Luneva（648.8 MB／rank 128）保住构图，把整帧推成"电影剧照"（木构转暖、沉黑加深、雾气加重、绿调压灰）；
    MIDJOURNEY_V1（162.2 MB／rank 32）改得更狠（换地面、整体压暗、青橙分色）。两件均无可见硬伤，
    对基线均差 32.87／42.66（阳性对照像素风 41.60）。SHA256 均与 civitai 声明命中。
    ⚠ **Luneva 要求 fp32 UNet，但在 int8-convrot 上出图干净无碎斑**——只能记"没看到缺陷"，
    **不等于 fp32 无用**（作者讲的是 FlowMatch 对 dtype 的细微敏感，本轮没做 bf16／fp32 对拍，
    换底模要重启且牵连同台 H3）。留在未验。
    ⚠ 四臂内容本身不同（换了地面、人物占比变小），**检光的全域统计会把"换内容"混进"换风格"**，只当次要证据。
    🔴 探针自伤一次：`lora_probe.py` 报三件都有 120/240 键"未命中"底模，但**已知能用的像素风那件数字一模一样**——
    底模用融合的 `attention.qkv`／`attention.out`，LoRA 用分离 `to_q/k/v`／`to_out.0`，
    属 ComfyUI `lora.py` 的重映射。⇒ **判兼容性只能实测；静态键名比对没有"已知能用的对照件"就毫无意义。**
    ✅ **两件 MJ LoRA 的硬件代价（热缓存 3 张／臂，时间取 ComfyUI 日志 `Prompt executed in`）**：
    不挂 5.24／5.03／5.02 s；Luneva 5.60／5.05／5.01；MJ_V1 5.62／5.04／5.02。
    ⇒ **显存零增加**（挂 180 patches 与不挂 0 patches，staged UNet 都是 **5888 MB**）；
    **稳态时间零增加**；唯一代价＝**换 LoRA 后第一张 +0.6 秒**（一次性重打补丁）⇒ **按 LoRA 分批跑即摊平**。
    真实差异只在 RAM／磁盘：Luneva 补丁本体 649 MB（驻留实测 +0.39 GB）、rank32 两件 162 MB
    （+0.00＝低于 12.4 GB 读数的分辨率，只能说没测出来）；磁盘合计 811 MB。
    🔴 **我从 header 静态推算的"命中层须从 int8 反量化成 bf16 ⇒ 净增 3.40 GB"是错的**，
    被日志 staged 数值直接证否（四臂同为 5888 MB）⇒ **静态推算资源代价不可信**。
    另：`comfy_run` 轮询是 4 秒一跳，**量不出秒级差异**——我第一版就量出"四臂都 12.1 秒"
    ＋"Luneva 反而省 1.39 GB 显存"这种假数，作废后改用日志才拿到真值。
    随 FLUX 一起失效：`loras\flux\` 三件约 1.4 GB。另纠正一条旧注释：
    `image_draft_batch.yaml` 举例的 `flux\Hanfu_Elegant_Flux.safetensors` **盘上根本没有**（已改注释）。

13. ★**锁几何／锁剪影已补回，且是 ComfyUI 原生路（10-04 傍晚）**：
    权重 `alibaba-pai/Z-Image-Turbo-Fun-Controlnet-Union-2.1-2602-8steps.safetensors`
    （6,712,485,600 B，全 BF16，**Apache-2.0 可商用**，SHA256 `d1251cc7…f4a689`），
    落 `models/model_patches/`（新建＋做成 junction 进 `D:\Models\ComfyUI\` 池）。
    **不用装第三方节点**：本机 0.35.1 的 `comfy_extras/nodes_model_patch.py:258` 有专门认它的分支
    （判据键 `control_all_x_embedder.2-1.weight`，按 `control_layers.4/14` 自动判 lite(3层)/全量(15层)），
    节点＝`ModelPatchLoader` → `ZImageFunControlnet`。
    🔴 **它不是标准 ControlNet 格式**（`controlnet_down_blocks` 一类键全无）⇒ `ControlNetLoader` 加载不了。
    支持 Canny/Depth/Pose/MLSD/Hed/Scribble/Gray ＋ inpaint，**且没有模式选择器**
    （喂什么预处理图就是什么控制）——FLUX Union 那个"模式号到底切没切过去"的悬案在这条路上不存在。
    **实测刻度**（`tmp\wzy\cn_adherence.py`，各带同提示词同 seed 不挂控制对照）：
    **strength 1.0 是拐点，1.5 无增益**（官方卡片 0.65~1.00 与实测对上）；
    稀疏控制图 hall：基线块布局相关 **−0.224**（提示词自己摆出的是反向构图）→ 挂控制 **0.956**、纵向投影 −0.454→0.920；
    稠密灰模 p3a：基线已摆对八成 → 增量只 +0.225（**增量小≠控制弱，是那条样本不需要控制**）。
    ⚠ **强度够高时控制压过提示词**：提示词写"背对镜头"，出的是控制图里那个侧身人物——
    跟姿态/站位冲突的描述会失效，别指望叠加。
    ⚠ 灰模可直喂（2602 的 Gray 控制，控制图走 VAE 编码），省一道预处理，本次纵向 0.529 vs 提边 0.648。
    挂控制 768×1344／8 步 **16.2 s/张**（不挂 5~9 s）。`previz_control` 已改指此路（steps 20→8、strength 0.8→1.0）。
    未验：int8 底模 vs 官方 bf16 无画质对拍；depth/pose/mlsd 没跑过；节点标 EXPERIMENTAL；每格样本＝1。
    🟡 **depth 的病根挪了但仍未通**：控制网侧没问题了，卡在 `DepthAnythingV2Preprocessor` 对 CG 帧出糊团；
    现在真正可行的路子是**从 UE/Blender 渲真深度缓冲(Z pass)直喂**，绕开估计器——这条路以前不存在。

14. ★**depth 通道定性（10-04 夜，带真值实验）**：上面"depth 仍不通"那句**已被自己推翻一半**——
    **通道是活的，死的是估计器出的深度图**。
    真值实验：自造一张结构已知的合成深度图（地平线＋地面渐变＋左近白块＋右中灰条），
    配一句**与深度结构相冲突**的提示词（"混凝土墙占满画面、无任何景深线索"）当探针。
    输出在真值矩形边界上的梯度富集比：不挂控制 **1.01x**、挂翻转估计深度 **1.02x**、
    **挂合成深度 s1.0＝2.42x**、挂合成深度 s2.0＝19.75x（**过驱：抄灰阶不是锁空间**）。
    ⇒ ① 09-28 那笔"手搓高对比深度块仍是图案不是场景"的悬案定案＝**FLUX union 的 depth 模式号没生效**，
      与深度图质量无关；② DepthAnythingV2 的输出**锐边占比 0.00 %**（合成图 0.32 %），
      而控制图走 VAE 编码 ⇒ **没有断缝＝没有信号**，这不是"CG 帧估不准"，是相对深度图天生不带边界信息；
    ③ **手工搓粗深度块是零门槛正路**（不必先装 3D 软件），`image_depth` 已改成"深度图由调用方给"、
      不再内嵌预处理器；④ depth 与 canny 强度行为不同，**canny 到 1.5 只是无增益、depth 到 2.0 会过驱**，都停在 1.0。
    🔴 **两把当场做废的尺子（同族教训：先量地板）**：
    ① 用"输出再估深度 vs 控制深度图"做 Pearson，量出 +0.082 像是正效应——
      把所有深度图两两交叉排矩阵才发现**无关对之间均值 0.719**，我所有读数全在地板以下；
      单目估计器输出高度模式化（下方亮、上角暗），**任何两张它生成的图都天然高相关**，这把尺子原理上就不能用。
    ② 主体轮廓带富集比 0.83~1.22x 那把，带子取 12px 宽且把背景岩石算进"主体"，被稀释，只配当旁证。
    ⇒ 判据：**用"相关"类指标前，先量无关对之间的地板；读数不过地板就等于没测。**
    与 [[feedback-evidence-loop-trap]] 同族（⑫ 单位错配／尺子丢维度上的否定结论不算结论）。

## ★换代模型候选与许可（10-04 现查 HF 元数据，huggingface.co 被墙⇒走 hf-mirror API）

| 模型 | 许可（HF tag／卡片原文） | 能不能商用 | 本机可行性 |
|---|---|---|---|
| **FLUX.2-klein-4B** | `apache-2.0`；卡片原文 “Open weights available for **commercial use** under the Apache 2.0 license” | ✅ | FP8 约 8–9GB（BF16 约 13GB），4 步蒸馏 |
| FLUX.2-klein-9B | `license:other` ＋ `license_name: **flux-non-commercial-license**`，且 **gated**（要登录同意） | ❌ 非商用＋有门槛 | 排除 |
| FLUX.2-dev（32B） | `other`（BFL 非商用） | ❌ | 排除 |
| **Z-Image-Turbo**（阿里，6B） | `apache-2.0` | ✅ | 官方口径就是「16GB 消费级」，8 NFE；TE＝`qwen_3_4b` |
| Qwen-Image-2512（20B） | `apache-2.0` | ✅ | 16GB 要量化＋offload，慢 |

- 🔑 **本机这台 ComfyUI 已经内置 Z-Image 与 Qwen-Image 支持**：`comfy/text_encoders/z_image.py`、
  `qwen_image.py`、`lumina2.py` 都在（`comfy/sd.py:1878-1879` 已接线）⇒ **换模型只差下载权重，不用升 ComfyUI**。
  D 盘余 244GB；现役 `flux1-dev-fp8.safetensors` 12GB 在 `models/diffusion_models/`。
- ⚠ **huggingface.co 直连不通**（curl 443 超时）⇒ 元数据与文件全走 `https://hf-mirror.com/api/models/<repo>`
  与 `.../resolve/main/<path>`（见 [[reference-cn-download-mirrors]]）。
- 样张已下到 `D:\AIWorkflow\tmp\模型样张_20261004\`（klein-4B 三张 jpg ＋ Z-Image 五张 png，
  含官方 leaderboard）。⚠ **那是厂商自宣样张，按 [[feedback-low-expectation-external-capability]] 不算结论**，
  真判据是同题对照：拿 K1b／K3b／K4b／K5b 在新模型上重跑，用检光量 p50／p1／亮面／饱和对范例区间。
- 榜单口径（Arena 快照 09-24）：闭源前五 1302–1424 Elo，开源最高 Qwen-Image-2512 1125／Z-Image 1084
  ⇒ **本地换模型追不上云端**，换它的理由是「可商用＋零成本＋可控」，不是「更强」。

**Why**：这是「能不能做某件事」的前置判断。上一轮因为误判而白烧三轮，本轮因为补了模板一次就成。
**How to apply**：凡需求形如「保这张图的构图/场景，改其中一部分」⇒ 走 Z-Image 那四条模板
（i2i **保构图换画风取 denoise 0.6**，0.3 只动材质、0.9 等于重画；只改局部用 inpaint 的 alpha 掩膜；
要加画面用 outpaint，记得 feather 那一条会被重画）。
🔴 凡需求是「改机位/改纵深/锁几何/锁剪影」⇒ **本地图片链现在没有这条路**：
10-04 删 FLUX.1 权重后 `image_depth` 与 `previz_control`（lineart）都已断，
以前那句"只能用 Canny 的灰模锚链"现在连那条也没了——要这类控制得另裁通道（云端或把权重从 E 盘拷回）。
关联 [[feedback-local-first-generation]]、[[reference-minimax-h3-local]]、[[reference-ffmpeg-location]]、[[feedback-evidence-loop-trap]]。
