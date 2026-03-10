@echo off
setlocal

cd /d "%~dp0"

set "PORT=%ELECTROCHEM_V6_PORT%"
if "%PORT%"=="" set "PORT=8010"

set "PYTHON_EXE=.venv\Scripts\python.exe"
set "ENTRY=run_v6.py"
set "UI_URL=http://127.0.0.1:%PORT%/ui"

if not exist "%ENTRY%" (
  echo [ERROR] Missing %ENTRY%.
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Virtual environment not found: .venv
  echo [TIP] Please run setup.bat first.
  pause
  exit /b 1
)

echo [INFO] Starting ElectroChem V6 server on port %PORT% ...
start "ElectroChem V6 Server" cmd /k ""%PYTHON_EXE%" "%ENTRY%" server --port %PORT%"

timeout /t 2 /nobreak >nul

echo [INFO] Opening %UI_URL%
start "" "%UI_URL%"

echo [OK] App launched. Keep the server window open while using the UI.
timeout /t 2 /nobreak >nul
exit /b 0
