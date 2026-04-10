# Deployment2 Architecture Plan
## Docker-Based Device Deployment

---

## Overview

The goal is to move all application code off the device and into Docker containers.
A single `deployment2.sh` script is the only file that needs to be downloaded to a new device.
All app updates are delivered by pulling new container images via Watchtower — no git, no SSH required for updates.

---

## What Runs in Containers vs Host

| Component | Where | Why |
|---|---|---|
| `aquila-backend` (FastAPI/uvicorn :8090) | Container | No hardware access, pure HTTP — safe to auto-update |
| `aquila-app` (application.py) | Container (same image as backend) | All Python code shared; needs `privileged: true` + device passthrough |
| `aquila-ui` (nginx + static files) | Container | Separate update cadence from Python backend |
| `watchtower` | Container | Auto-pulls new images on schedule or webhook |
| Chromium kiosk | Host | Wayland socket is user-session-scoped, not exposable to Docker |
| kanshi (display rotation) | Host | Session-level, trivial config, no value containerizing |
| labwc autostart | Host | Session-level, managed once by deployment2.sh |
| lightdm autologin | Host | OS-level, must stay on host |

### One Image, Two Containers

`aquila-backend` and `aquila-app` both use the same Docker image (built from `Dockerfile.api`).
They share all Python code (`aq_lib/`, `aq_curve/`, `config.py`, `profiles/`).
The difference is the `command:` override in docker-compose:

- `aquila-backend` → `uvicorn main:app --host 0.0.0.0 --port 8090`
- `aquila-app` → `python3 application.py`

---

## Persistent Directory Structure on Device

`deployment2.sh` builds this entire structure from scratch. Everything survives container updates.

```
/opt/aquila/                          ← all app data
├── config/
│   ├── device.env                    ← device identity (DEVICE_HOSTNAME, IMAGE_TAG, WATCHTOWER_TOKEN)
│   ├── host_config.json              ← hardware config (motor steps, GPIO, ADC) — standardized, same on all devices
│   └── state_config.json             ← UI state machine screen definitions — same on all devices
├── profiles/                         ← PCR thermal profiles (read-write, editable via web UI)
├── results/
│   └── results.json                  ← live run output written by firmware
└── logs/
    ├── results/                      ← run result JSON files
    ├── plots/                        ← optics PNG plots
    ├── pcr/                          ← PCR temperature logs
    ├── optics/                       ← optics capture logs
    └── lid_heater/                   ← lid heater logs

/opt/fleet/                           ← compose stack management
├── docker-compose.yml                ← downloaded from GitHub, NOT a git repo
├── .env                              ← IMAGE_TAG, DEVICE_HOSTNAME (Compose variable substitution)
└── update.sh                         ← written by deployment2.sh, runs manually to update stack
```

### How deployment2.sh Builds This Structure

The script creates every directory with `mkdir -p` and writes every file via heredoc or inline Python.
Nothing is copied from a local repo — everything is either generated or downloaded from GitHub raw URLs.

```
deployment2.sh
│
├── mkdir -p /opt/aquila/config
├── mkdir -p /opt/aquila/profiles
├── mkdir -p /opt/aquila/results
├── mkdir -p /opt/aquila/logs/results
├── mkdir -p /opt/aquila/logs/plots
├── mkdir -p /opt/aquila/logs/pcr
├── mkdir -p /opt/aquila/logs/optics
├── mkdir -p /opt/aquila/logs/lid_heater
└── mkdir -p /opt/fleet
```

Each file written by the script:

