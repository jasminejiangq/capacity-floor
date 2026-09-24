@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    Research layer  -  Step A : run the test suite
echo ============================================================
echo.
echo   49 tests. No database needed. Takes a few seconds.
echo   If anything fails here, do not bother running the rest.
echo.

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

!RUN! "tests\run_tests.py"
echo.
pause
