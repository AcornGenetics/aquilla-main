# Full Fleet Deployment Setup

This guide covers the full end‑to‑end setup for a new device.

## Base OS setup

Run the base deployment script once per device:

```bash
scripts/deployment1.sh
```

## Per‑device setup

1) Run setup:

```bash
scripts/setup_fleet_device.sh
```

2) Set device env:

Edit `/opt/aquila/config/device.env`:

- `DEVICE_ID=...`
- `IMAGE_TAG=dev|pilot|prod`
- `WATCHTOWER_HTTP_API_TOKEN=...` (or keep the generated one)

Or use a ring script instead of editing manually:

```bash
DEVICE_ID=pi-001 scripts/setup/device_dev.sh
DEVICE_ID=pi-002 scripts/setup/device_pilot.sh
DEVICE_ID=pi-003 scripts/setup/device_prod.sh
```

3) Login to GHCR (if images are private):

```bash
echo '<PAT>' | docker login ghcr.io -u <user> --password-stdin
```

4) Start / verify:

```bash
docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d
docker ps
```

## Tailscale (per device)

1) Generate a Linux server install script in Tailscale admin (pre‑auth key).
2) Run the script on the device.
3) Authenticate:

```bash
sudo tailscale up --ssh --authkey <key> --hostname <device-id>
```

If you don’t use a key:

```bash
sudo tailscale up --ssh
```

## Optional

```bash
pytest tests/fleet_device
```
