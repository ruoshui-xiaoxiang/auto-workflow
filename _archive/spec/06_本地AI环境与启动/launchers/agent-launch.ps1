param(
    [ValidateRange(0,3)] [int]$Tier = 0,
    [int]$Port = 8082,
    [switch]$Stop,
    [switch]$Status
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

# 桌面窗口的后端。窗口只负责显示，真正的判断全在这里，所以同一套逻辑也能命令行用：
#   agent-launch.ps1 -Status          打印 KEY=VALUE 现状
#   agent-launch.ps1 -Tier 1|2|3      起对应档（已在跑则直接报告，不重复起）
#   agent-launch.ps1 -Stop            卸载所有 llama-server
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$portList = 8082, 8083, 8084
$TIER_DESC = @{
    1 = 'gpt-oss-20b 全进显存 + 65536   净显存 11957 MiB / 114 tok/s / 独占整卡'
    2 = 'gpt-oss-20b 专家卸内存 + 65536  净显存  2354 MiB /  27 tok/s / 能力同档1'
    3 = 'Qwen2.5-7B Q4_K_M + 16384      净显存  4780 MiB /  82 tok/s / 装不下 41k 请求'
}

# alias 的唯一事实源在 start-agent-tier.ps1 的 $ALIAS，这里不再抄一份，避免改一处漏一处。

function Get-Gpu {
    $csv = (& nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits) -split ','
    [pscustomobject]@{ Used = [int]$csv[0].Trim(); Total = [int]$csv[1].Trim() }
}

function Get-Loaded { Get-Process llama-server -ErrorAction SilentlyContinue }

function Test-Ready([int]$p) {
    # 就绪轮询专用：一次 HTTP 就够，别在这里扫监听端口。
    try { (Invoke-RestMethod "http://127.0.0.1:$p/v1/models" -TimeoutSec 2).data[0].id } catch { $null }
}

function Done([string]$r) {
    # 桌面窗口不能等 stdout 的 EOF：它读的是本脚本的管道，而本脚本 Start-Process 出去的
    # llama-server 会继承同一个写句柄，服务活着 EOF 就永远不来，窗口会卡在"正在加载"。
    # 所以每条终止路径都必须自己报一声 DONE=。
    Write-Host "DONE=$r"
}

function Get-Serving {
    # 用监听端口认定"哪个档在服务"，比按进程名猜可靠：LM Studio 自己也会起 llama-server。
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $portList -contains $_.LocalPort } |
        Sort-Object LocalPort -Unique |
        ForEach-Object {
            $p = $_.LocalPort
            $id = Test-Ready $p
            if (-not $id) { $id = '未知' }
            [pscustomobject]@{ Port = $p; Model = $id; ProcId = [int]$_.OwningProcess }
        }
}

function Show-Status {
    $g = Get-Gpu
    "VRAM_USED=$($g.Used)"
    "VRAM_TOTAL=$($g.Total)"
    $ram = Get-CimInstance Win32_OperatingSystem
    "RAM_FREE_GB={0:N1}" -f ($ram.FreePhysicalMemory / 1MB)
    foreach ($s in Get-Serving) { "SERVING=$($s.Port):$($s.Model):$($s.ProcId)" }
    foreach ($pr in Get-Loaded) { "PROC=$($pr.Id):$([int]($pr.WorkingSet64/1MB))MB" }
}

