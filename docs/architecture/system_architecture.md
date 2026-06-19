# Sentri System Architecture

## Overview

Sentri is a PCR instrument control system running on Raspberry Pi. It is composed of three independent Docker services (backend API, assay loop, UI), a hardware abstraction library, and a PCR curve analysis engine. Deployment is managed via Docker Compose with Watchtower for auto-updates across a fleet of devices.

---

## Directory Structure

```
aquilla-main/
├── sentri_web/          # FastAPI backend + static UI
│   ├── main.py          # All REST endpoints + WebSocket state sync
│   └── static/          # Vanilla HTML/CSS/JS frontend (no build step)
│       ├── script.js    # UI logic + WebSocket client
│       ├── profiles/    # Profile editor (edit.js, profiles.js)
│       ├── run.html     # PCR run screen
│       ├── ready.html   # Profile selection + run initiation
│       ├── complete.html# Results display
│       ├── history.html # Run history list
│       └── history_detail.html / history_detail.js
├── sentri_lib/              # Hardware control library
│   ├── meerstetter.py   # Thermal controller (TEC) serial protocol
│   ├── motor_class.py   # Stepper motors (carousel + drawer)
│   ├── lid_temperature.py # ADS1115 ADC lid temperature sensor
│   ├── regulate.py      # Lid heater PID worker
│   ├── tecControl.py    # TEC high-level interface
│   ├── thermal_engine.py# Thermal runaway detection
│   ├── state_requests.py# HTTP client → backend state endpoints
│   ├── hw_api.py        # High-level hardware abstraction
│   └── config_module.py # Loads host_config.json per hostname
├── sentri_curve/            # PCR curve analysis
│   ├── curve.py         # Baseline correction, cross-talk, Cq calculation
│   └── evaluator.py     # Positive/negative detection
├── docker/              # Container build files
│   ├── Dockerfile.api   # Backend + assay loop image
│   ├── Dockerfile.ui    # NGINX static + reverse proxy image
│   ├── nginx.conf       # Proxy config (8080 → 8090)
│   └── entrypoint.sh    # Seeds bundled profiles on container start
├── fleet-config/        # Production fleet deployment
│   └── docker-compose.yml # backend, app, ui, watchtower services
├── scripts/             # Device provisioning and diagnostics
│   ├── setup_fleet_device.sh
│   ├── setup_grafana_alloy_rpi.sh
│   └── kiosk-control/   # X11 + Chromium kiosk management
├── config_files/        # Runtime configuration templates
│   ├── host_config.json # Per-device hardware specs (hostname-keyed)
│   ├── state_config.json# UI state machine (states -5 to 6)
│   ├── lid_heater_config.json
│   ├── device.env       # Deployment env vars template
│   └── meerstetter/     # Thermal controller XML calibration files
├── profiles/            # PCR assay protocol definitions (JSON)
│   └── bundled/         # Profiles baked into container image
├── tests/               # Contract + integration tests
├── unit_tests/          # Pure logic tests (curve math, validation)
├── application.py       # Main assay execution entry point
├── state_run_assay.py   # Assay state machine + hardware orchestration
├── adc_class.py         # Optical sensor (I2C ADC) interface
├── fan_class.py         # PCR cooling fan control
├── deployment2.sh       # Full device provisioning script
└── deployment2_verify.sh# Post-deployment verification
```

---

## DDD Bounded Contexts

| Domain | Key Files | Responsibility |
|--------|-----------|----------------|
| **Device Control** | `sentri_lib/`, `adc_class.py`, `fan_class.py` | Motors, thermal, optics, GPIO |
| **PCR Analysis** | `sentri_curve/` | Curve processing, Cq calculation, result interpretation |
| **Web/API** | `sentri_web/main.py` | REST endpoints, WebSocket, profiles, history |
| **UI/Kiosk** | `sentri_web/static/`, `scripts/kiosk-control/` | Frontend screens, X11 kiosk, Chromium |
| **Deployment/Monitoring** | `fleet-config/`, `deployment2.sh`, `scripts/` | Docker Compose, Grafana Alloy, Watchtower, Tailscale |

---

## System Architecture

```
┌──────────────────────────────────────────────────────────┐
│  NGINX (aquila-ui, port 8080)                            │
│  Serves static HTML/CSS/JS, proxies / → backend:8090     │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP + WebSocket
┌────────────────────────▼─────────────────────────────────┐
│  FastAPI Backend (aquila-backend, port 8090)             │
│  sentri_web/main.py                                      │
│  ├─ REST: /run /stop /profiles /history /results         │
│  └─ WebSocket /ws → broadcasts state changes to UI       │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP (state_requests.py)
┌────────────────────────▼─────────────────────────────────┐
│  Assay Loop (aquila-app)                                 │
│  application.py → state_run_assay.py                     │
│  ├─ Orchestrates PCR protocol steps                      │
│  ├─ Runs thermal, motor, optics threads concurrently     │
│  └─ Posts state transitions to backend                   │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│  Hardware Layer (sentri_lib/)                                │
│  ├─ Thermal:  meerstetter.py → /dev/ttyUSB0             │
│  │            TEC PID control, Kp=80 Ti=5 Td=4           │
│  ├─ Motors:   motor_class.py → GPIO (step/dir/enable)    │
│  │            Drawer open/close + carousel positioning   │
│  ├─ Optics:   adc_class.py → /dev/i2c-1                 │
│  │            4-channel fluorescence reads per cycle     │
│  ├─ Lid:      regulate.py → GPIO pin 21                  │
│  │            PID heater with ADS1115 voltage feedback   │
│  └─ Fan:      fan_class.py → GPIO (binary on/off)        │
└────────────────────────┬─────────────────────────────────┘
                         │ Raw optical data
┌────────────────────────▼─────────────────────────────────┐
│  PCR Analysis (sentri_curve/)                                │
│  ├─ curve.py: baseline correction, cross-talk removal    │
│  ├─ Cq detection via threshold (default 0.2 per dye)     │
│  └─ evaluator.py: positive/negative call per tube        │
└──────────────────────────────────────────────────────────┘
```

