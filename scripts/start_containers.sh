#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${REPO_ROOT}"

echo "Starting local containers (backend + UI)..."
docker compose -f docker/docker-compose.yml up -d

echo "Done. Use 'docker ps' to verify." 
