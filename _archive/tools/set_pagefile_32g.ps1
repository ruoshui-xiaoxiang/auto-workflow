$ErrorActionPreference = 'Stop'
$log = 'D:\AIWorkflow\logs\pagefile_set_result.txt'
try {
  $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management'
  Set-ItemProperty -Path $key -Name 'PagingFiles' -Value @('D:\pagefile.sys 32768 32768') -Type MultiString
  $v = (Get-ItemProperty -Path $key -Name 'PagingFiles').PagingFiles
  "REG=" + ($v -join '|') | Set-Content -LiteralPath $log -Encoding UTF8
  Add-Content -LiteralPath $log -Value 'OK'
} catch {
  $_.Exception.Message | Set-Content -LiteralPath $log -Encoding UTF8
  Add-Content -LiteralPath $log -Value 'FAIL'
}