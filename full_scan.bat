@echo off
setlocal

REM Like scan.bat but also --store-content (file_contents_fts / grep-text; much larger DB).
REM Full re-index + Obsidian.

python -m codeidx scan-obsidian --all-solutions --force --index-string-literals --store-content %*

endlocal
