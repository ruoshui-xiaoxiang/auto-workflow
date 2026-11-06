---
name: reference-feishu-communication
description: 飞书 bot 通信：发送侧实测可靠（文本/图两段式/视频须封面/媒体不能带文字，30MB 上限）；★审片三件套顺序＝文本结论→逐镜拼图→成片，中转 JSON 写 cwd（/tmp 对 Windows python 不可见），PIL 标签必须显式 msyh.ttc 否则汉字全变方块；**接收侧 2026-09-20 复核未证实——事件 scope 只有 p2p、群历史读被拒 230027、两轮监听 0 事件**；lark-cli.exe 完整路径；探测手法与替代方案
metadata:
  type: reference
---

用户通过**飞书（Feishu/Lark）**实现双向通信。App ID：`cli_aa11b4d639b8dcc1`。

> **2026-09-09：Qoder 市场 lark 插件已按用户要求卸载**（连同 dingtalk、hugging-face 一起）。lark:* 技能从 Qoder 会话消失，但 lark-cli.exe 本体（`.local\share\qoder\lark-cli\...`）与 feishu_relay.py 不受影响，飞书通道仍在。需要 lark:* 技能时从 Qoder 市场重装插件即可。备份在 `C:\Users\若水\.qoder\tmp\uninstalled_plugins_backup_20260909\`。

## 发送消息（已验证可用，2026-09-05 实测送达）

bot 身份在群聊 `oc_4f43e84db8b16403e036eb54d57bf49f`（群名"吕湘"，owner `ou_bc3e6dad84991f971f6594b3f91ad63c`）中发送。用户已确认该群即其本人接收通道。

```
lark-cli im +messages-send --chat-id oc_4f43e84db8b16403e036eb54d57bf49f --as bot --text "<内容>" --format json
```

成功判据：返回 JSON 的 `ok == true`，**不要**用 `code == 0` 判断。

`--image` 支持 URL、image key (img_xxx)、cwd 相对路径（**不支持绝对路径**）。**2026-09-12 实测：`--image <本地相对路径>` 的自动上传会报 code 2200 Internal Error**，改用两步走（**须 `--as bot`**，先 cd 到图所在目录）：`lark-cli im images create --data '{"image_type":"message"}' --file "image=<文件名>" --as bot --format json` 拿 `image_key`（形如 `img_v3_xxx`），再 `im +messages-send --chat-id <群> --as bot --image img_v3_xxx`（9 张 PNG 全部 ok:true）。**⚠️ 解析返回 JSON 注意（2026-10-01 踩坑）：lark-cli 输出是带缩进/空格的 pretty JSON（`"image_key": "img_..."`，冒号后有空格），`grep -o '"key":"...'` 无空格模式会全部失配、表现为静默"上传失败"。**

`--video` 已验证可用（2026-09-06，0.9MB mp4 实发成功；2026-09-07 复验 15-19MB mp4 正常）：**必须搭配 `--video-cover`**（封面图，key/URL/cwd 相对路径均可）；video 与 cover 都只认 cwd 相对路径，先 cd 到文件所在目录再发。**视频硬上限 30MB**（2026-09-07 实测 86.7MB 被拒 code 234006 "The file size exceed the max value"），超限先转码（如 720p/720k+96k AAC ≈ 26MB）。文件消息（`--file`）与音频（`--audio`，需 Opus）同走此模式。

**媒体消息不能带文字**（2026-09-07 实测）：`--image/--file/--video/--audio` 与 `--text/--markdown/--content` 互斥，同发报 validation "cannot be used with"；配文要另发一条纯文本消息。

**让用户"挑图"＝对比图 + 报号（2026-09-13 实测好用）**：要用户从多张候选里选时，**把候选 ffmpeg 拼成一张带区块编号的对比图**（如 3×2），发一条图 + 一段"左上=1 中上=2 …"的说明，用户报号即可——比逐张发省事得多。老版本 ffmpeg 拼图用 `scale=W:H,setsar=1` 强定尺寸（`pad` 会 "Failed to configure input pad"）。也可以连续发多条媒体（图/视频各带封面）再补一条纯文本说明。

**⚠️ 用 Git Bash 调 lark-cli 发文本的两条坑（2026-09-14 实测踩到）**：① `--text "…"` 里**不能出现反引号**——bash 会先做命令替换，把那段当命令跑掉（终端报 `xxx: command not found`），发出去的文本缺一块；要写代码/通道名就去掉反引号或改用单引号包外层。② 文本里**不能出现连续两个反斜杠**（Windows 路径 `E:\\a\\b`）——工具直接拒绝执行并报 `Command contains a UNC path that is not allowed`；路径一律写**正斜杠**（`E:/a/b`）或用中文表述。两条都踩过后只能补发一条干净说明才送达。

## Drive 云盘通道（>30MB 大文件的正解，2026-09-23 探到边界、未开通）

聊天视频硬上限 30MB，大文件（如 96MB 成片）审片通道＝飞书云盘：`lark-cli drive +upload --as bot --file ./x.mp4 --name 显示名`（>20MB 自动分片；bot 对新传文件自动 full_access）。**两条实测边界**：① `--file` **只认 cwd 内相对路径**，绝对路径报 `unsafe file path`——先 cp 进工作目录；② **应用当前没申请 drive scope**，实传被拒 code 99991672，缺 `drive:drive / drive:file / drive:file:upload`。开通＝账户侧动作：直达链接 `https://open.feishu.cn/page/scope-apply?clientID=<app>&scopes=...`（报错 JSON 里自带 console_url），**且很可能还要"发布新版本"才生效（同事件权限那个坑）**。2026-09-23 用户在后台点开通时报错（具体报错未回），通道暂搁——再提大文件分发时先问一句 scope 开了没，别默认能传。