| File | How It's Written | Contents |
|---|---|---|
| `/opt/aquila/config/device.env` | bash heredoc | `DEVICE_HOSTNAME`, `IMAGE_TAG`, `GHCR_REPO`, `WATCHTOWER_HTTP_API_TOKEN` |
| `/opt/aquila/config/host_config.json` | bash heredoc | Standardized hardware config (motor steps, GPIO, ADC) — same values on all devices |
| `/opt/aquila/config/state_config.json` | bash heredoc | UI state machine screen definitions — static, same on all devices |
| `/opt/fleet/.env` | bash heredoc | `IMAGE_TAG`, `DEVICE_HOSTNAME` for Docker Compose variable substitution |
| `/opt/fleet/docker-compose.yml` | `curl` from GitHub raw URL | Always gets latest from repo |
| `/opt/fleet/update.sh` | bash heredoc | Shell script to pull latest compose + images |
| `~/.config/autostart/chromium-kiosk.desktop` | bash heredoc | Chromium kiosk launch config |
| `~/.config/kanshi/config` | bash heredoc | Display rotation (HDMI-A-2, transform 270) |
| `~/.config/labwc/autostart` | bash heredoc | `kanshi &` |
| `/etc/lightdm/lightdm.conf.d/autologin.conf` | bash heredoc | `autologin-session=rpd-labwc` |
| `/etc/systemd/system/aquila-stack.service` | bash heredoc | Starts `docker compose up -d` on boot |

### Config Path

`Config()` reads from the path set by `CONFIG_DIR` env var, defaulting to `config_files` for local dev.
In Docker, `CONFIG_DIR=/opt/aquila/config` is set in the compose environment, pointing to the host-mounted volume.
The deployment script writes `host_config.json` and `state_config.json` to `/opt/aquila/config/` on the device.

---

## Docker Compose Service Layout

The telemetry stack (node-exporter, vmagent, vector) is being removed — not used.

| Service | Container name | Port | Notes |
|---|---|---|---|
| `backend` | `aquila-backend` | `8090:8090` | FastAPI/uvicorn |
| `app` | `aquila-app` | — | `python3 application.py`, `hostname: ${DEVICE_HOSTNAME}` |
| `ui` | `aquila-ui` | `8080:80` | nginx static files |
| `watchtower` | `aquila-watchtower` | `8081:8080` | webhook trigger on 8081 |
| ~~`node-exporter`~~ | — | — | **REMOVED** |
| ~~`vmagent`~~ | — | — | **REMOVED** |
| ~~`vector`~~ | — | — | **REMOVED** |

### DEVICE_HOSTNAME Pattern (confirmed from current compose)

`aquila-app` sets `hostname: ${DEVICE_HOSTNAME}` so that `socket.gethostname()` inside the container
returns the device serial (e.g. `sn03`) rather than the container ID. `DEVICE_HOSTNAME` is loaded
from `device.env` via `env_file:`. This is the existing pattern — keep as-is.

---

## deployment2.sh — Full Phase Breakdown

`deployment2.sh` is the only file downloaded to a new device. It can be invoked with no arguments:

```bash
bash deployment2.sh
```

### Interactive Prompts

The script prompts for required values **at the point they are needed**, not all upfront.
You should not need to know everything before running the script.
Each phase asks for what it needs, when it needs it. Example flow:

```
[Phase 8] Enter device hostname (e.g. sn04): _
[Phase 8] Enter IMAGE_TAG (dev/pilot/prod): _
[Phase 8] Enter lid heater upper bound voltage (e.g. 0.34): _
[Phase 8] Enter lid heater lower bound voltage (e.g. 0.20): _
[Phase 9] Enter GHCR username: _
[Phase 9] Enter GHCR personal access token: _
[Phase 12] Enter Tailscale auth key (or press Enter to authenticate interactively): _
[Phase 13] Enter Grafana RW API key: _
```

Values can also be passed as env vars to skip prompts:
```bash
DEVICE_HOSTNAME=sn04 IMAGE_TAG=prod bash deployment2.sh
```

### Step Feedback

Every phase must echo its result clearly:
```
✓ Phase 1 complete — OS packages installed
✗ Phase 3 FAILED — Docker install failed (exit code 1). Check network and retry.
```

