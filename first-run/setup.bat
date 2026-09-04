@echo off
chcp 65001 >nul
title auto-workflow 首次配置
echo ========================================
echo   auto-workflow 首次配置向导
echo ========================================
echo.

set APP_DIR=%~dp0..
cd /d "%APP_DIR%"

echo [1/3] 检查 Python 环境...
if not exist "python\python.exe" (
    echo 未找到 Python，正在下载嵌入式 Python 3.12...
    if not exist "first-run\fetch-python.bat" (
        echo 错误：缺少 fetch-python.bat
        pause
        exit /b 1
    )
    call "first-run\fetch-python.bat"
    if errorlevel 1 (
        echo Python 下载失败
        pause
        exit /b 1
    )
)
echo Python 已就绪：python\python.exe
echo.

echo [2/3] 检查 ComfyUI...
set COMFYUI_DIR=%APP_DIR%\ComfyUI_windows_portable
if not exist "%COMFYUI_DIR%" (
    echo 正在下载 ComfyUI 便携版（约 2GB，请耐心等待）...
    python\python.exe -c "import urllib.request; urllib.request.urlretrieve('https://github.com/comfyanonymous/ComfyUI/releases/download/latest/ComfyUI_windows_portable_nvidia.7z', 'comfyui_download.7z')"
    if errorlevel 1 (
        echo ComfyUI 下载失败，请手动下载并解压到：%COMFYUI_DIR%
        echo 下载地址：https://github.com/comfyanonymous/ComfyUI/releases
        pause
        exit /b 1
    )
    echo 解压中...
    if exist "C:\Program Files\7-Zip\7z.exe" (
        "C:\Program Files\7-Zip\7z.exe" x comfyui_download.7z -o"%APP_DIR%" -y
    ) else (
        echo 未找到 7-Zip，请手动解压 comfyui_download.7z
        pause
        exit /b 1
    )
    del comfyui_download.7z
)
echo ComfyUI 已就绪
echo.

echo [3/3] 检查模型文件...
set MODEL_DIR=%COMFYUI_DIR%\ComfyUI\models\checkpoints
if not exist "%MODEL_DIR%\*.safetensors" (
    echo 未检测到模型文件。
    echo.
    echo 请手动下载 FLUX 模型并放入：%MODEL_DIR%
    echo 推荐模型：
    echo   - FLUX.1-dev (https://huggingface.co/black-forest-labs/FLUX.1-dev)
    echo   - 或其他兼容的 checkpoint
    echo.
    echo 模型下载后可运行 first-run\download-models.bat 自动放置
    pause
)
echo.

echo ========================================
echo   配置完成！
echo   双击 start-webui.bat 启动
echo ========================================
pause
