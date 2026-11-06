---
name: reference-minimax-api
description: MiniMax/Hailuo API 接入手册——密钥文件位置、按量 REST 契约（首尾帧 base64 可传）、mmx-cli；**★sk-cp(Token Plan) key 只认 api.minimax.io、额度已耗尽(429)；M3 原生多模态 image_url/video_url**；按量 key 有模型但零余额；可灵 key 已活
metadata:
  type: reference
---

**密钥文件（对话/命令中勿输出明文；读文件传 Bearer）**：
- `E:\密钥文件\海螺ai.txt` = `sk-api-` 按量 key：api.minimax.cn 上有效（/v1/models 200）但**视频按量余额 0**——create task 返回 HTTP 200 + `base_resp.status_code 1008 insufficient balance`、task_id 空串（2026-09-08 实测）
- `E:\密钥文件\Token Plan.txt` = `sk-sp-` 订阅 key：**REST 直调被拒**（api.minimax.cn 与 api.minimaxi.com 均 1004 "login fail"）；订阅 key 与按量 key 不可互换，多模态须走 mmx-cli；mmx-cli login 成功但 quota 仍 1004 → **疑似未分配席位/积分**，需用户查 https://platform.minimax.cn/user-center/payment/token-plan

**按量 REST 契约**（Hailuo-02 首尾帧；官方文档 llms.txt 可整站检索）：
- `POST https://api.minimax.cn/v1/video_generation`：model `MiniMax-Hailuo-02`；`first_frame_image`/`last_frame_image` 接受**公网 URL 或 base64 data URL**（≤20MB、短边>300px、宽高比 0.4-2.5，视频尺寸跟随首帧）；`prompt_optimizer=false` 精确控制；prompt 支持 15 种 [指令] 运镜语法（[固定][推进][拉远][晃动][跟随]…）；duration 6|10（768P）/ 仅 6（1080P）；**首尾帧不支持 512P**
- 查询 `GET /v1/query/video_generation?task_id=`；下载 `GET /v1/files/retrieve?file_id=`
- 新 v2：`POST /v2/video_generation`，model `MiniMax-H3`（768P/2K、4-15s、首尾帧+多模态参考）/ `MiniMax-H3-Max`（480P/768P 极速），content 数组 role=first_frame/last_frame/reference_*

**mmx-cli**（Token Plan 唯一通道）：`npm i -g mmx-cli`（1.0.25）；git-bash shim 损坏（同 kling-cli 病）→ node 直调 `$LOCALAPPDATA/nodejs/node_modules/mmx-cli/dist/mmx.mjs`；登录 `auth login --api-key <key> --region=cn`（**等号语法**，空格写法只打印 help）；cn 端点 api.minimaxi.com

**★★ 2026-09-25 复核：新出现的 `sk-cp-` key（Coding/Token Plan）——host 选错就 401，选对就 429**

`E:\密钥文件\minimaxm3.txt` 里有两把 key：第 1 行 `sk-cp-...`（Token Plan / Coding Plan，新增）、下面「按量付费」段是 `sk-api-...`（与 `海螺ai.txt` 同一把）。

**决定性的 host 事实（9 个 host×path 组合实测）**：

| host | `/v1/models`（sk-cp） | `/anthropic/v1/models`（sk-cp） |
|---|---|---|
| **`api.minimax.io`** | **200 ✅**（列表含 MiniMax-M3 首位） | **200 ✅** |
| `api.minimaxi.chat` | 200 ✅（疑似别名） | 404 |
| `api.minimax.cn` | **401 invalid api key (2049)** | 401 authentication_error |
| `api.minimaxi.com` | **401 invalid api key (2049)** | 401 authentication_error |
| `api.minimax.chat` | 401 (2049) | 返回 HTML 前台页 |

⇒ **`sk-cp-` 这把 key 只认 `api.minimax.io`（国际站）**；`.cn` / `.minimaxi.com` 一律 401。旧文档口径"cn 用 api.minimax.cn"对这把 key 是错的。（对比：`sk-api-` 那把在 `.cn` 和 `.minimaxi.com` 上 `/v1/models` 都是 200。）

**认到了但用不了**：`POST https://api.minimax.io/v1/chat/completions`（model `MiniMax-M3`）与 `/anthropic/v1/messages` **都返回 HTTP 429**：`Token Plan usage limit reached: Upgrade your Token Plan or purchase Credits for more usage. (2056)`。即 host 与鉴权已通，卡在**套餐额度**（Token Plan 是 5 小时窗 + 周窗双限）。要恢复正常用，须用户本人去 `https://platform.minimax.io/user-center/payment/token-plan` 看窗口/买积分。

**M3 的多模态能力（官方 OpenAI 兼容文档原文，2026-09-25）**：
- `base_url = "https://api.minimax.cn/v1"`（文档给的国内口径）/ 端点 `/chat/completions`；模型 `MiniMax-M3`（另有 M2.7 / M2.7-highspeed / M2.5 / M2.5-highspeed / M2.1 / M2.1-highspeed / M2）。
- **支持图片输入**：`image_url` content block，`detail` 可取 `low|default|high`，JPEG/PNG/GIF/WEBP、≤10MB；**支持 `video_url`**；**不支持音频输入**。可选 `extra_body={"reasoning_split": True}`。
- ⚠️ **别拿 AI SDK 那页当依据**：`vercel-minimax-ai-provider` 页面写"不支持 image/file 输入"是**那个 provider 封装层的限制，不是模型的限制**——M3 在 OpenAI 兼容层是原生多模态（官方定位"原生多模态、1M 上下文的 Frontier Coding 模型"）。
- Anthropic 兼容端点：`https://api.minimax.cn/anthropic`（对应国际站 `https://api.minimax.io/anthropic`），env 为 `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`。

**⚠️ 2026-09-16 复核（key 有效但账户里没有图像模型、也没有余额）**：
- `GET /v1/models` 在 `api.minimax.cn` 与 `api.minimaxi.com` **两个 host 都返回 200**——`sk-api-` 这把 key 本身有效。
- 但返回的模型列表**只有 8 个对话模型**（`MiniMax-M3` / `M2.7` / `M2.7-highspeed` / `M2.5` / `M2.5-highspeed` / `M2.1` / `M2.1-highspeed` / `M2`），**一个图像模型都没有**。
- `POST /v1/image_generation`（`model: image-01`）→ HTTP **200** 但 `base_resp.status_code = 1008 insufficient balance`、`data: null`。

→ **结论：这把 key 的出图通道是死的，它的账户里根本没有图像模型。** 用户说的"MiniMax 还有好多积分"**不在这个账号上**，而在 `MiniMax Design` 那个桌面 App（App 的积分是另一套账，见 [[reference-hailuo-design-tool]]）。以后再听到"MiniMax 有额度"要先问清是**App 的**还是**这把 API key 的**。

**Why:** 2026-09-08《无音》同帧盲测被卡——云端三通道余额全零（可灵灵感值 0 / MiniMax 按量 0 / Token Plan 无席位），充值/席位分配是账号级操作必须用户本人完成。**同日后续：用户给出可灵开放平台 API key（`E:\密钥文件\可灵api.txt`，独立于网页灵感值计费）后云端通道复活**（见 [[reference-kling-api]]）；MiniMax 双 key 截至当日仍死。
**How to apply:** 提交后先看 base_resp.status_code（1008=余额、1004=key 类型/区域）；单价见 [[reference-ai-pricing]] MiniMax 节；账号状态变化快，用前重新 account/quota 实测。相关：[[reference-kling-cli]]、[[localai-video-model-plan]]。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- 海螺 H3 REST 契约/mmx-cli
