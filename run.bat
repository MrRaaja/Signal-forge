@echo off
REM ============================================================
REM   SignalForge  --  ONE-CLICK LAUNCHER
REM   Just double-click this file.
REM   First run: builds the environment + installs everything (~2-4 min).
REM   Every run after: launches instantly.
REM ============================================================
setlocal
cd /d "%~dp0"

REM --- Check Python is installed ------------------------------
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ERROR] Python is not installed or not on your PATH.
  echo.
  echo   1. Download Python 3.11 or 3.12 from https://www.python.org/downloads/
  echo   2. During install, TICK the box "Add Python to PATH".
  echo   3. Re-run this file.
  echo.
  pause
  exit /b 1
)

REM --- First-time setup: create venv + install deps ----------
if not exist ".venv\Scripts\python.exe" (
  echo ============================================================
  echo   First-time setup. This happens ONCE and takes a few minutes.
  echo ============================================================
  echo.
  echo [1/3] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 ( echo [ERROR] Could not create venv. & pause & exit /b 1 )

  echo [2/3] Upgrading pip...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip

  echo [3/3] Installing dependencies ^(PySide6, sounddevice, mido, etc^)...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed. Check your internet connection
    echo         and re-run this file.
    pause
    exit /b 1
  )
  echo.
  echo Setup complete!
  echo.
)

REM --- Launch the app ----------------------------------------
echo Starting SignalForge...
".venv\Scripts\pythonw.exe" main.py
exit /b 0
