#!/usr/bin/env bash

set -euo pipefail

if [[ -f /opt/aquila/config/device.env ]]; then
  set -a
  # shellcheck source=/dev/null
  source /opt/aquila/config/device.env
  set +a
fi

echo "Checking running containers..."
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "aquila-(backend|ui|watchtower|node-exporter|vmagent|vector)" || true

echo "Checking backend health (if running)..."
if docker ps --format "{{.Names}}" | grep -q "aquila-backend"; then
  docker inspect --format '{{json .State.Health}}' aquila-backend || true
fi

echo "Checking Watchtower API (if running)..."
if docker ps --format "{{.Names}}" | grep -q "aquila-watchtower"; then
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

echo "Recent vmagent logs (if running)..."
docker logs --tail 20 aquila-vmagent 2>/dev/null || true

echo "Recent vector logs (if running)..."
docker logs --tail 20 aquila-vector 2>/dev/null || true
