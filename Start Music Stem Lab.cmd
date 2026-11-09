@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\start_local.py" %*
) else (
    python "%~dp0scripts\start_local.py" %*
)
set "result=%errorlevel%"
if not "%result%"=="0" if not "%~1"=="--no-browser" pause
exit /b %result%
