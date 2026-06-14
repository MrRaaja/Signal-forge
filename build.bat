@echo off
REM ============================================================
REM  Build SignalForge into a standalone Windows .exe
REM  Run this from the project root in a Command Prompt.
REM ============================================================

echo [1/4] Creating virtual environment (.venv)...
python -m venv .venv
call .venv\Scripts\activate

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo [3/4] Building executable with PyInstaller...
REM --windowed : no console window
REM --onedir   : portable folder (recommended for audio apps; faster start,
REM              easier to ship DLLs than --onefile). The whole dist\ folder
REM              is what you copy to another PC.
pyinstaller ^
  --noconfirm ^
  --windowed ^
  --onedir ^
  --name "SignalForge" ^
  --collect-all sounddevice ^
  --collect-all soundfile ^
  --collect-all rtmidi ^
  --collect-submodules mido ^
  main.py

echo [4/4] Done.
echo.
echo Your app is in:  dist\SignalForge\
echo Copy that whole folder to another PC to run it. Launch SignalForge.exe
echo.
echo NOTE: install VB-Audio Virtual Cable on the target PC (see README).
pause
