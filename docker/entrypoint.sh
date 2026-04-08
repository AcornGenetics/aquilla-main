#!/usr/bin/env bash
set -euo pipefail

profile_dir="${PROFILE_DIR:-/opt/aquila/profiles}"
bundled_profile_dir="${BUNDLED_PROFILE_DIR:-/opt/aquila/profiles_bundled}"
profile_config_path="${PROFILE_CONFIG_PATH:-/opt/aquila/config/profile_config.json}"
profile_bundle="${PROFILE_BUNDLE:-}"

if [[ -z "${profile_bundle}" && -f "${profile_config_path}" ]]; then
  profile_bundle=$(python - <<'PY'
import json
import os

path = os.environ.get("PROFILE_CONFIG_PATH", "/opt/aquila/config/profile_config.json")
try:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    data = {}

value = None
if isinstance(data, dict):
    value = data.get("profile_bundle") or data.get("profiles")

if isinstance(value, list):
    value = ",".join(str(item) for item in value if item)

if isinstance(value, str):
    print(value)
PY
  )
fi

if [[ -d "${bundled_profile_dir}" ]]; then
  mkdir -p "${profile_dir}"

  if [[ -z "${profile_bundle}" ]]; then
    if [[ -z "$(ls -A "${profile_dir}" 2>/dev/null)" ]]; then
      shopt -s nullglob
      for profile in "${bundled_profile_dir}"/*.json; do
        cp -n "${profile}" "${profile_dir}/"
      done
      shopt -u nullglob
    fi
  else
    IFS=',' read -ra bundled_profiles <<< "${profile_bundle}"
    for profile in "${bundled_profiles[@]}"; do
      profile_name="${profile//[[:space:]]/}"
      if [[ -n "${profile_name}" && -f "${bundled_profile_dir}/${profile_name}" ]]; then
        cp -n "${bundled_profile_dir}/${profile_name}" "${profile_dir}/${profile_name}"
      fi
    done
  fi
fi

exec "$@"
