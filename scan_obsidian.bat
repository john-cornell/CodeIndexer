@echo off
setlocal

REM One-shot scan + Obsidian export.
REM You can pass any codeidx scan-obsidian args, e.g.:
REM   scan_obsidian.bat --out-dir .codeidx\vault --all-solutions --force --no-progress

python -m codeidx scan-obsidian %*

endlocal
