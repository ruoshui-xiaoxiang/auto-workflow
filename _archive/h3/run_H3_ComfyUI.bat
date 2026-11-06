@echo off
chcp 65001 >nul
cd /d D:\AIWorkflow\ComfyUI_H3
echo ============================================
echo   MiniMax H3 ComfyUI  (port 8189)
echo   GUI: http://127.0.0.1:8189
echo   首次出片会慢(JIT编译+模型载入), 第2条起变快
echo ============================================
REM ---- 2026-10-15 通用模式: 无sage + ck-attention + reserve 6 (用户确认可用于生产; 旧命令备份 .bak-20261015) ----
REM ---- 2026-09-17 added: keep a VRAM reserve for this 16GB card ----
REM   The H3 model is about 20GB, so a 16GB card is already at the edge.
REM   Measured: without a reserve, 3 jobs run fine and the 4th one dies with
REM   "torch.AcceleratorError: CUDA error: out of memory", which also wedges the
REM   server (queue cannot be cleared, /system_stats returns 500, restart needed).
REM   The node pack README validated exactly this "2 GiB reserve" config on a
REM   16GB card: 15/15 prompts passed.
REM   Original file backed up as run_H3_ComfyUI.bat.bak-*
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build --use-ck-attention --port 8189 --output-directory "D:\AIWorkflow\ComfyUI_H3\output" --reserve-vram 6.0
pause
