#!/bin/bash
# ============================================================================
# Worker Activity Tracker - Start Worker App
# ============================================================================
# This script starts the Worker application that captures screenshots
# and sends activity data to the Admin Server
# ============================================================================

echo ""
echo "========================================"
echo "  Worker Activity Tracker - Worker App"
echo "========================================"
echo ""

# Get script directory
cd "$(dirname "$0")" || exit 1

# Check if the compiled executable exists
if [ -f "dist/gui" ]; then
    echo "[INFO] Found compiled worker executable."
    echo "[INFO] Starting worker app from compiled binary..."
    echo ""
    echo "========================================"
    echo "  Starting Worker Application"
    echo "========================================"
    echo ""
    echo "[INFO] Connects to Admin API at: http://localhost:5000"
    echo "[INFO] Worker API available at: http://localhost:5001"
    echo ""
    echo "[INFO] Starting... Press Ctrl+C to stop."
    echo ""
    ./dist/gui &
    exit 0
fi

# If no compiled binary, try to run from source
echo "[INFO] No compiled binary found, running from source..."
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found! Please install Python 3.8+ first."
    echo "Install with: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "[INFO] Creating Python virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment!"
        exit 1
    fi
fi

# Activate virtual environment
echo "[INFO] Activating virtual environment..."
source venv/bin/activate

# Install dependencies if needed
if [ ! -f "venv/.installed" ]; then
    echo "[INFO] Installing Python dependencies..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install dependencies!"
        exit 1
    fi
    touch venv/.installed
    echo "[INFO] Dependencies installed successfully."
fi

# Check if Admin API is running
echo ""
echo "[INFO] Checking if Admin API is available..."
if ! curl -s --max-time 2 http://localhost:5000/api/admin/health &> /dev/null; then
    echo "[WARNING] Admin API is not running!"
    echo "[WARNING] Worker may not function properly without Admin API."
    echo "[INFO] Please start the Admin Server first using:"
    echo "         ../docker-db/start_admin_server.sh"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Load environment variables
if [ -f ".env" ]; then
    echo "[INFO] Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# Clear screen and show startup info
clear
echo ""
echo "========================================"
echo "  Worker Activity Tracker - Worker App"
echo "========================================"
echo ""
echo "[INFO] Starting Worker Application..."
echo ""
echo "Features:"
echo "  - Worker Login: http://localhost:5001"
echo "  - Admin API:    http://localhost:5000"
echo "  - Screenshot Capture: Every 5 minutes (configurable)"
echo ""
echo "Instructions:"
echo "  1. Login with your Worker ID and Password"
echo "  2. Click 'Clock In' to start activity tracking"
echo "  3. Screenshots will be captured automatically"
echo "  4. Click 'Clock Out' when done working"
echo ""
echo "========================================"
echo ""
echo "[INFO] Starting... Press Ctrl+C to stop."
echo ""

# Start the worker GUI
python gui.py
