@echo off
chcp 65001 >nul
title agent-engine
rem agent pipeline engine entry - uses PowerShell 7 via run-ps1.bat
call "%~dp0launchers\run-ps1.bat" "%~dp0LocalAI.ps1" %*
exit /b %ERRORLEVEL%
