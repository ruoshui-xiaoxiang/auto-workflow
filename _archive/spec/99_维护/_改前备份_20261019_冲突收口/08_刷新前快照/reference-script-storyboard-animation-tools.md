---
name: script-storyboard-animation-tools
description: 剧本/分镜/角色帧级动画开源工具盘点——GitHub star 排行 + Qoder 官方市场 + skills.sh 社区；pose-driven 模型(MusePose/DWPose/pose_inter)可替代 Godot K帧
metadata:
  type: reference
---

2026-09-12 全网检索成果（GitHub API 实拉 star + Qoder 官方市场 extension-market + skills.sh 社区），按用户三条能力线归档：剧本分析优化 / 帧级分镜 / 角色帧级分解建模。

**核心结论**：
1. 纯「剧本分析」高星开源工具**极少**，星高的是写作/编辑器类（betterfountain 450★ / Scrite 367★ / tuesday-js 688★，都是编辑器不分析）。最对口高星是 `0xsline/short-drama`(1194★，短剧全流程含**质量自检**) 和 `GongLingRui/screen-creative-skills`(402★，31个创作/评估/策划 agent)。
2. **星高≠分析深**：这些多是 prompt/agent skill（把方法论固化给 AI 用），与用户自研原则同类。用户剧本优化原则已相当完善，通用剧本 skill 价值有限；真正值得抄的是「质量自检/评估维度」。
3. **最大收获在「角色帧级分解」**：pose-driven 角色动画模型已成熟，可替代部分 Godot K帧——「真人/参考视频提骨骼 → 姿态序列驱动角色图 → 逐帧动画」。

**GitHub（带 star）**：
- 剧本/评估：`0xsline/short-drama`(1194★) · `GongLingRui/screen-creative-skills`(402★) · `GongLingRui/juben`(145★) · `neopen/story-shot-agent`(187★ PenShot 剧本→分镜→提示词→视频) · `taruma/SceneFlow`(122★ 剧本↔视频同步+AI成片评估) · `daisyu0608/script-up`(30★ 中文剧本分析 skill) · `tin2tin/Blender_Screenwriter`(226★ 剧本→3D场景)
- 分镜类：`colorAi/comfyui-storyboard` · `NickPittas/StoryboardUI2` · `smthemex/ComfyUI_StoryDiffusion` · `ComfyUI-Storyboard-LLM` · `0xsline/StoryGen-Atelier` · `62656456/ai-storyboard-director-v5.2`
- 角色帧级/姿态驱动：`TMElyralab/MusePose`(pose-driven i2v) · `MooreThreads/Moore-AnimateAnyone` · `HumanAIGC/AnimateAnyone` · `fssorc/ComfyUI_pose_inter`(关键帧姿态插值) · `IDEA-Research/DWPose` · `andreszs/ComfyUI-OpenPose-Studio`
- 短剧全流程：`xuanyustudio/LocalMiniDrama` · `alibaba/LumenX` · `HBAI-Ltd/Toonflow-app`

**Qoder 官方市场（extension-market MCP 可装）**：`script-to-storyboard`(剧本转分镜·标准分镜表) · `storyboard-generator`(剧本分镜表生成器·三帧法+静帧提示词+HTML) · `myreels-storyboard`(故事理解→角色三视图→镜头拆解 CSV) · `03-storyboard-prompter` · `story-bozo`(网文爽感分镜)。Seedance 系分镜 skill 因账号未开通暂略。

**skills.sh 社区（npx skills 可装）**：`zenstory-ai/drama-skills@short-drama-storyboard`(165) · `rainlib/ai-storyboard@film-storyboard-skill`(333) / `@scriptwriter-skill`(496) · `prime-skills/runcomfy-agent-skills@controlnet-pose`(356K) · `kinemotioninc/kinemotion@mediapipe-pose-detection`(82)。

---

**2026-09-15 复检（目标：找"导演 pass / 剪辑 pass"角色制 skill）——结论：没有整套现成的。**

