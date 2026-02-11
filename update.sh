#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${AQ_SRC_BASEDIR:-/home/pi/aquilla-main}"

echo "Using base directory: ${BASE_DIR}"

if [[ ! -d "${BASE_DIR}" ]]; then
  echo "Repo not found at ${BASE_DIR}."
  exit 1
fi

if [[ -d "${BASE_DIR}/.git" ]]; then
  git -C "${BASE_DIR}" status --short
  echo "Run 'git -C ${BASE_DIR} pull' if you want latest changes."
fi

for service_path in "${BASE_DIR}/aquila_app.service" "${BASE_DIR}/aquila_web/aquila_web.service" "${BASE_DIR}/server_web/serve.service"; do
  if [[ -f "${service_path}" ]]; then
    sudo cp "${service_path}" /etc/systemd/system/
  fi
done

sudo systemctl daemon-reload

for service in aquila_app.service aquila_web.service serve.service; do
  if systemctl list-unit-files | awk '{print $1}' | grep -qx "$service"; then
    sudo systemctl restart "$service"
  fi
done

echo "Update complete. Reboot if needed: sudo reboot now"
echo "After reboot, verify paths with: python3 ${BASE_DIR}/scripts/check_service_paths.py"
