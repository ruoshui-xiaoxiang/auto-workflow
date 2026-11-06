#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地工作流资料归集脚本
====================
把散落在 C / D / E 三盘的「本地 AI 工作流」参数规则、使用规范、注意事项资料
统一复制到 E:\\本地工作流规范手册\\ ，按主题分层、多副本去重，并生成可校验来源清单。

三条铁律
  1) 只复制，绝不删除 / 改名 / 改动任何源文件（shutil.copy2 保留时间戳与属性）。
  2) 每条入选与不入选的决定都写进 99_来源清单\\manifest.json 与 MANIFEST.md，可追溯。
  3) 可重复执行：再跑一次即 refresh —— 按 sha256 判断，源未变则跳过，源已变则覆盖副本。

用法
  py -3.12 build_manual.py            # 建目录 + 拷贝 + 出清单
  py -3.12 build_manual.py --check    # 只报告哪些副本已落后于源，不写任何文件
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime

DEST_ROOT = r"E:\本地工作流规范手册"
SEC_MANIFEST = "99_来源清单"
MANIFEST_NAME = "manifest.json"

# 源目录常量，避免到处写长路径
AW = r"D:\AIWorkflow"
CH3 = AW + r"\ComfyUI_H3"
WZY = AW + r"\tmp\wzy"
H3D = WZY + r"\h3"
TOOLS = AW + r"\tools"
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = r"C:\Users\若水\.qoder\skills\cinematic-video-production"   # 事实源（唯一可改处）
SKILL_PORTABLE = r"D:\cinematic-video-production-portable\cinematic-video-production"  # 去本机化脱敏可分发版
DT = r"E:\创作"   # 09-28 桌面整理：项目夹从桌面搬进 E:\创作；散件见 DD
DD = r"E:\创作\_待审文档"
MEM = r"C:\Users\若水\.qoder\memory"
PUB = r"E:\公共记忆"
LAI = r"E:\LocalAI"
CRE = r"E:\创作"
POOL = r"E:\图像影音资源池"
FILM = r"E:\若水AI电影"          # 10-02 新增：架构总纲根。只装三样（总纲／manifest／维护脚本），
                                 # **不拥有任何规则**——规则权威仍在本手册 20_通用规范层
MAINT = DEST_ROOT + r"\99_维护"  # 本层自校的三个校验器住这儿

# ---------------------------------------------------------------------------
# 文件地图： (源路径, 目标子目录, 目标文件名, 角色, 备注)
#   角色  canonical  = 现行真源 / 权威规范
#         reference  = 只读参考、模板、示例、历史留痕
#         project    = 项目产物（执行/审计/待审），非跨项目通用规则
#         live       = 会被就地编辑的活文档，副本需定期 refresh
# ---------------------------------------------------------------------------
# cinematic-video-production 的 23 篇 references（两份副本同名同清单）
SKILL_REFS = [
    "production-protocol.md", "communication.md", "cost-and-compliance.md",
    "budget-pricing.md", "prompt-specs-by-engine.md", "prompt-injection.md",
    "local-render-budget.md", "style-lock-and-retry.md", "character-anchoring.md",
    "keyframe-pairing.md", "combat-motion-continuity.md", "previz.md",
    "previz-control-referee.md", "script-and-qc.md", "craft-foundations.md",
    "craft-evaluation.md", "craft-examples.md", "craft-sources.md",
    "asset-planning.md", "asset-and-resume.md", "experience-loop.md",
    "examples.md", "web-check.md",
]