- 本机 `~/.qoder/skills/` 36 个：**无导演/剪辑 pass 类**；`cinematic-video-production\references\script-and-qc.md` 只有"剧本创作原则 + 质量铁律"，**完全没有剪辑层**。
- **Qoder 官方市场**：`filmmaking` 查空；`director` 出 17 条，沾边三条 —— `aigc-director`(6 阶段：剧本→角色场景→分镜→参考图→视频→剪辑，与自有 skill 重叠但更粗)、`cloudaipro-film-director`(纯知识型 prompt，modelscope 导入 v1.0.0)、`video-director`(知识类短视频图文动画，**不相关**)。
- **skills.sh（括号＝装量）**：
  - `zenstory-ai/drama-skills@short-drama-storyboard`(189) —— **最接近**：中文短剧分镜，明写"切镜必须带来信息、权力、情绪、空间或节奏变化；同义重复镜头删掉"，带 references「镜头手艺」「生产镜头语法」。
  - `wuwangzhang1216/directorskill@cinematic-director`(24) —— 13 步导演/previs 流水线，含 beat map(opening emotion→pressure→turn→closing emotion ≈ 场景价值翻转)、"A shot with no story function is deleted, not improved"、**切点几何自检**(同轴两档景别，或一档景别+30°以上角度变化)。**但是一整条流水线，会与自有 skill 抢位置。**
  - `changhochien/film-production-team-skills`(24–37) —— 整套剧组角色(orchestrator/editor/script-supervisor/gaffer/producer/first-ad)，但 `film-editor` 是**后期剪辑**(EDL/粗剪/调色/混音，对着已有素材)，**不是开拍前的剪辑 pass**；装量极低。
  - `rainlib/ai-storyboard@film-storyboard-skill`(336) / `@scriptwriter-skill`(496)；`liangdabiao/seedance2-storyboard-generator`(115，Seedance 2 专用)。
- **结论：不装。** 可"借"的是 zenstory 的切镜判据措辞 + cinematic-director 的切点几何自检；但正确顺序是**先把参考片数据抽出来**，看数据说了什么再定判据 —— 反过来先抄清单就是又回到"建机器"（[[feedback-evidence-loop-trap]]）。整案见 [[project-narrative-role-pass-upgrade]]。
- **操作提醒**：git-bash 里 `node`/`npx` 不在 PATH —— 查/装 skills.sh 用 `PATH="$LOCALAPPDATA/nodejs:$PATH" npx --yes skills@1.5.22 find -- '<query>'`，**PATH 只在单条命令上限定**，不能留在环境里（会遮住好的 arkcli，见 [[reference-ark-account]]）。
- **未验证**：会话技能目录里出现的 `vox-video-director`、`happyhorse-prompt-studio` 在 `~/.qoder/skills/` 与 Qoder 安装目录都没找到落盘位置 —— 来路不明、内容未看，**不可当结论引用**。

---

**2026-09-15 补检：端到端短剧生产平台（用户问"全网有没有现成专业工作流"）——有，但全都停在「拼接」，没有人做叙事剪辑。**

| 项目 | ★ | 链路覆盖 | 成片方式 | 许可 |
|---|---|---|---|---|
| `HBAI-Ltd/Toonflow-app` | ~15.6k | 小说→剧本→角色/场景→分镜→生图→生视频→**角色配音绑定**→导出 | 无限画布＋FFmpeg 合并 | Apache-2.0＋补充商业协议 |
| `chatfire-AI/huobao-drama` | ~15.2k | 剧本→角色/场景/道具抽取→分镜→生视频→**FFmpeg 分镜合成+字幕**→整集导出 | 勾选分镜→合并 | **CC BY-NC-SA 4.0（禁商用）** |
| `MemeCalculate/moyin-creator` | ~4.5k | 剧本解析→角色/场景→分镜→批量生图生视频 | 多镜合并进 Seedance 一次生成 | AGPL-3.0 |
| `HKUDS/ViMax` | — | Idea/Script/Novel 三入口→角色一致性校验→分镜→生视频→拼接 | moviepy 按镜序 concat | MIT |

- **共同缺口＝没有「叙事剪辑」**：四家的合成全是按镜序 `concatenate`／FFmpeg 顺序拼，**没有一家读实际成片来判断该留该删**。Toonflow 官方 demo 自述"两分钟成片、原素材约三分钟、剪掉约一分钟废片、全程约两小时约 ¥130"，但那个"剪"是在**无限画布上人工挑轨删轨**，不是自动判断。
- **Toonflow 的"配音"不是 TTS**：源码看是拿**已上传的音频**用 LLM 匹配角色音色（表 `o_assetsRole2Audio`），得先自备声音素材。
- **魔因漫创走的是另一条路**：把相邻分镜**并成一组**、连同对白唇形提示词一起喂 Seedance 2.0，让视频模型一次生成多镜连贯片段，回避"逐镜拼接线太硬"——对"事件链不断"这个诉求有针对性。
- 这几家要接的云端模型（Seedance／Nano Banana／GPT-Image）用户**都有本地等价物**（自有 ComfyUI/H3/FLUX 管线），重搭等于造轮子；**可借的是它们的编排骨架，缺的那层要自己补**：读素材→标可用区间→按事件链取舍→出剪接单。
- **未完成**：商业平台（LTX Studio 一类）与 `waooAI/waoowaoo` 的源码级核查**这一轮没跑完**（检索子代理撞上额度上限）——别把它们当已核实结论引用。skills.sh 上那些 `filmmaker`／`film-team` 技能仍是**文字方法论、不是可执行管线**。

