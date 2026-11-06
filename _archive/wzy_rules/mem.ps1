$os = Get-CimInstance Win32_OperatingSystem
"{0:N1} GB total / {1:N1} GB free / {2:N1} GB commit free" -f ($os.TotalVisibleMemorySize/1MB), ($os.FreePhysicalMemory/1MB), ($os.FreeSpaceInPagingFiles/1MB)
Get-Process | Sort-Object WS -Descending | Select-Object -First 10 Name, @{n='GB';e={[math]::Round($_.WS/1GB,2)}}, Id | Format-Table -AutoSize | Out-String
