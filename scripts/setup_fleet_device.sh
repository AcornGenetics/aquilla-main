#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing host requirements..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  gnupg \
  lsb-release

echo "Installing Grafana Alloy..."
sudo apt-get install -y gpg wget
sudo mkdir -p /etc/apt/keyrings
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update
sudo apt-get install -y alloy

if ! command -v docker >/dev/null 2>&1; then
  sudo rm -rf /var/lib/apt/lists/*
  sudo apt-get update
  sudo apt-get install -y iptables || echo "iptables not available. Check apt sources."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

sudo apt-get install -y docker-compose-plugin
sudo systemctl enable docker

echo "Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sudo sh
echo "Run 'sudo tailscale up --ssh' to authenticate this device."

echo "Creating fleet directories..."
sudo mkdir -p /opt/fleet
sudo mkdir -p /opt/aquila/config
sudo mkdir -p /opt/aquila/results
sudo mkdir -p /opt/aquila/logs/lid_heater
sudo mkdir -p /opt/aquila/logs/pcr
sudo mkdir -p /opt/aquila/logs/optics
sudo mkdir -p /opt/aquila/logs/results
sudo mkdir -p /opt/aquila/profiles

echo "Copying fleet configs..."
sudo cp "${REPO_ROOT}/fleet-config/docker-compose.yml" /opt/fleet/docker-compose.yml
sudo cp "${REPO_ROOT}/config_files/device.env" /opt/aquila/config/device.env
sudo cp "${REPO_ROOT}/config_files/grafana.env" /opt/aquila/config/grafana.env

image_tag="$(grep -E '^IMAGE_TAG=' /opt/aquila/config/device.env | tail -1 | cut -d= -f2-)"
image_tag="${image_tag:-dev}"
device_hostname="$(grep -E '^DEVICE_HOSTNAME=' /opt/aquila/config/device.env | tail -1 | cut -d= -f2- | tr -d '\r')"
device_hostname="${device_hostname:-$(hostname)}"
printf 'IMAGE_TAG=%s\nDEVICE_HOSTNAME=%s\n' "${image_tag}" "${device_hostname}" | sudo tee /opt/fleet/.env >/dev/null
echo "Wrote /opt/fleet/.env with IMAGE_TAG=${image_tag} DEVICE_HOSTNAME=${device_hostname}"

if [[ -z "${WATCHTOWER_HTTP_API_TOKEN:-}" ]]; then
  WATCHTOWER_HTTP_API_TOKEN="$(openssl rand -hex 32)"
  echo "Generated WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_HTTP_API_TOKEN}"
fi

sudo sed -i "s/^WATCHTOWER_HTTP_API_TOKEN=.*/WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_HTTP_API_TOKEN}/" \
  /opt/aquila/config/device.env
sudo chown root:root /opt/aquila/config/device.env
sudo chmod 600 /opt/aquila/config/device.env

echo "Starting fleet services..."
sudo docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d

echo "Done. If you just installed Docker, log out/in for group changes."
echo "Edit /opt/aquila/config/device.env to set DEVICE_ID, IMAGE_TAG, WATCHTOWER_HTTP_API_TOKEN, GHCR_USERNAME, and GHCR_TOKEN."
echo "Optional: run 'pytest tests/fleet_device' to verify scripts."
