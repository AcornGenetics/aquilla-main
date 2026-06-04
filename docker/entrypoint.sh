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
