---
name: reference-cn-download-mirrors
description: 本机国内网络下载与代理选型：HF 走 hf-mirror、GitHub 走 gh-proxy.com、PyPI 阿里源（缺包走官方+--proxy 7890）；YouTube 需代理+cookies、B站 412、不许改 torch
metadata:
  type: reference
---

本机实测（Clash 代理常被关、GitHub 直连超时）2026-09-06/07：

- **代理（2026-09-07 实测）**：Clash 端口 **7890**；git-bash 的 curl **不会自动吃系统代理**，必须 `-x http://127.0.0.1:7890`（yt-dlp/pip 用 `--proxy`）。逐端口探测法：对 7890/7897/10809/1080 跑 `curl -x http://127.0.0.1:$P -m 5 -o /dev/null -w "%{http_code}" https://www.youtube.com`，出 200 的就是代理口。
- **HuggingFace**：hf-mirror.com 直连 ~36MB/s，比走代理快（详见 [[localai-video-model-plan]] 下载通道教训）；faster-whisper 等模型下载设 `HF_ENDPOINT=https://hf-mirror.com`。**坑（2026-09-07）**：①后台/子 shell 的 python 里 HF_ENDPOINT 可能不生效（请求仍打 huggingface.co）→ 稳妥做法是 curl 直拉 `https://hf-mirror.com/<org>/<repo>/resolve/main/<path>`；②文件路径必须先查 `/api/models/<org>/<repo>` 的 siblings 列表，猜错路径不报错而是得到 15 字节 "Entry not found" 文件；③仓库 id 拼错同样 401（如 F5-TTS 官方是 **SWivid**/F5-TTS 不是 SWivl）
- **GitHub releases/大文件**：直连 curl 超时；`https://gh-proxy.com/https://github.com/<repo>/releases/download/...` 成功（同批 ghfast.top 未出文件）；下完用 zipfile/字节数校验
- **GitHub LFS 跟踪的文件（2026-09-16 实测，下 opencv_zoo 的 .onnx 时踩到）**：这类文件走 **`raw.githubusercontent.com` 只会拿到 131 字节左右的 LFS 指针文本**——脚本不校验字节数就会当"下载成功"，实际内容只是 `version https://git-lfs.github.com/spec/v1` 几行；`gh-proxy.com` 代理 raw 路径返回 **403**。**正解＝走 LFS 媒体域名 `https://media.githubusercontent.com/media/<owner>/<repo>/main/<path>`**（本次 232KB 的 YuNet 模型一次拿到）。**判据：字节数只有一两百就是拿到了指针，不是拿到了文件。**
- **PyPI**：清华源对部分 wheel 下载返回 **403**（triton-windows 实测）；**阿里源 `https://mirrors.aliyun.com/pypi/simple/` 可用但缺包**——faster-whisper、f5-tts 均无（2026-09-07 实测）。有代理时直接官方 PyPI：`pip install X --proxy http://127.0.0.1:7890`
- **SageAttention Windows 轮子源**：woct0rdho/SageAttention releases，文件名含 `cuXXXtorchX.Y.Zandhigher`、abi3 跨 Python 版本；必须匹配目标解释器现有 torch 版本（如 ComfyUI 便携版 torch 2.13.0+cu130），**绝不为凑轮子升降级 torch/cuda**——装不上就放弃该项。装新包前先 `pip install --dry-run` 检查会不会动 torch（f5-tts dry-run 确认 torch already satisfied 才放行）
- **YouTube**：直连必挂；请用户开代理后可用，但 **2026-09-07 起无 cookie 下载报 bot-check**（"Sign in to confirm you're not a bot"）→ 需 `--cookies-from-browser`；**Edge 正在运行时 cookie DB 被锁无法提取**（Chrome/Firefox 本机未装）——要么请用户关浏览器重试，要么换源。**archive.org 直连超时（HTTP 000）不通**
- **B站**：直连/API 对 yt-dlp 返回 HTTP 412（加 UA/referer 都绕不过），别浪费时间；但 **Qoder 内置浏览器（browser-use MCP）里页面内 fetch 带 session 可用**（2026-09-07 验证搜索 API）：`fetch('https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=...', {credentials:'include'})`；playurl 拿音频流未走完，理论需 Referer: https://www.bilibili.com
- **yt-dlp**：2026-09-07 已装系统 Python312（`python -m yt_dlp`，Python 不在 git-bash PATH 需绝对路径 `/c/Users/若水/AppData/Local/Programs/Python/Python312/python.exe`）；另 ComfyUI 便携版里也有一份。下载的 dash 格式文件本身完好但用户默认播放器打不开 → ffmpeg `-pix_fmt yuv420p -movflags +faststart` 重转码即解决
- **yt-dlp 2026-09-15 复测（下参考素材用）**：**`py -m yt_dlp` 直接可用**（Python Launcher 3.14，版本 2026.08.19）——不用再拼 Python312 绝对路径；配 **`--proxy http://127.0.0.1:7890` 可直下 YouTube 且这次没触发 bot-check**（此前记的"必须 --cookies-from-browser"这次不成立），实测约 0.7MB/s、22MB 短片 28s 下完；合并音视频要 `--ffmpeg-location "D:/AIWorkflow/tools"`。**下游坑：YouTube 1080p 下下来多是 VP9 / AV1**，喂云端 Seedance 或本地 H3 前要转 H.264（`-c:v libx264 -crf 18 -pix_fmt yuv420p`）。另：**本机 Git Bash 没有 `bc`**，脚本里别用 bc 算时间。

