@echo off
setlocal

REM Full scan wrapper. Today this runs scan + Obsidian export.
REM Forward any args to scan_obsidian.bat / codeidx scan-obsidian.

call "%~dp0scan_obsidian.bat" %*

endlocal
