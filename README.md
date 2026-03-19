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
- `profiles/`: assay/profile JSON files
- `logs/` and `data/`: results, logs, and run artifacts
- `docs/`: internal documentation

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

## Local Development
- Backend (FastAPI): run from `aquila_web/` with `uvicorn main:app --host 127.0.0.1 --port 8090`
- Simulated runs: `AQ_DEV_SIMULATE=1 AQ_DEV_RUN_DURATION=10 uvicorn main:app --host 127.0.0.1 --port 8090`

## Deployment Scripts
- Base setup: `deployment1.sh`
- Fleet setup: `scripts/setup_fleet_device.sh`
- Ring helpers: `scripts/setup/device_dev.sh`, `scripts/setup/device_pilot.sh`, `scripts/setup/device_prod.sh`

## Runbook
- Start backend UI (local): `cd aquila_web && uvicorn main:app --host 127.0.0.1 --port 8090`
- Start backend UI (simulated): `cd aquila_web && AQ_DEV_SIMULATE=1 AQ_DEV_RUN_DURATION=10 uvicorn main:app --host 127.0.0.1 --port 8090`
- Start assay loop (hardware): `python application.py`
- Start Streamlit plotter: `streamlit run PCR_plot.py`
- Start local Docker stack: `docker compose -f docker/docker-compose.yml up -d`
- Start fleet stack: `docker compose --env-file /opt/aquila/config/device.env -f /opt/fleet/docker-compose.yml up -d`
