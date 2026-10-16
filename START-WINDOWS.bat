@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
py -3.12 --version >nul 2>&1
if errorlevel 1 goto anypython
py -3.12 -m venv .venv
goto checkvenv
:anypython
py -3 --version >nul 2>&1
if errorlevel 1 goto usepython
py -3 -m venv .venv
goto checkvenv
:usepython
python --version >nul 2>&1
if errorlevel 1 goto missingpython
python -m venv .venv
:checkvenv
if not exist ".venv\Scripts\python.exe" goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" run_local.py
if errorlevel 1 goto failed
exit /b 0
:missingpython
echo Install Python 3.12 from python.org and enable Add Python to PATH.
pause
exit /b 1
:failed
echo Local start failed. Read the message above.
pause
exit /b 1
