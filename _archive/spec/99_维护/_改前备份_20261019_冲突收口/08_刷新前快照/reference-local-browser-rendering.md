---
name: reference-local-browser-rendering
description: 本机把 HTML 渲成 PNG／在浏览器里跑 UI 回归的正路——headless Edge 参数坑、内置 browser-use 无表面（0×0 不能截图/点击只能 evaluate_script）、后台标签页掐掉 rAF 与定时器，以及"对比图必须先机械互差核验"
metadata:
  type: reference
---

2026-10-04 做审片站画布（视觉三版对比＋A/B 手感规模回归）时把这几条踩通了，以后凡是
**"要真渲染出图给用户看"** 或 **"要在浏览器里断言 UI 行为"** 的活儿直接照此走。

## 一、要 PNG 就用 headless Edge（本机唯一可用 Chromium CLI）

- 二进制：`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`（本机**没有** Chrome；Edge 够用）。
- **必须** `--headless`（旧值）＋ **`--user-data-dir=<独立空目录>`**。
  🔴 `--headless=new` ＋复用现有 profile 时**静默不出图**（命令返回 0、没有 PNG 文件、也没有报错），
  因为已有浏览器实例占着 profile。
- 正解形态：`msedge --headless --disable-gpu --hide-scrollbars --user-data-dir="…\_edgeprofile"
  --force-device-scale-factor=1 --window-size=1440,740 --screenshot="<绝对 Windows 路径>.png" "<url>"`。
- 成功判据看 stderr 里那行 `NNNNNN bytes written to file …`，不要只看退出码。
- 截图前先让页面**自包含**：内联 CSS、图片用相对路径由本地 http 服务供（或直接 base64 内嵌）；
  `file://` 页去 fetch `http://127.0.0.1` 资源是通的。用完**删掉临时 profile 目录与临时页**。

## 二、内置 browser-use（MCP）在这台机器上的真实边界

- 它的页面对象是**隐藏**的：`take_screenshot`／`click`／`drag` 会报
  `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE … viewport=… visible=false attached=false`。
  ⇒ **只能用 `navigate_page` + `take_snapshot` + `evaluate_script`**（后者完全可用，且 dispatch 合成事件能触发页面自己的监听器）。
- `evaluate_script` 有个 `filePath` 参数：**大返回值（CSS/DOM dump）直接落盘**，别让它进对话上下文。
- 参数校验很死：`fill`/`click` **只认 `uid`**，多传 `elementDescription` 之类直接报
  `params must NOT have additional properties`；`uid` 必须来自最近一次 `take_snapshot`。
- 🔴 **隔离世界**：`evaluate_script` 跑在 isolated world，**看不见页面里的 `const`/`let` 顶层变量**
  （`ReferenceError: API is not defined`），但 **DOM、localStorage、fetch、派发的事件都是同一份**。
  ⇒ 驱动办法：把口令填进 `#pw`、`dispatchEvent(new MouseEvent('click'))` 点页面自己的登录按钮；
  读状态用 `getComputedStyle(...)` / DOM 文本，而不是引用页面变量。
- 键盘/指针断言要用**真 DOM 事件**派发（`PointerEvent` 带 `pointerType:'touch'` 才能测捏合），
  并且**别在页面函数里假设 target 有 `.matches()`**——`window`/`document` 派发时 target 没有该方法（这是当天修掉的一个真 bug）。

## 三、🔴 后台标签页把 rAF 和定时器都掐了——空结果不等于"没掉帧"

在这台机器上（无论内置 browser-use 的隐藏页，还是被切走的标签）：
- `requestAnimationFrame` **不触发** ⇒ 基于 rAF 的帧间隔采样返回 `frames:0`、依赖 rAF 的代码看起来"没生效"；
- `setTimeout/setInterval` 被节流到秒级 ⇒ 任何"轮询等待"循环会撞穿工具超时（15 s）；
- 结论：**帧率/耗时类指标不能用隐藏页量**。换前台浏览器、或用 `PerformanceObserver(['longtask'])`、
  或干脆只断言**状态与内容**（能过），并把"这条没拿到复测数字"明文写出来。
- 同源教训：**`await wait(700)` 之后再读一次，得到的 716ms 是我的等待窗口，不是操作耗时**（见 [[feedback-evidence-loop-trap]]）。

## 四、给别人看的"对比图"必须先自证不是一张图

- 当天差点交了假对比：以为取的是"旧版／新版"两份 DOM dump，其实**两次都从同一个页面取**，
  拼出来的前后图**逐像素均差 0.00**、字节数一模一样。是那个 0 把我拦住的。
  ⇒ 规矩：出任何"前后／多版"对比图前，跑一遍 `ImageChops.difference(...).getdata()` 均值断言（阈值给死，比如 >4），
  再对拼好的整图**逐格子**量亮度标准差与灰阶数（证明没有空格子），最后才发。
- 取向类判断的素材要用**他自己的真帧**（`E:\创作\仙戮双生\frames\*.jpg` 这类），不是色块；
  三版共用同一份数据，只差 CSS——这样他报号才是在比取向而不是比内容。
- PIL 标签**必须显式 `ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", N, index=…)`**（同 [[reference-feishu-communication]]），
  且**判据写成形态而不是计数**（前面用例已经消耗过计数器时，"第 15 次"会飘）。
- 成品图放 `E:\创作\_待审文档\`（他在审的目录），链接按 [[feedback-file-link-format]] 用尖括号＋正斜杠。

相关：[[reference-user-browser-shopping]]（要真·前台/登录态时用他的浏览器）、[[reference-qoder-agent-skill-hooks]]、
[[feedback-i-am-not-the-beauty-judge]]（我不判好看，只出编号对比让他报号）。
