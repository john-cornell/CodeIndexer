@echo off
setlocal

REM Full re-index + Obsidian: merged solutions, string_ref (--index-string-literals), --force.
REM MVVM edges on by default. No stored file bodies (smaller DB).
REM Examples: scan.bat   scan.bat C:\path\to\repo   scan.bat --no-progress

python -m codeidx scan-obsidian --all-solutions --force --index-string-literals %*

endlocal
