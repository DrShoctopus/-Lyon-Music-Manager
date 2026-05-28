#!/usr/bin/env bash
# Inject native binaries into the PyInstaller-produced .app bundle,
# rewrite dylib install names, thin universal binaries to arm64, and verify.
set -euo pipefail

APP="dist/Sea Lyon Media Manager.app"
FW="$APP/Contents/Frameworks"
BIN="$APP/Contents/MacOS/bin"

STAGED_VLC_DMG="${STAGED_VLC_DMG:-vendor-mac/vlc.dmg}"
STAGED_LIBDISCID_DYLIB="${STAGED_LIBDISCID_DYLIB:-vendor-mac/libdiscid.0.dylib}"
STAGED_FFMPEG="${STAGED_FFMPEG:-vendor-mac/ffmpeg}"
STAGED_FPCALC="${STAGED_FPCALC:-vendor-mac/fpcalc}"

mkdir -p "$FW/plugins" "$BIN"

# --- Mount VLC DMG and copy libvlc + plugins --------------------------
VLC_STAGE="$(mktemp -d)/VLC.app"
VLC_DEVICE=""
VLC_MOUNT=""

cleanup_vlc_mount() {
    if [ -n "$VLC_MOUNT" ]; then
        hdiutil detach "$VLC_MOUNT" -quiet >/dev/null 2>&1 || true
    elif [ -n "$VLC_DEVICE" ]; then
        hdiutil detach "$VLC_DEVICE" -quiet >/dev/null 2>&1 || true
    fi
}
trap cleanup_vlc_mount EXIT

attach_out=$(hdiutil attach "$STAGED_VLC_DMG" -nobrowse)
VLC_DEVICE=$(printf "%s\n" "$attach_out" | awk '/\/dev\// { dev=$1 } END { print dev }')
VLC_MOUNT=$(printf "%s\n" "$attach_out" | awk '/\/Volumes\// { mount=$NF } END { print mount }')
[ -n "$VLC_DEVICE" ] || { echo "Failed to determine mounted DMG device" >&2; exit 1; }
[ -n "$VLC_MOUNT" ] || { echo "Failed to determine mounted DMG path" >&2; exit 1; }
cp -R "$VLC_MOUNT/VLC.app" "$VLC_STAGE"
hdiutil detach "$VLC_DEVICE" -quiet
VLC_DEVICE=""
VLC_MOUNT=""

VLC_LIB="$VLC_STAGE/Contents/MacOS/lib"
VLC_PLUGINS="$VLC_STAGE/Contents/MacOS/plugins"

cp "$VLC_LIB/libvlc.dylib"     "$FW/"
cp "$VLC_LIB/libvlccore.dylib" "$FW/"
cp -R "$VLC_PLUGINS/." "$FW/plugins/"
rm -rf "$(dirname "$VLC_STAGE")"

# --- libdiscid --------------------------------------------------------
cp "$STAGED_LIBDISCID_DYLIB" "$FW/libdiscid.0.dylib"

# --- ffmpeg + fpcalc --------------------------------------------------
cp "$STAGED_FFMPEG" "$BIN/ffmpeg"; chmod +x "$BIN/ffmpeg"
cp "$STAGED_FPCALC" "$BIN/fpcalc"; chmod +x "$BIN/fpcalc"

# --- Rewrite dylib install names to @rpath ---------------------------
install_name_tool -id "@rpath/libvlc.dylib"      "$FW/libvlc.dylib"
install_name_tool -id "@rpath/libvlccore.dylib"   "$FW/libvlccore.dylib"
install_name_tool -id "@rpath/libdiscid.0.dylib"  "$FW/libdiscid.0.dylib"
install_name_tool -change \
    "@loader_path/libvlccore.dylib" "@rpath/libvlccore.dylib" \
    "$FW/libvlc.dylib"

# Rewrite each VLC plugin's link to libvlccore
while IFS= read -r -d '' plugin; do
    install_name_tool -change \
        "@loader_path/../../libvlccore.dylib" "@rpath/libvlccore.dylib" \
        "$plugin" 2>/dev/null || true
done < <(find "$FW/plugins" -name "*.dylib" -print0)

# --- Thin universal binaries to arm64 ---------------------------------
echo "Thinning universal binaries to arm64..."
while IFS= read -r -d '' f; do
    archs=$(lipo -archs "$f" 2>/dev/null || true)
    case "$archs" in
        "arm64") ;;
        *arm64*)
            tmp="${f}.arm64.tmp"
            lipo -thin arm64 "$f" -output "$tmp" && mv "$tmp" "$f"
            ;;
        "") ;;
        *)
            echo "FAIL: $f is '$archs' with no arm64 slice" >&2; exit 1 ;;
    esac
done < <(find "$APP" -type f \( -name "*.dylib" -o -name "*.so" \) -print0)

# Thin executables too
for f in "$APP/Contents/MacOS/LyonMusicManager" "$BIN/ffmpeg" "$BIN/fpcalc"; do
    [ -f "$f" ] || continue
    archs=$(lipo -archs "$f" 2>/dev/null || true)
    case "$archs" in
        "arm64") ;;
        *arm64*)
            tmp="${f}.arm64.tmp"
            lipo -thin arm64 "$f" -output "$tmp" && mv "$tmp" "$f"
            ;;
        *) echo "FAIL: $f arch '$archs' (expected arm64)" >&2; exit 1 ;;
    esac
done

# --- Hard verification: 100% arm64 ------------------------------------
echo "Verifying bundle is 100% arm64..."
violations=0
while IFS= read -r -d '' f; do
    if file "$f" 2>/dev/null | grep -q "Mach-O"; then
        archs=$(lipo -archs "$f" 2>/dev/null || echo "")
        if [ "$archs" != "arm64" ]; then
            echo "FAIL ($archs): $f"
            violations=$((violations + 1))
        fi
    fi
done < <(find "$APP" -type f -print0)

if [ "$violations" -gt 0 ]; then
    echo "Bundle contains $violations non-arm64 binaries — refusing to ship." >&2
    exit 1
fi
echo "Bundle staging complete: every Mach-O is arm64-only."
