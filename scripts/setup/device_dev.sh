#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${DEVICE_ID:-dev-000}"
WATCHTOWER_HTTP_API_TOKEN="${WATCHTOWER_HTTP_API_TOKEN:-REPLACE_WATCHTOWER_TOKEN}"
GHCR_USERNAME="${GHCR_USERNAME:-REPLACE_GHCR_USERNAME}"
GHCR_TOKEN="${GHCR_TOKEN:-REPLACE_GHCR_TOKEN}"
IMAGE_TAG="dev"

bash "$(dirname "$0")/../setup_fleet_device.sh"

sudo tee /opt/aquila/config/device.env >/dev/null <<EOF
DEVICE_ID=${DEVICE_ID}
RUN_MODE=prod
IMAGE_TAG=${IMAGE_TAG}
WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_HTTP_API_TOKEN}
GHCR_USERNAME=${GHCR_USERNAME}
GHCR_TOKEN=${GHCR_TOKEN}
EOF
# device.env must be group-readable by ggc_group so the ggc_user Greengrass
# components (and the root-run app compose stack) can source it. 0600 root:root
# leaves the app stack unable to read it. Fall back gracefully if ggc_group
# doesn't exist yet (pre-Greengrass setup); the enroll/deploy path fixes it later.
sudo chgrp ggc_group /opt/aquila/config/device.env 2>/dev/null || sudo chown root:root /opt/aquila/config/device.env
sudo chmod 640 /opt/aquila/config/device.env

sudo docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d

echo "Configured device.env with IMAGE_TAG=${IMAGE_TAG}."
