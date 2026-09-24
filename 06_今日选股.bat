@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo.
echo ============================================================
echo    Today's Screen  -  what the rules pick TODAY for YOUR capital
echo ============================================================
echo.
echo   Uses your capital from config.json, not the backtest's.
echo   Takes about 1 minute.
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
!RUN! "code\pick.py"
