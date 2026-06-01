# Aquila DDD Bounded Contexts

**Date**: 2026-04-30  
**Status**: Current

This document defines the five bounded contexts of the Aquila qPCR system using Domain-Driven Design vocabulary.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Aquila System                                │
│                                                                     │
│  ┌──────────────────┐    ┌──────────────────┐                      │
│  │  Device Control  │───▶│  PCR Analysis    │                      │
│  │  (Hardware I/O)  │    │  (Curve Engine)  │                      │
│  └────────┬─────────┘    └────────┬─────────┘                      │
│           │ state events          │ results                         │
│           ▼                       ▼                                 │
│  ┌──────────────────────────────────────────┐                      │
│  │           Web / API                      │                      │
│  │    (FastAPI + WebSocket broker)          │                      │
│  └──────────────────────┬───────────────────┘                      │
│                         │ screen events / live data                 │
│                         ▼                                           │
│  ┌──────────────────┐    ┌──────────────────┐                      │
│  │   UI / Kiosk     │    │  Fleet Deploy    │                      │
│  │  (Browser, Touch)│    │  (OTA, Config)   │                      │
│  └──────────────────┘    └──────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. Device Control

**Purpose**: Manage all hardware I/O during a PCR run.

**Ubiquitous Language**

| Term | Meaning |
|------|---------|
| Thermal Profile | Ordered sequence of hold/ramp segments defining temperature over time |
| Setpoint | Target temperature sent to the TEC controller |
| Well | Individual sample chamber; 6 per cartridge |
| Cycle | One complete temperature iteration in the profile |
| Optical Read | ADC fluorescence capture (FAM + ROX channels) at a specific well position |
| Home | Motor reference position established at startup via endstop sensor |
| Stop Event | Thread-safe flag that halts the hardware loop cleanly mid-run |

**Aggregates**

- **AssayInterface** (root): Coordinates motors, thermal, optical, and lid subsystems for a single run.
- **Motor**: X-axis and Drawer; maintains step position, executes move commands.
- **ThermalBlock**: Wraps Meerstetter controller; executes hold/ramp segments.
- **LidHeater**: Separate PID-controlled heater for condensation prevention.
- **OpticalReader**: SPI ADC; captures FAM/ROX readings per well per cycle.

**Key Files**
- `state_run_assay.py` — AssayInterface aggregate root
- `aq_lib/motor_class.py` — Motor aggregate
- `aq_lib/meerstetter.py` — ThermalBlock infrastructure
- `aq_lib/thermal_engine.py` — thermal profile execution
- `adc_class.py` — OpticalReader
- `aq_lib/lid_temperature.py`, `aq_lib/regulate.py` — LidHeater

**Integrates with**
- Web/API: publishes run state via `state_requests.py` HTTP calls
- PCR Analysis: writes raw fluorescence CSV/JSON to `/opt/aquila/logs/results/`

---

## 2. PCR Analysis

**Purpose**: Transform raw fluorescence time-series data into validated qPCR results.

**Ubiquitous Language**

| Term | Meaning |
|------|---------|
| Cq (Ct) | Quantification Cycle; cycle number at which fluorescence crosses the threshold |
| Baseline | Background fluorescence level in early cycles before exponential amplification |
| Threshold | Fluorescence value above which amplification is considered detected |
| Log Phase | Exponential amplification region of the PCR curve |
| Crosstalk | Spectral bleed between FAM and ROX channels; corrected via calibration matrix |
| Positive Well | Well with detected amplification (Cq within valid range) |
| Negative Well | Well with no amplification (Cq absent or outside valid range) |

**Aggregates**

- **Curve** (root): Represents one well's fluorescence time-series with all corrections applied.
- **Evaluator**: Runs 8+ validation checks on a Curve and produces a quality verdict.
- **AnalysisService**: Loads a run's raw data, processes all wells, and writes results.
- **PlotRenderer**: Generates PNG visualizations from Curve data.

**Key Files**
- `aq_curve/curve.py` — Curve aggregate
- `aq_curve/evaluator.py` — Evaluator
- `aq_curve/analysis_service.py` — AnalysisService
- `aq_curve/plot_utils.py` — PlotRenderer
- `aq_curve/pcr_curve_config.py` — Analysis parameters (thresholds, R² cutoffs)

**Domain Events**
- `RunAnalysisComplete` → triggers results JSON write and plot generation
- `WellPositive` / `WellNegative` → classification per well

**Integrates with**
- Device Control: consumes raw fluorescence files written to `/opt/aquila/logs/results/`
- Web/API: results JSON and PNG paths are served via REST endpoints

---

## 3. Web / API

**Purpose**: Expose device capabilities via HTTP and WebSocket; serve as the integration hub between hardware, analysis, and UI.

**Ubiquitous Language**

| Term | Meaning |
|------|---------|
| Run | A single PCR execution identified by a unique run ID and name |
| Profile | A named thermal profile selectable by the operator |
| Screen State | The current UI page (ready / running / complete / error) |
| History | Ordered list of completed runs with result summaries |
| Live State | Real-time device telemetry pushed via WebSocket |

