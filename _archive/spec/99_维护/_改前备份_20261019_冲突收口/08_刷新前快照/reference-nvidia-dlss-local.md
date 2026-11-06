---
name: reference-nvidia-dlss-local
description: 本机 NVIDIA 套件事实与陷阱——Overlay/「使用 NVIDIA 账户登录」窗「关不掉」的根因与根治；「优化」≠「DLSS 覆盖」；DLSS 预设字母对照(A–F老 / J,K=DLSS4 / L,M=DLSS4.5)；DLSS 5 需游戏集成、非驱动覆盖(首发驱动 616.64)；燕云十六声本机带全套 DLSS、官方只到 DLSS 4；社区「一键包」=代理 DLL 注入器(反作弊风险)
metadata:
  type: reference
---

**本机 NVIDIA 现状（2026-09-14 实查）**：RTX **5060 Ti**，驱动 **616.92**；NVIDIA App 装着（`NVIDIA App` + `NVIDIA Overlay` + `nvcontainer` 三组常驻合计 **~1.4GB**，是除 Qoder 外最大的一块内存占用）。

## 三个「关不掉」的坑（都实测过）

| 现象 | 根因 | 正解 |
|---|---|---|
| 覆盖层窗（标题 **"NVIDIA GeForce Overlay DT"**）点 ✕、任务管理器"结束任务"都没用 | 它是**覆盖层**窗口不是普通窗；且被 **nvcontainer 监督** → `taskkill` 后**立刻重生**（实测 pid 5140 杀掉 → 冒出 7852） | **Alt+Z** 切换收起（它是 toggle）；根治＝NVIDIA App → 设置 → 功能 → **覆盖层** → 关掉「游戏内覆盖层」（关后 NVIDIA Overlay 整组 ~489MB 不再跑） |
| **「使用 NVIDIA 账户登录」**窗关不掉 | 它是 **`NVIDIA App.exe` 本体**的主窗口（处于"请登录"态），跟 App 进程绑着，点 ✕ 无效 | **退掉 NVIDIA App 整组**（6 进程 ~752MB）窗口即消失（`Stop-Process -Name 'NVIDIA App'`） |
| 任务管理器「启动应用」里找不到 NVIDIA App，但每次开机仍弹登录 | App 的拉起**不在注册表 Run / 启动文件夹**，而在**计划任务 `NVIDIA App SelfUpdate_{B2FE1952-0186-46C3-BAEC-A80AA35AC5B8}`**（定时拉起 App 查更新，App 一起来就弹登录） | 禁用该计划任务可止住（代价：不再自动更新驱动/App）；或登录一次 NVIDIA 账号；或直接卸载 NVIDIA App（**驱动与显示功能在 nvcontainer/显示服务里，不受影响**） |

## 「优化」≠「DLSS 覆盖」（关键区分，别被提示误导）

NVIDIA App 对每个游戏有**两块独立**功能：

- **「优化」(Optimal Settings)**：自动调游戏内画质选项；**只对 NVIDIA 官方名单里的游戏开放** → 提示"**程序不支持优化**"说的是这一块。
- **「DLSS 覆盖」(DLSS Override)**：**驱动级**强制 DLSS 模型/预设（超分辨率 / 帧生成 / 光线重建 各一个「模型预设」下拉）；**不改游戏目录任何文件**。

所以看到"不支持优化"≠ DLSS 覆盖不能用 —— 要往下翻找独立的「DLSS 覆盖」区块。

## DLSS 预设字母对照（用户 App 下拉里能看到到 **M**）

| 预设 | 对应 | 说明 |
|---|---|---|
| A ~ F | DLSS 2 / 3 时代的 **CNN** 预设 | **比游戏自带的还老，别选** |
| G / H / I | **空号** | NVIDIA 没用过这几个字母 |
| **J、K** | **DLSS 4**（transformer） | 已被 4.5 超越 |
| **L、M** | **DLSS 4.5**（2026-01 上线） | ✅ 实测「性能档变身质量档、帧率还涨 ~30%」 |

- 省心选「**推荐**」（NVIDIA 按游戏+驱动自动挑）；想拿最好选 **M**；L/M 取向可能不同，值得各打一局自己比（我看不到画面）。
- **与 DLSS 5 无关**：这套下拉里不会出现 DLSS 5（见下）。

## DLSS 5 的本质（别被"一键包"带偏）

- 官方 **2026-03-16 宣布**、**2026 秋推出**；定义为「**实时神经网络渲染模型**」—— 吃每帧**色彩 + 运动矢量**，用 AI 加**光照与材质**（不是单纯超分）。
- 交付方式：**走 NVIDIA Streamline 框架、由游戏开发者在引擎里集成**（官方博客措辞）→ **不是驱动侧「DLSS 覆盖」能强开的**。
- **首发驱动 = 616.64**（2026-09-04）；先支持 RTX 50 系，随后（2026-09-04 报道）确认扩展到 RTX 40 系。**用户驱动 616.92 比首发驱动更新 → 驱动不是瓶颈。**

## 燕云十六声（yysls）本机事实

- 装在 `D:\DGames\yysls`；**两个 exe**：`yysls_medium\Engine\Binaries\Win64r\yysls.exe` 与 `Win64rh\yysls.exe`（h 版应是高清/光追路径）。
- **游戏自带全套 upscaler**：`Engine\Binaries\{Win64r,Win64rh}\` 下有 `Streamline\nvngx_dlss.dll`（版本 **310.6.0.0**）/ `nvngx_dlssg.dll`（帧生成）/ `nvngx_dlssd.dll`（光线重建）/ `nvngx_deepdvc.dll` / `sl.dlss*.dll`；另有 `amd_fidelityfx_dx12.dll`(FSR)、`libxess*.dll`(XeSS)、`NRD.dll`。
- **官方支持只到 DLSS 4**（NVIDIA 2025-12 公告），**网易未宣布 DLSS 5** —— 用户"官方还没消息"的观察成立。

## ⚠️ 社区「燕云 DLSS5 一键包」= **注入器**，不是换文件

B 站教程（置顶评论挂**百度网盘 zip**）里，UP 自己的回复自曝：**「`dxgi.dll` 的名字能不能自定义…有的有反作弊的那几个都用不了」** → 这是**代理 DLL 注入**（OptiScaler / DLSS Enabler 那一类），把代码注入游戏进程，**不是替换 DLL**。

- **燕云是联机 + 反作弊** → 改客户端文件 / 注入 = **封号风险**；而且作者自己都说**被反作弊挡**（那几条回复还提到"传错压缩包""通用版还有 BUG"）。
- **安全等价路径**：NVIDIA App 的「DLSS 覆盖」做的**本就是同一件事**（换 DLSS 模型），但**驱动级、不碰游戏文件、反作弊不可见** → 要收益走它。第三方"一键包"还是**陌生网盘 zip，投毒风险**。
- **用户态度：不折腾**（原话"没事，也不是必须要弄"）。

关联：[[user-research-ai-profile]]（5060 Ti 本机硬件）、[[reference-workflow-architecture]]（游戏目录一律不动的纪律）。