FILES = [
    # ---- 01 总手册 -------------------------------------------------------
    (DD + r"\AI影视生产系统_V1.1_实施手册.md", "01_总手册",
     "AI影视生产系统_V1.1_实施手册.md", "canonical",
     "桌面那份 50KB 的总实施手册，覆盖面最广的一份单体文档"),

    # ---- 02 H3 提示词规则 -----------------------------------------------
    (CH3 + r"\H3提示词工程规则方案.md", "02_H3提示词规则",
     "H3提示词工程规则方案_真源.md", "live",
     "规则真源。R1-R17 每条带实测翻车出处；改规则只改这里。"
     "⚠ 09-28 实改了 §一表 / §3.3 / §十一三处，但头部版本戳仍写 v2.1『只改 R5 一条，其余逐字未动』——该句已失真，见冲突表"),
    (CH3 + r"\H3提示词规则_现行合并版.md", "02_H3提示词规则",
     "H3提示词规则_现行合并版.md", "live",
     "现行执行版：合并真源 + 项目法条 + 三道闸现状，每条标 [拦]/[报]/[拼]/[人]/[废]。"
     "09-28 只改 §七第 4 条一行（video 与 h3_i2va 同判据）"),
    (CH3 + r"\prompts\official_h3\SKILL.md", "02_H3提示词规则",
     "官方规范_MiniMax-H3_h3-prompt-writing_SKILL.md", "canonical",
     "H3 权重仓自带的官方提示词规范"),
    (CH3 + r"\prompts\official_h3\base-en.txt", "02_H3提示词规则",
     "官方模板_基础三字段_base-en.txt", "reference", "官方基础模式模板原文"),
    (CH3 + r"\prompts\official_h3\ref-en.txt", "02_H3提示词规则",
     "官方模板_全参考六段_ref-en.txt", "reference", "官方全参考模式六段模板原文"),
    (H3D + r"\H3规则机检.md", "02_H3提示词规则",
     "H3规则机检.md", "canonical", "规则如何编成机器层（只报不拦）的说明"),
    (H3D + r"\R17空转实测.md", "02_H3提示词规则",
     "R17时长公式空转实测.md", "reference", "R17 时长=信息单元×0.9-1.2s 的实测依据"),
    (H3D + r"\一·七_H3适配.md", "02_H3提示词规则",
     "一·七_H3适配.md", "reference",
     "中文十块模板编译到 H3 原生骨架的适配记录。"
     "★09-28 纯追加 §12（画风归因六臂实测）与 §13（君仪形象训练集批 1 八张），第 1–160 行逐字未变；"
     "真源已从旧名 `第一章_H3适配说明.md` 改名"),
    (H3D + r"\三套产物归属核对.md", "02_H3提示词规则",
     "三套产物归属核对.md", "canonical",
     "A/B/C 三条产物线归属性核对——现行合并版 §十 的作用域真源"),
    (H3D + r"\另两条线核对.md", "02_H3提示词规则",
     "另两条线_B_C提示词核对.md", "reference", "B/C 线提示词过词表闸/法条闸的只报结果"),
    (H3D + r"\成片版本溯源.md", "02_H3提示词规则",
     "成片版本溯源.md", "reference", "哪版成片对应哪版提示词的可追溯链"),
    (H3D + r"\定妆词.md", "02_H3提示词规则",
     "定妆提示词法.md", "reference", "定妆/角色锚点出图词的写法"),
    (H3D + r"\自检报告.md", "02_H3提示词规则",
     "提示词自检报告样例.md", "reference", "机检输出报告的实际样例"),
    (CRE + r"\无音项目\工具\提示词工程系统模板.md", "02_H3提示词规则",
     "提示词工程系统模板_无音项目.md", "reference",
     "更早一版的项目级提示词模板，用于对照现行十块模板的来历"),

    # ---- 03 使用规范与关口流程 ------------------------------------------
    (CH3 + r"\使用规范_用前必读.md", "03_使用规范与关口流程",
     "H3本地出片_使用规范_用前必读.md", "live",
     "本地 H3 出片链的唯一权威使用规范：环境/配方/参数/性能/十坑/故障速查/禁做清单。"
     "⚠ 09-28 00:55 同批改：第 (5) 节写入「十块剥离、video 与 h3_i2va 同判据」，"
     "另第 10 行仍把 H3 定位为《哑女·废土》的第二出片通道（第一通道＝云端 Seedance 2.5 r2v）⇒ 与新版十块归属表述并见冲突表"),
    (DD + r"\本地工作流_关口化方案_待审.md", "03_使用规范与关口流程",
     "本地工作流_关口化实施说明_20260920.md", "canonical",
     "G1-G12 机器关口 + H1-H7 人工关口的现行实现位置。正文已声明替代旧《待审》版，故按实施说明归档"),
    (CH3 + r"\README_VERY_IMPORTANT.txt", "03_使用规范与关口流程",
     "ComfyUI_H3_README_VERY_IMPORTANT.txt", "reference", "实例目录自带的必读说明"),
    (AW + r"\logs\workflows\待批关口.txt", "03_使用规范与关口流程",
     "待批关口_实产样例.txt", "reference",
     "关口停住时落到本地的人话待批记录样例（格式本身是规范的一部分）"),
    (CH3 + r"\可灵云端_工作流规则.md", "03_使用规范与关口流程",
     "可灵云端_工作流规则.md", "live",
     "★10-02 用户裁「三个都立独立通道」新立的第六条通道真源：可灵。已确证＝两条接入路径不共用凭证、异步必须先轮询终态、能力面随 CLI 版本变以实时清单为准；⚠ 通篇 [未实测] 的部分＝提示词契约／长度上限／负面词／参考图能力，一律不许从别的通道外推。⚠ 现状：身份与真源已立，**路由与判据未落地**（词仍挂 cloud_sd 别名按十块审）＝GAP-C5 待实施（批 4·5）"),
    (CH3 + r"\Vidu云端_工作流规则.md", "03_使用规范与关口流程",
     "Vidu云端_工作流规则.md", "live",
     "★同批新立的第七条通道真源：Vidu。⚠ **本机实测为零**——唯一硬证据是它出现在千问 /api/v1/models 的 89 条视频模型清单里，「在别人列表里出现过」不等于本机接过跑过；所以本文件现在只是带纪律的空壳：禁止借用 H3 骨架／云端SD 十块／即梦三段式的任何实测数，判据在实测前一律不开"),
    (CH3 + r"\海螺云端_工作流规则.md", "03_使用规范与关口流程",
     "海螺云端_工作流规则.md", "live",
     "★同批新立的第八条通道真源：海螺／MiniMax 云端。🔴 本条第一行钉的是最容易读错的点——与**本地 H3 同源但不同契约**：本地走官方 I2VA 骨架五条由 _g7_skeleton 把关，云端不吃那五条，把它路由进 h3 或 cloud 都是错配（两种都出现过）；另注明海螺 AI 设计工具＝Electron GUI 黑盒，不是本通道的自动化入口"),
    (CH3 + r"\千问云端_工作流规则.md", "03_使用规范与关口流程",
     "千问云端_工作流规则.md", "live",
     "★09-28 用户裁定（冲突表 C79）新立的**第四条通道**规则真源：千问云端（qianwen CLI + QianWen Skills Hub）"
     "各通道规则分治——本通道不吃 H3 骨架五条、不吃中文十块、不吃 _g7_skeleton/_g7_tenblock；"
     "只共用机制层（作用域登记/冲突编号/未实测默认关/单源生成/sha256 判据/回归）。"
     "⚠ 本机实测为零，skill 自带硬要求一律标 [未实测] 只作参考资料；"
     "已知缺口见风险 28：channel_of() 只认 h3/cloud/image 且兜底是 else h3，千问稿默认落 h3 通道、"
     "被 G7 判「认不出格式」或「十块混用」error 拦死（不是按 cloud 判）"),
    (CH3 + r"\即梦云端_工作流规则.md", "03_使用规范与关口流程",
     "即梦云端_工作流规则.md", "live",
     "★09-28 用户指示（冲突表 C82）新立的**第五条通道**规则真源：即梦云端"
     "（用户手跑即梦网页画布出图/出视频，agent 只用 dreamina-canvas 取回＋机检）。"
     "官方出处三条（火山方舟 Seedream 4.0-5.0 提示词指南／Seedance 2.5 提示词指南／即梦官方资源页），"
     "硬约束＝图片 prompt 上限 **2000 字**（9 个模型全部）、视频按模型 2000–20000；"
     "★两条对外部口径的处置：① 社区「关键词 20–40 字」与即梦官方「无字数限制」直接矛盾 ⇒ 不采信，以 2000 硬上限为准；"
     "② 官方「简洁精确优于堆叠华丽」＝针对 tag 罗列＋冗余画质词，**不是**『结构描述要短』 ⇒ 本机口径收敛为「结构写细、形容词写少」。"
     "⚠ 负面词：官方只文档化「字幕／音频」两类负向控制 ⇒ 图片侧一律改写正向句（旧说法「即梦能不能收负面词」由此结案；"
     "但 UI 是否有独立负面框 `[未核实]`）。"
     "⚠ 已知缺口：即梦稿**不进任何机检**（人工执行通道、无引擎调用 ⇒ 不需要 channel_of 分支，与风险 28 的千问不同）；"
     "`seedance_2.5` 是云端SD 与本通道**共用的同一模型却两套契约**（冲突表 C84，未裁）"),
    (CH3 + r"\图片链_工作流规则.md", "03_使用规范与关口流程",
     "图片链_工作流规则.md", "live",
     "★10-02 用户裁定「批 1 余下：图片链真源新建」补上的**第一条通道的真源**（冲突表 C85）："
     "本地 ComfyUI 图片链（FLUX/SDXL/SD1.5），prompt_kind: image。"
     "此前它是五条通道里唯一**规则文档不存在、却带最多引擎 yaml 在跑**的（GAP-C1 的零真源那半）。"
     "⚠ 本通道真源的主体是**工具契约**（模板占位符/denoise 刻度/掩膜语义/耗时），不是提示词写法——"
     "图片口径在 check_preflight 里**无格式要求**，谁在这份文档里另写一套图片提示词规范就是造第二个漂移真源。"
     "★通道成员实测 **10 份流**（按 yaml 声明的 prompt_kind 数），不是 8 份（按 image_*.yaml 文件名数）："
     "previz_control/character_sheet/auto_draft 也吃同一套判据，image_refine 在文件名口径里却没声明 prompt_kind。"
     "★实测数字全部标了日期与样本（09-28 同帧 A/B，736×416 一个样本）⇒ 只做本通道内相对比较，不许外推；"
     "depth 锁几何**仍不可用**、Redux/FaceID 锁脸**本机全败**，别因为模板在就当能力在"),

    # ---- 04 生产流水线 Skill（23 篇参考）-------------------------------
    # ---- 04 生产流水线 Skill -------------------------------------------
    # 事实源 = .qoder\skills\（唯一可改处）；E:\公共记忆\skills\ 是它的逐字镜像（md5 相同）
    (SKILL + r"\SKILL.md", "04_生产流水线Skill_事实源", "SKILL.md", "live",
     "入口路由表：按任务指向首要资料与最小交付。事实源，只在这里改"),
] + [
    (SKILL + r"\references\\" + n, r"04_生产流水线Skill_事实源\references", n, "live",
     "cinematic-video-production 技能参考篇（事实源 .qoder\\skills\\，含本机单价与真实路径）")
    for n in SKILL_REFS
] + [
    # 脱敏可分发版：同一套 23 篇，但刻意抹掉账户单价／项目名／本机路径，用于对外分发
    # 并列保留是为了让人看见「同一规则在两份里被写成不同口径」，不代表它是现行版
    (SKILL_PORTABLE + r"\SKILL.md", "04b_生产流水线Skill_脱敏可分发版", "SKILL.md", "reference",
     "与事实源 SKILL.md md5 不同（09-23 17:15 后另写）；分发用途，不作本地判据"),
] + [
    (SKILL_PORTABLE + r"\references\\" + n, r"04b_生产流水线Skill_脱敏可分发版\references", n, "reference",
     "去本机化版：账户单价改成只讲计价方式、项目名匿名化、本机路径略；23 篇中 14 篇与事实源有差异")
    for n in SKILL_REFS
] + [
    # ---- 05 引擎与工作流参数定义 ----------------------------------------
    (AW + r"\engine\README.md", "05_引擎与工作流参数", "engine_README.md", "canonical",
     "执行引擎说明"),
    (AW + r"\engine\config.yaml", "05_引擎与工作流参数", "engine_config.yaml", "live",
     "引擎配置真源：pool_root/project/交付根派生/preflight/需锚角色/关口通知"),
    (AW + r"\AGENTS.md", "05_引擎与工作流参数", "AIWorkflow_AGENTS.md", "canonical",
     "整个 D:\\AIWorkflow 目录的 agent 作业约定"),
] + [
    (AW + r"\engine\workflows\\" + n, r"05_引擎与工作流参数\workflows", n, "canonical",
     "工作流参数定义（步骤/入参/默认值/关口挂载）")
    for n in [
        "h3_ref2va_video.yaml", "h3_i2va_video.yaml", "h3_i2va_batch.yaml",
        "h3_one_click_movie.yaml", "image_draft_batch.yaml", "image_draft_batch_sdxl.yaml",
        "image_batch_draft.yaml", "image_refine.yaml", "character_sheet.yaml",
        "previz_control.yaml", "auto_draft.yaml", "selftest.yaml", "selftest_gates.yaml",
    ]
] + [
    # comfy 模板层：yaml 管不到的 sampler / scheduler / cfg / 节点接线，固化在这里
    (AW + r"\engine\comfy\\" + n, r"05_引擎与工作流参数\comfy模板", n, "canonical",
     "ComfyUI 工作流模板：底模、sampler、scheduler、cfg、哨兵占位（__PROMPT__/__W__/__STEPS__ 等）")
    for n in [
        "h3_i2v_fl2va_api.json", "h3_i2v_ref2va_api.json",
        "h3_i2v_fl2va_dual_lora.json", "h3_i2v_ref2va_dual_lora.json",
        "draft_flux_api.json", "draft_upscale_api.json", "draft_sdxl_api.json",
        "draft_sd15_api.json", "refine_usdu_api.json", "flux_controlnet_lineart_api.json",
        "flux_cn_redux_api.json", "flux_redux_ref_api.json", "sdxl_faceid_ref_api.json",
    ]
] + [
    # ---- 06 本地 AI 环境与启动 ------------------------------------------
    (AW + r"\README.md", "06_本地AI环境与启动", "AIWorkflow_README.md", "reference",
     "AIWorkflow 根目录说明"),
    (LAI + r"\gateway\README.md", "06_本地AI环境与启动", "LocalAI_gateway_README.md", "canonical",
     "本地 AI 网关说明（端口/后端路由）"),
    (LAI + r"\gateway\config.json", "06_本地AI环境与启动", "LocalAI_gateway_config.json", "live",
     "网关实际配置：后端地址与端口定义"),
    (LAI + r"\_迁移MANIFEST_20260911.md", "06_本地AI环境与启动",
     "LocalAI_迁移MANIFEST_20260911.md", "reference", "E 盘本地 AI 栈迁移留痕"),
    (CH3 + r"\run_H3_ComfyUI.bat", "06_本地AI环境与启动", "run_H3_ComfyUI.bat", "canonical",
     "H3 实例启动参数真源：--port 8189 / --use-sage-attention / --output-directory"),
    (CH3 + r"\启动常驻ComfyUI.bat", "06_本地AI环境与启动", "启动常驻ComfyUI.bat", "reference",
     "常驻模式启动脚本"),
    (CH3 + r"\make_model_links.ps1", "06_本地AI环境与启动", "make_model_links.ps1", "reference",
     "模型目录 junction 建链脚本（16GB 卡那套模型布局）"),
    (LAI + r"\LocalAI.bat", "06_本地AI环境与启动", "LocalAI.bat", "reference", "本地 AI 栈总入口"),
    (LAI + r"\LocalAI.ps1", "06_本地AI环境与启动", "LocalAI.ps1", "reference", "总入口 PowerShell 实现"),
] + [
    (LAI + r"\launchers\\" + n, r"06_本地AI环境与启动\launchers", n, "reference",
     "启动器：端口/显存档位/模型选择都硬编码在这里，属环境参数事实源")
    for n in [
        "comfyui.bat", "comfyui-watch.bat", "agent-launch.ps1",
        "start-agent-tier.ps1", "start-qwen1234.ps1", "圣女出图一条龙.bat",
    ]
] + [
    # ---- 07 LoRA 训练规范 ----------------------------------------------
    (AW + r"\training\docs\asian_face_lora_training_plan.md", "07_LoRA训练规范",
     "人脸LoRA训练方案.md", "canonical", "训练路线与参数计划"),
    (AW + r"\training\docs\training_handoff.md", "07_LoRA训练规范",
     "训练交接说明.md", "canonical", "跨会话训练交接：数据集/权重位置/验收口径"),
    (AW + r"\training\docs\脸A_LoRA训练日志_20260916.md", "07_LoRA训练规范",
     "脸A_LoRA训练日志_20260916.md", "reference", "实测训练日志（epoch/损失/判废依据）"),
    (PUB + r"\projects\asian-face-lora.md", "07_LoRA训练规范",
     "公共记忆_asian-face-lora.md", "reference", "E:\\公共记忆 里该项目的跨工具摘要"),

    # ---- 09 项目执行与审计 --------------------------------------------
    (DT + r"\武昭君仪\武昭君仪_剧本与资产盘点_v1.md", "09_项目执行与审计\\无昭君仪",
     "武昭君仪_剧本与资产盘点_v1.md", "project",
     "★法条 R1–R5 的真源（被 tmp\\wzy\\prompt_rules.py 的 DOC= 硬引用）；第一轮漏收，本轮补"),
    (DT + r"\武昭君仪\武昭君仪资产包\index.md", "09_项目执行与审计\\无昭君仪",
     "武昭君仪资产包_index_v3.5.md", "project",
     "资产包台账现行版：比同目录 index.md 多「作者复审反馈 v3.4」与「作者定案 v3.5」两段（00:55→01:04）"
     "（⚠ 10-02 更正源路径：这两段当时只在 `index (1).md` 里，那份是下载重命名的副本却成了权威；"
     "本轮按 sha256 证实 `index.md` 是它的逐字节前缀后并回 `index.md`、删掉 `(1)` 副本，"
     "手册侧落点名 `武昭君仪资产包_index_v3.5.md` 不变）"),
    (DT + r"\武昭君仪\武昭君仪小说\第一章补全计划.md", "09_项目执行与审计\\无昭君仪",
     "第一章补全计划.md", "project",
     "⚠ 09-28 复核：该文件被**移动**到 `武昭君仪\\武昭君仪小说`（原判「已删除」是错的，只是路径漂了）"),
    (DT + r"\武昭君仪_重写版\00_设定与大纲.md", "09_项目执行与审计\\无昭君仪\\小说重写版",
     "00_设定与大纲.md", "project",
     "★09-28 01:21 新出现的项目：《武昭君仪》爽文版正文重写线（小说子通道，与视频线共用角色/世界观资产）"),
    (DT + r"\武昭君仪_重写版\01_写作计划.md", "09_项目执行与审计\\无昭君仪\\小说重写版",
     "01_写作计划.md", "project", "首卷八章交付清单与本轮新增硬约束（禁「记录/记账」类内容）"),
    (DT + r"\武昭君仪_重写版\02_文风规范.md", "09_项目执行与审计\\无昭君仪\\小说重写版",
     "02_文风规范.md", "project",
     "★十条禁令的「去 AI 味」硬约束，每章逐条过——与提示词侧「禁令即在点名」同族的写法经验，通用价值待批 2 判定"),
    (DT + r"\武昭君仪\三阶打斗_提示词全集.md", "09_项目执行与审计\\无昭君仪",
     "三阶打斗_12镜提示词全集_快照.md", "project",
     "09-28 03:20 快照（由修好的 `pack_p_prompts.py` 整份回写，58 行 → 212 行）：三阶线 12 镜总览 + 本轮固化的 5 条写法经验"
     "（通用价值高，已提进 R3）。~~逐镜全文段 12 处全是「缺文件」~~ **已修**：旧 glob 只认带镜名后缀的旧命名 ⇒ "
     "`shot_file()` 现在两个目录／两种命名都找，缺源时打印 `!!` 而不是静默留白；运镜列改为**从稿内正则读**（12/12 与表内声明一致）。"
     "全文真源仍是 `prompts_H3官方骨架\\`，本快照只是给人看的那一份"),
    (WZY + r"\h3\三阶打斗编排_v2.md", "09_项目执行与审计\\无昭君仪",
     "三阶打斗编排_v2.md", "project", "09-28 新出现：三阶段编排依据（P1 空手八极／P2 裹布棍法／P3 解布枪法）"),
    (WZY + r"\h3\三阶编排审计.md", "09_项目执行与审计\\无昭君仪",
     "三阶编排审计.md", "project", "09-28 新出现：三阶线审计"),
    (WZY + r"\h3\打斗编排_H11-H15.md", "09_项目执行与审计\\无昭君仪",
     "打斗编排_H11-H15.md", "project", "09-27 新出现：第一章攻防镜编排（G6 底线句实测对象）"),
    (WZY + r"\h3\画风基线.md", "09_项目执行与审计\\无昭君仪",
     "画风基线.md", "project", "09-27 新出现：全片画风/光影基线（10 KB，通用层 R4-16 的实例源）"),
    (WZY + r"\h3\君仪训练集.md", "09_项目执行与审计\\无昭君仪",
     "君仪训练集.md", "project",
     "09-27 新出现：**角色＋道具一起训**路线的落地文档（对应旧记录「缺的只是训练集」），跨项目价值待批 2 判定"),
] + [
    # ---- 02 新增：格式契约变更后必须并存的三份 --------------------------------
    (CH3 + r"\云端SD提示词模板_十块.md", "02_H3提示词规则",
     "云端SD提示词模板_十块.md", "live",
     "★09-28 新立：中文十块模板**从 H3 剥离后的新家**（云端 Seedance 视频／云端出图专用）。"
     "剥离依据＝A/B 实测 5 seed×2 臂：十块 4/5 条乱码、官方骨架 0/5"),
    (CH3 + r"\规则对比_官方写法_vs_项目规则.md", "02_H3提示词规则",
     "规则对比_官方写法_vs_项目规则.md", "canonical",
     "★09-28 新立：官方写法与项目规则的逐条对照（本次「重新全量梳理」的主索引之一）"),
    # 09-28 开闸后新放的"挡路灯条"：收进手册，因为下一个挑 prompt_file 的人就是它要拦的人
    (CH3 + r"\prompts\读我_本目录已是十块旧写法.md", r"09_项目执行与审计\无昭君仪",
     "读我_H3prompts目录现状.md", "live",
     "★`ComfyUI_H3\\prompts\\` 现存 56 份全是云端十块（`detect_format` 实测 56/56），当 `prompt_file` 跑 H3 "
     "必被 G7 判混用拦下；文内给现役真源指针、判废归档落点，与三条「不要做的事」"
     "（含「不要为了跑通把 preflight 关回去」）"),
] + [
    (CH3 + r"\prompts_H3官方骨架\\" + n, r"09_项目执行与审计\无昭君仪\H3官方骨架提示词", n, "project",
     "★09-28 起 H3 视频层**真源目录**（官方 I2VA 骨架，12 镜）；旧的十块写法目录 `prompts`、`prompts_官方三段式` 两目录未搬")
    for n in [
        "wuzhaojunyi_三阶P1A.txt", "wuzhaojunyi_三阶P1B.txt", "wuzhaojunyi_三阶P1C.txt",
        "wuzhaojunyi_三阶P1D.txt", "wuzhaojunyi_三阶P2A.txt", "wuzhaojunyi_三阶P2B.txt",
        "wuzhaojunyi_三阶P2C.txt", "wuzhaojunyi_三阶P2D.txt", "wuzhaojunyi_三阶P3A.txt",
        "wuzhaojunyi_三阶P3B.txt", "wuzhaojunyi_三阶P3C.txt", "wuzhaojunyi_三阶P3D.txt",
    ]
] + [
    # ---- 08b 公共记忆（跨工具共享层）里的工作流项目摘要 ----------------------
    (PUB + r"\projects\wuzhaojunyi-h3-fight-pipeline.md", "08b_公共记忆_跨工具项目摘要",
     "wuzhaojunyi-h3-fight-pipeline.md", "live", "34.8 KB，09-27 晚更新——三阶打戏 H3 管线跨工具摘要"),
    (PUB + r"\projects\auto-workflow.md", "08b_公共记忆_跨工具项目摘要",
     "auto-workflow.md", "live", "自动化工作流项目摘要"),
    (PUB + r"\projects\local-ai.md", "08b_公共记忆_跨工具项目摘要",
     "local-ai.md", "live", "本地 AI 栈项目摘要"),
    (PUB + r"\projects\shuanghua-film-pipelines.md", "08b_公共记忆_跨工具项目摘要",
     "shuanghua-film-pipelines.md", "live", "双姝／影视管线摘要"),
    (PUB + r"\projects\wuyin.md", "08b_公共记忆_跨工具项目摘要",
     "wuyin.md", "live", "无音项目摘要"),
    (PUB + r"\projects\local-ai-workflow-rules.md", "08b_公共记忆_跨工具项目摘要",
     "local-ai-workflow-rules.md", "live",
     "★09-28 新立：通道规则分治跨工具摘要（四条通道各自规则、只共用机制层；千问云端＝qianwen CLI＋SkillHub、"
     "实测为零故不过 G7；备份验收改为「缺 0 且 陈旧 0」）。真源在 `E:\\公共记忆\\projects\\`，本份是副本"),
    (H3D + r"\H3分镜与提示词.md", "09_项目执行与审计\\无昭君仪",
     "H3分镜与提示词.md", "project", "120KB 单文件，含逐镜参数与提示词全文"),
    (H3D + r"\出片计划.md", "09_项目执行与审计\\无昭君仪",
     "出片计划.md", "project", "批次划分与预算"),
    (DD + r"\仙戮打戏八镜_H3提示词待审_20260922.md", "09_项目执行与审计\\仙戮",
     "仙戮_打戏八镜_H3提示词待审_20260922.md", "project", ""),
    (DD + r"\剑来_剑指v3_分镜与运镜计划.md", "09_项目执行与审计\\仙戮",
     "剑来_剑指v3_分镜与运镜计划.md", "project", ""),
    (DD + r"\剑阵灭世_v5_H3提示词_待审.md", "09_项目执行与审计\\仙戮",
     "剑阵灭世_v5_H3提示词_待审.md", "project", ""),
    (DD + r"\太空战_星云篇MV方案_待审_20260922.md", "09_项目执行与审计\\太空战",
     "太空战_星云篇MV方案_待审_20260922.md", "project", ""),
    (DD + r"\烬骨辞_制作方案_v1.md", "09_项目执行与审计\\烬骨辞",
     "烬骨辞_制作方案_v1.md", "project", ""),
    (DD + r"\烬骨辞_第1批_首帧尾帧提示词_待审.md", "09_项目执行与审计\\烬骨辞",
     "烬骨辞_第1批_首帧尾帧提示词_待审.md", "project", ""),
    (DD + r"\烬骨辞_第2批_H3视频提示词_待审.md", "09_项目执行与审计\\烬骨辞",
     "烬骨辞_第2批_H3视频提示词_待审.md", "project", ""),
    (CRE + r"\太空战_H3_20260922\可灵\调优实验_说明.md", "09_项目执行与审计\\太空战",
     "可灵_调优实验说明.md", "project", "云端可灵参数实验"),
    (CRE + r"\太空战_H3_20260922\可灵\样片01_说明.md", "09_项目执行与审计\\太空战",
     "可灵_样片01说明.md", "project", ""),
    (CRE + r"\无音项目\无音\00_服装与视觉锚点台账_v3.md", "09_项目执行与审计\\无音",
     "无音_服装与视觉锚点台账_v3.md", "project", ""),
    (CRE + r"\无音项目\_收拢整理计划_20260911.md", "09_项目执行与审计\\无音",
     "无音_收拢整理计划_20260911.md", "project", ""),
    (POOL + r"\无音_镜1镜2_对照\无音_事件线与状态传递_工作流规划.md",
     "09_项目执行与审计\\无音", "无音_事件线与状态传递_工作流规划.md", "project",
     "跨镜状态传递的工作流设计"),
    (POOL + r"\无音_镜1镜2_对照\《哑女废土》M1_3Dpreviz单镜闭环_实施计划.md",
     "09_项目执行与审计\\无音", "哑女废土_M1_3Dpreviz单镜闭环_实施计划.md", "project", ""),
    (POOL + r"\无音_镜1镜2_对照\无音_分镜表与状态台账.md",
     "09_项目执行与审计\\无音", "无音_分镜表与状态台账.md", "project", ""),
    (POOL + r"\无音_镜1镜2_对照\阶段2_3D previz方案文档.md",
     "09_项目执行与审计\\无音", "无音_阶段2_3Dpreviz方案.md", "project", ""),
    (POOL + r"\无音_镜1镜2_对照\短剧_对门_制作方案_v1.md",
     "09_项目执行与审计\\无音", "短剧_对门_制作方案_v1.md", "project", ""),
    (POOL + r"\无音_镜1镜2_对照\shot05_即梦参考图测试\07_30帧清单.md",
     "09_项目执行与审计\\无音", "shot05_即梦参考图测试_30帧清单.md", "project", "关键帧去重实据"),
    (POOL + r"\无音_镜1镜2_对照\shot05_即梦参考图测试\09_最终22帧清单.md",
     "09_项目执行与审计\\无音", "shot05_即梦参考图测试_最终22帧清单.md", "project", ""),
]

