@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\start_local.py" --stop
) else (
    python "%~dp0scripts\start_local.py" --stop
)
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
