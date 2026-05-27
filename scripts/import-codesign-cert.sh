#!/usr/bin/env bash
# Import the Developer ID p12 certificate into a transient keychain for CI.
set -euo pipefail

KEYCHAIN="build-signing.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -base64 20)"

# Decode the base64-encoded p12
echo "${CERT_P12}" | base64 --decode > /tmp/cert.p12

# Create a fresh keychain (won't persist after the runner is torn down)
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"

# Import the certificate
security import /tmp/cert.p12 -k "$KEYCHAIN" -P "${CERT_PASSWORD}" \
    -T /usr/bin/codesign -T /usr/bin/security

# Allow codesign to access the key without prompting
security set-key-partition-list -S "apple-tool:,apple:" \
    -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN"

# Add our keychain to the search list
security list-keychains -d user -s "$KEYCHAIN" \
    "$(security list-keychains -d user | sed s/\"//g | tr -d '[:space:]')"

rm -f /tmp/cert.p12
echo "Certificate imported into $KEYCHAIN."