# 仙女星系战争 / 机械战星 两个项目的执行与审计文档，按目录批量收
PROJECT_BULK = [
    (DT + r"\仙女星系战争项目", "09_项目执行与审计\\仙女星系战争", [
        "分镜表_本地执行版_v1.md", "分镜表_本地执行版_v2_32镜.md", "生产审计_43镜_v1.md",
        "生产计划_v1.md", "执行计划_终版.md", "执行日志.md", "执行日志_v2.md",
        "偏差台账.md", "偏差台账_v2.md", "项目总审_v1.md",
        "末四镜_H3提示词待审_v1.md", "末四镜_结构锚点重画.md", "即梦_末四镜_提示词.md",
        "设定_帝国与联邦_v1.md", os.path.join("舰体设计", "实验C_结果.md"),
    ], "project", "桌面项目文档：执行方案/审计/偏差台账"),
    (DT + r"\机械战星项目", "09_项目执行与审计\\机械战星", [
        "执行方案_MV_v1.md", "执行日志_MV.md", "偏差台账_MV.md",
        "机械战星_分镜表_v1.md", "机械战星_MV对位表_v1.md", "仙后级_设定与舰桥尺度_v1.md",
    ], "project", "桌面项目文档：执行方案/偏差台账"),
]

# 10 机检与工具脚本（只读参考：真源在原目录，改动请改原处）
SCRIPTS = [
    (WZY + r"\h3_rule_gate.py", "H3 规则机检闸（真源在 D:\\AIWorkflow\\tmp\\wzy\\）"),
    (WZY + r"\prompt_lint.py", "词表闸 / 字面闸实现"),
    (WZY + r"\prompt_rules.py", "项目措辞法条 R1-R5 定义"),
    (WZY + r"\prompt_gate.py", "关口调度"),
    (WZY + r"\other_lines_check.py", "B/C 线提示词只报不拦核对"),
    (WZY + r"\qc.py", "图片一致性机检（9 项有效 / 5 项无效指标）"),
    (TOOLS + r"\check_preflight.py", "跑前自审 G1–G13 实现（编号跳空 G9/G10 属事实，清单以 ALL_GATES 为准）"),
    # 10-02/10-03 这几件是"声明面对账"的机器，不登记就等于手册里没有它们
    (TOOLS + r"\check_registry.py", "★通道与配置注册表自校验（四方对账：声明／代码／真源／yaml，含 [E] 项目落点与 [G] 决定单三方对账）"),
    (TOOLS + r"\check_thresholds.py", "★阈值注册表自校验（第五件）：值全现读、表里不抄值，authority 与 mirror 不等即 error"),
    (AW + r"\engine\decision_sheet.py", "★运行决定单：值归人的取法只此一处（slots/show/init/set/amend/check/paths）"),
    (TOOLS + r"\qc_batch_consistency.py", "★批内 DINO 相对尺（10-03 唯一被裁接进引擎的那把 QC 主尺）：最低 <0.75 拦、均值 <0.80 警示、量不了记 not_measured"),
    (TOOLS + r"\sync_skill.py", "技能三轴检查器（真源／两份副本的落后天数）"),
    (HERE + r"\check_official_contract.py",
     "★官方契约对账（10-03 批 11，取代批 10 的 check_cam_vocab）：现读官方三份模板抽四张固定值表，"
     "核对唯一转写处与指针、已作废旧数不复活、双反引号渲染、机器表不窄于官方；含 --selftest"),
    (HERE + r"\build_official_lexicon_cn.py",
     "★官方英文词表·中文对照（人审版）生成器（10-03 批 14）：值一个不抄，"
     "全部走 check_official_contract.official() 现读官方三模板；只往上添中文译法。"
     "两道反向自证：官方加词而译法没补→退出码 1 停下（不静默缺行）、副本被手改→--check 报。"
     "输出两份：00_读我 那份＋桌面那份"),
    (TOOLS + r"\post\fx_light.py", "后期叠光管线（10-03 由资产层归位到交付层 tools/post，GAP-D3）"),
    (TOOLS + r"\post\light_scopes.py", "★检光（10-04）：从成片／关键帧量示波器族读数（IRE 落点、削顶塌黑、"
                                       "光比档、对比档、肤色簇角度）。**只量不判**：全份没一个审美阈值，"
                                       "肤色线偏移要人给 `--skin-line-deg` 才算；口径（709 亮度方程、"
                                       "full/limited 摆幅、线性化幂律与量化地板）写进报表抬头。"
                                       "视频走 ffmpeg **码值域直读**，不经 cv2（它自己把 tv 展成 full 并夹掉"
                                       "超范围码值），摆幅旗**只换算一次**。自带 `--selftest`："
                                       "合成帧＋摆幅链自证（旗只算一次／读帧不展幅不夹值／cv2 展幅当活证据）。"
                                       "10-04 再加两组读数：**冷暖分区**（暗部／亮部各自的色度角与饱和，"
                                       "只报角度不冒充色温 K 数）＋**越界两列**（超出合法白／低于合法黑，"
                                       "与「顶到白」分开算）＋**亮面两列**（≥70／≥90 IRE 像素占比＝"
                                       "发光面积：曝光中点分不出「大面积发光体＋雾」与「单主体打光＋黑背景」"
                                       "这两种布光，这个分得出）"),
    (WZY + r"\light_structure.py", "★光影结构提取器（10-04）：把参考片**按镜头切开**再逐镜量光，出「结构卡」"
                                   "（黑位／中灰／白位／对比档／主体左右档＋亮侧／肤色角／冷暖Δ／越界超白）。"
                                   r"**算法一份不重写**，全部调 `tools\post\light_scopes.py`；切点是**启发式**"
                                   "（粗格亮度帧差＞中位＋k×MAD），并把每帧原始帧差一起落盘——切得对不对"
                                   "人眼一扫就知道；`--cut-k` 5 与 8 在范例上给出同一组分镜。只量不判、不建闸"),
    (TOOLS + r"\make_review_sheet.py", "呈审包生成器（编号静帧表 + 并排短片）"),
    # 09-28 新增：十块→官方骨架这条改线的机器件
    (WZY + r"\ab_tenblock.py", "★A/B 实测脚本：十块 vs 官方骨架（5 seed × 2 臂）——十块剥离 H3 的**证据源**"),
    (WZY + r"\to_official.py", "中文十块 → 官方 I2VA 骨架 编译器"),
    (WZY + r"\extract_official.py", "官方骨架字段抽取器"),
    (WZY + r"\verify_official.py", "官方骨架产物核对（G7 判据自证）"),
    (WZY + r"\audit_p_fight.py", "三阶线审计器"),
    (WZY + r"\pack_p_prompts.py", "★三阶 12 镜提示词合订本生成器（09-28 已修：双命名 glob＋缺文件必喊，"
                                  "运镜列改从稿内读；旧「缺文件 ×12」那份快照已由它重生成 212 行）"),
    (WZY + r"\h3_shots.py", "★第一章 A 线编译器：DEGUN 21 条替换表 / SPEAR_LOCK / CAST_LOCK / BASE_CN 基调句，"
                            "词形覆盖自检与坏中文报错都在这"),
    # 09-28 质检判定对齐轮新增的两件
    (WZY + r"\prompt_format.py", "★★提示词格式底座（判格式与切区的**唯一来源**）：识别 骨架/六段/十块/无格式，"
                                 "切 风格·事件·运镜·不变量·声音·台词 六区，混用检测。"
                                 "h3_rule_gate.H3R0、check_preflight.G7、audit_p_fight、other_lines_check 全吃它——"
                                 "改这里会同时改多条链，见冲突表风险 22"),
    (WZY + r"\verify_g7_dispatch.py", "G7 派发改造的对照验证（20 项）：真源 12 份零 error、官方六段在两种 kind 下都走六段、"
                                      "混用四例、图片漏声明、骨架内部故障逐项。跑它即回归"),
    (WZY + r"\archive_superseded_prompts.py", "★判废稿归档器（默认 dry-run）：copy → 逐份 sha256 复核 → **全对才删源**，"
                                             "并写 `_归档_MANIFEST/〈stamp〉/MANIFEST.md`（源路径／大小／mtime／sha256／"
                                             "判废原因／授权原话）。09-28 用它清掉 `prompts/` 里三阶旧十块 12 份（冲突表 C67）。"
                                             "**规则：同名两套并存时先归档再删，不许直接 del；删源前必须逐份哈希对上**"),
    (WZY + r"\detail_p_beats.py", "逐拍拆解器（动作四件：肢体/轨迹/接触点/受力反应）。⚠ 09-28 事故后加了**双旗标默认拒写**"
                                 "（`--force` ＋ `--i-know-this-is-superseded-tenblock-era`）＋写前格式探测："
                                 "它曾把 09-27 文本重刷进已判废的十块稿（风险 23）⇒ **会写源文件的脚本一律默认不写"),
    # 09-28 全盘整理轮新增的机器件（备份工具住在 tools 家）
    (r"D:\AIWorkflow\tools\backup_now.py", "★统一备份工具：类目＝手册/记忆/引擎配置/自产脚本，"
                                          "**同哈希跳过、每类只留最近 5 份快照**；验收口径是 `--check` 报 0。"
                                          "刻意不备份 `E:\\密钥文件`（明文凭证不做第二份复制）"),
    (r"D:\AIWorkflow\tools\一键备份.bat", "上面的免终端入口（桌面留了同名快捷方式；bat 内部 `cd /d D:\\AIWorkflow\tools`，与放置位置无关）"),
    (r"E:\_统一备份\备份位置索引.md", "★本机备份的总账：哪些在 `E:\\_统一备份`、哪些**故意不并进来**"
                                    "（`E:\\归档区` 17 GB、另一项目的 `_backup_repo`、海螺 App 自有目录、"
                                    "手册的 `_改前备份_20260928_质检`）以及各自理由"),
    # ── 10-02 「若水AI电影」架构轮：校验器、扫盘器、交付层补齐件 ──────────────
    # ⚠ 故意**不**登记 E:\若水AI电影\system_manifest.json：它是每次扫盘都重写的派生件
    #   （hand_edit: false），复制进手册＝造出一个永远"落后"的第二份，正是本层要避免的漂移真源。
    (MAINT + r"\check_layers.py", "★两层规则体系自校验器（只读、默认退出码 0＝只报不拦，--strict 才返回 1）。五项：① 指针有效性（含行号锚与「」关键词锚；绝对路径直接判存在性）② T1 名词剥离（词表含从 30_项目层\\P_* 目录名自动派生的项目代号）③ 反向索引完备性 ④ 冲突项清点（三个数分开报、不凑数）⑤ 执行者标记覆盖率。ALIASES 表吃掉 v1.md:835／方案 §3.3 这类简写，查不到报 ○ 简写未登记而不是 ⚠ 指针失效——假告警会淹没真告警"),
    (TOOLS + r"\review_publish.py", "★审片区发布器（批2 GAP-D1 补齐件）：secrets 生 16 位 hex 无鉴权 token；ffprobe 判要不要压（已在目标码率内就不重编码）；ffmpeg -movflags +faststart 压到 1 Mbps；scp 的 known_hosts 走绝对 Windows 路径以绕开中文用户名的 MSYS 乱码坑；上传后真发 Range 请求验 206，验不过 exit 3 不报已交付；--delete 只认 16 位小写 hex 否则拒执行 rm；--dry-run 零联网零上传。⚠ 无鉴权=知道 URL 就能看；实测服务器现存 6 个历史审片夹未清，说明「审完删」过去没被执行"),
    (TOOLS + r"\feishu_send.py", "★飞书审片三件套封装（批2 GAP-D2 补齐件）：锁死 lark-cli 全路径（两处真安装都不在 PATH）；顺序 ①文本结论 ②逐镜拼图 ③成片＋封面（媒体消息不能带文字，所以是三条不是一条）。封住的坑：媒体旗标只收 cwd 相对路径（绝对路径被拒）⇒ 内部 chdir；--video 必须配 --video-cover；30 MB 超限改走审片区而非压糊；输出是带空格 pretty JSON ⇒ 用 json 解析不用 grep。⚠ 只报「服务端接单」，接收侧未证实不承诺；默认不发，须 --yes"),
    (r"E:\若水AI电影\99_维护\scan_system.py", "★「若水AI电影」七层现状扫盘器（只读）→ 生成 E:\\若水AI电影\\system_manifest.json。M1 的机器化：每个数字运行时算、源码不写死计数；每条 gap 必带 evidence/missing 且脚本自己复核，复核不过标 evidence_broken；量不到写未测量。确定性自证＝连跑两次除 generated 外逐字相同（故耗时字段不进 JSON）。唯一的例外：为把测试数量准，会跑一次 pytest --collect-only（只收集不执行）"),
    (r"E:\若水AI电影\00_架构总纲.md", "★七层架构唯一入口（人读）。不拥有任何规则：规则权威仍是 20_通用规范层\\；它与本层冲突时以本层为准，并把冲突记成一条 gap"),
    (MAINT + r"\check_tables.py", "★自写文档表格列数自检（只读）。本层大量规则靠表格承载列级语义"
                                 "（判据／执行者／槽），**错一列＝错一条规则**，而这种缺陷肉眼读源码看不出来"),
    (FILM + r"\99_维护\scan_system.py", "★★「若水AI电影」七层现状扫盘器（只读）→ 生成 `E:\\若水AI电影\\system_manifest.json`。"
                                       "M1 的机器化：每个数字运行时算、源码不写死计数；每条 gap 必带 `evidence`/`missing` "
                                       "且脚本自己复核，复核不过标 `evidence_broken`。确定性自证＝连跑两次除 `generated` "
                                       "外逐字相同（所以**耗时字段不进 JSON**）。判据必须机械可复跑，"
                                       "不许写死文件名／行号／计数"),
    (FILM + r"\00_架构总纲.md", "★七层架构唯一入口（人读）。**不拥有任何规则**：规则权威仍是 `20_通用规范层\\`；"
                              "它与本层冲突时以本层为准，并把冲突记成一条 gap"),
]

