# 存档仓健康检查：工作区是否干净 / 本地 HEAD 是否与远端一致 / 提交身份是否正常 / 最近是否推过
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File D:\AIWorkflow\tools\archive_check.ps1
$ErrorActionPreference = "Continue"
$Repo = "D:\AIWorkflow\engine"
$Git = { param($a) git -c http.proxy= -c https.proxy= @a }
Set-Location $Repo

$fail = 0
function Check($name, $ok, $detail) {
    if ($ok) { Write-Host "[PASS] $name $detail" } else { Write-Host "[FAIL] $name $detail"; $script:fail++ }
}

# 1. 工作区干净（_archive 已同步）
$status = & $Git @("status", "--porcelain")
Check "工作区干净" ([string]::IsNullOrWhiteSpace($status)) ("未提交条目：" + (($status | Measure-Object -Line).Lines))

# 2. 本地 HEAD == 远端 main
$local = (& $Git @("rev-parse", "HEAD")).Trim()
$remote = ((& $Git @("ls-remote", "origin", "refs/heads/main")) -split "\s+")[0]
Check "HEAD 与远端一致" ($local -eq $remote) ("local=" + $local.Substring(0,8) + " remote=" + $remote.Substring(0,8))

# 3. 提交身份未被 agent 改写
$id = & $Git @("log", "-1", "--format=%an <%ae> | %cn <%ce>")
Check "提交身份正常" ($id -notmatch "trae-solo-agent") $id

# 4. 最近提交时间
$ts = & $Git @("log", "-1", "--format=%ct")
$age = [math]::Round((([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$ts) / 3600), 1)
Check "最近 24h 内有推送" ($age -le 24) ("距今 " + $age + " 小时")

# 5. 仓库完整性
$fsck = & $Git @("fsck", "--full", "--no-progress") 2>&1
Check "git fsck 无错误" (-not ($fsck -match "error|fatal")) (($fsck | Select-Object -First 1) -join "")

if ($fail -gt 0) { Write-Host "结果：$fail 项异常"; exit 1 }
Write-Host "结果：全部通过"
exit 0
