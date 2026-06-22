#!/usr/bin/env bash

set -euo pipefail

if [[ -f /opt/aquila/config/device.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/aquila/config/device.env
  set +a
fi

echo "Checking running containers..."
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "sentri-(backend|ui|watchtower|node-exporter)" || true

echo "Checking backend health (if running)..."
if docker ps --format "{{.Names}}" | grep -q "sentri-backend"; then
  docker inspect --format '{{json .State.Health}}' sentri-backend || true
fi

echo "Checking Watchtower API (if running)..."
if docker ps --format "{{.Names}}" | grep -q "sentri-watchtower"; then
  if [[ -n "${WATCHTOWER_HTTP_API_TOKEN:-}" ]]; then
    curl -s -o /dev/null -w "Watchtower API status: %{http_code}\n" \
      -X POST -H "Authorization: Bearer ${WATCHTOWER_HTTP_API_TOKEN}" \
      http://localhost:8081/v1/update || true
  else
    echo "WATCHTOWER_HTTP_API_TOKEN is not set in the environment."
  fi
fi

echo "Checking node-exporter metrics endpoint..."
curl -s -o /dev/null -w "Node exporter status: %{http_code}\n" http://localhost:9100/metrics || true

