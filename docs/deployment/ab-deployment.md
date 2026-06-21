# A/B Deployment System — Sentri Devices

## Why This Exists

Watchtower can pull and restart containers, but it cannot hard-gate promotion on test results.
If a new image crashes or fails hardware checks, Watchtower's lifecycle hook failures are logged
but do not block the restart. This system adds a true pass/fail gate so a bad image never
replaces the live slot.

---

## Core Concept

Two independent ideas:

- **Image version** — what CI built: `ghcr.io/acorngenetics/sentri-api:<git-sha>`
- **Slot** — where that version runs on the device: `A` or `B`

CI builds one image per version. The device controller decides which slot gets it.

**Rule:** deploy candidate to the slot that is NOT currently active.

| Active slot | Deploy candidate to |
|-------------|---------------------|
| A | B |
| B | A |

---

## Architecture

### Slots

| Slot A | Slot B |
|--------|--------|
| `sentri-backend-a` | `sentri-backend-b` |
| `sentri-app-a` | `sentri-app-b` |
| `sentri-ui-a` | `sentri-ui-b` |

### Front Door (Proxy)

A small nginx proxy always exposes the same host ports:

- `8080` → active slot UI
- `8090` → active slot backend

Promotion = rewrite proxy upstream + reload. No port rebinding, no downtime.

### State Files on Device

```
/opt/aquila/config/active_slot              # contents: A or B
/opt/aquila/config/current_good_api_tag     # last known-good API image tag
/opt/aquila/config/current_good_ui_tag      # last known-good UI image tag
/opt/aquila/config/deploy.lock              # prevents concurrent deployments
```

---

## Compose File Structure

Replace the single `fleet-config/docker-compose.yml` with:

```
docker/docker-compose.base.yml      # shared volumes, networks, env, logging
docker/docker-compose.slot-a.yml    # backend-a, app-a, ui-a
docker/docker-compose.slot-b.yml    # backend-b, app-b, ui-b
docker/docker-compose.proxy.yml     # front-door nginx proxy
```

### Base file (shared across all slots)

- `/opt/aquila` volume mounts (results, logs, profiles, config)
- Hardware device mappings (`/dev/ttyUSB0`, `/dev/i2c-1`, `/dev/spidev*`, `/dev/gpiomem`)
- `sentri_internal` Docker network
- `extra_hosts: host.docker.internal:host-gateway`
- Logging: `json-file`, max 10m / 3 files
- Restart: `unless-stopped`

### Slot A example (slot B mirrors with `-b` suffix)

```yaml
services:
  backend-a:
    container_name: sentri-backend-a
    image: ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG_API}
    environment:
      SLOT: "A"
      BACKEND_URL: "http://sentri-backend-a:8090"
    networks: [sentri_internal]

  app-a:
    container_name: sentri-app-a
    image: ghcr.io/${GHCR_REPO}-api:${IMAGE_TAG_API}
    command: ["python3", "application.py"]
    environment:
      SLOT: "A"
      BACKEND_URL: "http://sentri-backend-a:8090"
    depends_on: [backend-a]
    networks: [sentri_internal]

  ui-a:
    container_name: sentri-ui-a
    image: ghcr.io/${GHCR_REPO}-ui:${IMAGE_TAG_UI}
    networks: [sentri_internal]
```

### Proxy (always running)

```yaml
services:
  proxy:
    container_name: sentri-proxy
    image: nginx:stable-alpine
    ports:
      - "8080:80"
      - "8090:8090"
    volumes:
      - /opt/aquila/config/proxy.conf:/etc/nginx/conf.d/default.conf:ro
    networks: [sentri_internal]
    restart: unless-stopped
```

Proxy config template for slot A (`docker/nginx.proxy-a.conf`):

```nginx
upstream active_backend { server sentri-backend-a:8090; }
upstream active_ui      { server sentri-ui-a:80; }

server {
    listen 8090;
    location / { proxy_pass http://active_backend; }
}
server {
    listen 80;
    location / { proxy_pass http://active_ui; }
}
```