Rules:
- Print `✓ Phase N complete — <what was done>` on success
- Print `✗ Phase N FAILED — <reason>` on failure, then exit with a non-zero code
- Each phase is wrapped in error handling so a failure stops the script immediately
  rather than silently continuing to the next phase

### Test Design

The specific verification commands for each phase are defined in [`deployment2_tests.md`](deployment2_tests.md).
Each phase section below includes a **Verification** block showing the expected `✓`/`✗` echo output.
The script runs these tests automatically at the end of every phase — they are not optional.

Test format in the script:
```bash
run_phase_tests() {
  local phase=$1; shift
  for test_cmd in "$@"; do
    if eval "${test_cmd}"; then
      : # pass
    else
      echo "✗ Phase ${phase} FAILED — ${test_cmd}"
      exit 1
    fi
  done
  echo "✓ Phase ${phase} complete"
}
```

---

---

### Phase 1 — OS Prerequisites and Host Packages

```bash
apt-get update && apt-get upgrade -y

# Core utilities
apt-get install -y curl ca-certificates gnupg gettext-base python3

# Wayland display + kiosk browser
apt-get install -y chromium kanshi

# Kiosk fallback (kiosk.py via GTK/WebKit — kept as backup)
apt-get install -y python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0

# X11 tools (unclutter for cursor hiding, xterm for debugging)
apt-get install -y --no-install-recommends xterm unclutter
```

> **Key difference from deployment1:** No Python venv, no `pip install`, no `requirements.txt`
> on the host. All Python code and dependencies live inside the Docker container image.
> The host only needs packages for the kiosk display (Chromium + GTK fallback) and system tools.

