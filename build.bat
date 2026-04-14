@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================================
echo   音樂分源程式  Windows 建置腳本
echo ============================================================
echo.

:: ──────────────────────────────────────────────
:: 選擇建置版本
:: ──────────────────────────────────────────────
echo 請選擇打包版本：
echo   [1] CPU 版（約 700 MB，所有電腦適用，分源速度較慢）
echo   [2] GPU 版（約 1.6 GB，需 NVIDIA GPU，分源速度快 10-20 倍）
echo.
set /p BUILD_TYPE="請輸入 1 或 2："

if "%BUILD_TYPE%"=="1" (
    set "VERSION_SUFFIX=CPU"
    set "BUILD_LABEL=CPU 版"
    set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
) else if "%BUILD_TYPE%"=="2" (
    set "VERSION_SUFFIX=GPU"
    set "BUILD_LABEL=GPU ^(CUDA^) 版"
    set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
) else (
    echo [錯誤] 無效的選擇，請輸入 1 或 2
    pause & exit /b 1
)

echo.
echo 將建置：%BUILD_LABEL%
echo.

set "INNO_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set "APP_DIR=%~dp0"
set "APP_VERSION=1.1.0"
cd /d "%APP_DIR%"

:: ──────────────────────────────────────────────
:: Step 1：檢查 Python
:: ──────────────────────────────────────────────
echo [1/7] 檢查 Python 環境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請確認已安裝 Python 3.10+ 並加入 PATH
    pause & exit /b 1
)
python --version

:: ──────────────────────────────────────────────
:: Step 2：安裝對應版本的 PyTorch
:: ──────────────────────────────────────────────
echo.
echo [2/7] 安裝 %BUILD_LABEL% PyTorch...
pip install torch torchaudio --index-url "%TORCH_INDEX%" --quiet
if errorlevel 1 (
    echo [錯誤] PyTorch 安裝失敗，請檢查網路連線
    pause & exit /b 1
)
echo     PyTorch ^(%BUILD_LABEL%^) 就緒

:: ──────────────────────────────────────────────
:: Step 3：安裝 PyInstaller
:: ──────────────────────────────────────────────
echo.
echo [3/7] 安裝 PyInstaller...
pip install --upgrade pyinstaller --quiet
if errorlevel 1 (
    echo [錯誤] PyInstaller 安裝失敗
    pause & exit /b 1
)
echo     PyInstaller 就緒

:: ──────────────────────────────────────────────
:: Step 4：清除舊的 build / dist
:: ──────────────────────────────────────────────
echo.
echo [4/7] 清除舊的建置資料...
if exist "build"              rmdir /s /q "build"
if exist "dist\MusicSplitter" rmdir /s /q "dist\MusicSplitter"
echo     清除完成

:: ──────────────────────────────────────────────
:: Step 5：PyInstaller 打包
:: ──────────────────────────────────────────────
echo.
echo [5/7] 執行 PyInstaller 打包（可能需要 10~20 分鐘）...
echo.

pyinstaller build.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo [錯誤] PyInstaller 打包失敗，請檢查上方錯誤訊息
    pause & exit /b 1
)
echo.
echo     打包成功！

:: ──────────────────────────────────────────────
:: Step 6：下載並放入 FFmpeg
:: ──────────────────────────────────────────────
echo.
echo [6/7] 處理 FFmpeg...

set "FFMPEG_DEST=dist\MusicSplitter\ffmpeg.exe"

:: 先檢查是否已有本地的 ffmpeg.exe（手動放置）
if exist "ffmpeg.exe" (
    echo     發現本地 ffmpeg.exe，複製到打包資料夾...
    copy /y "ffmpeg.exe" "%FFMPEG_DEST%" >nul
    goto ffmpeg_done
)

:: 檢查系統是否已安裝 ffmpeg
where ffmpeg >nul 2>&1
if not errorlevel 1 (
    echo     從系統 PATH 複製 ffmpeg...
    for /f "tokens=*" %%i in ('where ffmpeg') do set "SYS_FFMPEG=%%i"
    copy /y "!SYS_FFMPEG!" "%FFMPEG_DEST%" >nul
    goto ffmpeg_done
)

:: 嘗試用 winget 安裝
echo     系統未安裝 FFmpeg，嘗試自動下載...
winget install --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('where ffmpeg 2^>nul') do set "SYS_FFMPEG=%%i"
    if defined SYS_FFMPEG (
        copy /y "!SYS_FFMPEG!" "%FFMPEG_DEST%" >nul
        echo     FFmpeg 已安裝並加入打包資料夾
        goto ffmpeg_done
    )
)

echo.
echo [警告] 無法自動取得 FFmpeg。
echo        MP3 下載功能需要 ffmpeg.exe，請手動操作：
echo.
echo        方法一（推薦）：
echo          1. 執行：winget install ffmpeg
echo          2. 將 ffmpeg.exe 複製到 dist\MusicSplitter\
echo.
echo        方法二：
echo          1. 至 https://github.com/BtbN/FFmpeg-Builds/releases
echo             下載 ffmpeg-master-latest-win64-gpl.zip
echo          2. 解壓後將 bin\ffmpeg.exe 複製到 dist\MusicSplitter\
echo.
echo        其他功能（分源、播放、簡譜）不受影響，可繼續使用。
echo.

:ffmpeg_done

:: ──────────────────────────────────────────────
:: Step 7：建立 ZIP 或 Inno Setup 安裝檔
:: ──────────────────────────────────────────────
echo.
echo [7/7] 建立發布套件...

set "OUT_NAME=音樂分源程式_安裝檔_v%APP_VERSION%_%VERSION_SUFFIX%"
set "ZIP_NAME=音樂分源程式_v%APP_VERSION%_%VERSION_SUFFIX%"

:: 優先嘗試 Inno Setup
if exist "%INNO_PATH%" (
    echo     使用 Inno Setup 建立安裝檔...
    if not exist "dist\installer" mkdir "dist\installer"
    "%INNO_PATH%" installer.iss /DVersionSuffix=%VERSION_SUFFIX%
    if not errorlevel 1 (
        echo.
        echo ============================================================
        echo   建置完成！[%BUILD_LABEL%]
        echo   安裝檔：dist\installer\%OUT_NAME%.exe
        echo ============================================================
        pause & exit /b 0
    )
)

:: Inno Setup 不存在就改用 PowerShell 壓 ZIP
echo     Inno Setup 未安裝，改為建立 ZIP 壓縮檔...
if not exist "dist\release" mkdir "dist\release"
powershell -Command "Compress-Archive -Path 'dist\MusicSplitter' -DestinationPath 'dist\release\%ZIP_NAME%.zip' -Force"

if errorlevel 1 (
    echo [錯誤] ZIP 建立失敗
    pause & exit /b 1
)

echo.
echo ============================================================
echo   建置完成！[%BUILD_LABEL%]
echo   ZIP 檔案：dist\release\%ZIP_NAME%.zip
echo   使用方式：解壓後直接執行 MusicSplitter.exe
echo ============================================================
echo.
pause
