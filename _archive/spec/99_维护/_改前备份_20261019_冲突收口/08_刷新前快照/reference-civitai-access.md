---
name: reference-civitai-access
description: Civitai 本机接入手册——直连不通须走代理 7890、key 在 E:\密钥文件\civitai.txt、下载端点要登录、Cloudflare 拦 urllib 只放 curl；🔴 API 的 search= 参数被静默忽略（必须用 query=）；HF 单源搜会严重低估 LoRA 供给
metadata:
  type: reference
---

Civitai 是 LoRA 的主库，HF 上大量 LoRA 只发在 civitai。本机接入实测（2026-10-04）。

## 通道

- **直连不通**：`curl https://civitai.com/...` → `http=000`；`WebFetch` → `fetch failed`。
  必须走代理：`-x http://127.0.0.1:7890`（代理客户端见 [[reference-local-network-baseline]]）。
- **API key**：`E:\密钥文件\civitai.txt`（32 字符）。**只报长度/类型，永不回显**
  （[[feedback-credential-no-echo]]）。
- 🔴 **`urllib` 被 Cloudflare 拦**：带 Bearer 的 urllib 请求回 **403 / `error code: 1010`**（按客户端指纹），
  而 **curl 能过 CF**。⇒ 取 civitai 一律用 curl，别用 `urllib`/`requests` 默认 UA。
- **下载端点要登录**：无 key 时 `https://civitai.com/api/download/models/<versionId>` 回 **401**
  `{"message":"The creator of this asset requires you to be logged in to download it"}`。
  带 key 后是 **307 → `b2.civicai/b2.civitai.com`**。

## 下载的正确姿势（四条都是踩出来的）

1. **key 不进 argv**：用 `curl -K -`，配置从 stdin 喂进去（`header = "Authorization: Bearer …"`）。
   写进命令行会进进程表，写临时文件会落盘。
2. **别把 key 透传给 CDN**：第一跳带 Authorization 只为解析重定向；
   **第二跳取文件时不带凭证**。
3. **Windows 上没有 `/dev/null`**：`output = /dev/null` 会让 curl 报 `(23) client returned ERROR on write`，
   而且此时 `%{redirect_url}` 是空的 ⇒ 用 `output = NUL` ＋ `dump-header = -`，自己从响应头里解 `Location:`。
4. **CDN 会中途断供**：实测 648 MB 下到 222 MB 报 **curl (18) end of response with 457 MB missing**。
   ⇒ 续传用 `continue-at = -`，且**每轮都要重新解析一次第一跳**（CDN 的签名 URL 限时）。
   **完成判据用 SHA256 命中，不用猜字节数**——civitai 的 API 每个文件都给 `hashes.SHA256`，
   这是比 HF 更强的一道对账（HF 的 `blobId` 是 LFS 指针的 git blob id，**不是内容 sha256**，
   见 [[reference-cn-download-mirrors]]）。

## 🔴 参数坑：`search=` 被静默忽略，必须用 `query=`

`GET /api/v1/models?types=LORA&search=midjourney&sort=Most%20Downloaded`
**不管 `search=` 填什么，返回的都是同一张"全站最高下载"通用榜**（实测两组不同关键词返回逐条相同）。
它不报错、不返回空——**返回一份看起来完全正常的列表**，于是"我搜过了、没有"是假的。
换成 `query=midjourney` 才真正过滤（命中 40 条，其中 Z-Image 底 3 条）。

**判据**：拿一个过滤参数下"不存在/没有"的结论之前，
必须①换一个已知能命中的词跑同一参数看返回是否随之变化；②或换参数名再跑一遍。
同族见 [[feedback-evidence-loop-trap]] ㉘。

## 另一条同类误判：只搜 HF 会严重低估 LoRA 供给

我先只在 hf-mirror 搜，得出"Z-Image 风格 LoRA 生态很小、没有 MJ 类"。
经代理查 civitai 后**推翻**：Z-Image 头部 LoRA 下载量 4k–16k，
MJ 风格 for Z-Image **有三件**（`Midjourney Luneva Cinematic Lora` 16,008 dl／作者 luneva／648.8 MB R128；
`MIDJOURNEY_V1_Z-image_Turbo` 5,115 dl／162.2 MB；`MIDJOURNEY_ ZIB` ZImageBase 1,228 dl）。
⇒ **判"某模型有没有 LoRA/生态大不大"必须双源查（HF ＋ civitai），单源结论只能写"HF 上没有"。**

## 许可：civitai 上"未标许可"是常态，不是例外

- 上面三件 MJ LoRA 的 `licensing` 字段全是 **`null`**（`meta` 也是 null），哪怕 16k 下载、1471 赞。
- 🔴 **HF 镜像上的许可标签可能是转帖者自己标的**：`mkczer/Midjourney_Luneva_Cinematic_Lora`
  frontmatter 写 `license: apache-2.0`，但**原作者 luneva 的 civitai 页 licensing 为 null**，
  而且那个 HF 仓是**空壳**（siblings 只有 `.gitattributes` ＋ `README.md`，没有任何权重文件）。
  ⇒ **非权利人贴的许可 ≠ 许可**；要引用必须核到原作者口径。
- 对照：`tarn59/pixel_art_style_lora_z_image_turbo`（HF，Apache-2.0，10,018 dl）与
  `DK9/3D_MMORPG_style`（Apache-2.0）、`Quorlen/…Sunbleached…`（MIT）是许可干净的可用样本。
- 按 [[reference-color-lighting-standards]]／用户的"未标 license 不引用"规矩，
  null 许可的件**可以下载本地试**，但**进商用产出前风险归他裁**（[[reference-ai-content-publishing-douyin]]）。

## 装机前先读 header（省一整轮误判）

safetensors 的 `__metadata__` 里 `ss_tag_frequency` 就是**触发词表**（例：
`{"1_Pixel art style.": {"Pixel art style.": 1}}` ⇒ 触发词是整句 `Pixel art style.`）。
civitai 侧对应字段是 `modelVersions[].trainedWords`（空数组＝不需要触发词）。
**读 header 不到 1 秒，跑一张图 6~16 秒**——先读再测，否则会像 10-04 那样把"没触发"误报成"没生效"。
键名前缀也要一起看：社区 LoRA 多为 `diffusion_model.layers.N.…`，ComfyUI 剥掉 `diffusion_model.` 后
与底模的 `layers.N.…` 一一匹配（int8-convrot 底模实测吃 LoRA，见 [[reference-local-image-chain]]）。

**How to apply**：要 LoRA/风格件时，双源查（civitai `query=` ＋ hf-mirror `search=`），
按下载量＋许可筛，读 header 确认触发词与底模匹配，再走上面的 curl 姿势下载并按 SHA256 对账。
脚本：`D:\AIWorkflow\tmp\wzy\civitai_dl.py`（curl 经 stdin 拿配置、双跳不透传 key、断点续传、哈希判完成）、
`lora_probe.py`（读 rank／键前缀／触发词）。相关 [[reference-cn-download-mirrors]]、
[[reference-local-image-chain]]、[[feedback-credential-no-echo]]、[[feedback-third-party-skill-install]]。
