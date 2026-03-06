#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${AQ_SRC_BASEDIR:-/home/pi/aquilla-main}"
AUTOLOGIN_USER="${AUTOLOGIN_USER:-${USER}}"
ROTATE_OUTPUT="${ROTATE_OUTPUT:-HDMI-2}"
ROTATE_DIR="${ROTATE_DIR:-left}"

echo "Using base directory: ${BASE_DIR}"

if [[ ! -d "${BASE_DIR}" ]]; then
  echo "Repo not found at ${BASE_DIR}."
  exit 1
fi

if [[ -d "${BASE_DIR}/.git" ]]; then
  git -C "${BASE_DIR}" status --short
  echo "Run 'git -C ${BASE_DIR} pull' if you want latest changes."
fi

if [[ -f "${BASE_DIR}/config_files/wifi.json" ]]; then
  echo "Applying Wi-Fi config from config_files/wifi.json"
  sudo python3 "${BASE_DIR}/scripts/apply_wifi.py" || true
fi

sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/autologin.conf >/dev/null <<EOF
[Seat:*]
autologin-user=${AUTOLOGIN_USER}
autologin-session=rpd-x
EOF

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

sudo mkdir -p /etc/xdg/openbox

if [[ -f "/etc/xdg/openbox/autostart" ]]; then
  if grep -q "xrandr --output .* --rotate" /etc/xdg/openbox/autostart; then
    sudo sed -i "s/xrandr --output .* --rotate .*/xrandr --output ${ROTATE_OUTPUT} --rotate ${ROTATE_DIR}/" /etc/xdg/openbox/autostart
  else
    echo "xrandr --output ${ROTATE_OUTPUT} --rotate ${ROTATE_DIR}" | sudo tee -a /etc/xdg/openbox/autostart >/dev/null
  fi
else
  echo "xrandr --output ${ROTATE_OUTPUT} --rotate ${ROTATE_DIR}" | sudo tee /etc/xdg/openbox/autostart >/dev/null
fi

echo "Update complete. Rebooting now..."
sudo reboot now
