@echo off
rem Double-click: deploy the code to Azure and check the live site. See ship.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ship.ps1"
echo.
pause
