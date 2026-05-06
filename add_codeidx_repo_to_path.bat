@echo off
setlocal EnableExtensions

REM Adds THIS repo folder to Windows User PATH so scan_obsidian.bat etc. run from any cwd.
REM Double-click or run:  add_codeidx_repo_to_path.bat
REM Then open a new terminal / restart Cursor.

for %%I in ("%~dp0.") do set "CODEIDX_ROOT=%%~fI"

echo.
echo Registering CodeIndexer repo:
echo   %CODEIDX_ROOT%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\add_codeidx_repo_to_path.ps1" -RepoRoot "%CODEIDX_ROOT%"

endlocal
