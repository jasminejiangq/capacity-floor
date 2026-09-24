@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    Research layer  -  Step C : factor diagnostics
echo ============================================================
echo.
echo   IC, Rank IC, ICIR, IC decay, decile monotonicity.
echo   These are the first three questions in any quant interview
echo   and the backtest cannot answer them.
echo.
echo   About 15 minutes the first time. Afterwards the signal
echo   panel is cached and it takes about a minute.
echo.
echo   Produces: results\factor_eval.json  and  .png
echo.

if not exist "data\ashare.db" (
  echo [ERROR] Database not found. Run 02_build_database.bat first.
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

!RUN! "research\factor_eval.py" %*

echo.
echo ============================================================
echo  Send results\factor_eval.json to Claude.
echo ============================================================
pause
