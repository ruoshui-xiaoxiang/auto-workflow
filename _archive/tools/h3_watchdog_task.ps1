# H3 产线停摆监测 —— Windows 计划任务注册/启停/卸载
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File D:\AIWorkflow\tools\h3_watchdog_task.ps1 install
# 动作：install / start / stop / uninstall / status / run
# 说明：走 schtasks 注册（普通用户权限即可，不需要管理员）；任务在「用户已登录」的会话里跑，
#       这样桌面通知才能弹到当前屏幕上。
param(
    [ValidateSet('install', 'start', 'stop', 'uninstall', 'status', 'run')]
    [string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'

$TaskName = 'H3_ComfyUI_Watchdog'
$Python   = 'C:\Users\若水\AppData\Local\Programs\Python\Python312\python.exe'
$Script   = 'D:\AIWorkflow\tools\h3_watchdog.py'
$WorkDir  = 'D:\AIWorkflow\tools'
$StatusFile = 'D:\AIWorkflow\tools\watch_status.json'
$UserSid   = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value

function Test-Task { return [bool](schtasks /query /tn $TaskName 2>$null) }

switch ($Action) {
    'install' {
        if (-not (Test-Path -LiteralPath $Python)) { throw "找不到 python: $Python" }
        if (-not (Test-Path -LiteralPath $Script)) { throw "找不到脚本: $Script" }

        $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>H3 产线（ComfyUI 8189）停摆监测：每 5 分钟只读检查产出/API/进程/GPU，停摆只告警一次</Description>
    <URI>\$TaskName</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>$UserSid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <RestartOnFailure><Count>2</Count><Interval>PT5M</Interval></RestartOnFailure>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
  </Settings>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>$((Get-Date).ToString('yyyy-MM-ddTHH:mm:00'))</StartBoundary>
      <Enabled>true</Enabled>
      <Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$UserSid</UserId>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>$Python</Command>
      <Arguments>"$Script" --quiet</Arguments>
      <WorkingDirectory>$WorkDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
        $xmlPath = Join-Path $env:TEMP 'h3_watchdog_task.xml'
        [System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)
        $ErrorActionPreference = 'Continue'
        $out = schtasks /create /tn $TaskName /xml $xmlPath /f 2>&1 | Out-String
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($code -ne 0) { throw "注册失败：$out" }
        Write-Host '[OK] 已注册计划任务' $TaskName '（每 5 分钟 + 登录时触发）'
        schtasks /query /tn $TaskName /fo list /v 2>&1 |
            Select-String -Pattern 'Status|Next Run Time|Repeat: Every|Task To Run' |
            ForEach-Object { $_.Line.Trim() }
    }
    'start' {
        if (-not (Test-Task)) { throw '任务不存在，请先执行 install' }
        schtasks /change /tn $TaskName /enable | Out-Null
        schtasks /run /tn $TaskName | Out-Null
        Write-Host '[OK] 已启用并立即触发一次' $TaskName
    }
    'stop' {
        if (-not (Test-Task)) { throw '任务不存在' }
        schtasks /end /tn $TaskName 2>$null | Out-Null
        schtasks /change /tn $TaskName /disable | Out-Null
        Write-Host '[OK] 已停止并停用' $TaskName '（恢复用 start）'
    }
    'uninstall' {
        if (Test-Task) {
            schtasks /delete /tn $TaskName /f | Out-Null
            Write-Host '[OK] 已卸载' $TaskName
        } else {
            Write-Host '[--]' $TaskName '本来就不存在'
        }
    }
    'run' {
        if (-not (Test-Task)) { throw '任务不存在，请先执行 install' }
        schtasks /run /tn $TaskName | Out-Null
        Start-Sleep -Seconds 2
        Write-Host '[OK] 已手动触发一次，看 watch_status.json'
    }
    'status' {
        if (-not (Test-Task)) { Write-Host '[--] 未注册'; break }
        schtasks /query /tn $TaskName /fo list /v 2>&1 |
            Select-String -Pattern 'TaskName|Status|Last Run Time|Last Result|Next Run Time|Repeat: Every' |
            ForEach-Object { $_.Line.Trim() }
        if (Test-Path -LiteralPath $StatusFile) {
            Write-Host '--- 最近一次监测结果 ---'
            $s = Get-Content -LiteralPath $StatusFile -Raw -Encoding utf8 | ConvertFrom-Json
            [pscustomobject]@{
                状态     = "$($s.state) / $($s.state_cn)"
                时间     = $s.updated_at
                理由     = $s.reason
                最后产出 = "$($s.last_output_file) @ $($s.last_output_time)"
                告警次数 = $s.counters.alerts
            } | Format-List
        }
    }
}
