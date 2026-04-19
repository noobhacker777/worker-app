@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: Worker Activity Tracker - Start Worker App
:: ============================================================================
:: This script starts the Worker application that captures screenshots
:: and sends activity data to the Admin Server
:: ============================================================================

echo.
echo ========================================
echo   Worker Activity Tracker - Worker App
echo ========================================
echo.

cd /d "%~dp0"

:: Check if the compiled executable exists
if exist "dist\gui.exe" (
    echo [INFO] Found compiled worker executable.
    echo [INFO] Starting worker app from compiled .exe...
    echo.
    echo ========================================
    echo   Starting Worker Application
    echo ========================================
    echo.
    echo [INFO] Connects to Admin API at: http://localhost:5000
    echo [INFO] Worker API available at: http://localhost:5001
    echo.
    echo [INFO] Starting... Press Ctrl+C to stop.
    echo.
    start "" "dist\gui.exe"
    exit /b 0
)

:: If no compiled exe, try to run from source
echo [INFO] No compiled executable found, running from source...
echo.

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.8+ first.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check if virtual environment exists
if not exist "venv\" (
    echo [INFO] Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
)

:: Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

:: Install dependencies if needed
if not exist "venv\.installed" (
    echo [INFO] Installing Python dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies!
        pause
        exit /b 1
    )
    echo. > venv\.installed
    echo [INFO] Dependencies installed successfully.
)

:: Check if Admin API is running
echo.
echo [INFO] Checking if Admin API is available...
curl -s --max-time 2 http://localhost:5000/api/admin/health >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Admin API is not running!
    echo [WARNING] Worker may not function properly without Admin API.
    echo [INFO] Please start the Admin Server first using:
    echo         ..\docker-db\start_admin_server.bat
    echo.
    choice /M "Continue anyway"
    if errorlevel 2 exit /b 1
)

:: Set environment variables
if exist ".env" (
    echo [INFO] Loading environment variables from .env file...
    for /f "tokens=* delims=" %%a in (.env) do (
        set "%%a"
    )
)

:: Clear screen and show startup info
cls
echo.
echo ========================================
echo   Worker Activity Tracker - Worker App
echo ========================================
echo.
echo [INFO] Starting Worker Application...
echo.
echo Features:
echo   - Worker Login: http://localhost:5001
echo   - Admin API:    http://localhost:5000
echo   - Screenshot Capture: Every 5 minutes (configurable)
echo.
echo Instructions:
echo   1. Login with your Worker ID and Password
echo   2. Click 'Clock In' to start activity tracking
echo   3. Screenshots will be captured automatically
echo   4. Click 'Clock Out' when done working
echo.
echo ========================================
echo.
echo [INFO] Starting... Press Ctrl+C to stop.
echo.

:: Start the worker GUI
python gui.py

pause