# Qoder 记忆条目：全部纳入，除下列非工作流项
MEM_EXCLUDE = {
    "user-hotel-business-side.md",            # 酒店业务
    "reference-jineetian-hotel-pms.md",       # 酒店 PMS 接口
    "reference-virtual-visa-card.md",         # 支付卡
    "reference-user-website.md",              # 网站运维（非本地生成工作流）
    "reference-user-browser-shopping.md",     # 购物
    "reference-stellarblade-ue4ss-trap.md",   # 游戏 MOD
    "feedback-server-security-reporting.md",  # 服务器安全汇报
}

# 明确不搬的重复副本 / 厂商自带文档 —— 要写进清单说明理由
DUP_NOTES = [
    (r"E:\创作\_待审文档\H3提示词工程规则方案.md",
     "未搬", "与 D:\\AIWorkflow\\ComfyUI_H3\\ 真源 md5 全等（由 h3_rule_gate.py --sync 回写的桌面快照），"
             "内容一致，只留一份"),
    (r"E:\公共记忆\skills\cinematic-video-production\**",
     "未搬", "与事实源 `C:\\Users\\若水\\.qoder\\skills\\cinematic-video-production\\` **逐字镜像**"
             "（SKILL.md 与 23 篇 references 中 9 篇 md5 全等，其余按既有约定视为同步副本）；只留事实源一份"),
    (r"D:\cinematic-video-production-portable\cinematic-video-production\SKILL.md 及 references\**",
     "已并列搬入 04b", "**更正记录**：初判按 mtime 认定 D 盘版更新（23 篇全部 09-23 17:15-17:37，"
             "晚于事实源 09-21/09-23 15:xx），故曾取它作 canonical —— **判错**。"
             "实读 diff 证实它是**刻意去本机化的可分发版**：账户单价被改写为「只讲计价方式、不写死数字」、"
             "项目名匿名化（「双姝」→「某双人打戏项目」）、本机路径标「略」。"
             "mtime 新 ≠ 权威。本地手册以 .qoder\\skills 事实源为主，脱敏版并列保留供比对"),
    (r"D:\AIWorkflow\engine\_backup_20260903_pre_*\README.md",
     "未搬", "引擎备份目录，已被现行 engine\\README.md 取代"),
    (r"D:\AIWorkflow\engine\examples\first-run\ 及 _backup_*",
     "未搬", "备份/示例快照，非现行规则"),
    (r"D:\AIWorkflow\training\toolkits\ai-toolkit\README.md, FAQ.md, dgx_instructions.md",
     "未搬", "第三方工具库自带文档（ostris/ai-toolkit），非本项目约定；要用请直接读上游"),
    (r"D:\AIWorkflow\ComfyUI_H3\ComfyUI\README.md, AGENTS.md, CONTRIBUTING.md, SECURITY.md, QUANTIZATION.md",
     "未搬", "ComfyUI 上游仓库文档，非本地工作流约定"),
    (r"D:\AIWorkflow\LivePortrait-main\readme*.md",
     "未搬", "LivePortrait 上游文档；该链路当前不在生产主线上"),
    (r"E:\创作\_归档\**\*.txt",
     "未搬", "归档区的一次性运行日志与调试输出（ollama/uia/shot 等），无规则价值"),
    (r"D:\AIWorkflow\ComfyUI_H3\prompts\*.txt（56 个；另有一份 `读我_本目录已是十块旧写法.md`）",
     "未搬", "逐镜/逐段提示词正文，属作品资产而非参数规则。"
             "⚠ 09-28 两次更新：①这里的三阶稿（`wuzhaojunyi_三阶P1A_拦路.txt` 等，带镜名后缀）是**十块旧写法**，"
             "09-28 00:54 起 H3 视频层真源换成 `prompts_H3官方骨架`（12 份，无镜名后缀），那 12 份已收进 "
             "`09_项目执行与审计\\无昭君仪\\H3官方骨架提示词`；②**同一批 12 份旧十块已于 09-28 归档删源**"
             "（copy→逐份 sha256→删，落 `E:\\图像影音资源池\\武昭君仪\\_判废归档_20260928\\prompts`，"
             "清单在同级 `_归档_MANIFEST\\`）⇒ 本目录不再与三阶镜号重名。"
             "**剩余 56 份 `detect_format` 实测 56/56 全是十块**（无音镜 4/6/7/8/9、seg01–08、shot5_clash_A/B、"
             "09-26 试验稿），开闸后拿它们跑 H3 会被 G7 判混用；目录内已放一份 `读我_…` 挡人，故**本手册不再收它的正文**。"
             "⇒ 目录名与文件名字面都相近，**别按名字认权威，按目录时间戳＋文档指认**"),
    (r"D:\AIWorkflow\ComfyUI_H3\prompts\读我_本目录已是十块旧写法.md",
     "已搬", "★这份是挡路灯条不是作品正文 ⇒ 收进 `09_项目执行与审计\\无昭君仪\\读我_H3prompts目录现状.md`（见 FILES 段）"),
    (r"D:\AIWorkflow\ComfyUI_H3\prompts_官方三段式\**（14 个 txt，26 KB）",
     "未搬", "09-28 新查出的**过渡形态目录**：同一批三阶镜的早期官方三段式写法稿，文件名带 `_拦路/_试探/仅去星号/官方骨架无元信息` 等后缀变体"
             "（P1B 一个镜在这里有 3 个变体）。现行真源已是 `prompts_H3官方骨架`（12 份无后缀名，39 KB），"
             "此处属同一产物的旧形态 ⇒ 只留最新一份，避免三个目录都被当权威（见冲突表 C1'）"),
    (r"D:\AIWorkflow\tmp\jianlai_test\*.txt, D:\AIWorkflow\tmp\wzy\*.log",
     "未搬", "单次跑批的临时产物与日志"),
    (r"E:\创作\武昭君仪\武昭君仪资产包\index.md（同旧注）",
     "已并回", "⚠ 10-02 更正：本条原写「`index.md` 未搬，被同目录 `index (1).md` 取代」——"
             "当时确实如此（`(1)` 多 v3.4 复审反馈与 v3.5 定案两段，mtime 00:55→01:04）。"
             "本轮已按 sha256 证实旧 `index.md` 是 `(1)` 的逐字节前缀（合并无损），"
             "把超集并回干净文件名 `index.md`、删掉 `(1)` 副本；"
             "现行源路径与本文件上方那条登记一致，手册落点名不变。两份原件都在"
             "`99_维护\\_改前备份_20261002_sidecar迁移\\`。"),
    (r"E:\创作\武昭君仪\写作计划_v1.0–1.3.docx, 设定与大纲_v0.5.docx, 第X章_*.docx, 说到古人穿越赛博朋克.docx",
     "未搬", "正文与文学设定（.docx），属作品资产而非工作流参数规则；同目录 `_H3实测`、`_实测输出`、"
             "`首帧图`、`火柴人参考`、`武昭君仪资产包`（除 index）为素材，亦未搬"),
    (r"E:\创作\武昭君仪_重写版\正文\第01–08章*.md, _作废_旧版正文\第01–03章*.md",
     "未搬", "11 份章节正文＝作品资产而非规则；只收同目录三份**规划/规范**文档（设定与大纲 / 写作计划 / 文风规范）。"
             "`_作废_旧版正文` 是被判定「AI 味太重」的旧版，按「提示词只留最新版」同一条约定不收"),
    (r"E:\创作\武昭君仪\_H3实测\三阶打斗\武昭君仪_三阶打斗_提示词全集.md（26,005 B）",
     "源已消失", "★09-28 01:30 复核：00:44 实读存在（26 KB、含 12 镜提示词全文），现已不在该目录，"
             "全盘 find 与回收站（`$Recycle.Bin` 下 `$I*` 元数据，只有两份无关的 C 盘 TEMP 解包残留）均未命中 ⇒ "
             "**判为刻意删除（不进回收站＝脚本/永久删），非移动非改名**。"
             "内容现由两处覆盖：① 12 份新真源 `prompts_H3官方骨架`\\\\wuzhaojunyi_三阶P??.txt`（00:54，已收）；"
             "② 3677 B 总览快照（01:04，已收，但其逐镜全文段 12 处全报「缺文件」——"
             "`pack_p_prompts.py` 仍读这批已消失的旧文件）。⇒ 全文只信 ①"),
]


