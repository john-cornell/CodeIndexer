@echo off
setlocal

REM One-shot scan + Obsidian export.
REM Defaults: --all-solutions --force to avoid interactive .sln prompts.
REM You can still pass extra args, e.g.:
REM   scan_obsidian.bat --no-progress
REM   scan_obsidian.bat C:\path\to\repo --out-dir .codeidx\vault

python -m codeidx scan-obsidian --all-solutions --force %*

endlocal