---

---

## 2026-09-20 追加：「有没有高星、完整、优质的工作流」核查（读 README + 文件树 + 发版/贡献者数，不看宣传语）

**判"完整优质"必须同时查这五项**（只看 star 会被骗）：`releases`（有没有正式发版）、`contributors`、`open_issues` 数与 star 的比例、最后提交日期、license。

| 项目 | star | 核查发现 | 判定 |
|---|---|---|---|
| `harry0703/MoneyPrinterTurbo` | 125k | v1.3.7/09-13、123 贡献者 | **真完整真维护，但类型不对**：素材是库存视频，无角色一致性/锁脸 → 营销号图文快剪 |
| `calesthio/OpenMontage` | 60k | **零正式发版**、52 贡献者、AGPL、2571 文件里 1957 个路径含 `skill` | 不是可安装软件，是给 Claude Code/Codex 驱动的**技能仓库**；覆盖面最广（含"从参考视频起步"复刻链）→ 读结构，不接管生产 |
| `HKUDS/ViMax` | 12.4k | v1.2.0/07-20、MIT、README 有"当前视频生成的局限/我们的解法"章 | **最接近剧情片端到端**（storyboard/character/consistency 都是明写卖点）；学术团队 |
| `HBAI-Ltd/Toonflow-app` | 15.8k | **open_issues=0**、10 贡献者、发版停在 06-08、最后提交 08-26 | 社区反馈读不出来，存疑；成本明细表格式可抄 |
| `ATH-MaaS/Pixelle-Video` | 28k | v0.1.15（0.1.x）、最后提交 06-14 | 主题→文案→出图→TTS→BGM 模板流水线；唯一值得看的是它 1 月加的**动作迁移模块** |
| `ZHO-ZHO-ZHO/ComfyUI-Workflows-ZHO` | 7.8k | 最后提交 **2024-12** | ⇒ **"高星 ComfyUI 工作流 JSON 合集"基本都已过时**，模型迭代比 JSON 快，别指望拿来即用 |

**核心结论（这条才是答案）：现成"完整流水线"全都把生成环节外包给云端 API（Seedance/可灵/MiniMax/即梦），所以它们完整的是**编排**，不是能力。**用户真正卡的两件事——动作拆解精度、跨镜角色一致性——恰好是这些工作流最薄的一层**；他本地这套（H3 + 逐拍拆解 + 锚点）在质量控制上比它们任何一条都硬。⇒ 正确用法是**读** ViMax 的跨镜一致性做法和 OpenMontage 的参考视频复刻链，**不是换工作流**。
（同族提醒：`MiniMax-AI/skills` 13.6k★、`Toonflow` 类"一键成片"包装厚，均属"看着热闹但接不上"。）

---

## 2026-09-20 GitHub 全量重盘（API 实拉，star/最近提交均核实；**没有一个装过或跑过**）

**方法（复用这个，别退回 WebSearch 猜数）**：无鉴权 GitHub Search API `sort=stars` 每查询 `sleep 7–9s`（10 次/分，超了 403 rate limit exceeded），核实单仓用 `/repos/{full}` 拿 `stars/forks/open_issues/subscribers/created_at/pushed_at/license`（core 60 次/时）。**看仓库必须同时看 created + pushed + open_issues**，只看 star 会被刷量骗。

