---
name: minimax-h3-local-deployment
description: MiniMax H3 开源视频模型本地部署（**已跑通**）——pruned INT8 16GB 方案、T8 双时钟采样修好音频、fl2va(8步+turbo8step LoRA) 与 ref2va(三锚点+8步+ref2v LoRA) 两套生产标准、原生音频直出、实测速度与 32GB 内存瓶颈；**附 T8 控制面盘点（335 节点：轨迹控制/latent 续接/VideoOutpaint/FaceRefine；深度·Fun 已被人审否）与「出图侧 ControlNet 备而未用」实查**
metadata:
  type: reference
---

MiniMax H3 已开源权重（可商用，年营收 <$20M 免费），原生 768p、最长 15s，2K 只在 API 侧。全量 BF16 ≈39.5GB，本地必须量化。

**量化档**：
- GGUF Q2–Q5 = 15.6–23.9GB
- INT4 ≈11.3GB
- INT8 ≈21GB
- NVFP4 ≈12.5GB（Blackwell 原生支持）

**16GB 显存推荐配置**：
- DiT: GGUF Q3_K_M (15GB) 或 INT4/INT8 混合
- 文本编码器: INT4 版（qwen3vl_32b，必须匹配 DiT 训练分布，不能用云端 API 替代）
- 另需 video VAE (fp16) + audio VAE (fp32)

**核心能力**：
- `fl2va` = 首尾帧 → 因果链结构硬门槛本地可做（节点 MiniMaxH3ImageToVideo + MiniMaxH3AddGuide）
- `ref2va` = 多模态参考生视频 → 正面解决跨镜脸飘，可用参考图锁角色不必先炼 LoRA
- 原生 joint audio（video+audio 双 VAE）
- 24fps，时长按帧对齐（17k+5），社区口径 5–15s

**文本编码器（qwen3vl_32b）关键约束**：
- 不是"可插拔的 LLM"，是 DiT 条件空间的一部分：输出必须是 [seq, 5120] hidden states
- 云端 API 不返回张量，分布必须严格对齐（换同架构不同权重都掉跟随性）
- 16GB 必须用 INT4/NVFP4 版，与 DiT 顺序换入换出（不并发驻留显存）
- 可通过 conditioning 缓存规避重复编码（同提示词换 seed/步数可复用）

**速度实测**（社区数据，未同卡验证）：
- 4090 + Q3_K_M DiT + Q2_K TE：10s 视频 = 6m20s
- 16GB 卡（5060 Ti）5s/768p：20 步约 6–8 分钟，Turbo LoRA (4-8 步) 约 1.5–3 分钟
- 对比 HV1.5：720p 121f (5s) = 26 分钟（+EasyCache 15 分钟）

**切换成本**：
- VRAM ↔ 内存：秒级（权重已在内存时）
- D: NVMe 冷读：10–25s / 15GB
- E: SATA 冷读：分钟级（致命档）
- 按阶段批处理（先编码落盘再批量采样）= 全片只换 2 次（+2–4%）
- 逐镜交替 = 每条 +30–120s（+15–40%）

**与 HV1.5 对比**：
- HV1.5 优势：已验证管线、锁定图直出零重绘、480p 草稿→超分工艺成熟
- H3 优势：首尾帧本地化（云端付费→免费）、ref2va 锁人、原生音频、可能省掉超分
- RAM 足迹相当：HV1.5 (16.65GB DiT + 9.38GB TE ≈ 26GB) vs H3 Q3_K_M+Q2_K (15GB+12GB ≈ 27GB)

**ComfyUI 节点**：
- MiniMaxH3ImageToVideo, MiniMaxH3AddGuide
- 模型：minimax_h3_fl2va_pruned_int8_convrot (T2V/I2V), minimax_h3_ref2va_pruned_int8_convrot (R2V)
- Turbo LoRA：fl2v_turbo_8step_v1.0, ref2v_turbo_4step_v0.1

**部署建议**：
- 另建 ComfyUI 实例（不覆盖现有 HV1.5 portable，避免打翻已验收配置）
- 模型放 D: NVMe（避免 E: SATA 冷读灾难）
- 先跑 480p/5s 20 步验证，再上 Turbo LoRA + 768p
- 拿《无音》已交付镜头做同帧 A/B 对比（H3 vs HV1.5）再决定主通道切换

