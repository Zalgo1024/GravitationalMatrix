@echo off
setlocal
title 引力矩阵运营后台 - Stop
cd /d "%~dp0"

echo Stopping the admin console (port 3001 only)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\admin-console.ps1" -Action stop
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo The shared backend (8000) and the workbench (3000) are left untouched.
echo Use stop.bat if you also want to stop those.
echo.
pause
exit /b %EXIT_CODE%
