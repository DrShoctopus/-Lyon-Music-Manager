#!/usr/bin/env bash
# Zip the .app, submit to Apple notary, wait for result, then staple.
set -euo pipefail

APP="dist/Sea Lyon Media Manager.app"
ZIP="dist/upload.zip"

echo "Creating zip for notarization..."
ditto -c -k --keepParent "$APP" "$ZIP"

echo "Submitting to Apple notary service..."
xcrun notarytool submit "$ZIP" \
    --apple-id "${APPLE_ID}" \
    --team-id "${APPLE_TEAM_ID}" \
    --password "${APPLE_APP_PASSWORD}" \
    --wait

echo "Stapling notarization ticket..."
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
rm -f "$ZIP"
echo "Notarization complete."
