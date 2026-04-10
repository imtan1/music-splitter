@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ================================================
echo   音樂分源程式 — 一鍵環境安裝腳本
echo ================================================
echo.

:: ── 取得腳本所在目錄（requirements.txt 位置）──────────────────
set "SCRIPT_DIR=%~dp0"
set "REQ_FILE=%SCRIPT_DIR%requirements.txt"

if not exist "%REQ_FILE%" (
    echo [錯誤] 找不到 requirements.txt，請確認此腳本與專案檔案在同一資料夾。
    goto :fail
)

:: ════════════════════════════════════════════════
:: [1] 檢查 Python 3.10+
:: ════════════════════════════════════════════════
echo [1/5] 檢查 Python...

set "PYTHON_CMD="
for %%c in (python py python3) do (
    if "!PYTHON_CMD!"=="" (
        %%c --version >nul 2>&1
        if !errorlevel!==0 (
            set "PYTHON_CMD=%%c"
        )
    )
)

if "!PYTHON_CMD!"=="" (
    echo       找不到 Python，正在自動安裝 Python 3.11...
    winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if !errorlevel! neq 0 (
        echo [錯誤] Python 安裝失敗。請前往 https://www.python.org/downloads/ 手動安裝後重新執行此腳本。
        goto :fail
    )
    :: 重新整理 PATH 後再偵測
    for /f "tokens=*" %%p in ('where python 2^>nul') do set "PYTHON_CMD=python"
    if "!PYTHON_CMD!"=="" (
        echo [錯誤] Python 安裝後仍無法偵測，請重新開啟命令提示字元後再執行此腳本。
        goto :fail
    )
)

:: 取得版本號並確認 >= 3.10
for /f "tokens=2" %%v in ('!PYTHON_CMD! --version 2^>^&1') do set "PY_VER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)
if !PY_MAJOR! LSS 3 (
    echo [錯誤] Python 版本 !PY_VER! 太舊，需要 3.10 以上。
    goto :fail
)
if !PY_MAJOR!==3 if !PY_MINOR! LSS 10 (
    echo [錯誤] Python 版本 !PY_VER! 太舊，需要 3.10 以上。
    goto :fail
)
echo       ✔ Python !PY_VER! 已安裝

:: ════════════════════════════════════════════════
:: [2] 檢查 FFmpeg
:: ════════════════════════════════════════════════
echo [2/5] 檢查 FFmpeg...

set "FFMPEG_OK=0"
ffmpeg -version >nul 2>&1
if !errorlevel!==0 set "FFMPEG_OK=1"

if "!FFMPEG_OK!"=="0" (
    if exist "C:\ffmpeg\bin\ffmpeg.exe" (
        set "FFMPEG_OK=1"
        set "PATH=C:\ffmpeg\bin;!PATH!"
        echo       ✔ FFmpeg 在 C:\ffmpeg\bin（已加入此次 PATH）
    )
)

if "!FFMPEG_OK!"=="0" (
    echo       找不到 FFmpeg，正在自動安裝...
    winget install --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
    if !errorlevel! neq 0 (
        echo [錯誤] FFmpeg 安裝失敗（winget 可能不可用）。
        echo        請手動執行：winget install ffmpeg
        goto :fail
    )
    echo       ✔ FFmpeg 安裝完成
) else (
    if "!FFMPEG_OK!"=="1" (
        echo       ✔ FFmpeg 已安裝
    )
)

:: ════════════════════════════════════════════════
:: [3] 偵測 NVIDIA GPU → 決定 PyTorch 版本
:: ════════════════════════════════════════════════
echo [3/5] 偵測 GPU...

set "HAS_CUDA=0"
nvidia-smi >nul 2>&1
if !errorlevel!==0 (
    set "HAS_CUDA=1"
    for /f "tokens=*" %%g in ('nvidia-smi --query-gpu=name --format=csv^,noheader 2^>nul') do (
        echo       ✔ 偵測到 NVIDIA GPU：%%g
    )
    echo       將安裝 CUDA 版 PyTorch（GPU 加速，速度提升 10-20 倍）
) else (
    echo       未偵測到 NVIDIA GPU，將使用 CPU 版 PyTorch
)

if "!HAS_CUDA!"=="1" (
    echo       正在安裝 CUDA 版 PyTorch...
    !PYTHON_CMD! -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
    if !errorlevel! neq 0 (
        echo [警告] CUDA 版 PyTorch 安裝失敗，將改用 CPU 版。
    ) else (
        echo       ✔ CUDA 版 PyTorch 安裝完成
    )
)

:: ════════════════════════════════════════════════
:: [4] 安裝所有 pip 套件
:: ════════════════════════════════════════════════
echo [4/5] 安裝 Python 套件（已安裝的會自動跳過）...
echo       這個步驟首次執行需要下載 PyTorch / Demucs 等大型套件，請耐心等待...
echo.

!PYTHON_CMD! -m pip install -r "%REQ_FILE%" --quiet
if !errorlevel! neq 0 (
    echo [錯誤] 套件安裝失敗，請確認網路連線正常後重新執行。
    goto :fail
)
echo       ✔ 所有套件安裝完成

:: ════════════════════════════════════════════════
:: [5] 驗證關鍵套件可正常匯入
:: ════════════════════════════════════════════════
echo [5/5] 驗證安裝結果...

!PYTHON_CMD! -c "import PySide6; print('  PySide6 OK')"
if !errorlevel! neq 0 ( echo [錯誤] PySide6 匯入失敗 & goto :fail )

!PYTHON_CMD! -c "import demucs; print('  demucs OK')"
if !errorlevel! neq 0 ( echo [錯誤] demucs 匯入失敗 & goto :fail )

!PYTHON_CMD! -c "import librosa; print('  librosa OK')"
if !errorlevel! neq 0 ( echo [錯誤] librosa 匯入失敗 & goto :fail )

!PYTHON_CMD! -c "import music21; print('  music21 OK')"
if !errorlevel! neq 0 ( echo [錯誤] music21 匯入失敗 & goto :fail )

!PYTHON_CMD! -c "import verovio; print('  verovio OK')"
if !errorlevel! neq 0 ( echo [錯誤] verovio 匯入失敗 & goto :fail )

echo.
echo ================================================
echo   ✅ 安裝完成！
echo.
echo   執行以下指令啟動程式：
echo     python main.py
echo.
echo   或直接雙擊「啟動.bat」
echo ================================================
echo.
pause
exit /b 0

:fail
echo.
echo ================================================
echo   ❌ 安裝未完成，請依照上方錯誤訊息處理後重新執行。
echo ================================================
echo.
pause
exit /b 1
