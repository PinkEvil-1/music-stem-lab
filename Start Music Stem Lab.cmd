@echo off
title Music Stem Lab
setlocal
pushd "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m scripts.start_local %*
) else (
    python -m scripts.start_local %*
)
set "result=%errorlevel%"
popd
if not "%result%"=="0" if not "%~1"=="--no-browser" pause
exit /b %result%
