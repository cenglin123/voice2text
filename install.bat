@echo off
rem voice2text one-click installer (ASCII messages only - avoid codepage issues)
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
rem isolate from any packages the user installed into AppData Roaming site-packages
set "PYTHONNOUSERSITE=1"
set "LLAMA_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cpu/"
set "PY="

echo [1/4] Locating Python 3.10+ ...

rem Prefer the py launcher
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto venv_bad
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 || goto venv_bad
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)

rem Plain python on PATH (the Microsoft Store stub returns a non-zero code here and is skipped)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    if not exist ".venv\Scripts\python.exe" python -m venv .venv || goto venv_bad
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 || goto venv_bad
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)

:venv_bad
rem Broken or outdated .venv: rebuild it via the py launcher if possible.
rem The rebuilt venv must pass the same version check, otherwise a 3.9-only
rem machine would loop forever and leave a poisoned .venv for run.bat.
if exist ".venv" rmdir /s /q ".venv"
py -3 -m venv .venv >nul 2>&1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 || rmdir /s /q ".venv"
)
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)

rem No usable Python: self-contained embeddable runtime
echo   No Python 3.10+ found, setting up embedded runtime ...
if exist "runtime\python\python.exe" if exist "runtime\python\Lib\site-packages\pip" goto runtime_ready

if not exist "runtime\python\python.exe" (
    where curl >nul 2>&1 || (echo   [FAIL] curl not found - please run on Windows 10 1803+ & goto fail)
    if not exist "runtime" mkdir runtime
    curl -L --fail --retry 3 -o runtime_embed.zip https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip || curl -L --fail --retry 3 -o runtime_embed.zip https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip || (echo   [FAIL] cannot download embeddable Python & goto fail)
    if not exist "runtime\python" mkdir "runtime\python"
    tar -xf runtime_embed.zip -C "runtime\python" || (echo   [FAIL] cannot extract embeddable Python & goto fail)
    rem ._pth isolated mode: enable site-packages and expose the project root,
    rem otherwise cwd is NOT on sys.path and `import voice2text` fails
    echo import site>> "runtime\python\python311._pth"
    echo ..\..>> "runtime\python\python311._pth"
)

rem pip bootstrap is re-runnable: a half-installed runtime (python.exe ok, pip missing) resumes here
if exist "runtime\python\Lib\site-packages\pip" goto runtime_ready
curl -L --fail -o get-pip.py https://bootstrap.pypa.io/get-pip.py || curl -L --fail -o get-pip.py https://mirrors.aliyun.com/pypi/get-pip.py || (echo   [FAIL] cannot download get-pip.py & goto fail)
"runtime\python\python.exe" get-pip.py --no-warn-script-location || (echo   [FAIL] pip bootstrap failed & goto fail)
del runtime_embed.zip get-pip.py 2>nul

:runtime_ready
set "PY=runtime\python\python.exe"

:got_python
echo   Using: %PY%

echo [2/4] Installing dependencies (this may take a few minutes) ...
"%PY%" -m pip install --upgrade pip --quiet --extra-index-url %LLAMA_INDEX%
"%PY%" -m pip install -r requirements.txt --extra-index-url %LLAMA_INDEX%
if errorlevel 1 (
    echo   Retry with Tsinghua PyPI mirror ...
    "%PY%" -m pip install -r requirements.txt --extra-index-url %LLAMA_INDEX% -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (echo   [FAIL] dependency installation failed & goto fail)
)

echo [3/4] Downloading models (~1.4 GB total, resumable) ...
"%PY%" scripts\download_models.py
if errorlevel 1 (echo   [FAIL] model download failed, check network and retry & goto fail)

echo [4/4] Verifying installation ...
"%PY%" -c "import voice2text, sherpa_onnx, llama_cpp, sounddevice, keyboard, uiautomation, pystray, pyperclip, pythoncom, win32clipboard; print('  all modules imported OK')"
if errorlevel 1 (echo   [FAIL] module import failed & goto fail)

echo.
echo ============================================
echo  Install OK. Start with: run.bat
echo ============================================
exit /b 0

:fail
echo.
echo  Install FAILED. Fix the problem above and re-run.
exit /b 1
