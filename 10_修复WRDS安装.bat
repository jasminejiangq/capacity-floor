@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo.
echo ============================================================
echo    Fix WRDS environment  (no compiler needed)
echo ============================================================
echo.
echo   Does NOT install the official 'wrds' package.
echo   That package pins pandas^<2.3, which has no prebuilt
echo   wheel for Python 3.14, so pip tries to compile it and
echo   fails without Visual Studio C++ tools.
echo.
echo   Instead: installs ONE PostgreSQL driver, trying
echo     psycopg -^> psycopg2-binary -^> pg8000 (pure Python)
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
if not defined RUN ( echo [ERROR] Python not found. & pause & exit /b 1 )
!RUN! "code\fix_wrds_install.py"
