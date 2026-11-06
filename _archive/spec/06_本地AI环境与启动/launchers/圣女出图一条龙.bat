@echo off
chcp 65001 >nul
title 圣女出图一条龙
cd /d "D:\AIWorkflow\engine"
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if not errorlevel 1 (
  echo [提示] 检测到有 python 进程正在运行（可能是 ComfyUI 或另一个批次）。
  echo 同时运行会抢显存，可能变慢或失败。
  choice /c YN /m "仍要继续吗? (Y=继续, N=取消)"
  if errorlevel 2 exit /b
)
echo.
echo 出图：FLUX 出立绘变体 -> 拼总览图 -> 发飞书（ComfyUI 引擎）
echo 改场景/提示词/张数：编辑 workflows\character_sheet.yaml，或用 --set 覆盖
echo 交付根：E:\图像影音资源池\圣女\批次
echo.
set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python.exe"
"%PY%" run.py character_sheet --output-root "E:\图像影音资源池\圣女\批次"
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (
  echo [完成] 立绘已生成并拼图；总览图已发飞书（send_feishu=true 时）。
) else (
  echo [失败] 错误码 %RC%，请查看上方日志。
)
pause
