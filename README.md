# Aquila
Aquila PCR system project.

## Quick Links
- Fleet setup: `docs/deployment/full_setup.md`
- Ring rollout guide: `docs/deployment/ring_rollout.md`
- Docker compose (local): `docker/docker-compose.yml`
- Fleet compose (device): `fleet-config/docker-compose.yml`

## Project Structure
- `aq_lib/`: hardware control drivers (motors, TEC, lid heater, state requests)
- `aq_curve/`: PCR curve analysis + results processing
- `aquila_web/`: FastAPI backend and UI routes
- `aquila_web/static/`: no-build HTML/CSS/JS UI assets
- `config_files/`: runtime configs and templates
- `config_files/meerstetter/`: Meerstetter XML configs copied to `/opt/aquila/config/meerstetter`
- `profiles/`: assay/profile JSON files
- `logs/` and `data/`: results, logs, and run artifacts
- `specs/`: spec-driven engineering — feature, backend, hardware, analysis, and testing specs
- `docs/`: internal documentation (ADRs, debugging, onboarding, architecture)

## Key Backend Files
- `aquila_web/main.py`: FastAPI app, API routes, simulation toggles
- `application.py`: main assay loop (hardware required)
- `state_run_assay.py`: assay state machine
- `config.py`: source base dir + config helpers

## Key Frontend Files
- `aquila_web/static/run.html`: primary run UI
- `aquila_web/static/history.html`: run history UI
- `aquila_web/static/script.js`: UI logic + WebSocket state updates
- `aquila_web/static/styles.css`: global styles

## Docker Images
- API Dockerfile: `docker/Dockerfile.api`
- UI Dockerfile: `docker/Dockerfile.ui`

## Bundled Profiles
- Place profiles you want baked into images in `profiles/bundled/`.
- On container start, bundled profiles are copied into `PROFILE_DIR` if it is empty.
- Set `PROFILE_BUNDLE` (comma-separated filenames) to copy only specific bundled profiles; listed files are copied even if `PROFILE_DIR` already has other profiles, and existing filenames are not overwritten.
- Or set `profile_bundle` in `config_files/profile_config.json` (mounted to `/opt/aquila/config/profile_config.json`) to control which bundled profiles are seeded on device.

## Contributing

### Spec-Driven Workflow

**No code without a spec.** Before writing code, find or create a spec in `specs/`:

```
specs/
  feature/    # User-facing features
  backend/    # API endpoints, data models
  hardware/   # Physical device behavior
  frontend/   # Screen layouts, kiosk UX
  analysis/   # Curve fitting, detection logic
  testing/    # Test plans, coverage targets
```

See `specs/SPEC_WORKFLOW.md` for the full workflow.

### GitHub Templates

- **Issues**: use `.github/ISSUE_TEMPLATE/` — bug report, feature request, or hardware issue
- **PRs**: link the relevant spec and complete the checklist in the PR template

### PR Checklist (summary)
- Spec file linked
- New tests written; full suite passes (`pytest tests unit_tests -v`)
- No secrets or `.env` files in diff
- ADR written if an irreversible architectural decision was made

---

## Testing

Tests live in two directories:
- `tests/` — contract and integration tests (FastAPI TestClient, no hardware)
- `unit_tests/` — pure logic tests (curve math, validation, path handling)

Run the full suite:
```bash
pytest tests unit_tests -v
```

### Markers
| Marker | Runs in CI | Description |
|--------|-----------|-------------|
| `unit` | Yes | No hardware, no network |
| `contract` | Yes | FastAPI TestClient only |
| `state` | Yes | State machine safety rules |
| `integration` | With `DEV_SIMULATE=1` | Simulated full run |
| `e2e` | With running frontend | Playwright browser tests |
| `hardware` | No — Pi only | Requires real GPIO/serial hardware |

### Feature Development
Every new feature must include tests. A feature is not complete until:
1. New tests are written (`tests/contract/` for API endpoints, `unit_tests/` for logic)
2. `pytest tests unit_tests -v` passes with no regressions

Hardware-only behavior that cannot be tested in CI should be documented with `@pytest.mark.hardware`.

## Local Development
- Backend (FastAPI): run from `aquila_web/` with `uvicorn main:app --host 127.0.0.1 --port 8090`
- Simulated runs: `AQ_DEV_SIMULATE=1 AQ_DEV_RUN_DURATION=10 uvicorn main:app --host 127.0.0.1 --port 8090`

## Deployment Scripts
- Base setup: `deployment1.sh`
- Fleet setup: `scripts/setup_fleet_device.sh`
- Ring helpers: `scripts/setup/device_sandbox.sh`, `scripts/setup/device_dev.sh`, `scripts/setup/device_pilot.sh`, `scripts/setup/device_prod.sh`

## Device Enrollment (Device Certificate)

After `deployment2.sh` has run on a Sentri (it generates the device keypair +
CSR), enrol it to get its mTLS **Device Certificate** from acorn-ca. Run from the
**operator's workstation** with AWS credentials — never on the Pi. The Pi must be
powered on (enrolment is two SSH round-trips: read the CSR, install the cert).

```bash
# one-shot: confirm CSR → enrol → verify over mTLS (defaults to PROD endpoints)
./scripts/enroll.sh sn03          # pass the serial-number host; SSHes as pi@sn03
```

Success prints `✅ sn03: enrolled + verified`. Full protocol, prerequisites, and
troubleshooting: [`docs/deployment/enrolling-a-device.md`](docs/deployment/enrolling-a-device.md).

## Versioning

The device UI displays the software version in the **Help** screen, at the bottom of the Help Topics panel.

To update the version:
1. Edit `aquila_web/static/help.html` — change the text inside `<p class="help-version">`.
2. Update this section with the new version number and a brief changelog note.

| Version | Notes |
|---------|-------|
| V 1.2.4 | PCR curve parameter tuning. Auto-update paused during active runs. |
| V 1.2.3 | PCR analysis improvements: baseline minimum, relative drop, result color updates. |
| V 1.1.0 | Initial versioned release. Version shown in Help screen. Purple run-start dot removed from Run screen. |

## Runbook
- Start backend UI (local): `cd aquila_web && uvicorn main:app --host 127.0.0.1 --port 8090`
- Start backend UI (simulated): `cd aquila_web && AQ_DEV_SIMULATE=1 AQ_DEV_RUN_DURATION=10 uvicorn main:app --host 127.0.0.1 --port 8090`
- Start assay loop (hardware): `python application.py`
- Start Streamlit plotter: `streamlit run PCR_plot.py`
- Start local Docker stack: `docker compose -f docker/docker-compose.yml up -d`
- Start fleet stack: `docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d`
