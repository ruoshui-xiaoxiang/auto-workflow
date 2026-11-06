---
name: reference-gpu-monitor-trafficmonitor
description: 本机性能监控正解＝TrafficMonitor v1.86 + MinimalPowerPlugin（D:\AIWorkflow\tools\TrafficMonitor），NVIDIA 叠加层口径偏游戏已被用户弃用
metadata:
  type: reference
---

2026-10-01 用户嫌 NVIDIA App 性能面板（Alt+R）数值不准，换装 **TrafficMonitor v1.86 + MinimalPowerPlugin v1.0.2**：

- 位置：`D:\AIWorkflow\tools\TrafficMonitor\TrafficMonitor\`（插件在其 `Plugins\` 子目录）；桌面快捷方式「性能监控.lnk」
- 实测占用：CPU ≈0.1% 全局（单核 1.9%）、内存 138 MB；GPU 项走 NVAPI/LibreHardwareMonitor，与任务管理器同源
- GPU 使用率/显存/温度需在悬浮条右键→显示设置勾选（一次性 GUI 操作）

**判"监控不准"的流程定论（10-01 实例）**：NVIDIA 面板显示 8% 而用户以为在跑视频生成——`nvidia-smi dmon -s um` 实测 SM 2%、ComfyUI 队列 running 0/pending 0，**是任务没在跑，不是监控坏了**。以后先跑三件套再下结论：dmon 采样、`curl 127.0.0.1:8189/queue`、output 目录 mtime。显存高≠在干活（模型常驻）。

## 🔴 ComfyUI `/system_stats` 的 `vram_free` 不可信（10-04 实测）

同一天两个数对不上：`GET /system_stats` 报 `devices[0].vram_free = 4.19 GB`（总 15.90 GB），
而 `nvidia-smi --query-gpu=memory.free` 报 **14557 MiB 空闲、总用量 1494 MiB**；
更硬的证据是**`POST /free {"unload_models":true,"free_memory":true}` 返回 200 之后，
`system_stats` 那个 4.19 GB 一动没动**——它不是实时采样，是 ComfyUI 自己缓存的旧账。

- **判据**：显存一律以 `nvidia-smi` 为准（`--query-gpu=name,memory.total,memory.used,memory.free --format=csv`）；
  `system_stats` 只用它的 `ram_free` 与 `comfyui_version`，**`vram_free` 不采信**。
- 差点造成的误判：我据此以为"没显存了、跑不动 Z-Image（6.2 GB）"，实际卡上 14 GB 空着。
- 顺带：`nvidia-smi --query-compute-apps` 在本机所有进程的 `used_memory` 都是 **N/A**，
  拿不到"谁占了多少显存"，只能拿总数；要指名占用者得看进程清单自己推。
- 同族：[[feedback-evidence-loop-trap]] 同族⑩（数字要从权威源现读，别拿缓存值）。
