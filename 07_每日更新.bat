@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo.
echo ============================================================
echo    Daily Update  -  add only the missing days
echo ============================================================
echo.
echo   Adds only the trading days missing since the last run.
echo   Does NOT delete any history. Usually 1-3 minutes.
echo   Run it after 15:30 on a trading day.
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
!RUN! "code\update_db.py"
