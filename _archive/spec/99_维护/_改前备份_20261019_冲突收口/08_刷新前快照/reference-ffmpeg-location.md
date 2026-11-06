---
name: ffmpeg-location
description: 本机 ffmpeg 位置及注意事项（旧版本，中文路径需 cd 到目录）
metadata:
  type: reference
---

**ffmpeg 位置**：`C:\Users\若水\AppData\Roaming\bilibili\ffmpeg\ffmpeg.exe`

**版本（2026-09-13 实测）**：**ffmpeg version 3.0.1**（libavcodec 57.x），很旧，缺不少新特性

**旧版能力边界（踩过的坑）**：
- `amix` **没有 `normalize` / `weights` 参数**（传了报 `Option not found`）——而且 amix 会**把每个输入各衰减 6 dB**，只能靠后级 `volume` 把音量补回来
- 混音可用的滤波器：`acompressor` / `alimiter` / `sidechaincompress` / `dynaudnorm` / `volume` **都在**（做配乐够用）
- `-ss` 放在 `-i` **前面**才是输入裁剪（配 BGM 时用 `-ss 20 -t 27.2 -i bgm.mp3` 取曲中段）
- 命令里**别出现 `//`**（含 `sed 's/.*x: //'` 这类会把工具误判成 UNC 路径而拒执行）

**配乐混音链范例**（2026-09-13 两镜连看配乐实测）：
```bash
ffmpeg -i video.mp4 -ss 20 -t 27.2 -i bgm.mp3 -filter_complex \
"[0:a]acompressor=threshold=0.1:ratio=3:attack=10:release=300:makeup=3[o];\
[1:a]volume=0.30,afade=t=in:st=0:d=1.5,afade=t=out:st=24.5:d=2.7[b];\
[o][b]amix=inputs=2:duration=first[m];[m]alimiter=limit=0.89[out]" \
-map 0:v -map "[out]" -c:v copy -c:a aac -b:a 192k out.mp4
```
原则见 [[feedback-bgm-mixing]]。

**注意事项**：
- 中文路径下直接指定输入文件会失败（`No such file or directory`）
- **解决方法**：先 `cd` 到帧序列所在目录，再用相对路径 `frame_%04d.png`
- 拼接命令示例：
  ```bash
  cd "renders/EP01_shot1" && "/c/Users/若水/AppData/Roaming/bilibili/ffmpeg/ffmpeg.exe" -y -framerate 24 -i "frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "../output.mp4"
  ```

**Why:** 用户已有 bilibili 附带的 ffmpeg，无需额外安装。但旧版本对中文路径支持差，需要 cd 到目录再用相对路径。

**How to apply:** 视频拼接时先 cd 到帧目录，用相对路径引用帧序列，输出到上级目录。

---

