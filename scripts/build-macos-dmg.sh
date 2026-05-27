#!/usr/bin/env bash
# Package the signed .app into a signed, notarized DMG.
set -euo pipefail

APP="dist/Sea Lyon Media Manager.app"
VERSION=$(python -c "from lyon import __version__; print(__version__)")
DMG_OUT="dist/SeaLyonMediaManager-${VERSION}-arm64.dmg"
DEV_ID="Developer ID Application: DrShoctopus (${APPLE_TEAM_ID})"

BG="docs/brand/dmg-background.png"
BG_ARG=""
if [ -f "$BG" ]; then
    BG_ARG="--background $BG"
fi

create-dmg \
    --volname "Sea Lyon Media Manager" \
    --window-pos 200 120 \
    --window-size 600 380 \
    --icon-size 110 \
    --icon "Sea Lyon Media Manager.app" 170 190 \
    --hide-extension "Sea Lyon Media Manager.app" \
    --app-drop-link 430 190 \
    $BG_ARG \
    "$DMG_OUT" \
    "$APP"

echo "Signing DMG..."
codesign --force --sign "$DEV_ID" --timestamp "$DMG_OUT"

echo "Notarizing DMG..."
xcrun notarytool submit "$DMG_OUT" \
    --apple-id "${APPLE_ID}" \
    --team-id "${APPLE_TEAM_ID}" \
    --password "${APPLE_APP_PASSWORD}" \
    --wait

xcrun stapler staple "$DMG_OUT"
echo "DMG ready: $DMG_OUT"
