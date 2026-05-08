<#
.SYNOPSIS
    End-to-end Windows build for Lyon Music Manager (Spotify branch).

.DESCRIPTION
    From a clean checkout, produces installer\Output\LyonMusicManager-Setup.exe.
    Steps: create Python 3.14 venv, install dependencies, download ffmpeg.exe
    and libdiscid.dll into bin\, run PyInstaller, run Inno Setup.

    Run from the project root:
        scripts\build-windows.ps1

    Optional flags:
        -SkipBinaries   Don't re-download ffmpeg / libdiscid if bin\ is already populated.
        -SkipInstaller  Build the bundle but don't run Inno Setup.
        -Clean          Wipe .venv, build\, dist\, installer\Output\ before building.

.NOTES
    Requires:
      - Python 3.14 64-bit on PATH (or the py launcher: py -3.14 ...).
      - Inno Setup 6 installed at the default location (unless -SkipInstaller).
#>
[CmdletBinding()]
param(
    [switch]$SkipBinaries,
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

# Resolve paths relative to the project root (one level up from this script).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $Root

Write-Host "==> Lyon Music Manager (Spotify branch) - Windows build" -ForegroundColor Green
Write-Host "    Project root: $Root"

# 0. Optional clean -----------------------------------------------------------
if ($Clean) {
    Write-Host "==> Cleaning previous build artefacts" -ForegroundColor Yellow
    foreach ($p in '.venv', 'build', 'dist', 'installer\Output') {
        $full = Join-Path $Root $p
        if (Test-Path $full) {
            Write-Host "    Removing $p"
            Remove-Item $full -Recurse -Force
        }
    }
}

# 1. Locate Python 3.14 -------------------------------------------------------
Write-Host "==> Locating Python 3.14" -ForegroundColor Cyan
$python = $null
try {
    & py -3.14 -c "import sys; print(sys.version)" | Out-Null
    if ($LASTEXITCODE -eq 0) { $python = 'py -3.14' }
} catch { }
if (-not $python) {
    try {
        $ver = & python --version 2>&1
        if ($ver -match '3\.14') { $python = 'python' }
    } catch { }
}
if (-not $python) {
    throw "Python 3.14 not found. Install from https://www.python.org/downloads/ and tick 'Add Python to PATH'."
}
Write-Host "    Using: $python"

# 2. Create venv --------------------------------------------------------------
Write-Host "==> Preparing virtual environment (.venv)" -ForegroundColor Cyan
if (-not (Test-Path '.venv')) {
    & cmd /c "$python -m venv .venv"
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
$venvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw "venv python not found at $venvPython" }

# 3. Install dependencies -----------------------------------------------------
Write-Host "==> Installing dependencies" -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPython -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt failed" }
& $venvPython -m pip install pyinstaller --quiet
if ($LASTEXITCODE -ne 0) { throw "pyinstaller install failed" }

# 4. Fetch ffmpeg.exe + libdiscid.dll into bin\ -------------------------------
$bin = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

$needFfmpeg  = -not (Test-Path (Join-Path $bin 'ffmpeg.exe'))
$needDiscid  = -not (Test-Path (Join-Path $bin 'discid.dll'))

if ($SkipBinaries) {
    if (-not (Test-Path (Join-Path $bin 'ffmpeg.exe'))) {
        Write-Warning "bin\ffmpeg.exe missing; CD ripping won't work in the built app."
    }
    if (-not (Test-Path (Join-Path $bin 'discid.dll'))) {
        Write-Warning "bin\discid.dll missing; CD detection won't work in the built app."
    }
} else {
    if ($needFfmpeg) {
        Write-Host "==> Downloading ffmpeg.exe" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP "lyon-ffmpeg.zip"
        Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $tmp
        $extract = Join-Path $env:TEMP 'lyon-ffmpeg-extract'
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Expand-Archive $tmp -DestinationPath $extract
        $exe = Get-ChildItem -Path $extract -Recurse -Filter ffmpeg.exe | Select-Object -First 1
        if (-not $exe) { throw "ffmpeg.exe not found inside the downloaded archive." }
        Copy-Item $exe.FullName -Destination (Join-Path $bin 'ffmpeg.exe') -Force
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\ffmpeg.exe already present; skipping"
    }

    if ($needDiscid) {
        Write-Host "==> Downloading libdiscid (Windows x64)" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP "lyon-discid.zip"
        Invoke-WebRequest -Uri 'https://github.com/metabrainz/libdiscid/releases/download/v0.6.4/libdiscid-0.6.4-win64.zip' -OutFile $tmp
        $extract = Join-Path $env:TEMP 'lyon-discid-extract'
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Expand-Archive $tmp -DestinationPath $extract
        $dll = Get-ChildItem -Path $extract -Recurse -Filter discid.dll | Select-Object -First 1
        if (-not $dll) {
            $dll = Get-ChildItem -Path $extract -Recurse -Filter libdiscid.dll | Select-Object -First 1
        }
        if (-not $dll) { throw "discid.dll not found inside the downloaded archive." }
        Copy-Item $dll.FullName -Destination (Join-Path $bin 'discid.dll') -Force
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\discid.dll already present; skipping"
    }
}

# 5. Smoke-test that the app at least imports ---------------------------------
Write-Host "==> Smoke-testing imports" -ForegroundColor Cyan
& $venvPython -c "from lyon.app import main; print('imports OK')"
if ($LASTEXITCODE -ne 0) { throw "Import smoke test failed; aborting before PyInstaller." }

# 6. PyInstaller bundle -------------------------------------------------------
Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
& $venvPython -m PyInstaller --noconfirm build\lyon.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 7. Inno Setup installer -----------------------------------------------------
if ($SkipInstaller) {
    Write-Host "==> Skipping installer step (-SkipInstaller)" -ForegroundColor Yellow
    Write-Host "    Bundle is at: $(Join-Path $Root 'dist\LyonMusicManager')"
} else {
    Write-Host "==> Building installer with Inno Setup" -ForegroundColor Cyan
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\iscc.exe"
    if (-not (Test-Path $iscc)) {
        $iscc = "${env:ProgramFiles}\Inno Setup 6\iscc.exe"
    }
    if (-not (Test-Path $iscc)) {
        throw "iscc.exe not found. Install Inno Setup 6 from https://jrsoftware.org/isinfo.php, or pass -SkipInstaller."
    }
    & $iscc installer\lyon.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }

    $setup = Join-Path $Root 'installer\Output\LyonMusicManager-Setup.exe'
    if (-not (Test-Path $setup)) { throw "Setup.exe not produced" }

    $size = (Get-Item $setup).Length / 1MB
    Write-Host ""
    Write-Host "==> Build complete" -ForegroundColor Green
    Write-Host ("    {0}  ({1:N1} MB)" -f $setup, $size)
}
