# Aquila

Aquila is a PCR instrument control system running on Raspberry Pi. It controls thermals, motors, optics, and a lid heater through a FastAPI backend + WebSocket UI, with Docker-based fleet deployment and Watchtower auto-updates.

---

## What it does

A PCR run goes through these stages:

1. Operator selects a profile (assay protocol) on the kiosk touchscreen
2. The assay loop (`application.py`) drives the hardware through each thermal cycle
3. The optical sensor reads fluorescence per tube per cycle
4. `aq_curve/` processes raw data: baseline correction → cross-talk removal → Cq detection
5. Results (Detected / Inconclusive / Not Detected per tube) are stored and shown on screen

---

## Quick start (on device)

```bash
# 1. On the Pi — bootstrap Tailscale
curl -fsSL "https://raw.githubusercontent.com/AcornGenetics/aquilla-main/main/scripts/setup/tailscale_bootstrap.sh" -o /tmp/tailscale_bootstrap.sh
sudo bash /tmp/tailscale_bootstrap.sh

# 2. SSH in from your laptop via Tailscale, then run the main deployment script
curl -fsSL "https://raw.githubusercontent.com/AcornGenetics/aquilla-main/main/deployment2.sh" -o /tmp/deployment2.sh
sudo bash /tmp/deployment2.sh

# 3. Verify the deployment
curl -fsSL "https://raw.githubusercontent.com/AcornGenetics/aquilla-main/main/deployment2_verify.sh" -o /tmp/deployment2_verify.sh
sudo bash /tmp/deployment2_verify.sh

# Start/restart the stack manually
sudo systemctl restart aquila-stack

# View logs
docker compose -f /opt/aquila/docker-compose.yml logs -f
```

The stack runs at `http://localhost:8080` (NGINX → FastAPI on 8090).

---

## Running tests

```bash
# All CI-compatible tests (contract + unit)
pytest tests unit_tests -v

# On-device candidate validation
./scripts/test_candidate.sh ghcr.io/acorngenetics/aquilla-main-api:<tag>

# Promote a candidate to stable (separate command — does not auto-run)
./scripts/promote_candidate.sh ghcr.io/acorngenetics/aquilla-main-api@sha256:<digest>
```

Test results are written to `/opt/aquila/test-results/` on the device.

---

## Key directories

| Path | What's in it |
|------|-------------|
| `aquila_web/` | FastAPI backend (`main.py`) + static HTML/JS frontend |
| `aq_lib/` | Hardware drivers: TEC, motors, optics, lid heater, fan |
| `aq_curve/` | PCR curve analysis: baseline, cross-talk, Cq, result calls |
| `fleet-config/` | Production `docker-compose.yml` (4 services + Watchtower) |
| `scripts/` | Device provisioning, kiosk control, Grafana setup |
| `config_files/` | Per-device and runtime config templates |
| `profiles/` | PCR assay protocol JSON files |
| `tests/` | Contract + integration + e2e tests |
| `unit_tests/` | Pure logic tests (curve math, validation) |

---

## Services (Docker)

| Service | Port | Role |
|---------|------|------|
| `aquila-backend` | 8090 | FastAPI REST + WebSocket |
| `aquila-app` | — | Assay loop (`application.py`) |
| `aquila-ui` | 8080 | NGINX — serves static UI, proxies to backend |
| `aquila-watchtower` | 8081 | Pulls updated images every 5 min |

All containers share `/dev/ttyUSB0` (TEC), `/dev/i2c-1` (optics/lid), GPIO, and `/opt/aquila/` volumes.

---

## Config files (on device at `/opt/aquila/config/`)

| File | Purpose |
|------|---------|
| `device.env` | `DEVICE_ID`, `IMAGE_TAG`, `GHCR_TOKEN`, `WATCHTOWER_HTTP_API_TOKEN` |
| `host_config.json` | Per-hostname hardware: PCR serial port, motor steps, ADC pins, drawer timing |
| `state_config.json` | UI state machine: maps states −5…6 to screen names |
| `lid_heater_config.json` | Heater voltage bounds |

---

## Docs

### Deployment
- [A/B Deployment System](deployment/ab-deployment.md) — Rolling A/B updates for the fleet
- [Fleet Deployment Plan](deployment/deployment_plan.md) — ECR, manifest API, Pi update agent
- [Device Security](deployment/device-security.md) — Pi kiosk hardening checklist

### Architecture
- [System Architecture](architecture/system_architecture.md) — Full architecture, wiring diagram, Docker services, PCR analysis pipeline
- [Motor Subsystem Specs](architecture/motor_specs.md) — Stepper motor hardware specs

### UI / Frontend
- [FastAPI GUI Migration Plan](ui/fastapi_gui_migration_plan.md) — Ongoing UI redesign checklist
- [Run Page Spec Sheet](ui/run-spec-sheet.md) — Design and behavior spec for the `/run` screen
- [Exit Button Fix Plans](ui/exit_button_fix_plans.md) — Kiosk exit button fix history and plan

### Testing
- [On-Device Testing Pipeline](testing/testing-pipeline.md) — Candidate/stable lane strategy, promotion policy
- [Test Suite](testing/tests.md) — Full test inventory by functional area

### Codebase
- [Repo Refactor Plan](codebase/refactor-plan.md) — Root cleanup and test consolidation