**★ 直接命中用户 H3 链路的（最有价值）**：
- `MiniMax-AI/MiniMax-H3` **8.9k★ / 建 2026-07-30**＝H3 **官方开源权重仓**；用户本地跑的是 pruned INT8，官方完整权重＝清晰度阶梯最上层（未实测是否含 ComfyUI 配方）。`MiniMax-AI/cli` 2.1k★/推 09-19（文/图/视频/语音/音乐官方 CLI）、`MiniMax-AI/MiniMax-MCP` 1.6k★——**云端兜底通道有官方 CLI，不必再手搓 REST**。
- **训 LoRA 的两个候选**：`unslothai/unsloth` 76k★/推 09-19（描述明列支持 **MiniMax-H3 + FLUX**，含本地 UI）、`ostris/ai-toolkit` 12k★ MIT/推 09-19（FLUX/SD LoRA 专精，16GB 可用）、`kohya-ss/sd-scripts` 7.2k★（open_issues 909）。**角色一致性"每次都漂"的正解仍是训 LoRA，不是继续加锚点。**
- **动作生成（他自认的真瓶颈）**：`Tencent-Hunyuan/HY-Motion-1.0` 2.6k★/推 07-18＝文本→3D 人体动作，**带现成 ComfyUI 插件** `jtydhr88/ComfyUI-HY-Motion1` 313★（另一副本 Aero-Ex/ComfyUI-HyMotion 42★）。`IDEA-Research/DWPose` 2.8k★ 但**最后提交 2023-12**（停维护仍可用，反向从原片抽骨骼）。
- **烤字幕/脏尾**：`YaoFANGUK/video-subtitle-remover` **13k★**/推 06-30 本地去硬字幕·水印（**不损分辨率、无第三方 API**）→ 直接对治"H3 把台词烧进画面"；`sczhou/ProPainter` 7k★ + `daniabib/ComfyUI_ProPainter_Nodes` 403★ 视频修补。
- **超分/补帧**：`OpenImagingLab/FlashVSR` 1.9k★（CVPR2026 实时扩散视频超分，16GB 可行性未测）、`k4yt3x/video2x` 21.7k★（**AGPL**）、`xinntao/Real-ESRGAN` 36.8k★**但 2024-08 后没动**、`hzwer/Practical-RIFE` 1k★ MIT（补帧；**只补帧，救不了动作本身不连贯**）。**`sczhou/CodeFormer` 18k★ 是 NOASSERTION（非商用研究授权）→ 片子要卖就得换。**

**数字人/口型（桌宠可能用得上）**：`met4citizen/TalkingHead` 1.6k★＝**JS/three.js 实时口型驱动全身 3D avatar**（浏览器原生，契合 Electron 桌宠"WebM 动作＋TTS 两张皮"）；`Kedreamix/Linly-Talker` 3.5k★；`antgroup/ditto-talkinghead` 886★。

**语音（变老/童声天花板的候选）**：`RVC-Boss/GPT-SoVITS` 61.9k★（1 分钟样本克隆）、`OpenBMB/VoxCPM` 37.8k★/推 09-02（VoxCPM2 无 tokenizer、主打真人感）、`FunAudioLLM/CosyVoice` 23.7k★、`SWivid/F5-TTS` 15.3k★（在用，推 2026-07）、`SYSTRAN/faster-whisper` 25.5k★但**停更 2025-11**。

**成片流水线（结论：读，不装）**：`calesthio/OpenMontage` 60k★（建 2026-03-29，**AGPL-3.0**，"12 流水线/700+ skill"）、`HKUDS/ViMax` 12.4k★ MIT、`ATH-MaaS/Pixelle-Video` 28k★、`harry0703/MoneyPrinterTurbo` 125k★（模板营销号向，非叙事）。

**🚩 热度指标反面教材（按 [[feedback-low-expectation-external-capability]] 处理）**：
- **star 高但 `open_issues=0`＝存疑**：`HBAI-Ltd/Toonflow-app` 15.8k★ 却是 0 issue（建 2026-01-29）→ 社区真实反馈读不出来。
- **star 与积压严重失衡**：`stablyai/orca` 72.5k★ 配 **6286 个未处理 issue**、watchers 仅 128 → 热度高但用不动。
- **宣传词型新贵**：`JuliusBrussee/caveman` 106k★（"像原始人说话省 65% token"）、`MemPalace/mempalace` 59k★（"best-benchmarked"）——只读 README，**不进承重位**。
- 值得读的一个：`obra/superpowers` 288k★ MIT＝agentic **skills 框架**，与用户自有 skill 体系同类，可借鉴组织方式（另 `openclaw` 390k★、`heygen-com/hyperframes` 51.6k★ "Write HTML. Render video. Built for agents" 做动效字幕可一看）。
- 许可注意：`Comfy-Org/ComfyUI` 133.9k★ GPL-3.0；`infiniflow/ragflow` 91k★；`ollama` 181k★（用户在 Windows+NVIDIA，Apple Silicon 系 `Rapid-MLX`/macOS 系全部无视）。

