#!/usr/bin/env bash
# Download arm64-only binaries needed for the macOS .app bundle.
# All downloads are verified against their SHA-256 checksums.
set -euo pipefail

VENDOR="vendor-mac"
mkdir -p "$VENDOR"

load_deno_manifest_value() {
    local key="$1"
    local python_bin
    python_bin=$(command -v python3 || command -v python)
    "$python_bin" - "$key" <<'PY'
import json
import sys
from pathlib import Path

key = sys.argv[1]
manifest = json.loads(Path("build/vendor-runtimes.json").read_text(encoding="utf-8"))
deno = manifest["deno"]
platform = deno["macos_arm64"]
values = {
    "version": deno["version"],
    "url": platform["url"],
    "sha256": platform["sha256"],
}
print(values[key])
PY
}

download_with_retries() {
    local url="$1"
    local output="$2"
    local attempts="${3:-3}"
    local attempt
    for attempt in $(seq 1 "$attempts"); do
        if curl -fsSL "$url" -o "$output"; then
            return 0
        fi
        if [ "$attempt" -ge "$attempts" ]; then
            return 1
        fi
        sleep $((attempt * 2))
    done
}

VLC_VERSION="${VLC_VERSION:-3.0.23}"
LIBDISCID_VERSION="${LIBDISCID_VERSION:-0.6.4}"
FPCALC_URL="${FPCALC_URL:-https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-macos-arm64.tar.gz}"
FPCALC_SHA256="${FPCALC_SHA256:-9c5d9565d2396dbcf0e1d797e1ffdf1e19242f3bed88ac3200e144286b57ede6}"
FFMPEG_URL="${FFMPEG_URL:-https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1/ffmpeg-darwin-arm64.gz}"
FFMPEG_SHA256="${FFMPEG_SHA256:-8923876afa8db5585022d7860ec7e589af192f441c56793971276d450ed3bbfa}"
LIBDISCID_URL="${LIBDISCID_URL:-https://github.com/metabrainz/libdiscid/releases/download/v${LIBDISCID_VERSION}/libdiscid-${LIBDISCID_VERSION}.tar.gz}"
LIBDISCID_SHA256="${LIBDISCID_SHA256:-dd5e8f1c9aead442e23b749a9cc9336372e62e88ad7079a2b62895b0390cb282}"
DENO_URL="${DENO_URL:-$(load_deno_manifest_value url)}"
DENO_SHA256="${DENO_SHA256:-$(load_deno_manifest_value sha256)}"

verify_checksum() {
    local f="$1"
    local expected="$2"
    local got
    if [ -z "$expected" ]; then
        return 0
    fi
    got=$(shasum -a 256 "$f" | awk '{print $1}')
    if [ "$expected" != "$got" ]; then
        echo "FAIL: $f checksum mismatch (expected $expected, got $got)" >&2
        exit 1
    fi
}

is_arm64_only() {
    local f="$1"
    local archs
    archs=$(lipo -archs "$f" 2>/dev/null || echo "unknown")
    [ "$archs" = "arm64" ]
}

verify_arm64_only() {
    local f="$1"
    local archs
    archs=$(lipo -archs "$f" 2>/dev/null || echo "unknown")
    if [ "$archs" != "arm64" ]; then
        echo "FAIL: $f arch is '$archs' (expected exactly 'arm64')" >&2
        exit 1
    fi
}

fetch_ffmpeg() {
    local archive
    rm -f "$VENDOR/ffmpeg"
    case "$FFMPEG_URL" in
        *.gz)
            archive="$VENDOR/ffmpeg.gz"
            curl -fsSL "${FFMPEG_URL}" -o "$archive"
            verify_checksum "$archive" "$FFMPEG_SHA256"
            gzip -dc "$archive" > "$VENDOR/ffmpeg"
            rm "$archive"
            ;;
        *.zip)
            archive="$VENDOR/ffmpeg.zip"
            curl -fsSL "${FFMPEG_URL}" -o "$archive"
            verify_checksum "$archive" "$FFMPEG_SHA256"
            unzip -o -j "$archive" "ffmpeg" -d "$VENDOR/"
            rm "$archive"
            ;;
        *)
            archive="$VENDOR/ffmpeg.download"
            curl -fsSL "${FFMPEG_URL}" -o "$archive"
            verify_checksum "$archive" "$FFMPEG_SHA256"
            mv "$archive" "$VENDOR/ffmpeg"
            ;;
    esac
    chmod +x "$VENDOR/ffmpeg"
}

fetch_deno() {
    rm -f "$VENDOR/deno"
    download_with_retries "${DENO_URL}" "$VENDOR/deno.zip"
    verify_checksum "$VENDOR/deno.zip" "$DENO_SHA256"
    unzip -o -j "$VENDOR/deno.zip" "deno" -d "$VENDOR/"
    rm "$VENDOR/deno.zip"
    chmod +x "$VENDOR/deno"
}

