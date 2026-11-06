---
name: reference-kling-api
description: 可灵开放平台 REST API 直调——Bearer 单密钥（E:\密钥文件\可灵api.txt）、api-beijing host、i2i 锁脸参数、22s/张；与 kling-cli 网页账号（0灵感值）无关
metadata:
  type: reference
---

可灵开放平台 REST 直调（2026-09-08 实测，用户指定为《无音》图+视频主通道，理由：与后续视频生成保持一致性）：

- **密钥**：`E:\密钥文件\可灵api.txt`，单行 `api-key-kling-...`，直接 `Authorization: Bearer <key>`（**不是** ak/sk JWT 那套）。勿在对话/记忆存完整 key。
- **Host**：`https://api-beijing.klingai.com`（CN 密钥只认这个；api.klingai.com 报 Auth failed、api-singapore 报 api key not found）。
- **生图**：POST `/v1/images/generations`，`model_name=kling-v2-1`；i2i 传 `image`=base64 + `human_fidelity`（锁人，用 0.9）+ `image_fidelity`（跟参考图程度，用 0.4 放开服饰/构图）；t2i 传 `aspect_ratio="9:16"`。返回 task_id 后 GET `/v1/images/generations/{task_id}` 轮询，succeed 时 `data.task_result.images[0].url`。单张约 22s。
- **锁脸效果**：以 `E:\创作\无音\locked\第01集\s13.jpg` 为参考，花钿/步摇/蓝花钗复现良好；画风比 s13 偏干净 3D（略 doll-like），全身立像构图（比中近景更适合定妆）。
- **与 kling-cli 的区别**：kling-cli（[[reference-kling-cli]]）走网页账号 OAuth，灵感值 0 已卡死；本 API key 是开放平台独立计费，两者互不相通。视频生成同 host `/v1/videos/*`，首尾帧/多图参考契约与 CLI 一致，可复用同 key 保证图视频同模型系。
- **封装**：`C:\Users\若水\Desktop\无音项目\工具\gen_wy_kling.py`（dz / shots 模式，复用 gen_wy3_assets 的 DZ 与 parse_shots）。
- **产线规则（2026-09-08 《无音》14 定妆+首帧实测定案）**：
  - **余额闸门**：余额耗尽报 HTTP 429 + `code 1102 Account balance not enough`（429 是外壳别误判限流）；充值只能真人去可灵开放平台控制台，agent 无绕行；2026-09-08 首充额度约 140 张图后耗尽，剩 16 镜待补。
  - 画风统一靠**所有提示词前置同一 STYLE_CLAUSE**（半写实3D/柔暖白主光/中灰渐变背景），不靠参考图传风格；
  - 主角 i2i ref=s13 hf0.9/if0.4 锁脸；**配角纯 t2i**——i2i 无论 hf 多低（0 也漏）都会漏参考图的花钿/发髻/服饰，negative_prompt 也拦不住（探针证伪）；
  - i2i 的 image_fidelity 同时锁服饰且**几乎不可破**：换装（e03 围裙）在 if 0.25/0.1、镜头级围裙从句前置全部失败 → 换装只能换参考图本体或接受偏差（E3 全集用 e01 系襦裙，偏差已写入人设圣经）；
  - **文字纪律**：提示词里引号汉字/"上书…"必被渲染成乱码（偶尔反而正确，如"不算骗"/"字会伤人"），脚本层 sanitize 成"纸面空白无字"、文字后期叠；**sanitize 正则须同时吃直引号与弯引号**（分镜 md 用直引号，首跑漏配导致 6 镜乱码返工）；
  - 构图漂移（胸像/全身随机）用 FRAMING 前缀+"构图下缘到鞋"压，仍输就换参考图连构图一起锁（e03 用 e01 全身做 ref）；
  - 每批出 contact sheet 自检（目检_*.jpg），漂移镜单张重跑；
  - **限流**：连发提交偶发 HTTP 429（21 镜返工批跑到第 6 镜起全 429，而 72 镜连发批曾全过），request 层内置 30s×5 退避重试后全过；大批量保持串行即可。

**How to apply:** 用户要《无音》生图/生视频默认走本通道；ARK（[[reference-ark-account]]）欠费未结清前不作主通道。批量先单张试跑目检再放量。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- Bearer 单密钥（密钥文件在册）、api-beijing host、i2i human_fidelity 锁脸、22s/张
- **2026-09-08 余额耗尽(code 1102)已停**
