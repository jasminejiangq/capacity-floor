@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    Research layer  -  Step B : capacity analysis
echo ============================================================
echo.
echo   This is the core result of the project.
echo.
echo   It runs the backtest ONCE with all costs switched off (to
echo   measure gross alpha and turnover), then re-runs it across a
echo   grid of account sizes with costs on, then compares the
echo   empirical curve against the closed-form bound.
echo.
echo   Roughly 60 minutes. Leave it running.
echo   Add  --quick  for a 6-point version (about 20 minutes).
echo.
echo   Produces: results\capacity.json  and  results\capacity.png
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

!RUN! "research\capacity.py" %*

echo.
echo ============================================================
echo  Send results\capacity.json to Claude.
echo ============================================================
pause
