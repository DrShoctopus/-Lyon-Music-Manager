#!/usr/bin/env bash
# Codesign every binary and the .app bundle.
set -euo pipefail

APP="dist/Sea Lyon Media Manager.app"
DEV_ID="Developer ID Application: DrShoctopus (${APPLE_TEAM_ID})"
ENTITLEMENTS="build/lyon.entitlements"

echo "Signing individual binaries..."
find "$APP/Contents" \( -name "*.dylib" -o -path "*/bin/*" \) -type f -print0 |
while IFS= read -r -d '' f; do
    codesign --force --sign "$DEV_ID" \
        --entitlements "$ENTITLEMENTS" \
        --options runtime --timestamp \
        "$f"
done

echo "Signing .app bundle..."
codesign --force --sign "$DEV_ID" \
    --entitlements "$ENTITLEMENTS" \
    --options runtime --timestamp \
    --deep "$APP"

echo "Verifying signature..."
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose "$APP"
echo "Codesign complete."
