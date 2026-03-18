#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Installing host requirements..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  gettext-base

echo "Installing Grafana Alloy..."
sudo apt-get install -y gpg wget
sudo mkdir -p /etc/apt/keyrings
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update
sudo apt-get install -y alloy

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

sudo apt-get install -y docker-compose-plugin

echo "Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sudo sh
echo "Run 'sudo tailscale up' to authenticate this device."

echo "Creating fleet directories..."
sudo mkdir -p /opt/fleet
sudo mkdir -p /opt/aquila/config
sudo mkdir -p /opt/aquila/results
sudo mkdir -p /opt/aquila/logs
sudo mkdir -p /opt/aquila/profiles

echo "Copying fleet configs..."
sudo cp "${REPO_ROOT}/fleet-config/docker-compose.yml" /opt/fleet/docker-compose.yml
sudo cp "${REPO_ROOT}/fleet-config/vmagent.yaml" /opt/fleet/vmagent.yaml.template
sudo cp "${REPO_ROOT}/fleet-config/vector.yaml" /opt/fleet/vector.yaml.template
sudo cp "${REPO_ROOT}/config_files/device.env" /opt/aquila/config/device.env
sudo cp "${REPO_ROOT}/config_files/grafana.env" /opt/aquila/config/grafana.env

echo "Rendering Grafana config templates..."
set -a
# shellcheck source=/dev/null
source /opt/aquila/config/grafana.env
set +a
envsubst < /opt/fleet/vmagent.yaml.template | sudo tee /opt/fleet/vmagent.yaml >/dev/null
envsubst < /opt/fleet/vector.yaml.template | sudo tee /opt/fleet/vector.yaml >/dev/null

echo "Starting fleet services..."
sudo docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d

echo "Done. If you just installed Docker, log out/in for group changes."
