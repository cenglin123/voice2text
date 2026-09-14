@echo off
rem voice2text launcher
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"

rem Probe each interpreter before use: a .venv whose base Python was uninstalled is broken
set "PY="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "pass" >nul 2>&1 && set "PY=.venv\Scripts\python.exe"
)
if not defined PY if exist "runtime\python\python.exe" (
    "runtime\python\python.exe" -c "pass" >nul 2>&1 && set "PY=runtime\python\python.exe"
)
if not defined PY (
    echo Not installed yet. Run install.bat first.
    pause
    exit /b 1
)

"%PY%" -m voice2text.main
if errorlevel 1 pause