**另一把更好用的 ffmpeg（2026-09-15 剪第01集实测）：`D:\AIWorkflow\tools\ffmpeg.exe`**
- **比 bilibili 那把新得多，滤波器齐**：`scdet`（场景切点检测）/ `select` / `mestimate` / `vidstabdetect`+`vidstabtransform` / `signalstats` / `deshake` 都在。**做切点分析、拉片段、拼片一律用这把。**
- **⚠️ 本机没有 `ffprobe`**（两处目录都只有 ffmpeg.exe，PATH 里也没有）。**探测时长/分辨率要用 `python_embeded` 的 cv2**：
  ★**2026-10-02 按盘上更正：这句已过期。** `D:\AIWorkflow\LivePortrait-main\bin\ffprobe.exe` **存在且可用**（80,991,232 字节，ffprobe 6.0-essentials，`-version` 实测跑通），
  引擎早就在用（`config.media_tools.ffprobe` → `tasks.py:867-872` 取路径、`probe_video` 走 `-show_streams -show_format -of json`）；
  `D:\AIWorkflow\tools\` 里确实只有 ffmpeg（7.1-essentials），**PATH 里两个都没有**这半句仍成立。
  cv2 探法不算错，但**别再写"本机没有 ffprobe"**；另注意"探(6.0)／编(7.1)是两个大版本、分住两个目录"这件事本身是个待裁风险。
  ```python
  c=cv2.VideoCapture(f); fps=c.get(cv2.CAP_PROP_FPS); n=c.get(cv2.CAP_PROP_FRAME_COUNT)
  w=int(c.get(cv2.CAP_PROP_FRAME_WIDTH)); h=int(c.get(cv2.CAP_PROP_FRAME_HEIGHT)); dur=n/fps
  ```
  或用 `ffmpeg -hide_banner -i f 2>&1 | grep -E "Duration|Stream"` 读 stderr。

**drawtext 打中文的两个坑（2026-09-15 连踩，已解）**
1. **中文经命令行传给 ffmpeg 会被按系统编码 mangle**（变成乱码笔画）→ **中文一律写进 UTF-8 文本文件，用 `textfile=card.txt`**，不要用 `text='中文'`。
2. **字体路径里的 `:` 是滤镜选项分隔符**，`fontfile=C:/Windows/...` 和转义 `C\:/Windows/...` 都试失败过 → **最稳的解法＝把字体复制到工作目录，用相对名 `fontfile=font.ttf`**（配 `subprocess(cwd=TMP)`，中文文本文件也放同目录）。可用字体：`C:\Windows\Fonts\simhei.ttf`（简单 TTF）、`msyh.ttc`（雅黑，是 collection 可能有 index 问题）。
   - 段内计时器：`drawtext=...:text='%{eif\:t\:d}s'`（单个数字，无中文，可走命令行）。
   - **⚠️ `arial.ttf` 没有中文字形**（2026-09-23 A/B 对照标签实测）：中文全变豆腐块。打中文标签用 `fontfile=../msyh.ttc`＋`textfile=`（相对路径），渲染正常。
   - **⚠️ image2 输出多帧到同一文件名报错**（"Cannot write more than one file with the same name"）：单图加 `-update 1 -frames:v 1`，或干脆输出 mp4。

**字幕烧进画面（subtitles 滤镜，2026-09-23 全片验证可用）**
`-vf "subtitles=subs.srt:fontsdir=.:force_style='FontName=Microsoft YaHei,FontSize=15,Bold=1,PrimaryColour=&H00F0F0F0,OutlineColour=&H64000000,BorderStyle=1,Outline=1,Spacing=3,MarginV=46'"`——srt 与 msyh.ttc 复制到 cwd 用相对名，中文场景卡直接烧，无需逐条 drawtext。**教训：旁挂 .srt 不算"有字幕"，用户网页播放器不加载它**——审片版就要烧进去，别等交付才发现全片"无字幕"。

**concat 拼片后帧率会漂 → 必须归一化**
- 用 `-f concat -c copy` 拼完，`-hide_banner -i` 显示 **avg fps 漂到 23.88**（各段时间戳累计误差，比标称少约 20 帧）。
- **解法：最终 concat 改成一次编码** 【10-03 已裁：本行是**旧写法记录**，现役标准＝代码 "-crf 18 / -ar 48000 / 刻意不挂 fps"（挂 fps 会 124→123 掉帧）。引用编码参数一律以 `engine/tasks.py` 为准，不要按本行改代码。】，加 `-vf fps=24,setsar=1 -c:v libx264 -crf 16 -r 24 -c:a aac -ar 44100 -ac 2`。分镜级中间件也统一按 `scale=W:H:force_original_aspect_ratio=decrease,pad=...,setsar=1,fps=24` 生成，保证 concat 输入同规格。
- 若某镜**无音轨**，concat 前要补 `anullsrc` 静音轨（否则 concat 段间音画不同步）。
- 用同规格分段 + count 数校验总长（cv2 读回 frames/fps 对账），别只看容器 Duration。

**⚠️ 合轨加 `-shortest` 会在音视频等长时丢视频尾包（2026-09-28 踩）**
- 音频已按各段强制对齐到与视频等长时，`-i base.mp4 -i a.wav -c:v copy -c:a aac -shortest out.mp4` 会把视频尾部**整个包丢掉**——实测 **110 帧 → 106 帧**（结尾少 0.17s），而**容器 Duration 仍报 110 帧的长度**，光看 Duration 完全看不出来。
- **查法**：`ffmpeg -i f -map 0:v -f rawvideo -pix_fmt yuv420p - | wc -c` 再除以单帧字节（WxHx1.5），比 cv2 的 `CAP_PROP_FRAME_COUNT`（本例也报错数）和 Duration 都可靠。
- **解法**：音轨既然已等长，**直接去掉 `-shortest`**（去掉后 110 帧完好）。不放心就改成 `-t <视频时长>`。

**居中裁 16:9：别用表达式，先探尺寸算死数（2026-09-26 连踩两口）**
- `crop=ih*16/9:ih` 只对**比 16:9 更宽**的素材成立。喂 1344×768（1.750，比 16:9 的 1.778 还窄）时它算出宽 1365 > 1344，ffmpeg 直接报错。窄向素材要反过来裁高：`h = iw*9/16`。
- 想用 `crop=w='min(iw,ih*16/9)'...` 一次通吃？**逗号会被 ffmpeg 的滤镜图解析器当成"链式下一个滤镜"的分隔符**，报 `No such filter: 'ih*16/9)/2)*2:trunc(min(ih'`（转义冒号救不了逗号）。
- 稳法：`ffmpeg -i` 抓 `Video: ... WxH` → 按 `if w*9 > h*16` 判裁宽还是裁高 → 拼 `crop=TW:TH:X:Y` 死数（TW/TH 取偶，yuv420p 要求）。顺带把"有无 Audio"用同一次 `-i` 一起解析出来，少起一个进程。

---

**本机 OpenCV 写中文路径会「静默失败」（2026-09-16 踩，白跑一轮）**
- `cv2.imwrite("E:\\创作\\...\\图.png", img)` 在含中文的路径下 **返回 `False` 且一个文件都不写**——脚本若不检查返回值就会以为写成功了（我就是在 `os.listdir` 里才发现目录是空的）。
- **读写的唯一稳组合**：

```python
im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)  # 读
cv2.imencode(".png", im)[1].tofile(path)                                # 写
```
- **`cv2.VideoCapture` 同样怕中文路径，而且症状是"能打开、读不出帧"**（`isOpened()` 可能仍 True、`CAP_PROP_FRAME_COUNT` 有值，但 `read()` 全返回 False）→ 下游 `np.hstack([])` 报 `need at least one array to concatenate`，看着像代码 bug。2026-09-26 在 H3 产物（`E:\图像影音资源池\…`）上踩到。**最省事的解法：先 `cp` 到纯 ASCII 路径再读**，别去修调用方。
- **渲染占满内存时，Python 端 numpy 会 `OpenBLAS error: Memory allocation still failed after 10 retries`**——连几 MB 的小脚本都起不来，误以为进程崩了。解法＝**给子进程钉死 BLAS 线程**：`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`（OpenBLAS 按核数预分配栈缓冲，32 核就是几个 GB，正是它先炸）。凡是"渲染期间还要跑点算术"的脚本都该带上这两个变量。

- 同理 `cv2.VideoCapture(中文路径)` 也不可靠——**中文路径下所有 I/O 都走 numpy 字节中转**。

**⚠️ `cv2.imwrite` 写中文名＝静默产出"乱码名"文件（症状与上一条不同，2026-09-28 又踩）**
- `cv2.imwrite("trial/K02_试跑_抽帧.jpg", img)` **不报错、也可能返回 True**，但落盘的文件名是按 GBK 误解出来的乱码（`K02_璇曡窇_鎶藉抚.jpg`）⇒ 之后按原名找不到文件、清单里多一个看不懂的垃圾。
- 正解：**存图一律 `cv2.imencode('.jpg', img)[1].tofile(path)`**（`PIL.Image.save` 无此问题）；对照图文件名用 ASCII 更省事。
- **顺带一条清理纪律**：同一张图经 `imwrite` 与 `imencode` 两条路径出来的 JPEG **不是逐字节相同**（实测 331,034 B / `956061240f8210c1` vs 329,794 B / `7eb06daba5ad8742`）⇒ 清掉自己造出来的乱码名副本时**别指望哈希相等**，按来源判定即可（那是我自己刚造的 byproduct，不是用户的源）。

---

**Python 脚本命名坑（2026-09-18 白跑一轮）**
脚本文件**别叫 `inspect.py`**（同理 `json.py` / `os.py` / `types.py` 等）：它会遮蔽标准库同名模块，而 numpy 启动时就要 `import inspect` → 拿到的是你这个脚本 → 循环导入，报 `partially initialized module 'cv2' has no attribute 'VideoCapture'`，**错误信息完全不指向真因**。改名即好。

**本机 `py -3.12` 的 cv2 是 5.0.0，Haar 级联不可用（2026-09-18）**
`cv2.data.haarcascades` 指向的 `site-packages/cv2/data/` 里**没有** `haarcascade_frontalface_default.xml` → `CascadeClassifier` 建出来是空的，`detectMultiScale` 抛 `!empty()`。**要量脸改用 `cv2.FaceDetectorYN`（YuNet）**，见 [[feedback-character-reference-image]]。

**scdet 数镜头切点（2026-09-18 好用）**
`ffmpeg -i x.mp4 -vf "scdet=threshold=8" -f null -` → 读 stderr 里的 `lavfi.scd.time`。一条 30s 竖屏短片一次切出 5 个切点＝6 段（每段 4.2–5.8s），正好用来做"逐段复刻"的切分依据。

**⚠️ `blend=all_mode=screen` 默认在 YUV 上做 → 整幅偏品红（2026-09-21 踩）**
把黑底发光层 screen 叠到画面上时，blend 会对 **U/V 色度平面也做 screen**（128 为中心 → 结果 ≈192），整幅色相被推走、波形/字幕反而看不出问题。**必须先转 RGB 再 blend**：
```
[0:v]format=gbrp[a];[1:v]format=gbrp[b];[a][b]blend=all_mode=screen,format=yuv420p[v]
```
同理适用于 `multiply` / `addition` / `screen` 任何模式。做法与"音乐反应波形层"整条管线见 [[audio-visualizer-waveform]]。

**自动定位裁切框，别目测叠了网格的图（2026-09-18 连读错两次坐标）**
给人物/主体定裁切框时，我照"叠了 100px 网格"的预览图读数，两次都裁错（一次裁到黑底、一次只裁到头发）。**正解＝程序化找内容块**：
```python
mask = (cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > 45).astype(np.uint8) * 255
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, 8)   # stats[i] = x,y,w,h,area
```
取面积／最高那块当主体包围盒，再打印"非黑像素占比"自检（>40% 才算裁到内容）。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- bilibili 旧版 3.0.1 缺特性 + **更好用的 `D:\AIWorkflow\tools\ffmpeg.exe`(带 scdet/mestimate/vidstab，切点分析与拼片用这把)**
- **无 ffprobe→探时长用 cv2**
- **drawtext 中文必走 `textfile=`、字体复制到 cwd 用相对名(arial 无中文字形→用 msyh.ttc)**
- **字幕烧画面＝subtitles+fontsdir+force_style YaHei 已验证
- 旁挂 srt 网页播放器不加载＝不算有字幕**
- **concat -c copy 后 fps 会漂→最终拼片加 `-vf fps=24`** 【10-03 已裁：本行是**旧写法记录**，现役标准＝代码 "-crf 18 / -ar 48000 / 刻意不挂 fps"（挂 fps 会 124→123 掉帧）。引用编码参数一律以 `engine/tasks.py` 为准，不要按本行改代码。】
- 中文路径需 cd 用相对路径
- **cv2 读写中文路径走 numpy 字节中转**
- **脚本别叫 `inspect.py`(遮蔽标准库→numpy/cv2 循环导入)**
- **cv2 5.0 无 haarcascade→量脸用 FaceDetectorYN**
- **定裁切框用亮度阈值+connectedComponentsWithStats，别目测叠网格的图**

## 2026-09-30 补：ffmpeg 滤镜里的路径与中文（四路并排片踩的）

- `drawtext=textfile=…:fontfile=C:/Windows/Fonts/msyh.ttc` **在滤镜串里裸写 Windows 路径＝`Invalid argument`**：滤镜用 `:` 分选项，路径里的冒号必须转义（`C\:/…`）或整值加引号；**改走 `-filter_complex_script 文件` 也躲不掉**（解析规则相同）。
- **中文路径更脆**：把输入/标签/滤镜脚本全放 ASCII 目录（`C:\Temp\…`；跨盘 `os.link` 会 `WinError 17` → 退回 `copy2`），产物先在 ASCII 目录生成再 `shutil.move` 回中文目录。
- **最省事＝不在片上烧字**：标签交给 PIL 接触表（`msyh.ttc` 直接画中文），视频只做 `scale=300:-2,setsar=1` ＋ `hstack=inputs=4`；**`setsar=1` 必须带**，否则 hstack 因 SAR 不一致拒接。

## 2026-09-30 补：分段编码 + concat 的坑，和"成片必须按帧号验收"

- **`concat -c copy` 拼出来的文件时间戳是坏的**：实测解码序第 470 帧的 pts 跑到 38.7 s（各段自带时基不统一）。
  后果＝播放器/抖音重编码可能错帧，而且**任何按秒取帧的自检都会给出错位置的图**（cv2 按帧号 seek、`ffmpeg -ss` 都被骗过两次）。
- **`-fps_mode cfr` 补救会多插一帧**（边界 1039→1040），**滤镜链头挂 `fps=24` 会吃掉最后一条输入的一帧**（静帧卡 216→215、正片 362→361）。
  ⇒ 正解：**别分段再拼**，五段放同一个 `-filter_complex` 里用 `concat=n=..:v=1:a=1`，时间戳由 ffmpeg 现生成；本来就是 24fps 的素材**不要再上 `fps` 滤镜**。
- **验收成片不许用"我记得我拼对了"**：① 整片缩到 54×96 **顺序解码**（唯一可信帧序）拿逐帧签名；② 卡片帧对 PNG 原图、正片帧对源片同偏移帧比签名；③ 四个切点必须"边界大差＋段内小差"；④ 按帧号抽图时文件名 PTS 必须＝帧号×512（时基 1/12288）＝恒定帧率。任何一条不符直接 `sys.exit`。
  静帧卡各帧一模一样 ⇒ 定位起点时误差曲线是平的，**平局必须取最早候选**，否则会挑到"看着也对"的错位置。