---

## Docker Services

Defined in `fleet-config/docker-compose.yml`:

| Service | Image | Port | Role |
|---------|-------|------|------|
| `aquila-backend` | `*-api` | 8090 | FastAPI REST + WebSocket |
| `aquila-app` | `*-api` | — | Assay loop (`application.py`) |
| `aquila-ui` | `*-ui` | 8080 | NGINX static + reverse proxy |
| `aquila-watchtower` | `nickfedor/watchtower` | 8081 | Auto-update images every 5 min |

All services share hardware device access (`/dev/ttyUSB0`, `/dev/i2c-1`, `/dev/spidev0.*`, `/dev/gpiomem`) and mount `/opt/aquila/` volumes.

---

## Key Config Files (on device at `/opt/aquila/config/`)

| File | Purpose |
|------|---------|
| `device.env` | `DEVICE_ID`, `IMAGE_TAG`, `GHCR_TOKEN`, `WATCHTOWER_HTTP_API_TOKEN` |
| `host_config.json` | Per-hostname hardware specs: PCR serial port, motor steps, ADC pins, drawer timing |
| `state_config.json` | UI state machine: maps states −5…6 to screen names + instruction text |
| `lid_heater_config.json` | Heater bounds: `lower_bound`, `upper_bound` voltage thresholds |
| `meerstetter/*.xml` | Thermal controller calibration (loaded by Meerstetter on first run) |

---

## PCR Profile Format

Profiles live in `profiles/` (JSON). Each step is one of:

```json
{ "setpoint": 95, "duration": 30 }         // temperature hold
{ "ramp_rate": 3.0 }                        // ramp to next setpoint
{ "enable": 0, "duration": 5 }             // lid heater on
{ "disable": 0, "duration": 5 }            // lid heater off
{ "pcr_fanon": 1 }                          // cooling fan on
```

Stages with cycles use a `repeat` wrapper:
```json
{ "repeat": [...steps], "cycles": 40 }
```

---

## UI State Machine

States are defined in `config_files/state_config.json` and drive which HTML screen is shown:

| State | Screen | Meaning |
|-------|--------|---------|
| 0 | `init` | Initializing |
| 1 | `ready` | Ready to run |
| 2 | `running` | Test in progress |
| 3 | `complete` | Test complete |
| −1 | `init` | Instrument error |
| −3 | `init` | Keyboard interrupt |

---

## PCR Curve Analysis

`sentri_curve/curve.py` processes raw fluorescence data:

1. Extract optical reads per cycle per tube per dye
2. Baseline correction: subtract mean of cycles 5–15
3. Cross-talk removal: apply 4×2×2 correction matrix
4. Threshold detection: default 0.2 per dye
5. Cq calculation: linear regression around threshold crossing

`sentri_curve/evaluator.py` calls Detected / Inconclusive / Not Detected per tube.

---

## Deployment

`deployment2.sh` runs phases sequentially on the Pi:

| Phase | What it does |
|-------|-------------|
| 1 | OS packages (Chromium, Openbox, Xorg, WebKit) |
| 2 | Hardware interfaces (I2C, SPI via raspi-config) |
| 3 | Docker + Docker Compose |
| 4 | LightDM autologin (X11/Openbox), Xorg GPU fix |
| 5 | Chromium kiosk (Openbox autostart) |
| 6 | Display and touch tools |
| 7 | Persistent directories (`/opt/aquila/`) |
| 8 | Device identity + all config files |
| 9 | GHCR login, download compose file, pull images |
| 10 | Register `aquila-stack` systemd service |
| 11 | Start Docker stack, Meerstetter first-time tuning |
| 11b | Kiosk control service |
| 12 | Tailscale VPN |
| 13 | Grafana Alloy monitoring |
| 14 | Quiet boot (tty3) |
| 15 | Security hardening (lock config, restrict sudo) |

---

## Security Model

- `/opt/aquila/config/` is `chmod 700`, files `chmod 600` — root-only
- `pi` user has no `sudo` access except: `docker compose *`, `systemctl restart/status aquila-stack`, `systemctl restart/status kiosk-control`
- Root access is via Tailscale SSH (authenticated through Tailscale account, not local credentials)
- Watchtower uses a per-device `WATCHTOWER_HTTP_API_TOKEN` (rotated per device)

---

## Monitoring

Grafana Alloy (installed on host, not in Docker) handles:
- **Metrics**: node exporter → Grafana Cloud Prometheus
- **Logs**: systemd journal + `/var/log/*.log` → Grafana Cloud Loki

Config lives in `/etc/alloy/config.alloy`, managed by `scripts/setup_grafana_alloy_rpi.sh`.

---

## Testing

| Location | Type | When |
|----------|------|------|
| `tests/contract/` | FastAPI TestClient endpoint tests | CI |
| `tests/fleet_device/` | Shell script content validation | CI |
| `unit_tests/` | Curve math, validation logic | CI |
| `tests/e2e/` | Playwright browser tests | Manual (needs running server) |
| `@pytest.mark.hardware` | Real device tests | Pi only |

Run all CI-compatible tests:
```bash
pytest tests unit_tests -v
```
