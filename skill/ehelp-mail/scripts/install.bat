@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
set "PYTHON="
py -3.12 -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3.12"
if defined PYTHON goto found
py -3 -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
if defined PYTHON goto found
python -c "import sys; sys.exit(sys.version_info < (3,11))" >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
if defined PYTHON goto found
"%LocalAppData%\Programs\Python\Python312\python.exe" -c "import sys" >nul 2>nul
if not errorlevel 1 set PYTHON="%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PYTHON goto found
echo 请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/windows/
echo 安装时勾选 Add Python to PATH，然后重试本文件。
exit /b 1
:found
if exist "%ROOT%.venv\Scripts\python.exe" goto dependencies
%PYTHON% -m venv "%ROOT%.venv"
if errorlevel 1 exit /b 1
:dependencies
"%ROOT%.venv\Scripts\python.exe" -m pip install --disable-pip-version-check "pydantic==2.13.5"
if errorlevel 1 exit /b 1
cd /d "%ROOT%"
"%ROOT%.venv\Scripts\python.exe" -B -m cli --help >nul
if errorlevel 1 exit /b 1
echo 安装完成。请让 Agent 运行 ehelp_mail.bat --json doctor。
exit /b 0
