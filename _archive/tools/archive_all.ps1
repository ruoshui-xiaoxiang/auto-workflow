# 存档并推送：同步镜像 -> 暂存 -> 提交 -> 推送到公开仓 ruoshui-xiaoxiang/auto-workflow
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File D:\AIWorkflow\tools\archive_all.ps1
param(
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$Repo = "D:\AIWorkflow\engine"
$Sync = "D:\AIWorkflow\tools\archive_sync.py"

# 提交身份：不用全局配置（全局是手机号邮箱），也不用 Trae 注入的 agent 身份
$env:GIT_AUTHOR_NAME = "ruoshui-xiaoxiang"
$env:GIT_AUTHOR_EMAIL = "ruoshui-xiaoxiang@users.noreply.github.com"
$env:GIT_COMMITTER_NAME = "ruoshui-xiaoxiang"
$env:GIT_COMMITTER_EMAIL = "ruoshui-xiaoxiang@users.noreply.github.com"

Write-Host "[1/4] 同步 _archive 镜像"
python $Sync
if ($LASTEXITCODE -ne 0) { throw "archive_sync 失败" }

Set-Location $Repo
Write-Host "[2/4] 暂存变更"
git -c http.proxy= -c https.proxy= add -A
$staged = git -c http.proxy= -c https.proxy= diff --cached --name-only
if (-not $staged) {
    Write-Host "无变更，跳过提交"
    exit 0
}

if (-not $Message) {
    $Message = "存档快照 $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

Write-Host "[3/4] 提交"
git -c http.proxy= -c https.proxy= commit -m $Message
if ($LASTEXITCODE -ne 0) { throw "commit 失败（若被 pre-commit 拦截，请按提示处理）" }

Write-Host "[4/4] 推送"
$ProxyArgs = @("-c", "http.proxy=", "-c", "https.proxy=")
$Token = $env:GITHUB_TOKEN
if (-not $Token) { $Token = (& gh auth token 2>$null) }
if (-not $Token) { throw "缺 token：请 gh auth login 或设置 GITHUB_TOKEN" }
$Basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$Token"))
$env:GIT_TERMINAL_PROMPT = "0"
$env:GIT_HTTP_LOW_SPEED_LIMIT = "2000"
$env:GIT_HTTP_LOW_SPEED_TIME = "30"
git @ProxyArgs -c credential.helper= -c http.extraHeader="Authorization: Basic $Basic" push origin main
if ($LASTEXITCODE -ne 0) { throw "push 失败：检查网络/代理与 GITHUB_TOKEN" }

Write-Host "完成：$(git -c http.proxy= -c https.proxy= log -1 --format='%h %s')"
