@echo off
rem --- Nexus Ark Launcher (For Packaged Distribution) ---
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
title Nexus Ark

echo Starting Nexus Ark...
echo If the browser does not open automatically, please open it and navigate to: http://127.0.0.1:7860
echo Please keep this window open while the application is running.

rem --- Change directory to the script's own location ---
cd /d "%~dp0"

rem --- Execute python from the embedded environment ---
python\python.exe nexus_ark.py

echo.
echo The application has been closed. You can now close this window.
pause