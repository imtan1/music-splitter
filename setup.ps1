# 音樂分源程式 — 一鍵環境安裝腳本
# 支援 Windows 10/11，需要 winget（Windows 套件管理員）

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  音樂分源程式 — 一鍵環境安裝腳本" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ─── 輔助函式 ─────────────────────────────────────────

function Step($n, $msg) {
    Write-Host "[$n/5] $msg" -ForegroundColor Yellow
}

function Ok($msg) {
    Write-Host "      ✔ $msg" -ForegroundColor Green
}

function Info($msg) {
    Write-Host "      $msg" -ForegroundColor Gray
}

function Fail($msg) {
    Write-Host ""
    Write-Host "[錯誤] $msg" -ForegroundColor Red
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Red
    Write-Host "  安裝未完成，請依照上方錯誤訊息處理後重新執行。" -ForegroundColor Red
    Write-Host "================================================" -ForegroundColor Red
    exit 1
}

function RunCmd($cmd, $args) {
    $result = & $cmd @args 2>&1
    return $LASTEXITCODE, $result
}

# ════════════════════════════════════════════════
# [1] 檢查 Python 3.10+
# ════════════════════════════════════════════════
Step 1 "檢查 Python..."

$PythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $PythonCmd = $cmd
                Ok "Python $($ver -replace 'Python ','') 已安裝"
                break
            }
        }
    } catch {}
}

if (-not $PythonCmd) {
    Info "找不到 Python 3.10+，正在自動安裝 Python 3.11..."
    try {
        winget install --id Python.Python.3.11 --silent `
            --accept-package-agreements --accept-source-agreements
    } catch {
        Fail "Python 安裝失敗：$_`n請前往 https://www.python.org/downloads/ 手動安裝後重試。"
    }
    # 重新整理 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    try {
        $ver = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) { $PythonCmd = "python"; Ok "Python 安裝完成：$ver" }
    } catch {}
    if (-not $PythonCmd) {
        Fail "Python 安裝後仍無法偵測，請重新開啟命令提示字元後再執行此腳本。"
    }
}

# ════════════════════════════════════════════════
# [2] 檢查 FFmpeg
# ════════════════════════════════════════════════
Step 2 "檢查 FFmpeg..."

$FFmpegOk = $false

# 檢查 PATH
try {
    & ffmpeg -version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $FFmpegOk = $true }
} catch {}

# 檢查 C:\ffmpeg\bin
if (-not $FFmpegOk -and (Test-Path "C:\ffmpeg\bin\ffmpeg.exe")) {
    $env:Path = "C:\ffmpeg\bin;" + $env:Path
    $FFmpegOk = $true
    Ok "FFmpeg 在 C:\ffmpeg\bin（已加入此次 PATH）"
}

if ($FFmpegOk) {
    if (-not (Test-Path "C:\ffmpeg\bin\ffmpeg.exe")) {
        Ok "FFmpeg 已安裝"
    }
} else {
    Info "找不到 FFmpeg，正在自動安裝..."
    try {
        winget install --id Gyan.FFmpeg --silent `
            --accept-package-agreements --accept-source-agreements
        Ok "FFmpeg 安裝完成"
    } catch {
        Fail "FFmpeg 安裝失敗（winget 可能不可用）：$_`n請手動執行：winget install ffmpeg"
    }
}

# ════════════════════════════════════════════════
# [3] 偵測 NVIDIA GPU → 決定 PyTorch 版本
# ════════════════════════════════════════════════
Step 3 "偵測 GPU..."

$HasCuda = $false
try {
    $gpuInfo = & nvidia-smi --query-gpu=name --format=csv,noheader 2>&1
    if ($LASTEXITCODE -eq 0 -and $gpuInfo) {
        $HasCuda = $true
        Ok "偵測到 NVIDIA GPU：$($gpuInfo.Trim())"
        Info "將安裝 CUDA 版 PyTorch（GPU 加速，速度提升 10–20 倍）"
    }
} catch {}

if (-not $HasCuda) {
    Ok "未偵測到 NVIDIA GPU，使用 CPU 版 PyTorch"
}

if ($HasCuda) {
    Info "正在安裝 CUDA 版 PyTorch..."
    $cudaUrl = "https://download.pytorch.org/whl/cu121"
    & $PythonCmd -m pip install torch torchaudio --index-url $cudaUrl --quiet
    if ($LASTEXITCODE -eq 0) {
        Ok "CUDA 版 PyTorch 安裝完成"
    } else {
        Write-Host "      [警告] CUDA 版 PyTorch 安裝失敗，將改用 CPU 版。" -ForegroundColor DarkYellow
    }
}

# ════════════════════════════════════════════════
# [4] 安裝所有 pip 套件
# ════════════════════════════════════════════════
Step 4 "安裝 Python 套件（已安裝的會自動跳過）..."
Info "首次執行需下載 PyTorch、Demucs 等大型套件，請耐心等待..."
Write-Host ""

$ReqFile = Join-Path $ScriptDir "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    Fail "找不到 requirements.txt，請確認腳本與專案檔案在同一資料夾。"
}

& $PythonCmd -m pip install -r $ReqFile
if ($LASTEXITCODE -ne 0) {
    Fail "套件安裝失敗，請確認網路連線正常後重新執行。"
}
Ok "所有套件安裝完成"

# ════════════════════════════════════════════════
# [5] 驗證關鍵套件可正常匯入
# ════════════════════════════════════════════════
Step 5 "驗證安裝結果..."

$packages = @(
    @{ name = "PySide6";  import = "PySide6"  },
    @{ name = "demucs";   import = "demucs"   },
    @{ name = "librosa";  import = "librosa"  },
    @{ name = "music21";  import = "music21"  },
    @{ name = "verovio";  import = "verovio"  }
)

$allOk = $true
foreach ($pkg in $packages) {
    & $PythonCmd -c "import $($pkg.import)" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Ok "$($pkg.name) ✔"
    } else {
        Write-Host "      ✘ $($pkg.name) 匯入失敗" -ForegroundColor Red
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "  ✅ 安裝完成！" -ForegroundColor Green
    Write-Host "" -ForegroundColor Green
    Write-Host "  執行以下指令啟動程式：" -ForegroundColor Green
    Write-Host "    python main.py" -ForegroundColor White
    Write-Host "" -ForegroundColor Green
    Write-Host "  或直接雙擊「啟動.bat」" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
} else {
    Fail "部分套件驗證失敗，請重新執行此腳本或手動執行 pip install -r requirements.txt"
}
