@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ============================================================
echo    FINISH THE PROJECT  -  runs everything that is still missing
echo ============================================================
echo.
echo   1. test suite            (~3 seconds, no database)
echo   2. all four figures      (~2 seconds, from results/*.json)
echo   3. statistical honesty   (~15 min with --pbo)
echo.
echo   Nothing here re-runs a backtest. Everything reads JSON that
echo   capacity.py and factor_eval.py already produced.
echo.

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
if not defined RUN ( echo [ERROR] Python not found. & pause & exit /b 1 )
if not exist "output" mkdir "output"

echo ---- 1/3  tests --------------------------------------------
!RUN! "tests\run_tests.py"
if errorlevel 1 ( echo. & echo [STOP] Tests failed. Fix before continuing. & pause & exit /b 1 )

echo.
echo ---- 2/3  figures ------------------------------------------
!RUN! "research\make_charts.py"

echo.
echo ---- 3/3  statistical honesty ------------------------------
!RUN! -u "research\stat_honesty.py" --pbo > "output\stat_honesty_log.txt" 2>&1
type "output\stat_honesty_log.txt"

echo.
echo ============================================================
echo   Done. results\ now holds:
echo     capacity.json  factor_eval.json  stat_honesty.json
echo     fig1..fig4 .png
echo.
echo   Next: commit and push.
echo     git add -A
echo     git commit -m "Factor evidence, corrected cost metric, figures"
echo     git push
echo ============================================================
pause
