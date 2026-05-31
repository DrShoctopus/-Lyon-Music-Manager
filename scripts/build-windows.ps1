<#
.SYNOPSIS
    End-to-end Windows build for Lyon Music Manager (WMP branch / main).

.DESCRIPTION
    From a clean checkout, produces dist\LyonMusicManager\, a portable zip
    (dist\SeaLyonMediaManager-{version}-windows.zip), and an Inno Setup 6
    installer (dist\SeaLyonMediaManager-{version}-Setup.exe).

    Steps: create Python 3.14 venv, install dependencies, download
    ffmpeg.exe, fpcalc.exe, deno.exe, libdiscid.dll, and the VLC runtime into
    bin\, run PyInstaller, zip output, compile installer.

    Run from the project root:
        scripts\build-windows.ps1

    Optional flags:
        -SkipBinaries   Don't re-download ffmpeg / fpcalc / libdiscid / VLC if bin\ is already populated.
        -SkipZip        Build the bundle but don't zip it.
        -SkipInstaller  Skip the Inno Setup installer step (requires Inno Setup 6 on PATH or default install location).
        -Clean          Wipe .venv, dist\, and generated PyInstaller build artefacts.

.NOTES
    Requires Python 3.14 64-bit on PATH (or the py launcher: py -3.14 ...).
#>
[CmdletBinding()]
param(
    [switch]$SkipBinaries,
    [switch]$SkipZip,
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

# Resolve paths relative to the project root (one level up from this script).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $Root

Write-Host "==> Lyon Music Manager - Windows build" -ForegroundColor Green
Write-Host "    Project root: $Root"

$ChromaprintVersion = '1.5.1'
$FpcalcArchive = 'chromaprint-fpcalc-1.5.1-windows-x86_64.zip'
$FpcalcUrl = 'https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-windows-x86_64.zip'
$VlcVersion = '3.0.23'
$VendorRuntimeManifest = Get-Content (Join-Path $Root 'build/vendor-runtimes.json') -Raw | ConvertFrom-Json
$DenoVersion = [string]$VendorRuntimeManifest.deno.version
$DenoArchive = [string]$VendorRuntimeManifest.deno.windows.archive
$DenoUrl = [string]$VendorRuntimeManifest.deno.windows.url
$DenoSha256 = [string]$VendorRuntimeManifest.deno.windows.sha256

function Get-ExpectedSha256FromText {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [string]$FileName
    )

    $lines = $Text -split "`r?`n"
    if ($FileName) {
        foreach ($line in $lines) {
            if ($line -match '^\s*([A-Fa-f0-9]{64})\s+[* ]?(.+?)\s*$') {
                $hash = $Matches[1].ToLowerInvariant()
                $name = [System.IO.Path]::GetFileName($Matches[2].Trim())
                if ($name -eq $FileName) { return $hash }
            }
        }
    }

    foreach ($line in $lines) {
        if ($line -match '([A-Fa-f0-9]{64})') {
            return $Matches[1].ToLowerInvariant()
        }
    }

    throw "No SHA-256 checksum found for $FileName."
}

function Get-ExpectedSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$FileName
    )

    Write-Host "    Fetching checksum $Uri"
    $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -ErrorAction Stop
    $contentType = [string]$response.Headers['Content-Type']
    if ($contentType -match 'text/html') {
        throw "Checksum URI returned HTML instead of checksum text: $Uri"
    }
    return Get-ExpectedSha256FromText -Text $response.Content -FileName $FileName
}

function Assert-FileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $actual = (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
    $expectedLower = $Expected.ToLowerInvariant()
    if ($actual -ne $expectedLower) {
        throw "$Label checksum mismatch. Expected $expectedLower, got $actual."
    }
    Write-Host "    Verified $Label SHA-256: $actual"
}

