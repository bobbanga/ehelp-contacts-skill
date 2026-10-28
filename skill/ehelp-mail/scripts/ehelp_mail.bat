@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
if exist "%ROOT%.venv\Scripts\python.exe" goto run
echo 尚未安装运行环境，请先运行 install.bat。
exit /b 1
:run
cd /d "%ROOT%"
"%ROOT%.venv\Scripts\python.exe" -B -m cli %*
exit /b %ERRORLEVEL%
