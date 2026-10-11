@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "scripts\desktop.py"
) else (
  where pythonw >nul 2>nul
  if errorlevel 1 (
    echo Please install Python 3.11+ with Tcl/Tk and add it to PATH.
    pause
    exit /b 1
  )
  start "" pythonw "scripts\desktop.py"
)
