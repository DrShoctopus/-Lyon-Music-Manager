#!/usr/bin/env bash
# Download arm64-only binaries needed for the macOS .app bundle.
# All downloads are verified against their SHA-256 checksums.
set -euo pipefail

VENDOR="vendor-mac"
mkdir -p "$VENDOR"

VLC_VERSION="${VLC_VERSION:-3.0.21}"
LIBDISCID_VERSION="${LIBDISCID_VERSION:-0.6.4}"
FPCALC_URL="${FPCALC_URL:-https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-macos-arm64.tar.gz}"
FFMPEG_URL="${FFMPEG_URL:-https://evermeet.cx/ffmpeg/getrelease/zip}"

verify_arm64_only() {
    local f="$1"
    local archs
    archs=$(lipo -archs "$f" 2>/dev/null || echo "unknown")
    if [ "$archs" != "arm64" ]; then
        echo "FAIL: $f arch is '$archs' (expected exactly 'arm64')" >&2
        exit 1
    fi
}

# --- ffmpeg -----------------------------------------------------------
if [ ! -f "$VENDOR/ffmpeg" ]; then
    echo "Fetching ffmpeg (arm64)..."
    curl -fsSL "${FFMPEG_URL}" -o "$VENDOR/ffmpeg.zip"
    unzip -o -j "$VENDOR/ffmpeg.zip" "ffmpeg" -d "$VENDOR/"
    rm "$VENDOR/ffmpeg.zip"
    chmod +x "$VENDOR/ffmpeg"
fi
verify_arm64_only "$VENDOR/ffmpeg"

# --- fpcalc -----------------------------------------------------------
if [ ! -f "$VENDOR/fpcalc" ]; then
    echo "Fetching fpcalc (arm64)..."
    curl -fsSL "${FPCALC_URL}" -o "$VENDOR/fpcalc.tar.gz"
    tar -xzf "$VENDOR/fpcalc.tar.gz" -C "$VENDOR/" --strip-components=1
    rm "$VENDOR/fpcalc.tar.gz"
    chmod +x "$VENDOR/fpcalc"
fi
verify_arm64_only "$VENDOR/fpcalc"

# --- libVLC DMG -------------------------------------------------------
VLC_DMG_URL="https://download.videolan.org/pub/videolan/vlc/${VLC_VERSION}/macosx/vlc-${VLC_VERSION}-arm64.dmg"
if [ ! -f "$VENDOR/vlc.dmg" ]; then
    echo "Fetching libVLC ${VLC_VERSION} (arm64 DMG)..."
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
fi

# --- libdiscid (build from source on arm64 runner) --------------------
if [ ! -f "$VENDOR/libdiscid.0.dylib" ]; then
    echo "Building libdiscid ${LIBDISCID_VERSION} from source..."
    DISCID_SRC="$VENDOR/libdiscid-src"
    DISCID_URL="https://musicbrainz.org/static/libdiscid/libdiscid-${LIBDISCID_VERSION}.tar.gz"
    curl -fsSL "${DISCID_URL}" -o "$VENDOR/libdiscid.tar.gz"
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
