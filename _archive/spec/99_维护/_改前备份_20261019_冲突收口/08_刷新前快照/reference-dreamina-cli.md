---
name: reference-dreamina-cli
description: 即梦官方 CLI（dreamina.exe）调用方式与凭证——无 API Key 走本机 OAuth 会话（artisan；2026-09-15 余额 72 积分）；**⚠️ image2image 已按张扣积分（2026-09-15 实测一张扣 8；早前"credit_count=0 免费"记录已不成立）**、支持 1-10 张输入图、模型到 5.0Pro；CLI 只回 URL 不落盘需自行下载；完整文档在 E:\密钥文件\即梦api.txt
metadata:
  type: reference
---

即梦（Dreamina）官方 CLI 与本机状态（2026-09-09 初测，2026-09-13 更新）：

- **可执行文件**：`C:\Users\若水\bin\dreamina.exe`（v1.4.17；官方安装 `curl -fsSL https://jimeng.jianying.com/cli | bash`）。
- **凭证＝本机 OAuth 会话，无传统 API Key**（设备流登录：`dreamina login`／`--headless`＋`checklogin --device_code=`；`logout` 即清，换机须重登）。会话存储路径由 CLI 自管、不公开，无法也无需导出明文。
- **当前账号**：user_id 110198628111，vip=artisan，已登录。**余额 2026-09-15 实测 72 积分**（09-13 为 102，更早 38）。计费＝积分制（非按量人民币），生成前 `user_credit` 查余额。
- **命令**：text2image / image2image / image_upscale / text2video / image2video / frames2video / multiframe2video / multimodal2video（原 ref2video，Seedance 2.5 可自选模型）/ query_result / list_task / session；异步任务 gen_status=success 才算成。模型支持以各子命令 `-h` 为准。
- **与 ARK 通道别混**（见 [[reference-ark-account]]）：即梦 CLI 走 jimeng.jianying.com 积分制；火山方舟走 arkcli＋API Key＋EP 按量计费。
- **用户偏好（2026-09-12 确认）**：视频生成主通道走**火山方舟 API**（Seedream/Seedance），不用即梦 CLI。即梦仅作为备用通道（积分制，并发限制多）。
- **完整文档（含命令速查表与登录流程）在 `E:\密钥文件\即梦api.txt`**，并已登记进 `E:\密钥文件\密钥清单.md` 的"留在原位"表。

**image2image 用法与"生图免费"权益（2026-09-13 实测）**：

- 调用形状：`dreamina image2image --images a.png --images b.png --prompt "…" --resolution_type 2k --model_version 5.0 --ratio 16:9 --poll 180`
- **`--images` 可重复传多张（1–10 张）**→ 实现「灰模帧 + 角色锚点」这类多图参考；`--resolution_type` **必填**（4.0/4.1/4.5/4.6/4.7/5.0 支持 2k/4k，5.0Pro 支持 1.5k/2k/4k）；`--model_version` 默认 5.0；`--ratio` 默认 16:9；`--generate_num` 1–10。
- **⚠️ 计费口径已变（2026-09-15 实测，推翻上条）**：此前 artisan 权益 `image_basic_v5_2k` 生图 `credit_count = 0`（零成本）；**09-15 用 `--model_version 5.0Pro --ratio 9:16 --resolution_type 2k` 出一张古装立像 → `credit_count = 8`，余额 102→72**。→ **别再假设"即梦批量出图免费"**；跑批前先 `user_credit` 记基线、跑完对账，**批量前先试一张探单价**（不同 model_version/resolution 档位单价不同）。
- 实测可用组合（2026-09-15）：`dreamina image2image --images <画风锚> --prompt "<STYLE_ONLY 描述>" --model_version 5.0Pro --ratio 9:16 --resolution_type 2k --poll 150` → 返回 1440×2560 PNG，`gen_status: success`，`result_json.images[0].image_url` 需自行 curl 下载（URL 带签名与有效期）。
- **CLI 只回 URL、不落盘**：结果在 `result_json.images[0].image_url`（`p11/p26-dreamina-sign.byteimg.com`，带签名、有有效期），**必须自己 curl 下载**；`list_task` **不返回 URL**（只有宽度/高度），所以提交时的 stdout 要自己留存。
- **偶发瞬时错误**：`get_history_by_ids failed: ret=1015` 会打印出来但**任务其实已提交**（随后 `list_task` 查到 success）→ 先查 `list_task`/`query_result` 再决定是否重跑，别直接重发。多图输入首次调用撞过一次，单图正常。
- **没有负面词（negative prompt）参数**：`image2image/text2image` 只有 `--prompt`，**加不了 negative**——想排除的东西（画风、元素）只能靠正向句"不得…/非…"来表达。写提示词时别按 webui 习惯留负面词位置。
- **逐帧差异化提示词可行**：同一批图不同帧可以各带一条独立提示词（每张输入自己的灰模帧 + 可选锚点图），批量脚本按帧循环即可；22 张连跑无并发问题。
- 批量脚本：`无音_virtual_production\scripts\dreamina_ref_batch.py` / `dreamina_ref22.py`（灰模关键帧 → 成品静帧参考图，含重试与自动下载）。

