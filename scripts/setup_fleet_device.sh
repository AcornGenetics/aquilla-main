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
sudo cp "${REPO_ROOT}/fleet-config/vmagent.yaml" /opt/fleet/vmagent.yaml
sudo cp "${REPO_ROOT}/fleet-config/vector.yaml" /opt/fleet/vector.yaml
sudo cp "${REPO_ROOT}/config_files/device.env" /opt/aquila/config/device.env

echo "Starting fleet services..."
sudo docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d

echo "Done. If you just installed Docker, log out/in for group changes."
