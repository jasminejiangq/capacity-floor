@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    A-Share Stock Tool  -  Step 2 : Build Local Database
echo ============================================================
echo.
echo   Downloads market history into a local database file.
echo   Everything after this runs offline from that file.
echo.
echo   You can close this window at any time.
echo   Running it again resumes from where it stopped.
echo.
echo ------------------------------------------------------------
echo   1 = TRIAL RUN    300 stocks,  about 10-20 minutes
echo                    (do this first, to check everything works)
echo.
echo   2 = FULL BUILD   whole market, about 3-8 hours
echo                    (can be stopped and resumed)
echo ------------------------------------------------------------
echo.

set "MODE="
set /p MODE="Type 1 or 2 then press Enter: "

if "!MODE!"=="1" (
  set "ARG="
  echo.
  echo Starting TRIAL RUN...
) else if "!MODE!"=="2" (
  set "ARG=full"
  echo.
  echo Starting FULL BUILD. This will take hours.
  echo You can close the window and re-run later to resume.
) else (
  echo.
  echo Not 1 or 2 - nothing to do. Run this file again.
  echo.
  pause
  exit /b 1
)
echo.

REM ---------- locate the environment made in step 1 ----------
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
  echo [ERROR] Python not found. Please run 01_data_check.bat first.
  echo.
  pause
  exit /b 1
)

!RUN! "code\build_db.py" !ARG!

echo.
echo ============================================================
echo  Open the "output" folder and send the .json file to Claude.
echo ============================================================
echo.
pause
