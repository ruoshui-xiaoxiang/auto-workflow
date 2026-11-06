---
name: character-scene-asset-pipeline
description: 「角色设定图／场景图／站位图」这类前置资产的既有流水线在哪、走哪条通道——E:\创作\无音项目\工具\ 下的 gen_costume / gen_scene_anchors（走云端 Seedream）；附"有脸走云端、无脸走本地"的分流口径，以及本地锁脸不可用后这套怎么改
metadata:
  type: reference
---

# 角色设定图 / 场景图 / 站位图 —— 既有流水线在哪

用户 2026-09-28 问过"能不能生成角色设定图场景图站位图之类的"。**这类活本来就有流水线，只是它走云端、且不在当前工作目录里**，所以记一条指针（免得下次从零搭）。

## 工具位置：`E:\创作\无音项目\工具\`（跨片通用，别被"无音项目"这层目录名骗了）
- `gen_costume.py --code char_e01 --n 3` —— **定妆/立绘候选**，走火山 Seedream 文生图；脸锚＝`图\定妆\char_e01.png`，挂锚时用"只改两处"从句（`ANCHOR_HEAD`），**不用文档正文**。
- `gen_scene_anchors.py [loc_key]` —— **场景锚点空镜（Seedream i2i）**；提示词与源图映射读 `资产\场景\00_场景定稿与定稿提示词.md`（改文档即改产出），产物落 `资产\场景\锚点候选\`。第 2 批派生自第 1 批成品，`SRC_OVERRIDE` 可显式换源。
- `compose_costume_lock.py` —— 锁脸候选评审图（锚＋3 张新候选，整身/脸部放大两行）。
- 其余同目录：`gen_face_candidates.py`／`gen_face_train_set.py`／`gen_jimeng_copy.py`（公共 `ROOT`/`read`/`parse_scenes`）／`promote_costume.py`／`promote_fix.py`／`pool_move.py`／`pool_survey.py`／`fix_defects.py`／`fix_scene_drift.py`／`adopt_anchors.py`／`build_ab_compare.py`／`make_looks_sheet.py`。
- 武昭君仪侧另有一套在 `D:\AIWorkflow\tmp\wzy\`：`junyi_trainset.py`（训练集脚本）、`face_match.py`／`face_lock_check.py`／`build_face_diag.py`（脸机检）、`faceswap_*.py`、`dz_prompts.py`、`h3_rule_gate.py`、`gen_first_frames.py`、`anchors/`（含两个互相矛盾的 junyi 脸锚）。
- 本地脸训练链：`D:\AIWorkflow\tools\gen_faceA_local.py`（本地 FLUX＋Redux 铺脸训练集，phase1 验锚／phase2 54 张）＋ `training/configs/train_faceA_flux.toml` ＋ 产物 `training/output/<角色>/`。**它写在文件头那条设计理念"训练分布＝使用分布"（LoRA 将来在本地 FLUX 上用，训练集就该本地出）仍然成立，但它的承重件"身份靠 Redux 参考图"已被实测证伪**，见 [[reference-local-face-identity-transfer]] 第十一条。

## 分流口径（跨片通用，也是项目一贯口径）
**有脸的走云端、无脸的走本地**：无脸镜（空镜／手部／兵器／服装形制）走本地 SDXL/FLUX 零成本；要锁身份就走**云端挂锚**（Seedream i2i 锁脸实测 ArcFace 0.922）。**"换低档 Seedream 省 ¥0.10/张"不值得**，真正的杠杆是有没有脸。定价见 [[reference-ark-account]]。

## 本地侧现状（2026-09-28 复核后）
- 本地**能做**：单张场景/道具/形制、i2i 保构图变体、inpaint 改局部、outpaint 扩画布 —— 见 [[reference-local-image-chain]]。
- 本地**做不到**：锁人物身份（Redux 与 FaceID 两条都实测失败）、同场景多机位一致、严格三视图。
- ⇒ 因此"整套角色设定图走本地"目前**不成立**；可行的组合是**云端出有脸的、本地出无脸的**，或者**云端铺训练集 → 本地训 LoRA → 之后本地出脸**。

关联 [[feedback-character-reference-image]]、[[feedback-local-first-generation]]、[[reference-local-image-chain]]、[[reference-local-face-identity-transfer]]、[[feedback-cost-consciousness]]。

## ★「通用角色库」批次怎么做（2026-09-28 用户定的口径，可复用）

用户 2026-09-28 晚从"死磕武君仪锁脸"**转向"专门做一批新角色"**（原话「不用这样，我们专门做一批新角色」），四项选择：**通用角色库（不绑具体片）× 两档画风对照 × 每角色特写+全身各一张 × 用户手跑、agent 取回机检**。

**五条可复用的做法**：
1. **提示词做成矩阵，只换一句才是对照**：`[角色句] + [形态句] + [画风句]`。只换画风句＝两档对照；只换形态句＝特写/全身对照。**两条绝不能同时换**（同一个变量纪律）。
2. **画风句必须是纯渲染描述**，不含任何角色信息 —— 否则"换画风"就变成"同时换两个东西"，对照失效。
3. **新角色一律不挂参考图**：挂锚会把锚的脸带进来、让多个角色**串脸**。这与"锁某个既定角色"是完全相反的口径，见 [[reference-local-face-identity-transfer]] 第十二条。
4. **机检判据要换**：新角色没有"身份基准"，要查的是 ① 可检出性 ② **角色间两两 ArcFace 应明显低于 0.5**（越高＝串脸，这是本类批次的主要风险）③ 同角色特写 vs 全身应 ≥0.5 ④ 两档画风差异交人目视。
5. **别用「BJD 人偶质感」去追 3D 半写实国漫的质感** —— 那四个字会长出球形关节接缝、加禁令也压不住（[[feedback-prompt-iteration-priors]]）。

**通道**：**即梦画布网页免费手跑 → `dreamina-canvas resource download` 整批取回（带服务端 sha256）**，见 [[reference-dreamina-canvas-cli]]。批次一＝4 角色（青年男剑客／仙门女修／白发师尊／江湖游侠女）× 2 档 × 2 形态 ＝ 16 条，落 `E:\创作\_待审文档\通用角色库_批次一_待审_20260928.md`；建议先只跑八张特写（定两档画风哪个要），定了再跑全身。

## ★2026-10-01 晚：角色库里有**两类交付物**，病灶不同 ⇒ 判据必须分套

10-01 按题材挑图时才看清：`E:\创作\通用角色库\` 下的成图分两类，**用同一套判据会两边都判错**。

| 类别 | 版式 | 主要病灶 | 判据要多带的两条 |
|---|---|---|---|
| **单幅人像**（补格子批 48 张） | 16:9 一张一人 | 被**正向词表**带走：影楼暖黄（6 个暖光词）、形制自己往高衩露背漂 | 无（用 ①–④ 那四条） |
| **角色设定图**（T1–T5 前置门批） | 正／背＋大头像＋侧脸＋腰封／鞋／发饰细节小图 | **组内自洽**：发色跨视图跳、靴底跳色、细节格缺角、整张漏掉大头像 | ⑤ **版式完整性**（大头像在不在、格子缺不缺角）⑥ **跨视图同一人**（发色／靴色／袍色几个视图之间有没有跳） |

⇒ **挑设定图的好坏，"脸漂不漂亮"基本不是变量**；最差那几张全是⑤⑥崩的，最好的是"同一人 × 细节齐全"。
⇒ 通用判据四条（脸完整不清裁／构图舒展／有无硬伤／光有没有方向）见 [[reference-image-consistency-qc]]，**判图分辨率下限（≥880px 近原图）也在那条里**——缩略拼图上判单张理由 3/4 是假的。

**按题材取图的正路（省一次考古）**：`测试图总览_20260929\`、`改写批前置门_20260929\`、`改写批前置门R2_20260929\` 三处文件名**自带题材标签**（`T1_仙侠玄幻`／`T2_古代乡村B版式`／`T3_古代明朝`／`T4_古代言情`／`T5_现代都市`），一个正则就能分组。
🔴 而最大的那池 `通用角色库\角色生成\`（**855 张**，09-28 批）**只有 `图片NNN_序号.png`、没有任何题材／提示词标签** ⇒ 想按题材或按写法分组，必须先回节点台账把 `图片NNN` 对回提示词，**别按文件名猜**。
