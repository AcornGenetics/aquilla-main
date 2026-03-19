#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${DEVICE_ID:-pilot-000}"
WATCHTOWER_HTTP_API_TOKEN="${WATCHTOWER_HTTP_API_TOKEN:-REPLACE_WATCHTOWER_TOKEN}"
IMAGE_TAG="pilot"

bash "$(dirname "$0")/../setup_fleet_device.sh"

sudo tee /opt/aquila/config/device.env >/dev/null <<EOF
DEVICE_ID=${DEVICE_ID}
RUN_MODE=prod
IMAGE_TAG=${IMAGE_TAG}
WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_HTTP_API_TOKEN}
EOF

echo "Configured device.env with IMAGE_TAG=${IMAGE_TAG}."
