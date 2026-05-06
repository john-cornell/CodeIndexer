@echo off
setlocal

REM Index + Obsidian export with --index-string-literals (string_ref edges).
REM Same defaults as scan_obsidian.bat: --all-solutions --force (no interactive .sln pick).
REM Examples:
REM   scan_obsidian_string_literals.bat
REM   scan_obsidian_string_literals.bat C:\path\to\repo --no-progress
REM   scan_obsidian_string_literals.bat --out-dir .codeidx\vault

python -m codeidx scan-obsidian --all-solutions --force --index-string-literals %*

endlocal
