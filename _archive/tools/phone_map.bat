@echo off
chcp 65001 >nul
setlocal
set "ADB=C:\Users\若水\AppData\Local\Microsoft\WinGet\Packages\Genymobile.scrcpy_Microsoft.Winget.Source_8wekyb3d8bbwe\scrcpy-win64-v5.0.1\adb.exe"
set "SCRCPY=C:\Users\若水\AppData\Local\Microsoft\WinGet\Packages\Genymobile.scrcpy_Microsoft.Winget.Source_8wekyb3d8bbwe\scrcpy-win64-v5.0.1\scrcpy.exe"

for /f "tokens=3" %%a in ('"%ADB%" mdns services 2^>nul ^| findstr "_adb-tls-connect"') do set "ADDR=%%a"
if "%ADDR%"=="" (
  echo 没有发现无线调试服务。
  echo 请在手机上打开「无线调试」，并确保手机和电脑在同一 Wi-Fi。
  pause
  exit /b 1
)

echo 连接 %ADDR% ...
"%ADB%" connect %ADDR%
"%ADB%" -s %ADDR% reverse tcp:8777 tcp:8777
"%ADB%" -s %ADDR% shell am start -a android.intent.action.VIEW -d "http://127.0.0.1:8777/map3d" >nul

start "" "%SCRCPY%" -s %ADDR% --max-size=1920 --video-bit-rate=8M --max-fps=60 --stay-awake --no-audio --window-title="Fanxing Phone (Wi-Fi)"
endlocal
