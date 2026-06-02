#!/usr/bin/env bash
set -euo pipefail

FLEET_ENV="/opt/fleet/.env"
DEVICE_ENV="/opt/aquila/config/device.env"

GHCR_TOKEN=$(grep GHCR_TOKEN "${DEVICE_ENV}" | cut -d= -f2)
GHCR_REPO=$(grep ^GHCR_REPO "${FLEET_ENV}" | cut -d= -f2)
IMAGE_TAG=$(grep ^IMAGE_TAG "${FLEET_ENV}" | cut -d= -f2)

curl -fsSL \
    -H "Authorization: token ${GHCR_TOKEN}" \
    "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
    -o /opt/fleet/docker-compose.yml

docker compose --env-file "${FLEET_ENV}" -f /opt/fleet/docker-compose.yml pull

_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
    "ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')
_DIGEST_UI=$(docker inspect --format='{{index .RepoDigests 0}}' \
    "ghcr.io/${GHCR_REPO}-ui:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')

sed -i "s|^RUNNING_IMAGE_DIGEST=.*|RUNNING_IMAGE_DIGEST=${_DIGEST:-}|" "${FLEET_ENV}"
sed -i "s|^RUNNING_IMAGE_DIGEST_UI=.*|RUNNING_IMAGE_DIGEST_UI=${_DIGEST_UI:-}|" "${FLEET_ENV}"

docker compose --env-file "${FLEET_ENV}" -f /opt/fleet/docker-compose.yml up -d

mkdir -p /opt/aquila/tests
