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
  echo Copy your private .env from the old project or run setup_windows.bat and fill it.
  pause
  exit /b 1
)

echo Starting Lead Radar MVP V3.2...
echo Web interface: http://127.0.0.1:8000
echo Close this window or press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" -m app.main

if errorlevel 1 (
  echo.
  echo [ERROR] Lead Radar stopped with an error.
  pause
)
