@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Step 3 : Backtest
echo    Strategy: Quality + Dividend + Low Volatility
echo ============================================================
echo.
echo   Runs entirely offline from the local database.
echo   Nothing is downloaded. Takes roughly 10-40 minutes.
echo.
echo   Produces:
echo     output\backtest report (HTML, opens automatically)
echo     output\equity curve (CSV)
echo     output\backtest result (JSON - send this to Claude)
echo.

if not exist "data\ashare.db" (
  echo [ERROR] Database not found.
  echo         Run 02_build_database.bat first.
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
  echo [ERROR] Python not found. Run 01_data_check.bat first.
  echo.
  pause
  exit /b 1
)

!RUN! "code\backtest.py"

echo.
echo ============================================================
echo  Open the "output" folder and send the .json file to Claude.
echo ============================================================
echo.
pause
