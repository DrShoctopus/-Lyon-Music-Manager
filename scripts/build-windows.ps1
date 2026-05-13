<#
.SYNOPSIS
    End-to-end Windows build for Lyon Music Manager (WMP branch / main).

.DESCRIPTION
    From a clean checkout, produces dist\LyonMusicManager\ and a
    distributable zip at dist\LyonMusicManager-windows.zip.

    Steps: create Python 3.14 venv, install dependencies, download
    ffmpeg.exe, libdiscid.dll, and the VLC runtime into bin\, run
    PyInstaller, zip output.

    Run from the project root:
        scripts\build-windows.ps1

    Optional flags:
        -SkipBinaries  Don't re-download ffmpeg / libdiscid / VLC if bin\ is already populated.
        -SkipZip       Build the bundle but don't zip it.
        -Clean         Wipe .venv, build\, dist\ before building.

.NOTES
    Requires Python 3.14 64-bit on PATH (or the py launcher: py -3.14 ...).
#>
[CmdletBinding()]
param(
    [switch]$SkipBinaries,
    [switch]$SkipZip,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

# Resolve paths relative to the project root (one level up from this script).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $Root

Write-Host "==> Lyon Music Manager (WMP / main branch) - Windows build" -ForegroundColor Green
Write-Host "    Project root: $Root"

# 0. Optional clean -----------------------------------------------------------
if ($Clean) {
    Write-Host "==> Cleaning previous build artefacts" -ForegroundColor Yellow
    foreach ($p in '.venv', 'build', 'dist') {
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

# 4. Fetch ffmpeg.exe + libdiscid.dll + VLC runtime into bin\ -----------------
$bin = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

$needFfmpeg = -not (Test-Path (Join-Path $bin 'ffmpeg.exe'))
$needDiscid = -not (Test-Path (Join-Path $bin 'discid.dll'))
$vlcDir = Join-Path $bin 'vlc'
$needVlc = -not (Test-Path (Join-Path $vlcDir 'libvlc.dll')) -or
           -not (Test-Path (Join-Path $vlcDir 'libvlccore.dll')) -or
           -not (Test-Path (Join-Path $vlcDir 'plugins'))

if ($SkipBinaries) {
    if ($needFfmpeg) { Write-Warning "bin\ffmpeg.exe missing; CD ripping won't work in the built app." }
    if ($needDiscid) { Write-Warning "bin\discid.dll missing; CD detection won't work in the built app." }
    if ($needVlc) { Write-Warning "bin\vlc runtime missing; packaged playback will fall back to Qt Multimedia without audible EQ." }
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
        # Try MetaBrainz FTP mirrors; GitHub releases only ship source tarballs.
        $urls = @(
            'https://ftp.musicbrainz.org/pub/musicbrainz/libdiscid/libdiscid-0.6.4-win.zip',
            'https://ftp.osuosl.org/pub/musicbrainz/libdiscid/libdiscid-0.6.4-win.zip',
            'https://ftp.musicbrainz.org/pub/musicbrainz/libdiscid/libdiscid-0.6.2-win.zip'
        )
        $ok = $false
        foreach ($u in $urls) {
            try {
                Write-Host "    Trying $u"
                Invoke-WebRequest -Uri $u -OutFile $tmp -ErrorAction Stop
                $ok = $true
                break
            } catch {
                Write-Host "      -> $($_.Exception.Message)"
            }
        }
        if (-not $ok) { throw "Could not fetch libdiscid Windows binary from any known source." }
        $extract = Join-Path $env:TEMP 'lyon-discid-extract'
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Expand-Archive $tmp -DestinationPath $extract
        # Prefer x64 DLL to match 64-bit Python.
        $dll = Get-ChildItem -Path $extract -Recurse -Filter discid.dll |
                 Where-Object { $_.FullName -match '64' } | Select-Object -First 1
        if (-not $dll) {
            $dll = Get-ChildItem -Path $extract -Recurse -Filter discid.dll | Select-Object -First 1
        }
        if (-not $dll) {
            $dll = Get-ChildItem -Path $extract -Recurse -Filter libdiscid.dll | Select-Object -First 1
        }
        if (-not $dll) { throw "discid.dll not found inside the downloaded archive." }
        Copy-Item $dll.FullName -Destination (Join-Path $bin 'discid.dll') -Force
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\discid.dll already present; skipping"
    }

    if ($needVlc) {
        Write-Host "==> Downloading VLC runtime (Windows x64)" -ForegroundColor Cyan
        $vlcVersion = '3.0.21'
        $tmp = Join-Path $env:TEMP "lyon-vlc.zip"
        $extract = Join-Path $env:TEMP 'lyon-vlc-extract'
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Invoke-WebRequest -Uri "https://download.videolan.org/pub/videolan/vlc/$vlcVersion/win64/vlc-$vlcVersion-win64.zip" -OutFile $tmp
        Expand-Archive $tmp -DestinationPath $extract
        $root = Get-ChildItem -Path $extract -Directory | Select-Object -First 1
        if (-not $root) { throw "VLC archive did not contain an extracted root directory." }
        if (Test-Path $vlcDir) { Remove-Item $vlcDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $vlcDir | Out-Null
        Copy-Item -Path (Join-Path $root.FullName 'libvlc.dll') -Destination $vlcDir -Force
        Copy-Item -Path (Join-Path $root.FullName 'libvlccore.dll') -Destination $vlcDir -Force
        Copy-Item -Path (Join-Path $root.FullName 'plugins') -Destination $vlcDir -Recurse -Force
        if (-not (Test-Path (Join-Path $vlcDir 'libvlc.dll'))) { throw "libvlc.dll was not copied to bin\vlc." }
        if (-not (Test-Path (Join-Path $vlcDir 'libvlccore.dll'))) { throw "libvlccore.dll was not copied to bin\vlc." }
        if (-not (Test-Path (Join-Path $vlcDir 'plugins'))) { throw "VLC plugins directory was not copied to bin\vlc." }
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\vlc runtime already present; skipping"
    }
}

# 5. Smoke-test that the app at least imports ---------------------------------
Write-Host "==> Smoke-testing imports" -ForegroundColor Cyan
$env:PATH = "$vlcDir;$env:PATH"
$env:VLC_PLUGIN_PATH = Join-Path $vlcDir 'plugins'
& $venvPython -c "from lyon.app import main; print('imports OK')"
if ($LASTEXITCODE -ne 0) { throw "Import smoke test failed; aborting before PyInstaller." }
& $venvPython -c "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]); from lyon.core.playback_backend import create_playback_backend; backend = create_playback_backend(); print(type(backend).__name__); assert type(backend).__name__ == 'VlcPlaybackBackend'"
if ($LASTEXITCODE -ne 0) { throw "VLC backend smoke test failed; aborting before PyInstaller." }

# 6. PyInstaller bundle -------------------------------------------------------
Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
& $venvPython -m PyInstaller --noconfirm build\lyon.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$bundle = Join-Path $Root 'dist\LyonMusicManager'
if (-not (Test-Path $bundle)) { throw "PyInstaller didn't produce $bundle" }
$bundleVlc = Join-Path $bundle '_internal\bin\vlc'
if (-not (Test-Path $bundleVlc)) { $bundleVlc = Join-Path $bundle 'bin\vlc' }
if (-not (Test-Path (Join-Path $bundleVlc 'libvlc.dll'))) { throw "Packaged app is missing libvlc.dll." }
if (-not (Test-Path (Join-Path $bundleVlc 'libvlccore.dll'))) { throw "Packaged app is missing libvlccore.dll." }
if (-not (Test-Path (Join-Path $bundleVlc 'plugins'))) { throw "Packaged app is missing VLC plugins." }

# 7. Zip the bundle for distribution -----------------------------------------
if ($SkipZip) {
    Write-Host "==> Skipping zip step (-SkipZip)" -ForegroundColor Yellow
    Write-Host "    Bundle is at: $bundle"
} else {
    $zip = Join-Path $Root 'dist\LyonMusicManager-windows.zip'
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Write-Host "==> Zipping bundle to dist\LyonMusicManager-windows.zip" -ForegroundColor Cyan
    Compress-Archive -Path "$bundle\*" -DestinationPath $zip
    $size = (Get-Item $zip).Length / 1MB
    Write-Host ""
    Write-Host "==> Build complete" -ForegroundColor Green
    Write-Host ("    {0}  ({1:N1} MB)" -f $zip, $size)
    Write-Host "    Distribute by sending this zip; users unzip and double-click LyonMusicManager.exe."
}