def sha256(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def build_map():
    """展开成 (src, dst_dir, dst_name, role, note) 列表"""
    rows = list(FILES)
    for base, sub, names, role, note in PROJECT_BULK:
        for n in names:
            rows.append((os.path.join(base, n), sub, os.path.basename(n), role, note))
    for p, note in SCRIPTS:
        rows.append((p, r"10_机检与工具脚本_只读参考", os.path.basename(p), "reference", note))
    if os.path.isdir(MEM):
        for n in sorted(os.listdir(MEM)):
            if n.endswith(".md") and n not in MEM_EXCLUDE and os.path.isfile(os.path.join(MEM, n)):
                rows.append((os.path.join(MEM, n), "08_Qoder记忆_现行约定", n, "live",
                             "Qoder 跨会话记忆条目（现行约定）；真源在 .qoder\\memory，副本会漂移"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只核对副本是否落后于源，不写文件")
    # 10-02 新增。**默认行为不变**（仍恒返回 0）——现有双击的 `刷新副本.bat` 不能因为
    # 加个闸门就突然失败。要机器判「落后／真源缺失」就显式加 --strict。
    # 这正是 GAP-R2 说的病：`--check` 恒 return 0 ⇒ 收尾三件套的「复验」那一步没有闸门。
    ap.add_argument("--strict", action="store_true",
                    help="配合 --check：有落后或真源缺失时退出码 1；不带 --check 时：有真源缺失退出码 1")
    args = ap.parse_args()

    rows = build_map()
    entries, missing, stale, ok = [], [], [], 0

    for src, dsub, dname, role, note in rows:
        src = os.path.abspath(src)
        if not os.path.isfile(src):
            missing.append(src)
            continue
        st = os.stat(src)
        src_hash = sha256(src)
        dst = os.path.join(DEST_ROOT, dsub, dname)
        changed = None
        if os.path.isfile(dst):
            changed = (sha256(dst) != src_hash)
        if not args.check:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if changed is None or changed:
                shutil.copy2(src, dst)
        entries.append({
            "source": src,
            "dest": os.path.join(dsub, dname),
            "role": role,
            "note": note,
            "bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "sha256": src_hash,
            "was_stale": changed,
        })
        if changed is None:
            # 副本不存在：旧口径把它既不算 ok 也不算 stale，于是 --check 会「假绿」——
            # 新增的源文件在手册里没有副本，检查却报 0 个落后（同族坑：备份验收器假绿）。
            stale.append(dsub + "\\" + dname + "（副本不存在）")
        elif changed:
            stale.append(dsub + "\\" + dname)
        elif changed is False:
            ok += 1

    if args.check:
        print("源缺失 %d 个；副本落后于源 %d 个；已同步 %d 个" % (len(missing), len(stale), ok))
        for s in stale:
            print("  需刷新:", s)
        for m in missing:
            print("  找不到:", m)
        if args.strict and (missing or stale):
            print("!! --strict：有落后或真源缺失 ⇒ 退出码 1")
            return 1
        return 0

    mdir = os.path.join(DEST_ROOT, SEC_MANIFEST)
    os.makedirs(mdir, exist_ok=True)
    total = sum(e["bytes"] for e in entries)
    meta = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dest_root": DEST_ROOT,
        "file_count": len(entries),
        "total_bytes": total,
        "missing_sources": missing,
        "excluded_duplicates": [{"path": p, "decision": d, "reason": r} for p, d, r in DUP_NOTES],
        "memory_excluded": sorted(MEM_EXCLUDE),
        "entries": entries,
    }
    with open(os.path.join(mdir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    lines = [
        "# 来源清单 / MANIFEST",
        "",
        "生成时间：%s ｜ 入选 %d 个文件 ｜ 合计 %.1f MB ｜ 目标目录 `%s`"
        % (meta["generated"], len(entries), total / 1048576, DEST_ROOT),
        "",
        "> 本表所列条目全部为**副本**。每个条目的真源路径在下表 `真源路径` 列，改东西一律改真源，再跑 `build_manual.py` 刷新副本。",
        "> 源文件在本次操作中**只被读取，未被写入或删除**（逐文件 sha256 见 `manifest.json`）。",
        "> 例外：`00_读我\\`（3 篇导航/速查/冲突裁定）、`99_维护\\build_manual.py`、`刷新副本.bat` 是本次**新写的**，无真源，不在下表内。",
        "",
        "## 一、入选文件（按主题目录）",
        "",
    ]
    for top in sorted({e["dest"].split("\\")[0] for e in entries}):
        grp = [e for e in entries if e["dest"].split("\\")[0] == top]
        lines += ["", "### %s （%d 个）" % (top, len(grp)), "",
                  "| 文件 | 角色 | 大小 | 源修改时间 | 真源路径 |", "|---|---|---|---|---|"]
        for e in sorted(grp, key=lambda x: x["dest"]):
            name = os.path.relpath(e["dest"], top).replace("\\", os.sep)
            lines.append("| %s | `%s` | %.1f KB | %s | `%s` |" % (
                name, e["role"], e["bytes"] / 1024, e["mtime"], e["source"]))
    lines += [
        "", "## 二、明确未搬入的重复副本与厂商自带文档", "",
        "| 路径 | 决定 | 理由 |", "|---|---|---|",
    ]
    for p, d, r in DUP_NOTES:
        lines.append("| `%s` | %s | %s |" % (p, d, r))
    lines += [
        "", "## 三、Qoder 记忆条目中被排除的非工作流项", "",
    ] + ["- `%s`" % n for n in sorted(MEM_EXCLUDE)]
    if missing:
        lines += ["", "## 四、清单里登记但实际找不到的源（需核对路径）", ""]
        lines += ["- `%s`" % m for m in missing]
    lines += ["", "## 五、校验和", "",
              "逐文件 sha256 见同目录 `manifest.json` 的 `entries[].sha256`。",
              "任何时候跑 `py -3.12 \"E:\\本地工作流规范手册\\99_维护\\build_manual.py\" --check` "
              "即可知道哪些副本已落后于真源。",
              "⚠ **`--check` 不带 `--strict` 时退出码恒 0**（10-02 加了 `--strict`，"
              "默认行为刻意不变，免得现有双击的 `刷新副本.bat` 突然失败）。",
              "要机器判闸门就写：`... --check --strict` ⇒ 有落后或真源缺失时退出码 1。", ""]
    with open(os.path.join(mdir, "MANIFEST.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("已写入 %d 个文件，%.1f MB -> %s" % (len(entries), total / 1048576, DEST_ROOT))
    print("刷新时覆盖的落后副本 %d 个" % len(stale))
    if missing:
        print("!! 源缺失 %d 个：" % len(missing))
        for m in missing:
            print("   ", m)
    if args.strict and missing:
        print("!! --strict：有真源缺失 ⇒ 退出码 1（副本已刷新，但清单里有登记了却不存在的路径）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
