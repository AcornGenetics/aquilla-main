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

1. Merge to `main` → CI builds `:latest` + `:<sha>`
2. **Cut a version** → run **build-and-push-images** with `action=cut-version` (builds the `:<version>` images + a GitHub Release)
3. **Assign it to a ring** → run **build-and-push-images** with `action=assign-ring`, `version=<x.y.z>`, `ring=dev|pilot|prod`
4. Devices on that ring pull the new tag (Watchtower or manual `pull`)

## Cut and Assign Versions

Both happen on the **build-and-push-images** "Run workflow" screen via the `action` input.

### Cut a version (`action=cut-version`)

Mints the next version (leave `version` blank to auto patch-bump, or type an exact one),
builds the `:<version>` images with the version baked in, and creates a GitHub Release.
Does **not** touch any ring.

### Assign a version to a ring (`action=assign-ring`)

Set `version=<x.y.z>` and `ring=dev|pilot|prod`. Retags that already-built version onto the
ring **by digest** — no rebuild, so the tested bytes and the baked version are preserved.
Refuses a version that has no built image (you must cut it first).

> The standalone `promote-images` workflow still exists, but `assign-ring` is the supported
> path (it gates on the image existing, so an un-versioned build can't reach a ring).

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
