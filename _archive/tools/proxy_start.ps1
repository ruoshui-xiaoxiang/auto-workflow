# proxy_start.ps1 — 通过云服务器开启本地 SOCKS5 浏览通道
# 用法: powershell -ExecutionPolicy Bypass -File proxy_start.ps1
# 成功后浏览器代理填: 127.0.0.1:1080 (SOCKS5)

$ErrorActionPreference = "Stop"
$Key = "$env:USERPROFILE\.ssh\server_deploy_key"
$Host_ = "root@47.250.138.158"
$Port = 1080
$LocalPid = "$env:TEMP\ssh_socks_1080.pid"

# 若已在跑则先停
if (Test-Path $LocalPid) {
    $old = Get-Content $LocalPid -ErrorAction SilentlyContinue
    if ($old) {
        $p = Get-Process -Id $old -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -match "ssh") {
            Write-Host "检测到旧隧道 (PID $old)，先停止..."
            Stop-Process -Id $old -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
    }
}

# 端口占用检查
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Error "端口 $Port 已被占用，先关掉占用进程再启动。"
    exit 1
}

Write-Host "启动 SSH SOCKS5 隧道 → 127.0.0.1:$Port ..."
$sshArgs = @(
    "-i", $Key,
    "-N",
    "-D", "127.0.0.1:$Port",
    "-o", "BatchMode=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    $Host_
)
$proc = Start-Process -FilePath "ssh" -ArgumentList $sshArgs -WindowStyle Hidden -PassThru
$proc.Id | Out-File -FilePath $LocalPid -Encoding ascii

# 等待端口就绪
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        $ready = $true
        break
    }
    if ($proc.HasExited) {
        Write-Error "SSH 进程已退出 (code $($proc.ExitCode))，检查密钥/网络。"
        exit 1
    }
}
if (-not $ready) {
    Write-Error "端口 $Port 未在 10 秒内就绪。"
    exit 1
}

# 走代理验证出网
Write-Host "隧道已就绪，验证出网..."
$env:HTTPS_PROXY = "socks5h://127.0.0.1:$Port"
$env:HTTP_PROXY = "socks5h://127.0.0.1:$Port"
try {
    $code = curl.exe -s --max-time 15 -o NUL -w "%{http_code}" https://www.google.com
    Write-Host "经代理访问 google.com → HTTP $code"
    $code2 = curl.exe -s --max-time 15 -o NUL -w "%{http_code}" https://github.com
    Write-Host "经代理访问 github.com → HTTP $code2"
} finally {
    Remove-Item Env:HTTPS_PROXY, Env:HTTP_PROXY -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "=== 通道已开启 ==="
Write-Host "SOCKS5 代理: 127.0.0.1:$Port"
Write-Host "浏览器设置: 代理类型 SOCKS5 / 主机 127.0.0.1 / 端口 $Port"
Write-Host "  · Firefox: 设置→网络→手动代理→SOCKS Host→勾选'使用 SOCKS v5 时代理 DNS'"
Write-Host "  · Chrome/Edge: 启动参数 --proxy-server=\"socks5://127.0.0.1:$Port\""
Write-Host "停止: 运行 proxy_stop.ps1"
