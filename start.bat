@echo off
setlocal

set "PYTHON_CMD="
python --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    py --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

%PYTHON_CMD% main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start. Make sure all packages are installed:
    echo   pip install -r requirements.txt
    echo.
    pause
)
