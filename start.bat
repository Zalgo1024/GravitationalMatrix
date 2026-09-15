@echo off
setlocal
title 引力矩阵工作台 - Start
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local-workbench.ps1" -Action start
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Startup failed. Review the message above and logs in .runtime.
  pause
)

exit /b %EXIT_CODE%