**How to apply:** 下模型/轮子/仓库时直接按本表选镜像，不要先试直连浪费时间；代理是否开着不可假设，先按无代理直连镜像走；镜像缺包且代理可用时直接官方源；镜像全不可用时（YouTube 类）直接请用户临时开代理，比反复重试快。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- hf-mirror / gh-proxy.com / PyPI 阿里源（缺包走官方+代理 7890，git-bash curl 要 -x）
- **`py -m yt_dlp` 可用、配 --proxy 7890 下 YouTube 无需 cookies（2026-09-15 复测），下完多是 VP9/AV1 要转 H.264
- Git Bash 无 bc**

### 10-04 复用同一条坑＋找到的正路：取 GitHub **别 clone，按 tree 挑文件走 raw**

`git clone` 仍被上面那条 `ghproxy.cn` 的 insteadOf 打死（`info/refs not valid: is this a git repository`）；
**我没有动他的全局配置**（`git config --global` 一律不碰），改成：

- `api.github.com/repos/<o>/<r>` 取 `default_branch` → `git/trees/<ref>?recursive=1` 拿**全量 blob 清单（含 sha 与 size）** →
  逐个 `curl -fL https://raw.githubusercontent.com/<o>/<r>/<ref>/<path>`。实测**单文件约 0.5 秒、不需要代理**，
  完全不必先试镜像。
- **按 sha 去重**：一个仓库里同一份大文件常被拷进多处（十个 skill 各带一份 1.16MB 的 `chinese-color-harmony.md`，blob 同一个）⇒ 只落一份，省掉 90%。
- **别 clone 整仓**：`nevertoday/zhongguo-traditional-colors` 仓约 1 GB（逐色 html 751＋svg 742＋png 742＋jpg 742），
  真正要的数据只有 ~26 MB。**先量 tree 再决定取哪些路径。**
- **下完现算 git blob sha1 与 tree 的 sha 对账**（`sha1(b"blob %d\0"+data)`）：这才能证明"拿到了、且内容对"，
  顺带当场抓到 LFS 指针／截断（呼应上面"一两百字节＝拿到指针"那条）。0 字节的合法空文件会被"size>0"判成失败，另计。
- `--fail` 偶发一次取不到（当日 8 个假失败、重试全成）⇒ **每个文件重试 2–3 次再报失败**，别把网络抖动记成"仓库缺这个文件"。

### 10-01 git 全局配置里有一个死代理，会把所有 git clone 打死

`git config --global` 现存：`http.proxy = http://127.0.0.1:7890`、`https.proxy = http://127.0.0.1:7890`、`url.https://ghproxy.cn/https://github.com/.insteadOf = https://github.com/`、`http.sslverify false`。
实测 **127.0.0.1:7890 无人监听**（netstat 计数 0），curl 直连 github.com / gh-proxy.com 都 200 —— 所以"GitHub 拉不下来"是 git 自己的配置，不是网络。
- 单条命令绕过：`GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=http.proxy GIT_CONFIG_VALUE_0= GIT_CONFIG_KEY_1=https.proxy GIT_CONFIG_VALUE_1= <命令>`（env 级配置优先级最高，不动他的全局设置）。
- 绕过后仍会栽在 `ghproxy.cn` 那条 insteadOf 上：它回 `info/refs not valid: is this a git repository` —— **ghproxy.cn 不能做 git 智能协议镜像**，只配当下载加速。⇒ 要 git clone 必须连这条 rewrite 一起绕（直接抓 `https://gh-proxy.com/https://github.com/<owner>/<repo>/archive/refs/heads/main.tar.gz` 再自己解包最省事）。
- 清配置（`git config --global --unset http.proxy` 等）是改他机器上的设置，**先问再动**。
