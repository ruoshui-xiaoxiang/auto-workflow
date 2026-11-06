# 结构锁 + 机器裁判（previz → 出图 之间的 QC 门）

> 2026-09-14某竖屏短片镜1的4关键帧实验，2026-09-21修订证据边界。
> 可选路径：灰模关键帧 → FLUX ControlNet静态结构控制 → 出图 → 机器初筛 → 用户审核。
> 机器标红不是删除，未标红也不等于人审确认。

## 一、局部实验结论

1. **结构条件不锁角色身份**。该批灰模实验中检测器未提取到可靠人形骨架；不能泛化成所有控制通道“长不出人”。身份仍需指定角色参考与QC。
2. **该批lineart（Canny预处理路径）结构指标较好**，不是所有画面的通用排名：
   - 边缘覆盖率：lineart 73%，纯提示词15.6%，Seedream i2i 45.5%。
   - 深度相关：lineart约0.84，Seedream约0.28–0.31。
3. **该批DWPose未识别简化灰模**，空白pose输入不能评估控制能力。优先检查提取结果；需要时使用有骨骼角色的3D关节投影，不盲目重复识别。
4. depth在该批的边缘覆盖约37.8%；外观与结构分数是不同维度，选择需看当前样本。

## 静态结构控制不等于时间控制

本路线控制的是出图几何，不是H3视频中间帧的专用lineart通道。先核对模型实际输入；普通九宫格参考、首尾帧、参考视频与专用pose视频条件是不同能力。连续条件也不保证接触、受力和身份正确，见 [combat-motion-continuity.md](combat-motion-continuity.md)。

## 二、三条裁判（下列脚本为自建示例，需按你的环境自行实现）

| 裁判 | 量什么 | 工具 | 成本 |
|---|---|---|---|
| 边缘闸 | 边缘结构覆盖，不等于人物／动作正确 | `structure_referee.py` / `annotate_shot.py` 内置 | 纯OpenCV，快 |
| 骨架闸 | 检测到的姿态；零检出可能是漏检 | `pose_referee.py` | DWPose，历史约15s/张 |
| 深度闸 | 空间层次相关（Pearson r） | `depth_referee.py` | DepthAnythingV2，二轮用 |

- 边缘批筛后，用骨架／深度检查可疑帧；检测器输入适配性须先确认。
- 历史起手阈值：边缘覆盖率低于0.30标疑似不匹配；全黑／无边缘参考、遮挡或检测失败记“不可测／需复核”。阈值须按样本校准。
- 机器完成记 `completed`，人审认可才记 `confirmed`。标红不是删除；所有小样均须用户审，不仅审标红项。静图拼图不能代替视频连看。

## 三、标注流程（固化成命令）

```
py -3.12 annotate_shot.py \
  --frames "<灰模关键帧通配>" --prompt "<提示词>" --out <目录> \
  [--threshold 0.30] [--skeleton]
```

- 逐关键帧：灰模帧 → Canny 提边 → FLUX ControlNet lineart 出图 → 边缘闸打分 → 标待复核。
- 产物：`annotations.csv`（帧号/覆盖率/骨架/初筛状态/产物路径）+ `contact_sheet.png`（灰模帧|出图，待复核红框）。旧工具若输出“废片”标签，仅按初筛理解，不作人审结论。
- 只跑**关键帧**（按提示词点名的关键镜头抽，不是均匀取），不是逐帧全量。

## 四、引擎落地（想批量时用）

- 历史入口：`engine/tasks.py` 的 `control` 任务、`engine/comfy/flux_controlnet_lineart_api.json`、`engine/workflows/previz_control.yaml`。
- 历史命令：`py run.py previz_control`，`src_image` 为灰模帧；记录约45秒出1024×576一张并落批次。实际使用前检查当前文件、参数与调用链是否仍在；未获本次生成授权不得执行。

## 五、关键坑（踩过，必记）

- **cv2 的 imread/imwrite 读不了中文路径** → 一律 `open('rb')` + `np.frombuffer` + `cv2.imdecode`；保存用 `cv2.imencode` + `buf.tofile()`。
- **FLUX ControlNet Union 必须给 ControlNetApplyAdvanced 接 `vae` 输入**，否则 KSampler 报 "This Controlnet needs a VAE"。
- 历史实现的FluxUnionControlNetMode可包装同一controlnet为多模式；总显存还含激活与其他条件，不能保证叠加通道没有资源增量。
- **SDPoseKeypointExtractor 要挂 MODEL+VAE（扩散模型），太重**；提骨架改用 `OpenposePreprocessor`(DWPose) 出骨架图再比图。
- 当时DWPose未识别简化灰模；不要由零检出推断不存在人。出图结果也可能漏检，需人工复核或可靠骨骼投影。
- 历史Seedream i2i记录最小面积921600px（1280×720），1024×576曾被拒；换模型／版本先查现行规格。

## 六、参考

- 完整盘点与工作流规划保存在该项目自己的文档里（本机路径略，不随本副本分发）。
- 裁判层历次实测与云对照全表保存在原环境的私有记忆中，不随本副本分发。