function Stop-All {
    $procs = @(Get-Loaded)
    if (-not $procs) { Write-Host '没有在跑的 llama-server，显存已经空了。'; return }
    $before = Get-Gpu
    $procs | ForEach-Object { Stop-Process -Id $_.Id -Force }
    Start-Sleep -Seconds 3
    $after = Get-Gpu
    Write-Host ("已卸载 {0} 个 llama-server（pid {1}），显存 {2} -> {3} MiB used" -f `
        $procs.Count, ($procs.Id -join ','), $before.Used, $after.Used) -ForegroundColor Green
}

# -Status 不起任何进程，EOF 正常到达，所以不用报 DONE；报了这个人类直接跑时会多一行噪音。
if ($Status) { Show-Status; exit 0 }
if ($Stop)   { Stop-All;    Done 'ok'; exit 0 }

if ($Tier -eq 0) { Write-Host '要用 -Tier 1|2|3 指定档位' -ForegroundColor Red; Done 'fail'; exit 2 }
$desc = $TIER_DESC[$Tier]

# 幂等：同端口已有服务就别再起了。档 1/档 2 现在各用独立 alias（-t1/-t2），
# 但三档仍共用一个端口，重复起只会撞显存，换档得先 -Stop。
$serving = @(Get-Serving | Where-Object { $_.Port -eq $Port })
if ($serving) {
    Write-Host "端口 $Port 上已经有 $($serving[0].Model) 在服务，不重复启动。" -ForegroundColor Green
    Write-Host "要换档请先 -Stop。" -ForegroundColor Yellow
    Write-Host "ENDPOINT=http://127.0.0.1:$Port/v1/chat/completions"
    Write-Host "MODEL_ID=$($serving[0].Model)"
    Done 'ok'
    exit 0
}

Write-Host "档 $Tier：$desc" -ForegroundColor Cyan
$launchScript = Join-Path $here 'start-agent-tier.ps1'
$ok = $false
for ($attempt = 1; $attempt -le 2 -and -not $ok; $attempt++) {
    try {
        # -PrintArgs 让 start-agent-tier.ps1 只做完参数探测和显存闸门就把结果交出来，
        # 闸门照样生效；被拒绝时走下面的占用确认，而不是绕过它硬起。
        $raw = & $launchScript -Tier $Tier -Port $Port -PrintArgs -ErrorAction Stop | Out-String
    } catch {
        $msg = $_.Exception.Message
        Write-Host "[拒绝] $msg" -ForegroundColor Red
        if ($msg -notmatch '显存不足' -or $attempt -eq 2) { Show-Status; Done 'fail'; exit 1 }
        $loaded = @(Get-Loaded)
        if (-not $loaded) { Done 'fail'; exit 1 }
        Write-Host ("占着显存的是 {0} 个 llama-server（pid {1}，共 {2} MB）。卸载后重试点 档{3}？" -f `
            $loaded.Count, ($loaded.Id -join ','),
            [int](($loaded | Measure-Object WorkingSet64 -Sum).Sum / 1MB), $Tier) -ForegroundColor Yellow
        # 窗口是用 CreateNoWindow 拉起 powershell 的，这里 Read-Host 没人能回答，会永远卡住。
        # 窗口会带上 AGENT_NO_PROMPT=1；真在控制台里双击跑时没有这个变量，照常询问。
        if ($env:AGENT_NO_PROMPT -eq '1') {
            Write-Host '[需要确认] 显存不够，当前是非交互调用，不会自动卸载别的模型。' -ForegroundColor Red
            Write-Host '请先点窗口里的「卸载全部模型」，再点档位。' -ForegroundColor Yellow
            Done 'need-stop'
            exit 1
        }
        if ((Read-Host '输入 Y 卸载并继续，其他键放弃').Trim().ToUpper() -ne 'Y') { Done 'fail'; exit 1 }
        Stop-All
        continue
    }
    $server = ($raw -split "`n" | Where-Object { $_ -like 'SERVER:*' } | Select-Object -First 1).Substring(7).Trim()
    $params = @($raw -split "`n" | Where-Object { $_ -like 'PARAM:*' } | ForEach-Object { $_.Substring(6).Trim() })
    if (-not $server -or -not $params) { Write-Host '[失败] 没拿到启动参数' -ForegroundColor Red; Done 'fail'; exit 1 }

    $dir = "E:\LocalAI\logs\agent-tier$Tier"
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $stamp = Get-Date -Format 'HHmmss'
    $out = Join-Path $dir "server-$stamp.log"
    $errf = Join-Path $dir "server-$stamp.err.log"
    Write-Host "后端：$server"
    Write-Host "日志：$out"
    # 和 start-qwen1234.ps1 一样：起在后台，关掉这个窗口服务不会停，要用 -Stop 才卸载。
    Start-Process -FilePath $server -ArgumentList $params -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $errf | Out-Null

    Write-Host '正在加载模型（冷读 12 GB 实测最久 255 秒，慢是正常的）...' -ForegroundColor Cyan
    for ($i = 0; $i -lt 210; $i++) {
        Start-Sleep -Seconds 2
        $id = Test-Ready $Port
        if ($id) {
            Write-Host "[就绪] $id @ http://127.0.0.1:$Port/v1" -ForegroundColor Green
            Write-Host "Trae 里 Base URL 和 Model ID 已填好，直接复制。" -ForegroundColor Yellow
            Write-Host "ENDPOINT=http://127.0.0.1:$Port/v1/chat/completions"
            Write-Host "MODEL_ID=$id"
            Done 'ok'
            $ok = $true
            break
        }
        if ($i % 8 -eq 0) { Write-Host ("仍在加载… 已等 {0} 秒" -f ($i * 2)) }
    }
    if (-not $ok) {
        Write-Host '[超时] 7 分钟内没起来。看日志文件，或用「卸载全部模型」清干净再试。' -ForegroundColor Red
        Write-Host "TAILLOG=$out"
        Done 'fail'
        exit 1
    }
}
exit 0

