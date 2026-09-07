@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo [ERROR] Python environment not found. Please run setup.bat first.
  pause
  exit /b 1
)
if not exist "packaging\electrochem_v6_launcher.py" (
  echo [ERROR] Desktop launcher not found.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "packaging\electrochem_v6_launcher.py"
exit /b 0