function Invoke-WebRequestWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [int]$Attempts = 3
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -ErrorAction Stop
            return
        } catch {
            if ($attempt -ge $Attempts) { throw }
            $delay = 2 * $attempt
            Write-Host "    Download failed (attempt $attempt/$Attempts): $($_.Exception.Message). Retrying in $delay seconds..."
            Start-Sleep -Seconds $delay
        }
    }
}

function Invoke-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile,
        [Parameter(Mandatory = $true)][string]$ChecksumUri,
        [string]$ChecksumFileName
    )

    Invoke-WebRequestWithRetry -Uri $Uri -OutFile $OutFile
    $expected = Get-ExpectedSha256 -Uri $ChecksumUri -FileName $ChecksumFileName
    Assert-FileSha256 -Path $OutFile -Expected $expected -Label ([System.IO.Path]::GetFileName($OutFile))
}

function Test-FpcalcVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    if (-not (Test-Path $Path)) { return $false }
    try {
        $output = & $Path -version 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        return ([string]$output) -match [regex]::Escape($ExpectedVersion)
    } catch {
        return $false
    }
}

function Assert-FpcalcVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    $output = & $Path -version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "fpcalc.exe -version failed: $output"
    }
    if (([string]$output) -notmatch [regex]::Escape($ExpectedVersion)) {
        throw "Expected fpcalc $ExpectedVersion, got: $output"
    }
    Write-Host "    Verified fpcalc version: $output"
}

function Test-DenoVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    if (-not (Test-Path $Path)) { return $false }
    try {
        $output = & $Path --version 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        return ([string]$output) -match [regex]::Escape("deno $ExpectedVersion")
    } catch {
        return $false
    }
}

function Assert-DenoVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedVersion
    )

    $output = & $Path --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "deno.exe --version failed: $output"
    }
    if (([string]$output) -notmatch [regex]::Escape("deno $ExpectedVersion")) {
        throw "Expected deno $ExpectedVersion, got: $output"
    }
    $firstLine = $output | Select-Object -First 1
    Write-Host "    Verified deno version: $firstLine"
}