**⚠️ 右下角强制水印 + 去水印方案（2026-09-15 实测，必读）**：

- **即梦每张出图都会在右下角烤一个半透明的圆角框「AI生成」水印**。这不只是难看——**当锚图挂 i2i 参考时，水印会被继承进后续所有派生图**；用在成片里更是直接穿帮。所以每张产出图都要顺手过一道去水印，别等拼片时才发现。
- 实测水印框位置（1440×2560）：约 `(1161,2423)-(1390,2508)`，即右边距 ~50px、底边距 ~52px、约 229×85。**位置相对固定**，可按比例定位。
- **去水印脚本**：`E:\创作\无音项目\工具\duimen\dewatermark.py`（OpenCV `inpaint` + TELEA）。
  用法：`py 工具/duimen/dewatermark.py <图1> <图2>` 或 `--dir <目录>`（原地覆盖，跑前先备份）。
  遮罩要**开足**（比实测框外扩一圈），否则圆角框的**右边框会残留一道弧**——第一版就是这样翻车的，从备份恢复后用 `MARGIN_R=0.028 / WM_W=0.181` 才干净。
- **`cv2.imread/imwrite` 读不了中文路径**（本项目路径全中文）→ 必须走字节流：`cv2.imdecode(np.fromfile(p, np.uint8), flags)` 读、`cv2.imencode(ext, img)[1].tofile(p)` 写。这个坑不加处理会静默失败（返回 None）。
- **单价与余额（2026-09-15）**：`--model_version 5.0Pro --ratio 9:16 --resolution_type 2k` ＝ **8 积分/张**；当日余额 **56**（72 的记忆已过时）。**跑批前先 `user_credit` 记基线**。
- **火山恢复后出图不要再走即梦**：火山（arkcli）按量计费、无积分上限，即梦是备用通道。2026-09-15 实测：火山恢复后出的图**不扣即梦积分**（余额停在 56 不动）。


## 2026-09-23 实测补记（即梦视频通道现实）
- **OAuth 会服务端失效但本地仍"已复用登录态"**：提交才报 `ret=10002 login fail`；`user_credit` 返回的是本地缓存（346 看着正常）。正解＝`dreamina relogin --headless` 打印 verification_uri/user_code/device_code（**约 11 分钟过期**）→ 用户点开 → `dreamina login checklogin --device_code=… --poll=540`（可后台挂着等）。
- **`image2video` 单价**：`seedance2.0` / 720p / 4s = **32 积分**；默认 `seedance2.0_vip`，**artisan 档 VIP 模型（seedance2.5 / 2.0_vip）不可用**。
- **免费队列是真瓶颈**：提交后 `queue_info` 给出 `queue_idx≈80109 / queue_length≈312480 / priority 2` → **几小时起步**，别按渲染时间估排期。要当天出片就走可灵/ARK。
- **并发＝1**：第二条提交直接 `ret=1310 ExceedConcurrencyLimit`，多镜必须串行。
- CLI 只回 URL 不落盘；`--poll N` 会被队列拖死。

## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- dreamina.exe（~/bin）无 API Key、本机 OAuth 会话（artisan）
- **⚠️ image2image 已按张扣积分（一张扣 8）**、支持 1–10 张输入图、模型到 5.0Pro
- **无负面词参数(只能正向加码)**
- 见 `E:\密钥文件\即梦api.txt`

## ★2026-09-28 实测：本机这把 CLI 的登录态失效了（要用得先 relogin）

- `query_result --submit_id=<id> --download_dir=<dir>` → 回 **`get_history_by_ids failed: ret=3018`**，`--download_dir` 一个文件都没落。
- `user_credit` → 返回 **`total_credit: 0 / user_id: 0 / vip_level: ""`**（这次连"本地缓存的假余额"都没了，与 09-23 那条"缓存还显示 346"不同）。
- 但 **`list_task` 照样能列出任务**（本地记录）：每条含 `submit_id` / `gen_task_type` / `gen_status` / `fail_reason`、`result_json.images[].{width,height}`、以及 `commerce_info.credit_count` 与 `benefit_type`（例：`image_basic_v50_pro_2k`）。**仍不回 URL**（印证 09-13 那条）⇒ 历史任务的产物拉不回来。
- **修法同 09-23**：`dreamina relogin --headless` → 用户点 verification_uri → `dreamina login checklogin --device_code=… --poll=540`。
- ⇒ **取回产物这条需求，2026-09-28 起首选 `dreamina-canvas` 的 `resource download`**（见 [[reference-dreamina-canvas-cli]]）：不依赖这把老 CLI 的登录态，还回 sha256、还支持视频。
