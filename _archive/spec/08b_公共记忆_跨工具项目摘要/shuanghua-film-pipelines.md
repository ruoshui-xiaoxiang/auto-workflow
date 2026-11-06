# 霜华影片生成管线 — SDXL/FLUX 出图 + HunyuanVideo 1.5 I2V 视频

## 基础信息

- 项目名：shuanghua-film-pipelines
- 位置（代码根目录）：Qoder 工作区 `C:\Users\若水\Documents\Qoder\2026-08-27\4543d0f4\`（管线脚本）+ `E:\LocalAI\ComfyUI_windows_portable\`（执行端）+ `E:\创作\一剑霜寒\`（影片资产）
- 定位（一句话）：AI 古装短片的**全本地生成管线**（《一剑霜寒》霜华 + 《无音》）——出图、锁定图直出 I2V、音轨后期、逐帧超分与模板管理
- 当前版本 / 里程碑：《无音》demo 全链路交付（直出草稿+音轨+超分，2026-09-07）；八极拳双重重绘路线已关闭
- 最新更新：2026-09-07 13:46
- 摘要：**标准出片流程定稿**（见使用说明）＝定妆照→锁定分镜图→锁定图直出 I2V 零重绘 480p 草稿→目检→逐帧超分正片——480p 草稿（60s/镜）→ 4x-UltraSharp 超分（35s 片约 20 分钟 GPU，完胜 lanczos 锐化），**720p 重生成路线废弃**；《无音》7 镜 demo 已交付含 BGM/音效/童声 TTS 混音版；音效走 Pixabay 详情页 JSON-LD 直链抓取，台词走 qwen TTS 童声候选制

## 当前状态（快照）

- 核心功能：角色定妆出图 → 锁定图直出 I2V（480p 草稿）→ 音轨混音（BGM/SFX/TTS）→ 逐帧超分出正片 → 飞书交付
- 主要模块路径：`hv15_i2v.py`（视频主管线）、`templates/`（5 个 API 格式模板）、`run_wy_draft.py`（分镜批量草稿）、`build_wuyin_audio.py`（混音）、`tts_wuyin_child.py`（TTS）、`sr_compare.py`+`sr_full_video.py`（超分）、`flux_*.py`/`sdxl_*.json`（出图）
- 技术栈：ComfyUI 便携版（torch 2.13.0+cu130，RTX 5060 Ti 16GB）+ HunyuanVideo 1.5（8.3B DiT）+ FLUX/SDXL + SageAttention 2.2.0 + lark-cli 飞书交付
- 执行端实例：`run_nvidia_gpu_sage.bat` 启动（`--use-sage-attention` 单开；**不带** `--fast fp16_accumulation`，实测有害）

## 工作流详情

### 1. HV1.5 I2V 视频主管线（hv15_i2v.py）

官方单 pass 结构（2026-09-06 逐 link 核对官方模板修正过接线）：
`UNETLoader → [EasyCache 可选] → ModelSamplingSD3(shift) → CFGGuider(cfg) → SamplerCustomAdvanced(euler/simple) → VAEDecode[或 Tiled] → CreateVideo(24fps) → SaveVideo(auto/h264)`
旁路：`DualCLIPLoader(qwen_2.5_vl_7b_fp8_scaled + byt5_small_glyphxl_fp16) → CLIPTextEncode×2`、`CLIPVisionLoader(sigclip) → CLIPVisionEncode`、`LoadImage → HunyuanVideo15ImageToVideo(start_image+clip_vision_output) → latent`

**关键接线铁则**：BasicScheduler 的 model 输入必须接**原始 UNETLoader 输出**，只有 CFGGuider 吃 ModelSamplingSD3(shift) 后的模型；接反 = sigma 时间表错位 = 51 分钟纯雪花噪声且全程无报错（已实锤一次）。

**四档位实测矩阵（49f 720×1088 热态，2026-09-06）**：

| 档位 | 参数 | 49f | 121f 外推 | 画质 | 用途 |
|---|---|---|---|---|---|
| 正片默认 | 720p cfg_distilled fp8_scaled, cfg1, 20步, shift7, 普通解码 | 7.2 min | ~26 min | 干净 | 交付正片 |
| 正片+EC | +EasyCache(0.2/0.15/0.95) | 4.8 min | ~15 min | 干净（实证） | 正片提速 |
| 迭代快档 | +EC+VAEDecodeTiled | 3.1 min | — | 背景高频区细网格纹 | 仅内部迭代 |
| 480p 草稿 | 480p step_distilled, cfg1, shift7, 12步, 480×720 | **60 s** | — | 干净 | 试镜头/种子 |

历史基线：基础版 fp16 cfg6 = 49f 17.5 min / 121f 78 min。蒸馏 1.9×、sage 采样 1.87-2.19×、EC 2.2×（跳 11/20 步）。

### 2. SDXL 出图线（6 风格工作流 JSON）

`sdxl_guofeng_real.json`/`_lora.json`（国风写实）、`_best_guoman_workflow.json`（国漫定稿）、`sdxl_guoman_25d(_v2)/fantasy/fullbody/xianxia.json`（变体）。用于角色定妆与风格探索。

### 3. FLUX 参考图/关键帧线

Redux/IPAdapter 参考定人：`flux_redux_batch.py`、`flux_redux_front.py`、`ipadapter_workflow.json`；分镜批量 `flux_storyboard_7shots.py`；打斗关键帧 `flux_sword_slash_30f.py`。**已知限制：FLUX 无法生成武器（剑）**——武打正片必须走 I2V 视频线补剑。

### 4. 打斗动画 v1（过渡方案，已交付）

`batch_fightgen.py` 批量出 9 帧（seed 777 定人）→ `review_fightgen.py` contact sheet 目检 → `assemble_fight.py` 拼 MP4/GIF。骨架支撑：`batch_dwpose_score.py`、`stickman_fight.py`、`extract_frames_dense.py`。v2 路线 = 打斗关键帧作 I2V 首帧（人物一致性天然解决 + 视频模型能出剑）。

### 5. 直出画面稳定性归因（2026-09-07《无音》7 镜复盘，供参考/沉淀）

《无音》草稿流畅稳定的四个原因，按贡献排序——**稳 = 让模型只做它擅长的事（在一张好图上做小幅运动）**：

1. **零重绘、首帧即锁定分镜图**（最关键）：视频第一帧就是精修 locked 分镜原图，构图/色彩/人物位置 t=0 像素级固定，模型只需"让图动起来"不凭空发明场景；对比八极拳"参考图→Redux 重绘→I2V"两级重绘层层衰减必飘必崩
2. **镜头类型选对**：慢叙事镜头（人群动态/递接/互动/微距/缓步跟随）是 I2V 甜点区；快动作至今不行——画面稳一部分是"题目出得保守"
3. **提示词压制运镜**：每条写"固定机位/极缓推近"，严禁 dynamic camera 类词，动作 5s 起承收逐拍拆解，场景描述不与首帧冲突
4. **蒸馏模型 + cfg1.0 + 同 seed 888**：采样轨迹短而稳、无引导振荡、七镜风格统一；原生 24fps 免插帧 + ffmpeg 无重编码 concat 保流畅底线

## 使用说明

**标准出片流程（2026-09-07 定稿，全链路已验证）**：

```
定妆照锁人物 → 分镜图按定妆照返工锁定（locked\）→ 锁定图作 I2V 首帧出 480p 草稿
→ 用户目检通过 → 全片 UltraSharp 逐帧超分出正片（1792x1024 master）→ crf22 压飞书版
```

两个前提（缺一个稳度就掉）：
1. **首帧必须是精修且内容定稿的图**：I2V 像素级继承首帧的一切，穿帮/瑕疵会被运动放大——首帧定稿前不出视频；且分辨率与视频分辨率**严格等比 + mod16 对齐**（1792x1024→896x512），否则裁切变形毁构图
2. **好首帧是必要非充分条件**：还需镜头类型在 I2V 甜点区（慢叙事，快动作不行）+ 提示词压制运镜 + 蒸馏/cfg1.0/同 seed，三条同时成立才稳（归因详见工作流详情第 5 节）

**视频生成（脚本路，推荐）**：
```
py hv15_i2v.py <图路径> "<英文运动提示词>" [选项]
# 正片默认：无额外选项（蒸馏+cfg1 已为默认）
# 提速档：--easycache        快档：--easycache --tiled
# 草稿：--draft --width 480 --height 720
# 其他：--seed --steps --cfg --shift --length --prefix --model
```
跑完 stdout 打印 `OK -> video/xxx.mp4`（相对 `E:\FLUX_Workflow\ComfyUI_output\`）。

**视频生成（浏览器路）**：ComfyUI UI → 左侧「工作流」→ 点 `hv15_dist720_cfg1` 等模板名（API 格式 JSON 新版前端直接开成节点图，已实测）→ 换 LoadImage 的图、改提示词 → 运行。

**交付**：lark-cli 发"吕湘"群 `oc_4f43e84db8b16403e036eb54d57bf49f`；`--video` 必须配 `--video-cover`，且**不能与 `--text` 同发**（视频和文字分两条）；路径只认 cwd 相对。

**抽帧目检**：ffmpeg 不在 PATH，用 `py -c "import cv2..."`；帧写 ASCII 目录 `E:/LocalAI/temp_frames/`。

## 重要改动记录

### 2026-09-07 ｜ 管线转向定稿：《无音》demo 直出 + 音轨 + 超分全链路交付
- 摘要：①八极拳 720p 正片被驳回关闭（根因=Redux+I2V 双重重绘两级损耗，参考图从未像素级参与），转向**锁定图直接作 HV1.5 I2V 首帧零重绘**，形象保真用户认可；②《无音》哑女短剧 7 镜×5s 480p 草稿全交付（`run_wy_draft.py` 批量+自动拼接），能力天花板判定=慢叙事镜头（人群/递接/互动/眼瞳微距/跟随/克制微动作/纹理）可直出，快动作不行；③**清晰度正解=逐帧超分**：本地 `upscale_models/4x-UltraSharp.pth` + ComfyUI 内嵌 python spandrel 推理（不动系统 torch），4x 后 lanczos 缩回 2x（896x512→1792x1024），35s 片约 20 分钟 GPU，对比实测完胜 lanczos+unsharp，**720p 重生成（3.5-4h）废弃**；④音轨管线跑通：BGM+按镜头音效+童声台词 ffmpeg amix（`-c:v copy` 不重编码），音效源 Pixabay 详情页 JSON-LD 直链 curl 直下，台词走 qwen-audio-3.0-tts-plus 童声 instruction 候选制（A/B 发飞书试听）
- 影响范围：今后所有短片的出片标准流（480p 草稿→目检→超分出正片）；音频后期不再依赖外部工具
- 相关文件：工作区 `run_wy_draft.py`/`build_wuyin_audio.py`/`tts_wuyin_child.py`/`sr_compare.py`/`sr_full_video.py`；分镜 `E:\创作\杂项素材\新建文件夹\视频生成提示词.md`；产物 `E:\LocalAI\wuyin\`（v2 混音版 / v3_sr 超分 master 36MB / v3_sr_web 飞书版 20.5MB，音频素材在 `audio\` 子目录）
- 决策/结论：定妆照类分镜图需锁图后作首帧（locked\ 目录）；提示词工艺=场景不与首帧冲突+服饰锚点复述+逐拍拆解+镜头克制+cfg1.0 全正向；飞书 30MB 门槛用 crf22 重编码（画质无损感），高码率版留本地当 master
- 待定：童声配音 A（软糯五岁，已用）/ B（活泼六岁）待用户飞书回复，重混 30 秒

### 2026-09-06 ｜ 四项提速优化收尾（sage/EC/tiled/480p 全实测）
- 摘要：Sage Attention 2.2.0（woct0rdho 轮子 cu130torch2.10+ abi3 + triton-windows 3.8，阿里 PyPI 源）装入便携版，采样 1.87-2.19×；EasyCache 做成 --easycache 开关（2.2×，画质实证干净）；480p step_distilled 模型下载（8,335,127,098 字节校验）+ --draft 预设（60s/条）；**fp16_accumulation 实测有害弃用**（720p VAE 解码 60s→335s）；**VAEDecodeTiled 有背景网格纹**降级为快档专用（必填 temporal_overlap）；最终 bat = run_nvidia_gpu_sage.bat（sage 单开）
- 影响范围：全部 720p 视频生成耗时；模板与脚本默认值
- 相关文件：`hv15_i2v.py`、`templates/`、`E:\LocalAI\ComfyUI_windows_portable\run_nvidia_gpu_sage.bat`
- 决策/结论：正片=蒸馏+sage+普通解码；EC 按镜头开（武打大动态默认关）；tiled 仅迭代；480p 做草稿

### 2026-09-06 ｜ 模板注册进 ComfyUI 工作流库
- 摘要：`templates/` 5 个 API 格式 JSON（hv15_base720_cfg6 / dist720_cfg1 / dist720_ec / fast720_ec / draft480_12s，由 build_workflow 导出保证与代码同步）复制进 `ComfyUI/user/default/workflows/`；浏览器实测新版前端可直接开成节点图
- 决策/结论：用户自行切模板起模型走浏览器路；脚本路走命名开关

### 2026-09-06 ｜ HV1.5 I2V 管线跑通并交付首支成片
- 摘要：四件套下载（720p_i2v_fp16 16.65GB + qwen_2.5_vl 9.38GB + byt5 0.44GB + vae 2.52GB，hf-mirror 直连）；首版工作流纯噪声翻车（误把模板旁路 SR 双 pass 当主结构 + 调度器接错模型）→ 修成官方单 pass；49f 验证一次通过；121f 成片 78 分钟交付飞书（月下雪崖回眸，全段一致无崩坏）；蒸馏版 A/B 1.9× 同日落定
- 相关文件：`hv15_i2v.py`、`hv15_i2v_template.json`（官方模板参照）、`resume_dl.sh`

### 2026-09-05~06 ｜ 打斗动画 v1 交付 + FLUX/SDXL 出图线定型
- 摘要：9 帧打斗关键帧（seed 777）→ MP4/GIF 交付；SDXL 6 风格工作流与 FLUX Redux 定人链验证完毕；确认 FLUX 无法生成武器、Redux 与全身姿态不兼容
- 决策/结论：武打 v2 走 I2V 首帧路线

## 当前待办 / 阻塞

- [ ] 自然语言一键调用层：智能体主路径；relay 关键词规则兜底；本地小模型/云端 API 解析器**配置项默认关**（用户拍板）；稳定性护栏（watchdog/探活/重提/必通知）
- [ ] 《无音》后续：童声配音 A/B 待用户飞书选型后重混；正片级 720p 直出是否必要待评估（超分版或已够）
- [x] ~~30 秒重剑武打短片~~：经 15s 玄铁重剑（草稿两轮驳回）→ 八极拳空手（720p 正片被驳回）演变，**整个双重重绘路线已关闭**，由「锁定图直出」取代（见 2026-09-07 改动记录）
- [ ] 可选：超分提速（当前 ~3fps，可试 fp16 批量/多帧 batch）；SeedVR2 视频修复模型对比（未安装）

## 关键路径速查

| 内容 | 路径 |
|---|---|
| 视频主管线脚本 | 工作区 `hv15_i2v.py` |
| 视频模板（5） | 工作区 `templates/` + `ComfyUI/user/default/workflows/` |
| 模型权重 | `D:\Models\ComfyUI\diffusion_models\`（junction）；text_encoders 同 |
| 输出视频 | `E:\FLUX_Workflow\ComfyUI_output\video\` |
| 抽帧中转（ASCII） | `E:\LocalAI\temp_frames\` |
| 启动 bat（生效） | `E:\LocalAI\ComfyUI_windows_portable\run_nvidia_gpu_sage.bat` |
| ComfyUI 日志 | `E:\LocalAI\ComfyUI_windows_portable\ComfyUI\user\comfyui.log` |
| 角色资产 | `E:\创作\一剑霜寒\角色\霜华\`（v4/v5 定妆照） |
| 《无音》分镜+产物 | 分镜 `E:\创作\杂项素材\新建文件夹\视频生成提示词.md`；成片 `E:\LocalAI\wuyin\`；音频 `E:\LocalAI\wuyin\audio\` |
| 超分模型 | `E:\LocalAI\ComfyUI_windows_portable\ComfyUI\models\upscale_models\4x-UltraSharp.pth`（spandrel 加载，须用内嵌 python） |
| 下载器 | 工作区 `resume_dl.sh`（hf-mirror 直连、断点续传、字节校验） |

## 注意事项 / 踩坑提醒

- **接线铁则**：BasicScheduler 接原始 UNet，CFGGuider 接 shift 后模型；接反出纯噪声且不报错（进度条正常走完）
- **shift 随分辨率/模型变**：720p i2v=7、480p cfg_distilled=5、480p step_distilled=7；别抄错
- **fp16_accumulation 禁用**：Blackwell 上使 720p VAE 解码慢 5 倍；sage 单开才是最优
- **VAEDecodeTiled**：必填 temporal_overlap（漏了 HTTP 400）；有背景网格纹，只做快档
- **ComfyUI 节点缓存跨 prompt 生效**：同进程内相同输入节点直接复用——A/B 计时防假快（改 seed 或重启）；重解码不换采样时可白嫖
- **重启 ComfyUI 前必须确认队列空**（GET /queue）；bat 末尾 pause + taskkill 会累积 cmd 尸体窗口（用户可见），代理重启改用 Popen(CREATE_NO_WINDOW)
- **中文路径**：cv2.imwrite 静默失败 → ASCII 中转 + shutil；Git Bash 会 mangle 中文 PATH；`taskkill /PID` 要加 MSYS_NO_PATHCONV=1 或走 Python subprocess
- **Python 启动器**：本机用 `py`；`python` 不在 Git Bash PATH、`E:/LocalAI/python/python.exe` 不存在
- **SaveVideo 参数**：format 只认 auto/mp4 且 codec 必填（h264）
- **下载镜像**：hf-mirror.com 直连 ~36MB/s 不走代理；GitHub 轮子走 gh-proxy.com；PyPI 轮子阿里源（清华源 403）；**绝不改 torch 版本凑轮子**
- **lark-cli**：--video 不能与 --text 同发；video/cover 只认 cwd 相对路径；成功判据 ok==true
- **飞书 30MB 视频硬限**：1792x1024×35s crf18=36MB 被拒；crf22 重编码 →20.5MB 肉眼无损；音频走 --file（mp3 可发，--audio 只认 Opus）
- **Pixabay 音频直链**：搜索页无直链，**详情页 JSON-LD script 含 cdn download URL**（evaluate_script 提取）；浏览器 viewport 隐藏时 click 不可用但 evaluate_script 可用；curl 带 UA+referer 即可下载
- **超分注意**：spandrel 只在 ComfyUI 内嵌 python（系统 py 没有）；inference tensor 不能 inplace（clamp_/mul_ 会报错，用非 inplace 链+clone）；`py` 启动器跑不了含 spandrel 的脚本
- **qwen TTS 中文 payload 必须写 UTF-8 JSON 文件 --data-binary 发**（curl -d 内联中文在 git-bash 编码坏掉报 411）；token-plan 只有 qwen 系音色，老人/童声无系统音色全靠 instruction
- **16GB 显存互斥**：跑视频时 FLUX 让位；121f 显存贴满 16GB 未 OOM 但引发块交换（1.8× 开销来源）
- **本机蓝屏观察期**：14 天 10 次内核蓝屏（内存损坏类，XMP 已降 4800MT/s）；GPU/内存超频搁置，纯软件侧优化
- **qwen_2.5_vl 是 HV1.5 内置文本编码器**，不是云端千问 LLM，别与兜底链混淆
