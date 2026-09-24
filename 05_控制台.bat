@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Control Panel
echo ============================================================
echo.
echo   Opens a local web page where you can:
echo     - change capital, rebalance frequency, holdings, factors
echo     - see the cost impact instantly, before running anything
echo     - run the backtest / today's screen with one click
echo.
echo   Runs on 127.0.0.1 only. Nothing is uploaded. No internet.
echo   Close this black window when you are done.
echo.

set "RUN="
if exist ".venv\Scripts\python.exe" (
  set "RUN=.venv\Scripts\python.exe"
) else (
  py -3 --version >nul 2>&1
  if !errorlevel! equ 0 ( set "RUN=py -3" )
)
if not defined RUN (
  python --version >nul 2>&1
  if !errorlevel! equ 0 ( set "RUN=python" )
)
if not defined RUN (
  echo [ERROR] Python not found.
  echo.
  pause
  exit /b 1
)

!RUN! "code\panel.py"
pause
