@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Dividend Pre-flight Check
echo ============================================================
echo.
echo   Takes 2-4 minutes. Run this BEFORE the full build.
echo   It verifies the dividend fix works on the live feed,
echo   so you don't wait 3 hours to find out it doesn't.
echo.
echo   Do NOT click inside this window. If it looks frozen,
echo   press Enter or Esc.
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

!RUN! "code\precheck_div.py"
