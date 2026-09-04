@echo off
chcp 65001 >nul
echo 正在下载 Python 3.12 嵌入式版本...

set PYTHON_URL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-embed-amd64.zip
set PYTHON_ZIP=python-embed.zip
set PYTHON_DIR=%~dp0..\python

if exist "%PYTHON_DIR%\python.exe" (
    echo Python 已存在，跳过下载
    exit /b 0
)

powershell -Command "& {Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_ZIP%'}"
if errorlevel 1 (
    echo 下载失败
    exit /b 1
)

echo 解压中...
powershell -Command "& {Expand-Archive -Path '%PYTHON_ZIP%' -DestinationPath '%PYTHON_DIR%' -Force}"
del %PYTHON_ZIP%

echo 配置 pip...
cd /d "%PYTHON_DIR%"
python.exe -m ensurepip --upgrade 2>nul
python.exe -m pip install --upgrade pip

echo 安装依赖...
python.exe -m pip install pyyaml

echo Python 3.12 已安装到：%PYTHON_DIR%
