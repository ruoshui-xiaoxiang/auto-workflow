---
name: reference-wuwang-screenshot-path
description: 鸣潮 PC 版拍照模式存图位置与发飞书的大图处理法（D:\DGames 安装，PNG 单张 13MB 超飞书图上限）
metadata:
  type: reference
---

鸣潮（Wuthering Waves）装在 `D:\DGames\Wuthering Waves`，游戏内拍照模式的照片存：
`D:\DGames\Wuthering Waves\Wuthering Waves Game\Client\Saved\ScreenShot\`，文件名 `YYYYMMDDHHMMSS.png`，每张约 13 MB（原生分辨率 PNG）。Windows 截屏文件夹（Videos\Captures、Pictures\Screenshots）里没有游戏照片。

发飞书的处理（2026-10-01 实测 5 张送达）：飞书 message 图片有大小上限，13 MB PNG 传不动——用 `D:\AIWorkflow\tools\ffmpeg.exe -q:v 2` 就地转 JPEG（2.0–2.3 MB、分辨率不降），再走 [[reference-feishu-communication]] 的两步传图法。用户说"帮我找游戏截图发飞书"时按这条路径处理。