**Aggregates**

- **RunController**: Accepts run start/stop commands; mediates with hardware subprocess.
- **ProfileRegistry**: CRUD for PCR profiles stored in `/opt/aquila/profiles/`.
- **HistoryLog**: Appends completed runs; reads result files for summary display.
- **StateManager**: Holds current screen state; broadcasts WebSocket events on change.

**Key Files**
- `aquila_web/main.py` — All routes and WebSocket logic

**API Surface**
- `POST /run/` — start a run
- `POST /stop/` — stop current run
- `GET /profiles/` — list profiles
- `POST /change_screen/{state_id}` — transition UI state (called by hardware loop)
- `GET /history/` — completed runs list
- `GET /results/{run_id}` — run results JSON + plot paths
- `WS /ws` — real-time state push to browser

**Integrates with**
- Device Control: receives state change HTTP calls from hardware loop
- PCR Analysis: reads analysis output files for `/results/` endpoint
- UI/Kiosk: serves static files; pushes WebSocket events

---

## 4. UI / Kiosk

**Purpose**: Provide a touch-optimized operator interface for run control, live monitoring, and results review.

**Ubiquitous Language**

| Term | Meaning |
|------|---------|
| Kiosk Mode | Full-screen Chromium with no browser chrome; touch-only input |
| Screen | A distinct HTML section shown based on current state (Ready, Running, History) |
| Modal | Overlay displayed on run completion or error |
| Profile Selector | Dropdown for choosing a thermal profile before starting a run |
| On-Screen Keyboard | Custom JS keyboard for text input without physical keyboard |

**Components**

- **Run Screen** (`run.html`): Profile selector, start/stop button, live cycle/temperature display.
- **History Screen** (`history.html`): Expandable list of past runs with Cq summaries and plot images.
- **State Machine** (`script.js`): WebSocket listener; swaps visible sections on `screen_change` events.
- **Keyboard** (`keyboard.js`): On-screen text input component.
- **Kiosk Service** (`aquila-kiosk.service`): systemd unit; starts Chromium on boot with touch flags.

**Key Files**
- `aquila_web/static/run.html`
- `aquila_web/static/history.html`
- `aquila_web/static/script.js`
- `aquila_web/static/keyboard.js`
- `aquila_web/static/styles.css`

**Integrates with**
- Web/API: WebSocket connection to `ws://localhost:8090/ws`; REST calls for profiles, history, run control

---

## 5. Fleet Deployment / Device Management

**Purpose**: Provision, configure, update, and monitor the fleet of Aquila devices.

**Ubiquitous Language**

| Term | Meaning |
|------|---------|
| Device | A physical Aquila unit identified by hostname (e.g., `sn01`) |
| Fleet | The collection of all deployed devices |
| Provisioning | Initial setup of a device: OS, Docker, config files, credentials |
| OTA Update | Over-the-air software update delivered by pushing a new container image |
| Manifest | (Future) Signed JSON describing the target image tag for a device or ring |
| Ring | A subset of the fleet used for staged rollouts (canary → pilot → production) |
| Persistent Data | PCR results and logs in `/opt/aquila`; survives container updates |

**Components**

- **Deployment Script** (`deployment2.sh`): Idempotent provisioning; installs Docker, creates `/opt/aquila` and `/opt/fleet`, writes systemd services, pulls initial images.
- **Watchtower**: Sidecar container that polls GHCR and auto-updates application containers.
- **Fleet Config Store** (`/opt/fleet/`): Per-device env and hardware config; bind-mounted into containers.
- **Verify Script** (`deployment2_verify.sh`): Post-deployment health checks (container status, API ping, GPIO access).
- **CI/CD Pipeline** (`.github/workflows/`): Builds and pushes images to GHCR on merge to `main`.

**Key Files**
- `deployment2.sh` — primary provisioning script
- `deployment2_verify.sh` — post-deploy validation  
- `config_files/device.env` — per-device environment template
- `config_files/host_config.json` — per-device hardware parameters
- `docker/` — Dockerfiles
- `compose.yaml` — Docker Compose
- `.github/workflows/` — CI/CD

**Future Direction** (from `docs/deployment_plan.md`)
- AWS Lambda manifest API + DynamoDB device registry for fleet-wide visibility
- Signed rollout manifests for ring-based deployments
- Remote device health telemetry

---

## Context Map

| Relationship | Upstream | Downstream | Integration |
|---|---|---|---|
| Hardware → API | Device Control | Web/API | HTTP (`state_requests.py`) → REST |
| API → Hardware | Web/API | Device Control | REST `POST /run/` → subprocess/thread |
| Hardware → Analysis | Device Control | PCR Analysis | Filesystem (raw CSV/JSON in `/opt/aquila`) |
| Analysis → API | PCR Analysis | Web/API | Filesystem (results JSON/PNG in `/opt/aquila`) |
| API → UI | Web/API | UI/Kiosk | WebSocket push + REST |
| Fleet → All | Fleet Deploy | All | Docker image, bind-mounts, env vars |
