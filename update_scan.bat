@echo off
setlocal

REM Incremental index + Obsidian: same as scan.bat but NO --force (skip unchanged files).
REM Use for day-to-day updates; run scan.bat after upgrading codeidx or when graph looks wrong.

python -m codeidx scan-obsidian --all-solutions --index-string-literals %*

endlocal
