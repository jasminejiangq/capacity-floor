@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    Research layer  -  Step D : statistical honesty
echo ============================================================
echo.
echo   Grades the backtest you already ran: haircut Sharpe,
echo   Deflated Sharpe Ratio, and (with --pbo) the Probability
echo   of Backtest Overfitting.
echo.
echo   Seconds without --pbo. About 15 minutes with it, and it
echo   reuses the cached signal panel from step C.
echo.
echo   Produces: results\stat_honesty.json
echo.

if not exist "output\回测结果.json" (
  echo [ERROR] No backtest result found. Run 04_backtest.bat first.
  pause & exit /b 1
)

set "RUN="
if exist ".venv\Scripts\python.exe" ( set "RUN=.venv\Scripts\python.exe" ) else (
  py -3 --version >nul 2>&1
  if !errorlevel! equ 0 ( set "RUN=py -3" )
)
if not defined RUN (
  python --version >nul 2>&1
  if !errorlevel! equ 0 ( set "RUN=python" )
)
if not defined RUN ( echo [ERROR] Python not found. & pause & exit /b 1 )

!RUN! "research\stat_honesty.py" %*

echo.
echo ============================================================
echo  Send results\stat_honesty.json to Claude.
echo ============================================================
pause
