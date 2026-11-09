@echo off
setlocal
pushd "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m scripts.start_local --stop
) else (
    python -m scripts.start_local --stop
)
set "result=%errorlevel%"
popd
if not "%result%"=="0" pause
exit /b %result%
