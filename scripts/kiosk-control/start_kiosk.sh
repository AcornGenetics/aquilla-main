#!/usr/bin/env bash
# start_kiosk.sh — launch Chromium in kiosk mode on the host.
# Must be run as the desktop user (pi) or from a context with DISPLAY set.
set -euo pipefail

KIOSK_URL="${KIOSK_URL:-http://localhost:8090}"
CHROMIUM_BIN="${CHROMIUM_BIN:-chromium}"

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-/home/pi/.Xauthority}"

# Kill any existing instance first so we don't open a second window
pkill -f "${CHROMIUM_BIN}" 2>/dev/null || true
sleep 1

exec "${CHROMIUM_BIN}" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --ozone-platform=wayland \
  --password-store=basic \
  --touch-events=enabled \
  --enable-touch-drag-drop \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --no-first-run \
  --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 \
  "${KIOSK_URL}"
