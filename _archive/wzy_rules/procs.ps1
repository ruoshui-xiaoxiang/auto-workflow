Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  ForEach-Object { "{0}`n  {1}" -f $_.ProcessId, $_.CommandLine }
