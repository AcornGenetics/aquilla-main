#!/usr/bin/env sh
set -e

compose_file="compose.yaml"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed"
  exit 1
fi

docker compose -f "$compose_file" config
docker compose -f "$compose_file" build
docker compose -f "$compose_file" up -d --remove-orphans

docker compose -f "$compose_file" ps

container_ids=$(docker compose -f "$compose_file" ps -q)
if [ -n "$container_ids" ]; then
  docker inspect --format='{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' $container_ids
fi

curl -fsS http://localhost:8090/health
curl -fsS http://localhost:8090/version
curl -fsSI http://localhost:8080/