## 2026-09-25 追加：ComfyUI 里的"3D 导演台"确实有了（他问"comfyui 现在支不支持 3D 导演台"）

**`arturitu/ComfyUI-scene-camera-action`** v0.5.0 —— **不是通用 3D 查看器，就是给 AI 视频做 previz 的**（README 原话"Stop prompting movement into a black box"）。核查项：45★、**最后提交 2026-09-01**、单作者、**pyproject 声明 MIT 但仓库里没有 LICENSE 文件（GitHub license API 404，README 那个 LICENSE 链接是死链）** ⇒ 内部 previz 可用，别当已核实授权。

- **三段节点**：`StagingNode`（白模搭景＋即时碰撞体，Orbit/Pan/Zoom，Group/多选取）→ `ActingNode`（**WASD 实时开角色**、练习彩排模式、多角色链式录制＋同步幽灵回放）→ `DirectingNode`（TPV/FPV/侧跟/自动框取，**防穿墙弹簧臂**，切镜时间轴）→ 输出标准 ComfyUI `VIDEO`（720p），**README 明写接 Seedance 2.5 / 2.0 Fast 或 MiniMax H3 Reference-to-Video**。
- **三个对我们特别合适的点**：① 跑在浏览器 **WebGL**，**不占显存**（按需渲染，导航节点图时自动暂停）；② 依赖只有 `pillow / numpy / typing_extensions`，**完全不碰 torch** ⇒ 装它零风险，符合"装前 dry-run 护 torch"；③ **自带 `skills/stage-builder/SKILL.md`，专门给 AI 编码代理用**——我用自然语言或参考图就能生成场景 JSON 预设落 `presets/`。基础工作流"0 AI models required"。ComfyUI Manager / `comfy node install` / git clone 三条装法都通。
- **三条限制（别当万能）**：角色只有 **Human / Car / Quadruped 三种，动画只有 idle/walk/run/sit** ⇒ 它给的是**站位、路径、机位、运镜**，**给不了打戏**；多人 v0.4/0.5 有但仍要避开肢体交叉；**预设全是西方场景**（`courthouse_square` `gas_station` `liberty_beach` `race_track` `space_platform_track` `collapsed_warehouse` `industrial_ruin` `varied_forest` `test-collider`），**没有一个中式古建**，洛阳民宅／夹层／霓虹下层区全得自己写 JSON（只有 `collapsed_warehouse` 勉强能改货栈）。
- **ComfyUI 自带的 `Preview3D` 只是模型查看器，不是导演台**，别混。
- **定位判断**：这条**不违反** 09-15 定的"不搭虚拟影棚/UE5"（见 [[project-ai-first-direction]]）——那条否的是拿引擎出成片，而这个恰好是允许的"引擎降级为条件供应方，previz 喂 AI"。而且比我们无音那套 Godot 白模强在：Godot 踩过 **DWPose 读不出灰模**、灰模特写无脸不能 QC（[[project-referee-layer]]、[[feedback-previz-closeup-limitation]]），这个直接出 RGB 视频走 H3 ref2va 已验通能吃的 `reference_video` 通道。
- **但收益未验，且有反例在前科**：同一个 T8 包里 2026-09-13 深度图灌 H3 已被人审判废（见 [[reference-minimax-h3-local]]）。RGB 白模当参考视频是**不同**通道，失败不自动转移，但说明 H3 的控制通道整体偏弱，**不能承诺接得住**。
- **决定（2026-09-25）**：**不现在装**，等武昭君仪批 1 开工时当**附带对照**装进来试一个货栈镜，不另立验证项目（[[feedback-evidence-loop-trap]]）。

---

**How to apply:** 用户要做剧本优化/帧级分镜/角色分解/导演·剪辑 pass 时先查本表选型；**报工具一律带 star＋最近提交＋许可，并明说"我没装过/没跑过"**；**找"可参考的分镜实物"（分镜集 / 絵コンテ / CC-BY 成片 / 从成片反推）走 [[reference-storyboard-reference-sources]]**；**已知无"角色 pass 制"现成方案**，要走自建（见 [[project-narrative-role-pass-upgrade]]）；角色动画优先评估 pose-driven 路线（[[feedback-animation-decomposition]]）而非盲目铺 Godot K帧（[[project-frame-by-frame-animation-exploration]]）；装 skill 走 qoder-find-extensions 流程。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- GitHub star 排行+Qoder 市场+skills.sh
- pose-driven 可替代 K 帧
- ⚠️许可红线 OpenMontage=AGPL／CodeFormer=非商用
- **★高星核查结论：现成"端到端影视流水线"完整的是编排不是能力，全外包云端 API，替代不了动作拆解与角色一致性**
- **★2026-09-25：ComfyUI 里确有 3D 导演台 `arturitu/ComfyUI-scene-camera-action`（WASD 演角色＋运镜→出 VIDEO 喂 H3/Seedance，WebGL 不占显存、依赖不碰 torch、自带给 AI 代理的场景 JSON skill），但角色只有 walk/run/idle＝给不了打戏、预设全西方无中式古建，未验，等批 1 当附带对照**

