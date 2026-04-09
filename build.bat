@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================================
echo   音樂分源程式  Windows 建置腳本
echo ============================================================
echo.

set "INNO_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

:: ──────────────────────────────────────────────
:: Step 1：檢查 Python
:: ──────────────────────────────────────────────
echo [1/6] 檢查 Python 環境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 Python，請確認已安裝 Python 3.10+ 並加入 PATH
    pause & exit /b 1
)
python --version

:: ──────────────────────────────────────────────
:: Step 2：安裝 PyInstaller
:: ──────────────────────────────────────────────
echo.
echo [2/6] 安裝 PyInstaller...
pip install --upgrade pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [錯誤] PyInstaller 安裝失敗
    pause & exit /b 1
)
echo     PyInstaller 就緒

:: ──────────────────────────────────────────────
:: Step 3：清除舊的 build / dist
:: ──────────────────────────────────────────────
echo.
echo [3/6] 清除舊的建置資料...
if exist "build"              rmdir /s /q "build"
if exist "dist\MusicSplitter" rmdir /s /q "dist\MusicSplitter"
echo     清除完成

:: ──────────────────────────────────────────────
:: Step 4：PyInstaller 打包
:: ──────────────────────────────────────────────
echo.
echo [4/6] 執行 PyInstaller 打包（可能需要 10~20 分鐘）...
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
:: Step 5：下載並放入 FFmpeg
:: ──────────────────────────────────────────────
echo.
echo [5/6] 處理 FFmpeg...

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

:: 嘗試用 winget 安裝（會加入 PATH，下次就能從 PATH 找到）
echo     系統未安裝 FFmpeg，嘗試自動下載...
winget install --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements >nul 2>&1
if not errorlevel 1 (
    :: winget 安裝後重新整理 PATH
    for /f "tokens=*" %%i in ('where ffmpeg 2^>nul') do set "SYS_FFMPEG=%%i"
    if defined SYS_FFMPEG (
        copy /y "!SYS_FFMPEG!" "%FFMPEG_DEST%" >nul
        echo     FFmpeg 已安裝並加入打包資料夾
        goto ffmpeg_done
    )
)

:: 若以上皆失敗，提示手動放置
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
:: Step 6：建立 ZIP 或 Inno Setup 安裝檔
:: ──────────────────────────────────────────────
echo.
echo [6/6] 建立發布套件...

:: 優先嘗試 Inno Setup
if exist "%INNO_PATH%" (
    echo     使用 Inno Setup 建立安裝檔...
    if not exist "dist\installer" mkdir "dist\installer"
    "%INNO_PATH%" installer.iss
    if not errorlevel 1 (
        echo.
        echo ============================================================
        echo   建置完成！
        echo   安裝檔：dist\installer\音樂分源程式_安裝檔_v1.0.0.exe
        echo ============================================================
        pause & exit /b 0
    )
)

:: Inno Setup 不存在就改用 PowerShell 壓 ZIP
echo     Inno Setup 未安裝，改為建立 ZIP 壓縮檔...
if not exist "dist\release" mkdir "dist\release"
powershell -Command "Compress-Archive -Path 'dist\MusicSplitter' -DestinationPath 'dist\release\音樂分源程式_v1.0.0.zip' -Force"

if errorlevel 1 (
    echo [錯誤] ZIP 建立失敗
    pause & exit /b 1
)

echo.
echo ============================================================
echo   建置完成！
echo   ZIP 檔案：dist\release\音樂分源程式_v1.0.0.zip
echo   使用方式：解壓後直接執行 MusicSplitter.exe
echo ============================================================
echo.
pause
