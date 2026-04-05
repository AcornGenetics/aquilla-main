#!/usr/bin/env bash
# deployment2.sh — Aquila device deployment
# Usage: sudo bash deployment2.sh
# All values can be pre-set as env vars to skip prompts:
#   DEVICE_HOSTNAME=sn04 IMAGE_TAG=prod GHCR_USER=... GHCR_TOKEN=... sudo bash deployment2.sh
set -euo pipefail

# ── Preflight ─────────────────────────────────────────────────────────────────
[[ "${EUID}" -ne 0 ]] && { echo "Run as root: sudo bash deployment2.sh"; exit 1; }

PI_HOME="/home/pi"
GHCR_REPO="${GHCR_REPO:-acorngenetics/aquilla-main}"

# ── Helpers ───────────────────────────────────────────────────────────────────
PHASE=""

phase_start() {
    PHASE=$1
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " Phase ${PHASE} — $2"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

phase_pass() {
    echo "✓ Phase ${PHASE} complete — $1"
}

phase_fail() {
    echo "✗ Phase ${PHASE} FAILED — $1"
    exit 1
}

prompt_if_unset() {
    local var=$1 msg=$2 secret=${3:-false}
    [[ -n "${!var:-}" ]] && return
    if [[ "${secret}" == "true" ]]; then
        read -rsp "[Phase ${PHASE}] ${msg}: " "${var}"; echo ""
    else
        read -rp  "[Phase ${PHASE}] ${msg}: " "${var}"
    fi
}

run_test() {
    local desc=$1 cmd=$2
    if eval "${cmd}" >/dev/null 2>&1; then
        echo "  ✓ ${desc}"
    else
        phase_fail "${desc}"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — OS Prerequisites and Host Packages
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 1 "OS Prerequisites and Host Packages"

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl ca-certificates gnupg gettext-base python3 \
    chromium kanshi \
    python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0 \
    xterm unclutter

run_test "curl installed"       "which curl"
run_test "chromium installed"   "which chromium"
run_test "kanshi installed"     "which kanshi"
run_test "python3 installed"    "which python3"
run_test "python3-gi available" "python3 -c 'import gi'"
run_test "WebKit2 available"    "dpkg -l libwebkit2gtk-4.1-0 | grep -q '^ii'"

phase_pass "all host packages installed"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Hardware Interfaces (I2C + SPI)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 2 "Hardware Interfaces (I2C + SPI)"

raspi-config nonint do_i2c 0
raspi-config nonint do_spi 0

run_test "I2C enabled in boot config" "grep -q 'dtparam=i2c_arm=on' /boot/firmware/config.txt"
run_test "SPI enabled in boot config" "grep -q 'dtparam=spi=on' /boot/firmware/config.txt"
run_test "/dev/i2c-1 exists"          "test -e /dev/i2c-1"
run_test "/dev/spidev0.0 exists"      "test -e /dev/spidev0.0"

phase_pass "I2C and SPI enabled, /dev/i2c-1 and /dev/spidev0.0 present"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Docker
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 3 "Docker"

if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose-plugin
usermod -aG docker pi
systemctl enable --now docker

run_test "Docker installed"         "docker --version"
run_test "Docker Compose installed" "docker compose version"
run_test "Docker service enabled"   "systemctl is-enabled docker | grep -q enabled"
run_test "Docker service running"   "systemctl is-active docker | grep -q active"
run_test "pi in docker group"       "groups pi | grep -q docker"

phase_pass "Docker installed and running, pi in docker group"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Autologin (Wayland)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 4 "Autologin (Wayland)"

mkdir -p /etc/lightdm/lightdm.conf.d
cat > /etc/lightdm/lightdm.conf.d/autologin.conf <<'EOF'
[Seat:*]
autologin-user=pi
autologin-session=rpd-labwc
EOF

run_test "autologin.conf exists"        "test -f /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "autologin-user=pi"           "grep -q 'autologin-user=pi' /etc/lightdm/lightdm.conf.d/autologin.conf"
run_test "autologin-session=rpd-labwc" "grep -q 'autologin-session=rpd-labwc' /etc/lightdm/lightdm.conf.d/autologin.conf"

phase_pass "LightDM configured for rpd-labwc autologin"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Chromium Kiosk
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 5 "Chromium Kiosk"

mkdir -p "${PI_HOME}/.config/autostart"
cat > "${PI_HOME}/.config/autostart/chromium-kiosk.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Exec=chromium --kiosk --noerrdialogs --disable-infobars --ozone-platform=wayland --password-store=basic --touch-events=enabled --enable-touch-drag-drop --disable-pinch --overscroll-history-navigation=0 --no-first-run --disable-session-crashed-bubble --check-for-update-interval=31536000 --incognito --disable-application-cache --disk-cache-dir=/tmp/chromium-cache --disk-cache-size=1 --media-cache-size=1 http://localhost:8090
Hidden=false
NoDisplay=false
Name=Chromium Kiosk
EOF
chown pi:pi "${PI_HOME}/.config/autostart/chromium-kiosk.desktop"

DESKTOP="${PI_HOME}/.config/autostart/chromium-kiosk.desktop"
run_test ".desktop file exists"        "test -f ${DESKTOP}"
run_test "Wayland flag present"        "grep -q -- '--ozone-platform=wayland' ${DESKTOP}"
run_test "password-store flag present" "grep -q -- '--password-store=basic' ${DESKTOP}"
run_test "URL not quoted"              "grep -qv '\"http' ${DESKTOP}"
run_test "Correct URL"                 "grep -q 'http://localhost:8090' ${DESKTOP}"

phase_pass "Chromium kiosk .desktop file configured correctly"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 6 — Display Rotation (kanshi)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 6 "Display Rotation (kanshi)"

mkdir -p "${PI_HOME}/.config/kanshi"
cat > "${PI_HOME}/.config/kanshi/config" <<'EOF'
profile {
    output HDMI-A-2 enable mode 1024x768@60.004 position 0,0 transform 270
}

profile {
    output HDMI-A-1 enable mode 1024x768@60.004 position 0,0 transform 270
}
EOF

mkdir -p "${PI_HOME}/.config/labwc"
cat > "${PI_HOME}/.config/labwc/autostart" <<'EOF'
kanshi &
EOF

chown -R pi:pi "${PI_HOME}/.config"

KANSHI_CONF="${PI_HOME}/.config/kanshi/config"
run_test "kanshi config exists"      "test -f ${KANSHI_CONF}"
run_test "kanshi config multiline"   "test \$(wc -l < ${KANSHI_CONF}) -gt 1"
run_test "HDMI-A-2 present"          "grep -q 'HDMI-A-2' ${KANSHI_CONF}"
run_test "transform 270 set"         "grep -q 'transform 270' ${KANSHI_CONF}"
run_test "labwc autostart exists"    "test -f ${PI_HOME}/.config/labwc/autostart"
run_test "kanshi in labwc autostart" "grep -q 'kanshi' ${PI_HOME}/.config/labwc/autostart"
run_test "correct file ownership"    "stat -c '%U' ${KANSHI_CONF} | grep -q pi"

phase_pass "kanshi config valid, labwc autostart configured"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Persistent Directory Structure
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 7 "Persistent Directory Structure"

mkdir -p /opt/aquila/config
mkdir -p /opt/aquila/profiles
mkdir -p /opt/aquila/results
mkdir -p /opt/aquila/logs/results
mkdir -p /opt/aquila/logs/plots
mkdir -p /opt/aquila/logs/pcr
mkdir -p /opt/aquila/logs/optics
mkdir -p /opt/aquila/logs/lid_heater
mkdir -p /opt/fleet

run_test "/opt/aquila/config"           "test -d /opt/aquila/config"
run_test "/opt/aquila/profiles"         "test -d /opt/aquila/profiles"
run_test "/opt/aquila/results"          "test -d /opt/aquila/results"
run_test "/opt/aquila/logs/results"     "test -d /opt/aquila/logs/results"
run_test "/opt/aquila/logs/plots"       "test -d /opt/aquila/logs/plots"
run_test "/opt/aquila/logs/pcr"         "test -d /opt/aquila/logs/pcr"
run_test "/opt/aquila/logs/optics"      "test -d /opt/aquila/logs/optics"
run_test "/opt/aquila/logs/lid_heater"  "test -d /opt/aquila/logs/lid_heater"
run_test "/opt/fleet"                   "test -d /opt/fleet"

phase_pass "all persistent directories created"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Device Identity and Config Files
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 8 "Device Identity and Config Files"

prompt_if_unset DEVICE_HOSTNAME "Enter device hostname (e.g. sn04)"
prompt_if_unset IMAGE_TAG       "Enter IMAGE_TAG (dev/pilot/prod)"
prompt_if_unset GHCR_USER       "Enter GHCR username"
prompt_if_unset GHCR_TOKEN      "Enter GHCR personal access token" true

WATCHTOWER_TOKEN="${WATCHTOWER_TOKEN:-$(openssl rand -hex 32)}"

# device.env
cat > /opt/aquila/config/device.env <<EOF
DEVICE_ID=${DEVICE_HOSTNAME}
DEVICE_HOSTNAME=${DEVICE_HOSTNAME}
IMAGE_TAG=${IMAGE_TAG}
GHCR_REPO=${GHCR_REPO}
RUN_MODE=prod
WATCHTOWER_HTTP_API_TOKEN=${WATCHTOWER_TOKEN}
GHCR_USERNAME=${GHCR_USER}
GHCR_TOKEN=${GHCR_TOKEN}
AQ_SRC_BASEDIR=/opt/aquila
EOF

# fleet .env (Compose variable substitution)
cat > /opt/fleet/.env <<EOF
IMAGE_TAG=${IMAGE_TAG}
DEVICE_HOSTNAME=${DEVICE_HOSTNAME}
GHCR_REPO=${GHCR_REPO}
DEVICE_ENV_FILE=/opt/aquila/config/device.env
EOF

# host_config.json — standardized across all devices (sn02 baseline)
cat > /opt/aquila/config/host_config.json <<'EOF'
{
    "info": {
        "dock_name": "aquila"
    },
    "pcr": {
        "comport": "/dev/ttyUSB0",
        "baudrate": 56700,
        "vid": "0x0403",
        "pid": "0x6001",
        "device_type": "1089",
        "pcr_profile": "profiles/verification_profile.json"
    },
    "optics": {
        "rox pin": 22,
        "fam pin": 27,
        "LED_ON": 0,
        "LED_OFF": 1
    },
    "drawer": {
        "open_steps": 4500,
        "close_steps": 0,
        "read_steps": 160,
        "home_steps": 5000,
        "step_multiplier": 32
    },
    "axis": {
        "home_steps": 2500,
        "step_multiplier": 8,
        "positions": [280, 640, 1010, 1365, 1720, 2075]
    },
    "adc": {
        "famP": 0,
        "famN": 1,
        "roxP": 2,
        "roxN": 3
    }
}
EOF

# state_config.json — static, same on all devices
cat > /opt/aquila/config/state_config.json <<'EOF'
{
    "-5": {
        "title": "EXIT?",
        "text": "Press Exit again to close the GUI",
        "screen": "init"
    },
    "-4": {
        "title": "EXIT",
        "text": "Closing GUI...",
        "screen": "init"
    },
    "-3": {
        "title": "KEYBOARD INTERRUPT",
        "text": "Restart run when ready",
        "screen": "init"
    },
    "-2": {
        "title": "STATE ERRROR",
        "text": "Invalid state requested, change state",
        "screen": "init"
    },
    "-1": {
        "title": "INSTRUMENT ERROR",
        "text": "Power cycle the instrument, if error persists contact Arete Biosciences",
        "screen": "init"
    },
    "0": {
        "title": "INITIALIZING",
        "text": "Please wait for instrument to complete initialization",
        "screen": "init"
    },
    "1": {
        "title": "READY TO RUN",
        "text": "Select profile then select \"Run\" to start",
        "screen": "ready"
    },
    "2": {
        "title": "TEST IN PROGRESS",
        "text": "Please wait for instrument to complete",
        "screen": "running"
    },
    "3": {
        "title": "TEST COMPLETE",
        "text": "Remove samples. Select \"Next Run\" to run again.",
        "screen": "complete"
    },
    "4": {
        "title": "READY TO RUN",
        "text": "No profile selected. Try again then press \"Run\" to start",
        "screen": "ready"
    },
    "5": {
        "title": "Run_assay.py not configured to loop back yet",
        "text": "to rerun use cmdline to run run_assay.py",
        "screen": "init"
    },
    "6": {
        "title": "READY TO RUN",
        "text": "Drawer Open selected.",
        "screen": "ready"
    },
    "7": {
        "title": "READY TO RUN",
        "text": "Drawer Close selected.",
        "screen": "ready"
    },
    "8": {
        "title": "TEST COMPLETE",
        "text": "Drawer Open Selected",
        "screen": "complete"
    },
    "9": {
        "title": "TEST COMPLETE",
        "text": "Drawer close Selected",
        "screen": "complete"
    }
}
EOF

run_test "device.env exists"          "test -f /opt/aquila/config/device.env"
run_test "DEVICE_HOSTNAME set"        "grep -q 'DEVICE_HOSTNAME=' /opt/aquila/config/device.env"
run_test "DEVICE_ID set"              "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
run_test "IMAGE_TAG set"              "grep -q 'IMAGE_TAG=' /opt/aquila/config/device.env"
run_test "WATCHTOWER_TOKEN set"       "grep -q 'WATCHTOWER_HTTP_API_TOKEN=' /opt/aquila/config/device.env"
run_test "GHCR username set"          "grep -q 'GHCR_USERNAME=' /opt/aquila/config/device.env"
run_test "GHCR token set"             "grep -q 'GHCR_TOKEN=' /opt/aquila/config/device.env"
run_test "/opt/fleet/.env exists"     "test -f /opt/fleet/.env"
run_test "host_config.json valid JSON" \
    "python3 -m json.tool /opt/aquila/config/host_config.json"
run_test "state_config.json valid JSON" \
    "python3 -m json.tool /opt/aquila/config/state_config.json"

phase_pass "device.env, fleet .env, host_config.json, and state_config.json written"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 9 — GHCR Login, Download Compose File, and Pull Images
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 9 "GHCR Login, Download Compose File, and Pull Images"

echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin
run_test "GHCR login succeeded" "grep -q 'ghcr.io' /root/.docker/config.json"

curl -fsSL \
    "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \
    -o /opt/fleet/docker-compose.yml

docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml pull

cat > /opt/fleet/update.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
curl -fsSL "https://raw.githubusercontent.com/${GHCR_REPO}/main/fleet-config/docker-compose.yml" \\
    -o /opt/fleet/docker-compose.yml
docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml pull
docker compose --env-file /opt/fleet/.env -f /opt/fleet/docker-compose.yml up -d
EOF
chmod +x /opt/fleet/update.sh

run_test "docker-compose.yml downloaded"   "test -f /opt/fleet/docker-compose.yml"
run_test "compose file non-empty"          "test -s /opt/fleet/docker-compose.yml"
run_test "backend image pulled"            "docker images | grep -q 'aquilla-main-api'"
run_test "ui image pulled"                 "docker images | grep -q 'aquilla-main-ui'"
run_test "update.sh exists and executable" "test -x /opt/fleet/update.sh"

phase_pass "docker-compose.yml downloaded, all images pulled"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 10 — Register systemd Service
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 10 "Register systemd Service"

cat > /etc/systemd/system/aquila-stack.service <<'EOF'
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
EOF

systemctl daemon-reload
systemctl enable aquila-stack.service

run_test "service file exists" "test -f /etc/systemd/system/aquila-stack.service"
run_test "service enabled"     "systemctl is-enabled aquila-stack.service | grep -q enabled"

phase_pass "aquila-stack.service registered and enabled"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 11 — Fleet Device Configuration (Start Stack)
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 11 "Fleet Device Configuration"

docker compose \
    --env-file /opt/fleet/.env \
    -f /opt/fleet/docker-compose.yml \
    up -d

echo "  Waiting for backend to become healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8090/health >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

echo "  Running Meerstetter first-time tuning..."
if ! docker exec \
    -e CONFIG_DIR=/opt/aquila/config \
    aquila-app \
    python3 - <<'PY'
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
meer.set_parid_long(108, 1, 0)
meer.read(100)
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
then
    phase_fail "Meerstetter tuning failed"
fi

WATCHTOWER_TOKEN=$(grep WATCHTOWER_HTTP_API_TOKEN /opt/aquila/config/device.env | cut -d= -f2)

run_test "DEVICE_ID set"            "grep -q 'DEVICE_ID=' /opt/aquila/config/device.env"
run_test "IMAGE_TAG is valid ring"   "grep -E 'IMAGE_TAG=(dev|pilot|prod)' /opt/aquila/config/device.env"
run_test "aquila-backend running"    \
    "docker ps --filter name=aquila-backend --format '{{.Status}}' | grep -q Up"
run_test "aquila-app running"        \
    "docker ps --filter name=aquila-app --format '{{.Status}}' | grep -q Up"
run_test "aquila-ui running"         \
    "docker ps --filter name=aquila-ui --format '{{.Status}}' | grep -q Up"
run_test "backend reachable :8090"   "curl -sf http://localhost:8090/health"
run_test "aquila-watchtower running" \
    "docker ps --filter name=aquila-watchtower --format '{{.Status}}' | grep -q Up"
run_test "watchtower webhook responds" \
    "curl -sf -o /dev/null -w '%{http_code}' -X POST http://localhost:8081/v1/update \
     -H 'Authorization: Bearer ${WATCHTOWER_TOKEN}' | grep -q 200"

phase_pass "fleet config set, containers running, backend reachable on :8090, watchtower webhook responding"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 12 — Tailscale
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 12 "Tailscale"

if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi

prompt_if_unset TAILSCALE_KEY \
    "Enter Tailscale auth key (press Enter to authenticate interactively)"

if [[ -n "${TAILSCALE_KEY:-}" ]]; then
    tailscale up --ssh --authkey "${TAILSCALE_KEY}" --hostname "${DEVICE_HOSTNAME}"
else
    tailscale up --ssh --hostname "${DEVICE_HOSTNAME}"
    echo "  → Complete Tailscale authentication in your browser, then press Enter to continue."
    read -r
fi

run_test "tailscale installed"     "which tailscale"
run_test "tailscaled active"       "systemctl is-active tailscaled | grep -q active"
run_test "device authenticated"    "tailscale status | grep -q ${DEVICE_HOSTNAME}"
run_test "Tailscale IPs assigned"  \
    "tailscale status --json | python3 -c \"import sys,json; d=json.load(sys.stdin); assert d.get('TailscaleIPs')\""

phase_pass "Tailscale active, device authenticated as ${DEVICE_HOSTNAME}"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 13 — Grafana Alloy
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 13 "Grafana Alloy"

prompt_if_unset GCLOUD_RW_API_KEY "Enter Grafana Cloud RW API key" true

GCLOUD_HOSTED_METRICS_ID="3026216" \
GCLOUD_HOSTED_METRICS_URL="https://prometheus-prod-56-prod-us-east-2.grafana.net/api/prom/push" \
GCLOUD_HOSTED_LOGS_ID="1508783" \
GCLOUD_HOSTED_LOGS_URL="https://logs-prod-036.grafana.net/loki/api/v1/push" \
GCLOUD_FM_URL="https://fleet-management-prod-008.grafana.net" \
GCLOUD_FM_POLL_FREQUENCY="60s" \
GCLOUD_FM_HOSTED_ID="1550994" \
ARCH="arm64" \
GCLOUD_RW_API_KEY="${GCLOUD_RW_API_KEY}" \
/bin/sh -c "$(curl -fsSL https://storage.googleapis.com/cloud-onboarding/alloy/scripts/install-linux.sh)"

systemctl enable alloy.service
systemctl restart alloy.service

run_test "alloy installed"       "which alloy"
run_test "alloy service active"  "systemctl is-active alloy.service | grep -q active"
run_test "alloy service enabled" "systemctl is-enabled alloy.service | grep -q enabled"

phase_pass "Grafana Alloy installed and running"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 14 — Quiet Boot
# ═══════════════════════════════════════════════════════════════════════════════
phase_start 14 "Quiet Boot"

if grep -q "console=tty1" /boot/cmdline.txt; then
    sed -i 's/console=tty1/console=tty3/' /boot/cmdline.txt
fi

run_test "tty3 in cmdline"     "grep -q 'console=tty3' /boot/cmdline.txt"
run_test "tty1 not in cmdline" "! grep -q 'console=tty1' /boot/cmdline.txt"

phase_pass "quiet boot configured (tty3)"

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 15 — Complete
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=================================================="
echo " Deployment complete for device: ${DEVICE_HOSTNAME}"
echo ""
echo " IMPORTANT: On first boot, physically push the"
echo " drawer back to the home sensor before powering on."
echo "=================================================="
echo ""
echo " Rebooting in 5 seconds... (Ctrl+C to cancel)"
sleep 5
reboot
