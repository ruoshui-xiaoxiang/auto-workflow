@echo off
chcp 65001 >nul
title auto-workflow WebUI
rem One-click launcher, idempotent (PowerShell 7 preferred for health checks).
rem   Path 1: server already healthy on 8787 -> open the page and exit
rem   Path 2: not running -> start webui.py, poll /health

set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python.exe"
set "URL=http://127.0.0.1:8787"
set "PSCMD=E:\LocalAI\launchers\run-pwsh-cmd.bat"
set "HEALTH=try { Invoke-RestMethod http://127.0.0.1:8787/health -TimeoutSec 1 | Out-Null; exit 0 } catch { exit 1 }"

rem --- Path 1: already running -> open the page ---
call "%PSCMD%" "%HEALTH%"
if not errorlevel 1 (
  echo WebUI already running - opening the page.
  start "" "%URL%"
  exit /b 0
)

rem --- Path 2: cold start ---
start "" /min "%PY%" "%~dp0webui.py"
for /l %%i in (1,1,30) do (
  call "%PSCMD%" "%HEALTH%"
  if not errorlevel 1 goto webui_ready
  ping -n 2 127.0.0.1 >nul
)
echo [ERROR] auto-workflow WebUI did not start on port 8787.
echo         Check the minimized console window for the error message.
pause
exit /b 1

:webui_ready
echo auto-workflow WebUI ready. Browser should have opened.
ping -n 3 127.0.0.1 >nul
exit /b 0
