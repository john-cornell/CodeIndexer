@echo off
setlocal

REM Incremental + --store-content + Obsidian (no --force). Pair with full_scan.bat for first run.

python -m codeidx scan-obsidian --all-solutions --index-string-literals --store-content %*

endlocal