# 0. Optional clean -----------------------------------------------------------
if ($Clean) {
    Write-Host "==> Cleaning previous build artefacts" -ForegroundColor Yellow
    foreach ($p in '.venv', 'dist', 'build\build', 'build\dist') {
        $full = Join-Path $Root $p
        if (Test-Path $full) {
            Write-Host "    Removing $p"
            Remove-Item $full -Recurse -Force
        }
    }
    Get-ChildItem -Path (Join-Path $Root 'build') -Filter '*.toc' -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host "    Removing build\$($_.Name)"
            Remove-Item $_.FullName -Force
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
& $venvPython -m pip install -r requirements-build.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements-build.txt failed" }

# 4. Fetch ffmpeg.exe + fpcalc.exe + deno.exe + libdiscid.dll + VLC runtime into bin\ -----
$bin = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null

$needFfmpeg = -not (Test-Path (Join-Path $bin 'ffmpeg.exe'))
$fpcalcPath = Join-Path $bin 'fpcalc.exe'
$fpcalcRelease = [pscustomobject]@{
    Version = $ChromaprintVersion
    Name = $FpcalcArchive
    Url = $FpcalcUrl
}
$needFpcalc = -not (Test-Path $fpcalcPath)
$denoPath = Join-Path $bin 'deno.exe'
$denoRelease = [pscustomobject]@{
    Version = $DenoVersion
    Name = $DenoArchive
    Url = $DenoUrl
    Sha256 = $DenoSha256
}
$needDeno = -not (Test-Path $denoPath)
$needDiscid = -not (Test-Path (Join-Path $bin 'discid.dll'))
$vlcDir = Join-Path $bin 'vlc'
$vlcVersionMarker = Join-Path $vlcDir 'lyon-vlc-version.txt'
$vlcVersionMatches = (Test-Path $vlcVersionMarker) -and
                     ((Get-Content -Path $vlcVersionMarker -Raw).Trim() -eq $VlcVersion)
$needVlc = -not (Test-Path (Join-Path $vlcDir 'libvlc.dll')) -or
           -not (Test-Path (Join-Path $vlcDir 'libvlccore.dll')) -or
           -not (Test-Path (Join-Path $vlcDir 'plugins')) -or
           -not $vlcVersionMatches

if (-not $SkipBinaries) {
    if (Test-Path $fpcalcPath) {
        if (Test-FpcalcVersion -Path $fpcalcPath -ExpectedVersion $fpcalcRelease.Version) {
            $needFpcalc = $false
        } else {
            Write-Host "    bin\fpcalc.exe is missing or not version $($fpcalcRelease.Version); refreshing"
            $needFpcalc = $true
        }
    }
    if (Test-Path $denoPath) {
        if (Test-DenoVersion -Path $denoPath -ExpectedVersion $denoRelease.Version) {
            $needDeno = $false
        } else {
            Write-Host "    bin\deno.exe is missing or not version $DenoVersion; refreshing"
            $needDeno = $true
        }
    }
}

if ($SkipBinaries) {
    if ($needFfmpeg) { Write-Warning "bin\ffmpeg.exe missing; CD ripping won't work in the built app." }
    if ($needFpcalc) { Write-Warning "bin\fpcalc.exe missing; AcoustID fingerprinting won't work in the built app." }
    if ($needDeno) { Write-Warning "bin\deno.exe missing; YouTube signature solving may fail in the built app." }
    if ($needDiscid) { Write-Warning "bin\discid.dll missing; CD detection won't work in the built app." }
    if ($needVlc) { Write-Warning "bin\vlc runtime missing; packaged audio/video playback and EQ will be disabled." }
} else {
    if ($needFfmpeg) {
        Write-Host "==> Downloading ffmpeg.exe" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP "lyon-ffmpeg.zip"
        $ffmpegArchive = 'ffmpeg-release-essentials.zip'
        $ffmpegUrl = "https://www.gyan.dev/ffmpeg/builds/$ffmpegArchive"
        Invoke-VerifiedDownload `
            -Uri $ffmpegUrl `
            -OutFile $tmp `
            -ChecksumUri "$ffmpegUrl.sha256" `
            -ChecksumFileName $ffmpegArchive
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

    if ($needFpcalc) {
        Write-Host "==> Downloading fpcalc.exe (Chromaprint $($fpcalcRelease.Version))" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP $fpcalcRelease.Name
        $extract = Join-Path $env:TEMP 'lyon-fpcalc-extract'
        if (Test-Path $tmp) { Remove-Item $tmp -Force }
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Invoke-WebRequest -Uri $fpcalcRelease.Url -OutFile $tmp -UseBasicParsing -ErrorAction Stop
        Expand-Archive $tmp -DestinationPath $extract -Force
        $exe = Get-ChildItem -Path $extract -Recurse -Filter fpcalc.exe | Select-Object -First 1
        if (-not $exe) { throw "fpcalc.exe not found inside $($fpcalcRelease.Name)." }
        Copy-Item $exe.FullName -Destination $fpcalcPath -Force
        Assert-FpcalcVersion -Path $fpcalcPath -ExpectedVersion $fpcalcRelease.Version
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\fpcalc.exe already present and up to date; skipping"
    }

    if ($needDeno) {
        Write-Host "==> Downloading deno.exe ($($denoRelease.Version))" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP $denoRelease.Name
        $extract = Join-Path $env:TEMP 'lyon-deno-extract'
        if (Test-Path $tmp) { Remove-Item $tmp -Force }
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        Invoke-WebRequestWithRetry -Uri $denoRelease.Url -OutFile $tmp
        Assert-FileSha256 -Path $tmp -Expected $DenoSha256 -Label $DenoArchive
        Expand-Archive $tmp -DestinationPath $extract -Force
        $exe = Get-ChildItem -Path $extract -Recurse -Filter deno.exe | Select-Object -First 1
        if (-not $exe) { throw "deno.exe not found inside $($denoRelease.Name)." }
        Copy-Item $exe.FullName -Destination $denoPath -Force
        Assert-DenoVersion -Path $denoPath -ExpectedVersion $denoRelease.Version
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\deno.exe already present and up to date; skipping"
    }

    if ($needDiscid) {
        Write-Host "==> Downloading libdiscid (Windows x64)" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP "lyon-discid.zip"
        $discidArchive = 'libdiscid-0.6.4-win.zip'
        $discidChecksumUrl = 'https://ftp.musicbrainz.org/pub/musicbrainz/libdiscid/libdiscid-0.6.4.SHA256SUMS'
        # GitHub releases page ships the Windows binary zip since 0.6.4.
        # MusicBrainz FTP mirrors kept as fallbacks in case GitHub CDN is unavailable.
        $urls = @(
            "https://github.com/metabrainz/libdiscid/releases/download/v0.6.4/$discidArchive",
            "https://ftp.musicbrainz.org/pub/musicbrainz/libdiscid/$discidArchive",
            "https://ftp.osuosl.org/pub/musicbrainz/libdiscid/$discidArchive"
        )
        $ok = $false
        foreach ($u in $urls) {
            try {
                Write-Host "    Trying $u"
                Invoke-VerifiedDownload `
                    -Uri $u `
                    -OutFile $tmp `
                    -ChecksumUri $discidChecksumUrl `
                    -ChecksumFileName $discidArchive
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
        Write-Host "    bin\vlc runtime is missing or not version $VlcVersion; refreshing"
        Write-Host "==> Downloading VLC runtime (Windows x64)" -ForegroundColor Cyan
        $tmp = Join-Path $env:TEMP "lyon-vlc.zip"
        $extract = Join-Path $env:TEMP 'lyon-vlc-extract'
        if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
        $vlcArchive = "vlc-$VlcVersion-win64.zip"
        $vlcUrl = "https://download.videolan.org/pub/videolan/vlc/$VlcVersion/win64/$vlcArchive"
        Invoke-VerifiedDownload `
            -Uri $vlcUrl `
            -OutFile $tmp `
            -ChecksumUri "$vlcUrl.sha256" `
            -ChecksumFileName $vlcArchive
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
        Set-Content -Path $vlcVersionMarker -Value $VlcVersion
        Remove-Item $tmp; Remove-Item $extract -Recurse -Force
    } else {
        Write-Host "    bin\vlc runtime already present; skipping"
    }
}

# 5. Smoke-test that the app at least imports ---------------------------------
Write-Host "==> Smoke-testing imports" -ForegroundColor Cyan
if (Test-Path $vlcDir) {
    $env:PATH = "$vlcDir;$env:PATH"
    $env:VLC_PLUGIN_PATH = Join-Path $vlcDir 'plugins'
} else {
    Write-Warning "bin\vlc not found; VLC backend smoke test will likely fail. Run without -SkipBinaries to download the runtime."
}
& $venvPython -c "from lyon.app import main; print('imports OK')"
if ($LASTEXITCODE -ne 0) { throw "Import smoke test failed; aborting before PyInstaller." }
& $venvPython -c "from PySide6.QtCore import QCoreApplication; app = QCoreApplication([]); from lyon.core.playback_backend import create_playback_backend; backend = create_playback_backend(); print(type(backend).__name__); assert type(backend).__name__ == 'VlcPlaybackBackend'"
if ($LASTEXITCODE -ne 0) { throw "VLC backend smoke test failed; aborting before PyInstaller." }
& $venvPython -c "from lyon.core.fingerprint import is_available; assert is_available(); print('fpcalc OK')"
if ($LASTEXITCODE -ne 0) { throw "fpcalc smoke test failed; aborting before PyInstaller." }
Assert-DenoVersion -Path $denoPath -ExpectedVersion $DenoVersion

# 6. PyInstaller bundle -------------------------------------------------------
Write-Host "==> Validating PyInstaller inputs" -ForegroundColor Cyan
foreach ($required in @('main.py', 'docs\brand\lyon-app-icon.png', 'bin\ffmpeg.exe', 'bin\fpcalc.exe', 'bin\deno.exe')) {
    if (-not (Test-Path (Join-Path $Root $required))) {
        throw "Required build input missing: $required"
    }
}

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
$bundleBin = Join-Path $bundle '_internal\bin'
if (-not (Test-Path $bundleBin)) { $bundleBin = Join-Path $bundle 'bin' }
if (-not (Test-Path (Join-Path $bundleBin 'fpcalc.exe'))) { throw "Packaged app is missing fpcalc.exe." }
if (-not (Test-Path (Join-Path $bundleBin 'deno.exe'))) { throw "Packaged app is missing deno.exe." }

# Read the app version from the Python package for use in output filenames.
$initPy = Join-Path $Root 'lyon\__init__.py'
$appVersion = '0.0.0'
if (Test-Path $initPy) {
    $m = Select-String -Path $initPy -Pattern '__version__\s*=\s*"([^"]+)"'
    if ($m) { $appVersion = $m.Matches[0].Groups[1].Value }
}
Write-Host "    App version: $appVersion"

# 7. Zip the bundle for distribution -----------------------------------------
if ($SkipZip) {
    Write-Host "==> Skipping zip step (-SkipZip)" -ForegroundColor Yellow
    Write-Host "    Bundle is at: $bundle"
} else {
    $zip = Join-Path $Root "dist\SeaLyonMediaManager-$appVersion-windows.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Write-Host "==> Zipping bundle to dist\SeaLyonMediaManager-$appVersion-windows.zip" -ForegroundColor Cyan
    Compress-Archive -Path "$bundle\*" -DestinationPath $zip
    $size = (Get-Item $zip).Length / 1MB
    Write-Host ("    {0}  ({1:N1} MB)" -f $zip, $size)
}

# 8. Inno Setup installer -----------------------------------------------------
if ($SkipInstaller) {
    Write-Host "==> Skipping installer step (-SkipInstaller)" -ForegroundColor Yellow
} else {
    Write-Host "==> Locating Inno Setup 6 compiler (ISCC)" -ForegroundColor Cyan
    $iscc = $null
    foreach ($candidate in @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
    if (-not $iscc) {
        $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($found) { $iscc = $found.Source }
    }
    if (-not $iscc) {
        Write-Warning "Inno Setup 6 not found; skipping installer. Install from https://jrsoftware.org/isinfo.php or pass -SkipInstaller to suppress this warning."
    } else {
        Write-Host "    Using: $iscc"
        $iss = Join-Path $Root 'build\lyon.iss'
        $ico = Join-Path $Root 'build\lyon-app-icon.ico'
        if (-not (Test-Path $ico)) {
            throw "Installer icon missing at build\lyon-app-icon.ico. Run the PyInstaller step first so the spec generates it from the brand PNG."
        }
        & $iscc $iss /DAppVersion=$appVersion /Q
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
        $installer = Join-Path $Root "dist\SeaLyonMediaManager-$appVersion-Setup.exe"
        if (-not (Test-Path $installer)) { throw "Expected installer not found at $installer." }
        $iSize = (Get-Item $installer).Length / 1MB
        Write-Host ("    {0}  ({1:N1} MB)" -f $installer, $iSize)
    }
}

Write-Host ""
Write-Host "==> Build complete" -ForegroundColor Green
if (-not $SkipZip -and (Test-Path (Join-Path $Root "dist\SeaLyonMediaManager-$appVersion-windows.zip"))) {
    Write-Host "    Portable zip  : dist\SeaLyonMediaManager-$appVersion-windows.zip  (unzip and double-click LyonMusicManager.exe)"
}
if (-not $SkipInstaller -and (Test-Path (Join-Path $Root "dist\SeaLyonMediaManager-$appVersion-Setup.exe"))) {
    Write-Host "    Installer     : dist\SeaLyonMediaManager-$appVersion-Setup.exe"
}
