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

powershell.exe -NoProfile -File "%~dp0scripts\start_web_windows.ps1" -OpenBrowser

if errorlevel 1 (
  echo.
  echo [ERROR] Lead Radar stopped with an error.
  pause
)
