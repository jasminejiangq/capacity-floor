@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Step 1 : Data Health Check
echo    (This step does NOT pick stocks or trade anything.)
echo ============================================================
echo.

REM ---------- 1. locate a Python interpreter ----------
set "PY="
py -3 --version >nul 2>&1
if !errorlevel! equ 0 set "PY=py -3"

if not defined PY (
  python --version >nul 2>&1
  if !errorlevel! equ 0 set "PY=python"
)

if not defined PY (
  python3 --version >nul 2>&1
  if !errorlevel! equ 0 set "PY=python3"
)

if not defined PY (
  echo [ERROR] Python not found on this computer.
  echo.
  echo   Please install Python 3.11 or 3.12 from:
  echo     https://www.python.org/downloads/
  echo.
  echo   IMPORTANT: during installation, tick the checkbox
  echo     "Add python.exe to PATH"
  echo.
  echo   Then double-click this file again.
  echo.
  pause
  exit /b 1
)

echo Found Python: !PY!
!PY! --version
echo.

REM ---------- 2. private environment (first run only) ----------
set "RUN="
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment...
  echo This happens only on the first run and may take a minute.
  echo.
  !PY! -m venv .venv
)

if exist ".venv\Scripts\python.exe" (
  set "RUN=.venv\Scripts\python.exe"
  echo Using private environment: .venv
) else (
  set "RUN=!PY!"
  echo [WARN] Could not create private environment.
  echo        Falling back to the system Python.
)
echo.

REM ---------- 3. install the two data packages ----------
set "MARK=.venv\installed.flag"
if not exist "!MARK!" (
  echo ------------------------------------------------------------
  echo Installing data packages: akshare, baostock
  echo This is a one-time download of roughly 50-100 MB.
  echo It can take 2-10 minutes. Please leave this window open.
  echo ------------------------------------------------------------
  echo.

  !RUN! -m pip install --upgrade pip -q -i https://pypi.tuna.tsinghua.edu.cn/simple
  !RUN! -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare baostock pandas numpy

  if !errorlevel! neq 0 (
    echo.
    echo [WARN] Mirror install failed. Retrying with the default index...
    echo.
    !RUN! -m pip install akshare baostock pandas numpy
  )

  if !errorlevel! equ 0 (
    echo done > "!MARK!"
    echo.
    echo Packages installed.
  ) else (
    echo.
    echo [WARN] Installation reported an error.
    echo        The check will still run and tell you what is missing.
  )
  echo.
)

REM ---------- 4. run the health check ----------
echo ------------------------------------------------------------
echo Running the data health check...
echo ------------------------------------------------------------
echo.

!RUN! "code\data_check.py"

echo.
echo ============================================================
echo  Finished. Open the "output" folder.
echo  Send the .json file inside it back to Claude.
echo ============================================================
echo.
pause
