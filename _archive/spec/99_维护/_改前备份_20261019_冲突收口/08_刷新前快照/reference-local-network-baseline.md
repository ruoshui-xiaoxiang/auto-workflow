---
name: reference-local-network-baseline
description: 本机网络基线与体检方法——有线千兆、线路实测 450–500 Mbps、IPv6 走中国移动、代理基线为"关"但装有 Clash Party 客户端（E:\代理\，起 GUI 会自己打开系统代理 7890）；百度网盘"开了会员还慢"真因是海量小文件排队；附卡密「代下/不限速」类灰产识别判据
metadata:
  type: reference
---

## 本机网络基线（2026-09-29 01:10 只读体检实测）

- **接入**：有线 `Realtek PCIe GbE Family Controller`，协商 **1 Gbps**；WLAN（Realtek 8852BE）未连接。网关 `<网关IP>`，本机 `<内网主机IP>`。
- **代理三处全关**：WinHTTP 直连；IE/WinINET `ProxyEnable=0`；百度网盘自身 `ProxySetting.ini` 里 `proxy_type=0`；环境变量无代理。
- **hosts 干净**（无非注释行）。
- **TCP 全是健康默认值，没有可调项**：接收窗口自动调节 `normal`、RSS 开、窗口缩放启发 `disabled`、Fast Open 开、ECN `disabled`。
- **网卡卸载**：校验和 offload 收发全开、LSO v2 开（64KB）、RSS 4 队列、**Advanced EEE 关闭**；`ReceivedDiscardedPackets=0`、`ReceivedPacketErrors=0`、`OutboundPacketErrors=0`。
- **IPv6 可用且不慢**：全局 `2409:8a62:288:4330::/64`（origin=RouterAdvertisement），默认路由正常。该前缀属**中国移动**。
- **DNS** 由路由器 `fe80::1` 转发；`pan.baidu.com` 正常解析出 v4 `112.34.111.107/108` ＋ v6。

### 实测吞吐（判"是不是网络慢"必须落到这个数上）

| 测法 | 结果 |
|---|---|
| 单连接拉腾讯云镜像（`mirrors.cloud.tencent.com/ubuntu/ls-lR.gz`，38MB） | **32–36 MB/s** |
| 4 路并发 range 请求同一文件 | 合计 **52 MB/s** |
| 期间网卡总接收（`Get-NetAdapterStatistics` 每 2s 采样） | **峰值 57 MB/s ≈ 460 Mbps** |
| 空闲基线 | RX **32.5 MB/s**、TX 0.7–1.3 MB/s |

⇒ **线路上限约 450–500 Mbps**（NIC 千兆，WAN 在 450–500M 量级）。**单连测试会被服务端限速，必须并发多路才测得出上限。**

### 百度网盘侧（同一时点实测）

- `baidunetdiskhost` 进程 IO ≈ **50 MB/s**（≈ 下载 32 MB/s ＋ 磁盘写）⇒ 百度网盘**自己已跑到 32 MB/s ≈ 256 Mbps**，吃掉线路约一半。
- 93 条 ESTABLISHED 里 **91 条走 IPv6（443）**，仅 2 条 v4；连接数在 93↔116 间抖动（有重连）。
- ⇒ **"开了会员还是慢"在本机不是网络问题、也不是配置问题。** 真瓶颈大概率是**海量小文件排队**（那次下的是 20 套素材 ≈ 2000+ 个 2–2.5MB 的 PNG），界面显示的"当前速度"是单文件速度。**可行解只有两条：整包/文件夹下载，以及把上传限速拉到最小**（观测 TX 0.7–1.3 MB/s，做种会挤占上行）。

### 体检方法（可复用）

1. 适配器/速率 `Get-NetAdapter`；地址与默认路由 `Get-NetIPAddress` / `Get-NetRoute`。
2. **代理要查三处**：`netsh winhttp show proxy`、`HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings` 的 `ProxyEnable/ProxyServer`、应用自己的配置文件。
3. **空闲基线用网卡计数器差分**：`Get-NetAdapterStatistics` 取两次隔 10s 相减。
4. **属主归属用进程 IO 计数器**：`Get-Counter "\Process(<name>*)\IO Data Bytes/sec"` —— 比 netstat 更能指出"是谁在占用"。
5. 吞吐用 `curl -o /dev/null -w "%{speed_download}"`；`-4` / `-6` 分别强制测一遍才判得出哪个协议栈是弱腿。
6. 网卡健康：`Get-NetAdapterStatistics` 的 Discarded/Errors，`Get-NetAdapterChecksumOffload` / `-Lso` / `-Rss`，高级属性里的 Energy/Green/EEE/Power Saving。
7. 中文适配器名在 Git Bash 输出会乱码，但脚本里按 `InterfaceDescription -like "*GbE*"` 选就没事。

