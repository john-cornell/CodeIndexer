@echo off
setlocal

REM Full scan wrapper. Runs scan + Obsidian export with
REM --all-solutions --force defaults from scan_obsidian.bat.
REM Forward any args to scan_obsidian.bat / codeidx scan-obsidian.

call "%~dp0scan_obsidian.bat" %*

endlocal
