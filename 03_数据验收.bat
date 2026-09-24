@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Step 3 : Data Acceptance Check
echo ============================================================
echo.
echo   Read-only. Nothing is downloaded, nothing is changed.
echo   Takes about 2-5 minutes.
echo.
echo   Answers 6 questions the backtest depends on:
echo     1. Are the 57 "failed" stocks a real data gap?
echo     2. Can annual and interim dividends be summed?
echo     3. Any placeholder rows with no amount?
echo     4. Do the three yield definitions match known anchors?
echo     5. Any look-ahead (announcement before report date)?
echo     6. How many stocks can 2500 CNY actually buy?
echo.
echo   Do NOT click inside this window. If it looks frozen,
echo   press Enter or Esc.
echo.

if not exist "data\ashare.db" (
  echo [ERROR] Database not found. Run 02_build_database.bat first.
  echo.
  pause
  exit /b 1
)

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

!RUN! "code\audit_data.py"

echo.
echo ============================================================
echo  Send output\data acceptance result (.json) to Claude.
echo ============================================================
echo.
pause
