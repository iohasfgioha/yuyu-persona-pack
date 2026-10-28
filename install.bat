@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\run.ps1" -Action install
set "YUYU_EXIT=%ERRORLEVEL%"
echo.
pause
popd
exit /b %YUYU_EXIT%
