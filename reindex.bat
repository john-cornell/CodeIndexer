@echo off
setlocal
if "%~1"=="" (
  echo Usage: %~nx0 ^<repo_root^>
  echo   Runs: python -m codeidx index ^<repo_root^> --force --no-sln ^(no interactive .sln pick^)
  exit /b 1
)
python -m codeidx index "%~1" --force --no-sln
