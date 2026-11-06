@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo   素材入库 — 把散落的无音视频/图片/音频收进 E:\图像影音资源池
echo   （只复制、不删源；目标已存在同名时自动加 __1 后缀）
echo ==========================================================
echo.
echo   [1] 预览清单（不复制，安全）
echo   [2] 执行复制（写 MANIFEST + sha256 校验）
echo   [3] 删源（只删下面 4 个范围里已被校验过副本的文件）
echo        D:\AIWorkflow\ComfyUI_H3\output     引擎暂存
echo        D:\AIWorkflow\tmp\staging           临时中间产物
echo        D:\AIWorkflow\tmp\frames            抽帧
echo        C:\Users\若水\Desktop               桌面散落/成品交片
echo       ^(海螺 App 的 renders 与 output_files 不在范围内，保留^)
echo   [0] 退出
echo.
set /p c=请选择 (0/1/2/3):
echo.
if "%c%"=="1" py -3.12 pool_reorg.py dry-run
if "%c%"=="2" py -3.12 pool_reorg.py ingest
if "%c%"=="3" (
    echo   删源前会逐文件用 sha256 复核池内副本，副本缺失/不符的一律不删。
    set /p y=   确认执行? (y/N):
    if /i "%y%"=="y" py -3.12 pool_reorg.py purge --root "D:\AIWorkflow\ComfyUI_H3\output" --root "D:\AIWorkflow\tmp\staging" --root "D:\AIWorkflow\tmp\frames" --root "C:\Users\若水\Desktop"
)
echo.
pause
