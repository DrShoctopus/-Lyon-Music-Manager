#!/usr/bin/env bash
set -euo pipefail
SRC="docs/brand/lyon-app-icon.png"
OUT="build/lyon-app-icon.iconset"
ICNS="build/lyon-app-icon.icns"

if [ ! -f "$SRC" ]; then
    # Try alternate casing
    SRC="Docs/brand/lyon-app-icon.png"
fi
if [ ! -f "$SRC" ]; then
    echo "ERROR: app icon PNG not found under docs/brand/ or Docs/brand/" >&2
    exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"
for size in 16 32 64 128 256 512; do
    sips -z "$size" "$size"              "$SRC" --out "$OUT/icon_${size}x${size}.png"     >/dev/null
    sips -z $((size*2)) $((size*2))      "$SRC" --out "$OUT/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$OUT" -o "$ICNS"
echo "Created $ICNS"
