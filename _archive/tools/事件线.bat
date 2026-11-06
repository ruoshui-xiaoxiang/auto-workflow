@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo   事件线（L0）— 生成文档 / 一致性校验
echo   真源：E:\创作\无音项目\事件线\shots.yaml + state_ledger.yaml
echo ==========================================================
echo.
echo   [1] 生成桌面文档（分镜表与状态台账）
echo   [2] 跑一致性校验
echo   [3] 生成文档 + 校验（一条龙）
echo   [4] 修台账死链（古风 ledger/shots.csv，先 dry-run）
echo   [0] 退出
echo.
set /p c=请选择 (0/1/2/3/4):
echo.
if "%c%"=="1" py -3.12 gen_shots_doc.py
if "%c%"=="2" py -3.12 check_continuity.py
if "%c%"=="3" (
    py -3.12 gen_shots_doc.py
    echo.
    py -3.12 check_continuity.py
)
if "%c%"=="4" py -3.12 fix_ledger_paths.py --dry-run
echo.
pause
