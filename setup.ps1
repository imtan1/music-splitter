param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step { param($n,$msg) Write-Host "[$n/5] $msg" -ForegroundColor Yellow }
function Ok   { param($msg) Write-Host "      [OK] $msg" -ForegroundColor Green }
function Info { param($msg) Write-Host "      ... $msg" -ForegroundColor Gray }
function Warn { param($msg) Write-Host "      [!] $msg" -ForegroundColor DarkYellow }
function Fail {
    param($msg)
    Write-Host ""
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
function TryRun {
    param([string]$exe, [string[]]$a)
    try { $o = & $exe @a 2>&1; return ($LASTEXITCODE -eq 0), $o }
    catch { return $false, $_.ToString() }
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Music Splitter - Auto Install" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ==============================================================
# [1] Python 3.10+
# ==============================================================
Step 1 "Checking Python..."

$PyCmd = $null
foreach ($c in @("python","py","python3")) {
    try {
        $v = & $c --version 2>&1
        if ($LASTEXITCODE -eq 0 -and "$v" -match "Python (\d+)\.(\d+)") {
            $mj = [int]$Matches[1]; $mn = [int]$Matches[2]
            if ($mj -gt 3 -or ($mj -eq 3 -and $mn -ge 10)) {
                $PyCmd = $c
                Ok "Python $mj.$mn found"
                break
            } else {
                Warn "Python $mj.$mn is too old (need 3.10+)"
            }
        }
    } catch {}
}

if (-not $PyCmd) {
    Info "Python not found, installing Python 3.11 via winget..."
    $ok, $out = TryRun "winget" @("install","--id","Python.Python.3.11","--silent","--accept-package-agreements","--accept-source-agreements")
    if (-not $ok) { Fail "Python install failed. Please install manually from https://www.python.org/downloads/" }

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    try {
        $v = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) { $PyCmd = "python"; Ok "Python installed: $v" }
    } catch {}
    if (-not $PyCmd) { Fail "Python installed but still not detected. Please reopen terminal and run again." }
}

# ==============================================================
# [2] FFmpeg
# ==============================================================
Step 2 "Checking FFmpeg..."

$FfOk = $false
$ok2, $null = TryRun "ffmpeg" @("-version")
if ($ok2) { $FfOk = $true; Ok "FFmpeg found in PATH" }

if (-not $FfOk -and (Test-Path "C:\ffmpeg\bin\ffmpeg.exe")) {
    $env:Path = "C:\ffmpeg\bin;" + $env:Path
    $FfOk = $true
    Ok "FFmpeg found at C:\ffmpeg\bin"
}

if (-not $FfOk) {
    Info "FFmpeg not found, installing via winget..."
    $ok2, $out = TryRun "winget" @("install","--id","Gyan.FFmpeg","--silent","--accept-package-agreements","--accept-source-agreements")
    if (-not $ok2) { Fail "FFmpeg install failed. Please run: winget install ffmpeg" }
    Ok "FFmpeg installed"
}

# ==============================================================
# [3] NVIDIA GPU detection
# ==============================================================
Step 3 "Detecting GPU..."

$HasGpu = $false
$ok3, $gpuOut = TryRun "nvidia-smi" @("--query-gpu=name","--format=csv,noheader")
if ($ok3 -and $gpuOut) {
    $HasGpu = $true
    Ok "NVIDIA GPU: $($gpuOut.ToString().Trim())"
    Info "Will install CUDA PyTorch (GPU acceleration, 10-20x faster)"
} else {
    Ok "No NVIDIA GPU detected, using CPU PyTorch"
}

if ($HasGpu) {
    Info "Installing CUDA PyTorch..."
    $cudaUrl = "https://download.pytorch.org/whl/cu121"
    & $PyCmd -m pip install torch torchaudio --index-url $cudaUrl --quiet
    if ($LASTEXITCODE -eq 0) { Ok "CUDA PyTorch installed" }
    else { Warn "CUDA PyTorch failed, will fall back to CPU version" }
}

# ==============================================================
# [4] pip packages
# ==============================================================
Step 4 "Installing pip packages (already-installed ones will be skipped)..."
Info "First run may take 10-30 minutes (downloading PyTorch, Demucs etc)..."
Write-Host ""

$ReqFile = Join-Path $ScriptDir "requirements.txt"
if (-not (Test-Path $ReqFile)) { Fail "requirements.txt not found. Make sure this script is in the project folder." }

& $PyCmd -m pip install -r $ReqFile
if ($LASTEXITCODE -ne 0) { Fail "Package install failed. Check your internet connection and try again." }
Ok "All packages installed"

# ==============================================================
# [5] Verify imports
# ==============================================================
Step 5 "Verifying installation..."

$allOk = $true
foreach ($mod in @("PySide6","demucs","librosa","music21","verovio")) {
    & $PyCmd -c "import $mod" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok $mod }
    else {
        Write-Host "      [FAIL] $mod import failed" -ForegroundColor Red
        $allOk = $false
    }
}

Write-Host ""
if ($allOk) {
    Write-Host "================================================" -ForegroundColor Green
    Write-Host "  Install complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Run the app:  python main.py" -ForegroundColor White
    Write-Host "  Or double-click start.bat" -ForegroundColor White
    Write-Host "================================================" -ForegroundColor Green
} else {
    Fail "Some packages failed. Try running: pip install -r requirements.txt"
}

Write-Host ""
Read-Host "Press Enter to exit"
