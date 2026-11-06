@echo off
chcp 65001 >nul
cd /d D:\AIWorkflow\tools
echo ================ 统一备份（全量快照，每类目留最近 5 份）================
echo.
echo 备份内容：规则手册 / Qoder 记忆 / 引擎配置与工作流 / 自产脚本
echo 落点：E:\_统一备份\^\
echo 每个类目保留最近 5 份快照，更旧的自动清。
echo 不备份 E:\密钥文件（明文凭证多一份就多一次泄露面）。
echo.
py backup_now.py
echo.
echo 想只看"备份里缺什么／哪份落后于活区"而不写任何东西，跑这个：
echo     py D:\AIWorkflow\tools\backup_now.py --check
echo 验收标准＝「缺 0 且 陈旧 0」两个数一起看（09-28 改的口径：旧版只数"缺"，
echo "文件在但内容不等于活区"被静默丢掉，所以旧版那个 0 是假绿 —— 手册冲突表 C80）。
echo.
pause