Slot B version is identical with `-b` container names.

---

## Scripts

### `scripts/deploy_candidate.sh`

```
Inputs: $API_TAG $UI_TAG
1. Acquire deploy.lock (exit if already locked)
2. Read ACTIVE_SLOT from /opt/aquila/config/active_slot
3. Set TARGET_SLOT = opposite
4. Export IMAGE_TAG_API, IMAGE_TAG_UI, SLOT for target
5. docker compose up target slot (detached)
6. Call validate_slot.sh $TARGET_SLOT
7. If exit 0: call promote_slot.sh $TARGET_SLOT
8. If nonzero: call rollback_slot.sh $TARGET_SLOT; exit 1
9. Release deploy.lock
```

### `scripts/validate_slot.sh`

Builds on existing `compose_smoke_test.sh` and `verify_fleet_device.sh` logic:

```
Inputs: $SLOT (A or B)
1. Wait up to 60s for all slot containers to reach running state
2. Check none are in restart loop (restart count < 3)
3. Check Docker health status (backend has HEALTHCHECK already)
4. GET http://sentri-backend-{slot}:8090/health → expect 200
5. GET http://sentri-backend-{slot}:8090/version → expect 200
6. GET http://sentri-ui-{slot}:80/ → expect 200
7. Confirm application.py process alive in sentri-app-{slot}
8. Verify /opt/aquila/profiles exists and is non-empty
9. Check /dev/ttyUSB0, /dev/i2c-1, /dev/spidev0.0 are present
10. Scan last 50 log lines of each container for: ImportError, PermissionError, crash
11. Exit 0 on full pass, nonzero on any failure
```

### `scripts/promote_slot.sh`

```
Inputs: $TARGET_SLOT
1. Copy docker/nginx.proxy-{target_slot}.conf → /opt/aquila/config/proxy.conf
2. docker exec sentri-proxy nginx -s reload
3. Write TARGET_SLOT → /opt/aquila/config/active_slot
4. Write API_TAG → /opt/aquila/config/current_good_api_tag
5. Write UI_TAG → /opt/aquila/config/current_good_ui_tag
6. (Optional) Stop old slot after 60s grace period
```

### `scripts/rollback_slot.sh`

```
Inputs: $TARGET_SLOT (the slot that failed)
1. Stop target slot containers
2. Proxy config is unchanged (still points to old active slot)
3. active_slot file is unchanged
4. Log failure with timestamp and image tags attempted
5. Exit 1
```

---

## Deployment Flow

```
CI pushes ghcr.io/acorngenetics/sentri-api:<sha>
                         │
                         ▼
          deploy_candidate.sh <api-sha> <ui-sha>
                         │
              ┌──────────┴──────────┐
              │  read active_slot   │
              │  target = opposite  │
              └──────────┬──────────┘
                         │
              docker compose up slot-{target}
                         │
              validate_slot.sh {target}
                         │
              ┌──────────┴──────────┐
              │                     │
            PASS                  FAIL
              │                     │
    promote_slot.sh         rollback_slot.sh
    proxy → target          stop target
    active_slot = target    active_slot unchanged
    known-good tags saved   log failure
```

---

## Watchtower Role (Reduced)

Keep Watchtower running but restrict it:

```yaml
watchtower:
  command: >
    --label-enable
    --http-api-update
    --http-api-periodic-polls
    --cleanup
    --interval 300
```

- Only manages containers with `com.centurylinklabs.watchtower.enable=true`
- Remove that label from slot containers — Watchtower should **not** touch `sentri-backend-a/b`, `sentri-ui-a/b`
- Watchtower can optionally be used to notify when new images are available, triggering `deploy_candidate.sh` via webhook

---

## Environment Variables Per Slot

```bash
# Slot A
SLOT=A
IMAGE_TAG_API=<git-sha>
IMAGE_TAG_UI=<git-sha>
BACKEND_URL=http://sentri-backend-a:8090
KIOSK_CONTROL_URL=http://host.docker.internal:9191

# Slot B  
SLOT=B
IMAGE_TAG_API=<git-sha>
IMAGE_TAG_UI=<git-sha>
BACKEND_URL=http://sentri-backend-b:8090
KIOSK_CONTROL_URL=http://host.docker.internal:9191
```

