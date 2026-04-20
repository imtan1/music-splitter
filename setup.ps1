param()

# Auto-elevate to admin
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$pr = [Security.Principal.WindowsPrincipal]$id
$isAdmin = $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting administrator privileges..."
    $me = $MyInvocation.MyCommand.Path
    Start-Process powershell -Verb RunAs -ArgumentList ("-ExecutionPolicy Bypass -File `"" + $me + "`"")
    exit
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step { param($n,$msg) Write-Host "[$n/5] $msg" -ForegroundColor Yellow }
function Ok   { param($msg)    Write-Host "      [OK] $msg" -ForegroundColor Green }
function Info { param($msg)    Write-Host "      ... $msg" -ForegroundColor Gray }
function Warn { param($msg)    Write-Host "      [!]  $msg" -ForegroundColor DarkYellow }
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
    try {
        $o = & $exe @a 2>&1
        return ($LASTEXITCODE -eq 0), "$o"
    } catch {
        return $false, $_.ToString()
    }
}

function Download {
    param([string]$url, [string]$dest)
    Info "Downloading: $url"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        return $true
    } catch {
        Warn "Download failed: $_"
        return $false
    }
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
            $mj = [int]$Matches[1]
            $mn = [int]$Matches[2]
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
    Info "Python not found, downloading installer..."
    $pyExe = "$env:TEMP\python-3.11.9-amd64.exe"
    $dlOk = Download "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" $pyExe
    if ($dlOk -and (Test-Path $pyExe)) {
        Info "Running Python installer..."
        $p = Start-Process -FilePath $pyExe -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            Fail "Python installer failed (exit $($p.ExitCode)). Install manually: https://www.python.org/downloads/"
        }
        Remove-Item $pyExe -ErrorAction SilentlyContinue
        Ok "Python installed"
    } else {
        Fail "Cannot download Python. Install manually: https://www.python.org/downloads/"
    }

    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

    foreach ($c in @("python","py")) {
        try {
            $v = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) {
                $PyCmd = $c
                Ok "Python confirmed: $v"
                $pyPath = (Get-Command $c -ErrorAction SilentlyContinue).Source
                if ($pyPath) { Ok "Installed at: $(Split-Path -Parent $pyPath)" }
                break
            }
        } catch {}
    }

    if (-not $PyCmd) {
        Fail "Python installed but not detected. Close this window and run setup.bat again."
    }
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
    Info "FFmpeg not found, downloading directly..."
    $ffZip  = "$env:TEMP\ffmpeg.zip"
    $ffDest = "C:\ffmpeg"
    $dlOk = Download "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $ffZip

    if ($dlOk -and (Test-Path $ffZip)) {
        Info "Extracting FFmpeg to C:\ffmpeg ..."
        $ffTmp = "$env:TEMP\ffmpeg_extract"
        if (Test-Path $ffDest) { Remove-Item $ffDest -Recurse -Force }
        if (Test-Path $ffTmp)  { Remove-Item $ffTmp  -Recurse -Force }
        Expand-Archive -Path $ffZip -DestinationPath $ffTmp -Force
        $inner = Get-ChildItem $ffTmp -Directory | Select-Object -First 1
        Move-Item $inner.FullName $ffDest
        Remove-Item $ffZip -ErrorAction SilentlyContinue
        Remove-Item $ffTmp -Recurse -ErrorAction SilentlyContinue

        $syspath = [System.Environment]::GetEnvironmentVariable("Path","Machine")
        if ($syspath -notlike "*C:\ffmpeg\bin*") {
            [System.Environment]::SetEnvironmentVariable("Path","$syspath;C:\ffmpeg\bin","Machine")
        }
        $env:Path = "C:\ffmpeg\bin;" + $env:Path
        Ok "FFmpeg installed to C:\ffmpeg"
        Ok "Installed at: C:\ffmpeg\bin"
    } else {
        Fail "Cannot download FFmpeg. Install manually: https://ffmpeg.org/download.html"
    }
}

# ==============================================================
# [3] NVIDIA GPU detection
# ==============================================================
Step 3 "Detecting GPU..."

$HasGpu = $false
$ok3, $gpuOut = TryRun "nvidia-smi" @("--query-gpu=name","--format=csv,noheader")
if ($ok3 -and "$gpuOut".Trim() -ne "") {
    $HasGpu = $true
    Ok "NVIDIA GPU: $("$gpuOut".Trim())"
    Info "Will install CUDA PyTorch (10-20x faster)"
} else {
    Ok "No NVIDIA GPU, using CPU PyTorch"
}

if ($HasGpu) {
    Info "Installing CUDA PyTorch..."
    & $PyCmd -m pip install torch torchaudio --index-url "https://download.pytorch.org/whl/cu121" --quiet
    if ($LASTEXITCODE -eq 0) { Ok "CUDA PyTorch installed" }
    else { Warn "CUDA PyTorch failed, will use CPU version from requirements.txt" }
}

# ==============================================================
# [4] pip packages
# ==============================================================
Step 4 "Installing pip packages (skipping already-installed)..."
Info "First run may take 10-30 min (PyTorch + Demucs are large)..."
Write-Host ""

$ReqFile = Join-Path $ScriptDir "requirements.txt"
if (-not (Test-Path $ReqFile)) {
    Fail "requirements.txt not found. Make sure setup.ps1 is in the project folder."
}

& $PyCmd -m pip install -r $ReqFile
if ($LASTEXITCODE -ne 0) {
    Fail "Package install failed. Check internet connection and try again."
}
Ok "All packages installed"

# ==============================================================
# [5] Verify imports
# ==============================================================
Step 5 "Verifying installation..."

$allOk = $true
foreach ($mod in @("PySide6","demucs","librosa","music21","verovio","basic_pitch")) {
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
    Write-Host "  Run: python main.py" -ForegroundColor White
    Write-Host "  Or double-click start.bat" -ForegroundColor White
    Write-Host "================================================" -ForegroundColor Green
} else {
    Fail "Some packages failed. Try: pip install -r requirements.txt"
}

Write-Host ""
Read-Host "Press Enter to exit"
