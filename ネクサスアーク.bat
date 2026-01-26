@echo off
cd /d "%~dp0"

echo ---------------------------------------------------
echo  Nexus Ark Launching...
echo ---------------------------------------------------

if exist "venv\Scripts\python.exe" (
    echo [INFO] Virtual Environment found.
    echo [INFO] Starting with venv python...
    "venv\Scripts\python.exe" nexus_ark.py
) else (
    echo [WARNING] venv folder not found.
    echo [INFO] Starting with system python...
    python nexus_ark.py
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] An error occurred.
)

echo.
echo ---------------------------------------------------
echo  Application Closed.
echo ---------------------------------------------------
pause