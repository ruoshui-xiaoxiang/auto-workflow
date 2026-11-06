---
name: reference-cinematic-skill
description: 影视 Skill「cinematic-video-production」的事实源与两份副本位置、同步规则、去本机化口径、许可与分发要求
metadata:
  type: reference
---

# 影视 Skill 的落点与同步规则

| 角色 | 路径 | 说明 |
|---|---|---|
| **事实源（唯一可编辑）** | `C:\Users\若水\.qoder\skills\cinematic-video-production\` | `SKILL.md` + `references/`，24 个 md；纯文档，不含脚本／依赖 |
| 逐字镜像快照 | `E:\公共记忆\skills\cinematic-video-production\` | 与源逐文件 sha256 一致，供 trae 等工具取用；附 `E:\公共记忆\skills\README.md` |
| 去本机化可分发副本 | `D:\cinematic-video-production-portable\` | 24 md + `去本机化说明.md`；已剥机器／账户／项目身份 |
| 装载点 | Trae CN `C:\Users\若水\.trae-cn\skills\`（同 `SKILL.md` 约定）；Qoder 用户级 `~/.qoder/skills/`；项目级 `<项目>/.qoder/skills/`（同名时项目级优先） | 新增文件需重启 IDE 才进列表；放对位置 ≠ 已被触发 |

**Why:** 三份东西长得一样但用途不同，混着改会造成"改了一份、另两份静默过期"。

**How to apply:**
- 改内容只在事实源改；两份副本都是**快照、不自动跟随**，改完要重新导出并复核（镜像份核 sha256，可分发份跑残留词表复扫）。
- 去本机化口径七条：本机路径与服务地址→占位符；本机实测数字→**保留数字**但标"参考机条件、换机必重测"；项目名与角色名→匿名化但**保留失败形状**；账户单价／积分／余额→删数字只留计价方式；私有记忆双链 `[[...]]`→删；私人审美默认→降级为"示例偏好"；**引擎公开规范与方法论→原样保留**。
- 副本不含脚本，只留自建工具的**判据与口径**（`check_preflight.py`／`measure_motion.py`／结构裁判等）。
- 许可：内容自有，方法论原创改写自三个社区 Skill（AlterLab Film Analysis、Dylan Tarre Filmmaker 均 MIT；Omer Metin Video Production Apache-2.0）。**对外再分发须让 `references/craft-sources.md` 随包同行**。
- 这套 Skill 的结构性约束见 [[feedback-review-production-prompts]]（提示词先审、脚本改了整份回写文档）；专业规范层不设"先过评测门"的前置，见 [[feedback-evidence-loop-trap]] 同族⑥。


## 10-02 新增：`D:\AIWorkflow\tools\sync_skill.py`（三轴检查器，GAP-M1 的处置件）

**三条轴分开报，不许混成一件事**：
- **[A] 逐字镜像是否等值**：事实源 vs `E:\公共记忆\skills\cinematic-video-production\`，**逐文件 sha256**。
  10-02 实测 **24/24 全等、0 陈旧 0 缺失** ⇒ 这一轴其实没漂，汇报时别把它说成问题。
- **[B] 去本机化副本是否漏了敏感东西**：⚠ **不能比哈希**（内容本就该不同），改成扫残留词表。
- **[C] 上游是否比 skill 新**：`ComfyUI_H3\*.md` 逐份比 skill `references\` 最新 mtime。
  10-02 实测**九份通道真源落后 4.4–9.1 天**（三份新立通道文档各 9.1 天）。

**`--mirror` 只做 copy＋复制后重读哈希复核；永不删源、也永不删镜像里多出来的文件**——
"这份该不该留"是判定，判定权在人（同资产索引不给 `experiment` 档）。

⚠ **残留词表首版严重过捕**：6 处命中里 4 处是误报。判据教训——
"单价／余额／积分"**光出现字样不算漏网**（本仓库口径本来就是"删数字、留计价方式"），
必须**旁边带数字或金额符号**才算；`[[...]]` 要写成"方括号里须有内容"，否则把《去本机化说明》里
**举的反例本身**算成违规。⇒ 关键词探针分不清"讲解示例"与"真漏网"，剩下的命中一律交人读、不自动放行也不自动定罪。

⚠ 尚未接进扫描器：GAP-M1 的 lag 数现在扫描器与 `sync_skill.py` **各算一份**＝两处来源的病，
下一步改成扫描器消费 `--json`，做成"两个独立实现必须给同一个数"的常设对账。

相关：[[reference-public-memory]]、[[feedback-third-party-skill-install]]。

