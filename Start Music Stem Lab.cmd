@echo off
title Music Stem Lab
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 13)" >nul 2>nul
    if not errorlevel 1 goto local
)
set "base=%LocalAppData%\Programs\Python\Python313\python.exe"
if exist "%base%" goto base
py -3.13 -c "import sys" >nul 2>nul
if not errorlevel 1 goto py
python -c "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 13)" >nul 2>nul
if not errorlevel 1 goto path
if "%~1"=="--no-browser" goto missing
echo [  0%%] 缺少 Python 3.11–3.13。是否使用 Windows 套件管理員下載並安裝 Python 3.13？
choice /c YN /n /m "請選擇 [Y/N]："
if not "%errorlevel%"=="1" goto cancelled
echo [  2%%] 正在下載並安裝 Python 3.13…
winget install --id Python.Python.3.13 --exact --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto missing
if exist "%base%" goto base
echo Python 已安裝。請重新開啟 Start Music Stem Lab.cmd。
goto cancelled

:local
".venv\Scripts\python.exe" -m scripts.start_local %*
goto finished

:base
"%base%" -m scripts.start_local %*
goto finished

:py
py -3.13 -m scripts.start_local %*
goto finished

:path
python -m scripts.start_local %*
goto finished

:missing
echo 無法啟動 Python。請安裝 Windows x64 Python 3.13 後重試。
cmd /c exit 1
goto finished

:cancelled
popd
exit /b 0

:finished
set "result=%errorlevel%"
popd
if not "%result%"=="0" if not "%~1"=="--no-browser" pause
exit /b %result%
