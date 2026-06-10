#!/usr/bin/env bash
# Install or update the host-side kiosk-control service, then verify Wi-Fi endpoints.
#
# Defaults to raw GitHub so it works on fleet devices that do not have a repo
# checkout. Override BRANCH or RAW_REPO_URL to test unmerged changes.
set -euo pipefail

BRANCH="${BRANCH:-main}"
RAW_REPO_URL="${RAW_REPO_URL:-https://raw.githubusercontent.com/AcornGenetics/aquilla-main/${BRANCH}}"
SERVICE_DIR="${SERVICE_DIR:-/etc/systemd/system}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
KIOSK_CONTROL_URL="${KIOSK_CONTROL_URL:-http://127.0.0.1:9191}"

SCRIPT_DEST="${BIN_DIR}/kiosk_control.py"
SERVICE_DEST="${SERVICE_DIR}/kiosk-control.service"

LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fetch_or_copy() {
  local name="$1"
  local dest="$2"
  local local_src="${LOCAL_DIR}/${name}"
  local remote_src="${RAW_REPO_URL}/scripts/kiosk-control/${name}"

  if [[ -f "${local_src}" ]]; then
    echo "Installing ${name} from local checkout"
    sudo cp "${local_src}" "${dest}"
  else
    echo "Installing ${name} from ${remote_src}"
    sudo curl -fsSL "${remote_src}" -o "${dest}"
  fi
}

check_endpoint() {
  local path="$1"
  echo "Checking ${KIOSK_CONTROL_URL}${path}"
  curl -fsS "${KIOSK_CONTROL_URL}${path}"
  echo
}

echo "Updating kiosk-control host service"
fetch_or_copy "kiosk_control.py" "${SCRIPT_DEST}"
sudo chmod +x "${SCRIPT_DEST}"

fetch_or_copy "kiosk-control.service" "${SERVICE_DEST}"

sudo systemctl daemon-reload
sudo systemctl enable --now kiosk-control
sudo systemctl restart kiosk-control

echo "Waiting for kiosk-control to start"
sleep 2

sudo systemctl status kiosk-control --no-pager
check_endpoint "/health"
check_endpoint "/wifi/status"
check_endpoint "/wifi/scan"

echo "kiosk-control update complete"