#### What is NOT installed on the host (unlike deployment1)
| deployment1 | deployment2 | Reason |
|---|---|---|
| `python3-venv` + venv setup | Not needed | Python runs in container |
| `pip install -r requirements.txt` | Not needed | Dependencies baked into image |
| `xserver-xorg`, `openbox` | Not needed | Using Wayland (rpd-labwc), not X11 |
| `nodejs`, `npm`, `serve` | Not needed | serve.service removed |
| `aquila_app.service` | Not needed | Replaced by Docker Compose |
| `aquila_web.service` | Not needed | Replaced by Docker Compose |

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 1](deployment2_tests.md#phase-1--os-prerequisites-and-host-packages)
```
✓ Phase 1 complete — all host packages installed
✗ Phase 1 FAILED — chromium not found after install. Check apt sources.
```

---

### Phase 2 — Enable Hardware Interfaces
```
raspi-config nonint do_i2c 0        # /dev/i2c-1 for ADS1115 lid temp sensor
raspi-config nonint do_spi 0        # /dev/spidev0.0 for optical ADC
```
These write to `/boot/firmware/config.txt` and take effect after reboot.

#### Verification (runs automatically at end of phase — post-reboot)
> Full test definitions: [deployment2_tests.md — Phase 2](deployment2_tests.md#phase-2--hardware-interfaces-i2c--spi)
```
✓ Phase 2 complete — I2C and SPI enabled, /dev/i2c-1 and /dev/spidev0.0 present
✗ Phase 2 FAILED — /dev/i2c-1 not found. Reboot may be required.
```

---

### Phase 3 — Install Docker
```
curl -fsSL https://get.docker.com | sh
usermod -aG docker pi
apt-get install -y docker-compose-plugin
systemctl enable docker
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 3](deployment2_tests.md#phase-3--docker)
```
✓ Phase 3 complete — Docker installed and running, pi in docker group
✗ Phase 3 FAILED — Docker service not active. Check: sudo systemctl status docker
```

---

### Phase 4 — Configure Autologin (Wayland)
Creates `/etc/lightdm/lightdm.conf.d/autologin.conf`:
```ini
[Seat:*]
autologin-user=pi
autologin-session=rpd-labwc
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 4](deployment2_tests.md#phase-4--autologin-wayland)
```
✓ Phase 4 complete — LightDM configured for rpd-labwc autologin
✗ Phase 4 FAILED — autologin.conf missing or has wrong session value
```

---

### Phase 5 — Chromium Kiosk
Creates `~/.config/autostart/chromium-kiosk.desktop`:
```ini
[Desktop Entry]
Type=Application
Exec=chromium --kiosk --noerrdialogs --disable-infobars --ozone-platform=wayland --password-store=basic http://localhost:8090
Hidden=false
NoDisplay=false
Name=Chromium Kiosk
```
Notes: no quotes around URL, `--password-store=basic` requires two dashes.

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 5](deployment2_tests.md#phase-5--chromium-kiosk)
```
✓ Phase 5 complete — Chromium kiosk .desktop file configured correctly
✗ Phase 5 FAILED — --ozone-platform=wayland flag missing from .desktop file
```

---

### Phase 6 — Display Rotation (kanshi)
Creates `~/.config/kanshi/config` (4 spaces indent, NOT single line):
```
profile {
    output HDMI-A-2 enable mode 1024x768@60.004 position 0,0 transform 270
}

profile {
    output HDMI-A-1 enable mode 1024x768@60.004 position 0,0 transform 270
}
```
Creates `~/.config/labwc/autostart`:
```
kanshi &
```
Sets correct ownership: `chown -R pi:pi /home/pi/.config/`

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 6](deployment2_tests.md#phase-6--display-rotation-kanshi)
```
✓ Phase 6 complete — kanshi config valid, labwc autostart configured
✗ Phase 6 FAILED — kanshi config is single-line (must be multiline with 4-space indent)
```

---

### Phase 7 — Build Persistent Directory Structure
```bash
mkdir -p /opt/aquila/config
mkdir -p /opt/aquila/profiles
mkdir -p /opt/aquila/results
mkdir -p /opt/aquila/logs/results
mkdir -p /opt/aquila/logs/plots
mkdir -p /opt/aquila/logs/pcr
mkdir -p /opt/aquila/logs/optics
mkdir -p /opt/aquila/logs/lid_heater
mkdir -p /opt/fleet
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 7](deployment2_tests.md#phase-7--persistent-directory-structure)
```
✓ Phase 7 complete — all persistent directories created
✗ Phase 7 FAILED — /opt/aquila/logs/optics missing
```

---

### Phase 8 — Write Device Identity Files

`/opt/aquila/config/device.env`:
```bash
DEVICE_ID=<DEVICE_HOSTNAME>
DEVICE_HOSTNAME=<DEVICE_HOSTNAME>
IMAGE_TAG=<IMAGE_TAG>
GHCR_REPO=<GHCR_REPO>
RUN_MODE=prod
WATCHTOWER_HTTP_API_TOKEN=<generated with openssl rand -hex 32>
```

`/opt/fleet/.env` (for Docker Compose variable substitution):
```bash
IMAGE_TAG=<IMAGE_TAG>
DEVICE_HOSTNAME=<DEVICE_HOSTNAME>
DEVICE_ENV_FILE=/opt/aquila/config/device.env
```

`/opt/aquila/config/lid_heater_config.json`:
```json
{
    "lower_bound": <LID_HEATER_LOWER_BOUND>,
    "upper_bound": <LID_HEATER_UPPER_BOUND>
}
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 8](deployment2_tests.md#phase-8--device-identity-files)
```
✓ Phase 8 complete — device.env and fleet .env written
✗ Phase 8 FAILED — WATCHTOWER_HTTP_API_TOKEN not set in device.env
```

---

### Phase 9 — GHCR Login, Download Compose File, and Pull Images

The script prompts for GHCR credentials here if not already set as env vars.

```bash
# Prompt if not set
[Phase 9] Enter GHCR username: _
[Phase 9] Enter GHCR personal access token: _

# Login to GHCR
echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin

# Download boot config (private repo requires token)
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
  "https://raw.githubusercontent.com/${GHCR_REPO}/main/config.txt" \
  -o /boot/firmware/config.txt

# Download Meerstetter TEC config(s)
curl -fsSL -H "Authorization: token ${GHCR_TOKEN}" \
  "https://raw.githubusercontent.com/${GHCR_REPO}/main/config_files/meerstetter/24NOV25.SN1.Config.w.PT1000.cal.1.xml" \
  -o /opt/aquila/config/meerstetter/24NOV25.SN1.Config.w.PT1000.cal.1.xml

# Download compose file from GitHub (no git clone needed)
curl -fsSL "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
  -o /opt/fleet/docker-compose.yml

# Pull all images for the selected ring (IMAGE_TAG set in Phase 8)
docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml pull
```

**`/opt/fleet/update.sh`** — written by the script for future manual updates:
```bash
#!/usr/bin/env bash
curl -fsSL "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
  -o /opt/fleet/docker-compose.yml
docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml pull
docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml up -d
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 9](deployment2_tests.md#phase-9--docker-images)
```
✓ Phase 9 complete — GHCR login confirmed, docker-compose.yml downloaded, all images pulled
✗ Phase 9 FAILED — GHCR login not found in /root/.docker/config.json. Check credentials.
```

---

### Phase 10 — Register systemd Service

Creates `/etc/systemd/system/aquila-stack.service`:
```ini
[Unit]
Description=Aquila Docker Compose Stack
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/fleet
ExecStart=/usr/bin/docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload
systemctl enable aquila-stack.service
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 10](deployment2_tests.md#phase-10--systemd-service)
```
✓ Phase 10 complete — aquila-stack.service registered and enabled
✗ Phase 10 FAILED — aquila-stack.service not enabled. Run: systemctl daemon-reload && systemctl enable aquila-stack.service
```

---

### Phase 11 — Fleet Device Configuration

Start the stack using the IMAGE_TAG and credentials set in earlier phases. No additional prompts.

```bash
docker compose --env-file /opt/fleet/.env \
  -f /opt/fleet/docker-compose.yml up -d
```

Once the backend is healthy, apply the initial Meerstetter tuning parameters (runs inside the `aquila-app` container):

```bash
docker exec -e CONFIG_DIR=/opt/aquila/config aquila-app python3 - <<'PY'
from aq_lib.config_module import Config
from aq_lib.meerstetter import MeerStetter

config = Config()
device_type = int(config.pcr["device_type"])
pid = int(config.pcr["pid"], 16)
vid = int(config.pcr["vid"], 16)
device = MeerStetter.find_meer(vid, pid, device_type)
if not device:
    raise SystemExit("Meerstetter device not found")

meer = MeerStetter(device, baudrate=57600, timeout=1)
meer.set_parid_long(2000, 1, 1)
meer.set_parid_float(3002, 3.0)
meer.set_parid_float(3010, 80.0)
meer.set_parid_float(3011, 5.0)
meer.set_parid_float(3012, 4.0)
meer.set_parid_float(3013, 0.0)
meer.set_parid_float(3030, 9.0)
meer.set_parid_float(3033, 73.0)
meer.set_parid_float(3040, 1.0)
meer.set_parid_long(108, 1, 1)
meer.close()
print("Meerstetter tuning applied")
PY
```

Watchtower will watch the running containers and automatically pull new images for the same tag (dev/pilot/prod) whenever they are pushed to GHCR.

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 11](deployment2_tests.md#phase-11--fleet-device-configuration)
```
✓ Phase 11 complete — all 4 containers running, backend reachable on :8090, watchtower webhook responding
✗ Phase 11 FAILED — aquila-app not running. Check: docker logs aquila-app
```

---

### Phase 12 — Tailscale Setup (per device)

#### Step 5 — Install and Authenticate Tailscale
Generate a Linux server install script or pre-auth key from the Tailscale admin console, then run it on the device.

**With a pre-auth key:**
```bash
sudo tailscale up --ssh --authkey <key> --hostname <device-id>
```

**Without a pre-auth key:**
```bash
sudo tailscale up --ssh
# Follow the login link shown in terminal
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 12](deployment2_tests.md#phase-12--tailscale)
```
✓ Phase 12 complete — Tailscale active, device authenticated as <DEVICE_HOSTNAME>
✗ Phase 12 FAILED — Tailscale not authenticated. Run: sudo tailscale up --ssh
```

---

### Phase 13 — Grafana Alloy Setup (observability)

#### Step 6 — Export Grafana Cloud Environment Variables and Install
```bash
GCLOUD_HOSTED_METRICS_ID="3026216" \
GCLOUD_HOSTED_METRICS_URL="https://prometheus-prod-56-prod-us-east-2.grafana.net/api/prom/push" \
GCLOUD_HOSTED_LOGS_ID="1508783" \
GCLOUD_HOSTED_LOGS_URL="https://logs-prod-036.grafana.net/loki/api/v1/push" \
GCLOUD_FM_URL="https://fleet-management-prod-008.grafana.net" \
GCLOUD_FM_POLL_FREQUENCY="60s" \
GCLOUD_FM_HOSTED_ID="1550994" \
ARCH="arm64" \
GCLOUD_RW_API_KEY=<grafana-rw-api-key> \
/bin/sh -c "$(curl -fsSL https://storage.googleapis.com/cloud-onboarding/alloy/scripts/install-linux.sh)"

bash scripts/setup_grafana_alloy_rpi.sh
```
> **Note:** `GCLOUD_RW_API_KEY` is a secret — store it securely, do not commit to the repo.

#### Step 7 — Verify Alloy is Running
```bash
sudo systemctl restart alloy.service
sudo systemctl status alloy.service
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 13](deployment2_tests.md#phase-13--grafana-alloy)
```
✓ Phase 13 complete — Grafana Alloy installed and running
✗ Phase 13 FAILED — alloy.service not active. Check: sudo systemctl status alloy.service
```

---

### Phase 14 — Quiet Boot
```bash
sed -i 's/console=tty1/console=tty3/' /boot/cmdline.txt
```

#### Verification (runs automatically at end of phase)
> Full test definitions: [deployment2_tests.md — Phase 14](deployment2_tests.md#phase-14--quiet-boot)
```
✓ Phase 14 complete — quiet boot configured (tty3)
✗ Phase 14 FAILED — console=tty1 still present in /boot/cmdline.txt
```

---

### Phase 15 — Print Instructions and Reboot
```
==================================================
Deployment complete for device: <DEVICE_HOSTNAME>

IMPORTANT: On first boot, physically push the drawer
back to the home sensor before powering on.
==================================================
Rebooting in 5 seconds...
```

---

## Update Flow (Zero-Touch via Watchtower)

1. Developer pushes new image to GHCR
2. Watchtower polls every 300s OR receives webhook: `POST http://<device>:8081/v1/update`
   with header `Authorization: Bearer <WATCHTOWER_HTTP_API_TOKEN>`
3. Watchtower pulls new image → stops old container → starts new one
4. `aquila-app` re-homes motors on startup (expected, existing behavior)
5. No SSH, no git, no files touched on device

### Manual Stack Update (Compose Structure Changes)
```bash
ssh pi@<device> bash /opt/fleet/update.sh
```

---

---

## What Is NOT on the Device After deployment2.sh

- No git repo (`aquilla-main` directory does not exist)
- No Python venv (Python lives inside the container image)
- No `serve.service`, `aquila_app.service`, or `aquila_web.service`
- No telemetry stack (node-exporter, vmagent, vector)
- Replaced by: `aquila-stack.service` → `docker compose up -d`
