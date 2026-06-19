# Sentri On-Device Testing Pipeline

## Overview

A two-lane deployment pipeline that prevents bad images from replacing a working system:

- **Stable lane** — what the device is currently trusted to run
- **Candidate lane** — every newly pulled image goes here first, gets tested on-device, and is only promoted if it passes

---

## Core Principles

### 1. Never let a new image replace production immediately

Do not have watchtower pull a new image and directly restart the production container.

Flow:
1. CI builds image → pushes candidate tag or immutable digest
2. Device pulls that image
3. Device starts a candidate stack on isolated ports/network
4. Tests run against candidate
5. Only if tests pass does the device update the stable service to that exact digest

Watchtower monitors containers selectively — keep your production lane separate from your test lane.

### 2. Put the tests on the device, not just in CI

Use a split between a host orchestrator and a test container:

| Component | Responsibilities |
|---|---|
| **Host orchestrator** | Pull candidate image, launch candidate Compose profile, wait for health, run test container, record pass/fail, promote or roll back |
| **Test container** | Run pytest suite, hit HTTP endpoints, check container states, run feature/regression tests, optionally trigger hardware tests |

This makes it AI-agent friendly — an agent can always run:
```bash
make test-device
```
and get the same result a human would.

### 3. Treat container health as the first gate

Every service must have a real Docker `HEALTHCHECK`, not just "container started." Use `depends_on` with `condition: service_healthy`.

```yaml
services:
  backend:
    image: ghcr.io/acorngenetics/aquilla-main-api:${IMAGE_TAG}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8090/health"]
      interval: 10s
      timeout: 3s
      retries: 6
      start_period: 20s

  ui:
    image: ghcr.io/acorngenetics/aquilla-main-ui:${IMAGE_TAG}
    depends_on:
      backend:
        condition: service_healthy
```

---

## Compose Structure

Use Compose profiles to keep testing optional but built-in:

| Profile | Services |
|---|---|
| *(default)* | `backend`, `ui` |
| `candidate` | `backend_candidate`, `ui_candidate` |
| `test` | `tester` |

```yaml
services:
  backend:
    image: ghcr.io/acorngenetics/aquilla-main-api:${STABLE_DIGEST}
    ports: ["8090:8090"]

  backend_candidate:
    image: ${CANDIDATE_IMAGE}
    profiles: ["candidate"]
    ports: ["18090:8090"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8090/health"]
      interval: 10s
      timeout: 3s
      retries: 6

  tester:
    build: ./tests/runner
    profiles: ["test"]
    depends_on:
      backend_candidate:
        condition: service_healthy
    environment:
      BASE_URL: http://backend_candidate:8090
```

Production stays untouched while the candidate comes up alongside it.

---

## Test Layers

Ordered from cheapest to most expensive:

| Marker | Description | Default |
|---|---|---|
| `smoke` | App boots, health endpoint, core endpoint returns | on |
| `contract` | API responses match expected schema | on |
| `integration` | Multiple containers working together | on |
| `regression` | Known bugs that must never return | on |
| `hardware` | GPIO, camera, sensor, touchscreen, serial | on (when hardware affected) |
| `destructive` | Can alter device state | **off by default** |

```ini
# pytest.ini
[pytest]
markers =
    smoke: fast core checks
    contract: api contract tests
    integration: multi-service tests
    hardware: requires device hardware
    regression: protects against previously fixed bugs
    destructive: changes persistent state
```

Use `pytest-xdist` for parallelization when speed matters (`pytest -n auto`).

---

## Scripts

### `scripts/test_candidate.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

CANDIDATE_IMAGE="${1:?candidate image required}"

echo "Pulling candidate image..."
docker pull "$CANDIDATE_IMAGE"

echo "Starting candidate stack..."
CANDIDATE_IMAGE="$CANDIDATE_IMAGE" \
docker compose --profile candidate up -d backend_candidate ui_candidate

echo "Waiting for candidate health..."
timeout 90 bash -c '
  until [ "$(docker inspect -f "{{.State.Health.Status}}" $(docker compose ps -q backend_candidate))" = "healthy" ]; do
    sleep 2
  done
'

echo "Running smoke + integration + regression..."
docker compose --profile test run --rm tester \
  pytest -m "smoke or integration or regression" -q

