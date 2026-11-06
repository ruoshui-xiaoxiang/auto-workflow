# proxy_stop.ps1 — 停止本地 SOCKS5 浏览通道
$LocalPid = "$env:TEMP\ssh_socks_1080.pid"
if (Test-Path $LocalPid) {
    $old = Get-Content $LocalPid -ErrorAction SilentlyContinue
    if ($old) {
        $p = Get-Process -Id $old -ErrorAction SilentlyContinue
        if ($p) {
            Stop-Process -Id $old -Force
            Write-Host "已停止 SSH 隧道 (PID $old)"
        } else {
            Write-Host "PID $old 不存在，可能已退出"
        }
    }
    Remove-Item $LocalPid -ErrorAction SilentlyContinue
} else {
    # 兜底：按命令行找 ssh -D 1080
    $cands = Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -match "-D\s+127\.0\.0\.1:1080|-D\s+1080" }
    if ($cands) {
        $cands | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force
            Write-Host "已停止 SSH 隧道 (PID $($_.ProcessId))"
        }
    } else {
        Write-Host "未发现运行中的 SOCKS 隧道"
    }
}
# 确认端口释放
Start-Sleep -Milliseconds 300
if (Get-NetTCPConnection -LocalPort 1080 -State Listen -ErrorAction SilentlyContinue) {
    Write-Warning "端口 1080 仍在监听，可能未完全释放"
} else {
    Write-Host "端口 1080 已释放"
}
