# Fleet Config

This directory contains the deployment compose file and monitoring/logging
templates intended to live on each device (or in a fleet-config repo).

## Device Setup

1. Copy `fleet-config/docker-compose.yml` to `/opt/fleet/docker-compose.yml`.
2. Copy `fleet-config/vmagent.yaml` to `/opt/fleet/vmagent.yaml.template`.
3. Copy `fleet-config/vector.yaml` to `/opt/fleet/vector.yaml.template`.
4. On each device, edit `/opt/aquila/config/device.env` with:
   - `DEVICE_ID`
   - `RUN_MODE`
   - `IMAGE_TAG` (`dev`, `stable`, or `prod`)
   - `WATCHTOWER_HTTP_API_TOKEN`
5. Edit `/opt/aquila/config/grafana.env` with:
   - `GRAFANA_METRICS_USER`
   - `GRAFANA_METRICS_TOKEN`
   - `GRAFANA_LOGS_USER`
   - `GRAFANA_LOGS_TOKEN`
6. Render templates:

```bash
set -a
source /opt/aquila/config/grafana.env
set +a
envsubst < /opt/fleet/vmagent.yaml.template > /opt/fleet/vmagent.yaml
envsubst < /opt/fleet/vector.yaml.template > /opt/fleet/vector.yaml
```

## Compose Run

```bash
docker login ghcr.io
docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml pull
docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d
```

## Ring Promotion

Use the GitHub Actions workflows:

- `build-and-push-images`: optional `ring_tag` input to publish `dev/stable/prod`
- `promote-images`: retag `source_tag` to `target_tag`

## Watchtower API Example

```bash
curl -X POST \
  -H "Authorization: Bearer $WATCHTOWER_HTTP_API_TOKEN" \
  http://localhost:8081/v1/update
```

## Secrets Note

Grafana credentials live in `/opt/aquila/config/grafana.env` and are rendered
into `/opt/fleet/vmagent.yaml` and `/opt/fleet/vector.yaml`.

## Deployment Checklist

- [x] GHCR build/push workflow with ring tags
- [x] Fleet compose with app + watchtower + node-exporter + vmagent + vector
- [x] Persistent volumes for app data, Vector, VMAgent
- [x] Device config in `/opt/aquila/config/device.env`
- [x] Watchtower API token + port mapping
- [ ] Tailscale installed on host + ACLs configured
- [ ] Loki/VictoriaMetrics endpoints configured in templates
- [ ] Fleet provisioning run on each Pi
