@echo off
setlocal
title 引力矩阵 - 体检 (core regression check)
cd /d "%~dp0"

echo ============================================
echo   引力矩阵 - 体检
echo   Run this after changing code to confirm
echo   core features are not broken.
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify-all.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [PASS] Core features OK. Safe to deliver.
) else (
  echo [FAIL] Core features affected. Fix before delivering.
)
echo.
pause
exit /b %EXIT_CODE%
