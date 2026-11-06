@echo off
chcp 936 >nul
rem 本地工作流规范手册 · 副本刷新
rem 用法：双击运行；或命令行 run 后跟 check / build
cd /d "%~dp0"

if /i "%~1"=="check" goto do_check
if /i "%~1"=="build" goto do_build

echo ============================================
echo  本地工作流规范手册 - 维护菜单
echo ============================================
echo   [1] 只检查   哪些副本已落后于真源（不写任何文件）
echo   [2] 刷新     把落后的副本按真源重新覆盖
echo   [3] 完整重建 清空重建全部目录与来源清单
echo   [4] 退出
echo.
choice /c 1234 /n /m "  请选择: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto do_rebuild
if errorlevel 2 goto do_build
goto do_check

:do_check
echo.
echo --- 正在比对真源与副本（只读）---
python -W ignore 99_维护\build_manual.py --check
call :do_tables
goto end

:do_build
echo.
echo --- 正在按真源刷新副本 ---
python -W ignore 99_维护\build_manual.py
echo.
echo 来源清单已更新： 99_来源清单\MANIFEST.md
call :do_tables
goto end

:do_rebuild
echo.
echo !!! 完整重建会先删除下列**纯副本**目录再按真源重拷 !!!
echo     00_读我 与 20_通用规范层 与 30_项目层 与 99_维护 是新写的文档与脚本，
echo     **不在删除名单内、不会被清**。真源文件不受影响（本脚本从不写源目录）。
choice /c YN /n /m "  确认删除并重建? (Y/N): "
if errorlevel 2 goto end
for %%D in (01_总手册 02_H3提示词规则 03_使用规范与关口流程 04_生产流水线Skill_事实源 04b_生产流水线Skill_脱敏可分发版 05_引擎与工作流参数 06_本地AI环境与启动 07_LoRA训练规范 08_Qoder记忆_现行约定 08b_公共记忆_跨工具项目摘要 09_项目执行与审计 10_机检与工具脚本_只读参考 99_来源清单) do if exist "%%D" rd /s /q "%%D"
python -W ignore 99_维护\build_manual.py
call :do_tables
goto end

:do_tables
echo.
echo --- 正在自检自写文档的表格列数（只读）---
python -W ignore 99_维护\check_tables.py
goto :eof

:end
echo.
pause
