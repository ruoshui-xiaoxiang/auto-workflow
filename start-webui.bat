@echo off
chcp 65001 >nul
title auto-workflow WebUI
rem Start the local web console: webui.py server -> health poll -> browser
rem Port 8787; shows error and pauses if port is taken or Python is missing.

set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python.exe"

start "" /min "%PY%" "%~dp0webui.py"
for /l %%i in (1,1,30) do (
  powershell.exe -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:8787/health -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"
  if not errorlevel 1 goto webui_ready
  timeout /t 1 /nobreak >nul
)
echo [ERROR] auto-workflow WebUI did not start on port 8787.
echo         Port busy or Python missing. Check the console window.
pause
exit /b 1

:webui_ready
echo auto-workflow WebUI ready. Browser should have opened.
timeout /t 2 /nobreak >nul
exit /b 0