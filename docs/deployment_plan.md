# Deployment plan (containerized fleet updates)

## Table of contents

- [Architecture (what you’re building)](#architecture-what-youre-building)
  - [On each Raspberry Pi](#on-each-raspberry-pi)
  - [In AWS (cloud)](#in-aws-cloud)
  - [Optional (later)](#optional-later)
- [Step-by-step setup plan](#step-by-step-setup-plan)
  - [1) Containerize your app (UI + API)](#1-containerize-your-app-ui--api)
  - [2) Create ECR repositories](#2-create-ecr-repositories)
  - [3) GitHub Actions: build + push to ECR on every `main` commit](#3-github-actions-build--push-to-ecr-on-every-main-commit)
  - [4) Build the Manifest API (FastAPI) and deploy as Lambda-from-ECR](#4-build-the-manifest-api-fastapi-and-deploy-as-lambda-from-ecr)
  - [5) Create DynamoDB tables (device registry + status)](#5-create-dynamodb-tables-device-registry--status)
  - [6) Implement the Pi update-agent (systemd service on host)](#6-implement-the-pi-update-agent-systemd-service-on-host)
  - [7) Rollout strategy (fleet-safe)](#7-rollout-strategy-fleet-safe)
  - [8) Observability + safety checks (minimum)](#8-observability--safety-checks-minimum)
  - [9) Where Mender A/B fits (optional add-on later)](#9-where-mender-ab-fits-optional-add-on-later)
- [Steps list (clean summary)](#steps-list-clean-summary)
- [What you still need to decide](#what-you-still-need-to-decide)

## Architecture (what you’re building)

### On each Raspberry Pi

- Your app runs as Docker containers via Docker Compose:
  - `app-ui` (frontend)
  - `api` (FastAPI backend)
  - Optional: local `db` container if offline storage is required
- A small update-agent (systemd service on the host) that:
  1. Calls your cloud endpoint for a signed manifest
  2. Verifies the signature with a pinned public key
  3. Pulls images from ECR
  4. Flips the running version
  5. Health-checks
  6. Reports status
  7. Rolls back if unhealthy

### In AWS (cloud)

- ECR stores versioned container images (tag + digest)
- Manifest API: API Gateway (HTTP API) → Lambda (container image) running FastAPI
- DB (DynamoDB recommended): device registry, device status, desired versions
- Signing: AWS KMS (or Secrets Manager) used by the manifest API to sign manifests

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
     - `api` → `ECR_URI/api:<tag>` or `@sha256:<digest>`
     - `ui` → `ECR_URI/ui:<tag>` or `@sha256:<digest>`
   - Add `restart: always`
   - Add healthchecks in compose
4. Decide DB strategy:
   - Prefer cloud DB for fleet devices (Postgres/RDS, DynamoDB, etc.)
   - Only run local DB on Pi if you must support offline use

Outcome: your app can be started anywhere with `docker compose up -d`.

### 2) Create ECR repositories

1. Create ECR repos:
   - `yourapp-ui`
   - `yourapp-api`
   - Optional: `yourapp-manifest-api` (the Lambda container)
2. Configure ECR lifecycle policies (keep last N images, expire old untagged)
3. Create IAM permissions:
   - For GitHub Actions: build/push to ECR
   - For Pis: pull from ECR (read-only)

### 3) GitHub Actions: build + push to ECR on every `main` commit

1. Add workflow triggers:
   - `on` push to `main`
2. Workflow steps:
   - Checkout repo
   - Login to ECR
   - Build UI image
   - Build API image
   - Tag images with:
     - Git SHA (always)
     - Optional semver like `1.2.7` (recommended for readability)
   - Push to ECR
   - Capture resulting image digests (best for immutability)
3. Recommended: create a “release record”:
   - Store digests + version in DynamoDB or as GitHub Release output
   - Helps the manifest API reference exact digests

Outcome: every merge to `main` produces a deployable UI/API image pair in ECR.

### 4) Build the Manifest API (FastAPI) and deploy as Lambda-from-ECR

#### 4A) Design your manifest data model

Manifest should include:

- `manifest_version`
- `device_id` (or group)
- `desired_release` (e.g., `1.2.7`)
- `images` (use digests ideally)
  - `api`: `.../yourapp-api@sha256:...`
  - `ui`: `.../yourapp-ui@sha256:...`
- `compose_template_version` (optional)
- `issued_at`, `expires_at`
- `signature` (or separate signature field)

#### 4B) Endpoints (minimal)

1. `GET /v1/manifest?device_id=XYZ`:
   - Looks up device in DB
   - Determines which release that device should run
   - Returns signed manifest
2. `POST /v1/status`:
   - Device reports:
     - current release, current digests
     - update attempt result
     - health status
     - last error
     - timestamps
3. Optional: `POST /v1/register`:
   - First boot: device requests enrollment token → gets device record created

#### 4C) Signing (required)

- Use AWS KMS (ideal) to sign manifests
- Pi stores public key pinned locally
- Agent rejects unsigned/invalid manifests

#### 4D) Deploy

1. Containerize manifest API (`Dockerfile`)
2. Push it to ECR
3. Create Lambda using that ECR image
4. Put API Gateway HTTP API in front

Outcome: you have a simple “desired version” service that your Pis poll.

### 5) Create DynamoDB tables (device registry + status)

Recommended minimal tables:

1. `Devices`
   - `device_id` (PK)
   - `device_group` (e.g., beta/prod)
   - `desired_release` (optional override)
   - `last_seen`
   - `last_known_release`
2. `Releases`
   - `release_id` (PK) e.g. `1.2.7`
   - `ui_digest`, `api_digest`
   - `created_at`
3. `StatusEvents` (optional)
   - append-only log of status updates

Outcome: you can control rollout per-device or per-group.

### 6) Implement the Pi update-agent (systemd service on host)

#### 6A) Install base runtime on Pi

1. Install Docker
2. Install Docker Compose plugin
3. Create app directory:
   - `/opt/yourapp/`
4. Store:
   - `docker-compose.yml` (or a template)
   - `.env` file (where images/tags/digests are written)
   - `public_key.pem` (pinned public key)

#### 6B) Update agent logic (exact flow)

Runs every N minutes (or continuously with sleep):

1. Read local `device_id`
2. Call `GET /manifest?device_id=...`
3. Verify signature using pinned public key
4. Compare desired release vs current release
5. If new:
   - Write new image refs into `.env` (or a small `compose.override.yml`)
   - `docker compose pull`
   - `docker compose up -d` (recreate)
6. Health check:
   - call `http://localhost:<api_port>/health`
   - call UI endpoint
7. If healthy:
   - mark success locally (save “current release”)
   - report `POST /status` success
8. If unhealthy:
   - rollback to previous `.env` (previous release)
   - `docker compose up -d`
   - report failure + rollback performed

#### 6C) systemd service

- `yourapp-update-agent.service`:
  - starts on boot
  - restarts if it crashes
  - use logs via journald

Outcome: fully autonomous update loop with rollback.

### 7) Rollout strategy (fleet-safe)

Implement at least one of:

- Device groups: beta devices get new release first, then prod
- Staged percent rollout: manifest API returns new release to X% of devices
- Pin/hold: ability to freeze a device on current release

Outcome: you avoid bricking every Pi at once.

### 8) Observability + safety checks (minimum)

- Each Pi sends status:
  - “download started”, “restart complete”, “health ok”, “rollback done”
- Cloud dashboard could be as simple as:
  - DynamoDB + CloudWatch logs queries
- Add alarms:
  - if >N devices rollback on same release, stop rollout

### 9) Where Mender A/B fits (optional add-on later)

If you want OS-level atomic updates:

- Use Mender to manage A/B partitions and OS images
- Keep Docker-based app updates for frequent app changes
- Use Mender for infrequent base-image updates:
  - kernel, drivers, system libs, Docker version, etc.

Outcome: containers handle “app”, Mender handles “platform”.

## Steps list (clean summary)

1. Create Docker containers for UI + API (+ optional DB).
2. Create ECR repos to store images.
3. GitHub Actions builds + pushes images to ECR on each `main` commit (tag + digest).
4. Create release record (store digests/version in DynamoDB).
5. Create Manifest API (FastAPI) and deploy as Lambda from ECR image.
6. Manifest API returns signed manifest with desired release + image digests.
7. Pi update-agent (systemd) polls manifest, verifies signature, pulls images, flips, health checks, rolls back, reports status.
8. Add rollout controls (groups/percent) + monitoring.
9. Later: add Mender for OS A/B partitioning.

## What you still need to decide

- Endpoint style: API Gateway HTTP API is great; FastAPI works fine behind it in Lambda container.
- FastAPI endpoints (recommended):
  - `GET /v1/manifest`
  - `POST /v1/status`
  - Optional: `POST /v1/register`

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
