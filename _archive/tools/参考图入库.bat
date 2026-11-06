@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ===== 1/3 扫描 MiniMax Design output_files =====
py mmd_ingest.py scan
echo.

echo ===== 2/3 预演（dry-run，不真正复制）=====
py mmd_ingest.py ingest --dry-run
echo.

set /p ok=^> 确认入库？(y=复制到定妆目录 / n=退出 / s=复制到场景目录): 
if /i "%ok%"=="s" (
    py mmd_ingest.py ingest --role 场景
) else if /i "%ok%"=="y" (
    py mmd_ingest.py ingest
) else (
    echo 已取消，未做任何修改。
)
echo.
pause
