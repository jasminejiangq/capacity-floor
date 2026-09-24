@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Diagnose
echo ============================================================
echo.
echo   Answers three open questions before the full build:
echo     - why the finance table has 11500 rows
echo     - the real column names of the dividend feed
echo     - whether historical industry data is available
echo     - whether market cap can be derived from existing data
echo     - how fast parallel download runs
echo.
echo   Takes about 3-6 minutes. Nothing is downloaded in bulk.
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
  echo [ERROR] Python not found. Run 01_data_check.bat first.
  echo.
  pause
  exit /b 1
)

!RUN! "code\diagnose.py"

echo.
echo ============================================================
echo  Send output\diagnose json file back to Claude.
echo ============================================================
echo.
pause
