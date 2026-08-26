@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python launcher "py" not found. Install Python 3.12+ and try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3.12 -m venv .venv 2>nul || py -m venv .venv
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo.
  echo Created .env from .env.example.
  echo Safe defaults are already enabled. API keys are optional for local UI tests.
)

echo Creating safe database backup if an old SQLite database exists...
".venv\Scripts\python.exe" -m scripts.backup_database
if errorlevel 1 goto :fail

echo Applying database migrations...
".venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 goto :fail

echo Checking database integrity...
".venv\Scripts\python.exe" -m scripts.check_data_integrity
if errorlevel 1 goto :fail

echo.
echo Setup complete.
echo Run start_windows.bat
pause
exit /b 0

:fail
echo.
echo [ERROR] Setup failed. Copy the error output and send it for review.
pause
exit /b 1
