param(
    # 非交互入口：给 agent / 脚本 / 其它软件调用。不带参数＝人工菜单（2026-10-19 起只剩两项，状态自动显示）。
    [ValidateSet('menu','up','status','models','chat','down','pipeline','stop')]
    [string]$Action = 'menu',
    [string]$Model = 'qwen3-14b',
    [int]$Tier = 1,
    [switch]$Json,
    [string]$Text = ''
)
$ErrorActionPreference = 'Stop'
# （2026-10-19 菜单收敛后本文件不再需要脚本根目录：所有路径都是绝对写的，
#   原先的 $ROOT 只剩一处用它的调用（gateway\start-desktop.bat），那处已去掉。）

# ============================================================
# agent出片引擎 —— 本机唯一的 Agent / 出片 / LLM 默认启动入口
#
# 【强制声明】任何 agent 跑出图 / 出片 / 工作流 / 本地 LLM 时，
#   必须默认从本入口（E:\LocalAI\LocalAI.bat）启动或引用本入口拉起的服务。
#   禁止另开端口、禁止绕过网关直连零散脚本。
#
# 端口总表（互不抢占）：
#   11434  Ollama                    （通道：OLL）
#   1234   LM Studio Local Server    （通道：LM）
#   8080   本引擎网关 OpenAI 兼容     （通道：agent出片引擎）
#   8081   qwen3-14b llama-server    （本引擎后端）
#   8082   agent 档 llama-server     （本引擎后端，换档先卸载）
#   8189   统一 ComfyUI（FLUX/SDXL/H3）——唯一的出片后端进程
#   8787 / 8790  已废门面端口（engine WebUI / 说话出片 UI）：本菜单**不启动**它们，
#                只在状态里如实显示有没有残留进程还占着
#
# 菜单只两项（2026-10-19 用户裁定「收成 2 项，最狠」）：
#   1 = 起模型服务（网关 8080 + 后端 qwen3-14b）
#   2 = 停服务腾卡（停 8081-8084，顺带保证 ComfyUI 8189 在跑）
#   0 = 退出
#   ⇒ 状态不再占一个按键：每次画菜单时自动打在屏幕上（Get-StatusPanel，进程内查，不起子进程）。
#   ⇒ 出片不在本菜单里：人用走桌面「娱乐流」，agent 走 `python run.py <workflow>`。
#     原第 4 项「卸载本地 LLM」本来就是第 2 项的第一步，已并入（`-Action stop` 仍单独可用）。
#   ⇒ 本菜单**不再默认弹 tkinter 工作台**（`gateway\desktop.py`，它前台阻塞、而且是第三个 GUI）。
#     想手动试模型：跑 `gateway\start-desktop.bat`，或 `LocalAI.bat -Action chat -Text "..."`。
# ============================================================

$PORT_MAP = [ordered]@{
    11434 = 'Ollama (OLL)'
    1234  = 'LM Studio (LM)'
    8080  = '网关 8080'
    8081  = 'qwen3-14b 后端'
    8082  = 'agent档后端 t1'
    8083  = 'agent档后端 t2'
    8084  = 'agent档后端 t3'
    8189  = 'ComfyUI 8189'
    8787  = '已废 WebUI'
    8790  = '已废 说话出片'
}