## 接收消息：**接收侧 2026-09-20 复核＝未证实可用，别再当现成通路**

⚠️ 本节下方原记「2026-09-06 验证可用」**已被推翻**（至少群消息这一路不成立）。

2026-09-20 两轮当场探测（`event consume im.message.receive_v1 --as bot`，窗口 150s 与 4m）：`feishu-websocket: connected` + `ready` 都正常，但**各收到 0 条事件**。同时查到的三条硬事实：

- `lark-cli event schema im.message.receive_v1` 声明的 required scope 是 **`im:message.p2p_msg:readonly`（私聊只读）**——所以**私聊才是主通路，群消息大概率根本推不过来**。
- 轮询兜底也被堵：`im +chat-messages-list --as bot --chat-id oc_4f43…` 返回 **code 230027 `user_unauthorized` / "access denied for this bot operation"**，即 bot 没有读群消息的权限。
- `im +chat-list --as bot` 返回 `ok:true` 但 **0 个群**。⚠️ 这条**不能**当"bot 不在群里"的证据（往该群发消息实测一直成功），只能说明缺列群权限。
- `event consume --dry-run` 的三项 preconditions（credentials / console_event_published / scopes_granted）全 ok —— **这只算"配置允许"，不是"消息会到"的证据**，别拿它当结论。

探测手法（复用）：`event list` / `event schema <key>` 看 required scopes；`event consume <key> --as bot --timeout 4m --max-events 2 > 文件 2> 日志` 后台起、让他发一条、再读文件。**`--quiet` 会隐藏事件丢失，探测时别加。**

**要群接收只能去开放平台后台**：加「读取群消息」类权限 + 事件订阅 `im.message.receive_v1` 并**发布一个新版本**——账户侧动作，交用户做，不要自己声称已通。

若只走私聊：机器人需先被他搜到并发起会话；回复要按事件里的 `chat_id` 回原处（`+messages-send --chat-id <事件带回的 chat_id>`），不要写死群号。事件文本里 `@机器人` 是 **`@_user_N` 占位符**，解析前必须正则剥掉。

老坑保留：event consumer 要求 stdin 保持打开，Python subprocess 需用 `os.pipe()` 维持写端，否则立即退出。本机 lark-cli 版本 1.0.87（有 1.0.96 可升）。

## lark-cli.exe 完整路径

Python subprocess 无法通过 PATH 找到 lark-cli（Git Bash shell 脚本），需用完整 Windows 路径：

```
C:\Users\若水\.local\share\qoder\lark-cli\node_modules\@larksuite\cli\bin\lark-cli.exe
```

## feishu_relay.py 远程指令中转

工作区 `feishu_relay.py`：飞书 bot 远程指令中转脚本。在飞书群发消息即可控制本机。

