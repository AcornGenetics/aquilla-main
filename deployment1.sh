#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${AQ_SRC_BASEDIR:-/home/pi/aquilla-main}"
VENV_DIR="${BASE_DIR}/venv"
BIN_LINK="${BASE_DIR}/bin"
AUTOLOGIN_USER="${AUTOLOGIN_USER:-${USER}}"
ROTATE_OUTPUT="${ROTATE_OUTPUT:-HDMI-2}"
ROTATE_DIR="${ROTATE_DIR:-left}"
INSTALL_DOCKER="${INSTALL_DOCKER:-0}"
WATCHTOWER_ENABLE="${WATCHTOWER_ENABLE:-0}"
WATCHTOWER_INTERVAL="${WATCHTOWER_INTERVAL:-300}"

echo "Manual step: ensure SSH keys are installed if cloning private repos."
echo "Using base directory: ${BASE_DIR}"

sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git screen vim pylint python3-dev python3-venv python3-pip

if ! command -v docker >/dev/null 2>&1; then
  if [[ "${INSTALL_DOCKER}" == "1" ]]; then
    echo "Docker not found. Installing Docker..."
    sudo rm -rf /var/lib/apt/lists/*
    sudo apt-get update
    sudo apt-get install -y iptables || echo "iptables not available. Check apt sources."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "${AUTOLOGIN_USER}" || true
    sudo apt-get install -y docker-compose-plugin
  else
    echo "Docker not found. Set INSTALL_DOCKER=1 to install it."
  fi
fi

if [[ ! -d "${BASE_DIR}" ]]; then
  echo "Repo not found at ${BASE_DIR}. Clone it first."
  exit 1
fi

python3 -m venv "${VENV_DIR}"
if [[ ! -e "${BIN_LINK}" ]]; then
  ln -s "${VENV_DIR}/bin" "${BIN_LINK}"
fi

source "${VENV_DIR}/bin/activate"
python3 -m pip install --upgrade pip
python3 -m pip install -r "${BASE_DIR}/requirements.txt"

sudo apt-get install -y --no-install-recommends xserver-xorg x11-xserver-utils xinit openbox xterm unclutter
sudo apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0

sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/autologin.conf >/dev/null <<EOF
[Seat:*]
autologin-user=${AUTOLOGIN_USER}
autologin-session=rpd-x
EOF

if [[ -d "${BASE_DIR}/server_web" ]]; then
  cp "${BASE_DIR}/server_web/kiosk.py" "${HOME}/"
  sudo cp "${BASE_DIR}/server_web/autostart" /etc/xdg/openbox/
  sudo cp "${BASE_DIR}/server_web/environment" /etc/xdg/openbox/
  if [[ -d "${HOME}/.config/chromium/Default/Cache" ]]; then
    rm -rf "${HOME}/.config/chromium/Default/Cache"
  fi
  if [[ -d "${HOME}/.config/chromium/Default/Service Worker" ]]; then
    rm -rf "${HOME}/.config/chromium/Default/Service Worker"
  fi
  if [[ -d "${HOME}/.config/chromium/Default/Code Cache" ]]; then
    rm -rf "${HOME}/.config/chromium/Default/Code Cache"
  fi
  if [[ -d "${HOME}/.config/chromium/Default/GPUCache" ]]; then
    rm -rf "${HOME}/.config/chromium/Default/GPUCache"
  fi
  if [[ -d "${HOME}/.cache/chromium" ]]; then
    rm -rf "${HOME}/.cache/chromium"
  fi
  if [[ -f "${BASE_DIR}/server_web/.bash_profile" ]]; then
    cp "${BASE_DIR}/server_web/.bash_profile" "${HOME}/"
  fi
  if [[ -d "${BASE_DIR}/server_web/app" ]]; then
    cp -r "${BASE_DIR}/server_web/app" "${HOME}/"
  fi
fi

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

sudo apt-get install -y nodejs npm
sudo npm install -g serve

if [[ -f "${BASE_DIR}/server_web/serve.service" ]]; then
  sudo cp "${BASE_DIR}/server_web/serve.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable serve.service
  sudo systemctl start serve.service
fi

if [[ -f "${BASE_DIR}/aquila_app.service" ]]; then
  sudo cp "${BASE_DIR}/aquila_app.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now aquila_app.service
fi

if [[ -f "${BASE_DIR}/aquila_web/aquila_web.service" ]]; then
  sudo cp "${BASE_DIR}/aquila_web/aquila_web.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now aquila_web.service
fi

if command -v docker >/dev/null 2>&1 && [[ "${WATCHTOWER_ENABLE}" == "1" ]]; then
  if ! sudo docker ps -a --format '{{.Names}}' | grep -qx "watchtower"; then
    sudo docker run -d --name watchtower --restart unless-stopped \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v "/home/${AUTOLOGIN_USER}/.docker/config.json:/config.json" \
      containrrr/watchtower --label-enable --cleanup --interval "${WATCHTOWER_INTERVAL}"
  else
    sudo docker start watchtower >/dev/null 2>&1 || true
  fi
fi

if [[ -f "/boot/cmdline.txt" ]]; then
  sudo sed -i 's/console=tty1/console=tty3/' /boot/cmdline.txt
fi

if [[ -x "${BASE_DIR}/update.sh" ]]; then
  "${BASE_DIR}/update.sh"
else
  echo "Setup complete. Rebooting now."
  sudo reboot now
fi

echo "Deployment done. Run: python3 ${BASE_DIR}/scripts/check_service_paths.py"
