@echo off
setlocal

cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"
set "REQ_FILE=requirements.txt"

if not exist "%REQ_FILE%" (
  echo [ERROR] Missing %REQ_FILE%.
  pause
  exit /b 1
)

if exist "%VENV_PY%" goto install

echo [INFO] Creating virtual environment in .venv ...
call :find_python
if errorlevel 1 (
  echo [ERROR] Python 3 not found. Please install Python 3.12+, then rerun setup.bat.
  pause
  exit /b 1
)

call %PYTHON_CMD% -m venv .venv
if errorlevel 1 (
  echo [ERROR] Failed to create virtual environment.
  pause
  exit /b 1
)

:install
echo [INFO] Installing dependencies ...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip.
  pause
  exit /b 1
)

"%VENV_PY%" -m pip install -r "%REQ_FILE%"
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies.
  pause
  exit /b 1
)

echo.
echo [OK] Setup completed.
echo [TIP] Double-click start.bat to launch the app.
pause
exit /b 0

:find_python
set "PYTHON_CMD="
py -3.12 -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3.12"
  exit /b 0
)
py -3 -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
  exit /b 0
)
python -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  exit /b 0
)
exit /b 1
