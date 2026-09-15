@echo off
setlocal
title 引力力矩运营后台 - Start (independent)
cd /d "%~dp0"

echo ============================================
echo   引力力矩运营后台  -  independent start
echo   admin console : http://127.0.0.1:3001/admin-console/overview
echo   backend API   : http://127.0.0.1:8000  (shared)
echo   workbench     : http://127.0.0.1:3000  (NOT started here)
echo ============================================
echo.

REM Stop a leftover admin console first so stale code is never reused.
REM This only touches port 3001 - the workbench (3000) and backend (8000) stay put.
echo [1/2] Stopping any previous admin console instance...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\admin-console.ps1" -Action stop >nul 2>&1

echo [2/2] Starting admin console (starts the shared backend if it is down)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\admin-console.ps1" -Action start
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Admin console failed to start. Check the messages above and .runtime\admin-frontend-error.log
  pause
)

exit /b %EXIT_CODE%