支持指令：`/help` `/ping` `/status` `/gpu` `/disk` `/comfy` `/img <提示词>` `/x <命令>`

启动：`python feishu_relay.py`（后台运行，日志写 `feishu_relay.log`）

**当前限制**：
- bot 身份 ready，**user 身份 `token_missing`（need_user_authorization）**，只能以应用身份发消息
- 缺少 `im:chat.members:read` 等 scope
- bot 身份无法枚举 p2p 单聊
- `/open-apis/authen/v1/user_info` 是 user-only 端点，bot 调用返回 404（不能用来测 bot 鉴权）

**pipeline.py 的 `send`/`send_sheets` 不可用（2026-09-12）**：它硬编码 `--as user` + `--user-id`，但 user 身份 token_missing；且 Python subprocess 找不到 `lark-cli`（需完整 .exe 路径）。实际发送绕开 pipeline，直接 bot 身份发群聊（上面两步传图法）。

**How to apply:** 通知用户用发送命令（发送侧实测可靠，图/视频/文字都行）；**接收侧默认不可用**——需要用户回话时，先当场双向验证，验不通就改成免终端的本地入口（桌面 .bat / 一键命令），不要基于"以前能收"设计流程。lark-cli 在 Python 中必须用完整 .exe 路径。发送消息属于对他人可见的操作，若目标不是已确认群须先确认。


## 索引细节迁回（2026-09-28 第二轮，原只在 MEMORY.md 目录行里）

- **发送侧可靠**：bot 发群文本/图（两段式 `im images create`→`--image img_v3_*`）/视频（须 `--video-cover`、30MB、媒体不能带 --text）
- **大文件正解＝`drive +upload` 云盘通道，缺 drive scope(99991672) 待用户后台开通(2026-09-23 报错暂搁)、--file 只认 cwd 相对路径**

## ★2026-10-01 补：发"视频＋图＋说明"三件套的实操细节（复刻片 H 审片，三条全 ok）

- **`/tmp` 对 Windows 侧 python 不可见**：`lark-cli ... > /tmp/x.json` 在 Git Bash 里写成功了，但紧接着用 `python.exe` 去 `open('/tmp/x.json')` 直接 `FileNotFoundError`。⇒ **中转 JSON 一律写到当前工作目录**（`_imgkey.json`），用完删。与 [[reference-ffmpeg-location]] 那族"ASCII／cwd"坑同源。
- **`--video-cover` 走 image_key 最稳**：先按图片那套两步式 `im images create` 拿 `img_v3_*`，再 `--video <相对名> --video-cover <key>`。实测 3.19 MB mp4 一次过。
- **审片三件套的顺序**：① 纯文本结论（先说成了什么、没成什么）② 逐镜 N 格拼图 ③ 成片。媒体不能带文字，所以说明必须独立一条；用户是在**手机上**看，所以"哪一帧该注意什么"要写进那条文本里，别指望他放大拼图。
- **拼图标签**：用 PIL 时**必须显式 `ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', N)`**；默认位图字体不含汉字，标签会整排渲染成方块（10-01 就这么翻过一次，图发出去了才发现）。
- 用户说"发飞书看看"＝他要**离开这台机器审片**，此时不要紧接着开新的长任务；把"等他回话"显式说出来。


## 🔴 发送侧不可回读 ⇒ 发送当次就要用 --jq 拿 message_id（10-01 踩到）

这台 bot 对目标群**只有发权限、没有读权限**，三条回读路全断：
- `im +chat-messages-list --as bot` → `230027 user_unauthorized`
- `api GET /open-apis/im/v1/messages?...` → `99992402 field validation failed`
- 任何 `--as user` → `token_missing`（本机 user 身份未登录）

⇒ **发完就查不到"到底进没进去"**。所以每次 `im +messages-send` 必须带
`--jq '{ok:.ok, id:.data.message_id, err:(.error.code//null)}'`，
**不要** `| tail -3`——成功与失败的 JSON 都以 `}` 收尾，截断后无法分辨（10-01 就是这么把一条长文本发出去后判不了，只能重发，可能在他群里留了重复）。
图片仍走"ASCII 中转文件名＋cwd 相对路径"，发完即 `rm` 清中转。
