@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   REBUILD THE REPOSITORY WITHOUT THE LITERATURE PDFs
echo ============================================================
echo.
echo   The first push included zhishiku\ -- about 7 MB of
echo   publisher PDFs from library subscriptions. Deleting them
echo   in a new commit is NOT enough: git keeps every old commit,
echo   so the files would still be downloadable from history.
echo.
echo   The only clean fix is to throw away the local history and
echo   the GitHub repository, then push again from scratch.
echo.
echo   BEFORE running this, delete the repo on GitHub:
echo     https://github.com/jasminejiangq/capacity-floor/settings
echo     scroll to the bottom -^> Delete this repository
echo.
set /p DONE="  Have you deleted it on GitHub? (y/n): "
if /i not "!DONE!"=="y" (
  echo   Delete it first, then run this again.
  pause & exit /b 1
)

if exist ".git" (
  echo   removing local git history ...
  rmdir /s /q ".git"
)

git init -b main >nul
git add -A

echo.
echo   ---- what will be committed this time ---------------------
git status --short
echo   -----------------------------------------------------------
echo.
echo   Check: NO .pdf, NO .doc/.docx, nothing under zhishiku\,
echo   no .db file, no output\ folder.
echo.
set /p OK="  Clean? (y/n): "
if /i not "!OK!"=="y" ( echo   Aborted. & pause & exit /b 1 )

git commit -m "The Capacity Floor: fixed per-trade costs and the minimum viable account" -m "Analytic two-sided capacity model, empirical A-share estimation over 15.6 years of point-in-time data, factor diagnostics (IC/ICIR/decay/monotonicity), multiple-testing corrections, and a cross-market counterfactual against the October 2019 US retail commission-to-zero shift."

echo.
echo ============================================================
echo   Now recreate the repository on GitHub (same name is fine):
echo     https://github.com/new     name: capacity-floor
echo     Public, do NOT add README / .gitignore / licence
echo.
echo   Then run these two lines:
echo.
echo     git remote add origin https://github.com/jasminejiangq/capacity-floor.git
echo     git push -u origin main
echo.
echo   The push should be well under 1 MB this time. If it says
echo   several MB again, stop and check the file list.
echo ============================================================
echo.
cmd /k
