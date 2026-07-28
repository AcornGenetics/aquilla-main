#!/usr/bin/env bash
set -euo pipefail

profile_dir="${PROFILE_DIR:-/opt/aquila/profiles}"
bundled_profile_dir="${BUNDLED_PROFILE_DIR:-/opt/aquila/profiles_bundled}"

if [[ -d "${bundled_profile_dir}" ]]; then
  mkdir -p "${profile_dir}/bundled"
  shopt -s nullglob
  for profile in "${bundled_profile_dir}"/*.json; do
    cp -f "${profile}" "${profile_dir}/bundled/"
  done
  shopt -u nullglob
fi

# Sync host-side helper scripts out to /opt/fleet (#355).
#
# Container images are the ONLY automatic delivery path to a device. Host
# scripts have none: /opt/fleet/update.sh is written once by deployment2.sh at
# provisioning and never refreshes itself, so anything fetched from GitHub at
# provisioning time is frozen there forever.
#
# Shipping helpers in the image and writing them out here fixes that, and it
# keeps them versioned with the ring the device is on — a pilot device gets the
# pilot build's script, not whatever main says right now. That matters for a
# script that deletes images: bugs in it should soak through
# sandbox -> dev -> pilot -> prod like everything else.
#
# Only the backend service bind-mounts /opt/fleet, so this is a no-op in the
# app container. Best-effort: an absent or read-only mount must never stop the
# backend from starting.
fleet_dir="${FLEET_DIR:-/opt/fleet}"
helper_src="/opt/aquila/scripts/deploy"
if [[ -d "${fleet_dir}" && -w "${fleet_dir}" ]]; then
  for helper in prune-images.sh; do
    if [[ -f "${helper_src}/${helper}" ]]; then
      install -m 0755 "${helper_src}/${helper}" "${fleet_dir}/${helper}" \
        || echo "warning: could not sync ${helper} to ${fleet_dir}"
    fi
  done
fi

# If this container is running the hardware app, wait until the backend is
# healthy before starting. This removes the race condition without needing
# a compose-file change on each device.
if [[ "${1:-}" == *"application.py"* ]]; then
  backend_url="${BACKEND_URL:-http://aquila-backend:8090}"
  echo "Waiting for backend at ${backend_url}/health ..."
  for i in $(seq 1 30); do
    if curl -sf "${backend_url}/health" > /dev/null 2>&1; then
      echo "Backend ready."
      break
    fi
    sleep 2
  done
fi

exec "$@"
