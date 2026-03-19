# Ring Rollout Guide (dev / pilot / prod)

This guide explains how ring tags work and how to promote images safely.

## Rings

- `dev`: internal devices (fastest updates)
- `pilot`: near‑prod devices (small rollout)
- `prod`: customer devices (full rollout)

Devices pick a ring with `IMAGE_TAG` in their env file:

```bash
IMAGE_TAG=dev
# or IMAGE_TAG=pilot
# or IMAGE_TAG=prod
```

## How Updates Flow

1. Push to `main` → CI builds `:latest` + `:<sha>`
2. Manually tag a ring (`dev`, `pilot`, or `prod`)
3. Devices on that ring pull the new tag (Watchtower or manual `pull`)

## Build and Tag Images

### Option A: Build with a ring tag

Run the GitHub Action **build-and-push-images** and set `ring_tag`:

- `ring_tag=dev` → publishes `:dev`
- `ring_tag=pilot` → publishes `:pilot`
- `ring_tag=prod` → publishes `:prod`

### Option B: Promote a tested SHA

Run **promote-images** with:

- `source_tag=<sha>`
- `target_tag=dev|pilot|prod`

This retags the existing image without rebuilding.

## Device Configuration

- Fleet devices use `/opt/aquila/config/device.env` to set `IMAGE_TAG`.
- Local compose defaults to `latest` unless `IMAGE_TAG` is set.

Example:

```bash
IMAGE_TAG=pilot
RUN_MODE=prod
DEVICE_ID=pi-001
```

## Setup Scripts

You can use the helper scripts under `scripts/setup/` to stamp the ring and
device metadata after running the fleet setup:

- `scripts/setup/device_dev.sh`
- `scripts/setup/device_pilot.sh`
- `scripts/setup/device_prod.sh`

Each script honors:

- `DEVICE_ID` (device name/identifier)
- `WATCHTOWER_HTTP_API_TOKEN` (unique per device)

## Watchtower Notes

Watchtower updates containers when the tag it tracks changes. If a device is
set to `IMAGE_TAG=pilot`, it will only update when `:pilot` moves.
