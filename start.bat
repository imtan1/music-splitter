@echo off
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start. Make sure all packages are installed:
    echo   pip install -r requirements.txt
    echo.
    pause
)