function Get-StatusPanel {
    # 状态面板：一次 Get-NetTCPConnection 拿全部监听，进程名用 in-process 的 Get-Process，
    # 不起 PowerShell 子进程（原来 Show-Status 每个端口起一次查询，画一次菜单要十几次）。
    # 为什么要记进程名：2026-10-19 8790 曾 LISTEN pid=37940，十几分钟后进程没了，
    # 只留个号 ⇒ 事后问「那是哪个程序」只能靠推断。
    $lines = @()
    $listen = @{}
    $queryFailed = ''
    try {
        # 🔴 LocalPort 是 [uint16]，而 $PORT_MAP 的键是 [int] ⇒ 直接 .Contains($c.LocalPort)
        # **恒为 False**（装箱类型不同，Equals 不认），实测有 8189 在听却报 0 行、全表 idle。
        # 一律先 [int] 归一再查表。
        $all = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
        foreach ($c in $all) {
            $port = [int]$c.LocalPort
            if ($PORT_MAP.Contains($port) -and -not $listen.ContainsKey($port)) {
                $listen[$port] = $c.OwningProcess
            }
        }
    } catch {
        # 查询失败**不许静默当成「全空闲」**：那样这张表会把「在跑」的服务报没了。
        $queryFailed = $_.Exception.Message
    }
    $vramLine = '显存 未取到'
    try {
        $nv = (& nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>$null)
        if ($nv) { $parts = ($nv -split ','); $vramLine = '显存 {0}/{1} MiB 已用' -f [int]$parts[0], [int]$parts[1] }
    } catch {}
    $gwLine = ''
    if ($listen.ContainsKey(8080)) {
        try {
            $m = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/v1/models' -TimeoutSec 3
            $ids = @($m.data | ForEach-Object { $_.id })
            $gwLine = '  在服模型：' + ($ids -join ', ')
        } catch { $gwLine = '  在服模型：端口在听但 /v1/models 没答（后端可能还在装权重）' }
    }
    $ghosts = @()
    foreach ($port in $PORT_MAP.Keys) {
        if ($listen.ContainsKey($port)) {
            $procId = $listen[$port]
            $name = '?'
            try { $name = (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch {}
            $lines += ('   :{0,-5} {1,-16} LISTEN pid={2} ({3})' -f $port, $PORT_MAP[$port], $procId, $name)
            if ($port -in 8787, 8790) { $ghosts += $port }
        } else {
            $lines += ('   :{0,-5} {1,-16} idle' -f $port, $PORT_MAP[$port])
        }
    }
    return @{ lines = $lines; vram = $vramLine; gateway = $gwLine; ghosts = $ghosts;
              queryFailed = $queryFailed }
}

function Show-Menu {
    Clear-Host
    $st = Get-StatusPanel
    Write-Host ""
    Write-Host "  ============ agent出片引擎 · 本地模型服务 ============"
    Write-Host ""
    Write-Host "  这里只管本地 LLM 的起停。出片不走这里：" -ForegroundColor DarkGray
    Write-Host "    人用 = 桌面「娱乐流」(8189+面板)   agent = engine\run.py" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host ("  " + $st.vram)
    if ($st.queryFailed) {
        Write-Host ("   🔴 端口查询失败：" + $st.queryFailed + " —— 下面这张表不可信，别据此判断服务没在跑") -ForegroundColor Red
    }
    foreach ($l in $st.lines) { Write-Host $l }
    if ($st.gateway) { Write-Host ("  " + $st.gateway.Trim()) -ForegroundColor DarkGray }
    if ($st.ghosts.Count) {
        Write-Host ("   ⚠ 已废门面端口仍有人占着：" + ($st.ghosts -join ', ') +
                    " —— 那个进程不归本菜单管，自己关或直接 kill") -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "    1   起模型服务      网关 8080 + qwen3-14b 后端（显存不够会拒绝起并给选项）"
    Write-Host "    2   停服务腾卡      停 8081-8084 后端，顺带保证 ComfyUI 8189 在跑"
    Write-Host ""
    Write-Host "    0   退出"
    Write-Host ""
    Write-Host "  真源: E:\LocalAI\CHANNELS.md（通道）· D:\AIWorkflow\官方路径.json（入口）" -ForegroundColor DarkGray
    Write-Host "  -----------------------------------------------"
}

function Start-ModelService {
    # 不再前台阻塞弹 tkinter 工作台（那是第三个 GUI）；起服务这件事只有一份实现：agent_engine.py up
    Write-Host ""
    Write-Host "  [起模型服务] 网关 8080 + 后端 qwen3-14b ..." -ForegroundColor Cyan
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { Write-Host "[ERROR] python not on PATH" -ForegroundColor Red; return }
    & $py 'D:\AIWorkflow\tools\agent_engine.py' up --model qwen3-14b
    Write-Host ""
    Write-Host "  想手动试模型（tkinter 工作台，前台阻塞到关窗）：E:\LocalAI\gateway\start-desktop.bat" -ForegroundColor DarkGray
    Write-Host "  不换窗口快速验一句：LocalAI.bat -Action chat -Text \"你好\"" -ForegroundColor DarkGray
    Write-Host "  要出图出片：按 2 腾卡，或直接双击桌面「娱乐流」。" -ForegroundColor DarkGray
}

function Start-AgentPipeline {
    # 菜单 2 / -Action pipeline（同一个实现，人和 agent 走同一条）。
    # = 停 8081-8084 腾显存（原菜单第 4 项，已并进来）＋ 保证唯一后端 ComfyUI 8189 在跑。
    # 2026-10-19 治理：不再启动 8787 引擎 WebUI 与 8790 说话出片 UI（已登记废弃）。
    # 人要看得懂的界面走 E:\LocalAI\娱乐流.bat（同样只占 8189）。
    Write-Host ""
    Write-Host "  [停服务腾卡] 把显存让给 ComfyUI ..." -ForegroundColor Cyan
    Stop-LocalLLM
    $uni = Get-NetTCPConnection -LocalPort 8189 -State Listen -ErrorAction SilentlyContinue
    if ($uni) {
        Write-Host "   统一实例 8189 已在跑，复用。" -ForegroundColor DarkGray
    } else {
        Write-Host "   统一实例 8189 未运行，正在拉起 ..." -ForegroundColor Yellow
        $bat = 'D:\AIWorkflow\ComfyUI_H3\run_H3_ComfyUI.bat'
        if (-not (Test-Path $bat)) {
            Write-Host "   [ERROR] 启动脚本不在：$bat" -ForegroundColor Red
            Write-Host "           真源见 D:\AIWorkflow\官方路径.json（entries）" -ForegroundColor Red
            return
        }
        Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$bat`"" `
            -WorkingDirectory 'D:\AIWorkflow\ComfyUI_H3' -WindowStyle Minimized
        # 等待窗口按 2026-10-19 11:29 那次重启的实测定：ComfyUI-Manager 开机拉 github 超时
        # 会把启动拖到 200~300 秒，原来 180 秒就报失败是误判 ⇒ 等到 420 秒并每 60 秒报进度。
        $ready = $false
        for ($i = 1; $i -le 210; $i++) {
            Start-Sleep -Seconds 2
            if ($i % 30 -eq 0) { Write-Host ("   还在等，已 %d 秒 …" -f ($i * 2)) -ForegroundColor DarkGray }
            $c2 = Get-NetTCPConnection -LocalPort 8189 -State Listen -ErrorAction SilentlyContinue
            if ($c2) { $ready = $true; break }
        }
        if ($ready) { Write-Host "   8189 已就绪。" -ForegroundColor Green }
        else { Write-Host "   [WARN] 420 秒内 8189 没起来，看那个最小化窗口的报错（别反复点图标）。" -ForegroundColor Yellow }
    }
    Write-Host ""
    Write-Host "  agent 出片请走唯一编排入口（不再有 WebUI）：" -ForegroundColor Cyan
    Write-Host "    cd D:\AIWorkflow\engine && python run.py <workflow> [--tier play|draft|final]" -ForegroundColor White
    Write-Host "  人要带界面的：双击桌面「娱乐流」（只起 8189 + 面板页，不新占端口）。" -ForegroundColor DarkGray
    Write-Host "  已废：8787 引擎 WebUI / 8790 说话出片 UI（登记在 D:\AIWorkflow\官方路径.json 的 deprecated 段，状态「待归档」⇒ 原脚本还能跑，路障桩未立）。" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  出片结束后要恢复 LLM 后端，用菜单 1。" -ForegroundColor DarkGray
}

function Stop-LocalLLM {
    param([switch]$NoSweep)
    Write-Host ""
    $stopped = $false
    foreach ($p in 8081, 8082, 8083, 8084) {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $procId = ($conn | Select-Object -First 1).OwningProcess
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Host "   已停 :$p (PID $procId)" -ForegroundColor Green
            $stopped = $true
            Start-Sleep -Seconds 2
        }
    }
    # 残留 llama-server 也占显存，但**不能按名字一把杀**：LM Studio 的服务进程可能同名，
    # 那是通道 1（1234），不归本入口管 ⇒ 只杀命令行里确实带我们 8081-8084 端口的那些。
    if (-not $NoSweep) {
        try {
            # 判据收紧：必须是**我们的启动器留下的痕迹**（--port 8081-8084 或路径在 LocalAI 下），
            # 只按 '808[1-4]' 太宽——LM Studio 的模型文件名里恰好带这四位数字就误杀。
            $mine = Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction Stop |
                    Where-Object { $_.CommandLine -match '--port\s*808[1-4]' -or
                                   $_.CommandLine -match 'LocalAI' -or
                                   $_.ExecutablePath -match '^E:\\LocalAI\\' }
            foreach ($m in $mine) {
                Stop-Process -Id $m.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Host "   已清理残留 llama-server (PID $($m.ProcessId))" -ForegroundColor Green
                $stopped = $true
            }
        } catch {}
    }
    if (-not $stopped) {
        Write-Host "   没有在跑的本地 LLM 后端。" -ForegroundColor DarkGray
    } else {
        Write-Host "   Ollama / LM Studio 未动。" -ForegroundColor DarkGray
    }
}

# ============================================================
# 非交互模式（agent / 脚本 / 其它软件）：无 Clear-Host、无 Read-Host、有退出码
#   LocalAI.bat -Action up [-Model qwen3-14b|agent|none] [-Tier 1|2|3] [-Json]
#   LocalAI.bat -Action status|models|down [-Json]
#   LocalAI.bat -Action chat -Text "..." [-Json]
#   LocalAI.bat -Action pipeline   # 菜单 2 等价：停后端腾卡 -> 保证 ComfyUI 8189 在跑（不起 8787/8790）
#   LocalAI.bat -Action stop       # 只停 8081-8084 后端（含命令行带 8081-8084/LocalAI 的残留 llama-server）
# 真正的实现在 D:\AIWorkflow\tools\agent_engine.py（这里只做转发，避免两套逻辑）
# ⚠ 例外：pipeline / stop 两个动作本地实现（agent_engine.py 不管腾卡与门面），别当成转发了
# ⚠ 菜单里没有「出片」这一项，也不该有：门面只两个（娱乐流 / run.py），本菜单只管模型服务
# ============================================================
if ($Action -ne 'menu') {
    $cli = 'D:\AIWorkflow\tools\agent_engine.py'
    if ($Action -eq 'pipeline') { Start-AgentPipeline; exit 0 }
    if ($Action -eq 'stop')     { Stop-LocalLLM; exit 0 }
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $py) { Write-Host '[ERROR] python not on PATH'; exit 4 }
    if (-not (Test-Path $cli)) { Write-Host "[ERROR] missing $cli"; exit 4 }
    $cliArgs = @($cli, $Action)
    if ($Json) { $cliArgs += '--json' }
    if ($Action -eq 'up') {
        $cliArgs += @('--model', $Model)
        if ($Model -eq 'agent') { $cliArgs += @('--tier', "$Tier") }
    }
    if ($Action -eq 'chat') {
        if (-not $Text) { Write-Host '[ERROR] -Action chat 需要 -Text "..."'; exit 4 }
        $cliArgs += $Text
    }
    & $py @cliArgs
    exit $LASTEXITCODE
}

while ($true) {
    Show-Menu
    $ch = (Read-Host "   请选择 [0-2]").Trim()

    switch ($ch) {
        '1' { Start-ModelService; [void](Read-Host "   按回车返回菜单") }
        '2' { Start-AgentPipeline; [void](Read-Host "   按回车返回菜单") }
        '0' { exit 0 }
        default {
            Write-Host "   无效选择。" -ForegroundColor Yellow
            Start-Sleep -Milliseconds 600
        }
    }
}
