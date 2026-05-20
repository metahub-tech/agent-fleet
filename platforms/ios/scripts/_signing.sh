#!/usr/bin/env bash
# Shared WDA signing-mode resolver — sourced by build-wda.sh and
# refresh-wda-cert.sh so "free" and "paid" are resolved identically everywhere.
#
# Two first-class modes, auto-detected from the environment:
#
#   FREE  (Personal Team / free Apple ID)
#     - No App Store Connect API key. xcodebuild signs using the Apple ID
#       account configured in Xcode (GUI). 7-day certs. Headless minting is
#       impossible (account drops on reboot → "No Accounts"; re-adding needs
#       2FA), so refresh is manual.
#
#   PAID  (Apple Developer Program + App Store Connect API key)
#     - Set WDA_ASC_KEY_PATH + WDA_ASC_KEY_ID + WDA_ASC_ISSUER_ID. xcodebuild
#       signs fully headless via the API key (-authenticationKey*). 1-year certs,
#       no GUI, no 2FA — so refresh can be fully automated.
#
# Team ID resolution (both modes):
#   - WDA_TEAM_ID env override wins (needed for a paid first build when no signing
#     identity exists in the keychain yet).
#   - else extracted from the "Apple Development" codesigning identity.
#
# After calling `resolve_wda_signing`, these globals are set:
#   WDA_SIGNING_MODE  "free" | "paid"
#   WDA_TEAM_ID       10-char team id (may be empty → caller errors with guidance)
#   WDA_AUTH_ARGS     bash array of xcodebuild auth flags (empty in free mode)
#
# Expand WDA_AUTH_ARGS set -u / bash 3.2 safely:  ${WDA_AUTH_ARGS[@]+"${WDA_AUTH_ARGS[@]}"}

resolve_wda_signing() {
    # WDA_TEAM_ID env override wins; else extract from the keychain identity.
    if [ -z "${WDA_TEAM_ID:-}" ]; then
        WDA_TEAM_ID="$(security find-identity -v -p codesigning 2>/dev/null \
            | grep 'Apple Development' | head -1 | sed -E 's/.*\(([A-Z0-9]{10})\)".*/\1/')"
    fi

    WDA_AUTH_ARGS=()
    if [ -n "${WDA_ASC_KEY_PATH:-}" ] && [ -n "${WDA_ASC_KEY_ID:-}" ] && [ -n "${WDA_ASC_ISSUER_ID:-}" ]; then
        WDA_SIGNING_MODE="paid"
        WDA_AUTH_ARGS=(-authenticationKeyPath "$WDA_ASC_KEY_PATH"
                       -authenticationKeyID "$WDA_ASC_KEY_ID"
                       -authenticationKeyIssuerID "$WDA_ASC_ISSUER_ID")
    else
        WDA_SIGNING_MODE="free"
    fi
}
