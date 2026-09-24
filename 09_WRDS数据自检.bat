@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo.
echo ============================================================
echo    WRDS Data Availability Check
echo ============================================================
echo.
echo   Verifies THREE things before you write any analysis code:
echo     1. CRSP delisting returns (survivorship bias)
echo     2. Compustat rdq  (point-in-time anchor)
echo     3. CCM link table
echo.
echo   You will get a Duo push on your phone. Approve it.
echo   WARNING: never commit WRDS data to a public repo.
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
!RUN! -c "import wrds" 2>nul
if !errorlevel! neq 0 (
  echo Installing the wrds package...
  !RUN! -m pip install wrds
)
!RUN! "code\wrds_check.py"