**现成 GitHub 部署方案（2026-09-13 已核实）**：
- **neng320/minimax-h3-local-deployment**＝最对症：16GB 消费级卡实测（4060Ti 16GB，含 5060Ti 参考数），一键脚本 + deployment-handbook.md + 恢复指南；核心加速链=cu130 硬件反量化+SageAttention+T8 双时钟 turbo；**只有 SageAttention 可靠加速，TE-Speed 实测失真弃用**
- **双版本必须按用途选**：v1=pruned INT8 20.9G（产品/动画向，快但细节弱）vs v2=full INT8 34G（真人/写实向，~300s/条）；**《无音》电影级写实CG → 必须 v2**（v1 剪枝丢层，加分辨率补不回）
- 速度：v2+Sage 4060Ti 640×640 ≈300s/条；**5060Ti 8步 154s / 20步 ~190s**；480p 抽卡 3-5 分钟
- **AIMixer/ComfyUI_MiniMaxH3_Director**（huangserva 有副本）＝导演台工作流，5 份 JSON（T2V/FL2V/R2V/V2V/**RV2V=视频换人**，RV2V 对锁脸/换人极有用）
- **tritant/ComfyUI_MiniMax_H3_Extender**＝多镜连续生成（Motion Context 开=跨镜连续性，关=逐镜独立可随机改）
- 官方权重 Comfy-Org/MiniMax-H3（HF）+ ModelScope 国内直连下载；模型清单＝DiT(INT8 pruned20.9G/full34G)+qwen3vl_32b NVFP4 TE+video VAE fp16+audio VAE fp32+turbo LoRA(仅v2)
- **许可证排除美/欧/英/韩地区，中国可用**（商用/出海先自查协议原文）

**已落地部署（2026-09-13，5060Ti 16GB + 32GB 内存实测跑通）**：
- **使用规范（用前必读）已落成**：`D:\AIWorkflow\ComfyUI_H3\使用规范_用前必读.md`（顶层；含生产配方/提示词要求/性能数据/10 条坑/故障速查/待办）——经用户验收「完全可用、达成片标准」。改动配置或排查前先读它
- 新实例 `D:\AIWorkflow\ComfyUI_H3`（复制 HV1.5 portable 的 python_embeded=torch2.13+cu130+sage2.2，git checkout v0.30.2 升核心，模型 15 个 junction 指向 D:\Models\ComfyUI），端口 8189
- 跑批脚本 `run_h3.py`（直调 /prompt 原生节点，I2V=LoadImage→UNETLoader→MiniMaxH3SigmaShift(12/3)→MiniMaxLowVRAMAttention→CLIPLoader(type=minimax)→VAELoader→MiniMaxH3ImageToVideo→ConditioningZeroOut→KSampler(dpmpp_2m+beta+cfg1)→VAEDecode→**CreateVideo(fps24)→SaveVideo(format="mp4",codec="h264")**）
- **两个坑（必记）**：①comfy_kitchen 必须 ≥0.2.26（0.2.22 缺 `dequantize_embedding` → INT8 convrot 模型加载报 `TensorWiseINT8Layout has no attribute dequantize_embedding`）；②0.30.x 的 SaveVideo 只收 VIDEO 类型，要 VAEDecode→CreateVideo 桥接，format 填 "mp4" 不是 "video/mp4"；/history 里视频在 "animated" 键
- **实测速度**：1024×576 20步=冷启 5m47s（采样 4m55≈14.7s/步），输出 h264 5.17s 无音轨；下次跑 JIT 已缓存会更快；音频解码走 VAEDecodeAudio+audio_vae→CreateVideo.audio（基准测试未接）
- 文本编码器 qwen3vl NVFP4(14.6G) 随 DiT 顺序换入换出，显存峰值约 14GB 内
- **时长-耗时非线性（关键）**：5s(124帧)=冷启 5m47s（采样 4m55，14.7s/步）；**15s(362帧)=总计 25m38s（采样 23m46，71.3s/步）**——帧数 2.9× 但耗时 4.8×（注意力随序列超线性）
- **32GB 内存是长镜硬瓶颈**：15s 跑时空闲内存仅剩 1.8GB，40GB 模型载入被换页拖到 ~14 分钟；结论＝H3 本地适合**短镜(5–8s)**，15s 级长镜在 32GB 上很痛苦（要么拆镜、要么长镜留云端）
- 长镜建议：shorter shots preferred；如必须长镜，先考虑拆成 5-8s 段，或升内存
- **turbo LoRA 实测（2026-09-13）**：两个 LoRA 都能在 **pruned INT8** 上加载并出片（推翻作者"pruned INT8 不能完整应用 turbo LoRA"的存疑，但画质需盲判）——`LoraLoaderModelOnly` 插在 UNETLoader→SigmaShift 之间，strength 1.0
- 文件名：`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`、`minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors`（各 1.82G，在 D:\Models\ComfyUI\loras）
- **5s 镜提速实测**：20步 347s → 8步+8stepLoRA 180s(3:00) → 4步+4step_768p LoRA 110s(1:50)
- run_h3.py 支持 `--lora <文件名> --lora-strength <x>`；run_h3.py 有 outputs 写入竞态，已加防抖重读
- **15s 镜4 turbo 对比实测（1024×576，同首帧/提示词/seed）**：20步 25m38s(采样23m46) → **8步+8stepLoRA 11m32s(采样9m40)** → **4步+4step_768p LoRA 6m42s(采样4m50)**；LoRA 出来后 model 显示 "208 patches attached" 表示生效；输出落 D:\AIWorkflow\ComfyUI_H3\output\（h3_shot04_test / _turbo8 / _turbo4.mp4）
- **生产标准（用户 2026-09-13 定）**：H3 本地出片**最低 8 步**＋`minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16`（strength 1.0）。**4 步版画面有缺陷，弃用**。run_h3.py 默认已改为 steps=8 + 挂 turbo8step LoRA
- **原生音频已接通（2026-09-13）**：`VAELoader(audio_vae=minimax_h3_audio_vae_fp32)` → `VAEDecodeAudio(samples=KSampler, vae=audio_vae)` → `CreateVideo.audio`；输出 mp4 = h264 视频 + **aac 32kHz 立体声**；比无音轨仅多约 10s；`--no-audio` 可关。run_h3.py 默认开音频
- **音频人声风险（待用户听验）**：H3 是音视频联合生成，测试提示词未写"不出声"时音轨可能冒出人声/哼鸣。哑女（沈无音）出片必须在提示词写死「全程不出声、无对白、不张嘴」（同 [[feedback-video-quality-standards]]），否则音轨会带人声
- **脚本输出目录坑**：ComfyUI 用 `--output-directory D:\AIWorkflow\ComfyUI_H3\output` 启动，run_h3.py 的 OUTPUT_DIR 必须与之一致（不是默认的 ComfyUI\output），否则脚本永远报"无输出"但片子其实已落盘
- **音频杂乱的根因与解法（2026-09-13 实测）**：原生 KSampler 是**单一时基**，处理不了 H3 的 AV 双流协议 → 8 步音频噪（音量 profile -14.1/-2.2，近削波）、要 20 步才干净（-22.0/-7.5）。**正解＝换 T8 双时钟采样链**：装 `T8mars/comfyui-minimax-h3-audio-T8`（**零额外依赖**，注册 **335 个节点**，克隆到 custom_nodes 即可）→ 用 `MiniMaxH3DualClockSamplerT8`（输入 model/av_latent/steps/shift_video/shift_audio，**输出 model+sampler+sigmas**）→ `BasicGuider` + `RandomNoise` + `SamplerCustomAdvanced` + `MiniMaxH3AVDecodeT8`（输入 av_latent/video_vae/audio_vae，输出 frames+generated_audio）
- **实测：T8 双时钟 8 步 + turbo8step LoRA + 音频 = 186s**（与原生 8 步 180s 几乎同价），音量 profile **-22.8/-9.2 ≈ 20 步干净版**。即"快 + 音频干净"的解
- run_h3.py 加 `--sampler {t8,native}`（**默认 t8**）；T8 采样链保留原生 `MiniMaxH3ImageToVideo` 做 conditioning/av_latent，LoRA 插在 UNETLoader 与 DualClockSampler 之间
- T8 包还有：`MiniMaxH3MultiRateSamplerEXPT8`（video_steps/audio_steps 分开，但**按 audio_steps 计费**，4/10≈10 次 DiT 调用）；官方稳定基线是 **4V4A**（双时钟同步数）
- **Ref2VA 多图参考已装并跑通（2026-09-13）**：权重 `minimax_h3_ref2va_pruned_int8_convrot.safetensors`（19.53G，D:\Models\ComfyUI\diffusion_models）+ 原生节点 `MiniMaxH3ReferenceToVideo`（最多 9 图/3 视频/3 音频，**无 first_frame**，提示词用 `<Picture i>`/`<Video k>`/`<Audio j>` 指代）。run_h3.py 支持 `--ref-images "a.png,b.png,..."`（给了就走 ref2va 模式，默认不挂 LoRA）
- **★ fl2va 尾帧（last_frame）两头夹动作已接上并实测有效（2026-09-20）**：节点 `MiniMaxH3ImageToVideo` 原生有 `last_frame` 输入（`comfy_extras/nodes_minimax_h3.py` L117–118；首帧=frame0 直接拉伸、尾帧=frame_count-1 居中裁切，打包成 `minimax_keyframes`），但 `run_h3.py` 以前只接 first_frame。**已给 run_h3.py 加 `--last-frame <png>`**（fl2va 两条 builder 都接、模式串显示 `fl2va/t8+尾帧`）。**实测《对门》G07 撕绷带镜**（576×1024/len144→H3 按 17n+5 抬到 158 帧/8步/turbo8step/带音频，261s）：灰度归一化相关端点相似度 **首帧vs起始参考 0.995、末帧vs结尾参考 0.995、中帧居中(0.81/0.91)** → 首尾两头确实钉住、中间插值出动作。**这是"锁动作"的正解，比堆参考图对症**（参考图只锁身份外观不锁运动）。⚠️ 尾帧要的是"动作做完那一帧"，需单独备好（见 [[project-duimen-shortdrama]]：G07 首帧真源其实是结尾态，起始帧用即梦 i2i 生成）。
- **autogrow 输入的 API 键名坑（内省确认）**：不是 `ref_image_0`，而是 **`ref_images.ref_image_0`**（组名.前缀序号，点号连接；同理 `ref_videos.ref_video_0`）；用错会报 `execute() got an unexpected keyword argument`
- ref2va 实测：5s / 1024×576 / **20 步无 LoRA = 426s**（带音频）；ref2v 有独立 turbo LoRA（`minimax_h3_ref2v_turbo_4step_v0.1`，未测，4步版画质风险同 fl2v）
- **★ 参考视频（ref_videos）2026-09-15 打通并实测**：`ref_videos.ref_video_N` 吃的是**图像帧序列（IMAGE）不是视频文件**——链路 `LoadVideo(file: 文件名) → GetVideoComponents(video)`，取输出 `[0]=images` 接 ref_videos；**刻意不接 `ref_video_audios`**（参考片原声/对白会污染音轨）。官方 tooltip 口径 **24fps / 48–360 帧 / 2–15s**，内部 `while n%17!=5: n-=1` 截齐，**超过生成长度的部分直接丢弃**；最多 3 个视频，提示词用 `<Video k>` 指代（与 `<Picture i>` 各算各的 1-based 编号）。`run_h3.py` 已加 `--ref-videos "a.mp4,b.mp4"`（向后兼容，不给该参数行为完全不变）。
- **⚠️ 参考视频的代价＝token 每一步都参与注意力 → 5.17s/124 帧/8 步 = 15 分 08 秒一条（83–87s/步）**，比纯图 fl2va 的 180s 慢约 5 倍（175 帧约 20 分钟）。**整段分段复刻按 15–20 分钟/条排期**；想提速只能减参考帧数或降分辨率。
- **参考视频实测有效（2026-09-15）**：真人对白戏特写段 + 无音锚点 + 真实摄影画风锚 → **运镜（中景→面部特写推近）、动作节奏、含泪表演都被复刻**，且**原片的 iQIYI 水印与中英字幕被提示词里的"不得水印/字幕"压住**——说明"只取运镜动作、不取画风场景人物外观"的职责句**对视频参考同样成立**。多角色对白戏可拆：女主镜挂无音锚、男主镜挂自制原创角色锚、双人镜两个一起挂（图序＝`<Picture 1>`无音 / `<Picture 2>`原创男主 / `<Picture 3>`画风锚）。
- **★ 整段分段复刻实测（2026-09-15，《逐玉》247–289s 42 秒对峙戏 → 8 段拼回 39.96s）**：按镜头边界切 8 段（3.0–7.6s），逐段 ref2va（参考视频＋锚点图）复刻后 concat 拼回，**画质/电影感/运镜推进/表演节奏成立，但用户验收「人物站位和剧情跟原片对不上」（见下条根因）**，水印字幕未带入；角色替换＝女主镜→无音、男主镜→**即梦新生成的原创角色**（挂 STYLE_ONLY 画风锚，不撞演员）、双人镜→两锚同挂。
  - **耗时对帧数超线性（排产铁律）**：73帧=441s／90帧=557s／107帧=702–743s／141帧=1017s／**175帧=2223s**；首条 158 帧因 JIT＋与另一条并发争抢达 3638s，**不代表常态、勿作基数**。→ **段一律切 3–5 秒，绝不超过 7 秒**；本次 8 段合计约 2h48m。
  - 拼接：各段按 `17n+5` 对齐后总长略短于原片（39.96 vs 42.16s）；**concat 必须重编码并加 `-vf fps=24`**（源 25fps 混 24fps 会漂到 47.94fps）；上下对照片同样要分别 `fps=24` + `setsar=1` 再 vstack。
  - 交付链路：对比视频+成片发飞书群（<30MB，须 `--video-cover`，只认 cwd 相对路径，媒体不能带文字，配文另发）。
  - **⚠️⚠️ 用户反馈（2026-09-15）"人物站位和剧情跟原片对不上，但画面质感有电影感了"→ 查出两条硬根因，改前必读**：
    - **① ref2va 节点没有几何锚点，构图从来就没被锁住。** `MiniMaxH3ReferenceToVideo.define_schema()` 的输入只有 `ref_images(≤9) / ref_videos(≤3) / ref_video_audios / ref_audios / ref_image_size`，**没有 first_frame**；参考图/视频被编码成独立尺寸的 latent 块挂在 payload 旁（`ref_blocks`），模型是"看着参考另起一张画布"生成。**只有 `MiniMaxH3ImageToVideo`(fl2va) 的 `first_frame` 是真几何锚**——源码注释原话 `# geometry anchor: plain stretch to canvas`。两者**互斥不可兼得**（fl2va 无 ref_images/ref_videos，ref2va 无 first_frame）。
      - ⇒ **参考图永远赢过文字**：本次人物锚是 4 格立绘（脸特写＋全身正/侧/背），3/4 画面是全身站姿 → 模型按全身立绘构图，提示词写"近景特写"压不住。**要特写必须给裁到特写的参考图，或改 fl2va 用首帧锁构图。**
    - **② 砍台词＝砍掉整段戏。** 原片《逐玉》247–289s 的戏剧信息 100% 在台词里（"也是侯夫人""三媒六聘在何处""这婚事岂能当真""你没有资格替我做主"），本次按"无音是哑女"写死全程不出声/不张嘴 → 8 拍只剩"两人站着对视"，剧情必然对不上。**且【事件脚本】是采样 12 帧自己推的、不是原片实际动作。**
    - 具体偏差清单（对照 `output/_参考段校对表.jpg` 8 段×4 帧）：seg05/seg06 原片女主脸部大特写→出来中景站定；seg03 原片男主背影占前景大幅虚化＋女主右侧中景→出来并肩等距无遮挡；seg07 原片男主左前景＋女主右中后景有纵深→出来等距并肩；seg02/seg08 原片含切镜→按一镜到底做丢了切镜；**seg06 原片出场是女主、本次给了男主（选角错）**。
    - **修法（按性价比）**：换 fl2va 首帧几何锚（先把原片首帧"换人换景"成我们的画面；**本地无真人检测，可直接抽原片首帧**）＞ 参考图按景别裁切（零成本）＞ 逐段核对出场人物重排锚点 ＞ **方法上先跑 1 段最难的验证构图再复制，别 8 段一起写完再批量跑**（本次因此白烧 2h48m）。
- **真人画风＝挂"真实摄影画风参考图"已验收（2026-09-13 用户"这版还可以"）**：ref2va 挂 **4 图**＝三锚点 + 1 张真实摄影图当画风锚；提示词把该图职责写死"**只采用其实拍摄影的画风与质感，不采用其人物／面孔／服装款式／构图／背景**"，并把画风口径从"电影级写实 CG"改为"**这是一幅实拍摄影作品，不是 CG 渲染**"；**无音的脸仍只来自锚点图 <Picture 1>**（须显式写死，防脸被带偏）。用户选定图＝`E:\创作\无音项目\图\画风参考\用户选定_鞠婧祎古装.jpg`（4 图版 5s ≈ 236–246s，比三锚点多约 30–40s）
- 本地**无真人检测**（云端 Seedance 的 PrivacyInformation 是 API 侧策略）；但**真人剧照/肖像素材发表后仍有肖像权与版权风险**，生产建议用自拍/授权素材。可选加码：多挂真实参考图（≤9）、T8 `MiniMaxH3ReferenceVisualStrengthEXPT8` 调参考权重
- **脸/清晰度修复链（2026-09-13 逐条实测）**：
  1. `--ref-image-size max`——参考图改用 2048px 短边（不再压到出片面积），节点的"最佳身份保真"档；**代价：5s 从 236s→436s（≈1.8×，参考 token 每步都参与）**
  2. **1344×768 原生画布**（一直跑 1024×576 是低于模型设计尺寸）——5s/8步/max = 646s
  3. **CodeFormer 逐帧修脸**（`face_restore.py`，本地现成 `codeformer-v0.1.0.pth` + `face_yolov8m.pt`）：LoadVideo→GetVideoComponents→FaceRestoreCFWithModel→CreateVideo→SaveVideo；**50–65 秒/条、零重生成**，fidelity 0.5 清晰增益明显；风险＝逐帧独立→帧间跳动
  4. **修跳动**：开头 1.0s 保持原始不修 + 0.8s 平滑过渡（ffmpeg `blend=all_expr='A*(1-clip((T-1.0)/0.8,0,1))+B*clip(...)'`，旧版 ffmpeg 也支持 clip()）
  5. **T8 Face Refine Window**（未搭但可行）：只重绘坏脸时间窗、H3 原生→天然无帧间跳动；缺的 T8 转码 LoRA 可用仓库自带 `tools/convert_minimax_h3_lora_for_comfyui.py` 转；`06-face-refine/2026-09-05_..._Window_Manual_Review_Advanced_EXP.json`
  6. 二次采样（`13-latent-upscale` 学习型 latent 放大 + 二阶段/`28-progressive-sampling`）：能补真细节，但要下 `minimax_h3_latent_upscaler_3d_fp16.safetensors`、EXP、我们这台上很慢（作者 4060Ti 4+4 5s=1572s）
  7. 完整版 INT8（34G）＝天花板最高，需 64GB 内存
- **硬盘虚拟内存顶不了内存**：ComfyUI 每步都要把权重从内存搬进显存，权重落页面文件＝每步读硬盘，不是慢一点而是慢几十上百倍（15s 那条空闲内存剩 1.8G 时光"载入"就被换页拖到 ~14 分钟可佐证）
- **残留模糊＝"pruned 剪枝 + 分辨率"的合成上限**（用户 2026-09-13 判断："剩下的模糊感主要来源是低画质"）；突破要么完整版+64G内存，要么脸关键镜走云端
  - 补测（2026-09-13）：同一个 3 锚点 5s 镜，**4 步+ref2vLoRA=150s / 8 步+ref2vLoRA=215s**（vs 20 步无 LoRA 426s）；三条均 5.17s/1024×576/带音轨，画质由用户盲判定夺（ref2v LoRA 只有 v0.1 的 4 步版，故额外跑了 8 步看能否救画质）
- **ref2v turbo LoRA 用户验收通过（2026-09-13）**：原话「可以用／这一条很完美了」→ **ref2va 生产标准＝三锚点 + 8 步 + `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16`（strength 1.0）+ 强化写实风格 + T8 双时钟 + 原生音频**。run_h3.py 给 `--ref-images` 时默认**不挂** LoRA，要显式 `--lora` 指定（fl2v 与 ref2v 是两套 LoRA，不可混用）
- **"画风偏卡通"的解法（2026-09-13 用户反馈「有点偏卡通的感觉」→改完验收「很完美」）**：只写"电影级写实 CG"不够，要把【风格与光影】压成**具体可观察的摄影特征**——皮肤毛孔/细纹/次表面散射的通透红润、发丝根根分明带自然分叉、旧丝绸能看清织纹折痕与磨损、哑光塑料与半旧金属的工业质感（划痕掉漆沙尘）、锈蚀金属斑驳红锈；真实电影镜头的浅景深与自然焦外、轻微镜头畸变、高光柔和滚降、细腻胶片颗粒、极轻微镜头呼吸感。并在**两处**写死「不得卡通化、不得二次元大眼睛、不得塑料感皮肤、不得 3D 游戏模型感、不得过度磨皮、不得鲜艳平涂色块」（cfg1.0 无独立负面词字段，只能写进正文）
- **15s ref2va 生产实测**：1024×576 / 362 帧 / 8 步 + ref2v LoRA + 3 锚点 = **742s（12m22s）**，输出 15.08s h264 + aac 32kHz
- **免终端入口**：`D:\AIWorkflow\ComfyUI_H3\run_H3_ComfyUI.bat`（双击起 8189 服务）；规范见同目录 `使用规范_用前必读.md`
- **音频取向（用户 2026-09-13）**：H3 原生音轨「其实可用后期配，不过如果能直出肯定是最好的」→ 继续走 T8 双时钟直出，后期配只作兜底；哑女镜仍须在提示词写死"不出声"
- **本地无真人检测（2026-09-13 确认）**：H3 是本地权重推理，**整条链路没有任何内容审核／人脸拦截**；云端 Seedance 的 `PrivacyInformation` 拦截是 **API 侧策略**、不是模型限制。所以本地可以自由挂真人照片／真人视频做参考素材。
- **"往真人画风推"的主杠杆＝挂真实摄影参考图（2026-09-13）**：ref2va 最多 9 图，把参考素材从"AI 定妆图"扩到"**真实摄影作品**"最有效——真实照片挂成 `<Picture 4>`，提示词写死其职责「**只采用其实拍摄影的画风与质感（真实自然光、皮肤毛孔与次表面散射、织物经纬垂坠、镜头光学虚化与胶片感），不采用其人物／面孔／服装款式／构图／背景**」，并把【风格与光影】口径从"电影级写实 CG"改成"**这是一幅实拍摄影作品，不是 CG 渲染**"，同时保留「无音的面孔与身份只来自 <Picture 1>，不得被其它参考图替换」。实测 4 图 5s / 8 步 + ref2v LoRA = **236–246s**（比三锚点多约 30–40s）。可再多挂真实参考，或用 T8 的 `MiniMaxH3VisualReferenceStrengthEXPT8` 调参考强度。
- **⚠️ 法律面（须向用户说明一次）**：**本地不拦 ≠ 能用**。真人肖像、影视成片帧做素材，**作品发表后仍有肖像权与版权风险**——建议用自建/已授权的实拍素材。若画风推到头仍差意思，那是 pruned 剪枝版的天花板 → 回到"升 64GB 内存上 V2 完整版"的岔路。
- **画风参考素材（已归档）**：`E:\创作\无音项目\图\画风参考\` 下有用户选定的 `用户选定_鞠婧祎古装.jpg`（某女演员古装剧照 690×920）与 agent 抓的 `真实摄影_汉服女子.jpg`（Pixabay 可商用）。
- **挑参考图流程（我看不了图时）**：内置浏览器搜图（**Baidu 图搜可用**；Bing 图搜本机 ERR_ABORTED）→ `evaluate_script` 提直链 → curl 下载（Baidu 直链要带 `-e https://image.baidu.com/` referer）→ **ffmpeg 拼成带编号的 3×2 对比图 → 发飞书让用户报号**（比逐张发省事）。注意老版本 ffmpeg 拼图用 `scale=W:H,setsar=1` 强定尺寸（`pad` 会 configure 失败）。

**⚠️ 脸/清晰度问题与"便宜→贵"解法阶梯（2026-09-13 用户提出，进行中）**
用户「**人脸救不了，加了（剪映）画质增强还是模糊的**」——**后期超分救不了脸**，它只会"猜"细节、猜不出本来没拍到的结构。根因分层：①分辨率没吃满（跑 1024×576，H3 原生 1344×768）；②**pruned 剪枝版固有丢细节**（作者原话"加分辨率补不回"）；③8 步 + 蒸馏 LoRA 偏软；④**脸在画面里占的像素太少**（中景脸只百来像素，给多少分辨率都有限）。
- **① `ref_image_size` 改 `max`（免费，改一个参数）**：`match`＝把参考图缩到出片像素面积（默认，等于一开始就把锚点脸的信息削掉）；`max`＝参考图走 2048px 短边，节点说明称 "best identity fidelity"。**实测会慢**（参考 token 每步参与）：5s/1024×576 从 236s → **436s**。
- **② 出片直接上 1344×768 原生画布（免费）**：max@1344×768 5s = **646s**。用户判定「**768 能救回来一点，不过作用还比较有限**」。
- **③ 本地逐帧人脸修复（CodeFormer，零下载、零重生成，最省）**：模型 `codeformer-v0.1.0.pth`（376MB，`D:\Models\ComfyUI\facerestore_models\`）+ 节点 `FaceRestoreModelLoader` / `FaceRestoreCFWithModel`（`codeformer_fidelity` 0–1，高=更接近原片、低=修得更狠但易塑料感）。链路＝`LoadVideo → GetVideoComponents(images/audio/fps/bit_depth) → FaceRestoreCFWithModel → CreateVideo(images,fps,audio) → SaveVideo`；脚本 `D:\AIWorkflow\ComfyUI_H3\face_restore.py`；**5s 片 65 秒出**。风险＝塑料感 / 逐帧闪烁（待用户判）。
- **④ T8 Face Refine Window（H3 原生，正路但重）**：`06-face-refine/2026-09-05_H3_Face_Refine_Window_Manual_Review_Advanced_EXP.json`——**一次只修一个连续时间窗**（源片整理成单镜头 24fps，填 0 基闭区间帧号如 `0-23`），给它源片 + **两张清晰身份参考图** + 模型/LoRA/VAE；默认只预览，人看完再把 decision 改成接受。EXP、必须人审、作者明确「**不要批量自动接受**」。
- **⑤ 加内存上完整版 INT8（34G）**——天花板根治（需 64GB 内存）。
- **⑥ 脸关键的镜走云端**（Seedance / 可灵）——兜底。

**⚠️「用硬盘虚拟内存顶内存不够」＝不可行**：ComfyUI 是动态显存加载，**每步都要把权重从内存搬进显存**；权重一旦落进页面文件就变成每步读盘 → 慢几十到上百倍、基本卡死。**先兆已现**：15s 那次空闲内存只剩 1.8G，光"模型载入"被换页拖到 ~14 分钟。页面文件还必须开在 NVMe（开 E: SATA 更惨）、且伤 SSD。**结论：换页只解决"能不能启动"，不解决"能不能用"；要用完整版只能加内存。**

**H3 二次采样（T8，均 EXP）**：① `13-latent-upscale`＝**学习型潜空间放大 + 二采**（低清 4 步 → 学习型 3D 放大 → 高分 4 步；需另下 `models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16.safetensors`；**学习型非插值 → 能给真细节**；作者 4060Ti 4+4·124 帧 = **1572s**，历史 4+3·736×416→1472×832 = 627s）；② `28-progressive-sampling`＝6+2（同一放大模型，小画幅采 6 步→放大→再采 2 步，作者称省 ~37–38% 端到端时间）。**定位＝"用算力换高分辨率"的省时路径，不是超越单遍高分的画质魔法；且二采省算力、不省内存。** 坑：二采工作流对 LoRA 有特定契约——缺 PEFT alpha 处理的 `_comfyui` LoRA 会被放大 ~16 倍造成"整幅融化"。

**⚠️ 处理顺序铁律（2026-09-13）：超分在前、修脸永远放最后。** 超分放在"修脸之后"＝让通用超分模型再处理一遍刚修好的脸，容易把修脸成果**重新弄软／加人脸伪影**。正确顺序＝`生成 →（可选）整体超分 → CodeFormer 修脸 → 头段平滑`（超分后脸更大，CodeFormer 检测/修复反而更准；修完的脸是终版，不再被后续处理碰）。另：**后期超分只是"化妆"（放大+猜细节），补不出真结构**——要真细节只有二次采样 / 完整版模型 / 云端。

**用户验收（2026-09-13）**：CodeFormer 结果「**清晰很多**」；跳动只在**开头约 1 秒**；加「头 1s 不修 + 0.8s 平滑过渡」后用户「**可以的，这个效果看起来好点**」→ **这条清晰度链定型**并写进规范 §10。用户对 1344×768 的判定＝「**768 能救回来一点，不过作用还比较有限**」。用户对硬件取舍的结论＝「**果然在硬件限制下二者不可兼得**」（我的说法：不是不可兼得，是**得挑一种货币买单**——内存／时间／钱，外加免费的"构图让脸占更大像素"）。

**2026-09-14 运维补充（实测踩到，两条都容易误判）**：
- **"把片段切得更细"治不了逐帧跳动**：跳动来自 CodeFormer 的**逐帧独立修复**（帧与帧之间没有连续性约束）——**粒度不是原因**，切更细也白搭。真解只有两条：① 头段不修 + 平滑过渡（跳动只局限在头段时够用）；② **T8 Face Refine Window**（H3 整段重生那段时间窗，天生连贯）。
- **删掉大模型文件后空间不会立即到账**：ComfyUI 会 mmap 住**载入过**的权重文件，进程不松句柄时 Windows 只标记删除、不还原空间。本次删混元 6 件（~27.8G）后**只先释放了 8G**，**关掉 8189 实例后一次到账（44G→62G）**。所以看到"删了没释放"≠ 删除失败，先关对应实例再看。

**⚠️ T8 控制面盘点（2026-09-14 实查；此前只用了十来个节点）**

T8 包实际注册 **335 个 H3 节点**（`/object_info` 实查）。其中一整族是**控制 / 续写 / 修复**，包自带 `docs/` 34 篇验证文档：

| 能力族 | 代表节点 | 包内验证结论 |
|---|---|---|
| 轨迹控制 | `TrajectoryControlPlan/Render/Checkpoint/Probe` | 未查到 |
| Fun 控制 | `FunControlApply/Loader` | **人审未通过（原话"没有控制住"）**；ControlNet 模型本地未装 |
| 深度参考 | `examples/workflows/04-long-video/…H3_Depth_Ref2VA…json` | **人审未通过**（起幅继承灰度轮廓）；预处理器 ReShot / Video-Depth-Anything 只做了"研究目录隔离安装"、**未装进本机 Comfy** |
| **latent 级续接** | `NativeLatentContinuationConcat` / `NativeLatentTimelineConcat` / `NativeLatentCheckpointSave|Load` / `NativeLatentResumeManifest` | 未查到。**跨段 latent 状态延续 —— "续写"里最深的一层**（比像素级重编码强） |
| 视频外扩/续写 | `VideoOutpaint*`（含 `ContinueCandidate`） | 见 `docs/H3_VIDEO_OUTPAINT_PLAN.md`（81KB） |
| 长视频编排 | `LongVideo*`（Orchestrator/Planner/ContextSave\|Load/ColorMatch/SeamDrift） | 两段 8 秒已验证 |
| 分段修复 | `SelectiveSegmentRepair*` / `RepairSegmentSelect` | 未查到。**只重做失败段** |
| 原生修脸 | `FaceRefine*`（Window/Plan/Parity/QualityGate…） | `FACE_REFINE_ADVANCED_VALIDATION.md`；我们当时却自己手搓 CodeFormer |
| 原生超分/插帧 | `LearnedLatentUpscale` / `DLSSNR*` / `FlashVSR*` / `RealBasicVSRRestore` | 有独立审计文档 |

- **必读边界文档**：`docs/DEPTH_REFERENCE_EXP.md`（深度/Fun 的失败证据）+ `docs/LOCAL_RELIABILITY_SCOPE_20260913.md`（作者反复强调"**测试通过 ≠ 人审通过**"）→ **节点名称不等于能力，用前逐条冒烟**。
- **⚠️ 上表里标"人审否"的两条（深度/Fun）必须带上来源限定**（2026-09-14 用户追问后核实）：① 那些是**上游 T8mars 仓库的验证记录**，随克隆而来（git 查证：T8mars 2026-09-13 12:49 提交，本机工作区无改动），**不是我们在自己素材上跑出来的** —— 文中"用户"是作者的评审人；② 证的是一次**特定配置**的尝试没过评审（Fun 用 20 步/s0.7/e0.75，官方 demo 用 40 步/1.0；文档自己写"**不是已确定的失败根因**"），**不等于路线技术不可行**。→ 定位＝**高价值导航信息，不是判决书**；真要按某条路走仍须自己验一次。
- 那些结论是**包作者在其测试环境**得到的，不是我们在自己素材上的结论。
- **姿态读取工具本机已有**：`SDPoseKeypointExtractor` + `SavePoseKpsAsJsonFile`（提骨骼落 JSON）→ 可做"生成结果 vs previz 骨骼"的姿态误差度量。
- 工作流模板在 `custom_nodes\comfyui-minimax-h3-audio-T8\examples\workflows\`（16 个分类：04-long-video / 06-face-refine / 07-motion-detail / 13-latent-upscale / 14-prompt-relay …）。
- **2026-09-14 冒烟侦察结论（三条，改了计划）**：
  - **H3-World 本机跑不了**：`26-h3-world` 要求**完整 34G 底模**（`minimax_h3_fl2va_int8_convrot`，我们只有 pruned 版）＋另下 `t8star/Minimax-H3-World-Comfy` 的 LoRA；32G 内存上不去 → 这条（唯一过了盲测的交互控制）应短期划掉。
  - **「视频扩画」≠ 续写**：`27-video-outpaint` 是**空间扩边**（改画幅，joint_decode/preserve_source 两模式），**不需要新模型**；真正的**时序续写**在 `04-long-video\` 的 4+4 两段（`accepted_picture_low_context_v1`：上一段末 39 帧当下一段 LOW 参考），但要另下 `latent_upscaler_3d_fp16` + `turbo_v4_step600_ema_B`。
  - **出图侧 ControlNet 已打通**（`tools\controlnet_smoke.py`）：canny 48s / pose(DWPose) 68s 两条腿都出图。**关键坑：FLUX ControlNet Union 必须给 `ControlNetApplyAdvanced` 接 `vae` 输入**，否则 KSampler 报 "This Controlnet needs a VAE but none was provided"。depth 腿需 `depth_anything_v2` 权重（本地没有）。

**出图侧 ControlNet：2026-09-14 曾"备而未用"，2026-09-23 已正式启用**（`engine/comfy/flux_controlnet_lineart_api.json` ＋ `tasks.py` 的 `control` 任务 ＋ 工作流 `previz_control.yaml`，LoadImage→`CannyEdgePreprocessor`→`ControlNetLoader`→`FluxUnionControlNetMode`→`ControlNetApplyAdvanced`）。**实测：灰模锚→Canny→FLUX，强度 0.8，裁切构图与等距灯带都锁得住**——这是"文字拧不动剪影与构图、锚一张就动"的硬证据（详见 [[feedback-local-first-generation]] 末段）。⚠️ 别再去新建这条链，引擎里早就有。

---

**★ 中文对白 · 竖屏 · 风格偏移（2026-09-15 实测，《对门》第 2 批）**

- **H3 能出中文对白——原"未验证"项现已验证可用**：fl2va 首帧 I2V，提示词【声音】段写「女子用很轻、平直的普通话语气说一句短促的话：『能借点水吗』」→ 音轨里**真的有这句话**。抽音轨转写（`py -3.12` + `faster_whisper`(1.2.1) 的 `base` 模型，`HF_ENDPOINT=https://hf-mirror.com`）得到「能切点水吗」。**发音准不准只能人耳判**——机器转写分辨不了"借/切"是模型咬字偏还是转写误差，别拿转写结果当判决。
- **⚠️ 它会把台词烤成字幕烧进画面**：提示词里写了具体台词，H3 就同时产出 ① 语音 ② **字幕（白字黑边、画面中下部）**。这**违反项目那条"AI 一律不产字、字形全部后期叠"的铁律**（见 [[feedback-video-quality-standards]] 第 14 条）。但实测**字形正确、无乱码**。
  - **这是个必须交用户拍的二选一**：要原生对白（**口型天然同步**，这是后期 TTS 花多少钱都补不回来的，也是音视频联合生成的最大优势）→ 接受字幕版式由模型定、**每镜可能不一致**；要字幕版式统一 → 提示词里**不写台词** + 后期 TTS + 后期叠字 → 代价是**口型错位**。2026-09-15 用户试听后选了前者。
- **竖屏可用**：`--w 576 --h 1024` 实测通过。**9:16 且两边都是 32 倍数的解**＝`宽=288n / 高=512n` → 576×1024 / 864×1536 / 1152×2048（**别去凑 768×1344，那个不是 9:16**）。
- **最短 124 帧**：训练区间 124–362 是真的——**3–4 秒的镜也得先出 124 帧（5s）再剪**，出不到更短。
- **5s 镜基准**：576×1024 / 124 帧 / 8 步 + turbo8step / T8 双时钟 + 音频 = **185s**（与规范 180s 吻合）；8 镜（124/124/124/192/144/124/144/124 帧）约 30–40 分钟。
- **⚠️ H3 会把"写实 3D CG 立绘"往实拍方向拉**：同一个首帧，CG 质感越精致这个偏移越明显（脸变圆润、CG 精致度掉、像实拍柔焦）。**两层必须分开归因**：① 像素糊 = 分辨率不足（576×1024 相对 1440×2560 首帧**掉 84% 像素**）；② 五官气质变了 = **模型风格倾向，跟分辨率无关**（H3 主要吃实拍视频训练）。对策＝分辨率提到 864×1536 ＋【风格与光影】写死"保持 3D 渲染的渲染感与精致度、不得转成真人实拍、不得柔焦/油画涂抹/塑料感"（同 [[feedback-video-quality-standards]] 第 35 条的"具体特征 + 不得…"三件套）。**两层都压不住 → 说明这个模型不适合该画风，换通道（要花钱，先把价算给用户再问）。**
- **批量跑批的观测坑**：Python 输出重定向是**块缓冲**，中途读 stdout 常常是空的——**别把"看不到进度"误判成卡死**，去看输出目录有没有新文件更可靠。

---

**★ 2026-09-18 复盘：一批四条全废，根因是"接线错误"不是模型（仙戮_双生项目）**

用户反馈「**这角色画风都变了，打斗也不如原视频丝滑了**」。查下来四条 ref2va 全废，三条硬错误，**全都零成本可修**：

1. **`ref_images` 槽位配错，身份锚整批串了。** 从 `D:\AIWorkflow\logs\workflows\h3_ref2va_video_<run_id>.log` **第一行 `args=`** 读出实际参数（⚠️ 批次 `manifest.json` 和 `status.json` **不存** ref_images / 宽高，只有这行日志有），四条 run 的图序是：
   - shot1 `s03,s01,s01,s01` / shot2 `s03,s01,s02,s01` / shot3 `s03,s01,s03,s01` / shot4 `s03,s01,s04,s01`
   - md5 实测 `wfref_2_s01 == wfref_3_s01 == wfref_4_s01`（同一文件塞三个槽）、`wfref_1_s03 == wfref_3_s03` → **四个槽实际只有两三张不同的图**，多视角身份锚完全没生效。
   - 更要命：s01–s04 **全是白玖璃**（狐耳＋紫金眼罩），**薇拉的真图 s05–s07 一张都没挂**，而提示词写 `<Picture 2> 是薇拉`、Picture 2 却是白玖璃全身像。模型照图认人（"参考图永远赢过文字"），于是三条薇拉镜要么凭空生成、要么长成白玖璃。
   - ⇒ **挂多锚点前必做两件免费的事**：① 按 **md5 查重**（同图占多槽＝白占额度还误导模型）；② **逐槽核对"图里画的是谁"与提示词 `<Picture N> 是X` 是否一致**。这两条一分钟就能查完，本次白烧四条 ≈ 31 分钟。
2. **没有画风锚，而且锚点之间画风自己打架。** s01 大红底／s02 大青底／s03 品红底／s04 暖橙火星，景别从全身、背影大全景到脸部大特写混着挂；目标片是**冷灰蓝低饱和电影调**。无音配方里 Picture 4 位置本来是专职画风锚，这次被一张重复的 s01 占了。提示词还**整块缺【风格与光影】和【保持一致】**（只有五块）→ 等于没有任何东西钉住渲染风格。
3. **【事件脚本】又是自己推的、不是原片实际动作——第二次踩。** 老提示词写"薇拉肩甲被击中碎裂、闷哼一声后退"，原片对应段实际是**两人从左右对冲→中心炸白热核→紫色能量展开成蝶形双翼→收成竖直光柱→两人被弹开对峙**，**根本没有肩甲、没有单人受击**。同《逐玉》那次"采样 12 帧自己推"是同一个坑。⇒ **复刻类镜头的【事件脚本】必须从原片该段密读逐拍抄出来**（每 ~0.5s 一帧、拼成节拍条看），不能凭采样印象写。

**"不丝滑"的归因（先测量、推翻了一个假设）**
- **帧率不是原因**：原片实测 **24fps**（720×1280 / 30.05s / HEVC / 带 AAC），成片也是 24fps——我原本怀疑 24 vs 25/30 的差，量完直接排除。
- 剩下的真因：① **这批完全没挂 `ref_videos`**（四条都只有图），而"运镜＋表演节奏能被复刻"是 2026-09-15 唯一实测出来的那条路；② **8 步 turbo LoRA 是为慢动作调的，快动作正是它的短板区**；③ pruned INT8 上限。
- 原片是**外部 AIGC 平台的成片**（元数据 `comment: vid:v0269cg...` + `AIGC ContentProducer 001191...`），不是本地或自家云端出的 → 追它的运动质量＝追另一个模型，本地有天花板，这点要跟用户讲明。
- 排查手法：`/history` 的 `prompt` 字段能读回**节点实际输入**（含 `ref_image_size`、每份 `LoadImage` 的文件名、完整提示词），比日志更硬。

**实测数据补记**
- **864×1536 竖屏（真 9:16）实测**：124 帧 / 8 步 / 4 图 / `ref_image_size=max` / ref2v turbo LoRA / T8 双时钟 + 音频 ＝ **553s**；同参数**再加一段参考视频（102 帧）＝ 1032s**（≈1.9×）。⇒ 参考视频在竖屏高分档的加价比 1024×576 那档更狠，排期要按 **17–18 分钟/条** 估，别拿低分辨率基数外推。
- **参考帧会被静默截齐**：102 帧按 `17n+5` 截到 **90 帧，丢 12 帧（约 0.5s 收尾动作）**。复刻类镜头若收尾动作关键，切段时就按 17n+5 切，别指望后处理补回。
- **引擎模板的参考图槽数＝硬上限 4**：`engine/comfy/h3_i2v_ref2va_api.json` 只有 `__REF1..4__` 四个 LoadImage 占位符；**挂 5 张＝第 5 张被静默丢弃，挂 3 张＝`__REF4__` 以字面量提交给 LoadImage 直接失败**。另外**该模板不支持 ref_videos**，要挂参考视频当时只能走 `run_h3.py`。
- **⚠️ 双真源的代价＝参数与归档双双失踪（2026-09-19/20）**：`h3_ref2va_video.yaml` 自称主力通道但历史只跑过 5 次；9-15 那批与 9-19 的 A/B 全走 `ComfyUI_H3/run_h3.py` 裸脚本 → **不产生 `args=` 日志、不进 `E:\图像影音资源池` 批次归档**，参数只存在于当轮对话里，`ComfyUI_H3/output/` 堆了 31 条 49.9MB 未归档（同一份还存两遍）。⇒ **出片一律走引擎**；确要用裸脚本兜底，事后必须手工补一份参数记录（分辨率/帧数/步数/seed/逐槽锚点/耗时）。（2026-09-20 已在引擎侧补：提示词 `prompt_file` 入口、台账逐步落盘、跑前自审闸 `tools/check_preflight.py`；用前先看 `workflows/selftest_gates.yaml` 的自测口径。）
- **YuNet 量脸实测（2026-09-20，可作脸锚判据参照）**：原片裁的脸锚 **189px**、角色卡裁的造型锚 **33px**（正常，它不当脸锚用）、9-18 那批文生图关键帧 s01 仅 **128px**。⇒ ~300px 那条线是**启发式、不是硬界**；189px 这一档实测仍能保住身份，报给用户时按"偏弱、可能锁不住"措辞，别说成"不能用"。
- **768×1344 / 124 帧 / 4 图 / `ref_image_size=max` / 8 步 + ref2v turbo LoRA / T8 双时钟 + 音频 ＝ 462s（7.7 分）一条**（竖屏 9:16-ish 档的新基数；此前 236–246s 那个数是 1024×576 三/四锚点）。
- 挂 `ref_videos` 的"5s 镜 ≈ 15 分钟"是在 **1024×576** 测的，**别直接乘到 864×1536 上**——像素和参考 token 双重超线性，实测可能 30–50 分钟/条。**排期前先用同分辨率跑一条拿真基数**，别拿低分辨率基数外推（本次差点按 23 分钟的错估承诺给用户）。

**取片/预览坑**
- 走引擎的任务产物会被 `relocate()` 搬进 `E:\图像影音资源池\<项目>\批次\<run_id>\video\`，**ComfyUI 的 `/view?filename=…&type=output` 之后会 404** → 预览和取片一律走归档路径，别用 ComfyUI output 地址。
- 判"这条素材是谁出的"看容器元数据（`comment: vid:*` / `AIGC ContentProducer`）比猜快。

---

**★ 2026-09-20 外部资源补记（GitHub API 核实，均未安装/未跑）**
- **`MiniMax-AI/MiniMax-H3`（8.9k★，建 2026-07-30，push 08-15）＝ H3 官方开源权重仓**——本机一直跑 pruned INT8（20.9G），清晰度阶梯最上层"完整版"的**官方源**在这里；配套还有 `MiniMax-AI/cli`（2.1k★，push 09-19，文/图/视频/语音/音乐官方 CLI）与 `MiniMax-AI/MiniMax-MCP`，**云端兜底别再手搓 REST**。`unslothai/unsloth`（76k★）描述明列支持 MiniMax-H3 训练，可作 LoRA 路线候选（此前只有 `neng320/minimax-h3-local-deployment` 那条推理侧方案）。
- **"把台词烤成字幕"现在有本地后处理解**：`YaoFANGUK/video-subtitle-remover`（13k★，push 2026-06-30，硬字幕/文本水印去除、**不损分辨率、无第三方 API**）；补洞修补类走 `sczhou/ProPainter`（7k★，有 ComfyUI 节点包 403★）。→ 意味着"原生对白 vs 版式统一"那个二选一**不再必须二选一**（可要原生对白＋后期擦掉烤进去的字）。未实测擦除质量。
- **动作/画质类**：文本→3D 人体动作可接 ComfyUI 的是 `Tencent-Hunyuan/HY-Motion-1.0`；补帧 `hzwer/Practical-RIFE`（MIT，**只补帧、救不了动作不连贯**）；视频超分候选 `OpenImagingLab/FlashVSR`（1.9k★，16GB 可行性未测）。
- **许可红线**：`sczhou/CodeFormer`（在用）是**非商用研究授权**——片子要商用/出海必须换方案。详见 [[script-storyboard-animation-tools]] 2026-09-20 段。

## ★步数/LoRA 不影响运动量（2026-09-21 用 09-13 的存档重测，零 GPU 成本）

2026-09-13 那批 8-vs-20-vs-4 步对照片**还在盘上**（不在 output\，在 `E:\图像影音资源池\无音\素材\`）：`h3_shot04_test.mp4`＝20步无LoRA、`h3_shot04_turbo8.mp4`＝8步+turbo8step、`h3_shot04_turbo4.mp4`＝4步，同首帧同提示词同 seed、362 帧。用光流尺子量：flow_mean **0.939 / 0.946 / 1.082**，差 0.7% 在噪声内。

→ **"步数蒸馏 LoRA 压住了运动"这个假设是错的，别再拿步数解释"画面不动"**；工程旋钮（步数/LoRA/分辨率/帧数）对动态量基本无关，同配方下动作镜能到 0.94、说话镜只有 0.17–0.44，**差的是内容不是配方**。附带一条：**4 步版运动量反而最高但画面有缺陷已弃用 → 运动量 ≠ 画质，不能用它当质量指标**。
⚠️ 边界：只测了一个镜、一种内容（动作镜）。要在说话镜上钉死，加一条"同镜 20 步不挂 LoRA"即可（约 20 分钟），当前判断是不必。
**通用教训：提"要不要再跑一组实验"之前，先查这批片子是不是早就存在**——这次答案躺在归档里 8 天，量它花了一分钟，而原计划要烧 40 分钟显卡。

## ★2026-09-21 烬骨辞第2批：fl2va＋尾帧的排期实测 ＋ 两条原生对白/自审闸的硬规律


- **fl2va（首帧锁，不挂 ref_images）864×1536 / 124 帧 / 8 步 / T8 / 原生音频 / 带尾帧 = 563 s → 4.54 s/帧**。19 镜 2980 帧的整批 ≈ **3.6 小时**（不含失败重做）。对比既有数：ref2va 4图/max 同长度是 553 s（864竖屏）或 462 s（768×1344）——**fl2va 并不比 ref2va 便宜多少，但省掉了挂错锚点的整类风险**（身份已经烘在首帧像素里，槽位无从配错）。
- **★原生对白＝谁在画里就让谁说。** 源剧本把沈清辞的「今日碎玉，断情！」标在分镜13，而 13 的画面是**男主僵住的特写**——照抄进 13 的提示词，H3 会让萧烬言开口替她说。**台词必须跟着"画里那张嘴"走，不是跟着剧本的标号走**；标错时改画面归属（把这句挪到有她脸/或无脸的镜）而不是硬挂。无脸镜（手部/碎片）挂台词＝画外音，能出但对口型无处可对。
- **★跑前自审闸 `check_preflight.py` 在 fl2va 上的两个假阳性，写提示词时就得绕开**：① 统一【保持一致】里写"全片只有一个女主（沈清辞）和一个男主（萧烬言）"→ G7 判「**点名角色却没挂参考图**」**直接 error 拦死提交**（fl2va 本来就不挂 ref，身份在首帧里）→ 提示词一律改说"**同首帧的男子/女子**"，别出现注册过的角色名；② 统一段"动作幅度小而慢"会把砸玉、扣腕这类**关键一拍压成慢推** → 写成"**除【事件脚本】明确写出的那一拍外**幅度小而慢"，并在该镜专属块里写明"这一拍要发力、不受该约束"。
- **`python_embeded` 才有 insightface**：`py`（默认 3.14）没有；`py -3.11` 因**中文用户名**报 `Unable to create process`（路径里的"若水"变 `??`）。量脸一律走 `D:\AIWorkflow\ComfyUI_H3\python_embeded\python.exe`。跟 H3 出片并行判分时加 `--cpu`（CPUExecutionProvider），别跟 11.3 G 的显存抢。

## ★2026-09-21 同日补：客户端"超时"≠渲染失败 ＋ 长序列在 16GB 上的速度悬崖

- **⚠️⚠️ `run_h3.py` 报 FAIL 先去看 `/queue` 和输出目录，别信它。** ComfyUI **执行长任务时事件循环被占死，`/history` 这类 GET 会 60s 超时** → 客户端抛 `TimeoutError` 退出、日志写 FAIL，**但 GPU 一直在正常渲**（本次镜8/9/10 全被判 FAIL，实际 `running 1 / pending 5`）。已把 `http_json` 改成 **GET 无限重试（10s 间隔）、POST /prompt 不重试**（提交重试＝同一镜排两次队，是更坏的失败）。
  - **副作用要知道**：客户端中途死掉，ComfyUI 仍会把片子写成**默认名 `h3_i2v_000NN_.mp4`**，不会拿到 `--out` 的 `jinguci_GNN.mp4` 名字（改名是客户端干的）。恢复＝按 **帧数＋mtime 顺序**对回镜号；两条同帧数的镜用"有没有脸"区分。
- **长序列速度悬崖（16GB 实测，排产必看）**：同为 fl2va/864×1536/8步/T8/音频，**124 帧 ≈ 4.3–4.8 s/帧，226 帧 = 13.1 s/帧（G03，2960s 一条）**——不是线性外推，是**跨过显存驻留阈值后开始换页**。显存占用从 11.3G 涨到 15.6G（TE 14956MB + VideoVAE 4965MB + DiT 19995MB staged 动态换入换出）。⇒ **300 帧级（13s+）的镜在 16GB 上要么拆段、要么降分辨率**，别按短镜的 s/帧 给承诺。这与旧结论"32GB 内存是长镜硬瓶颈"是同一堵墙的两面。
- **fl2va 的 `--last-frame` 在批跑里工作正常**（镜5/8/11/14 四条夹尾帧），G14 端点贴合 0.986。

## ★2026-09-22 太空战批：横屏 fl2va 首帧链基数 ＋ 三条模型行为

- **横屏 1344×768 / fl2va 只挂首帧 / 8步+turbo8step / T8 / 原生音频 / seed 42**：192帧=634s、141帧=412–434s、124帧=346s ⇒ **约 3.3–3.5 s/帧**，六段 931 帧合计 **48.1 分钟**。比竖屏 864×1536（4.5 s/帧含尾帧）便宜，与 ref2va 横屏长档 3.95 s/帧 同量级。**排 8 秒级横屏镜按 10–11 分钟/条估。**
- **⚠️ 模型会自己补大尺度背景天体，且一旦入画就被后续段继承**：主炮横扫段受击区凭空多出一颗类地行星，接下来两段把它当既有设定接着画。⇒ 背景里"有没有星/行星/卫星"要在提示词里显式钉死或排除，否则改不回去。
- **⚠️ 颜色词压不过首帧像素**（第三次确认"参考图永远赢过文字"）：要塞段提示词写 `obsidian-black`，实际渲成偏白灰——首帧是浅灰装甲，文字追不上。要换色只能换首帧，不能靠加形容词。
- **快速横移（`tracks/pans with large amplitude at fast speed`）会带出运动模糊糊帧**，且糊的是整段最贵的一拍；甩镜类运镜要么降幅度要么在质检里预期到糊。
- **首帧链式继承是跨段主体一致性的唯一手段**：战舰/要塞这种"整段主体"不能各段独立文生图，只能把前段**实际末帧**当下一段首帧（本次 T2–T6 全这么接，六段主体造型没崩）。合片时只去掉后五段各自重复的第一帧（5 帧），别做变速补帧。
- 相关项目状态见 [[project-spacewar-shortfilm]]。

## ★2026-09-24 引擎 h3_i2va_video 补充：默认横屏坑 + 竖屏 243 帧基数

- **⚠️ `h3_i2va_video` 默认 `width=1344 height=768`（横屏！）**——竖屏出片必须显式 `--set width=864 --set height=1536`；投错时 preflight G5 会 warn 长短边比。已停在 H3 的 run 参数改不了：`--deny RUN_ID H3 --note 原因` 后**重投**（内容变了会当新关口重新上报）。
- **fl2va 竖屏 864×1536／243 帧／8步+turbo8step／带音频 单跑 = 1325.7s（≈5.5 s/帧）**——介于 124 帧 4.5 s/帧与"226 帧 13.1 s/帧"之间；243 帧单跑没触发悬崖，反推 226 帧那个 13.1 很可能含并发争抢，**悬崖起点别按 226 帧报**。
- 单条 FLUX 快速出图工具：`D:\AIWorkflow\tools\comfy_run.py --workflow engine/comfy/draft_flux_api.json --set "PROMPT=..." --n 3 --prefix p --out <dir>`（占位符 `__PROMPT__`/`__SEED__`；`--set` 不拷文件进 input 目录，只有 `--ref` 会拷）。
- 批准/续跑一律带 `--project`（gate key 含项目名，缺了永不匹配）；A/B 两条 run 可同时 resume，ComfyUI 侧自动排队串行。
- **竖屏 864×1536／124 帧／8步+turbo8step／带音频实测 513.9s（≈4.1 s/帧）；196 帧 ≈ 16.5 分钟**。多条 run 可同时提交，ComfyUI 自动串行排队。
- **引擎侧 fl2va 模板仍只接 first_frame**（`h3_i2v_fl2va_api.json` 节点 7 无 last_frame 输入），run_h3.py 的 `--last-frame` 可用。要在引擎里两头夹：video task 的 `ref_images→__REF1..n__` 拷贝机制是通用的，**建一个第二 LoadImage(`__REF2__`)→last_frame 的双参考变体即可，不用改 tasks.py**。

## ★2026-09-21 武打 LoRA 兼容性边界

- **未发现可直接加载到 MiniMax-H3 的成熟武打／连招专项 LoRA。** 现用 `turbo8step` 是加速 LoRA，不提供动作知识；SDXL／FLUX 的武侠、格斗 LoRA 只能用于生成更可靠的武术关键姿态静帧；Wan、HunyuanVideo 等视频模型的动作 LoRA 权重结构不兼容，不能塞进 H3。
- 因而 H3 动作戏的有效控制单位仍是：一小段明确的起势→接触/落空/格挡→收势，配合连续关键姿态或骨骼条件、短段 `fl2va` 首尾帧。不要把“有武打 LoRA”误报成“能直接改善中间帧连招”。

### ★2026-09-27 实查：全机只有 H3 那条线在挂 LoRA，图侧一条都没接

- **生产链路里唯一挂 LoRA 的地方＝`engine/tasks.py` 的三个 H3 profile**（`stable_t8`／`preview_t4`／`fight_fast8`＝turbo8step@1.0 → `Bunny_weapon_combatV1`@0.5）。**SDXL／FLUX 侧没有任何在跑的工作流**：盘上有 SDXL LoRA 四件（自训 `faceA_sdxl_v1`、`ip-adapter-faceid-plusv2_sdxl_lora`、`国风_明制SDXL_v1`、`add_details`）＋ FLUX 三件（`faceA_flux_v1`、`East_Face_Flux`、`RealSkin_Flux`），但引用它们的只有 8–9 月的测试旁支（`engine/comfy/sdxl_faceid_ref_api.json`、`tmp/sdxl_img2img_test.py`）。⇒ **走"图侧 LoRA 锁一致性"不是换个 LoRA 文件名，是要从训练集＋工作流新建整条线。**
- **⚠️ `wushu_spatial_physics_clean_3000_pruned.safetensors`（09-26 12:00 落盘，155 MB）在 `D:\AIWorkflow` 的 .py/.json/.md 里零引用**——只在 loras 目录躺着。记忆里"spatial-physics 0.3"是 fight 链的一环 ⇒ **很可能是漏接的，用前先问，别默认它在生效。**
- 两个 ComfyUI 实例（H3 的 `ComfyUI_H3/ComfyUI` 与 E 盘 portable）**共用同一个 `D:\Models\ComfyUI\loras`**（都是 junction 指过去）⇒ 在那里放/改名 LoRA 会同时影响两条线。

## ★2026-09-21 同日补：官方提示词规范找到了 ＋ ref2va 横屏长档基数 ＋ 闸与格式的冲突

- **★H3 官方提示词规范就在权重仓里**：`MiniMax-AI/MiniMax-H3` → `skills/h3-prompt-writing/`（`SKILL.md` + `references/base-en.txt` 15.8KB + `references/ref-en.txt` 23.6KB），已镜像到 **`D:\AIWorkflow\ComfyUI_H3\prompts\official_h3\`**；同仓还有 8 个题材配方 skill。**完整字段名、片内 `[Shot N] At MM:SS.mmm` 多镜切点、运镜受控词表、`<Subject N>`/`retention_analysis` 规则见 [[reference-minimax-h3-official-prompt-spec]]——必读，别再拿中文十块喂 H3。**
- **⚠️ 跑官方英文六段格式必须 `--skip-preflight`（2026-09-22 已放宽）**：`tools/check_preflight.py` 编码的是中文十块（G7 要求【声音】等），英文六段会被整批 error 拦死。**现在闸按 `prompt_kind` 分派（image / video / h3_i2va），首帧三字段路线可带闸跑**，详见 [[reference-minimax-h3-official-prompt-spec]] 末段。
- **G3 会用 `<图>.anchor.json` 的 `character` 核对提示词里的 `<Picture N> 是X`**：写描述性别称（"展翅者"）→ 报"槽位冲突"；sidecar 没有 `character` 字段（如纯影调锚 `p4_grade.png`）→ 报"职责句而非点名身份"（warn）。⇒ **提示词用 sidecar 登记的真名**。
- **ref2va 横屏长档新基数**：**1344×768／243 帧（10.125s）／8 步／4 图／`ref_image_size=max`／ref2v turbo LoRA／T8 双时钟＋原生音频＝960s（3.95 s/帧，16 分钟一条）**。对比 864×1536/124帧＝553s、768×1344/124＝462s、1024×576/362＝742s。⇒ **横屏 1344×768 的 s/帧 反而低于竖屏 864×1536**（像素更少），排 10 秒级横屏打戏按 **16–18 分钟/条** 估。
- **帧数仍要 17n+5**：10 秒取 **243**（不是 240）。

## ★2026-09-21 打戏验证批：`--no-audio` 速率基准 ＋ 自审闸把【声音】列成核心分块

- **fl2va `--no-audio` 864×1536 / 124 帧 / 8 步 / turbo8step / T8，无尾帧、不挂 ref**：五条实测 **4.08–4.55 s/帧**（542–565s 一条），**5 条整批 45 分钟**。⇒ 无音频比带音频（563s）只省一点点，**别指望关音频大幅提速**；排期按 9–10 分钟/条估。
- **⚠️ 跑前自审闸把【声音】算核心分块：缺＝error、直接拒绝提交 GPU（0 秒失败、不烧卡）**。本次五镜提示词只写了六块（场景与环境／主体与关系／事件脚本／镜头／风格与光影／保持一致），五条**全在 0 秒被拦**：`[preflight:G7][ERROR] 缺核心分块: ['声音']`。补上【声音】块后通过。
  - **不出声轨也要写【声音】块**——它同时是给画面的节奏提示（什么响、响几下、什么时候归于无声）。应急绕过＝`--skip-preflight`（风险自担，别默认用）。
  - `[preflight:G3][WARN] 没解析到 <Picture N> 是 X 身份声明` 在 fl2va 上是**正常噪音**（本来就不挂 ref），只是 warn。
- **裸调 `run_h3.py` 时自己补参数留痕**：批跑脚本把每条完整命令行写进实验目录 `calls.log`（`--theme` 只进自审日志、不进批次归档），否则参数只活在对话里（同 09-19 那条双真源的坑）。
- **火山 `+gen` 显式 `--model ep-*` 需要控制面 SSO 解析**：SSO 掉时 `--model ep-...` 报 `GetEndpoint requires ... SSO STS`，**去掉 `--model` 走 profile 默认照样出图**（数据面 apikey 通道）。`--output-format png` 不保证落 png——实测仍回 `ark-gen.jpeg`，脚本要按 `.png/.jpg/.jpeg` 三种找。`--dry-run` 会打印调用计划但**不联网、不校验服务端权限**，不能拿它证明某模型真能调通。

## ★2026-09-24 剑来 v4/v5：段数与总长绑死、窄带动作天花板、推镜与身份的兑换、别引擎提示词要编译

- **★段数＝总长下限的乘数（排片前第一件事）**：G6 硬闸 `H3_MIN_FRAMES=124 / H3_MAX_FRAMES=362 @24fps`（`tools/check_preflight.py` L34–36），**124 帧＝每段最短 5.17 秒，出不了更短**。⇒ 总时长下限＝段数×5.17s：5 段 25.9s／6 段 31.0s／7 段 36.2s／8 段 41.3s。**用户要"30 秒一镜到底"时，段数上限就是 6，拆到 7–8 段在时长上根本不成立**；本轮用户改口"延长到 36 秒"才换来 7 段名额。排段前先拿这条乘一遍，别写完分镜才发现装不下。
- **★多段拼片不是"一镜到底"**：fl2va 单条上限 15.08s，30s+ 必然拆段。能做到的最好程度＝**每段首帧抽上一段成片末帧（同源链）＋拼片 0.15s 淡接**，观感连续但不是无缝。用户提"一镜到底/无缝衔接"时先把这句讲明白，别承诺。
- **★窄带动作在全帧度量下天花板很低，且换 ROI 也救不回来**：一条"中央一根光柱在长粗"的镜，动作只占画面窄条，四周是静止空天与云底 → 全帧帧间差 mean 只有 2.27；**按中央光柱带（x 33–67%）重量是 2.51，而全画幅翻涌的 spectacle 段是 6.67**。⇒ 2.5× 的提升是真的、事件确实发生了，但它**天生到不了 spectacle 量级**。教训：**别用"度量方式偏了"给没达标的数找台阶**（我第一反应就是找这个解释，换尺子复量后自己推翻，见 [[feedback-evidence-loop-trap]] 同族⑦）。要那一档观感只能改内容（让整幅都在翻），不是改算法。
- **★推镜＝用身份稳定性换运动量（实测）**：同一张锁脸首帧（豆包 ref2 直当首帧），v3 固定机位 124 帧全程 ArcFace **0.84–0.88 零漂移**、运动量 1.56；v4 改成"果断出手＋缓慢推镜"后运动量 **4.71（3.0×）**，但身份 **0.888 → 0.697**（最低 0.683）。**漂移量与脸在画面中的像素面积严格同向（30k→108k px²）——推得越近，模型越要自己发明脸部细节。** 仍在同人区间（门槛 0.5）但趋势向下。⇒ 有脸镜要"更有力"时，先把这笔兑换摆给用户：要运动量让一点身份／要身份稳退回固定机位，别默认二者兼得。
- **★别的引擎的提示词不能直接喂 H3，"编译"是必做工序**：用户会交来写给**万相（Wan 3）**等中文模型的提示词（中文散文体＋独立"负面提示词"块＋"8K/无闪烁/纹理锐利"形容词）。本机 `h3_i2va_video` 工作流**根本没有负面词字段**（args 只有 theme/prompt_file/ref_images/width/height/length/duration/steps/seed/lora/lora_strength），那 24 条一个字都进不了模型；中文散文体也过不了 G7（要官方英文首帧指令行＋恰好三字段＋正文以 `[Shot 1]` 开头）。**正确交付＝把创作意图编译成原生格式**：负面词里能救的折成正向约束句进正文、其余删；"99 圈/第 99 圈/每圈更多"这类计数改定性（"由内向外逐层、越外越密越快"）；"淡出黑场"移出提示词（后期做）；"8K/无闪烁"删；**每段补 `overall_soundscape`（H3 原生出声，这层是白送的，用户稿常整块漏）**。
- **⚠️ 自写校验脚本不能当真闸证据**：我在生成器里复刻了一份 `gate_check()` 并全报"通过"，而它的 CLI 版（`check_preflight.py --only G7`）**没有 `--prompt-kind` 参数**、默认走"中文十块"分支，对合法 H3 三字段格式必然误报。⇒ 见 [[reference-localai-console-engine]] 末段：离线自审要 import 真模块传 `prompt_kind="h3_i2va"`，并用"引擎已放行过的旧提示词"做反证。

## ★排长片镜头表的算术：生成帧数与成片秒数必须分开算（2026-09-23《仙女星系》43 镜定稿时踩到）

**我第一版把两件事混成一件，跑出来成片 229.92 秒、比音乐长 2.71 秒。** 正确模型是两条独立的量：

- **成片秒数**＝导演的节奏，逐镜累加必须等于目标总长（本项目 227.00s，音乐 227.21s，余 0.21s 给结尾黑屏）。
- **生成帧数**＝`17n+5` 网格上**不小于**成片秒数×fps 的最近值。**宁可多生成再剪短，绝不能生成不够**（不够就只能变速或补帧，两者都更贵更丑）。
- 时间轴一律**按成片秒数累加**排，不按生成帧数累加排——否则每镜背 0.2–1.5 秒误差，45 镜能漂出十几秒。

**网格的数学事实**：网格值恒 ≡5 (mod 17)，所以**固定镜数下，一组镜头的总帧数模 17 恒等于 5×镜数**。想同时满足"总长＝某个整秒值"且"每道幕边界都落在整秒上"，多数情况无解——**别逐镜硬凑，把余量一次性交给结尾黑屏**。

**四条按时长分档的制作方式改写（都省 GPU 且更可控）**：
1. **超过自设上限的镜（本项目上限 243 帧＝10.125s，H3 实际可到 362 帧）→ 拆成两条**，不是硬顶格。15s 级长镜在 16GB 上有换页悬崖（226 帧＝13.1 s/帧），横屏 362 帧没测过，别拿整批赌。
2. **短于生成下限（本项目 107 帧＝4.458s）的镜 → 若它的运镜本就是"极慢／几乎静止"，干脆不生成，改"静帧＋后期运镜"**。理由不是省钱（虽然确实省 3–4 倍），是**这类镜要的是精确控制的慢，不是 AI 猜的慢**；生成反而会引入不受控的微运动。
3. **屏幕／UI／雷达特写一律不生成，走矢量合成**。扩散模型做不出可信的军事界面，自绘 HUD 更干净，且动效在后期可控。
4. **自设上下限要写进生成器**（本项目 `gen_shotlist.py` 的 `MINF/MAXF`），别每次手算——手算容易把"吸附"做成"四舍五入"，生成就不够长。

**★多角色对白戏的"零角色锚"拍法（同批定，省掉整条锁脸管线）**：剧本有 7 个有名有姓的说话人时，别去出 7 套定妆锚——**把桥段改写成不需要正脸的景别**：大全景拍空舱或剪影群像、过肩镜头（本来不露脸）、背影＋逆光、手部与仪器特写、舷窗反光代替"瞳孔里映出 XX"（后者 AI 极易出废片）。代价是全片没有清晰正脸，收益是**同时绕开角色锚、口型、跨镜身份一致性三个坑**，且台词走后期 TTS 后画外音配剪影反而更压。⚠️ 反过来：要正脸就得单开一条定妆→锁脸→口型的排期，不能混进硬表面批里算。
相关：[[project-spacewar-shortfilm]]、[[feedback-split-long-shots]]、[[feedback-video-quality-standards]]。

### seed 到底锁了什么（2026-09-24 查 `engine/comfy/h3_i2v_fl2va_api.json`，回答"草稿档达标了下次不是随机吗"）

seed 落在 **`node18 RandomNoise.noise_seed`**（不在采样器节点上），它锁的是**初始噪声张量**，而该张量的**形状由 width/height/length 决定**。推论三条：

- **换分辨率＝换形状＝换一整份噪声** ⇒ 576×1024 的 seed42 与 864×1536 的 seed42 是**两次互不相干的采样**。**"低分辨率草稿先验证、通过了再上全量"这条省 GPU 的路子不成立**（用户一句话问穿，已撤回）。同理"换帧数长度再跑一遍同 seed"也不是同一次抽签。
- **同分辨率＋同 seed＋同帧数＝可复现** ⇒ 这才是单变量对照（只改一个词、其余不动）能出因果结论的地基，不是运气。
- **我们真正的降随机手段是首帧**：首帧是人挑的确定图像，构图/景别/主体位置/色调全被钉死，随机只剩"运动怎么实现"这一层。镜2 换首帧后帧间运动 0.91→2.27 属首帧效应。
  ⇒ **省成本的正解＝把钱花在云端挑首帧（一张几毛钱、30 秒），不要在本地做两档分辨率对照（一段十几分钟）。**

## ★把 Seedance/云端分镜表搬到 H3 时的六条硬约束（2026-09-26 实查，不是推测）

1. **引擎的跑前自审闸按 `prompt_kind` 分两套格式，`h3_i2va` 那一套不吃中文十块。** `tools/check_preflight.py` 的 g7 在 `kind=="h3_i2va"` 分支里硬要求：提示词必须**逐字**以 `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.` + 空行开头；必须**恰好**出现 `integrated_multimodal_description:` / `overall_soundscape:` / `non_diegetic_music:` 各一次且按此序；正文必须紧跟 `[Shot 1]`；出现 `subject_definitions:`/`retention_analysis:`/`<Subject`/`<Video`/`<Audio` 或引用第二个 Picture 槽＝error；出现运镜器材名词＝error。**十块中文模板只能用在"出首帧"的图片提示词上**（图片走 `kind != video` 分支，只查器材名词）。
2. **帧数网格 17n+5 @24fps，合法 124–362 帧（5.17–15.08s）**，且 `length` 与 `duration` 差 >0.35s 会 warn。→ 排产算法＝成片秒×24 向上取到网格最近值，**宁可多生成再剪短**；时间轴按成片秒累加，别按生成帧数累加。
3. **镜子的"预估秒数"不能信文档摘要，要按台词重算**：`Σ台词字数/4.7 + (轮数-1)×0.6` 与动作下限取大。武昭君仪第一章 T21 表上写 15s，重算 9 轮对白要 **19.9s** → 362 帧装不下，必须拆。**台词让程序从正文正则抓 `“…”` 再配说话人、条数不符即报错**，比自己誊抄可靠得多（顺手就抓出总表把「还护着呢？把手松开。」缩写成"还护着呢"这类偏差）。
4. **fl2va 与 ref2va 互斥，承接机制要换轨**：ref2va 有 `ref_images(≤9)` 但**没有 first_frame**（构图从来没被锁住）；fl2va 有 `first_frame`（+原生 `last_frame`）但**不能挂锚点图**。云端那套"承接尾帧当参考图 + 同时挂若干锚点"在 H3 里做不到 → 改成**首帧＝前镜成片末帧抽帧**（软参考升级成硬几何锚），一致性前移到出首帧那一步用锚点图锁。
5. **H3 原生画布 1344×768 是 7:4 不是 16:9**，G5 会 warn；要严格 16:9 只能 1024×576 / 1536×864（两边都是 32 倍数）。与云端 1280×720 素材混剪时，拼片阶段垂直裁到 1344×756 再缩到 1280×720（裁 12px 看不出来）。
6. **没有音频文件就挂不了 `<Audio N>`**，跨镜音色无从锁。补偿＝H3 原生对白用 `<d>[中文]…</d>` 逐字 + **全片统一的 (S1)(S2) 说话人编号** + **声线描述每镜重复同一句**（有音色锚的项目恰恰相反，不重复写）；仍不稳就后期本地 F5-TTS 克隆一条过审的 take 替换。
7. **引擎跑完会把产物 relocate 出 ComfyUI 的 output 目录**（本项目＝`E:\图像影音资源池\<项目>\批次\<ts>\video\`）。自己写批处理驱动时**只扫 output 目录会把成功判成失败**——先解析引擎 stdout 里 `"files": [...]` 的绝对路径（JSON 里是双反斜杠，要 unescape），再兜底扫资源池。03:30 就这样把一条 1648s 跑完的好片记成"无产物"并停了整批。
8. **锁页内存（comfy_aimdo）是这台 31.8GB 机器真正的并发上限，不是显存**。渲染期间再起一个吃 2–3GB 的分析进程（insightface/DINOv2/LPIPS 一类），空闲掉到 ~1.9GB 后，**下一次提交会在建模阶段前 13 秒死掉**，报 `RuntimeError: HostBuffer.read_file_slice failed`（落在 VAE 或 llama 文本编码器，看运气）。这不是"分析自己 OOM"这么轻——它把渲染一起打死。解法只有**重启 ComfyUI**（杀掉后空闲 1.9→21.8GB）。所以：重活一律整批跑完、停服之后；无人值守夜跑要配看门狗（驱动死了→先看空闲内存→必要时重启 ComfyUI→从未完成的第一镜重拉，同一镜拉 3 次仍无产物就停手留话，别死循环烧卡）。
- ✅ 已验（2026-09-26 03:35，武昭君仪 H05）：**横屏 1344×768 顶格 362 帧＝1648.4s 端到端 4.55 s/帧**（8 步采样 24:20 ＋ VAE/音频解码 ~3 分钟），**没有换页悬崖**——226 帧 13.1 s/帧那条是竖屏 864×1536 的数，别外推到横屏。
- ⚠️ 仍未验：**H3 原生中文对白的清晰度/音色稳定性**（此前项目是哑女无对白；有台词的镜要等落盘后停服补 ASR）。注意**兜底代价是有界的**：对白不行就 `--no-audio` 只出画面、台词走本地 F5-TTS，成片本身不重做，所以不必为这一项单独立"先测台词"的前置批次。

## ★H3 提示词规则总纲已收录（2026-09-27）

**唯一真源＝`D:\AIWorkflow\ComfyUI_H3\H3提示词工程规则方案.md`**（跨剧本通用，与具体剧本解耦；v2＋R16/R17＝357 行）。R1–R17 每条都带"实测翻车"出处，原则是他自己写的：**不是预设定理，换模型/换参数后需重测复核**。已在 `使用规范_用前必读.md` §4 第 6 条挂了入口指针。

- ⚠️**桌面同名文件是快照不是真源**：他递来的那份 355 行，比 ComfyUI_H3 那份少 R16/R17。发现方法＝`diff` 两份＋比 mtime。**以后他再递桌面版，先 md5 对真源，别默认桌面＝最新。**
- 机器层＝`D:\AIWorkflow\tmp\wzy\h3_rule_gate.py`（**只报不拦**，判废权归人）。跑法：`py h3_rule_gate.py`（对 23 镜已编译提示词逐条检），`--sync` 把真源整份回写桌面快照。它同时打印"机器判不了的"（§十 VL 四问）＋冲突登记表。
- **编号两套，别混**：方案第四节的 R1–R17 是**通用 H3 提示词规则**；`wzy/prompt_rules.py` 的 R1–R5 是**本项目措辞法条**（矛头/金属/云肩/BJD/免责句）。机器层里方案的条一律写成 `H3R*`。
- 收录时登记的四处冲突（都只写了口径，没代裁）：① 方案内部 **R10 推荐"章法词" vs R13 判抽象词无效**→按 R13 检（抽象词同句无身体部位＝warn）；② **R5/§九 用禁令句排特效 vs 本机已验"H3 禁令无效"**→正向物理描述必写、排除句只当保险不作判据；③ **§九/§十一 逐字用「长枪/枪花/回马枪」vs 现行"枪"永久硬闸**（视觉描述区零"枪"字）；④ **§六 素材绑定（图1 管身份…冲突以图1 为准）只对 ref2va 成立**，fl2va 只有一张首帧挂不了参考图→一致性前移到出首帧那一步。

## ★2026-09-27 实查：另一条工具线（WorkBuddy）在本机加的 H3 能力（不是我建的，已逐条核实）

- **人脸保持上限 ≈0.57，提示词/锚点都突破不了 ⇒ 换脸是唯一解**：`inswapper_128` 逐帧换到 `junyi_face_real.png`，实测 sim **0.57 → 0.70–0.84**。工具 `wzy/faceswap_h01.py`、`faceswap_fight.py`。**含义：跨镜一致性要分两层分开治——身体层（线稿结构锚）＋人脸层（换脸），只做一层"看起来就不像同一个人"。**
- **可灵 Element 的真实边界：锁风格/主题，不锁脸几何**。要锁身体轮廓 **喂线稿比喂照片有效**（照片版 8 镜 ArcFace 0.00–0.24、还出现角色互换/性别错画；`wzy/face_check.json` 就是那份诊断）。线稿转绘要点：`clean black ink line drawing on pure white background… no shading`＋**脸只画成"极简椭圆＋两点一眼线"**，后续上色模型才不会去纠结五官。KEEP 句：`严格保留所有人物身形轮廓、服装、发型、武器位置与比例，仅在轮廓内填色、赋材质、加光影…`。工具 `wzy/kling_to_lineart.py` / `kling_create_lineart_elements.py` / `kling_batch_lineart.py`。
- **引擎 `D:\AIWorkflow\engine\tasks.py` 里多了一个 profile（09-26 14:55 改的）**：`fight_fast8` ＝ 736×416 / 124 帧 / **8 步** / `minimax_h3_fl2v_turbo_8step_v1.0`@1.0 ＋ **`Bunny_weapon_combatV1`@0.5** ＋ `head_chunks:4`（同表还有 `stable_t8`、`preview_t4`）。**⚠️ 我改 profile 之前要先知道这三个是别人在用的。**
- **三阶打斗 12 镜驱动**＝`E:\teng\tgptgrok\outputs\fight_multishot.py`（链式：提交→轮询→抓末帧当下一镜首帧→concat），配置走 `cfg_<id>.json` + `workflow: comfy/h3_i2v_fl2va_dual_lora.json`。**它的 W/H/LEN 与第一章不同（736×416/124 帧），别拿我第一章的 1344×768 基数去估它的时间**（≈82s/镜 是 736×416 的实测）。
- 1344×768 顶格 362 帧的 s/帧基数仍按我实测的 4.11–4.71 用（账本里 H01–H05 实测 3.34–4.71）。


## ★★2026-09-28 掉线根因：OS 事件确认＝**提交（虚拟内存）被吃满**，不是显存（推翻"并发分析进程"这个归因方向）

**现象**：任务在 `MiniMaxH3AVDecodeT8` 报 `hostbuf_file_reader_read failed`；8189 随后拒绝连接；重启后同参数照跑成功。

**硬证据（Windows 自己报的，不是推断）**：`System` 日志 `Microsoft-Windows-Resource-Exhaustion-Detector` **Event 2004**，时间戳与失败那一秒**完全重合**（16:39:08，同期 ComfyUI 日志写 "Prompt executed in 80.70 seconds"）：
- 提交上限 **63.78 GB** ／ 提交总量 **63.77 GB ＝ 100.0% 用满**
- 点名 `python.exe (23668)` ＝ **ComfyUI_H3 实例一家独占 39.26 GB 提交**（第二名是 Qoder 的 python 2.71 GB，第三 NVIDIA Overlay 1.57 GB）

**稳态算术（这才是根因）**：每步日志里四个模型全程 `0 models unloaded`、体量恒定 ——
`TE 14,956 + DiT 19,995 + VideoVAE 4,965 + AudioVAE 576 ≈ **40.5 GB 常驻提交**`，而物理内存只有 **31.8 GB** ⇒ **天生超配，一直靠页面文件吊着**。提交上限＝31.8 ＋ 页面文件上限 32 ＝ 63.8 GB，与事件报的 63.78 完全吻合。**不是泄漏，是稳态就超。**

**触发条件比我原来记的低得多**：三镜一连跑完实测 **空闲提交只剩 3.8 GB**（上限 61.2）⇒ **根本不需要"并发一个吃 2–3GB 的分析进程"，H3 自己就把余量吃到只剩 ~4 GB，任何额外消费者都足以顶爆。** 本次在场的额外消费者＝我这边的 ffmpeg 抽帧/编码后期活 ＋ Qoder 自身 2.71 GB。
⇒ **旧口径（§2026-09-26："再起一个吃 2–3GB 的分析进程才会死"）要改**：门槛是"**余量只有 ~4 GB**"，不是"有人吃了 2–3 GB"。

**为什么"修复"没挡住**：启动器里唯一记在案的修复是 **2026-09-17 的 `--reserve-vram 2.0`**，其注释写明防的是 `torch.AcceleratorError: CUDA error: out of memory` —— 那是**显存**。当天日志**零 CUDA OOM**，说明它确实生效了。**这次是提交/内存，两码事，修不到。**

**处置（本次验证有效）**：`Stop-Process -Id <8189 的 pid> -Force` → 空闲 RAM 3.9 → **23.3 GB**、空闲提交 3.9 → 24.3 GB、提交上限 61.2 → **47.8 GB**；用 `launch_cmd` 那条 Popen(DETACHED|NO_WINDOW) 重启，**13 秒就绪**。
- ⚠️ git-bash 里 `taskkill /PID` 会被 MSYS 当路径转义（报 `无效参数 'C:/…/PID'`），用 PowerShell `Stop-Process` 或 `//PID`。

**两条纪律（写死，违反就会重演）**：
1. **生成期间、以及"生成刚跑完"都不能跑后期重活** —— ffmpeg 抽帧/编码/拼片**同样算重活**，不只是"分析进程"。⇒ 重活一律**停服之后**做（本次就是停下来做的后期，全程安全）。
2. **失败后不要立刻重试**：提交还满着的时候重试，会在 staged 阶段 **90 毫秒内**把服务打死（本次 16:39:36 提交 → 16:39:36.869 日志终止），把"一次失败"升级成"服务掉线"。先查余量、先重启，再重投。

**未做**：`使用规范_用前必读.md` §7 故障速查表里**还没有这一条**（表里只有"服务起不来 / dequantize_embedding / SaveVideo format / 音轨嘈杂 / 15s 慢"五条）。

**★当天复现一次（2026-09-28 傍晚，我自己违反纪律踩的）**：跑 FLUX 出图（fp8 底模 + t5xxl fp8 ≈18GB）**的同时**，我那边在跑 numpy 拼对照图 → ComfyUI 又报 **`hostbuf_file_reader_read failed`**（KSampler 阶段），日志同屏一串 `OpenBLAS error: Memory allocation still failed after 10 retries`。
⇒ **两条加深**：① 触发条件不需要 H3，**任何大模型载入 + 并发内存消费者**都会撞；② **numpy/OpenBLAS 是惯犯**（按核数预分配，32 核就是几个 GB）——渲染期间要跑脚本一律钉 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`，**能停服再跑就停服**。（这条纪律原本只写在"生成期间"，现在证明**出图期间同样适用**。）

## ★2026-09-28 生成侧实测：点名"介质飞溅"在 H3 上兑现（横屏 736×416／124 帧／8 步／102s）

同一动作链重跑时，把命中拍从"只有动作"改成**点名介质**：「杆身中段扫在他躯干侧面：两者接触的那一点炸开一团过曝的白光，他脚下的积水被冲起一片水雾，火星与碎砖屑从接触点朝两侧飞散」＋【保持一致】豁免句里补"水花、水雾、火星、碎屑"。
- **成片里肉眼可见**：接触点过曝白光团、水雾朝两侧炸开、落地与撞墙全程带水花碎屑（不是"慢慢化开的白雾"）。⇒ §十二 在可灵上量到的 flow 1.09→2.34 那条**在 H3 上也成立**，介质与实体飞溅点名就能进画面。
- **不超配时长同样有效**：同一镜 175 帧→**124 帧**（5 人信息单元按 R17 该给 4.5–6s，7.29s 是超配），飞行段自动从 3.2s 缩到约 1.9s，**不再需要靠后期变速去救**（老版 1.9 m/s → 新版约 3.2 m/s）。⇒ 先按单元配时长，再谈后期。

## ★2026-09-28 复核：首尾帧（last_frame）——通道差异要讲清，且 `使用规范` 那句是过时的

用户主动问「H3 也可以首尾帧的是么」（同 2026-09-20 那条：节点已接、实测有效）。复核后要补的只有差异与一处旧话：

- **节点/模型层支持，本机确实跑过**：`MiniMaxH3ImageToVideo` 的 `first_frame` / `last_frame` 两个可选输入都在（尾帧钉在 `frame_count-1`）；`ComfyUI\input\` 里留有历史尾帧输入图 `h3L_*.png`（G05/G07/G08/G11/G14/k2/k3 等）。
- **回答用户时先给通道差异**：`run_h3.py --last-frame` 可用；**引擎那条没接**——`h3_i2va_batch` → `engine/comfy/h3_i2v_fl2va_api.json` 三张 fl2va 图各只有一个 LoadImage、只喂 first_frame，整个 `D:\AIWorkflow\engine` 搜 `last_frame` **零命中**。要在引擎里两头夹＝建第二 LoadImage(`__REF2__`)→last_frame 的变体（见上文 2026-09-24 那条），或直调 run_h3.py。
- **⚠️ 一处文档过时**：`使用规范_用前必读.md` 末尾把"首尾帧（FL2V）"与 `MiniMaxH3AddGuide`（中间帧引导）混在一起写"在本版 ComfyUI 未见"——**两半都不对**：AddGuide 本版已注册可用（`nodes_minimax_h3.py` 的 `MiniMaxH3Extension` 里列着），而首尾帧本来就不需要 AddGuide（它是节点自带的 `last_frame`）。谁再引那句，按本条纠正。
- **备图注意**：首帧是按画布**拉伸**（geometry anchor）、**尾帧是按画布居中裁切**（follower）⇒ 尾帧图最好本来就接近出片比例，否则会被裁。

### ★同日晚：抡枪砸飞单镜「两头夹」A/B 实测结果（首尾帧到底管什么）

- **设置（单变量）**：首帧＝双人站位；尾帧＝**A 原片末帧 f123**（他埋进砖堆那帧）；提示词与参数和 A **一字不差**（736×416／124 帧／8 步／seed 20260928）；走 `run_h3.py --last-frame`，**105s** 出片。
- **① 末端保真 MAE = 3.93 / 255**（末帧 vs 给定尾帧锚，像素级）⇒ **尾帧锚被严格执行**。这是首尾帧最硬的价值：**落点／机位／构图可以事先钉死**，不用赌模型自己收在哪。
- **② 运动节奏被改变**（`measure_motion_profile.py`，每格＝该秒平均光流）：
  - A 无尾帧 `1.81 / 2.31 / 2.99 / **7.49** / 4.69 / 1.53`（全片 3.80）——开头"确认长相"，第 3 秒一个尖峰；
  - B 有尾帧 `**2.31** / 2.85 / 3.51 / 5.83 / 4.79 / 1.29`（全片 3.79）——一上来就在动、峰值摊平；
  - ⇒ 挂尾帧后**动作提前起来、更均匀，总运动量不变**。对 5s 动作镜有意义（少了前段空转）。
- **⚠️ 这条没证明"能把击飞位移拉大"**：锚取自现有那条偏保守的落点 ⇒ 它证的是"**钉得准**"不是"**钉得远**"。要治"位移量弱"必须**手工造一张更远的落点图**当尾帧，再看模型是否把整段飞行拉长去够它。
- 素材与对照片：`E:\创作\武昭君仪\打戏练习件_长枪vs义体腿\_实验_首尾帧两头夹\`（原片／原速并排／同刻抽帧表／尾帧保真核对）。项目背景见 [[project-wuzhaojunyi-fight-practice]]。
- **图级核实（别只看脚本选项）**：跑中的图里 `MiniMaxH3ImageToVideo`(节点7) 同时收到 `first_frame←1` 与 `last_frame←21`，提交串回显 `fl2va/t8+尾帧`。

### ★★同日晚续：**跨两镜两头夹成立**（用户嫌单镜看不出差别 → 改跨镜，这条才是首尾帧的正用法）

用户看单镜 A/B 说「感觉看不到出来差别」——**原因是单镜两端状态本来就接近，模型不挂尾帧也收在那儿**。改成跨两镜：
**首帧＝第一镜（抡枪砸飞）首帧，尾帧＝第二镜（起身转身）尾帧**，把两镜动作压进**一条连续生成**。

- 参数：**243 帧 / 10.125s**（两镜动作合计约 10.3s，124 帧装不下）/ 736×416 / 8 步 / seed 20260928 → **205s（≈0.84 s/帧）**。⚠️ **243 帧在 736×416 未见换页悬崖**（对比竖屏 864×1536 的 226 帧 13.1 s/帧）。
- **结果：整段弧线真被补出来了** —— 逐段抽帧：站位 → 横扫命中(接触点过曝+水雾) → 机甲离地 → 腿伸出砖墙 → 砖墙塌落 → 埋在里面 → **镜头贴着他头部掠过（特写）** → 镜头绕到侧面女子入画 → 两人对峙落幅。**跨镜合一还长出了原两镜没有的一拍**（掠过机甲头部），是自成节奏的一条长镜。
- **两端都钉住、尾端更紧**：首帧锚 vs B f0 **MAE 15.65**（diff 呈**轮廓状＝轻微整体错位**，非内容不同）、尾帧锚 vs B f242 **MAE 4.41**（近全黑）。
  ⇒ **首帧对齐比尾帧松**：首帧虽标称 geometry anchor（拉伸到画布），模型仍会用 VAE 重画一遍、带出轻微整体位移；要"第一帧逐像素对"的镜要留意。
- ⇒ **"两头夹"给两个端点就能补出中间 10 秒整段动作**，这是"锁动作"里比堆参考图更对症的一条（参考图只锁身份外观、不锁运动）。**要治"位移量弱"仍须手工造更远的落点图当尾帧**。
- 全部素材：`E:\创作\武昭君仪\打戏练习件_长枪vs义体腿\_实验_首尾帧两头夹\`（含合一镜原片/逐段抽帧/端点保真/与原两镜拼接的同刻对照/提示词/日志）。

### ★★再补：换 seed 复现——**锚是结构性的、中间是抽签的**（同日第 3 条，最有用的一条）

同设置只换 seed（20260928 → 20260929），耗时同为 **205s**。⚠️ 前提认知：**同 seed＋同输入是确定性的**，重投只会得到逐像素一样的一条 ⇒ 要"再出一条"**必须换 seed**。

- **两端保真几乎逐值复现**：首帧锚 vs f0 ＝ **15.65 / 15.77**；尾帧锚 vs 末帧 ＝ **4.41 / 4.56**（两条只差 0.12/0.15）。
  ⇒ 这两个误差是**结构性的、不是抽签**：首帧那 ~15.7 是"模型用 VAE 重画了一遍 frame 0"造成的整体错位（diff 呈**轮廓状**），尾帧那 ~4.5 是极小残差。**锚稳。**
- **但中间过程差别很大**（逐秒光流，512 归一，全片）：T1 `2.84/10.43/**15.07**/6.13/5.19/9.23/**17.62**/8.82/3.16/2.07/1.57`＝**8.00** vs T2 `1.08/5.88/6.35/2.94/3.03/2.15/5.15/**8.15**/7.44/2.83/1.98`＝**4.48**。
  观感：T1 更冲更紧（2.0s 已砸到墙边、6.0s 给机甲头部特写、8.0s 已到落幅）；T2 更缓更宽（2.0s 还在空中翻滚、6.0s 只是中景站着、弧线更晚）。
- ⇒ **两头夹锁的是"两端"，不锁"中间怎么走"**。实务含义：**用两头夹做正式镜要留挑选余地（多出几条挑一条）**，别当成一次就能定；反过来，只要两端锚住，**收尾是可靠的**。
- **★用户看片判定（把"不锁中间"的代价点实了）**：
  - **T1（seed 20260928）＝混混"侧面"飞出去、像被挑飞 ⇒ 重演了老的"方向错"问题**；**T2（seed 20260929）＝方向对、跟定稿一致、观感还更好**。
  - ⇒ **首尾帧锁"两端姿态/构图"，不锁中间路径——包括最要紧的飞行方向**。而且翻车那条**其它方面全成立**（两端照样钉住、弧线照样走完）⇒ 不是整条崩，是**单点错，最容易漏检**。
  - ⇒ **打戏里"方向是硬要求"的镜，用两头夹必须多出几条挑一条**；要一次到位得给**中间**加锚（`MiniMaxH3AddGuide` 中间帧引导 / 分段生成后剪接），别指望尾帧管方向。（同 [[feedback-combat-shot-grammar]]：击飞方向属编排层。）


- 已跑通(8189/run_h3.py)
- fl2va=8步+turbo
- ref2va=三锚点+画风锚
- 超分在前修脸最后
- **挂多锚点前必做 md5 查重+逐槽核对身份**
- ⚠️226帧=13.1s/帧悬崖
- ⚠️报 FAIL 先查 /queue
- **★云端分镜表搬 H3 六条硬约束：G7 按 prompt_kind 分格式(h3_i2va 吃不下中文十块)/帧数 17n+5·124–362/镜长按台词重算别信摘要/fl2va 与 ref2va 互斥→承接改"前镜末帧当首帧"/1344×768 是 7:4/无音频文件挂不了 <Audio N>→声线句逐镜重复**
- 规则总纲见下条

## ★2026-09-28 引擎直调单镜（不碰生产 jobs.json）＋三条必踩的坑

- **单镜提交契约**（复用 `wzy/run_batch.py` 的 `submit()` 形态，不必改它）：
  `python D:\AIWorkflow\engine\run.py h3_i2va_batch --project 武昭君仪 --output-root <根> --set theme=<名> --set prompt_file=<*.txt> --set ref_images=<首帧> --set width=736 --set height=416 --set length=124 --set duration=5.17 --set steps=8 --set seed=<n>`（可选 `--set no_audio=true`、`--lora`/`--lora_strength`）。引擎默认挂 `minimax_h3_fl2v_turbo_8step_v1.0`、`head_chunks:4`。
- **⚠️ G11 硬闸：交付根路径里必须含项目名**。`--output-root` 指向不含 `武昭君仪` 的目录时，G11 报"项目段不含当前 project"**直接终止**（进程退出、零产物）。把根设成 `<…>/trial/武昭君仪` 即通过——这也是**把练习件产物隔离出生产批次池**的干净做法（产物落 `<根>/<run_id>/video/`）。
- **速度**：736×416／124 帧／8 步 ＝ **99.1s**（与 `fight_fast8` ≈82s/镜同档）⇒ 适合当"改一句话、重跑一条"的单变量对照成本。
- **预检照跑**：`h3_i2va_batch` 保留 G1–G11 自审；官方骨架格式（首行固定指令＋恰三字段）能过 G7，只有一条 G3 warn。
- **⚠️ `cv2.imwrite` 写不了中文路径——会静默写出乱码名文件**（`K02_璇曡窇_鎶藉抚.jpg`），不报错。抽帧存图一律用 `cv2.imencode('.ext', img)[1].tofile(path)`；`PIL` 存图无此问题。
- **光流尺子**：`E:\创作\烬骨辞\工具\measure_motion_profile.py <mp4>`（逐秒分桶）；跨片比较用它，别用只采 40 对的 `measure_motion.py`。
- **ComfyUI 要先把 8189 起起来**：`D:\AIWorkflow\ComfyUI_H3\run_H3_ComfyUI.bat`（起服务约十几秒到一分钟，`/system_stats` 返回 200 才算就绪）。
- **⚠️ 武昭君仪"现成首帧"的选型陷阱（2026-09-28 实查）**：真正可用的双人机位首帧＝`E:\创作\武昭君仪\首帧图\线稿机位图\h3first\P{1..3}{A..D}_first.png`，**1472×828**（跑前要缩到跑分档，本次裁到 736×416）；其中**P3 系列已是裸枪**（P1/P2 仍裹布），**P3D 带「武君仪」竖排字**、违反无字规则不可用。⇒ 而 `首帧图\首帧_面对面站位.png` **名不副实**——那是粗臂男的四视图设定表（棚拍白底＋上下霓虹条），不是双人同框；别按文件名取用，先看图。

## ★★2026-09-30 本机首次跑通「纯文生视频」（T2VA，零输入图）

用户问「能不能文生视频哦」。**答案＝能，而且节点层一直支持，只是本机从没打开过那扇门。**

- **门被脚本堵住，不是模型堵的**：`MiniMaxH3ImageToVideo` 的 docstring 原话 `t2va and fl2va: prompt (+ optional first/last keyframes)`，
  `first_frame`／`last_frame` 两个输入都是 `optional=True`（`ComfyUI\comfy_extras\nodes_minimax_h3.py` L130–131），
  权重 `minimax_h3_fl2va_pruned_int8_convrot` 同时服务 T2V/I2V。
  但 **`run_h3.py` L322–324 在"无首帧位置参数、无 `--ref-images`、无 `--ref-videos`"时直接 `exit 2`** ⇒ 生产侧没有 T2V 出口。
  ⇒ **通用判据（第 N 次印证）：判"本机某能力有没有"要看节点 `define_schema()` 与权重说明，不要只看脚本的 CLI 选项。**
- **处置＝另写、不改他的脚本**：`E:\创作\H3改写_算盘与崩山_20260930\run_h3_t2v.py` ＝ `run_h3.py` 的 `build_workflow_t8`
  **去掉节点 1（LoadImage）与节点 7 的 `first_frame`**，采样链（LowVRAMAttention→DualClockSamplerT8→BasicGuider→RandomNoise→SamplerCustomAdvanced→AVDecodeT8）一字不动。生产脚本零改动。
- **实测基数（首个 T2V 数）**：1024×576／**124 帧**／8 步＋`fl2v_turbo_8step`@1.0／T8 双时钟＋原生音频／seed 20260930 ＝ **181 秒**、2.23 MB、实探 124 帧 24.00 fps 5.17 s。
  362 帧（15.08 s，顶格）同参数在跑，按 09-13 的 i2v 基数 11m32s 估 **11–13 分钟**（T2V 少一份 keyframe，不会更贵）。
- **⚠️ 提交内存余量（排 362 帧前必看）**：那条 **124 帧**渲染中 `FreeVirtualMemory` 掉到 **598 MB**，总提交上限只有 **53→56 GB**（09-28 崩前那次是 63.8 GB）
  ⇒ 印证 09-28 结案（H3 四模型常驻 ≈40.5 GB 提交、物理只 31.8 GB，靠页面文件吊）；**页面文件是动态的，别拿上次的 63.8 当常量**。
  渲染期间空闲物理内存只剩 2–3.6 GB ⇒ 362 帧属压线跑，期间绝不叠加任何重活（ffmpeg/numpy 一律停服后做）。
- **用途**：把云端那条（即梦技能包自规投喂版，Seedance 2.5／720p，¥22.74 已出片）**同内容编译进 H3**，做「一份提示词 × 两个通道」对照——
  要验的是 **H3 在没有任何几何锚时能不能自己切出 8 个镜**（云端那条 8 镜切出来了）。编译逐条映射见 [[reference-h3-prompt-rules]] 末段。
- **⚠️ 自己造的假失败（09-30，同 09-21"报 FAIL 先查 /queue"一族）**：把渲染用 `nohup … > full.log &` 丢后台、
  **同一条被跟踪的命令里紧接着 `sleep 20; tail full.log`** → 文件还没落盘，tail 报 not-found，**整个后台任务被判 exit 1 "failed"**，
  而真实渲染早就提交成功了（`prompt_id` 已发、`/queue` 显示 running 1）。
  ⇒ **判"提交成没成"只认两个硬证据：`prompt_id` 与 `/queue` 的 running/pending 计数**，别拿包装命令的退出码当结论；
  要拿完成通知，就单独起一个只 grep 日志终态行的等待命令，别把 tail 和起进程混在一条里。

### ★同日续：362 帧全量出片，**H3 纯文本读得懂 8 镜分镜表**（09-30，本条最有价值）

- **实测基数补全**：1024×576／**362 帧（15.08 s 顶格）**／8 步＋turbo8step／T8＋原生音频／seed 20260930 ＝ **721 s（12m01s）**、7.08 MB。
  ⇒ 与 09-13 的 i2v 同档基数 11m32s 几乎一致，**T2V 不比 i2v 便宜**（省的那份 keyframe token 抵不掉长序列注意力）。
- **切点命中（帧间差尺子，硬切阈值 35）**：提示词点名 `[Shot 2..8]` 落在 2.0/4.0/5.5/7.5/9.5/11.0/13.0 秒，
  实检 **0.5/1.9/3.8/5.3/7.3/9.3/10.8/12.8** ⇒ **七道指定切全中，误差 0.1–0.3 秒**（0.5 那刀是镜1 内部甩链爆点）。
  同内容云端 Seedance 2.5 七刀 @1.5/2.92/4.58/6.42/8.67/10.33/12.75，**误差最大 0.8 秒**。
  ⇒ **H3 在零几何锚、零参考图下能按时间码自己切镜并逐镜演出指定动作**，八拍内容抽帧逐一对上（贴地靴→抽脸→低角全景断柱→绕腕特写→吼冲→顶视角勒腕→拽倒撞柱→满脸血抬头）。
  这条推翻了我自己此前的默认预期"本地 H3 得靠首帧/参考图带镜"。
- **⚠️ 尺子不通约（别拿运动量跨画幅比）**：H3 横屏 1024×576 motion_mean 19.05／静秒 4，云端竖屏 720×1280 是 12.98／静秒 8。
  缩到宽 240 后每像素代表的场景范围不同 ⇒ **只有"切点"这一项两条同尺可比，motion_mean 不可比**。
- **原生中文对白出声、且这次没烧字幕**：转写（`faster_whisper base`，py -3.12）得「同前也敢碰我」，与目标「铜钱也敢碰我」**同音**
  ⇒ 句子真说出来了（咬字准不准仍须人耳，09-15 判据不变）。**结尾 13.0–15.1 s 六帧逐个看过，无烤入字幕**
  ⇒ **09-15 那条"写台词就烤字幕"不是必然**，别当硬约束写进规则。
  音轨 mean −30.9 dB／max −7.0 dB，**没有 09-13 那种近削波噪轨**（那次 −14.1/−2.2）。
- **两处偏差**：① 写了 `3D CG, cinematic, hyperrealistic`，出来是**实拍质感**（男角色直接像真人演员）——
  09-15 记的"H3 把 CG 往实拍拉"这次**一路拉到底**，走 H3 做国漫 3D 风要按"这条通道给不了 CG"来规划；
  ② 发型「短发束在脑后」→ 长辫子。零锚时细特征必漂（同 [[feedback-character-reference-image]]）。
- **🔴 G7 假报已实测坐实（未改他的闸，待裁）**：`check_preflight.py --channel h3 --prompt-kind h3_i2va`
  对一份**合法** T2VA 稿回 `✗ [G7] H3 骨架缺官方首行指令` **error=1**。
  根因＝G7 的 h3_i2va 判据把 **I2VA 的图片对齐首行**当成骨架必备，而官方 §2.1 明写 **T2VA 没有对齐指令行、必须直接以 `integrated_multimodal_description:` 开头**。
  ⇒ 现走 `run_h3_t2v.py` 自带的最小字段校验（三字段各恰一次＋必须以上述字段开头）顶替；**要不要给 G7 加 T2VA 分支归他定**。
- **交付**：飞书群「吕湘」14:02–14:03 三条（成片／彩色抽帧表／机检说明），各 `ok:true`；
  留痕在 `E:\创作\H3改写_算盘与崩山_20260930\`（`calls.log`／`full.log`／`smoke.log`／`qc_h3.json`／`改写说明_T2VA编译稿.md` §五）。
  **全部只算 completed，八镜成不成立待人审。**

### ★同日人审回来了：**我列的"方位四条"是错的病灶，用户点的是距离与动量**（09-30 下午）

- **用户原话**：「不是，H3两个人站位太靠近了，女的链子本来应该对着男的甩过去的，生成的是向侧方位甩，打空气了。然后男的被打中，是慢慢走过去撞的柱子，没有体现被击飞的感觉。其他其实都还好。」
  而我此前用逐帧表给出的诊断是四条：命中部位（左脸→胸肩）、镜2 后半两人全变背影＝轴线翻、特写里手的归属、镜5 下潜丢人。**四条都不是他要的那件事。**
  ⇒ **通用纪律：agent 拿抽帧＋机检自己归纳"病灶清单"时，很容易把"能测到的"当成"他在意的"。先把用户点名的可见现象逐条抄下来再开药，不要用自己的分类替换他的描述。** 相关 [[feedback-animation-decomposition]]。
- **而且根因在我自己的改写措辞里**（可复用，价值最高的一条）：
  - 我把技能包"踉跄后退半步"译成 `staggers half a step back onto his heels`、把"退到断柱前"译成 `The man retreats to … column and braces …`。
    **`retreats`／`staggers`／`walks` 全是主动位移动词 ⇒ 模型照字面演成"他自己走过去撑住柱子"，"被击飞"就这么被写没了。**
    **正解＝主动位移动词一律换成被动受力＋可量位移**：`his whole body is thrown sideways two metres, both boots skidding rather than stepping`、`he is still carrying the momentum of that same blow when he reaches the column`（撞柱写成同一次受力的延续，不是新动作）。
  - **构图本身会删信息**：镜1 我按技能包写成"贴地特写、同框两人小腿"，**特写里根本没有"隔三米"的容身之处**，模型只能把两人贴一起；镜2 又写"她左前景／他右中景"，深度上再压一次。
    ⇒ **要表达空间距离，就得让构图装得下这段距离**（低机位带前景的中景＋明写"两人之间三米空地、中间没有任何人任何物"）。这比加形容词有效。
  - **方向要写成"朝目标飞"，不是"沿画面怎么走"**：我写 `chain cracks diagonally from the lower right of the frame to the upper left` ＝ 画面几何方向，于是"向侧方甩、打空气"。正解 `the chain unrolls at full length straight across that open ground toward the man on the right`。
- **⚠️ 位移量弱在 H3 上撞过墙，别承诺提示词能治**：09-28 两头夹实测记过——尾帧锚证明的是"**钉得准**"不是"**钉得远**"，要治位移只能手工造一张落点更远的尾帧图。
  所以 v3 若把"走过去"改成了"扑出去"但幅度仍不够，那是模型层，下一步该上中间帧锚／两头夹，**不是继续加形容词**。
- **复跑基数（同参数三条，可当排产常量）**：362 帧／1024×576／8 步＋turbo8step／T8＋音频 ＝ **721 s / 716.6 s**（±1%）。
  124 帧＝181 s。**T2V 与 i2v 同价，且耗时极稳。**
- **★`fl2va` 首帧两条硬事实（用户下一步要用线稿当首帧，先说清）**：
  ① **frame 0 就是那张图本身，H3 不会顺手上色** ⇒ 拿黑白线稿当首帧，成片很可能从线稿开场并一路带素描感；要能用的片必须先过一遍上色（本地 FLUX i2i／即梦图生图）。
  ② **首帧是按画布"plain stretch to canvas"拉伸**（源码注释）⇒ **出图比例必须与目标画幅一致**（1024×576 就得要 16:9），否则被硬拉变形。尾帧则是居中裁切（follower），另算。
  ③ 附带提醒：**首帧描述的状态必须和视频提示词的起点一致**——他给的线稿是"男已撞柱瘫坐捂胸"＝镜7 之后的落幅，配不上从镜1 甩链开场的 15 秒稿；要么改提示词起点，要么换线稿状态。
- **✅ 用户改口：接受实拍画风**（09-30 原话「之前感觉实拍立不住可能是我误判了，是我们自己的问题，实拍效果也很好」）。
  ⇒ 上面"H3 给不了 CG"那条**不再是缺陷、只是通道特性**；不要再按"必须保住 3D CG"去规划 H3 的镜，也不用为它开修复批次。
  但反过来：**别把这条推广成"写实档随便走"**——他这次接受的是 H3 给的具体这一档，换项目仍要他看过再定（[[user-visual-taste]]）。
- **对照实验设计记一笔（这次做对了）**：v2／v3 都**保持 seed 20260930 与全部参数不变、只改一类句子**，
  并用 `difflib` 逐行核改动面（v3 只碰镜1/2/3/7）；抄写时顺手改了镜5 两个词（`coarse cloth thrown over`→`dirty cloth on`）
  **当场如实报给用户、并声明它使 v1↔v3 不是绝对干净的单变量**，不为一处口误重烧 12 分钟。⇒ **"改动面自证＋污染如实申报"这套要继续用。**

### ★2026-09-30 线稿首帧（fl2va）实测：锚管几何、不管长相，且**线稿会被当场上色**

同内容第四版 F1＝即梦出的对峙线稿当 `first_frame`，走生产 `run_h3.py`（1024×576／362 帧／8 步＋turbo8step／T8＋音频／seed 20260930）＝ **737 s**。

- **✅ 我上一轮的预判被推翻**：以为"线稿当首帧→成片一路素描感"。**实测第 0 帧彩度 9.5、与线稿灰度 MAE 6.7（＝第一帧就是那张线稿），第 12 帧（0.5 s）彩度跳到 59.4，之后稳定 66–68**。
  ⇒ **H3 把线稿当"待上色的内容"渲染，不当"风格"保持**。线稿首帧可以放心用，不会污染成片画风。
  ⚠️ 但**别拿 0.5 s 处 MAE 涨到 125 去说"构图也丢了"**——镜1 本来就在快速后撤，构图变化里混着相机运动，这把尺子分不开；构图要看抽帧表。
- **✅ 几何锚比措辞修更能治"距离＋动量"**：1.9 s 两人之间是看得见的空地、链子横穿过去；3.9 s 他被拉着往后滑脚擦地；4.4 s 整个人撞进柱身带落灰。
  v3（纯文本改措辞）把距离做出来了但位移量偏软。**两条都有效，锚更硬。**
- **切点结构反而更干净**：F1 检出 **7 刀 @2.0/3.83/5.25/7.0/9.33/10.75/12.75**（指定 2.0/4.0/5.5/7.5/9.5/11.0/13.0，最大误差 0.5 s，无多余切）；
  v3 检出 9 刀（镜5 内部多切两下）。⇒ 首帧压住了模型的"自作切镜"。
- **🔴 锚只管几何不管长相**：上色那一瞬间服装配色被重新发明（她→白袍红腰带，他→古铜皮肤白裤，场景→大晴天），与参考图和线稿的灰青暗纹调全不符。
  ⇒ **要锁外观只能给"上色静帧"当首帧，或走 ref2va 挂参考图**；线稿首帧的这一项不要指望。
  推论（成本正路）：**线稿定构图 → 上色定外观 → 拿上色版当首帧**，比一上来就出精绘静帧便宜一个数量级。
- **🔴 G3 口径漏子（实测坐实，未改他的闸）**：fl2va 的首帧走位置参数 `--image`，而 G3 只数 `--ref-images` ⇒
  **一份带 `<Picture 1>` 的合法 fl2va 稿必报"编号越界"error、拒绝提交**。把首帧改用 `--refs` 传进去，**error 立刻归零（error=0 warn=1）**。
  ⇒ 与 09-28 那条"fl2va 提示词一律改说『同首帧的男子/女子』、别用 `<Picture N>`"是同一件事的两面：**当时的绕法是让提示词迁就闸，而官方 I2VA 格式恰恰要求写 `<Picture 1>`**。要不要补闸归用户。本次用 `--skip-preflight` 提交，命令行进 `calls.log` 留痕。
- **⚠️ 又踩一次 cv2 路径坑（这次差点造出假结论）**：`cmp_sheet.py` 收到 MSYS 风格 `/c/Temp/...`，`VideoCapture` 打不开，
  而我把读帧失败**静默兜底成零矩阵** → 产出一张**全黑"对照表"**，看起来像"片子是黑的"。
  ⇒ **抽帧/拼图脚本里读帧失败一律 `sys.exit`，绝不填黑帧**；已改。cv2 只认 `C:/...`，不认 `/c/...`。
- 素材：`E:\创作\H3改写_算盘与崩山_20260930\`（`firstframe_lineart.jpg` 原图 1536×864、`firstframe_1024x576.jpg`、`f1_lineart_i2va.txt`、`h3f1_lineart.mp4` sha 前 16 `e588c470ee9f803a`、`对照_v3纯文本_vs_F1线稿首帧.jpg`、`f1.log`）。

### ★2026-09-30 F1 三抽（同线稿首帧，只换 seed 930／931／932）：什么被锚钉住、什么仍是抽签

- **钉得住（与 seed 无关）**：首帧保真 MAE **6.7／6.8／6.6**、第 0 帧彩度 9.5／9.7／9.3（三条都从线稿原样起步）；
  切点 930＝7 刀、931＝7 刀（位置差 ≤0.25 s）、932＝9 刀（多出的是 0 s 上色跳变与 8.33 s 镜内多切）；
  **最关键那拍（1.9 甩链 → 2.4 链子横穿空地打到他 → 3.9 被拉着滑 → 4.4 撞进柱身）三条全部成立**——v1 那个"链子打空气"的病，上锚之后不再复现。
- **会漂**：调色（930 黄昏暖＋蓝云／931 冷灰乌云／932 大橙日落，0.5 s 处彩度 59／88／80）、**她的服装颜色三条三个样**（白袍红腰带／白粉袍红腰带／灰褐袍）、柱位、机位高低、他的肤色体型。
- **🔴 本条最有用的一句**：**换 seed 连服装配色都不一致 ⇒ 线稿首帧只钉 frame 0，0.5 秒后模型重新上色，每次上得不一样**。
  ⇒ **"上色静帧当首帧"不只是让画面好看，它是跨镜／跨条可复现性的前提**。想要长得一样，首帧必须是已定色定材质的图，不能是线稿。
  与 09-28 那条"锚是结构性的、中间是抽签的"合起来：**锚钉几何，上色钉外观，中间的运动路径两者都不管，只能多抽挑一条。**
- **★通道差异（不要与云端互借）**：本地 H3 **换 seed 运动量很稳**。可复跑口径（`E:\创作\技能包转H3_SOP\工具\qc_cut.py`，原值存 `C:\Temp\h3cmp\f1_three_rolls_recheck.json`）：
  帧间差均值 **930=14.45／931=14.32／932=13.76**，p90 29.32／29.26／33.50。两条干净抽（930/931）只差 **0.9%**；932 低是因为镜内多两刀。
  ⚠️ **本条曾记作 15.21／15.14／14.55——那组数出自一个已不在盘上的临时脚本，不可复跑，已按可复跑值更正**（规矩见 [[feedback-evidence-loop-trap]]：交付数字必须从盘上重读、自证必须可复跑）。
  而云端 Seedance 2.0-mini 同臂复抽的运动量是 9.57→14.35 级别的噪声（09-30 实测）。
  ⇒ **"运动量类指标必须多条抽样才可判"这条只对无 seed 的云端成立；本地 H3 有 seed，运动量近确定性，可以当判据用。** 见 [[feedback-per-channel-rules]]。
- 素材：`E:\创作\H3改写_算盘与崩山_20260930\`（`h3f1_seed20260931.mp4` sha `225f8a82a5dfa3c7`／`h3f1_seed20260932.mp4` sha `7edaecb6e4f84395`、`对照_F1三抽_同刻.jpg`、`reroll_metrics.json`、`reroll_f1.sh`、`reroll_*.log`）。
  两条各 **741 s／742 s**，串行跑（并发会顶爆提交内存）。飞书已发三视频＋三表＋三说明。

### ★2026-09-30 晚：第二段零锚跑通 ⇒ **跨段承接靠文字就成立**（但一批之内锚必须统一）

同一份分镜的第二段（技能包写稿 → SOP 编译 → T2VA 零锚，seed 20260930／362 帧／672.7 s／¥0）：

- **切点比第一段更准**：指定 2.0/4.0/5.5/7.5/9.5/11.0/13.0，实检 7 刀 @1.92/4.00/5.50/7.50/9.58/11.00/12.92，
  **最大误差 0.08 s、无多余切**（第一段零锚 0.5 s）。⇒ "H3 读得懂逐镜时间码"这条从 1 例变成 2 例。
- **承接住了**：他半跪在带崩口的断柱下／她三米外（第一帧就是这关系）、链子仍绕他右腕并在镜4 再加一圈、
  镜6 反手绕过后颈、柱上崩口从镜1 就在、他左眼带血、她青灰短打短发没漂。
  ⇒ **上一段的站位／武器圈数／场景损伤／人物伤态，写进下一段第一拍就能传**，H3 不需要"上一段"这个输入。
- **台词照样出声且不烧字幕**：13.96–14.78 s 说"铜钱不赊账"（whisper 得同音「同钱不收账」），结尾 32 帧底部亮像素占比 0.000。
- ⚠️ **音轨响度会飘**：本段 mean −36.1 dB／max −11.5，第一段 mean −17.1。零锚 T2V 的声音不是每条一样厚，要发片得补音效或抬响度。
- 🔴 **最容易踩的新坑：一批之内锚必须统一**。第一段最后挑的是挂线稿首帧的 F1（白袍红腰带），第二段零锚是青灰短打——
  **两条混剪外观对不上，等于换了个角色**。要么整批零锚（文字一致→外观一致），要么整批挂同一张上色首帧。
- 产物与留痕：`E:\创作\H3改写_算盘与崩山_20260930\h3_段2_00001_.mp4`、`接触表_段2_八镜.jpg`、`段2_t2va.txt`、`段2.log`、
  `C:\Temp\h3cmp\qc_duan2.json`；结论已写回 `E:\创作\技能包自规_双人打斗_20260930\算盘与崩山_第二段.md` §六。
  流水线本身已固化成 SOP：[[reference-h3-prompt-rules]] 指向的 `E:\创作\技能包转H3_SOP\README_SOP.md`。

### ★2026-09-30 晚（续）：段2 缠身版＋"上一段成片帧当首帧"两条同时验通

用户 18:15 亲自改动作＝**锁链从她手上飞出去、一圈一圈绑到他身上**。我把它拆成**三镜三圈**（镜2 胸臂／镜3 背肩／镜4 膝），
首帧不新画、**从段1 选中成片（930）抽 12.40 s 那一帧**当 fl2va 锚。seed 20260930／362 帧／**697 s**／¥0，
产物 `h3_段2v2_缠身.mp4`（sha `9029d914b514f1bf`）。

- **锚这条正路成立**：第 0 帧对锚图 **MAE 4.74**（线稿那三条是 6.6–6.8），彩度 0.04 s 73.3 → 0.5 s 72.6 → 1.9 s 72.8 **不漂**，
  与段1 服装配色必然一致。**跨段外观一致的正解＝拿上一段选中成片的承接帧当下一段首帧，零成本，不要为新段另画静帧。**
- **"小肌肉动作换成整体位移事件"成立**：第一圈**过程看得见**（2.4 s 横过胸口 → 2.8 s 合到背上 → 3.2 s 两臂被贴身锁住）；
  躯干和重心全程参与（她拧转甩链、被拽时靴底打滑后坐、他转身—跪—前栽—脸着地），v1 的"只有手臂动"消失。
- ⚠️ **两半没到位**：第二圈在顶视角里只表现为**环带变宽**，"又一圈压过来"这个事件没演；第三圈**迟到一镜**——镜4 他站着弯腰腿上没东西，
  7.6–8.1 s（镜5）大腿上才出现那一圈。⇒ **同一拍内"第 N 圈"这种序数区分，H3 给不出；能给的只有"缠上了／缠得更宽"。**
- 🔴 **机检口径修正：运动量尺子判不了"僵"。** v2 帧间差均值 **13.92 < v1 的 15.05**、静秒 9 > 6，按尺子 v2"更不动"，人眼却是 v2 不僵。
  手臂乱挥在这把尺子上同样算运动量。"僵"＝躯干与重心是否参与，**结构判据不是能量判据**，只能逐帧看。
  （与 09-30 那条"本地运动量近确定性、可当判据"不冲突：**可复现 ≠ 判得对**，尺子本身选错了。）
- 切点最大误差 0.25 s（v1 0.08 s，退半步）；台词「铜钱不赊账」逐字同音被转写成「同錢不奢障」（v1 错一个字）**咬字比 v1 准**，不烧字幕（底部 >230 亮像素 0.0000）；
  音轨 mean −16.8 dB／峰值 0.95／零削波，比 v1 响 19 dB。
- ⚠️ 本轮**动作与挂锚两类变量一起动**（用户挑了"先挂上色首帧再看"后又追加改动作），"不僵了"不能单独归因给任一条。

### ★2026-09-30 深夜：段2 v4 换锚成功 ＋ 两把新尺子（qc_face / qc_style）的边界各被用上一次

**换锚（下一段首帧＝上一段成片帧）第二次生效**：v4 用 v3 自己 1.40 s 帧当首帧，镜1 删掉"转身"换回段1 那句甩链 ⇒
甩链飞行回到镜1、三人距离回到一整片空地、朝向守住（镜2 脸可见 94%、镜8 100%），切点最大误差 0.33 s，彩度 72.2→72.4 不漂。
**第三圈（膝）三版全迟到一镜（镜4→镜5）**，v2/v3/v4 措辞各异错在同一格 ⇒ 判为模型层，停止用改词追它。

🔴 **尺子边界 3 第一次真被用上**：`qc_face` 报镜5 从 v2 的 88% 掉到 v4 的 25%，看着像退步，
实际 v2 那 88% 是"**背对对手但脸朝镜头**"——正是文件头写的第 3 条边界。⇒ 脸可见率**不能单看**，
必须与逐帧表同读；真正判朝向的是"身体前侧朝哪"，那还得人眼。
`qc_style`（逐镜锐度＋彩度＋脸面积）也第一次抓到东西：v4 镜2 锐度 62.8、镜8 锐度 71.5／彩度 105.4 被自动标成"特写＋低锐度＝磨皮 CG 感"，
与人审"后边变 CG"对上；同时它的**边界 1** 也现形——镜3 锐度 243.7 不是实拍感强，是**一屏铜钱**。

## ★★2026-10-13 查清：通道4「本地脚本化出片流水线」动起来换人的根因（不是玄学，是接线）

用户报「参考图放第一张，动起来就换人」。顺着 `E:\LocalAI\本地脚本化出片流水线.bat` → `launchers\start-nl-pipeline.ps1` → `engine\nl_ui\server.py`（8790）→ `workflows\h3_i2va_video.yaml` 逐层实查，四条同时成立：

1. **UI 视频模式写死 fl2va 通道，且界面上没有 workflow 选择器**（`server.py` `workflow = body.get("workflow") or "h3_i2va_video"`，`index.html` 无该控件）。引擎里另有被标"**主力出片通道**"的 `workflows\h3_ref2va_video.yaml`，UI 走不到。
2. **多传的参考图被静默丢弃**：模板 `comfy/h3_i2v_fl2va_api.json` 里只有 **1 个 `__REF1__`**＋1 个 `first_frame`；`tasks.py` L882–891 给每张图生成 `__REFi__` 并把文件拷进 input 目录 ⇒ 文件看着在、**第 2 张起没有任何占位符接它**。23:13 那条日志实读 `参考图1张`。
3. **唯一进模型的那张是几何锚，不是身份条件**（已验的老账：`first_frame` 会被 VAE 重画，frame0 MAE 6.7–15.7；「锚管几何不管长相」）⇒ 一运动脸部细节由模型自己发明。
4. **他跑的那两条 `lora_strength=1.0`**，而 yaml 注释自己写着：turbo 8-step LoRA 满强度**有已知 identity drift（首帧是参考图、动起来换人）**，RunComfy 口径降 strength 换中性；**10-13 已改 0.7**（他跑时还是 1.0）。
5. 两条共犯：`use_llm_polish` **默认 true**，dashscope 把「让图中人物跳舞」改写成 `A person stands centered in a softly lit indoor studio…` ⇒ **主体被写成泛化 "A person"、场景凭空发明**；以及 `768×1344` 是 **4:7 不是 9:16**，G5 当场 warn"会被裁或变形"（首帧是 plain stretch 硬拉）。

⇒ **正解顺序**：要锁身份必须走 `h3_ref2va_video`（≤4 图 + `<Picture N> 是X`），代价是 ref2va **无 first_frame、构图与站位不锁**（09-15 那次"站位对不上"就是它）；fl2va 这边把 strength 降到 0.7／20 步不挂 LoRA、提示词自己写英文并核对改写回写稿、首帧换**已上色＋脸占比大**的静帧、画幅改 9:16 的 32 倍数解（576×1024 / 864×1536）。
⇒ **天花板仍在**：本机实测 H3 自身人脸保持上限 ArcFace ≈0.57，提示词/锚突破不了；换脸（inswapper 逐帧，`wzy/faceswap_*.py`，0.57→0.70–0.84）或脸关键镜走云端才是解。**CodeFormer 只治糊，不治换人。**
⇒ **通用判据**：判"我挂的参考图进没进模型"别看上传了几个文件，看日志里 `参考图N张` 与模板里 `__REFn__` 占位符个数是否相等。

## ★2026-10-13 晚：通道4 UI 已加「出片通道」+「中文→英文合规稿并填入」（改了哪、怎么验的）

- 改动三处，**生产文件一个字没动**：① 新建 `engine\workflows\h3_ref2va_play.yaml`＝ref2va 四图通道，只留 auto G 闸，**去掉 H3/H4 人工关口、不发飞书**（对齐他 09-23 给 `h3_i2va_batch` 的"不再人审"授权）；生成参数与生产 `h3_ref2va_video` 严格同配对（steps 4 ↔ ref2v 4-step LoRA、head_chunks 4、模板 4 个 `__REFn__`）。② `engine\nl_ui\server.py`：`VIDEO_CHANNELS`＝{fl2va→h3_i2va_video, ref2va→h3_ref2va_play}，新增 `POST /api/translate`（**复用引擎 `tasks.t_llm` + config.yaml 的 dashscope，不另起一套 LLM 逻辑**），首稿残留非英文字符自动做一次定点修补；ref2va 强制正好 4 张（少挂 400、多挂 400），fl2va 在 >1 张时明确告知"其余被模板丢弃"，并按 md5 报同图占多槽。③ `index.html`：出片通道下拉 + 翻译按钮，翻译后自动把润色置否（防二次改写把主体写成 "a person"）。
- **验证口径（可复跑）**：两份真翻译稿走**真闸** `tools/check_preflight.py --prompt-kind h3_i2va|h3_ref2va --channel h3 --only G7` ⇒ 均 **error=0 warn=0**；`/api/run` 的三种非法组合都在提交前 400（不占 GPU）；`run.py --list` 能列出新通道；`py_compile` 过。测试起在 **8791**，没动他正在用的 8790，测完已停。
- **仍未验**：ref2va 通道端到端出片（要 4 张真锚 + 4–8 分钟 GPU）；`<Subject N>` 与 `.anchor.json` sidecar 的 G3 身份核对（UI 上传的图没有 sidecar，只会 warn）。
- **改 UI 代码后必须重启 8790 才生效**：launcher 检测到 8790 活着就跳过启动，双击快捷方式不会重载 ⇒ 先停那个 python 进程再起。

## ★2026-10-14 凌晨：出片三模式已配到 UI（下拉预置）＋我一条归因被自己的看图推翻

- **UI 现在只有三种出片模式，参数全预置、不给精细微调**（`server.py` 的 `VIDEO_MODES`/`RATIOS`/`LENGTHS`，前端下拉由 `GET /api/presets` 单源填充）：
  `first` 锁首帧 1 图 → `h3_i2va_video`；`first_last` 锁首尾帧 2 图 → **新建** `h3_fl2va_dual_play`（模板 `comfy/h3_i2v_fl2va_dual_api.json`，由 `comfy/make_dual_template.py` 生成：多接一个 LoadImage 到 `last_frame`，其余节点与源模板逐字节一致）；`refs` 多参考图 4 图 → `h3_ref2va_play`。
  画幅 5 档全是 32 倍数：864×1536 / 576×1024 / 1536×864 / 1024×576 / 1344×768(7:4，G5 会 warn)；时长 4 档走 17n+5：124/192/243/362。出片模式下宽高与帧数输入框已隐藏。润色在出片路径彻底取消（`use_llm_polish` 固定 false），中文未翻译在提交前 400 挡下。
- **真闸自证**：两头夹模板被 `check_preflight` 认出 2 槽 —— 2 图 `G4 ✓ G7 ✓ error=0`，1 图 `G4 ✗ error=1`（反证到位）。
- 🔴 **我上一轮的一条归因是错的，已撤回**：我把"脸在画面里占的像素太少"列为他换人的共犯，**但没量过那张首帧**。实际看图（`engine/tmp/nl_ui/uploads/1791908951510_..._251_1.jpg`）＝半写实 3D 国漫女性立绘、单人、银冠长发白裙坐姿、**脸占画面很大且清晰** ⇒ "脸太小"不成立。性别级错换的重排成因：① fl2va 首帧只是几何锚、第 0 帧被 VAE 重画；② H3 把 CG 立绘往实拍真人拉的固有倾向（09-30 已记"一路拉到底"），风格一换性别特征最易被重造；③ 他渲染用 832×1216（0.684）而图本身是 9:16（0.5625）⇒ 首帧被 plain stretch 硬拉变形；④ 润色把主体写成无性别的 "a person" ⇒ 没有文字在抵抗。**③④已被这次改动堵住**（画幅预置 + 润色取消 + 翻译器强制写具体性别与形制）。
  ⇒ 通用教训：**别把"通用成因清单"直接当本批归因**，先看图/先量（同 [[feedback-evidence-loop-trap]]）。
- **仍未端到端验证**：`first_last` 与 `refs` 两条 play 通道都没真跑过（各需 6–15 分钟显卡）；两头夹的尾帧要"动作做完那一帧"，需另备图（即梦/FLUX i2i）。

## ★2026-10-14 凌晨（续）：档位矩阵 + 看图链跑通，两条踩坑记录

- **UI 现在是「模式 × 档位 × 画幅 × 时长」四个下拉，全预置**（`/api/presets` 单源，前端不抄第二份）。档位＝步数与 LoRA **成对**给（引擎里本来就有"4step LoRA 只能配 4 步"的硬校验，所以绝不让 UI 单独调步数）：
  `first`→ std8(h3_i2va_video，turbo@0.7) / draft4(同工作流 + turbo4step@1.0) / **fight8(h3_fl2va_fight_play，双 LoRA 模板 turbo@1.0 + Bunny_weapon@0.5)** / **clean20(h3_fl2va_clean_play，20 步不挂 LoRA)**；
  `first_last`→ std8/draft4 = h3_fl2va_dual_play，clean20 = h3_fl2va_dual_clean_play；`refs` 只有 refstd（ref2va 只有 4-step LoRA）。
- 新增两份模板（脚本 `comfy/make_nolora_templates.py` 生成，带前置断言）：`h3_i2v_fl2va_nolora_api.json`、`h3_i2v_fl2va_dual_nolora_api.json` —— **20 步不挂 LoRA 不能靠传空字符串**（`LoraLoaderModelOnly.lora_name` 空值＝ComfyUI 无效 LoRA 名），必须把 13 号节点摘掉、`4.model` 直接接 `2`。真闸核过：G4 槽位 1/2 各自正确、G7 骨架通过、G8 空 lora 自动跳过 LoRA 检查（error=0）。
- **娱乐流归档已独立**：UI 提交一律带 `--project 娱乐流 --output-root E:\图像影音资源池\娱乐流\批次`（G11 要求根含项目名），产物不再混进 无音/武昭君仪 的批次池。
- ★**看图链（qwen3-vl-plus）跑通，但两个坑**：
  ① 模型名——这把按量 key 的目录里**没有 `qwen-vl-plus`（404 model_not_found）**、`qwen-vl-max-latest` 是 **403 access_denied**，能用的是 **`qwen3-vl-plus`**（`E:\密钥文件\阿里多模态.txt` 那个专用 key 文件已不在盘上）。
  ② **我自己造的假 401**：`vl_look` 第一版漏了 `Authorization` 头 ⇒ 服务端回 401，我一度怀疑成 key 失效，跑了"三把 key × 三个模型"矩阵 + env/文件 key 指纹比对（`sha256[:8]` 相同 ⇒ env 就是文件#1，另两把 401 已死）才定位到请求本身。**教训：401 先核有没有带认证头，别急着怀疑凭证。**
- ★**反幻觉规则见效（这条最有价值）**：`COMMON_RULES` 第 6 条改成"具体只能来自用户写了的或看图清单有的，两者都没有就回指 `<Picture 1>`，绝不发明服装/家具/地面/窗/光源"。同一张图同一句中文需求，改前稿子编出 `cream cable-knit sweater / pale oak floor / sheer white curtains / distant birdsong`；改后＋看图 ⇒ `silver carved sofa, left hand supporting chin, cool blue-white key light from left front`（与立绘实物一致）。
- **ComfyUI 侧边栏 `user/default/workflows/` 吃的是 UI 格式（nodes/links），API 格式放进去不是画布** —— 六份引擎模板已挪进子目录 `娱乐流/API格式_非画布_先看这个说明/` 并留 README 说明对应关系；要可视化画布得按 UI 格式另搭（现成参照：上一级 `H3_首帧视频_T8_完整工作流.json`）。
- **未做**：二采档（`13-latent-upscale`，放大模型 `minimax_h3_latent_upscaler_3d_fp16.safetensors` 已在 `D:\Models\ComfyUI\latent_upscale_models\`，但本机从没接过这条链，且二采省算力不省内存）。
