@echo off
setlocal EnableDelayedExpansion

echo ============================================================
echo   MusicSplitter - Windows Build Script
echo ============================================================
echo.

echo Select build type:
echo   [1] CPU  ~700 MB   (All PCs)
echo   [2] GPU  ~1.6 GB   (Requires NVIDIA GPU)
echo.
set /p BUILD_TYPE="Enter 1 or 2: "

if "%BUILD_TYPE%"=="1" (
    set "VERSION_SUFFIX=CPU"
    set "BUILD_LABEL=CPU"
    set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
) else if "%BUILD_TYPE%"=="2" (
    set "VERSION_SUFFIX=GPU"
    set "BUILD_LABEL=GPU (CUDA)"
    set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
) else (
    echo [ERROR] Invalid choice. Please enter 1 or 2.
    pause & exit /b 1
)

echo.
echo Building: %BUILD_LABEL%
echo.

set "APP_DIR=%~dp0"
set "APP_VERSION=1.1.0"
cd /d "%APP_DIR%"

echo [1/5] Checking Python...
set "PYTHON_CMD="
python --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    py --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    pause & exit /b 1
)

%PYTHON_CMD% --version

echo.
echo [2/5] Installing %BUILD_LABEL% PyTorch...
%PYTHON_CMD% -m pip install torch torchaudio --index-url "%TORCH_INDEX%" --quiet
if errorlevel 1 (
    echo [ERROR] PyTorch installation failed. Check network connection.
    pause & exit /b 1
)
echo     PyTorch (%BUILD_LABEL%) ready

echo.
echo [3/5] Installing PyInstaller...
%PYTHON_CMD% -m pip install --upgrade pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] PyInstaller installation failed.
    pause & exit /b 1
)
echo     PyInstaller ready

echo.
echo [4/5] Cleaning old build artifacts...
if exist "build"              rmdir /s /q "build"
if exist "dist\MusicSplitter" rmdir /s /q "dist\MusicSplitter"
echo     Clean done

echo.
echo [5/5] Running PyInstaller (may take 10-20 minutes)...
echo.

%PYTHON_CMD% -m PyInstaller build.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. See errors above.
    pause & exit /b 1
)
echo.
echo     Build successful!

echo.
echo --- FFmpeg ---
set "FFMPEG_DEST=dist\MusicSplitter\ffmpeg.exe"

if exist "ffmpeg.exe" (
    echo     Found local ffmpeg.exe, copying...
    copy /y "ffmpeg.exe" "%FFMPEG_DEST%" >nul
    goto ffmpeg_done
)

for /f "usebackq delims=" %%i in (`powershell -ExecutionPolicy Bypass -Command "(Get-Command ffmpeg -ErrorAction SilentlyContinue).Source"`) do set "SYS_FFMPEG=%%i"
if defined SYS_FFMPEG (
    echo     Copying ffmpeg from system PATH...
    copy /y "!SYS_FFMPEG!" "%FFMPEG_DEST%" >nul
    goto ffmpeg_done
)

echo     FFmpeg not found locally. Trying winget...
winget install --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('where ffmpeg 2^>nul') do set "SYS_FFMPEG=%%i"
    if defined SYS_FFMPEG (
        copy /y "!SYS_FFMPEG!" "%FFMPEG_DEST%" >nul
        echo     FFmpeg installed and copied.
        goto ffmpeg_done
    )
)

echo.
echo [WARNING] FFmpeg not found. MP3 export will not work.
echo    Option 1: Run "winget install ffmpeg", then copy ffmpeg.exe to dist\MusicSplitter\
echo    Option 2: Download from https://github.com/BtbN/FFmpeg-Builds/releases
echo              Extract bin\ffmpeg.exe to dist\MusicSplitter\
echo    Other features (stem separation, playback, notation) are unaffected.
echo.

:ffmpeg_done

echo.
echo ============================================================
echo   Build complete! [%BUILD_LABEL%]
echo   Output: dist\MusicSplitter\MusicSplitter.exe
echo ============================================================
echo.
pause