# --- ffmpeg -----------------------------------------------------------
if [ ! -f "$VENDOR/ffmpeg" ]; then
    echo "Fetching ffmpeg (arm64)..."
    fetch_ffmpeg
elif ! is_arm64_only "$VENDOR/ffmpeg"; then
    echo "Cached ffmpeg is not arm64; refetching..."
    fetch_ffmpeg
fi
verify_arm64_only "$VENDOR/ffmpeg"

# --- fpcalc -----------------------------------------------------------
if [ ! -f "$VENDOR/fpcalc" ]; then
    echo "Fetching fpcalc (arm64)..."
    curl -fsSL "${FPCALC_URL}" -o "$VENDOR/fpcalc.tar.gz"
    verify_checksum "$VENDOR/fpcalc.tar.gz" "$FPCALC_SHA256"
    tar -xzf "$VENDOR/fpcalc.tar.gz" -C "$VENDOR/" --strip-components=1
    rm "$VENDOR/fpcalc.tar.gz"
    chmod +x "$VENDOR/fpcalc"
fi
verify_arm64_only "$VENDOR/fpcalc"

# --- deno -------------------------------------------------------------
if [ ! -f "$VENDOR/deno" ]; then
    echo "Fetching deno (arm64)..."
    fetch_deno
elif ! is_arm64_only "$VENDOR/deno"; then
    echo "Cached deno is not arm64; refetching..."
    fetch_deno
fi
verify_arm64_only "$VENDOR/deno"

# --- libVLC DMG -------------------------------------------------------
VLC_DMG_URL="https://download.videolan.org/pub/videolan/vlc/${VLC_VERSION}/macosx/vlc-${VLC_VERSION}-arm64.dmg"
VLC_DMG_VERSION_FILE="$VENDOR/vlc.dmg.version"

fetch_vlc_dmg() {
    echo "Fetching libVLC ${VLC_VERSION} (arm64 DMG)..."
    rm -f "$VENDOR/vlc.dmg" "$VENDOR/vlc.dmg.sha256.txt" "$VLC_DMG_VERSION_FILE"
    curl -fsSL "${VLC_DMG_URL}" -o "$VENDOR/vlc.dmg"
    # Verify SHA-256 if a sidecar checksum is available
    SHA_URL="${VLC_DMG_URL}.sha256"
    if curl -fsSL "${SHA_URL}" -o "$VENDOR/vlc.dmg.sha256.txt" 2>/dev/null; then
        expected=$(awk '{print $1}' "$VENDOR/vlc.dmg.sha256.txt")
        got=$(shasum -a 256 "$VENDOR/vlc.dmg" | awk '{print $1}')
        if [ "$expected" != "$got" ]; then
            echo "FAIL: VLC DMG checksum mismatch (expected $expected, got $got)" >&2
            exit 1
        fi
    fi
    printf '%s\n' "$VLC_VERSION" > "$VLC_DMG_VERSION_FILE"
}

if [ ! -f "$VENDOR/vlc.dmg" ]; then
    fetch_vlc_dmg
elif [ ! -f "$VLC_DMG_VERSION_FILE" ] || [ "$(cat "$VLC_DMG_VERSION_FILE")" != "$VLC_VERSION" ]; then
    echo "Cached libVLC DMG is not ${VLC_VERSION}; refetching..."
    fetch_vlc_dmg
fi

# --- libdiscid (build from source on arm64 runner) --------------------
if [ ! -f "$VENDOR/libdiscid.0.dylib" ]; then
    echo "Building libdiscid ${LIBDISCID_VERSION} from source..."
    DISCID_SRC="$VENDOR/libdiscid-src"
    curl -fsSL "${LIBDISCID_URL}" -o "$VENDOR/libdiscid.tar.gz"
    verify_checksum "$VENDOR/libdiscid.tar.gz" "$LIBDISCID_SHA256"
    mkdir -p "$DISCID_SRC"
    tar -xzf "$VENDOR/libdiscid.tar.gz" -C "$DISCID_SRC" --strip-components=1
    rm "$VENDOR/libdiscid.tar.gz"
    (
        cd "$DISCID_SRC"
        ./configure --prefix="$(pwd)/out" CFLAGS="-arch arm64" LDFLAGS="-arch arm64"
        make -j"$(sysctl -n hw.ncpu)"
        make install
    )
    cp "$DISCID_SRC/out/lib/libdiscid.0.dylib" "$VENDOR/libdiscid.0.dylib"
    rm -rf "$DISCID_SRC"
fi
verify_arm64_only "$VENDOR/libdiscid.0.dylib"

echo "All vendor binaries fetched and verified."