---

## 2026-09-28 复核（用户问"能不能用 GitHub 开源补短板"，并质疑"星太低了吧"）

**★判档三指标（star 只是热度，会骗人）**：① 有没有正式发版/tag；② **有没有打包进 PyPI 且有真实下载量**（＝有人替你踩过坑，比 star 硬）；③ 近 6 个月是否仍在 push。实测对照：`soCzech/TransNetV2` 只有 1,046★、2023-12 停更，但打包版 `transnetv2-pytorch` **近一周 9,151／近一月 31,027 次下载**；反过来 `harry0703/MoneyPrinterTurbo` 126,367★、当天还在推、MIT，却是营销号模板流水线，与我们的活无关。

**★用户口径（要记住）**：**低星的东西绝不配占"承重位"**；低星只允许两种用法——**一次性外挂**（装上跑一条、出产物即交付、坏了只废那一条）或**读物**（只读架构、不接管生产）。发版／PyPI 下载／推送频率三项过关才谈进流水线。

**诚实边界：分镜可视化这块 GitHub 上没有高星方案，不是没找到，是这个场是空的**——`camera motion previz` 全站只命中 4 条、其中 3 条 0 star。⇒ 这条短板**不走开源**：要么用他账号里已有的商业件（可灵／即梦自带分镜与故事板），要么自建（分镜表本就是结构化文本转 HTML，用现成 canvas/Sites 两百行内）。

**许可红旗（进产物前必看，全是本轮实查）**：`sczhou/CodeFormer` NOASSERTION（非商用）、`k4yt3x/video2x` AGPL-3.0、`AaronFeng753/Waifu2x-Extension-GUI` NOASSERTION、`Tencent-Hunyuan/HY-Motion-1.0` NOASSERTION（其 ComfyUI 插件 `jtydhr88/ComfyUI-HY-Motion1` **无 LICENSE 文件**）、`liangdabiao/Seedance2-Storyboard-Generator` NONE、**`MiniMax-AI/MiniMax-H3` 官方权重仓也无 LICENSE 文件**。无授权文件＝默认保留所有权利：读源码可以，进产物不行。

**"端到端影视流水线"仍只是编排（负面证据更新）**：`RayVentura/ShortGPT` 7,988★ 但最后推送 **2025-02-10**（实质停摆）；`AIDC-AI/Pixelle-Video` 28,471★ Apache-2.0 停在 2026-06-14；`google-research/frame-interpolation`(FILM) **已归档**；`AI short drama pipeline` 查询 48 条命中全是 500★ 以下的年轻项目（`wind-comic` 586★／`openshorts` 27★／`comfy-agent` 25★——架构可读、能力没有）。仍在维护的剧情片向端到端只有 `HKUDS/ViMax`（12,511★ MIT、push 2026-09-20）⇒ **读它的跨镜一致性做法，不接管生产**。

**⚠️ 记忆里的仓库名会失效**：`Wandmappers/Storyboarder`、`hacksalot/Storyboarder`、`KIT-Screendraft/Scratch`、`linyi0210/NarratoAI` 本轮直连**全 404**（改名或下架）。⇒ **报工具名一律先 `/repos/{full_name}` 现拉一次**，别拿本文旧条目当目录。

**建议的最小试点（未执行）**：只装 `Breakthrough/PySceneDetect`（5,204★ BSD-3、有正式发版、纯 Python 不碰 torch、2026-09-21 仍在推）出一张"参考片切点表"，对着"一镜一拍／相位不重叠"判据看差多少；`YaoFANGUK/video-subtitle-remover`（13,077★ Apache-2.0）作一次性外挂治"H3 把台词烧进画面"。其余（`ostris/ai-toolkit` 12,143★ MIT、`unslothai/unsloth` 76,891★ Apache-2.0）留作角色 LoRA 候选，装前先估显存。
