#!/usr/bin/env bash
set -euo pipefail

FLEET_ENV="/opt/fleet/.env"
DEVICE_ENV="/opt/aquila/config/device.env"

GHCR_TOKEN=$(grep ^GHCR_TOKEN= "${DEVICE_ENV}" | cut -d= -f2)
GHCR_TOKEN_2=$(grep ^GHCR_TOKEN_2= "${DEVICE_ENV}" 2>/dev/null | cut -d= -f2 || echo "")
GHCR_REPO=$(grep ^GHCR_REPO "${FLEET_ENV}" | cut -d= -f2)
IMAGE_TAG=$(grep ^IMAGE_TAG "${FLEET_ENV}" | cut -d= -f2)

# If a second token is configured, validate the primary and fall back to it.
# This allows zero-downtime token rotation: add GHCR_TOKEN_2 to device.env,
# verify it works, then promote it to GHCR_TOKEN and remove GHCR_TOKEN_2.
if [[ -n "${GHCR_TOKEN_2}" ]]; then
    if ! curl -fsSL -o /dev/null \
            -H "Authorization: token ${GHCR_TOKEN}" \
            "https://api.github.com/repos/${GHCR_REPO}" 2>/dev/null; then
        GHCR_TOKEN="${GHCR_TOKEN_2}"
    fi
fi

curl -fsSL \
    -H "Authorization: token ${GHCR_TOKEN}" \
    "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
    -o /opt/fleet/docker-compose.yml

docker compose --env-file "${FLEET_ENV}" -f /opt/fleet/docker-compose.yml pull

_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
    "ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')
_DIGEST_UI=$(docker inspect --format='{{index .RepoDigests 0}}' \
    "ghcr.io/${GHCR_REPO}-ui:${IMAGE_TAG}" 2>/dev/null | awk -F@ '{print $2}')

_upsert_env() {
    local key=$1 val=$2 file=$3
    if grep -q "^${key}=" "${file}"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "${file}"
    else
        echo "${key}=${val}" >> "${file}"
    fi
}

_upsert_env RUNNING_IMAGE_DIGEST    "${_DIGEST:-}"    "${FLEET_ENV}"
_upsert_env RUNNING_IMAGE_DIGEST_UI "${_DIGEST_UI:-}" "${FLEET_ENV}"

# --force-recreate: a same-tag digest change (e.g. pilot->new pilot) otherwise
#   leaves the old container running; force it so the pulled image is swapped in.
# --remove-orphans: clear any half-finished Watchtower swap leftovers
#   (<hash>_aquila-backend) so they don't linger and fight for the same ports.
docker compose --env-file "${FLEET_ENV}" -f /opt/fleet/docker-compose.yml up -d --force-recreate --remove-orphans

mkdir -p /opt/aquila/tests
