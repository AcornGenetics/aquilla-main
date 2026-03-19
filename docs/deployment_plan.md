# Deployment plan (GitHub/GHCR fleet updates)

## Table of contents

- [Architecture (what you’re building)](#architecture-what-youre-building)
  - [On each Raspberry Pi](#on-each-raspberry-pi)
  - [In GitHub (registry + CI)](#in-github-registry--ci)
  - [Optional (later)](#optional-later)
- [Step-by-step setup plan](#step-by-step-setup-plan)
  - [1) Containerize your app (UI + API)](#1-containerize-your-app-ui--api)
  - [2) Create GHCR repositories](#2-create-ghcr-repositories)
  - [3) GitHub Actions: build + push to GHCR on every `main` commit](#3-github-actions-build--push-to-ghcr-on-every-main-commit)
  - [4) Implement device update flow](#4-implement-device-update-flow)
  - [5) Rollout strategy (fleet-safe)](#5-rollout-strategy-fleet-safe)
  - [6) Observability + safety checks (minimum)](#6-observability--safety-checks-minimum)
  - [7) Where Mender A/B fits (optional add-on later)](#7-where-mender-ab-fits-optional-add-on-later)
- [Steps list (clean summary)](#steps-list-clean-summary)
- [What you still need to decide](#what-you-still-need-to-decide)

## Architecture (what you’re building)

### On each Raspberry Pi

- Your app runs as Docker containers via Docker Compose:
  - `app-ui` (frontend)
  - `api` (FastAPI backend)
  - Optional: local `db` container if offline storage is required
- A simple update loop that:
  1. Pulls new images from GHCR (Watchtower or manual)
  2. Restarts containers
  3. Health-checks
  4. Reports status

### In GitHub (registry + CI)

- GHCR stores versioned container images (tag + digest)
- GitHub Actions builds and pushes images on each `main` commit
- Ring tags (`dev/pilot/prod`) control which devices update

### Optional (later)

- Mender for A/B partitioning so you can safely update OS/rootfs too
- Keep containers for app updates; Mender handles OS-level safety

## Step-by-step setup plan

### 1) Containerize your app (UI + API)

1. Create Dockerfiles:
   - `ui/Dockerfile` (React/Vue/etc.)
   - `api/Dockerfile` (FastAPI)
2. Implement health endpoints:
   - API: `GET /health` returns 200 when dependencies are OK
   - UI: return 200 for `/` (or `/health` if you add one)
3. Create a `docker-compose.yml` for the Pi:
   - Uses pinned image references (tag or digest)
   - Example services:
    - `api` → `ghcr.io/<org>/aquila-api:<tag>` or `@sha256:<digest>`
    - `ui` → `ghcr.io/<org>/aquila-ui:<tag>` or `@sha256:<digest>`
   - Add `restart: always`
   - Add healthchecks in compose
4. Decide DB strategy:
   - Prefer a centralized DB if needed for fleet tracking
   - Only run local DB on Pi if you must support offline use

Outcome: your app can be started anywhere with `docker compose up -d`.

### 2) Create GHCR repositories

1. Create GHCR repos:
   - `aquila-ui`
   - `aquila-api`
   - Optional: `aquila-streamlit`
2. Configure GHCR retention (keep last N images, expire old untagged)
3. Create permissions:
   - For GitHub Actions: build/push to GHCR
   - For Pis: pull from GHCR (read-only PAT or token)

### 3) GitHub Actions: build + push to GHCR on every `main` commit

1. Add workflow triggers:
   - `on` push to `main`
2. Workflow steps:
   - Checkout repo
   - Login to GHCR
   - Build UI image
   - Build API image
   - Tag images with:
     - Git SHA (always)
     - Optional semver like `1.2.7` (recommended for readability)
   - Push to GHCR
   - Capture resulting image digests (best for immutability)
Outcome: every merge to `main` produces a deployable UI/API image pair in GHCR.

### 4) Implement device update flow

Use one of these approaches:

1. Watchtower
   - Devices run Watchtower with label-based updates
   - Update triggered via Watchtower HTTP API
2. Manual pull
   - `docker compose pull`
   - `docker compose up -d`

Devices choose release via `IMAGE_TAG` (`dev/pilot/prod`) in `device.env`.

### 5) Rollout strategy (fleet-safe)

Implement at least one of:

- Device groups: beta devices get new release first, then prod
- Staged promotion: promote tags in waves once health metrics pass
- Pin/hold: ability to freeze a device on current release

Outcome: you avoid bricking every Pi at once.

### 6) Observability + safety checks (minimum)

- Each Pi sends status:
  - “download started”, “restart complete”, “health ok”, “rollback done”
- Central dashboard could be as simple as:
  - Grafana/Logs from the existing fleet telemetry stack
- Add alarms:
  - if >N devices rollback on same release, stop rollout

### 7) Where Mender A/B fits (optional add-on later)

If you want OS-level atomic updates:

- Use Mender to manage A/B partitions and OS images
- Keep Docker-based app updates for frequent app changes
- Use Mender for infrequent base-image updates:
  - kernel, drivers, system libs, Docker version, etc.

Outcome: containers handle “app”, Mender handles “platform”.

## Steps list (clean summary)

1. Create Docker containers for UI + API (+ optional DB).
2. Create GHCR repos to store images.
3. GitHub Actions builds + pushes images to GHCR on each `main` commit (tag + digest).
4. Devices pull updates via Watchtower or manual `docker compose pull`.
5. Use ring tags (`dev/pilot/prod`) to control rollout.
6. Add monitoring/log shipping as needed.
7. Later: add Mender for OS A/B partitioning.

## What you still need to decide

- Update mechanism: Watchtower API vs manual pulls on each device.
- Tag strategy: how you promote `dev` → `pilot` → `prod`.
- Access control: device auth for GHCR pulls.

## Progress log

- 2026-02-24: Added `GET /health` FastAPI endpoint in `aquila_web/main.py`.
- 2026-02-24: Added `GET /version` FastAPI endpoint in `aquila_web/main.py`.
- 2026-02-24: Smoke-checked that `/health` and `/version` routes are registered.
- 2026-02-24: Added container healthchecks to API/UI Dockerfiles and updated compose version.
- 2026-02-24: Added `scripts/compose_smoke_test.sh` to validate Docker Compose setup.
- 2026-02-24: Removed the Streamlit service from the device `docker-compose.yml`.
- 2026-02-24: Updated `scripts/compose_smoke_test.sh` to remove orphans and handle missing healthchecks.
- 2026-02-24: Added `matplotlib` to `requirements-backend.txt` for the API container.
- 2026-02-24: Added root `compose.yaml` so `docker compose up` works by default.
