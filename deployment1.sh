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

# Add device hostname to host_config.json if not already present
DEVICE_HOSTNAME="$(hostname)"
python3 - <<PYEOF
import json, sys

config_path = "${BASE_DIR}/config_files/host_config.json"
hostname = "${DEVICE_HOSTNAME}"

with open(config_path, "r") as f:
    config = json.load(f)

if hostname in config:
    print(f"host_config.json already has entry for {hostname}, skipping.")
else:
    config[hostname] = {
        "info": { "dock_name": hostname },
        "pcr": {
            "comport": "/dev/ttyUSB0",
            "baudrate": 56700,
            "vid": "0x0403",
            "pid": "0x6001",
            "device_type": "1089",
            "pcr_profile": "profiles/verification_profile.json"
        },
        "optics": { "rox pin": 22, "fam pin": 27, "LED_ON": 0, "LED_OFF": 1 },
        "drawer": {
            "open_steps": 4500,
            "close_steps": 0,
            "read_steps": 160,
            "home_steps": 5000,
            "step_multiplier": 32
        },
        "axis": {
            "home_steps": 2500,
            "step_multiplier": 8,
            "positions": [280, 640, 1010, 1365, 1720, 2075]
        },
        "adc": { "famP": 0, "famN": 1, "roxP": 2, "roxN": 3 }
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=4)
    print(f"Added {hostname} to host_config.json with default template.")
PYEOF

# Enable I2C (required for ADS1115 lid temperature sensor)
sudo raspi-config nonint do_i2c 0
# Enable SPI (required for optical ADC)
sudo raspi-config nonint do_spi 0

sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/autologin.conf >/dev/null <<EOF
[Seat:*]
autologin-user=${AUTOLOGIN_USER}
autologin-session=rpd-labwc
EOF

if [[ -d "${BASE_DIR}/server_web" ]]; then
  cp "${BASE_DIR}/server_web/kiosk.py" "${HOME}/"
  if [[ -f "${BASE_DIR}/server_web/.bash_profile" ]]; then
    cp "${BASE_DIR}/server_web/.bash_profile" "${HOME}/"
  fi
  if [[ -d "${BASE_DIR}/server_web/app" ]]; then
    cp -r "${BASE_DIR}/server_web/app" "${HOME}/"
  fi

  # Clear Chromium cache
  rm -rf "${HOME}/.config/chromium/Default/Cache"
  rm -rf "${HOME}/.config/chromium/Default/Service Worker"
  rm -rf "${HOME}/.config/chromium/Default/Code Cache"
  rm -rf "${HOME}/.config/chromium/Default/GPUCache"
  rm -rf "${HOME}/.cache/chromium"

  # XDG autostart for Chromium kiosk (works with rpd-labwc / Wayland)
  mkdir -p "${HOME}/.config/autostart"
  cat > "${HOME}/.config/autostart/chromium-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Exec=chromium --kiosk --noerrdialogs --disable-infobars --ozone-platform=wayland --password-store=basic http://localhost:8090
Hidden=false
NoDisplay=false
Name=Chromium Kiosk
EOF

  # labwc autostart: kanshi for display rotation, kiosk.py as fallback
  mkdir -p "${HOME}/.config/labwc"
  cat > "${HOME}/.config/labwc/autostart" <<EOF
kanshi &
sleep 3 && DISPLAY=:0 python3 ${HOME}/kiosk.py &
EOF

  # kanshi display rotation config for rpd-labwc (Wayland)
  mkdir -p "${HOME}/.config/kanshi"
  cat > "${HOME}/.config/kanshi/config" <<EOF
profile {
    output HDMI-A-2 enable mode 1024x768@60.004 position 0,0 transform ${ROTATE_DIR_KANSHI:-270}
}

profile {
    output HDMI-A-1 enable mode 1024x768@60.004 position 0,0 transform ${ROTATE_DIR_KANSHI:-270}
}
EOF
fi

# Display rotation is handled by kanshi (see ~/.config/kanshi/config above).
# xrandr is not used — rpd-labwc runs Wayland, not X11.

sudo apt-get install -y nodejs npm
sudo npm install -g serve

# serve.service is not used — no Astro dist exists in this repo.
# Disable it if previously installed to prevent CHDIR failures.
if sudo systemctl is-enabled serve.service &>/dev/null; then
  sudo systemctl disable --now serve.service || true
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
