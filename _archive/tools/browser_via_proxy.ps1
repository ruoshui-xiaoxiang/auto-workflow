# browser_via_proxy.ps1 — 通过 SOCKS5 通道启动浏览器
# 用法: powershell -ExecutionPolicy Bypass -File browser_via_proxy.ps1 [edge|chrome|firefox] [url]

$ErrorActionPreference = "Stop"
$Proxy = "socks5://127.0.0.1:1080"
$Browser = if ($args.Count -ge 1 -and $args[0]) { $args[0].ToLower() } else { "edge" }
$Url = if ($args.Count -ge 2 -and $args[1]) { $args[1] } else { "https://www.google.com" }

# 确认通道在
$listening = Get-NetTCPConnection -LocalPort 1080 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    Write-Host "SOCKS 通道未启动，正在拉起..."
    & "D:\AIWorkflow\tools\proxy_start.ps1"
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

function Find-Exe {
    param([string[]]$Paths)
    foreach ($p in $Paths) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

switch ($Browser) {
    "edge" {
        $exe = Find-Exe @(
            "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        )
        if (-not $exe) { Write-Error "未找到 Edge"; exit 1 }
        Write-Host "启动 Edge (代理 $Proxy)..."
        Start-Process -FilePath $exe -ArgumentList "--proxy-server=`"$Proxy`"", $Url
    }
    "chrome" {
        $exe = Find-Exe @(
            "C:\Program Files\Google\Chrome\Application\chrome.exe",
            "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
        )
        if (-not $exe) { Write-Error "未找到 Chrome"; exit 1 }
        Write-Host "启动 Chrome (代理 $Proxy)..."
        Start-Process -FilePath $exe -ArgumentList "--proxy-server=`"$Proxy`"", $Url
    }
    "firefox" {
        $exe = Find-Exe @(
            "C:\Program Files\Mozilla Firefox\firefox.exe",
            "C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
        )
        if (-not $exe) { Write-Error "未找到 Firefox"; exit 1 }
        Write-Host "启动 Firefox..."
        Write-Host "Firefox 请手动设置: 设置→网络→手动代理→SOCKS Host 127.0.0.1 端口 1080，选 SOCKS v5，勾选'使用 SOCKS v5 时代理 DNS'"
        Start-Process -FilePath $exe $Url
    }
    default {
        Write-Error "不支持的浏览器: $Browser (可选 edge|chrome|firefox)"
        exit 1
    }
}
