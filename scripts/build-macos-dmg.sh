#!/usr/bin/env bash
# Package the .app into a DMG. Sign/notarize only when CI credentials exist.
set -euo pipefail

APP="dist/Sea Lyon Media Manager.app"
VERSION=$(python -c "from lyon import __version__; print(__version__)")
DMG_OUT="dist/SeaLyonMediaManager-${VERSION}-arm64.dmg"
SIGNING_ENABLED="${MACOS_SIGNING_ENABLED:-0}"

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

if [ "$SIGNING_ENABLED" != "1" ]; then
    echo "MACOS_SIGNING_ENABLED is not 1; leaving unsigned DMG: $DMG_OUT"
    echo "DMG ready: $DMG_OUT"
    exit 0
fi

: "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required when MACOS_SIGNING_ENABLED=1}"
: "${APPLE_ID:?APPLE_ID is required when MACOS_SIGNING_ENABLED=1}"
: "${APPLE_APP_PASSWORD:?APPLE_APP_PASSWORD is required when MACOS_SIGNING_ENABLED=1}"

DEV_ID="Developer ID Application: DrShoctopus (${APPLE_TEAM_ID})"

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
