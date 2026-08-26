@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found.
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [ERROR] .env not found.
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)

echo Starting Lead Radar Mini App in safe web-only mode...
echo Open: http://127.0.0.1:8000
echo Telegram is not required in this mode.
echo.
".venv\Scripts\python.exe" -m app.main --web-only

if errorlevel 1 (
  echo.
  echo [ERROR] Lead Radar stopped with an error.
  pause
)
