#!/usr/bin/env bash
set -euo pipefail

profile_dir="${PROFILE_DIR:-/opt/aquila/profiles}"
bundled_profile_dir="${BUNDLED_PROFILE_DIR:-/opt/aquila/profiles_bundled}"

if [[ -d "${bundled_profile_dir}" ]]; then
  mkdir -p "${profile_dir}"
  shopt -s nullglob
  for profile in "${bundled_profile_dir}"/*.json; do
    cp -n "${profile}" "${profile_dir}/"
  done
  shopt -u nullglob
fi

exec "$@"
