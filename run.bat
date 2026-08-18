@echo off
setlocal EnableDelayedExpansion
title Stream Scoop

:: ─────────────────────────────────────────────────────────────────
::  Stream Scoop launcher - run.bat
::    Window stays open on ANY error so you can always read what went wrong.
:: ─────────────────────────────────────────────────────────────────

:: Strip trailing backslash from %~dp0 so paths don't double-up
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "VENV_DIR=%SCRIPT_DIR%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"
set "REQ_FILE=%SCRIPT_DIR%\requirements.txt"

echo.
echo  ===================================================
echo    Stream Scoop  ^|  Starting up...
echo  ===================================================
echo.

:: ── 1. Find Python ────────────────────────────────────────────
set "PYTHON="

where py >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "PYTHON=py"
    goto :found_python
)

where python >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    :: Guard against the Windows Store stub which returns error 9009
    python --version >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "PYTHON=python"
        goto :found_python
    )
)

where python3 >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    set "PYTHON=python3"
    goto :found_python
)

echo  [ERROR] Python was not found on this computer.
echo.
echo  Install Python 3.9+ from:  https://www.python.org/downloads/
echo  IMPORTANT: tick "Add Python to PATH" during installation.
echo.
goto :fatal

:found_python
for /f "tokens=2 delims= " %%V in ('!PYTHON! --version 2^>^&1') do set "PY_VER=%%V"
echo  [OK] Python  :  !PYTHON!  ^(!PY_VER!^)

:: ── 2. Create venv on first run ───────────────────────────────
if not exist "!VENV_PY!" (
    echo.
    echo  [SETUP] First run - creating virtual environment...
    "!PYTHON!" -m venv "!VENV_DIR!"
    if !ERRORLEVEL! NEQ 0 (
        echo.
        echo  [ERROR] Could not create virtual environment.
        echo          Try:  !PYTHON! -m venv "!VENV_DIR!"
        goto :fatal
    )
    echo  [OK] Virtual environment created.

    echo.
    echo  [SETUP] Installing dependencies ^(one-time, ~1 min^)...
    "!VENV_PIP!" install --upgrade pip --quiet
    "!VENV_PIP!" install -r "!REQ_FILE!"
    if !ERRORLEVEL! NEQ 0 (
        echo.
        echo  [ERROR] Dependency installation failed.
        echo          Check your internet connection and try again.
        echo          Or install manually:  pip install yt-dlp colorama
        goto :fatal
    )
    echo  [OK] Dependencies installed.
) else (
    echo  [OK] Venv     :  ready
)

:: ── 3. Sanity-check main.py is present ───────────────────────
if not exist "!SCRIPT_DIR!\main.py" (
    echo.
    echo  [ERROR] main.py not found in:
    echo          !SCRIPT_DIR!
    echo.
    echo  Make sure run.bat is in the same folder as the .py files.
    goto :fatal
)

:: ── 4. FFmpeg check ───────────────────────────────────────────
where ffmpeg >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo  [OK] FFmpeg   :  found
) else (
    echo.
    echo  [WARN] FFmpeg not found in PATH.
    echo         Stream Scoop needs it to merge video + audio.
    echo.
    echo         Install with ONE of these commands:
    echo           winget install --id Gyan.FFmpeg -e
    echo           choco install ffmpeg
    echo         Or: https://ffmpeg.org/download.html
    echo.
    echo  Press any key to launch anyway...
    pause >nul
)

:: ── 5. aria2c check (optional) ────────────────────────────────
where aria2c >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo  [OK] aria2c   :  found  ^(faster downloads enabled^)
) else (
    echo  [--] aria2c   :  not found  ^(optional^)
)

echo.
echo  ===================================================
echo    Launching...
echo  ===================================================
echo.

:: ── 6. Launch ─────────────────────────────────────────────────
cd /d "!SCRIPT_DIR!"
"!VENV_PY!" main.py
set "EXIT_CODE=!ERRORLEVEL!"

if !EXIT_CODE! EQU 0 goto :clean_exit

echo.
echo  ===================================================
echo  [ERROR] Stream Scoop exited with code !EXIT_CODE!
echo  ===================================================
echo.
echo  Things to try:
echo    1. Delete the .venv folder, then run this bat again
echo       to do a clean reinstall of all dependencies.
echo    2. Run this bat as Administrator.
echo    3. Make sure ALL .py files are in the same folder as run.bat.
echo.
goto :fatal

:clean_exit
endlocal
exit /b 0

:fatal
echo.
echo  Press any key to close...
pause >nul
endlocal
exit /b 1
