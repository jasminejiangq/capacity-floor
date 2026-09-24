@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
set PYTHONUTF8=1
cd /d "%~dp0"

echo.
echo ============================================================
echo    Publish to GitHub
echo ============================================================
echo.

git --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git is not installed.
  echo         Install it from https://git-scm.com/download/win
  echo         then run this file again.
  echo.
  pause & exit /b 1
)

REM ---- identity -------------------------------------------------
for /f "delims=" %%i in ('git config --global user.name 2^>nul') do set "GN=%%i"
for /f "delims=" %%i in ('git config --global user.email 2^>nul') do set "GE=%%i"
if not defined GN (
  echo Git does not know who you are yet.
  set /p GN="  Your name (shown on every commit): "
  git config --global user.name "!GN!"
)
if not defined GE (
  set /p GE="  Your GitHub email: "
  git config --global user.email "!GE!"
)
echo   committing as: !GN! ^<!GE!^>
echo.

REM ---- safety check ---------------------------------------------
if exist "data\us" (
  echo [STOP] data\us exists. It is gitignored, but verify before pushing.
)

if not exist ".git" (
  echo   initialising repository ...
  git init -b main >nul
)

git add -A
echo.
echo   ---- what will be committed -------------------------------
git status --short
echo   -----------------------------------------------------------
echo.
echo   Check the list above. There must be NO .db file, NO csv of
echo   market data, and nothing under data\us or data\wrds.
echo.
set /p OK="  Looks right? (y/n): "
if /i not "!OK!"=="y" (
  echo   Aborted. Nothing was committed.
  pause & exit /b 1
)

git commit -m "The Capacity Floor: fixed per-trade costs and the minimum viable account" -m "Analytic two-sided capacity model, empirical A-share estimation over 15.6 years of point-in-time data, factor diagnostics (IC/ICIR/decay/monotonicity), multiple-testing corrections, and a cross-market counterfactual against the October 2019 US retail commission-to-zero shift." 2>nul
if errorlevel 1 (
  echo   ^(nothing new to commit^)
)

echo.
echo ============================================================
echo   NEXT STEPS -- do these in your browser, once
echo ============================================================
echo.
echo   1. Go to  https://github.com/new
echo   2. Repository name:  capacity-floor
echo   3. Description:
echo      Fixed per-trade commissions create a MINIMUM viable
echo      account size for factor strategies. Measured on 15.6
echo      years of A-share data.
echo   4. Choose Public. Do NOT tick "Add a README" or
echo      "Add .gitignore" -- this repo already has both.
echo   5. Click "Create repository".
echo   6. Copy the URL it shows you, then run:
echo.
echo        git remote add origin https://github.com/YOURNAME/capacity-floor.git
echo        git push -u origin main
echo.
echo      Git will open a browser window to sign you in.
echo.
echo   Paste those two lines into this window now, or close it and
echo   run them later from a terminal in this folder.
echo.
cmd /k
