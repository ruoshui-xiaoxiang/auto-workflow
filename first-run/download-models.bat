@echo off
chcp 65001 >nul
echo ========================================
echo   模型下载脚本
echo ========================================
echo.
echo 此脚本将下载 FLUX.1-dev 模型（约 23GB）
echo 确保有足够的磁盘空间和稳定的网络连接
echo.
pause

set APP_DIR=%~dp0..
set MODEL_DIR=%APP_DIR%\ComfyUI_windows_portable\ComfyUI\models\checkpoints

if not exist "%MODEL_DIR%" (
    echo 错误：ComfyUI 未安装，请先运行 setup.bat
    pause
    exit /b 1
)

echo 下载 FLUX.1-dev...
powershell -Command "& {Invoke-WebRequest -Uri 'https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors' -OutFile '%MODEL_DIR%\flux1-dev.safetensors'}"

if errorlevel 1 (
    echo 下载失败，请手动下载
    echo 下载地址：https://huggingface.co/black-forest-labs/FLUX.1-dev
    pause
    exit /b 1
)

echo.
echo 模型已下载到：%MODEL_DIR%\flux1-dev.safetensors
echo.
pause