---

## Safety Rules

1. Never touch the active slot until validation passes
2. Always use immutable tags (git SHA) — never `latest` or `prod` for deployment decisions
3. Use the deploy lock to prevent concurrent deployments
4. Store state locally so a mid-update reboot recovers correctly
5. Proxy switch = promotion — never rebind host ports

---

## Implementation Task List

### Phase 1 — Foundation

- [ ] Create `docker/docker-compose.base.yml` with shared volumes, networks, device mounts
- [ ] Create `docker/docker-compose.slot-a.yml` (backend-a, app-a, ui-a)
- [ ] Create `docker/docker-compose.slot-b.yml` (backend-b, app-b, ui-b)
- [ ] Create `docker/docker-compose.proxy.yml` (sentri-proxy)
- [ ] Create `docker/nginx.proxy-a.conf` and `docker/nginx.proxy-b.conf`
- [ ] Initialize state files: `active_slot=A`, `current_good_api_tag`, `current_good_ui_tag`
- [ ] Update `scripts/setup/device_prod.sh` (and dev/pilot) to write initial `active_slot=A`

### Phase 2 — Scripts

- [ ] Write `scripts/validate_slot.sh` — extend existing `compose_smoke_test.sh` checks + hardware checks
- [ ] Write `scripts/promote_slot.sh` — proxy swap + state file update
- [ ] Write `scripts/rollback_slot.sh` — stop target, leave active unchanged
- [ ] Write `scripts/deploy_candidate.sh` — orchestrates the above three
- [ ] Add deploy lock (`/opt/aquila/config/deploy.lock`) logic to prevent concurrent runs

### Phase 3 — Validation

- [ ] Test full cycle on a dev device: deploy to B, validate, promote to B
- [ ] Test failure path: deploy broken image to B, confirm traffic stays on A
- [ ] Test reboot recovery: confirm active_slot persists and proxy starts on correct slot
- [ ] Test rollback: confirm one command switches proxy back to previous slot

### Phase 4 — CI Integration

- [ ] Update GitHub Actions workflow to build with git SHA tag (not just `prod`/`dev`)
- [ ] Add step to trigger `deploy_candidate.sh` on device after image push (via SSH or Watchtower webhook)
- [ ] Remove `com.centurylinklabs.watchtower.enable=true` from slot containers in compose files

### Phase 5 — Hardening (Nice to Have)

- [ ] Post-promotion soak: monitor new active slot for 2 min, auto-rollback if health degrades
- [ ] Deployment report: write JSON log to `/opt/aquila/logs/deployments.log` per attempt
- [ ] Ring rollout: deploy to `dev` devices first, gate `stable`/`prod` on pass rate

---

## Recommended Agents for Implementation

| Agent | Role | Why |
|-------|------|-----|
| `planner` | Phase planning + task breakdown | Sequences the compose/script work without conflicts |
| `system-architect` | Compose structure + proxy design | Designs the base/slot/proxy split cleanly |
| `coder` | Write all 4 scripts + compose files | Core implementation agent |
| `tester` | Write validate_slot.sh + test scenarios | Extends existing smoke test; designs failure cases |
| `reviewer` | Review compose files + scripts | Catches security issues (privileged containers, secrets) |
| `cicd-engineer` | Update GitHub Actions workflow | Adds git SHA tagging + deploy trigger step |
| `sparc-coord` | Orchestrate all agents together | Runs planner → architect → coder → tester → reviewer in sequence |

**Suggested spawn order for a swarm build:**

1. `planner` — produces detailed task list with file ownership
2. `system-architect` + `cicd-engineer` (parallel) — compose design + CI design
3. `coder` — implements all scripts and compose files
4. `tester` — writes validate_slot.sh and test scenarios
5. `reviewer` — final pass on security and correctness
