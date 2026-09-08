@echo off
setlocal
title Triad Analysis Workbench - Start
cd /d "%~dp0"

echo ============================================
echo   Triad Analysis Workbench - starting...
echo   (frontend http://127.0.0.1:3000  +  backend http://127.0.0.1:8000)
echo ============================================
echo.

REM Stop leftover processes first so stale code is never reused (edit code -> double-click again)
echo [1/2] Cleaning up any previous instances...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local-workbench.ps1" -Action stop >nul 2>&1

echo [2/2] Starting fresh instances...
call "%~dp0start.bat"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Startup failed. Review the message above and logs in .runtime.
  pause
)

exit /b %EXIT_CODE%
