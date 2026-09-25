@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONFAULTHANDLER=1
cd /d "%~dp0"

echo.
echo ============================================================
echo    Research layer  -  Step C : factor diagnostics
echo ============================================================
echo.
echo   IC, Rank IC, ICIR, IC decay, decile monotonicity.
echo.
echo   The signal panel is cached from the previous run, so this
echo   should take about a minute rather than fifteen.
echo.
echo   All output is also written to output\factor_log.txt so
echo   nothing is lost if the window closes or the script crashes.
echo.

if not exist "data\ashare.db" (
  echo [ERROR] Database not found. Run 02_build_database.bat first.
  pause
  exit /b 1
)
if not exist "output" mkdir "output"

set "RUN="
if exist ".venv\Scripts\python.exe" set "RUN=.venv\Scripts\python.exe"
if not defined RUN (
  py -3 --version >nul 2>&1
  if !errorlevel! equ 0 set "RUN=py -3"
)
if not defined RUN (
  python --version >nul 2>&1
  if !errorlevel! equ 0 set "RUN=python"
)
if not defined RUN (
  echo [ERROR] Python not found.
  pause
  exit /b 1
)

echo Using: !RUN!
echo.
!RUN! -u "research\factor_eval.py" %* > "output\factor_log.txt" 2>&1
set "RC=!errorlevel!"

type "output\factor_log.txt"

echo.
echo ============================================================
if "!RC!"=="0" (
  echo  Done. Send results\factor_eval.json to Claude.
) else (
  echo  Exit code !RC! -- it failed.
  echo  Send output\factor_log.txt to Claude; the traceback is in it.
)
echo ============================================================
pause
