@echo off
rem Wait until ComfyUI serves on :8188, then open the browser once.
powershell -NoProfile -Command "for ($i=0; $i -lt 120; $i++) { try { Invoke-WebRequest -Uri 'http://127.0.0.1:8188/system_stats' -UseBasicParsing -TimeoutSec 3 | Out-Null; Start-Process 'http://127.0.0.1:8188'; exit 0 } catch { Start-Sleep -Seconds 3 } }"
