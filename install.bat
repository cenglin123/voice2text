@echo off
rem voice2text one-click installer (ASCII messages only - avoid codepage issues)
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
rem isolate from any packages the user installed into AppData Roaming site-packages
set "PYTHONNOUSERSITE=1"
if exist "offline-bundle.txt" goto offline_install
set "LLAMA_INDEX=https://abetlen.github.io/llama-cpp-python/whl/cpu/"
set "PY="
set "LOCAL_LLAMA="
set "PY_CHECK=import sys,struct,tkinter; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) and struct.calcsize('P') == 8 else 1)"

echo [1/4] Locating Python 3.11-3.13 x64 with Tk ...

rem Prefer the py launcher
py -3 -c "%PY_CHECK%" >nul 2>&1
if not errorlevel 1 (
    if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || goto venv_bad
    ".venv\Scripts\python.exe" -c "%PY_CHECK%" >nul 2>&1 || goto venv_bad
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)

rem Plain python on PATH (the Microsoft Store stub returns a non-zero code here and is skipped)
python -c "%PY_CHECK%" >nul 2>&1
if not errorlevel 1 (
    if not exist ".venv\Scripts\python.exe" python -m venv .venv || goto venv_bad
    ".venv\Scripts\python.exe" -c "%PY_CHECK%" >nul 2>&1 || goto venv_bad
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
    ".venv\Scripts\python.exe" -c "%PY_CHECK%" >nul 2>&1 || rmdir /s /q ".venv"
)
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    goto got_python
)

rem No usable Python: python-build-standalone includes tkinter for the GUI.
echo   No compatible Python found, setting up standalone runtime ...
if exist "runtime\python\python.exe" if exist "runtime\python\Lib\site-packages\pip" goto runtime_ready

if not exist "runtime\python\python.exe" (
    where curl >nul 2>&1 || (echo   [FAIL] curl not found - please run on Windows 10 1803+ & goto fail)
    if not exist "runtime" mkdir runtime
    rem python-build-standalone 官方 CPython 独立包：自带 tkinter（embeddable zip 和 nuget 包都没有，GUI 跑不起来）
    curl -L --fail --retry 3 -o runtime_py.tar.gz https://github.com/astral-sh/python-build-standalone/releases/download/20240415/cpython-3.11.9+20240415-x86_64-pc-windows-msvc-shared-install_only.tar.gz || (echo   [FAIL] cannot download Python runtime & goto fail)
    tar -xzf runtime_py.tar.gz -C "runtime" || (echo   [FAIL] cannot extract Python runtime & goto fail)
    rem install_only 布局直接解出 runtime\python，无 ._pth，cwd 天然在 sys.path
    del runtime_py.tar.gz 2>nul
)

rem pip bootstrap is re-runnable: a half-installed runtime (python.exe ok, pip missing) resumes here
if exist "runtime\python\Lib\site-packages\pip" goto runtime_ready
curl -L --fail -o get-pip.py https://bootstrap.pypa.io/get-pip.py || curl -L --fail -o get-pip.py https://mirrors.aliyun.com/pypi/get-pip.py || (echo   [FAIL] cannot download get-pip.py & goto fail)
"runtime\python\python.exe" get-pip.py --no-warn-script-location || (echo   [FAIL] pip bootstrap failed & goto fail)
del runtime_py.tar.gz get-pip.py 2>nul

:runtime_ready
set "PY=runtime\python\python.exe"
"%PY%" -c "%PY_CHECK%" >nul 2>&1
if errorlevel 1 (echo   [FAIL] incompatible runtime; move runtime folder aside and retry & goto fail)

:got_python
echo   Using: %PY%

echo [2/4] Installing dependencies (this may take a few minutes) ...
"%PY%" -m pip install --upgrade pip --quiet
set "WHEEL_SOURCE=--extra-index-url %LLAMA_INDEX%"
for %%F in ("vendor\llama_cpp_python-0.3.35-*.whl") do if exist "%%~fF" set "LOCAL_LLAMA=%%~fF"
if defined LOCAL_LLAMA (
    echo   Installing bundled llama-cpp-python wheel ...
    "%PY%" -m pip install --no-deps "%LOCAL_LLAMA%"
    if errorlevel 1 (echo   [FAIL] bundled llama-cpp-python wheel installation failed & goto fail)
    set "WHEEL_SOURCE=--find-links vendor"
)
"%PY%" -m pip install --only-binary=:all: -r requirements.txt %WHEEL_SOURCE%
if errorlevel 1 (
    echo   Retry with Tsinghua PyPI mirror ...
    "%PY%" -m pip install --only-binary=:all: -r requirements.txt %WHEEL_SOURCE% -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (echo   [FAIL] dependency installation failed & goto fail)
)

echo [3/4] Downloading models (~1.5 GB total, resumable) ...
"%PY%" scripts\download_models.py
if errorlevel 1 (echo   [FAIL] model download failed, check network and retry & goto fail)

echo [4/4] Verifying installation ...
"%PY%" -c "import voice2text, sherpa_onnx, llama_cpp, sounddevice, keyboard, uiautomation, pystray, pyperclip, pythoncom, win32clipboard, tkinter; print('  all modules imported OK')"
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

:offline_install
echo Verifying self-contained offline installation ...
"runtime\python\python.exe" -I -X utf8 scripts\verify_install.py
if errorlevel 1 goto fail
echo Install OK. Start with run.bat
exit /b 0
