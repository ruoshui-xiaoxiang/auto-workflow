@echo off
rem ============================================================
rem ComfyUI launcher (ASCII only - cmd.exe mis-parses batch files
rem containing multi-byte characters).
rem
rem Logic:
rem   1. If ComfyUI already serves on :8188, just open the page.
rem   2. Otherwise unload tier 1 (gpt-oss-20b) if it holds the GPU.
rem      Tier 1 takes ~13.2 GB of the 16 GB card, so FLUX checkpoints
rem      cannot load while it is resident.
rem   3. Start the server detached, poll until it listens, open browser.
rem
rem Log: E:\LocalAI\logs\comfyui.log
rem To bring tier 1 back after rendering: run E:\LocalAI\LocalAI.bat and pick menu 1.
rem ============================================================
setlocal
set "ROOT=E:\LocalAI\ComfyUI_windows_portable"
set "PORT=8188"
set "LOG=D:\AIWorkflow\logs\comfyui.log"

powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/system_stats' -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process 'http://127.0.0.1:%PORT%'; exit 10 } catch { exit 11 }"
if "%errorlevel%"=="10" (
  echo ComfyUI already running - opened the page.
  exit /b
)

REM --- unload tier 1 if it is holding the card ---
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue; if ($p) { $p.OwningProcess | Select-Object -First 1 }"`) do set "TIER1PID=%%I"
if defined TIER1PID (
  echo Tier 1 is running on the GPU, PID %TIER1PID% - stopping it so FLUX can load.
  echo Run E:\LocalAI\LocalAI.bat (menu 1) when you are done rendering.
  taskkill /PID %TIER1PID% /F >nul 2>&1
  timeout /t 4 /nobreak >nul
)

echo Starting ComfyUI, log: %LOG%
cd /d "%ROOT%"
start "" /min "E:\LocalAI\launchers\comfyui-watch.bat"
start "ComfyUI-Server" /min cmd /c ".\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --output-directory D:\AIWorkflow\tmp\staging > %LOG% 2>&1"
exit /b
