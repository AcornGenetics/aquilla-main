#!/usr/bin/env bash
# install_splash.sh — Install or update the Sentri boot splash page on an Aquila device.
#
# Usage:
#   sudo bash install_splash.sh
#
set -euo pipefail

[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash install_splash.sh"; exit 1; }

GHCR_REPO="${GHCR_REPO:-acorngenetics/aquilla-main}"
RAW_REPO_URL="https://raw.githubusercontent.com/${GHCR_REPO}/main"
PI_HOME="/home/pi"
AUTOSTART="${PI_HOME}/.config/openbox/autostart"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Sentri — Splash Page Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Download splash page ──────────────────────────────────────────────────────
echo "  → Downloading splash.html..."
curl -fsSL "${RAW_REPO_URL}/sentri_web/static/splash.html" -o /opt/aquila/splash.html
echo "  ✓ splash.html installed to /opt/aquila/splash.html"

# ── Update Openbox autostart if needed ───────────────────────────────────────
if [[ ! -f "${AUTOSTART}" ]]; then
    echo "  ✗ Openbox autostart not found at ${AUTOSTART} — run deployment2.sh first"
    exit 1
fi

if grep -q "kiosk http://localhost:8090" "${AUTOSTART}"; then
    sed -i \
        's|--kiosk http://localhost:8090|--kiosk file:///opt/aquila/splash.html|' \
        "${AUTOSTART}"
    echo "  ✓ Autostart updated: Chromium now loads splash first"
elif grep -q "splash.html" "${AUTOSTART}"; then
    echo "  ✓ Autostart already points to splash.html — no change needed"
fi

if ! grep -q "disable-web-security" "${AUTOSTART}"; then
    sed -i \
        's|--ozone-platform=x11|--ozone-platform=x11 \\\n    --disable-web-security \\\n    --allow-file-access-from-files|' \
        "${AUTOSTART}"
    echo "  ✓ Added --disable-web-security and --allow-file-access-from-files flags"
fi

chown pi:pi /opt/aquila/splash.html

# ── Verify ────────────────────────────────────────────────────────────────────
echo ""
echo "  Verifying..."
[[ -f /opt/aquila/splash.html ]] && echo "  ✓ splash.html present" || { echo "  ✗ splash.html missing"; exit 1; }
grep -q "splash.html" "${AUTOSTART}"       && echo "  ✓ autostart points to splash" || { echo "  ✗ autostart not updated"; exit 1; }
grep -q "disable-web-security" "${AUTOSTART}" && echo "  ✓ web security flags present" || { echo "  ✗ flags missing"; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Done. Splash will appear on next reboot."
echo " To apply immediately without rebooting:"
echo "   pkill chromium && DISPLAY=:0 su pi -c 'chromium --kiosk file:///opt/aquila/splash.html --disable-web-security --allow-file-access-from-files &'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
