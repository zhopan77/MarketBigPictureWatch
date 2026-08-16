@echo off
REM ---------------------------------------------------------------------
REM Convenience shim for double-clicking on Windows.
REM
REM The real command is the same on every platform:
REM
REM     python run.py
REM
REM This file exists only so a desktop shortcut keeps working, and so a
REM double-click does not vanish before you can read the error.
REM
REM It probes for an interpreter rather than assuming `python` resolves.
REM On Windows `python` can be missing from PATH entirely (an Anaconda or
REM Microsoft Store install), or worse, be the Store's stub that opens the
REM Store instead of running anything -- which is how this went wrong on the
REM desktop balancer. `py` is the official launcher and is the more reliable
REM of the two, so it is tried first.
REM ---------------------------------------------------------------------
cd /d "%~dp0"

set "PY="
for %%C in ("py -3" "python" "python3") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=%%~C"
    )
)

if not defined PY (
    echo.
    echo   Could not find Python 3.10 or newer. Tried: py -3, python, python3
    echo.
    echo   Install it from https://www.python.org/downloads/ and tick
    echo   "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

%PY% run.py %*
if errorlevel 1 pause
