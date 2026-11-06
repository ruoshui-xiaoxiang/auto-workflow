---
name: reference-pixabay-assets
description: Pixabay 音效/音乐素材直链抓取法——WebFetch 403 须走内置浏览器；搜索页提结果、详情页 JSON-LD script 直接含 cdn download 直链（evaluate_script 提取，无需点击）再 curl
metadata:
  type: reference
---

Pixabay 音效/音乐素材抓取（2026-09-07《无音》找 China street 音效验证）：

- **WebFetch/curl 直抓 403（Cloudflare）**，必须走 Qoder 内置浏览器（browser-use MCP）。
- **搜索页**：`https://pixabay.com/sound-effects/search/<关键词>%20<关键词>/`，evaluate_script 提取 `[...document.querySelectorAll('a[href^="/sound-effects/"]')]` 的 href+innerText 即结果列表（页面 JS 渲染，脚本里先 sleep ~4s）。
- **音乐同理（2026-09-13 复核）**：`https://pixabay.com/music/search/<关键词>%20<关键词>/`（如 `happy%20upbeat%20instrumental`），选择器换成 `a[href^="/music/"]` 并过滤掉 `/music/` 与 `/search/` 本身，一次能拿到 ~20 条结果；详情页提取直链的写法与音效完全一样，实测 3/3 命中。
- **详情页直链（2026-09-07 复核实锤：music 页 + 3 个音效页全命中）**：详情页 `<script type="application/ld+json">` 里直接含 `https://cdn.pixabay.com/download/audio/....mp3?filename=...`——evaluate_script 从 document.scripts 正则提取即可，**无需点播放/下载按钮、无需等懒加载**（搜索页才没有直链）。curl 下载带浏览器 UA + `-e https://pixabay.com/` referer 即成。
- **浏览器后台态坑**：viewport 隐藏时 click 报 NATIVE_BROWSER_VIEWPORT_UNAVAILABLE 不可用，但 evaluate_script / take_snapshot 仍可用——优先脚本提取，别把流程押在点击上。
- 时长在详情页以 `0:24` 形式的 span 文本出现（第一个非 0:00 的即本条时长）。
- 下载后用 ffmpeg 切段+lowpass/loudnorm 做试听候选（流程同《无音》音效试听）。

相关：[[reference-cn-download-mirrors]]（下载代理与镜像）
