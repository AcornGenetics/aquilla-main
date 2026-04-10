#!/usr/bin/env bash
# install.sh — install and enable the kiosk-control systemd service on the Pi host.
# Run once on the Pi as a user with sudo access.
set -euo pipefail

BASE_DIR="${AQ_SRC_BASEDIR:-/home/pi/aquilla-main}"
SERVICE_SRC="${BASE_DIR}/scripts/kiosk-control/kiosk-control.service"
SERVICE_DEST="/etc/systemd/system/kiosk-control.service"

echo "=== Installing kiosk-control ==="

# --- 1. No extra Python packages needed (uses stdlib http.server only) ---

# --- 2. Install the systemd unit ---
echo "Installing systemd service..."
sudo cp "${SERVICE_SRC}" "${SERVICE_DEST}"
sudo systemctl daemon-reload
sudo systemctl enable kiosk-control.service
sudo systemctl restart kiosk-control.service

# --- 3. Verify it started ---
sleep 2
if sudo systemctl is-active --quiet kiosk-control.service; then
    echo "kiosk-control is running."
else
    echo "ERROR: kiosk-control failed to start. Check: journalctl -u kiosk-control -n 50"
    exit 1
fi

# --- 4. Smoke test ---
echo "Testing health endpoint..."
response=$(curl -sf http://127.0.0.1:9191/health || echo "FAIL")
if echo "${response}" | grep -q '"ok"'; then
    echo "Health check passed: ${response}"
else
    echo "ERROR: health check failed. Response: ${response}"
    exit 1
fi

echo ""
echo "=== Installation complete ==="
echo "Useful commands:"
echo "  sudo systemctl status kiosk-control"
echo "  journalctl -u kiosk-control -f"
echo "  curl -X POST http://127.0.0.1:9191/exit-kiosk   # test exit"
echo "  curl -X POST http://127.0.0.1:9191/start-kiosk  # test start"
