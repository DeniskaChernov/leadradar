@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0scripts\start_cloudflare_windows.ps1" -OpenBrowser
if errorlevel 1 pause
