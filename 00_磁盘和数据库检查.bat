@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Disk ^& Database Health Check
echo ============================================================
echo.
echo   Read-only. Nothing is deleted, nothing is downloaded.
echo   Takes about 3-8 minutes (it measures folder sizes for real).
echo.
echo   IMPORTANT: do NOT click inside this window while it runs.
echo   Windows "quick edit" mode freezes the program when you
echo   select text. If it looks stuck, press Enter or Esc here.
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

!RUN! "code\disk_check.py"

echo.
echo ============================================================
echo  Open the "output" folder and send the .json file to Claude.
echo ============================================================
echo.
pause