echo "Candidate passed."
```

### `scripts/promote_candidate.sh`

Keep test and promote as **separate commands** so an agent cannot accidentally deploy just by running tests.

```bash
./scripts/promote_candidate.sh ghcr.io/acorngenetics/aquilla-main-api@sha256:...
```

---

## Promotion Policy

Promotion pins the exact digest that passed — never a floating tag.

Flow:
1. CI pushes `:sha-abc123`
2. Device tests digest `sha256:...`
3. Approval file updates stable reference to that digest
4. Production restarts on that digest only

### Approval criteria

A candidate is approved only if **all** of the following pass:
- Candidate containers become healthy
- Smoke tests pass
- Integration tests pass
- All regression tests pass
- No container exits unexpectedly during the test window
- Hardware tests pass (when affected areas changed)

If any fail, candidate is rejected and stable remains untouched.

---

## Test Result Artifact

Every test run writes a result locally:

```json
{
  "timestamp": "2026-04-15T16:22:00Z",
  "candidate_image": "ghcr.io/acorngenetics/aquilla-main-api@sha256:abcd...",
  "device_id": "sn03",
  "suite": ["smoke", "integration", "regression"],
  "result": "pass",
  "duration_seconds": 84,
  "git_sha": "abc1234"
}
```

Stored at: `/opt/aquila/test-results/`

Agents inspect the latest result before changing code.

---

## Repo Structure

```
aquila-main/
  docker/
    compose.yml
    compose.candidate.yml
  tests/
    runner/
      Dockerfile
      requirements.txt
    smoke/
      test_health.py
      test_core_api.py
    integration/
      test_sync_flow.py
      test_ui_backend.py
    regression/
      test_bug_014_touch_input.py
      test_bug_027_exit_gui.py
    hardware/
      test_gpio.py
      test_touchscreen.py
      test_camera.py
    conftest.py
    pytest.ini
  scripts/
    test_candidate.sh
    promote_candidate.sh
    rollback_stable.sh
    wait_for_health.sh
  state/
    approved.json
    last-test-result.json
  Makefile
```

---

## Makefile Interface

Agents and humans use the same commands:

```makefile
test-smoke:
	docker compose --profile candidate up -d backend_candidate ui_candidate
	docker compose --profile test run --rm tester pytest -m smoke -q

test-integration:
	docker compose --profile candidate up -d backend_candidate ui_candidate
	docker compose --profile test run --rm tester pytest -m integration -q

test-regression:
	docker compose --profile candidate up -d backend_candidate ui_candidate
	docker compose --profile test run --rm tester pytest -m regression -q

test-device:
	./scripts/test_candidate.sh $(CANDIDATE_IMAGE)

promote:
	./scripts/promote_candidate.sh $(CANDIDATE_IMAGE)
```

---

## GitHub Actions Integration

| Stage | Where it runs |
|---|---|
| Lint, unit tests, build image | Cloud CI runner |
| Hardware-aware integration tests | Self-hosted device/lab runner |
| Publish candidate | Cloud CI |
| On-device approval | Device-side script |
| Promote stable | `promote_candidate.sh` |

Self-hosted runners are labeled and targeted in workflow `runs-on`. Reusable workflows share the `build → test → publish candidate` pattern across repos.

---

## Triggering

Two options:

- **Explicit (recommended to start):** After each pull/update script, explicitly call the test pipeline. Easier to debug, safer.
- **Event-driven:** Watch `docker events` and trigger candidate tests when a pull or container restart is detected.

Start explicit. Add event-driven triggering once the pipeline is stable.

---

## On Watchtower

Do not make Watchtower the approval engine.

Let Watchtower (or your pull mechanism) **only fetch/update candidate material**. Let a separate test orchestrator decide whether production should move. Approval logic lives in your own script/service so it is explicit, testable, and agent-safe.

---

## Minimum First Implementation

Do this before adding anything else:

1. Add healthchecks to all containers
2. Create candidate versions of backend/ui on different ports
3. Create one tester container with pytest
4. Add `smoke` and `regression` markers
5. Add `test_candidate.sh`
6. Store `approved.json` with approved digest
7. Make stable startup read only from approved digest

---

## Summary

> Every new image is pulled as a candidate, launched in an isolated Compose profile, validated by on-device pytest-based smoke/integration/regression/hardware tests, and only then promoted by digest to the stable runtime.