### 三个无害但要留意的残留

- 网卡高级属性 **`Power Saving Mode = 启用`**（关掉对延迟稳定性略有帮助，对吞吐影响很小）。改它要管理员权限、会重置网卡断网几秒 ⇒ **改前先问用户**。
- 注册表残留 `ProxyServer=127.0.0.1:7890`（`ProxyEnable=0` 已禁用），是以前 Clash 类工具留下的。现在无害；若以后重装并换端口，不吃 WinINET 开关的程序可能误连。参考 [[reference-cn-download-mirrors]]。
  - 🔴 **2026-10-04 更新：那条残留不是残留，是装过的客户端的默认口。** 客户端＝**Clash Party**（FlClash 系，
    Electron），注册表 DisplayName `Clash Party`／InstallLocation `E:\FlClash\`，
    实际 exe 在 **`E:\代理\Clash Party\Clash Party.exe`**，内核 **`resources\sidecar\mihomo.exe`**
    （另有 `mihomo-alpha.exe`／`mihomo-smart.exe`），起来后听 **`127.0.0.1:7890`**。
  - ⚠ **启动 GUI 会自己把系统代理打开**（`ProxyEnable` 0→1），不是我用命令改的。
    绕过表含 `localhost;127.*;192.168.*;…`，所以本机 ComfyUI（127.0.0.1:8189）不受影响，
    但**其他程序流量会一并走代理**——这与他 09-29 那次体检记的"三处代理全关"基线相反，
    属于**机器级状态改变，必须主动报**。10-04 他明确说「代理先留着」，所以那次是**授权常开**，
    但**下次新会话不要假设它还开着**（基线仍是"关"）。
  - 用法：只给自己的请求加 `-x http://127.0.0.1:7890`，**不要顺手改全局/环境变量代理**。
  - 吞吐提醒：走代理拉 civitai CDN 明显慢于 hf-mirror 直连（后者 10-04 实测 16.8 MB/s，
    代理链路拉 648 MB 要十几分钟且中途断供）。⇒ **能走镜像就别走代理**，代理只用于镜像没有的站（civitai）。
- 常驻 **`AweSun`（向日葵，4 进程）**：本次空闲（IO=0），但这类远控工具串流时会静默吃上行。
- 百度网盘的用户设置文件（`%APPDATA%\baidu\BaiduNetdisk\users\<uid>\PersonalSetting.xml`）是**加密/混淆的**，读不出会员档位 —— **档位只能用户在 App 里自己确认**（"普通会员"没有下载提速，只有超级会员 SVIP 有）。

## 卡密「代下/不限速」类灰产服务的识别判据（2026-09-29 实例）

用户拿过一个 `http://<裸IP>:8000/down?card=<卡密>` 问"这个网站有问题么"。落地页自称「**百度网盘极速下载 - 企业团队下载券转换系统**」—— 原理不是破解限速，而是**让你蹭百度企业版的团队下载券/企业通道**（"一键加入企业团队，畅享不限速下载"）。

**判据（任一命中就该拦）**：

- 裸 IP、**非标端口**、**无域名/无反向解析**、**纯 HTTP 无 TLS**、国内无备案 ⇒ 可随时丢弃的落地。
- 落地页只是 JS 外壳（3–4 KB），真正逻辑在前端脚本里。
- **卡密写死在 URL 里** ⇒ 这条 URL 本身就是凭证，明文过链路易被截获。（实例：`210.16.171.69:8000`，湖北武汉，AS146817 Hubei Feixun Network。）

**风险（按严重度）**：

1. 卡密＝凭证已泄漏；建议当它作废、别再外发、用完即弃。
2. "加入企业团队"必须交出**百度账号关系**（团队管理员对该账号有管理权限）。
3. 若索要 **BDUSS／cookie ⇒ 账号被完全接管**（可读全部文件、可删、可代操作）—— **绝对红线**，用户网盘里有商业素材与项目资产。
4. "链接转换"意味着**你的分享内容对它完全可见**（含酒店业务资料/PII 就是外泄）。
5. 代下链路可**换包**（尤其 .exe/.zip）。
6. 裸 IP＋卡密充值＝**跑路无售后**（黑猫投诉有同类"效果不佳望退款"案例）；合规上属灰产。

**How to apply**：用户再来问"下载慢 / 有没有办法绕"时 —— ① 先跑上面的体检把**真实瓶颈**测出来（本次结论是网络无问题，真瓶颈在小文件排队）；② 再说明他找的这条对他没用（换通道解决不了排队，却要交出账号与素材）；③ **不要去请求带卡密的那条链接**（会消耗他的卡密），只看根路径/公开页面做判定。相关 [[feedback-credential-no-echo]]、[[reference-cn-download-mirrors]]、[[feedback-server-security-reporting]]。
